import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Blacklist, Listing, MonitoredIP, User
from app.security import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/export.csv")
def export_csv(
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Listing)
    if start:
        query = query.filter(Listing.detected_at >= start)
    if end:
        query = query.filter(Listing.detected_at <= end)
    listings = query.order_by(Listing.detected_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ip", "blacklist", "sublist", "severidade", "detectado_em", "removido_em", "duracao_min", "status", "ticket"])
    for l in listings:
        ip = db.query(MonitoredIP).get(l.ip_id) if l.ip_id else None
        bl = db.query(Blacklist).get(l.blacklist_id)
        writer.writerow([
            ip.ip if ip else "", bl.name if bl else "", l.sublist or "", l.severity.value,
            l.detected_at.isoformat(), l.removed_at.isoformat() if l.removed_at else "",
            l.duration_minutes or "", l.status.value, l.ticket_ref or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=relatorio_blacklist.csv"},
    )


@router.get("/top-offenders")
def top_offenders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from sqlalchemy import func
    rows = (
        db.query(Blacklist.name, func.count(Listing.id).label("total"))
        .join(Listing, Listing.blacklist_id == Blacklist.id)
        .group_by(Blacklist.name)
        .order_by(func.count(Listing.id).desc())
        .all()
    )
    return [{"blacklist": r[0], "total": r[1]} for r in rows]
