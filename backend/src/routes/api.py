from fastapi import APIRouter,Depends
from sqlalchemy import select,func,text
from src.config.database import get_db
from src.controllers.auth import current,writable,admin,login
from src.controllers.export import export_review,export_disclosures
from src.schemas.business import Login,BatchInput,InspectionInput,ReviewInput,ApprovalInput,DisclosureInput
from src.models.entities import Batch,Inspection,Review,Audit,FrozenBatchMean
from src.services import business,disclosure
from src.utils.serialize import record
router=APIRouter()
@router.post('/auth/login')
def auth(data:Login,db=Depends(get_db)):return login(db,data)
@router.get('/auth/me')
def me(u=Depends(current)):return {'email':u.email,'role':u.role}
@router.get('/batches')
def get_batches(db=Depends(get_db),u=Depends(current)):return business.batches(db)
@router.post('/batches',status_code=201)
def add_batch(data:BatchInput,db=Depends(get_db),u=Depends(writable)):return business.create(db,Batch,data.model_dump())
@router.get('/inspections')
def get_inspections(batch_id:int|None=None,db=Depends(get_db),u=Depends(current)):return business.inspections(db,batch_id)
@router.post('/inspections',status_code=201)
def add_inspection(data:InspectionInput,db=Depends(get_db),u=Depends(writable)):return business.add_inspection(db,data.model_dump())
@router.get('/reviews')
def get_reviews(db=Depends(get_db),u=Depends(current)):
    return [{k:v for k,v in record(x).items() if k!='snapshot'} for x in db.scalars(select(Review).order_by(Review.id.desc()))]
@router.post('/reviews',status_code=202)
def create_review(data:ReviewInput,db=Depends(get_db),u=Depends(writable)):return business.submit(db,data.model_dump(),u)
@router.get('/reviews/{id}')
def get_review(id:int,db=Depends(get_db),u=Depends(current)):return record(business.review(db,id))
@router.post('/reviews/{id}/approve')
def approve(id:int,data:ApprovalInput,db=Depends(get_db),u=Depends(admin)):return business.approve(db,id,data.note,u)
@router.get('/reviews/{id}/export')
def export(id:int,db=Depends(get_db),u=Depends(current)):return export_review(business.review(db,id))
@router.get('/disclosures/frozen-means')
def frozen_means(db=Depends(get_db),u=Depends(current)):
    # Internal view of which batch means are already frozen per arrival month.
    rows=db.scalars(select(FrozenBatchMean).order_by(FrozenBatchMean.month_key,FrozenBatchMean.id)).all()
    code={b.id:b.code for b in db.scalars(select(Batch)).all()}
    return [{'batch_id':r.batch_id,'batch_code':code.get(r.batch_id),'month_key':r.month_key,'sample_count':r.sample_count,'frozen_at':r.created_at.isoformat()} for r in rows]
@router.get('/disclosures')
def list_disclosures(db=Depends(get_db),u=Depends(current)):return disclosure.list_applications(db,u)
@router.post('/disclosures',status_code=202)
def create_disclosure(data:DisclosureInput,db=Depends(get_db),u=Depends(writable)):return disclosure.create_application(db,data.batch_ids,u)
@router.get('/disclosures/{application_id}')
def get_disclosure(application_id:int,db=Depends(get_db),u=Depends(current)):return disclosure.get_application(db,application_id,u)
@router.post('/disclosures/{application_id}/retry',status_code=202)
def retry_disclosure(application_id:int,db=Depends(get_db),u=Depends(writable)):return disclosure.retry_application(db,application_id,u)
@router.get('/disclosures-export')
def export_disclosure(db=Depends(get_db),u=Depends(current)):return export_disclosures(disclosure.export_published(db))
@router.get('/audits')
def audits(db=Depends(get_db),u=Depends(admin)):return [record(x) for x in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]
@router.get('/counts')
def counts(db=Depends(get_db),u=Depends(current)):return {m.__tablename__:db.scalar(select(func.count()).select_from(m)) for m in (Batch,Inspection,Review)}
