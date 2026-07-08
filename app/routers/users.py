from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog, Role, User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


def _guard_last_active_admin(db: Session, target: User):
    """Blocks a change that would leave the system with zero active admins."""
    other_active_admins = db.query(User).filter(
        User.role == Role.admin, User.is_active == True, User.id != target.id  # noqa: E712
    ).count()
    if other_active_admins == 0:
        raise HTTPException(400, "Não é possível remover o último administrador ativo")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.query(User).order_by(User.created_at).all()


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Já existe um usuário com esse e-mail")
    if len(payload.password) < 8:
        raise HTTPException(400, "A senha deve ter ao menos 8 caracteres")
    new_user = User(
        email=payload.email, name=payload.name, role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    db.add(ActivityLog(user_id=user.id, action="user_created", entity=f"user:{new_user.email}", payload={"role": new_user.role.value}))
    db.commit()
    return new_user


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    target = db.query(User).get(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")

    data = payload.model_dump(exclude_unset=True, exclude={"password"})
    effective_role = data.get("role", target.role)
    effective_active = data.get("is_active", target.is_active)

    if target.id == user.id and effective_active is False:
        raise HTTPException(400, "Você não pode desativar sua própria conta")
    # A mudança tiraria o último admin ativo do sistema (troca de papel ou desativação).
    if target.role == Role.admin and target.is_active and not (effective_role == Role.admin and effective_active):
        _guard_last_active_admin(db, target)

    for k, v in data.items():
        setattr(target, k, v)

    if payload.password is not None:
        if len(payload.password) < 8:
            raise HTTPException(400, "A senha deve ter ao menos 8 caracteres")
        target.password_hash = hash_password(payload.password)

    db.add(ActivityLog(user_id=user.id, action="user_updated", entity=f"user:{target.email}", payload={}))
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    target = db.query(User).get(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if target.id == user.id:
        raise HTTPException(400, "Você não pode remover sua própria conta")
    if target.role == Role.admin:
        _guard_last_active_admin(db, target)
    db.delete(target)
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/disable-2fa", response_model=UserOut)
def disable_2fa(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    target = db.query(User).get(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    target.totp_enabled = False
    target.totp_secret = None
    db.add(ActivityLog(user_id=user.id, action="user_2fa_disabled", entity=f"user:{target.email}", payload={}))
    db.commit()
    db.refresh(target)
    return target
