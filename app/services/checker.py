"""Orchestrates ping pre-check + DNSBL checks + listing lifecycle + notifications
for one or many monitored IPs / domains. Used by both the scheduler and the
manual "verificar agora" API action.
"""
import asyncio
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ActivityLog,
    Blacklist,
    BLType,
    CheckRun,
    Domain,
    IPStatus,
    Listing,
    ListingStatus,
    MonitoredIP,
    PingStatus,
    Severity,
)
from app.runtime_settings import effective_settings
from app.services import dnsbl, ping
from app.services.notifications import dispatch_check_error, dispatch_for_listing


def _severity_rank(sev: Severity) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}[sev.value]


# risk_score is recomputed from the currently-open listings each check, so it
# rises AND falls with real state instead of only accumulating.
_RISK_WEIGHT = {Severity.low: 10, Severity.medium: 25, Severity.high: 50, Severity.critical: 100}


async def check_single_ip(db: Session, ip_row: MonitoredIP, force: bool = False) -> None:
    previous_status = ip_row.current_status
    group = ip_row.group
    ping_mode = group.ping_mode.value if group else "skip_unreachable"

    reachable = await ping.is_reachable(ip_row.ip, mode=ping_mode, force=force)
    ip_row.last_ping_at = datetime.utcnow()
    ip_row.ping_status = PingStatus.up if reachable else PingStatus.unreachable

    if not reachable and ping_mode != "check_all" and not force:
        ip_row.current_status = IPStatus.unchecked
        ip_row.last_checked_at = datetime.utcnow()
        db.add(ip_row)
        db.commit()
        return

    ip_version_type = BLType.ipv6 if ":" in ip_row.ip else BLType.ipv4
    blacklists = db.query(Blacklist).filter(Blacklist.enabled == True, Blacklist.type == ip_version_type).all()  # noqa: E712
    if not blacklists:
        ip_row.current_status = IPStatus.clean
        ip_row.last_checked_at = datetime.utcnow()
        db.add(ip_row)
        db.commit()
        return

    results = await dnsbl.check_ip_against_blacklists(ip_row.ip, blacklists, settings=effective_settings(db))

    open_listings = {l.blacklist_id: l for l in db.query(Listing).filter(
        Listing.ip_id == ip_row.id, Listing.removed_at.is_(None)
    ).all()}

    any_error = False
    any_listed = False
    highest_severity = None
    error_details: list[tuple[str, str]] = []

    for bl in blacklists:
        res = results.get(bl.id)
        if res is None:
            continue
        if res.error:
            any_error = True
            error_details.append((bl.name, res.error))
            continue
        existing = open_listings.get(bl.id)
        if res.listed:
            any_listed = True
            sublist, severity_str = dnsbl.interpret_codes(res.codes, bl.return_code_map, bl.default_severity.value)
            severity = Severity(severity_str)
            if highest_severity is None or _severity_rank(severity) > _severity_rank(highest_severity):
                highest_severity = severity
            if existing is None:
                listing = Listing(
                    ip_id=ip_row.id,
                    blacklist_id=bl.id,
                    sublist=sublist,
                    severity=severity,
                    detected_at=datetime.utcnow(),
                    txt_reason=res.txt,
                    status=ListingStatus.detected,
                )
                db.add(listing)
                try:
                    db.flush()
                except IntegrityError:
                    # A concurrent check already opened this listing (unique
                    # index on open (ip_id, blacklist_id)). Treat as already
                    # listed and skip so we don't double-notify.
                    db.rollback()
                    continue
                db.add(ActivityLog(action="listing_detected", entity=f"ip:{ip_row.ip}", payload={
                    "ip": ip_row.ip, "blacklist": bl.name, "severity": severity.value,
                }))
                db.commit()
                await dispatch_for_listing(db, listing, resolved=False)
        else:
            if existing is not None:
                existing.removed_at = datetime.utcnow()
                existing.status = ListingStatus.removed
                delta = existing.removed_at - existing.detected_at
                existing.duration_minutes = int(delta.total_seconds() // 60)
                db.add(ActivityLog(action="listing_removed", entity=f"ip:{ip_row.ip}", payload={
                    "ip": ip_row.ip, "blacklist": bl.name,
                }))
                db.commit()
                await dispatch_for_listing(db, existing, resolved=True)

    ip_row.last_checked_at = datetime.utcnow()
    open_after = db.query(Listing).filter(
        Listing.ip_id == ip_row.id, Listing.removed_at.is_(None)
    ).all()
    ip_row.risk_score = min(100, sum(_RISK_WEIGHT.get(l.severity, 0) for l in open_after))
    if any_listed:
        ip_row.current_status = IPStatus.listed
    elif any_error and not any_listed:
        ip_row.current_status = IPStatus.error
    else:
        ip_row.current_status = IPStatus.clean

    db.add(ip_row)
    db.commit()

    if ip_row.current_status == IPStatus.error and previous_status != IPStatus.error:
        await dispatch_check_error(db, ip_row.ip, "IP", error_details, group_id=ip_row.group_id, client_id=ip_row.client_id)
    elif previous_status == IPStatus.error and ip_row.current_status != IPStatus.error:
        await dispatch_check_error(db, ip_row.ip, "IP", [], group_id=ip_row.group_id, client_id=ip_row.client_id, resolved=True)


async def check_single_domain(db: Session, domain_row: Domain) -> None:
    previous_status = domain_row.current_status
    blacklists = db.query(Blacklist).filter(Blacklist.enabled == True, Blacklist.type == BLType.domain).all()  # noqa: E712
    if not blacklists:
        domain_row.current_status = IPStatus.clean
        domain_row.last_checked_at = datetime.utcnow()
        db.add(domain_row)
        db.commit()
        return

    results = await dnsbl.check_ip_against_blacklists(domain_row.domain, blacklists, settings=effective_settings(db))
    open_listings = {l.blacklist_id: l for l in db.query(Listing).filter(
        Listing.domain_id == domain_row.id, Listing.removed_at.is_(None)
    ).all()}

    any_listed = False
    any_error = False
    error_details: list[tuple[str, str]] = []
    for bl in blacklists:
        res = results.get(bl.id)
        if not res:
            continue
        if res.error:
            any_error = True
            error_details.append((bl.name, res.error))
            continue
        existing = open_listings.get(bl.id)
        if res.listed:
            any_listed = True
            if existing is None:
                sublist, severity_str = dnsbl.interpret_codes(res.codes, bl.return_code_map, bl.default_severity.value)
                listing = Listing(
                    domain_id=domain_row.id,
                    blacklist_id=bl.id,
                    sublist=sublist,
                    severity=Severity(severity_str),
                    detected_at=datetime.utcnow(),
                    txt_reason=res.txt,
                    status=ListingStatus.detected,
                )
                db.add(listing)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    continue
                db.add(ActivityLog(action="listing_detected", entity=f"domain:{domain_row.domain}", payload={
                    "domain": domain_row.domain, "blacklist": bl.name, "severity": severity_str,
                }))
                db.commit()
                await dispatch_for_listing(db, listing, resolved=False)
        elif existing is not None:
            existing.removed_at = datetime.utcnow()
            existing.status = ListingStatus.removed
            delta = existing.removed_at - existing.detected_at
            existing.duration_minutes = int(delta.total_seconds() // 60)
            db.add(ActivityLog(action="listing_removed", entity=f"domain:{domain_row.domain}", payload={
                "domain": domain_row.domain, "blacklist": bl.name,
            }))
            db.commit()
            await dispatch_for_listing(db, existing, resolved=True)

    if any_listed:
        domain_row.current_status = IPStatus.listed
    elif any_error:
        domain_row.current_status = IPStatus.error
    else:
        domain_row.current_status = IPStatus.clean
    domain_row.last_checked_at = datetime.utcnow()
    db.add(domain_row)
    db.commit()

    if domain_row.current_status == IPStatus.error and previous_status != IPStatus.error:
        await dispatch_check_error(db, domain_row.domain, "domain", error_details, client_id=domain_row.client_id)
    elif previous_status == IPStatus.error and domain_row.current_status != IPStatus.error:
        await dispatch_check_error(db, domain_row.domain, "domain", [], client_id=domain_row.client_id, resolved=True)


# Strong references to in-flight background batch tasks, so the event loop
# doesn't garbage-collect them mid-run (asyncio only keeps weak refs).
_background_tasks: set[asyncio.Task] = set()


async def _execute_batch(db: Session, run: CheckRun, ip_ids: list[int], concurrency: int = 20) -> CheckRun:
    """Runs the concurrent workers against ``ip_ids`` and finalizes ``run``.
    ``db`` (owning ``run``) is touched only for the CheckRun bookkeeping; each
    worker opens its own Session so concurrent coroutines never share one (a
    Session is not async-safe).
    """
    sem = asyncio.Semaphore(concurrency)
    skipped = 0
    errors = 0

    async def worker(ip_id: int):
        nonlocal skipped, errors
        async with sem:
            wdb = SessionLocal()
            try:
                row = wdb.query(MonitoredIP).get(ip_id)
                if row is None:
                    return
                before_status = row.current_status
                await check_single_ip(wdb, row)
                if row.current_status == IPStatus.unchecked and before_status != IPStatus.unchecked:
                    skipped += 1
            except Exception:
                errors += 1
                wdb.rollback()
            finally:
                wdb.close()

    await asyncio.gather(*(worker(i) for i in ip_ids))

    run.finished_at = datetime.utcnow()
    run.ips_checked = len(ip_ids)
    run.ips_skipped_ping = skipped
    run.errors = errors
    db.add(run)
    db.commit()
    return run


async def run_check_batch(db: Session, ip_ids: list[int], concurrency: int = 20) -> CheckRun:
    """Creates a CheckRun and runs the batch to completion (awaited inline).
    Used by the scheduler. Callers pass IP ids, not ORM rows, since rows are
    bound to the caller's session.
    """
    run = CheckRun(started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    return await _execute_batch(db, run, ip_ids, concurrency)


async def run_check_batch_bg(ip_ids: list[int], run_id: int, concurrency: int = 20) -> None:
    """Background entrypoint: opens its own Session (the request's session is
    long gone), loads the pre-created CheckRun and executes the batch."""
    db = SessionLocal()
    try:
        run = db.query(CheckRun).get(run_id)
        if run is None:
            return
        await _execute_batch(db, run, ip_ids, concurrency)
    finally:
        db.close()


def queue_check_batch(db: Session, ip_ids: list[int], concurrency: int = 20) -> CheckRun:
    """Creates the CheckRun (started) synchronously so the caller can return its
    id immediately, then fires the batch as a background task. Must be called
    from within a running event loop (i.e. an async request handler)."""
    run = CheckRun(started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    task = asyncio.create_task(run_check_batch_bg(ip_ids, run.id, concurrency))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return run
