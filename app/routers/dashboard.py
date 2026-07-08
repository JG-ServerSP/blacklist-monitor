from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Domain, IPStatus, Listing, MonitoredIP, Severity, User
from app.security import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/kpis")
def kpis(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    total = db.query(func.count(MonitoredIP.id)).scalar() or 0
    clean = db.query(func.count(MonitoredIP.id)).filter(MonitoredIP.current_status == IPStatus.clean).scalar() or 0
    listed = db.query(func.count(MonitoredIP.id)).filter(MonitoredIP.current_status == IPStatus.listed).scalar() or 0
    critical = (
        db.query(func.count(func.distinct(Listing.ip_id)))
        .join(MonitoredIP, MonitoredIP.id == Listing.ip_id)
        .filter(
            Listing.removed_at.is_(None),
            Listing.severity == Severity.critical,
            MonitoredIP.current_status == IPStatus.listed,
        )
        .scalar() or 0
    )
    domains = db.query(func.count(Domain.id)).scalar() or 0

    def pct(n):
        return round(100 * n / total, 1) if total else 0.0

    return {
        "monitored_ips": total,
        "clean_ips": clean,
        "clean_pct": pct(clean),
        "listed_ips": listed,
        "listed_pct": pct(listed),
        "critical_listings": critical,
        "critical_pct": pct(critical),
        "monitored_domains": domains,
    }


@router.get("/severity-breakdown")
def severity_breakdown(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Listing.severity, func.count(Listing.id))
        .join(MonitoredIP, MonitoredIP.id == Listing.ip_id)
        .filter(Listing.removed_at.is_(None), MonitoredIP.current_status == IPStatus.listed)
        .group_by(Listing.severity)
        .all()
    )
    counts = {s.value: 0 for s in Severity}
    for sev, count in rows:
        counts[sev.value] = count
    counts["total_ips"] = db.query(func.count(MonitoredIP.id)).scalar() or 0
    counts["clean_ips"] = (
        db.query(func.count(MonitoredIP.id))
        .filter(MonitoredIP.current_status == IPStatus.clean)
        .scalar() or 0
    )
    return counts


@router.get("/timeline")
def timeline(days: int = 7, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(func.date(Listing.detected_at), Listing.severity, func.count(Listing.id))
        .filter(Listing.detected_at >= since)
        .group_by(func.date(Listing.detected_at), Listing.severity)
        .all()
    )
    by_day: dict[str, dict[str, int]] = {}
    for day, sev, count in rows:
        by_day.setdefault(str(day), {s.value: 0 for s in Severity})[sev.value] = count
    return by_day


@router.get("/recent-listings")
def recent_listings(severity: str | None = None, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(MonitoredIP).filter(MonitoredIP.current_status == IPStatus.listed)
    ips = query.order_by(MonitoredIP.last_checked_at.desc()).limit(limit).all()

    results = []
    for ip in ips:
        open_listings = [l for l in ip.listings if l.removed_at is None]
        if not open_listings:
            continue
        if severity and severity != "all":
            open_listings = [l for l in open_listings if l.severity.value == severity]
            if not open_listings:
                continue
        severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
        worst = max(open_listings, key=lambda l: severity_rank[l.severity.value])
        results.append({
            "ip_id": ip.id,
            "ip": ip.ip,
            "client": ip.client.name if ip.client else None,
            "service": ip.service.name if ip.service else None,
            "blacklists": [
                {"name": l.blacklist.name, "id": l.blacklist_id} for l in open_listings
            ],
            "severity": worst.severity.value,
            "last_detection": max(l.detected_at for l in open_listings).isoformat(),
        })
    return results


@router.get("/ip-detail/{ip_id}")
def ip_detail(ip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ip = db.query(MonitoredIP).get(ip_id)
    if not ip:
        return {}
    listings = sorted(ip.listings, key=lambda l: l.detected_at, reverse=True)
    return {
        "ip": ip.ip,
        "client": ip.client.name if ip.client else None,
        "service": ip.service.name if ip.service else None,
        "group": ip.group.name if ip.group else None,
        "asn": ip.asn,
        "datacenter": ip.datacenter,
        "created_at": ip.created_at.isoformat(),
        "current_status": ip.current_status.value,
        "listings": [
            {
                "id": l.id,
                "blacklist": l.blacklist.name,
                "severity": l.severity.value,
                "detected_at": l.detected_at.isoformat(),
                "removed_at": l.removed_at.isoformat() if l.removed_at else None,
                "status": l.status.value,
                "txt_reason": l.txt_reason,
                "ticket_ref": l.ticket_ref,
            }
            for l in listings
        ],
    }
