"""End-to-end logic harness for the disclosure review (stdlib only).

It imports the real src.utils.linear module and mirrors the production
orchestration in src.services.disclosure against in-memory tables: frozen
means, same-month equation system, rejection with implicated batches,
idempotent ledger posting and retries.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from src.utils.linear import solvable_columns  # noqa: E402


class Batch:
    def __init__(self, bid, code, month, values):
        self.id, self.code, self.month, self.values = bid, code, month, values


class App:
    def __init__(self, aid, month, batch_ids):
        self.id = aid
        self.month = month
        self.batch_ids = list(batch_ids)
        self.batch_codes = []
        self.status = "pending"
        self.published_sum = None
        self.ledger_key = None
        self.solvable_batches = []
        self.attempts = 0


class Harness:
    def __init__(self):
        self.batches = {}
        self.frozen = {}          # batch_id -> Decimal mean
        self.apps = {}
        self.published_keys = set()
        self._aid = 0

    def add_batch(self, code, month, values):
        bid = len(self.batches) + 1
        self.batches[bid] = Batch(bid, code, month, list(values))
        return bid

    def append_sample(self, bid, value):
        self.batches[bid].values.append(value)

    def _freeze(self, month):
        for bid, b in self.batches.items():
            if b.month == month and bid not in self.frozen:
                total = sum((Decimal(str(v)) for v in b.values), Decimal(0))
                self.frozen[bid] = total / Decimal(len(b.values))

    def _equation_rows(self, month, ordered):
        published = [a for a in self.apps.values()
                     if a.month == month and a.status == "published"]
        universe = list(ordered)
        for a in published:
            for bid in a.batch_ids:
                if bid not in universe:
                    universe.append(bid)
        index = {bid: i for i, bid in enumerate(universe)}
        rows = []
        for a in published:
            row = [0] * len(universe)
            for bid in a.batch_ids:
                row[index[bid]] = 1
            rows.append(row)
        return rows, universe, index

    def submit(self, month, batch_ids, fail_ledger_once=False):
        self._aid += 1
        app = App(self._aid, month, batch_ids)
        app.batch_codes = [self.batches[b].code for b in batch_ids]
        self.apps[app.id] = app
        self.judge(app.id, fail_ledger_once=fail_ledger_once)
        return app

    def judge(self, aid, fail_ledger_once=False):
        app = self.apps[aid]
        if app.status in ("rejected", "published"):
            return app
        app.attempts += 1
        app.status = "judging"
        self._freeze(app.month)
        rows, universe, index = self._equation_rows(app.month, app.batch_ids)
        candidate = [0] * len(universe)
        for bid in app.batch_ids:
            candidate[index[bid]] = 1
        exposed = solvable_columns(rows, candidate)
        if exposed:
            app.status = "rejected"
            app.solvable_batches = [
                {"batch_id": universe[c], "batch_code": self.batches[universe[c]].code}
                for c in exposed
            ]
            return app
        total = sum((self.frozen[bid] for bid in app.batch_ids), Decimal(0))
        key = f"disclosure:{app.month}:app-{app.id}"
        if key in self.published_keys:      # idempotent retry path
            app.status = "published"
            app.ledger_key = key
            return app
        if fail_ledger_once:
            app.status = "failed"
            return app
        self.published_keys.add(key)
        app.ledger_key = key
        app.published_sum = float(total)
        app.status = "published"
        return app

    def retry(self, aid):
        app = self.apps[aid]
        assert app.status == "failed"
        app.status = "pending"
        return self.judge(aid)


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def main():
    h = Harness()
    b1 = h.add_batch("QH-A", "2026-11", [70.0, 72.0])           # mean 71
    b2 = h.add_batch("QH-B", "2026-11", [74.0, 76.0])           # mean 75
    b3 = h.add_batch("QH-C", "2026-11", [80.0, 82.0])           # mean 81
    b4 = h.add_batch("QH-D", "2026-11", [60.0, 64.0, 62.0])     # mean 62

    # 1) First multi-batch request with no history is published, exact sum.
    a1 = h.submit("2026-11", [b1, b2])
    assert a1.status == "published", a1.status
    assert approx(a1.published_sum, 71.0 + 75.0), a1.published_sum

    # 2) A single-batch request always reveals that batch -> rejected.
    a2 = h.submit("2026-11", [b3])
    assert a2.status == "rejected"
    assert {x["batch_code"] for x in a2.solvable_batches} == {"QH-C"}
    assert a2.published_sum is None

    # 3) Difference attack: published b1+b2, asking b1+b2+b3 isolates b3.
    a3 = h.submit("2026-11", [b1, b2, b3])
    assert a3.status == "rejected", a3.status
    assert {x["batch_code"] for x in a3.solvable_batches} == {"QH-C"}

    # 4) Second pair b2+b3 alongside b1+b2 leaves one degree of freedom,
    #    null vector (-1,1,-1) has no zero coordinate -> no single exposed.
    a4 = h.submit("2026-11", [b2, b3])
    assert a4.status == "published", a4.status
    assert approx(a4.published_sum, 75.0 + 81.0)

    # 5) Completing the 3-batch circle with b1+b3 makes the system full rank.
    a5 = h.submit("2026-11", [b1, b3])
    assert a5.status == "rejected", a5.status
    assert {x["batch_code"] for x in a5.solvable_batches} == {"QH-A", "QH-B", "QH-C"}

    # 6) Freeze immutability: a later inspection must not move the frozen mean.
    h.append_sample(b1, 100.0)   # live mean would become ~80.67
    assert h.frozen[b1] == Decimal("71"), h.frozen[b1]
    # A single-batch request for a connected member exposes the whole connected
    # component (b1,b2,b3 linked by published pair sums), but not isolated b4.
    a6 = h.submit("2026-11", [b2])
    assert a6.status == "rejected", a6.status
    assert {x["batch_code"] for x in a6.solvable_batches} == {"QH-A", "QH-B", "QH-C"}
    # A fresh, not-yet-mentioned batch requested alone exposes only itself.
    a6b = h.submit("2026-11", [b4])
    assert a6b.status == "rejected"
    assert {x["batch_code"] for x in a6b.solvable_batches} == {"QH-D"}

    # 7) Ledger failure then retry along the same row: no duplicate posting.
    b6 = h.add_batch("QH-F", "2026-12", [77.0, 79.0])           # mean 78
    b7 = h.add_batch("QH-G", "2026-12", [69.0, 71.0])           # mean 70
    a8 = h.submit("2026-12", [b6, b7], fail_ledger_once=True)
    assert a8.status == "failed" and a8.published_sum is None
    keys_before = set(h.published_keys)
    a8r = h.retry(a8.id)
    assert a8r.status == "published"
    assert approx(a8r.published_sum, 78.0 + 70.0)
    assert a8r.ledger_key == f"disclosure:2026-12:app-{a8.id}"
    a8r.status = "failed"
    h.retry(a8.id)
    assert len([k for k in h.published_keys if k.endswith(f"app-{a8.id}")]) == 1
    assert h.published_keys == keys_before | {a8r.ledger_key}

    # 8) Months are isolated: November publications do not constrain December.
    b8 = h.add_batch("QH-H", "2026-12", [55.0])
    a9 = h.submit("2026-12", [b8])
    assert a9.status == "rejected"
    assert {x["batch_code"] for x in a9.solvable_batches} == {"QH-H"}

    # 9) A redundant re-request of an already published sum exposes nothing.
    c1 = h.add_batch("R-1", "2027-01", [1.0, 3.0])             # mean 2
    c2 = h.add_batch("R-2", "2027-01", [5.0, 7.0])             # mean 6
    r1 = h.submit("2027-01", [c1, c2])
    assert r1.status == "published"
    r2 = h.submit("2027-01", [c1, c2])
    assert r2.status == "published" and approx(r2.published_sum, 8.0)

    # 10) Rejected apps never enter the ledger and never expose values.
    assert all(a.published_sum is None for a in h.apps.values()
               if a.status == "rejected")
    assert all(a.ledger_key is None for a in h.apps.values()
               if a.status == "rejected")

    print("ALL DISCLOSURE HARNESS TESTS PASSED")
    print("published:", [(a.id, a.month, round(a.published_sum, 4))
                         for a in h.apps.values() if a.status == "published"])
    print("rejected :", [(a.id, [x["batch_code"] for x in a.solvable_batches])
                         for a in h.apps.values() if a.status == "rejected"])


if __name__ == "__main__":
    main()
