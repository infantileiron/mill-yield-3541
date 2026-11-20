"""Outbound disclosure review service.

Rules implemented here:

* Each batch mean is frozen the first time an application for its arrival
  month is accepted for judging, and never changes afterwards.
* An application requests the sum of the selected batches' frozen means.
* Before publishing, the new sum equation is combined with every sum already
  published in the same arrival month.  If the combined linear system
  uniquely determines any single batch mean, the request is rejected and the
  implicated batches are recorded for internal review only.
* Publishing goes through a Redis-backed shared ledger with row locks so
  concurrent workers cannot post the same application twice or observe each
  other's half-finished judgments.  Retries reuse the original application id
  and ledger key, so a failed posting never creates a second publication.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config.settings import REDIS_URL
from src.models.entities import Batch, DisclosureApplication, FrozenBatchMean, Inspection
from src.utils.linear import solvable_columns
from redis import Redis

queue = Redis.from_url(REDIS_URL, decode_responses=True)
LEDGER_LOCK = "mill:disclosure:ledger-lock"
# A short per-key guard complements the DB unique constraint on ledger_key.
LEDGER_POSTED = "mill:disclosure:posted"
# The lock covers DB freezing plus one judgment; keep it comfortably above the
# worst-case transaction so a slow judge cannot have the lock auto-expire and
# let a second worker enter the same critical section.
LOCK_TIMEOUT = 60
LOCK_WAIT = 55


def _mean_checksum(rows):
    payload = json.dumps(
        [(r["sample_code"], str(r["flour_yield"])) for r in rows],
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _batch_inspections(db, batch_id):
    return db.scalars(
        select(Inspection).where(Inspection.batch_id == batch_id).order_by(Inspection.id)
    ).all()


def freeze_month_means(db, month_key):
    """Freeze every not-yet-frozen batch of the given arrival month.

    Returns the mapping batch_id -> FrozenBatchMean.  Runs inside the
    application transaction; callers hold the ledger lock when judging.
    """
    batches = db.scalars(select(Batch).where(Batch.received_date.like(f"{month_key}-%"))).all()
    means = {}
    for batch in batches:
        frozen = db.scalar(
            select(FrozenBatchMean).where(FrozenBatchMean.batch_id == batch.id)
        )
        if frozen is None:
            samples = _batch_inspections(db, batch.id)
            if not samples:
                # A batch without inspections has no mean; it cannot be part
                # of any valid application and is simply skipped.
                continue
            exact_total = sum(Decimal(str(s.flour_yield)) for s in samples)
            mean_value = float(exact_total / Decimal(len(samples)))
            frozen = FrozenBatchMean(
                batch_id=batch.id,
                month_key=month_key,
                mean_value=mean_value,
                sample_count=len(samples),
                checksum=_mean_checksum(
                    [{"sample_code": s.sample_code, "flour_yield": s.flour_yield} for s in samples]
                ),
            )
            db.add(frozen)
            db.flush()
        means[batch.id] = frozen
    return means


def _month_of(batch):
    return batch.received_date[:7]


def create_application(db, batch_ids, user):
    if not batch_ids:
        raise HTTPException(422, "请至少选择一个批次再提交外发申请")
    if len(batch_ids) != len(set(batch_ids)):
        raise HTTPException(422, "所选批次存在重复，请去重后再提交")
    batches = []
    for bid in batch_ids:
        batch = db.get(Batch, bid)
        if batch is None:
            raise HTTPException(404, f"批次 {bid} 不存在")
        if not _batch_inspections(db, batch.id):
            raise HTTPException(422, f"批次 {batch.code} 暂无检验记录，无法冻结出粉率均值")
        batches.append(batch)
    months = {_month_of(b) for b in batches}
    if len(months) != 1:
        raise HTTPException(422, "一份申请只能包含同一到货月的批次")
    month_key = months.pop()
    obj = DisclosureApplication(
        month_key=month_key,
        batch_ids=list(batch_ids),
        batch_codes=[b.code for b in batches],
        status="pending",
        created_by=user.email,
    )
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "申请落库失败，请重试")
    db.refresh(obj)
    try:
        queue.rpush("mill:disclosure:jobs", obj.id)
    except Exception:
        obj.status = "failed"
        obj.reject_reason = "判单队列不可用，请恢复后沿原单重试"
        db.commit()
        raise HTTPException(503, obj.reject_reason)
    return _serialize(obj, user)


def retry_application(db, application_id, user):
    obj = db.get(DisclosureApplication, application_id)
    if obj is None:
        raise HTTPException(404, "外发申请不存在")
    if obj.status != "failed":
        raise HTTPException(409, "只有失败状态的申请可以重试")
    obj.status = "pending"
    obj.reject_reason = ""
    db.commit()
    db.refresh(obj)
    try:
        # Same application id is re-enqueued; the worker always reuses this row
        # and its stable ledger key, so no duplicate publication can appear.
        queue.rpush("mill:disclosure:jobs", obj.id)
    except Exception:
        obj.status = "failed"
        obj.reject_reason = "判单队列不可用，请恢复后沿原单重试"
        db.commit()
        raise HTTPException(503, obj.reject_reason)
    return _serialize(obj, user)


def _published_equation_rows(db, month_key, ordered_batch_ids):
    """Coefficient rows of every published equation in the month.

    Columns follow ordered_batch_ids.  Only batches that appear in the
    ordered universe get a column; other published batches are fetched too so
    the universe covers every equation fully.
    """
    published = db.scalars(
        select(DisclosureApplication)
        .where(
            DisclosureApplication.month_key == month_key,
            DisclosureApplication.status == "published",
        )
        .order_by(DisclosureApplication.id)
    ).all()
    universe = list(ordered_batch_ids)
    for app in published:
        for bid in app.batch_ids:
            if bid not in universe:
                universe.append(bid)
    index = {bid: i for i, bid in enumerate(universe)}
    rows = []
    for app in published:
        row = [0] * len(universe)
        for bid in app.batch_ids:
            row[index[bid]] = 1
        rows.append(row)
    return rows, universe, index, published


def judge_application(app_id):
    """Worker entry point.  Returns True when the application reached a
    terminal state, False when it must be retried later."""
    from src.config.database import Session

    with Session() as db:
        app = db.get(DisclosureApplication, app_id)
        if app is None or app.status in ("rejected", "published"):
            return True
        app.attempts += 1
        app.status = "judging"
        db.commit()

        lock = Redis.from_url(REDIS_URL, decode_responses=True).lock(
            LEDGER_LOCK, timeout=LOCK_TIMEOUT, blocking_timeout=LOCK_WAIT
        )
        try:
            acquired = lock.acquire(blocking=True)
        except Exception:
            acquired = False
        if not acquired:
            app.status = "failed"
            app.reject_reason = "发布账正忙，未取得判单锁；请沿原单重试"
            db.commit()
            return False
        try:
            return _judge_locked(db, app)
        finally:
            try:
                lock.release()
            except Exception:
                pass


def _judge_locked(db, app):
    # Re-read inside the lock so concurrent postings are visible.
    db.expire_all()
    app = db.get(DisclosureApplication, app.id)
    if app.status in ("rejected", "published"):
        return True

    means = freeze_month_means(db, app.month_key)
    missing = [bid for bid in app.batch_ids if bid not in means]
    if missing:
        app.status = "failed"
        app.reject_reason = "部分批次仍无检验样本，无法冻结均值"
        db.commit()
        return False

    ordered = list(app.batch_ids)
    existing_rows, universe, index, published = _published_equation_rows(
        db, app.month_key, ordered
    )
    candidate = [0] * len(universe)
    for bid in app.batch_ids:
        candidate[index[bid]] = 1

    newly_solvable = solvable_columns(existing_rows, candidate)
    if newly_solvable:
        id_to_code = {b.id: b.code for b in db.scalars(select(Batch)).all()}
        app.status = "rejected"
        app.solvable_batches = [
            {"batch_id": universe[col], "batch_code": id_to_code.get(universe[col], str(universe[col]))}
            for col in newly_solvable
        ]
        app.reject_reason = (
            "拒发：与本月已发布等式联立后，可唯一解出单批均值。"
            "涉及批次仅在内部留痕，不对外披露。"
        )
        app.judged_at = datetime.now(timezone.utc)
        db.commit()
        return True

    requested_sum = round(sum(means[bid].mean_value for bid in app.batch_ids), 4)
    app.requested_sum = requested_sum

    ledger_key = f"disclosure:{app.month_key}:app-{app.id}"
    guard = Redis.from_url(REDIS_URL, decode_responses=True)
    # Idempotency guard: a previous attempt may have marked the ledger key
    # even though the DB transaction failed afterwards.
    if guard.sismember(LEDGER_POSTED, ledger_key):
        existing = db.scalar(
            select(DisclosureApplication).where(
                DisclosureApplication.ledger_key == ledger_key
            )
        )
        if existing and existing.status == "published":
            app.status = "published"
            app.published_sum = existing.published_sum
            app.ledger_key = ledger_key
            app.judged_at = existing.judged_at
            db.commit()
            return True

    try:
        app.ledger_key = ledger_key
        app.published_sum = requested_sum
        app.status = "published"
        app.judged_at = datetime.now(timezone.utc)
        db.commit()
    except IntegrityError:
        # Another worker won the unique ledger_key race.  Never double-post.
        db.rollback()
        app = db.get(DisclosureApplication, app.id)
        if app.status != "published":
            app.status = "failed"
            app.reject_reason = "发布账写入冲突，未对外发出数值；请沿原单重试"
            db.commit()
        return app.status == "published"

    try:
        guard.sadd(LEDGER_POSTED, ledger_key)
    except Exception:
        # The DB unique constraint remains the authoritative guard.
        pass
    return True


def list_applications(db, user):
    rows = db.scalars(
        select(DisclosureApplication).order_by(DisclosureApplication.id.desc())
    ).all()
    return [_serialize(a, user) for a in rows]


def get_application(db, application_id, user):
    app = db.get(DisclosureApplication, application_id)
    if app is None:
        raise HTTPException(404, "外发申请不存在")
    return _serialize(app, user)


def _serialize(app, user):
    internal = user.role == "admin"
    data = {
        "id": app.id,
        "month_key": app.month_key,
        "batch_ids": app.batch_ids,
        "batch_codes": app.batch_codes,
        "status": app.status,
        "attempts": app.attempts,
        "created_by": app.created_by,
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "judged_at": app.judged_at.isoformat() if app.judged_at else None,
    }
    if app.status == "published":
        data["published_sum"] = app.published_sum
        data["requested_sum"] = app.requested_sum
    else:
        # External callers must never see a numeric value before publication.
        data["published_sum"] = None
        data["requested_sum"] = None
    if internal:
        data["reject_reason"] = app.reject_reason
        data["solvable_batches"] = app.solvable_batches
        data["ledger_key"] = app.ledger_key
    else:
        data["reject_reason"] = "该申请未通过外发复核" if app.status == "rejected" else ""
        data["solvable_batches"] = []
        data["ledger_key"] = None
    return data


def export_published(db):
    """Rows for the public export: approved values and their batch codes only.
    Pending, rejected and failed applications contribute nothing."""
    apps = db.scalars(
        select(DisclosureApplication)
        .where(DisclosureApplication.status == "published")
        .order_by(DisclosureApplication.month_key, DisclosureApplication.id)
    ).all()
    return apps
