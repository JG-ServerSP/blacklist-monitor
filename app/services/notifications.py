"""Email (SMTP) + Pushover notifications, and alert rule evaluation.

Alert is fired only on state TRANSITION (entered/left a blacklist), never
every check cycle, per the planning doc's deduplication requirement.
"""
import smtplib
from email.mime.text import MIMEText

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AlertRule, Listing, MonitoredIP, Notification, Severity, User

SEVERITY_RANK = {Severity.low: 0, Severity.medium: 1, Severity.high: 2, Severity.critical: 3}
PUSHOVER_PRIORITY = {Severity.critical: 2, Severity.high: 1, Severity.medium: 0, Severity.low: -1}


def send_email(settings: Settings, to: str, subject: str, body_html: str) -> tuple[bool, str | None]:
    if not settings.smtp_host:
        return False, "SMTP not configured"
    try:
        msg = MIMEText(body_html, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [to], msg.as_string())
        return True, None
    except Exception as exc:
        return False, str(exc)


def send_pushover(settings: Settings, user_key: str, title: str, message: str, priority: int = 0) -> tuple[bool, str | None]:
    if not settings.pushover_app_token:
        return False, "Pushover not configured (missing app token)"
    try:
        payload = {
            "token": settings.pushover_app_token,
            "user": user_key,
            "title": title,
            "message": message,
            "priority": priority,
        }
        if priority == 2:
            payload["retry"] = 60
            payload["expire"] = 3600
        resp = httpx.post("https://api.pushover.net/1/messages.json", data=payload, timeout=10)
        if resp.status_code == 200:
            return True, None
        return False, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as exc:
        return False, str(exc)


def render_listing_email(ip: str, blacklist_name: str, severity: str, txt_reason: str | None, resolved: bool) -> str:
    if resolved:
        heading = f"IP removed from blacklist {blacklist_name}"
        color = "#22c55e"
    else:
        heading = f"IP listed on blacklist {blacklist_name}"
        color = "#ef4444"
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;background:#0d1220;color:#e5e7eb;padding:24px;border-radius:8px;">
      <h2 style="color:{color};margin-top:0;">{heading}</h2>
      <p><b>IP:</b> {ip}</p>
      <p><b>Severity:</b> {severity}</p>
      {f'<p><b>Reason:</b> {txt_reason}</p>' if txt_reason else ''}
      <p style="color:#9ca3af;font-size:12px;">Blacklist Monitor — automatic notification</p>
    </div>
    """


def render_check_error_email(target: str, kind: str, error_details: list[tuple[str, str]], resolved: bool) -> str:
    if resolved:
        heading = f"{kind.capitalize()} check back to normal"
        color = "#22c55e"
        body = f"<p>Blacklist queries for <b>{target}</b> are working normally again.</p>"
    else:
        heading = f"{kind.capitalize()} check failure"
        color = "#f59e0b"
        items = "".join(f"<li><b>{name}:</b> {err}</li>" for name, err in error_details)
        body = (
            f"<p>Could not complete the check for <b>{target}</b> against one or more blacklists:</p>"
            f"<ul>{items}</ul>"
        )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;background:#0d1220;color:#e5e7eb;padding:24px;border-radius:8px;">
      <h2 style="color:{color};margin-top:0;">{heading}</h2>
      {body}
      <p style="color:#9ca3af;font-size:12px;">Blacklist Monitor — automatic notification</p>
    </div>
    """


def dispatch_check_error(
    db: Session,
    target: str,
    kind: str,
    error_details: list[tuple[str, str]],
    group_id: int | None = None,
    client_id: int | None = None,
    resolved: bool = False,
) -> None:
    """Alerts registered channels when a check could not be completed (DNS
    resolution errors etc.), separate from listing detected/resolved alerts.
    Only fires on state transition (entering/leaving the error state), same
    dedup rule used for listings.
    """
    from app.runtime_settings import effective_settings

    settings = effective_settings(db)
    rules = db.query(AlertRule).filter(AlertRule.enabled == True).all()  # noqa: E712
    subject_prefix = "Check back to normal" if resolved else "Check failure"

    for rule in rules:
        cond = rule.conditions or {}
        if not cond.get("on_error"):
            continue
        if cond.get("group_id") and cond["group_id"] != group_id:
            continue
        if cond.get("client_id") and cond["client_id"] != client_id:
            continue
        for channel in rule.channels or []:
            ctype = channel.get("type")
            status_, error, recipient = "sent", None, None
            if ctype == "email":
                to = channel.get("to")
                body = render_check_error_email(target, kind, error_details, resolved)
                ok, error = send_email(settings, to, f"[Blacklist Monitor] {subject_prefix} - {target}", body)
                status_ = "sent" if ok else "failed"
                recipient = to
            elif ctype == "pushover":
                user_key = channel.get("user_key")
                message = (
                    "back to normal"
                    if resolved
                    else "; ".join(f"{n}: {e}" for n, e in error_details) or "check error"
                )
                ok, error = send_pushover(settings, user_key, f"{subject_prefix} — {kind} {target}", message, priority=1 if not resolved else 0)
                status_ = "sent" if ok else "failed"
                recipient = user_key
            elif ctype == "user":
                target_user = db.query(User).get(channel.get("user_id"))
                if not target_user:
                    continue
                to = target_user.notify_email or target_user.email
                if to:
                    body = render_check_error_email(target, kind, error_details, resolved)
                    ok, err = send_email(settings, to, f"[Blacklist Monitor] {subject_prefix} - {target}", body)
                    db.add(Notification(rule_id=rule.id, channel="email", recipient=to,
                                         status="sent" if ok else "failed", error=err))
                if target_user.pushover_user_key:
                    message = "back to normal" if resolved else "check error"
                    ok, err = send_pushover(settings, target_user.pushover_user_key, f"{subject_prefix} — {kind} {target}",
                                             message, priority=1 if not resolved else 0)
                    db.add(Notification(rule_id=rule.id, channel="pushover", recipient=target_user.pushover_user_key,
                                         status="sent" if ok else "failed", error=err))
                continue
            else:
                continue

            db.add(Notification(rule_id=rule.id, channel=ctype, recipient=recipient, status=status_, error=error))
    db.commit()


