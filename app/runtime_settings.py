"""Merges the env-based Settings with admin-editable overrides persisted in
the `settings` table (SettingKV), so changes made in the Settings UI
take effect immediately without a restart.
"""
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.crypto import decrypt
from app.models import SettingKV

OVERRIDABLE_KEYS = {
    "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_use_tls", "smtp_from",
    "pushover_app_token", "spamhaus_dqs_key", "dns_resolvers",
    "default_check_interval_minutes", "listed_ip_recheck_minutes",
    "log_level", "timezone", "language",
}

_CASTERS = {
    "smtp_port": int,
    "smtp_use_tls": lambda v: str(v).lower() == "true",
    "default_check_interval_minutes": int,
    "listed_ip_recheck_minutes": int,
}


def effective_settings(db: Session) -> Settings:
    base = get_settings()
    rows = db.query(SettingKV).filter(SettingKV.key.in_(OVERRIDABLE_KEYS)).all()
    overrides = {}
    for row in rows:
        if not row.value_encrypted:
            continue
        value = decrypt(row.value_encrypted)
        if not value:
            continue
        caster = _CASTERS.get(row.key)
        try:
            overrides[row.key] = caster(value) if caster else value
        except (TypeError, ValueError):
            continue
    return base.model_copy(update=overrides) if overrides else base
