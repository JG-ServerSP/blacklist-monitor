"""Orchestrates ping pre-check + DNSBL checks + listing lifecycle + notifications
for one or many monitored IPs / domains. Used by both the scheduler and the
manual "verificar agora" API action.
"""
import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

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
                db.flush()
                db.add(ActivityLog(action="listing_detected", entity=f"ip:{ip_row.ip}", payload={
                    "ip": ip_row.ip, "blacklist": bl.name, "severity": severity.value,
                }))
                db.commit()
                dispatch_for_listing(db, listing, resolved=False)
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
                dispatch_for_listing(db, existing, resolved=True)

    ip_row.last_checked_at = datetime.utcnow()
    if any_listed:
        ip_row.current_status = IPStatus.listed
        ip_row.risk_score = min(100, ip_row.risk_score + 10)
    elif any_error and not any_listed:
        ip_row.current_status = IPStatus.error
    else:
        ip_row.current_status = IPStatus.clean

    db.add(ip_row)
    db.commit()

    if ip_row.current_status == IPStatus.error and previous_status != IPStatus.error:
        dispatch_check_error(db, ip_row.ip, "IP", error_details, group_id=ip_row.group_id, client_id=ip_row.client_id)
    elif previous_status == IPStatus.error and ip_row.current_status != IPStatus.error:
        dispatch_check_error(db, ip_row.ip, "IP", [], group_id=ip_row.group_id, client_id=ip_row.client_id, resolved=True)


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
                db.commit()
        elif existing is not None:
            existing.removed_at = datetime.utcnow()
            existing.status = ListingStatus.removed
            db.commit()

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
        dispatch_check_error(db, domain_row.domain, "domínio", error_details, client_id=domain_row.client_id)
    elif previous_status == IPStatus.error and domain_row.current_status != IPStatus.error:
        dispatch_check_error(db, domain_row.domain, "domínio", [], client_id=domain_row.client_id, resolved=True)


async def run_check_batch(db: Session, ip_rows: list[MonitoredIP], concurrency: int = 20) -> CheckRun:
    run = CheckRun(started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    sem = asyncio.Semaphore(concurrency)
    skipped = 0
    errors = 0

    async def worker(ip_row):
        nonlocal skipped, errors
        async with sem:
            try:
                before_status = ip_row.current_status
                await check_single_ip(db, ip_row)
                if ip_row.current_status == IPStatus.unchecked and before_status != IPStatus.unchecked:
                    skipped += 1
            except Exception:
                errors += 1

    await asyncio.gather(*(worker(r) for r in ip_rows))

    run.finished_at = datetime.utcnow()
    run.ips_checked = len(ip_rows)
    run.ips_skipped_ping = skipped
    run.errors = errors
    db.add(run)
    db.commit()
    return run
