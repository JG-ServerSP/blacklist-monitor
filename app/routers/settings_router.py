"""Runtime-editable settings, persisted in the `settings` table (encrypted).

Note: this module is named settings_router to avoid clashing with app.config's
`settings` instance / the stdlib-ish naming collision across the codebase.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import SettingKV, User
from app.schemas import SettingsUpdate
from app.security import require_admin
from app.services.logging_control import apply_log_level

router = APIRouter(prefix="/api/settings", tags=["settings"])

SENSITIVE_KEYS = {"smtp_password", "pushover_app_token", "spamhaus_dqs_key"}


def _get_all(db: Session) -> dict:
    rows = db.query(SettingKV).all()
    result = {}
    for row in rows:
        value = decrypt(row.value_encrypted) if row.value_encrypted else ""
        result[row.key] = "" if row.key in SENSITIVE_KEYS and value else value
        if row.key in SENSITIVE_KEYS:
            result[row.key] = "••••••••" if value else ""
    return result


@router.get("")
def get_settings_values(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _get_all(db)


@router.put("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        row = db.query(SettingKV).get(key)
        stored = encrypt(str(value))
        if row:
            row.value_encrypted = stored
        else:
            db.add(SettingKV(key=key, value_encrypted=stored))
    db.commit()
    if "log_level" in payload.model_dump(exclude_unset=True):
        apply_log_level(payload.log_level)
    return _get_all(db)
