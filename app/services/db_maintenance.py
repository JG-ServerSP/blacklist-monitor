"""Finds and removes leftover rows that don't belong to any active monitoring
target — e.g. IPBlock definitions left behind after a CIDR was re-imported or
replaced, whose MonitoredIP rows now point somewhere else (or nowhere)."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import IPBlock, MonitoredIP


def scan_database(db: Session) -> list[dict]:
    issues: list[dict] = []

    member_counts = dict(
        db.query(MonitoredIP.block_id, func.count(MonitoredIP.id))
        .filter(MonitoredIP.block_id.isnot(None))
        .group_by(MonitoredIP.block_id)
        .all()
    )
    for block in db.query(IPBlock).all():
        if member_counts.get(block.id, 0) == 0:
            issues.append({
                "type": "orphan_block",
                "id": block.id,
                "label": block.cidr,
                "detail": f"Bloco {block.cidr} (id {block.id}) sem nenhum IP vinculado",
            })

    block_ids = {row[0] for row in db.query(IPBlock.id).all()}
    dangling_query = db.query(MonitoredIP).filter(MonitoredIP.block_id.isnot(None))
    if block_ids:
        dangling_query = dangling_query.filter(~MonitoredIP.block_id.in_(block_ids))
    for ip in dangling_query.all():
        issues.append({
            "type": "dangling_ip_block_ref",
            "id": ip.id,
            "label": ip.ip,
            "detail": f"IP {ip.ip} referencia o bloco id {ip.block_id}, que não existe mais",
        })

    return issues


def clean_database(db: Session, issues: list[dict]) -> dict:
    removed_blocks = 0
    fixed_ips = 0
    for issue in issues:
        if issue["type"] == "orphan_block":
            block = db.query(IPBlock).get(issue["id"])
            if block:
                db.delete(block)
                removed_blocks += 1
        elif issue["type"] == "dangling_ip_block_ref":
            ip = db.query(MonitoredIP).get(issue["id"])
            if ip:
                ip.block_id = None
                fixed_ips += 1
    db.commit()
    return {"removed_blocks": removed_blocks, "fixed_ips": fixed_ips}
