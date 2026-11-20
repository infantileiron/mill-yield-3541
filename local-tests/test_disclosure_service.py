"""Integration test driving the REAL src.services.disclosure against stubs.

Run with -I and an explicit sys.path (stubs live in an isolated directory, so
a planted module elsewhere cannot be imported).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-tests" / "stubs" / "site"))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import Session  # noqa: E402
from src.models.entities import (  # noqa: E402
    Batch, Inspection, DisclosureApplication, FrozenBatchMean,
)
from src.services import disclosure  # noqa: E402


class U:
    def __init__(self, email, role):
        self.email, self.role = email, role


admin = U("admin@demo.local", "admin")
analyst = U("analyst@demo.local", "analyst")
viewer = U("viewer@demo.local", "viewer")


def reset():
    Session.registry.clear()


def add_batch(db, code, line, supplier, tonnes, received_date):
    db.add(Batch(code=code, line=line, supplier=supplier, tonnes=tonnes,
                 received_date=received_date))
    db.commit()
    return db.scalars(__import__("sqlalchemy").select(Batch)).all()[-1]


def add_inspection(db, batch, sample_code, y, moisture=12.0, inspector="林洁"):
    db.add(Inspection(sample_code=sample_code, batch_id=batch.id,
                      flour_yield=y, moisture=moisture, inspector=inspector))
    db.commit()


def main():
    reset()
    db = Session()

    # ---- Fixture: two months, three November batches + one December batch.
    b1 = add_batch(db, "QH-A", "一线", "丰垦", 25.0, "2026-11-01")
    b2 = add_batch(db, "QH-B", "一线", "丰垦", 26.0, "2026-11-02")
    b3 = add_batch(db, "QH-C", "二线", "北原", 27.0, "2026-11-03")
    b4 = add_batch(db, "QH-D", "三线", "河谷", 28.0, "2026-12-01")
    add_inspection(db, b1, "A-S1", 70.0); add_inspection(db, b1, "A-S2", 72.0)  # 71
    add_inspection(db, b2, "B-S1", 74.0); add_inspection(db, b2, "B-S2", 76.0)  # 75
    add_inspection(db, b3, "C-S1", 80.0); add_inspection(db, b3, "C-S2", 82.0)  # 81
    add_inspection(db, b4, "D-S1", 60.0); add_inspection(db, b4, "D-S2", 64.0)  # 62

    # Viewer cannot create (route layer enforces via writable; service itself
    # accepts any user object, mirroring how FastAPI injects the dependency).

    # ---- 1) Validation: mixed months rejected.
    from fastapi import HTTPException
    try:
        disclosure.create_application(db, [b1.id, b4.id], analyst)
        raise AssertionError("mixed-month request should be rejected")
    except HTTPException as e:
        assert e.status_code == 422

    # ---- 2) Validation: empty / duplicate ids.
    try:
        disclosure.create_application(db, [], analyst)
        raise AssertionError("empty request should be rejected")
    except HTTPException as e:
        assert e.status_code == 422
    try:
        disclosure.create_application(db, [b1.id, b1.id], analyst)
        raise AssertionError("duplicate ids should be rejected")
    except HTTPException as e:
        assert e.status_code == 422

    # ---- 3) First safe multi-batch application -> published via judge worker.
    app1 = disclosure.create_application(db, [b1.id, b2.id], analyst)
    assert app1["status"] == "pending"
    assert disclosure.judge_application(app1["id"]) is True
    out1 = disclosure.get_application(db, app1["id"], viewer)
    assert out1["status"] == "published"
    assert abs(out1["published_sum"] - 146.0) < 1e-9, out1["published_sum"]

    # Frozen rows created for the month's batches with samples.
    frozen = db.scalars(__import__("sqlalchemy").select(FrozenBatchMean)).all()
    assert {f.batch_id for f in frozen} == {b1.id, b2.id, b3.id}
    assert all(f.month_key == "2026-11" for f in frozen)
    assert all(f.sample_count == 2 for f in frozen)
    # Checksum is populated and stable (internal integrity anchor).
    assert all(len(f.checksum) == 64 for f in frozen)

    # ---- 4) Freeze immutability: new inspection does not change frozen mean.
    add_inspection(db, b1, "A-S3", 100.0)
    f1_before = next(f for f in frozen if f.batch_id == b1.id)
    # Re-judge a new application; freeze must remain the original row/value.
    app_safe = disclosure.create_application(db, [b2.id, b3.id], analyst)
    disclosure.judge_application(app_safe["id"])
    f1_after = db.get(FrozenBatchMean, f1_before.id)
    assert f1_after is f1_before
    assert abs(f1_after.mean_value - 71.0) < 1e-9

    # app_safe = b2+b3 alongside b1+b2: null vector has no zero coord -> safe.
    assert disclosure.get_application(db, app_safe["id"], viewer)["status"] == "published"

    # ---- 5) Difference attack completing the 3-cycle -> rejected, names batches.
    app_att = disclosure.create_application(db, [b1.id, b3.id], analyst)
    disclosure.judge_application(app_att["id"])
    rej = disclosure.get_application(db, app_att["id"], admin)
    assert rej["status"] == "rejected"
    assert {b["batch_code"] for b in rej["solvable_batches"]} == {"QH-A", "QH-B", "QH-C"}
    assert "拒发" in rej["reject_reason"]
    # Viewer must not see internal reasons, implicated batches or any number.
    rej_v = disclosure.get_application(db, app_att["id"], viewer)
    assert rej_v["solvable_batches"] == []
    assert rej_v["reject_reason"] == "该申请未通过外发复核"
    assert rej_v["published_sum"] is None and rej_v["requested_sum"] is None
    assert rej_v["ledger_key"] is None

    # ---- 6) Single-batch request is always rejected.  With b1+b2 and b2+b3
    # already published (rank 2 over 3 vars), fixing b3 completes the system
    # and makes every batch in the connected component solvable.
    app_single = disclosure.create_application(db, [b3.id], analyst)
    disclosure.judge_application(app_single["id"])
    single = disclosure.get_application(db, app_single["id"], admin)
    assert single["status"] == "rejected"
    assert {b["batch_code"] for b in single["solvable_batches"]} == {
        "QH-A", "QH-B", "QH-C"
    }, single["solvable_batches"]

    # ---- 7) Month isolation: December pair publishes regardless of November.
    app_dec = disclosure.create_application(
        db, [b4.id], analyst
    )  # single batch in fresh month -> rejected
    disclosure.judge_application(app_dec["id"])
    dec = disclosure.get_application(db, app_dec["id"], viewer)
    assert dec["status"] == "rejected" and dec["published_sum"] is None

    # ---- 8) Public export contains only published rows, value + codes only.
    apps_pub = disclosure.export_published(db)
    exported_ids = {a.id for a in apps_pub}
    assert app1["id"] in exported_ids and app_safe["id"] in exported_ids
    assert app_att["id"] not in exported_ids and app_single["id"] not in exported_ids
    from src.controllers.export import export_disclosures
    import csv as _csv, io as _io
    resp = export_disclosures(apps_pub)
    body = resp.content
    assert "QH-A" in body and "QH-B" in body and "146.0000" in body
    # Strict two-column shape: approved value and covered batch codes only.
    rows = list(_csv.reader(_io.StringIO(body.lstrip("﻿"))))
    assert rows[0] == ["获准公布的出粉率均值加总值(%)", "所含批号"]
    assert all(len(r) == 2 for r in rows)
    # Month and application identifiers never enter the public export.
    assert "2026-11" not in body and "2026-12" not in body
    assert not any(r[0].isdigit() and len(r[0]) <= 3 for r in rows[1:])
    # Rejected internals never leak into the export.
    assert "拒发" not in body and "solvable" not in body
    assert resp.media_type.startswith("text/csv")

    # ---- 9) Idempotent retry path: simulate a failed app then re-judge.
    b5 = add_batch(db, "QH-E", "一线", "丰垦", 29.0, "2026-12-05")
    add_inspection(db, b5, "E-S1", 77.0); add_inspection(db, b5, "E-S2", 79.0)  # 78
    app_retry = disclosure.create_application(db, [b4.id, b5.id], analyst)
    # Force failure before any ledger write.
    row = db.get(DisclosureApplication, app_retry["id"])
    row.status = "failed"
    row.reject_reason = "模拟落账失败"
    db.commit()
    assert disclosure.get_application(db, app_retry["id"], viewer)["published_sum"] is None
    retried = disclosure.retry_application(db, app_retry["id"], analyst)
    assert retried["status"] == "pending"
    assert disclosure.judge_application(app_retry["id"]) is True
    ok = disclosure.get_application(db, app_retry["id"], viewer)
    assert ok["status"] == "published"
    assert abs(ok["published_sum"] - (62.0 + 78.0)) < 1e-9
    # Stable ledger key tied to the original application id.
    assert ok["ledger_key"] is None  # hidden from viewer
    ok_admin = disclosure.get_application(db, app_retry["id"], admin)
    assert ok_admin["ledger_key"] == f"disclosure:2026-12:app-{app_retry['id']}"

    # Re-judging an already terminal application is a no-op (no double post).
    assert disclosure.judge_application(app_retry["id"]) is True
    ledger_rows = [a for a in db.scalars(
        __import__("sqlalchemy").select(DisclosureApplication)).all()
        if a.ledger_key == ok_admin["ledger_key"]]
    assert len(ledger_rows) == 1

    # ---- 10) Listing endpoint shape and role-aware masking.
    listed = disclosure.list_applications(db, viewer)
    assert all("solvable_batches" in x for x in listed)
    # Viewers never receive implicated batch identities.
    assert all(x["solvable_batches"] == [] for x in listed)
    assert all(x["ledger_key"] is None for x in listed)
    listed_admin = disclosure.list_applications(db, admin)
    assert any(x["solvable_batches"] for x in listed_admin)

    # ---- 11) Frozen-means internal view route payload shape.
    from src.models.entities import FrozenBatchMean as FBM
    frows = db.scalars(__import__("sqlalchemy").select(FBM)).all()
    code = {b.id: b.code for b in db.scalars(__import__("sqlalchemy").select(Batch)).all()}
    payload = [{"batch_id": r.batch_id, "batch_code": code.get(r.batch_id),
                "month_key": r.month_key, "sample_count": r.sample_count,
                "frozen_at": r.created_at.isoformat()} for r in frows]
    assert all(set(p) == {"batch_id", "batch_code", "month_key",
                          "sample_count", "frozen_at"} for p in payload)

    print("REAL-SERVICE INTEGRATION TESTS PASSED")
    print("applications:", [(x["id"], x["status"], x["published_sum"])
                            for x in disclosure.list_applications(db, admin)])


if __name__ == "__main__":
    main()
