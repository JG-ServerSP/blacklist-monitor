import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ActivityLog, IPBlock, Listing, MonitoredIP, User
from app.schemas import BulkIdsRequest, BulkIPUpdateRequest, IPBlockOut, IPImportRequest, ListingOut, MonitoredIPOut, MonitoredIPUpdate
from app.security import get_current_user, require_operator
from app.services.checker import check_single_ip, run_check_batch
from app.services.cidr import CIDRExpansionError, parse_entry

router = APIRouter(prefix="/api/ips", tags=["ips"])
settings = get_settings()


def _import_entry(db: Session, req: IPImportRequest, user: User) -> list[MonitoredIP]:
    try:
        parsed = parse_entry(req.entry, settings.max_cidr_expansion)
    except CIDRExpansionError as exc:
        raise HTTPException(400, str(exc))

    block = None
    if "/" in req.entry or "-" in req.entry:
        block = IPBlock(
            cidr=parsed.cidr_label, group_id=req.group_id, client_id=req.client_id,
            service_id=req.service_id, asn=req.asn,
        )
        db.add(block)
        db.flush()

    created = []
    for addr in parsed.addresses:
        existing = db.query(MonitoredIP).filter(MonitoredIP.ip == addr).first()
        if existing:
            continue
        row = MonitoredIP(
            ip=addr, block_id=block.id if block else None, group_id=req.group_id,
            client_id=req.client_id, service_id=req.service_id, asn=req.asn,
            datacenter=req.datacenter, tags=req.tags,
            check_interval_minutes=req.check_interval_minutes,
        )
        db.add(row)
        created.append(row)
    db.commit()
    db.add(ActivityLog(user_id=user.id, action="ip_import", entity=req.entry, payload={"count": len(created)}))
    db.commit()
    for row in created:
        db.refresh(row)
    return created


def _filtered_ips_query(
    db: Session,
    status_filter: str | None,
    client_id: int | None,
    group_id: int | None,
    q: str | None,
    block_id: int | None = None,
):
    query = db.query(MonitoredIP)
    if status_filter:
        query = query.filter(MonitoredIP.current_status == status_filter)
    if client_id:
        query = query.filter(MonitoredIP.client_id == client_id)
    if group_id:
        query = query.filter(MonitoredIP.group_id == group_id)
    if block_id:
        query = query.filter(MonitoredIP.block_id == block_id)
    if q:
        query = query.filter(MonitoredIP.ip.contains(q))
    return query


