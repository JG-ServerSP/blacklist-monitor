from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crypto import encrypt
from app.database import get_db
from app.models import Blacklist, User
from app.runtime_settings import effective_settings
from app.schemas import BlacklistCreate, BlacklistOut, BlacklistUpdate
from app.security import get_current_user, require_admin, require_operator

router = APIRouter(prefix="/api/blacklists", tags=["blacklists"])


def _to_out(bl: Blacklist, global_dqs_key: str = "") -> BlacklistOut:
    out = BlacklistOut.model_validate(bl)
    # A chave por-blacklist é opcional: quando ausente, o motor de verificação
    # (app/services/checker.py) cai para a chave global de Configurações ->
    # Spamhaus DQS. O indicador precisa refletir essa mesma regra, senão a UI
    # mostra "pendente" para zonas que na prática já estão autenticando.
    out.has_key = bool(bl.api_key_encrypted) or bool(global_dqs_key)
    return out


@router.get("", response_model=list[BlacklistOut])
def list_blacklists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    global_dqs_key = effective_settings(db).spamhaus_dqs_key
    return [_to_out(b, global_dqs_key) for b in db.query(Blacklist).order_by(Blacklist.name).all()]


@router.post("", response_model=BlacklistOut)
def create_blacklist(payload: BlacklistCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    data = payload.model_dump(exclude={"api_key"})
    bl = Blacklist(**data)
    if payload.api_key:
        bl.api_key_encrypted = encrypt(payload.api_key)
    db.add(bl)
    db.commit()
    db.refresh(bl)
    return _to_out(bl, effective_settings(db).spamhaus_dqs_key)


@router.put("/{bl_id}", response_model=BlacklistOut)
def update_blacklist(bl_id: int, payload: BlacklistUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    bl = db.query(Blacklist).get(bl_id)
    if not bl:
        raise HTTPException(404, "Blacklist não encontrada")
    data = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    for k, v in data.items():
        setattr(bl, k, v)
    if payload.api_key is not None:
        bl.api_key_encrypted = encrypt(payload.api_key) if payload.api_key else None
    db.commit()
    db.refresh(bl)
    return _to_out(bl, effective_settings(db).spamhaus_dqs_key)


@router.delete("/{bl_id}")
def delete_blacklist(bl_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    bl = db.query(Blacklist).get(bl_id)
    if not bl:
        raise HTTPException(404, "Blacklist não encontrada")
    db.delete(bl)
    db.commit()
    return {"ok": True}


@router.post("/{bl_id}/toggle", response_model=BlacklistOut)
def toggle_blacklist(bl_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    bl = db.query(Blacklist).get(bl_id)
    if not bl:
        raise HTTPException(404, "Blacklist não encontrada")
    bl.enabled = not bl.enabled
    db.commit()
    db.refresh(bl)
    return _to_out(bl, effective_settings(db).spamhaus_dqs_key)
