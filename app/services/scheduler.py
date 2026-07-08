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


async def job_check_due_ips():
    db = SessionLocal()
    try:
        default_minutes = effective_settings(db).default_check_interval_minutes
        now = datetime.utcnow()
        rows = db.query(MonitoredIP).filter(MonitoredIP.enabled == True).all()  # noqa: E712
        due = [
            r for r in rows
            if r.last_checked_at is None
            or (now - r.last_checked_at) >= timedelta(minutes=_effective_interval_minutes(r, default_minutes))
        ]
        if due:
            logger.info("Check tick: %d of %d enabled IPs are due", len(due), len(rows))
            await run_check_batch(db, due)
    finally:
        db.close()


async def job_recheck_listed_ips():
    db = SessionLocal()
    try:
        rows = db.query(MonitoredIP).filter(
            MonitoredIP.enabled == True, MonitoredIP.current_status == IPStatus.listed  # noqa: E712
        ).all()
        if rows:
            logger.info("Accelerated re-check of listed IPs: %d IPs", len(rows))
            await run_check_batch(db, rows)
    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return
    db = SessionLocal()
    try:
        s = effective_settings(db)
        default_minutes, recheck_minutes = s.default_check_interval_minutes, s.listed_ip_recheck_minutes
    finally:
        db.close()
    scheduler.add_job(
        job_check_due_ips,
        "interval",
        minutes=TICK_MINUTES,
        id="check_due_ips",
        replace_existing=True,
    )
    scheduler.add_job(
        job_recheck_listed_ips,
        "interval",
        minutes=recheck_minutes,
        id="recheck_listed_ips",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started (tick every %dmin, respecting per-IP/group/global interval - default %dmin; "
        "re-check of listed IPs every %dmin)",
        TICK_MINUTES, default_minutes, recheck_minutes,
    )
