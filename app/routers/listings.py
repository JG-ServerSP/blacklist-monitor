from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog, Listing, ListingStatus, MonitoredIP, User
from app.schemas import DelistRequest, ListingOut
from app.security import get_current_user, require_operator

router = APIRouter(prefix="/api/listings", tags=["listings"])


@router.get("", response_model=list[ListingOut])
def list_listings(
    severity: str | None = None,
    active_only: bool = False,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Listing)
    if severity:
        query = query.filter(Listing.severity == severity)
    if active_only:
        query = query.filter(Listing.removed_at.is_(None))
    return query.order_by(Listing.detected_at.desc()).offset(offset).limit(limit).all()


@router.post("/{listing_id}/delist-request", response_model=ListingOut)
def request_delist(listing_id: int, payload: DelistRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    listing = db.query(Listing).get(listing_id)
    if not listing:
        raise HTTPException(404, "Listagem não encontrada")
    listing.status = ListingStatus.delist_requested
    listing.delist_requested_by = payload.requested_by
    listing.delist_requested_at = datetime.utcnow()
    db.commit()
    ip = db.query(MonitoredIP).get(listing.ip_id) if listing.ip_id else None
    db.add(ActivityLog(user_id=user.id, action="delist_requested", entity=f"ip:{ip.ip if ip else listing.domain_id}", payload={
        "listing_id": listing.id, "requested_by": payload.requested_by,
    }))
    db.commit()
    db.refresh(listing)
    return listing
