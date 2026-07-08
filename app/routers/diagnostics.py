import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Blacklist, BLType, MonitoredIP, User
from app.runtime_settings import effective_settings
from app.security import get_current_user
from app.services import dnsbl
from app.services.asn_lookup import lookup_asn
from app.services.diagnostics import run_full_diagnostics

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/asn-lookup")
async def asn_lookup(ip: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, "IP inválido")
    return await lookup_asn(ip, settings=effective_settings(db))


@router.get("/ip-lookup")
async def ip_lookup(ip: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Read-only ASN + blacklist check for an arbitrary IP, not persisted.

    Used by the dashboard's manual lookup box, so any IP (monitored or not)
    can be inspected the same way a monitored IP is.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, "IP inválido")

    settings = effective_settings(db)
    asn_info = await lookup_asn(ip, settings=settings)

    ip_version_type = BLType.ipv6 if addr.version == 6 else BLType.ipv4
    blacklists = db.query(Blacklist).filter(Blacklist.enabled == True, Blacklist.type == ip_version_type).all()  # noqa: E712
    results = await dnsbl.check_ip_against_blacklists(ip, blacklists, settings=settings)

    checks = []
    for bl in blacklists:
        res = results.get(bl.id)
        if res is None:
            continue
        item = {"blacklist": bl.name, "listed": bool(res.listed), "error": res.error}
        if res.listed:
            sublist, severity = dnsbl.interpret_codes(res.codes, bl.return_code_map, bl.default_severity.value)
            item.update({"severity": severity, "sublist": sublist, "txt": res.txt})
        checks.append(item)

    return {"ip": ip, "asn": asn_info, "checks": checks}


@router.get("/by-ip")
async def diagnose_by_ip(ip: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Same PTR/FCrDNS/SPF/DKIM/DMARC/port-25 panel as /{ip_id}, for IPs not (yet) monitored."""
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, "IP inválido")
    return await run_full_diagnostics(ip, settings=effective_settings(db))


@router.get("/{ip_id}")
async def diagnose_ip(ip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(MonitoredIP).get(ip_id)
    if not row:
        raise HTTPException(404, "IP não encontrado")
    return await run_full_diagnostics(row.ip, settings=effective_settings(db))
