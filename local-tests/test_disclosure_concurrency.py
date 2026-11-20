"""Concurrency, lock and idempotency guarantees for disclosure judging.

The in-memory redis stub is single-threaded, so true parallelism is modelled
by pre-acquiring the shared ledger lock (busy path) and by processing a queue
of applications the way the worker pops them.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-tests" / "stubs" / "site"))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import Session, select  # noqa: E402
from src.models.entities import Batch, Inspection, DisclosureApplication  # noqa: E402
from src.services import disclosure  # noqa: E402
from src.services.disclosure import LEDGER_LOCK  # noqa: E402
from redis import Redis  # noqa: E402


class U:
    def __init__(self, email, role):
        self.email, self.role = email, role


analyst = U("analyst@demo.local", "analyst")


def seed(db, n=4):
    ids = []
    for i in range(n):
        db.add(Batch(code=f"C{i}", line="一线", supplier="s", tonnes=10.0,
                     received_date="2026-11-10"))
        db.commit()
        b = db.scalars(select(Batch)).all()[-1]
        db.add(Inspection(sample_code=f"C{i}-S1", batch_id=b.id,
                          flour_yield=70.0 + i, moisture=12.0, inspector="i"))
        db.commit()
        ids.append(b.id)
    return ids


def main():
    Session.registry.clear()
    db = Session()
    ids = seed(db)

    # ---- Busy-lock path: hold the ledger lock, judging must fail cleanly.
    holder = Redis.from_url("x").lock(LEDGER_LOCK, timeout=30, blocking_timeout=25)
    assert holder.acquire(blocking=True) is True
    app = disclosure.create_application(db, [ids[0], ids[1]], analyst)
    # The judge creates its own client; the stub shares the global _locks set
    # across instances, so it observes the held lock and refuses to block.
    result = disclosure.judge_application(app["id"])
    assert result is False
    row = db.get(DisclosureApplication, app["id"])
    assert row.status == "failed", row.status
    assert row.published_sum is None and row.ledger_key is None
    holder.release()

    # Retry after the lock frees -> published along the same original row.
    disclosure.retry_application(db, app["id"], analyst)
    assert disclosure.judge_application(app["id"]) is True
    row = db.get(DisclosureApplication, app["id"])
    assert row.status == "published"
    assert row.ledger_key == f"disclosure:2026-11:app-{app['id']}"
    assert abs(row.published_sum - (70.0 + 71.0)) < 1e-9

    # ---- Queue drain: many applications, each gets a distinct stable key.
    created = [app["id"]]
    for pair in ([ids[1], ids[2]], [ids[2], ids[3]], [ids[0], ids[3]]):
        created.append(disclosure.create_application(db, pair, analyst)["id"])
    for aid in created:
        disclosure.judge_application(aid)
    keys = []
    for aid in created:
        r = db.get(DisclosureApplication, aid)
        if r.ledger_key:
            keys.append(r.ledger_key)
    # Every posted ledger key is unique -> no application posted twice.
    assert len(keys) == len(set(keys))
    # No application ever carries more than one ledger key row.
    all_rows = db.scalars(select(DisclosureApplication)).all()
    posted = [r for r in all_rows if r.status == "published"]
    assert all(r.ledger_key for r in posted)
    assert len({r.ledger_key for r in posted}) == len(posted)

    # ---- Re-judging a terminal published app is idempotent (no new side effect).
    before = len(posted)
    assert disclosure.judge_application(app["id"]) is True
    after = [r for r in db.scalars(select(DisclosureApplication)).all()
             if r.status == "published"]
    assert len(after) == before
    same = db.get(DisclosureApplication, app["id"])
    assert same.ledger_key == f"disclosure:2026-11:app-{app['id']}"

    # ---- Rejected apps never get a ledger key even after repeated judging.
    rej_app = disclosure.create_application(db, [ids[0]], analyst)
    disclosure.judge_application(rej_app["id"])
    rr = db.get(DisclosureApplication, rej_app["id"])
    assert rr.status == "rejected" and rr.ledger_key is None and rr.published_sum is None
    assert disclosure.judge_application(rej_app["id"]) is True  # terminal no-op
    rr2 = db.get(DisclosureApplication, rej_app["id"])
    assert rr2.ledger_key is None

    print("CONCURRENCY / LOCK / IDEMPOTENCY TESTS PASSED")
    print("published count:", len(posted), "unique keys:", len({r.ledger_key for r in posted}))


if __name__ == "__main__":
    main()
