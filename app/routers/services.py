from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Service, User
from app.schemas import ServiceCreate, ServiceOut
from app.security import get_current_user, require_operator

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
def list_services(client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Service)
    if client_id:
        q = q.filter(Service.client_id == client_id)
    return q.order_by(Service.name).all()


@router.post("", response_model=ServiceOut)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    svc = Service(**payload.model_dump())
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc


@router.delete("/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    svc = db.query(Service).get(service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    db.delete(svc)
    db.commit()
    return {"ok": True}