@router.get("", response_model=list[MonitoredIPOut])
def list_ips(
    response: Response,
    status_filter: str | None = None,
    client_id: int | None = None,
    group_id: int | None = None,
    q: str | None = None,
    block_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = _filtered_ips_query(db, status_filter, client_id, group_id, q, block_id)

    if block_id:
        # Fetching one block's members (block-expand UI) — paginate raw rows.
        response.headers["X-Total-Count"] = str(query.count())
        return query.order_by(MonitoredIP.created_at.desc()).offset(offset).limit(limit).all()

    # Paginate by *unit* (a whole CIDR/range block counts as one item, same
    # as a standalone IP) instead of by raw row. Otherwise a single large
    # block's members fill the entire page and push every other block off
    # page 1 — e.g. importing three /24s left only the newest one visible.
    meta = query.with_entities(MonitoredIP.id, MonitoredIP.block_id, MonitoredIP.created_at).all()
    units: dict[tuple[str, int], object] = {}
    for row_id, blk_id, created_at in meta:
        key = ("block", blk_id) if blk_id else ("ip", row_id)
        if key not in units or created_at > units[key]:
            units[key] = created_at
    ordered = sorted(units.items(), key=lambda kv: kv[1], reverse=True)
    response.headers["X-Total-Count"] = str(len(ordered))

    page = ordered[offset : offset + limit]
    if not page:
        return []
    block_ids = [k[1] for k, _ in page if k[0] == "block"]
    ip_ids = [k[1] for k, _ in page if k[0] == "ip"]
    result = query.filter(or_(MonitoredIP.block_id.in_(block_ids), MonitoredIP.id.in_(ip_ids)))
    return result.order_by(MonitoredIP.created_at.desc()).all()


@router.get("/blocks", response_model=list[IPBlockOut])
def list_blocks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Lists CIDR/range blocks so the UI can group their member IPs under a
    collapsible row (must be registered before /{ip_id} to avoid the int
    path param swallowing this literal segment). Includes each block's true
    member count so the UI doesn't have to infer it from a paginated slice.
    """
    counts = dict(
        db.query(MonitoredIP.block_id, func.count(MonitoredIP.id))
        .filter(MonitoredIP.block_id.isnot(None))
        .group_by(MonitoredIP.block_id)
        .all()
    )
    blocks = db.query(IPBlock).order_by(IPBlock.created_at.desc()).all()
    return [
        IPBlockOut(
            id=b.id, cidr=b.cidr, group_id=b.group_id, client_id=b.client_id,
            service_id=b.service_id, asn=b.asn, note=b.note, created_at=b.created_at,
            ip_count=counts.get(b.id, 0),
        )
        for b in blocks
    ]


@router.post("/import", response_model=list[MonitoredIPOut])
def import_ips(payload: IPImportRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return _import_entry(db, payload, user)


@router.post("/import-csv")
async def import_csv(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
):
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    total_created = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        entry = (row.get("ip") or row.get("cidr") or "").strip()
        if not entry:
            continue
        try:
            req = IPImportRequest(
                entry=entry,
                client_id=None,
                datacenter=row.get("datacenter") or None,
                tags=row.get("tags") or None,
            )
            created = _import_entry(db, req, user)
            total_created += len(created)
        except HTTPException as exc:
            errors.append(f"linha {i}: {exc.detail}")
    return {"created": total_created, "errors": errors}


@router.post("/bulk-check")
async def bulk_check(payload: BulkIdsRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    rows = db.query(MonitoredIP).filter(MonitoredIP.id.in_(payload.ids)).all()
    if not rows:
        raise HTTPException(404, "No IP found for the given IDs")
    run = await run_check_batch(db, rows)
    return {"checked": len(rows), "errors": run.errors}


@router.post("/check-all")
async def check_all(
    status_filter: str | None = None,
    client_id: int | None = None,
    group_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
):
    rows = _filtered_ips_query(db, status_filter, client_id, group_id, q).all()
    if not rows:
        raise HTTPException(404, "No IP found for the given filter")
    run = await run_check_batch(db, rows)
    return {"checked": len(rows), "errors": run.errors}


@router.post("/bulk-update")
def bulk_update(payload: BulkIPUpdateRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    rows = db.query(MonitoredIP).filter(MonitoredIP.id.in_(payload.ids)).all()
    if not rows:
        raise HTTPException(404, "No IP found for the given IDs")
    data = payload.model_dump(exclude_unset=True, exclude={"ids"})
    for row in rows:
        for k, v in data.items():
            setattr(row, k, v)
        db.add(row)
    db.commit()
    return {"updated": len(rows)}


@router.post("/bulk-delete")
def bulk_delete(payload: BulkIdsRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    rows = db.query(MonitoredIP).filter(MonitoredIP.id.in_(payload.ids)).all()
    deleted = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return {"deleted": deleted}


@router.get("/{ip_id}", response_model=MonitoredIPOut)
def get_ip(ip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(MonitoredIP).get(ip_id)
    if not row:
        raise HTTPException(404, "IP not found")
    return row


@router.get("/{ip_id}/listings", response_model=list[ListingOut])
def get_ip_listings(ip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Listing).filter(Listing.ip_id == ip_id).order_by(Listing.detected_at.desc()).all()


@router.patch("/{ip_id}", response_model=MonitoredIPOut)
def update_ip(ip_id: int, payload: MonitoredIPUpdate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    row = db.query(MonitoredIP).get(ip_id)
    if not row:
        raise HTTPException(404, "IP not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{ip_id}/check", response_model=MonitoredIPOut)
async def force_check(ip_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    row = db.query(MonitoredIP).get(ip_id)
    if not row:
        raise HTTPException(404, "IP not found")
    await check_single_ip(db, row, force=True)
    db.refresh(row)
    return row


@router.delete("/{ip_id}")
def delete_ip(ip_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    row = db.query(MonitoredIP).get(ip_id)
    if not row:
        raise HTTPException(404, "IP not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
