"""Reads and parses the application's log file for the Logs screen.

Deliberately reads the real file written by systemd (StandardOutput/
StandardError=append:...) instead of duplicating log records into the
database — it's the same content ops already tails with `tail -f`, so the
UI never drifts from what's actually happening on the server.
"""
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from app.config import get_settings

# Our own lines (logging.basicConfig format): "2026-07-07 16:31:21,140 INFO logger.name: message"
_APP_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) (?P<logger>[^:]+): (?P<msg>.*)$"
)
# uvicorn's own access/error log lines: "INFO:     127.0.0.1:1234 - \"GET / HTTP/1.1\" 200 OK"
_UVICORN_LINE_RE = re.compile(r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(?P<msg>.*)$")

MAX_SCAN_BYTES = 4_000_000  # cap how much of a (possibly huge) log file we read from the tail


def _parse_line(line: str) -> dict:
    m = _APP_LINE_RE.match(line)
    if m:
        return {"timestamp_raw": m.group("ts"), "level": m.group("level"), "logger": m.group("logger"), "message": m.group("msg")}
    m = _UVICORN_LINE_RE.match(line)
    if m:
        return {"timestamp_raw": None, "level": m.group("level"), "logger": "uvicorn", "message": m.group("msg")}
    return {"timestamp_raw": None, "level": None, "logger": None, "message": line}


def _format_timestamp(raw: str | None, tz_name: str) -> str | None:
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(ZoneInfo(tz_name))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, KeyError):
        return raw


def common_timezones() -> list[str]:
    return sorted(available_timezones())


def read_recent_logs(level: str | None = None, q: str | None = None, limit: int = 200, tz_name: str = "UTC") -> list[dict]:
    settings = get_settings()
    path = Path(settings.log_file_path)
    if not path.exists():
        return []

    with path.open("rb") as f:
        size = f.seek(0, 2)
        if size > MAX_SCAN_BYTES:
            f.seek(size - MAX_SCAN_BYTES)
            f.readline()  # discard the partial line left by the seek
        else:
            f.seek(0)
        data = f.read().decode("utf-8", errors="replace")

    level_filter = level.upper() if level else None
    q_filter = q.lower() if q else None

    entries = []
    for line in reversed(data.splitlines()):
        if not line.strip():
            continue
        parsed = _parse_line(line)
        if level_filter and (parsed["level"] or "") != level_filter:
            continue
        if q_filter and q_filter not in line.lower():
            continue
        parsed["timestamp"] = _format_timestamp(parsed.pop("timestamp_raw"), tz_name)
        entries.append(parsed)
        if len(entries) >= limit:
            break
    return entries
