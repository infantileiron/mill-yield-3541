import time,os,traceback
from pathlib import Path
from sqlalchemy import select
from src.config.database import Session,Base,engine
from src.models.entities import Review,DisclosureApplication
from src.services.business import queue
from src.services.statistics import diagnose
from src.services.disclosure import judge_application
Base.metadata.create_all(engine)
# Recover committed jobs if a process stopped between database commit and queue push.
with Session() as db:
    for obj in db.scalars(select(Review).where(Review.status.in_(['queued','running']))):queue.rpush('mill:jobs',obj.id)
    # Pending/judging disclosures are re-enqueued along their original row;
    # idempotent ledger guards make the duplicate delivery safe.
    for app in db.scalars(select(DisclosureApplication).where(DisclosureApplication.status.in_(['pending','judging','failed']))):
        if app.status in ('pending','judging'):
            queue.rpush('mill:disclosure:jobs',app.id)
while True:
    Path('/tmp/worker-heartbeat').touch()
    # Pop whichever queue has work; short timeouts keep both streams alive.
    item=queue.blpop('mill:jobs',timeout=2)
    if item:
        with Session() as db:
            obj=db.get(Review,int(item[1]))
            if not obj or obj.status not in ('queued','running'):continue
            obj.status='running';db.commit()
            try:
                obj.result=diagnose(obj.snapshot);obj.status='completed'
                Path('/artifacts').mkdir(exist_ok=True)
                Path(f'/artifacts/review-{obj.id}.json').write_text(__import__('json').dumps(obj.result,ensure_ascii=False))
            except Exception as e:obj.status='failed';obj.note=str(e);traceback.print_exc()
            db.commit()
        continue
    disclosure_item=queue.blpop('mill:disclosure:jobs',timeout=2)
    if not disclosure_item:continue
    app_id=int(disclosure_item[1])
    try:
        judge_application(app_id)
    except Exception:
        traceback.print_exc()
        # Mark failed along the original row; no value leaves the system.
        with Session() as db:
            app=db.get(DisclosureApplication,app_id)
            if app and app.status not in ('published','rejected'):
                app.status='failed';app.reject_reason='判单过程异常，请沿原单重试';db.commit()
