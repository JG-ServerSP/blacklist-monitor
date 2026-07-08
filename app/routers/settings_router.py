"""Runtime-editable settings, persisted in the `settings` table (encrypted).

Note: this module is named settings_router to avoid clashing with app.config's
`settings` instance / the stdlib-ish naming collision across the codebase.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import Blacklist, SettingKV, User
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
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is None:
            continue
        row = db.query(SettingKV).get(key)
        stored = encrypt(str(value))
        if row:
            row.value_encrypted = stored
        else:
            db.add(SettingKV(key=key, value_encrypted=stored))
    if updates.get("spamhaus_dqs_key"):
        # Zones like Spamhaus ZEN/DBL ship disabled until a key is set, since
        # querying them without one just returns resolver-blocked errors.
        db.query(Blacklist).filter(
            Blacklist.requires_key == True, Blacklist.enabled == False  # noqa: E712
        ).update({"enabled": True})
    db.commit()
    if "log_level" in updates:
        apply_log_level(payload.log_level)
    return _get_all(db)
