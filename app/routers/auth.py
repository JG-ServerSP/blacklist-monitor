from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog, User
from app.schemas import LanguageUpdate, LoginRequest, NotifyProfileUpdate, TokenResponse, UserOut
from app.security import create_access_token, get_current_user, hash_password, verify_password, verify_totp

router = APIRouter(prefix="/api/auth", tags=["auth"])

SUPPORTED_LANGUAGES = {"pt-BR", "en", "es", "fr", "de"}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.totp_enabled:
        if not payload.totp_code or not verify_totp(user.totp_secret, payload.totp_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing 2FA code")

    token = create_access_token(user.email)
    db.add(ActivityLog(user_id=user.id, action="login", entity="user", payload={"email": user.email}))
    db.commit()
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="The new password must be at least 8 characters long")
    user.password_hash = hash_password(payload.new_password)
    db.add(ActivityLog(user_id=user.id, action="password_changed", entity="user", payload={"email": user.email}))
    db.commit()
    return {"ok": True}


@router.put("/me/notifications", response_model=UserOut)
def update_my_notifications(
    payload: NotifyProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user.notify_email = payload.notify_email or None
    user.pushover_user_key = payload.pushover_user_key or None
    db.commit()
    db.refresh(user)
    return user


@router.put("/me/language", response_model=UserOut)
def update_my_language(
    payload: LanguageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.language and payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language")
    user.language = payload.language or None
    db.commit()
    db.refresh(user)
    return user
