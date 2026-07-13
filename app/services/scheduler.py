import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import SessionLocal
from app.models import IPStatus, MonitoredIP
from app.runtime_settings import effective_settings
from app.services.checker import run_check_batch

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler()

# Resolução do "tick": de quanto em quanto tempo olhamos se algum IP está
# devido para verificação. Precisa ser bem menor que o menor intervalo que
# alguém configure (por IP, por grupo ou global) - senão intervalos curtos
# nunca disparam na hora certa. O tick em si é barato (só uma query + laço em
# Python); só os IPs realmente devidos disparam consultas DNS de verdade.
TICK_MINUTES = 1


def _effective_interval_minutes(ip_row: MonitoredIP, default_minutes: int) -> int:
    if ip_row.check_interval_minutes:
        return ip_row.check_interval_minutes
    if ip_row.group and ip_row.group.check_interval_minutes:
        return ip_row.group.check_interval_minutes
    return default_minutes


def _due_interval_minutes(ip_row: MonitoredIP, s) -> int:
    """How stale an IP may get before it's re-checked. Listed IPs use the
    (freshly read) accelerated re-check interval; everyone else uses the
    per-IP/group/global cascade."""
    if ip_row.current_status == IPStatus.listed:
        return max(1, s.listed_ip_recheck_minutes)
    return _effective_interval_minutes(ip_row, s.default_check_interval_minutes)


async def job_check_due_ips():
    db = SessionLocal()
    try:
        # Read settings fresh every tick so changes to the check intervals
        # (including listed_ip_recheck_minutes) take effect without a restart.
        s = effective_settings(db)
        now = datetime.utcnow()
        rows = db.query(MonitoredIP).filter(MonitoredIP.enabled == True).all()  # noqa: E712
        due = [
            r for r in rows
            if r.last_checked_at is None
            or (now - r.last_checked_at) >= timedelta(minutes=_due_interval_minutes(r, s))
        ]
        if due:
            logger.info("Check tick: %d of %d enabled IPs are due", len(due), len(rows))
            await run_check_batch(db, [r.id for r in due])
    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return
    db = SessionLocal()
    try:
        default_minutes = effective_settings(db).default_check_interval_minutes
    finally:
        db.close()
    scheduler.add_job(
        job_check_due_ips,
        "interval",
        minutes=TICK_MINUTES,
        id="check_due_ips",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started (tick every %dmin, respecting per-IP/group/global interval - default %dmin; "
        "listed IPs use listed_ip_recheck_minutes, read fresh each tick)",
        TICK_MINUTES, default_minutes,
    )
