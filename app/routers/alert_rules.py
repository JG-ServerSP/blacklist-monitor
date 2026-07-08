from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AlertRule, User
from app.schemas import AlertRuleCreate, AlertRuleOut
from app.security import get_current_user, require_admin

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


@router.get("", response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(AlertRule).order_by(AlertRule.created_at.desc()).all()


@router.post("", response_model=AlertRuleOut)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=AlertRuleOut)
def update_rule(rule_id: int, payload: AlertRuleCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rule = db.query(AlertRule).get(rule_id)
    if not rule:
        raise HTTPException(404, "Regra não encontrada")
    for k, v in payload.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rule = db.query(AlertRule).get(rule_id)
    if not rule:
        raise HTTPException(404, "Regra não encontrada")
    db.delete(rule)
    db.commit()
    return {"ok": True}
