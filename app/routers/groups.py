from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IPGroup, User
from app.schemas import IPGroupCreate, IPGroupOut
from app.security import get_current_user, require_operator

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[IPGroupOut])
def list_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(IPGroup).order_by(IPGroup.name).all()


@router.post("", response_model=IPGroupOut)
def create_group(payload: IPGroupCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    group = IPGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.put("/{group_id}", response_model=IPGroupOut)
def update_group(group_id: int, payload: IPGroupCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    group = db.query(IPGroup).get(group_id)
    if not group:
        raise HTTPException(404, "Grupo não encontrado")
    for k, v in payload.model_dump().items():
        setattr(group, k, v)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    group = db.query(IPGroup).get(group_id)
    if not group:
        raise HTTPException(404, "Grupo não encontrado")
    db.delete(group)
    db.commit()
    return {"ok": True}