def _matches_conditions(rule: AlertRule, listing: Listing, ip: MonitoredIP | None, resolved: bool) -> bool:
    cond = rule.conditions or {}
    min_severity = cond.get("min_severity")
    if min_severity and SEVERITY_RANK.get(listing.severity, 0) < SEVERITY_RANK.get(Severity(min_severity), 0):
        return False
    if cond.get("blacklist_id") and listing.blacklist_id != cond["blacklist_id"]:
        return False
    if cond.get("group_id") and (not ip or ip.group_id != cond["group_id"]):
        return False
    if cond.get("client_id") and (not ip or ip.client_id != cond["client_id"]):
        return False
    if cond.get("on_resolution") and not resolved:
        return False
    if not cond.get("on_resolution") and resolved:
        return False
    return True


def dispatch_for_listing(db: Session, listing: Listing, resolved: bool = False) -> None:
    from app.runtime_settings import effective_settings

    settings = effective_settings(db)
    ip = db.query(MonitoredIP).filter(MonitoredIP.id == listing.ip_id).first() if listing.ip_id else None
    blacklist = listing.blacklist
    rules = db.query(AlertRule).filter(AlertRule.enabled == True).all()  # noqa: E712

    for rule in rules:
        if not _matches_conditions(rule, listing, ip, resolved):
            continue
        for channel in rule.channels or []:
            ctype = channel.get("type")
            status_, error = "sent", None
            if ctype == "email":
                to = channel.get("to")
                body = render_listing_email(ip.ip if ip else "?", blacklist.name, listing.severity.value, listing.txt_reason, resolved)
                ok, error = send_email(settings, to, f"[Blacklist Monitor] {blacklist.name} - {ip.ip if ip else ''}", body)
                status_ = "sent" if ok else "failed"
                recipient = to
            elif ctype == "pushover":
                user_key = channel.get("user_key")
                priority = PUSHOVER_PRIORITY.get(listing.severity, 0)
                title = f"{'Removed from' if resolved else 'Listed on'} {blacklist.name}"
                message = f"IP {ip.ip if ip else '?'} - severity {listing.severity.value}"
                ok, error = send_pushover(settings, user_key, title, message, priority)
                status_ = "sent" if ok else "failed"
                recipient = user_key
            elif ctype == "user":
                target = db.query(User).get(channel.get("user_id"))
                if not target:
                    continue
                to = target.notify_email or target.email
                if to:
                    body = render_listing_email(ip.ip if ip else "?", blacklist.name, listing.severity.value, listing.txt_reason, resolved)
                    ok, err = send_email(settings, to, f"[Blacklist Monitor] {blacklist.name} - {ip.ip if ip else ''}", body)
                    db.add(Notification(listing_id=listing.id, rule_id=rule.id, channel="email", recipient=to,
                                         status="sent" if ok else "failed", error=err))
                if target.pushover_user_key:
                    priority = PUSHOVER_PRIORITY.get(listing.severity, 0)
                    title = f"{'Removed from' if resolved else 'Listed on'} {blacklist.name}"
                    message = f"IP {ip.ip if ip else '?'} - severity {listing.severity.value}"
                    ok, err = send_pushover(settings, target.pushover_user_key, title, message, priority)
                    db.add(Notification(listing_id=listing.id, rule_id=rule.id, channel="pushover", recipient=target.pushover_user_key,
                                         status="sent" if ok else "failed", error=err))
                continue
            else:
                continue

            db.add(Notification(
                listing_id=listing.id,
                rule_id=rule.id,
                channel=ctype,
                recipient=recipient,
                status=status_,
                error=error,
            ))
    db.commit()
