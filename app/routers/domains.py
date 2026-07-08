from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Domain, Listing, User
from app.schemas import DomainCreate, DomainOut, ListingOut
from app.security import get_current_user, require_operator
from app.services.checker import check_single_domain

router = APIRouter(prefix="/api/domains", tags=["domains"])


@router.get("", response_model=list[DomainOut])
def list_domains(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Domain).order_by(Domain.created_at.desc()).all()


@router.post("", response_model=DomainOut)
def create_domain(payload: DomainCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    if db.query(Domain).filter(Domain.domain == payload.domain).first():
        raise HTTPException(400, "Domain already registered")
    row = Domain(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{domain_id}/listings", response_model=list[ListingOut])
def get_domain_listings(domain_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Listing).filter(Listing.domain_id == domain_id).order_by(Listing.detected_at.desc()).all()


@router.post("/{domain_id}/check", response_model=DomainOut)
async def force_check(domain_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    row = db.query(Domain).get(domain_id)
    if not row:
        raise HTTPException(404, "Domain not found")
    await check_single_domain(db, row)
    db.refresh(row)
    return row


@router.delete("/{domain_id}")
def delete_domain(domain_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    row = db.query(Domain).get(domain_id)
    if not row:
        raise HTTPException(404, "Domain not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
