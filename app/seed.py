"""Startup seed: idempotent, production-safe.

Ensures the default DNSBL definitions exist (these are real configuration,
not demo data) and that at least one admin user exists. Never inserts
clients/IPs/listings — those are real inventory and must be created by an
operator (UI, CSV import, or the API).
"""
import logging
import secrets

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BLType, Blacklist, Role, Severity, User
from app.security import hash_password

logger = logging.getLogger("seed")
settings = get_settings()

BLACKLIST_SEED = [
    dict(
        name="Spamhaus ZEN", zone="{key}.zen.dq.spamhaus.net", type=BLType.ipv4,
        default_severity=Severity.critical,
        return_code_map={
            "127.0.0.2": {"sublist": "SBL", "severity": "critical"},
            "127.0.0.3": {"sublist": "SBL-CSS", "severity": "critical"},
            "127.0.0.4": {"sublist": "XBL", "severity": "critical"},
            "127.0.0.5": {"sublist": "XBL", "severity": "critical"},
            "127.0.0.6": {"sublist": "XBL", "severity": "critical"},
            "127.0.0.7": {"sublist": "CSS", "severity": "critical"},
            "127.0.0.10": {"sublist": "PBL", "severity": "low"},
            "127.0.0.11": {"sublist": "PBL", "severity": "low"},
        },
        delist_url="https://check.spamhaus.org/", lookup_url="https://check.spamhaus.org/",
        rate_limit_qps=20, requires_key=True,
    ),
    dict(
        name="Barracuda BRBL", zone="b.barracudacentral.org", type=BLType.ipv4,
        default_severity=Severity.high, return_code_map={"127.0.0.2": {"sublist": "BRBL", "severity": "high"}},
        delist_url="https://www.barracudacentral.org/rbl/removal-request",
        lookup_url="https://www.barracudacentral.org/lookups", rate_limit_qps=5,
    ),
    dict(
        name="SpamCop", zone="bl.spamcop.net", type=BLType.ipv4,
        default_severity=Severity.high, return_code_map={"127.0.0.2": {"sublist": "SpamCop", "severity": "high"}},
        delist_url="https://www.spamcop.net/bl.shtml", lookup_url="https://www.spamcop.net/bl.shtml",
        rate_limit_qps=5,
    ),
    dict(
        name="PSBL", zone="psbl.surriel.com", type=BLType.ipv4,
        default_severity=Severity.medium, return_code_map={"127.0.0.2": {"sublist": "PSBL", "severity": "medium"}},
        delist_url="https://psbl.org/remove", lookup_url="https://psbl.org/listing", rate_limit_qps=5,
    ),
    dict(
        name="SORBS", zone="dnsbl.sorbs.net", type=BLType.ipv4,
        default_severity=Severity.medium, return_code_map={"127.0.0.2": {"sublist": "SORBS", "severity": "medium"}},
        delist_url="https://www.sorbs.net/lookup.shtml", lookup_url="https://www.sorbs.net/lookup.shtml",
        rate_limit_qps=3,
    ),
    dict(
        name="UCEPROTECT L1", zone="dnsbl-1.uceprotect.net", type=BLType.ipv4,
        default_severity=Severity.medium, return_code_map={"127.0.0.2": {"sublist": "L1", "severity": "medium"}},
        delist_url="http://www.uceprotect.net/en/rblcheck.php",
        lookup_url="http://www.uceprotect.net/en/rblcheck.php", rate_limit_qps=3,
    ),
    dict(
        name="SURBL", zone="multi.surbl.org", type=BLType.domain,
        default_severity=Severity.high, return_code_map={"127.0.0.2": {"sublist": "SURBL", "severity": "high"}},
        delist_url="http://www.surbl.org/surbl-analysis", lookup_url="http://www.surbl.org/surbl-analysis",
        rate_limit_qps=5,
    ),
    dict(
        name="Spamhaus DBL", zone="{key}.dbl.dq.spamhaus.net", type=BLType.domain,
        default_severity=Severity.critical, return_code_map={"127.0.1.2": {"sublist": "DBL", "severity": "critical"}},
        delist_url="https://check.spamhaus.org/", lookup_url="https://check.spamhaus.org/",
        rate_limit_qps=20, requires_key=True,
    ),
]


def ensure_blacklists(db: Session) -> None:
    existing_names = {b.name for b in db.query(Blacklist.name).all()}
    for spec in BLACKLIST_SEED:
        if spec["name"] not in existing_names:
            db.add(Blacklist(**spec))
    db.commit()


def ensure_admin_user(db: Session) -> None:
    if db.query(User).first():
        return

    password = settings.admin_password or secrets.token_urlsafe(12)
    admin = User(
        email=settings.admin_email, name="Administrator", role=Role.admin,
        password_hash=hash_password(password),
    )
    db.add(admin)
    db.commit()

    if settings.admin_password:
        logger.warning("Admin user created: %s (password set via ADMIN_PASSWORD)", settings.admin_email)
    else:
        logger.warning(
            "=== Admin user created: %s / generated password: %s === "
            "Save this password now — it will not be shown again. Change it after your first login.",
            settings.admin_email, password,
        )


def seed_if_empty(db: Session) -> None:
    ensure_blacklists(db)
    ensure_admin_user(db)
