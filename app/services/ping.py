"""ICMP pre-check with TCP fallback.

Raw ICMP sockets require root; instead we shell out to the system `ping`
binary (typically setuid or capabilities-enabled) which works unprivileged
on Linux/most distros. This matches the 3 modes described in the planning
document: skip_unreachable (default), check_all, tcp_fallback.
"""
import asyncio
import ipaddress
from datetime import datetime, timedelta

from app.config import get_settings

settings = get_settings()

# in-memory ping cache: ip -> (is_up: bool, checked_at: datetime)
_ping_cache: dict[str, tuple[bool, datetime]] = {}
# Defensive upper bound so a large fleet can't grow the cache without limit.
_PING_CACHE_MAX = 10_000

DEFAULT_TCP_PORTS = [80, 443, 25, 22]


async def _icmp_ping(ip: str, timeout: float, attempts: int) -> bool:
    is_v6 = ipaddress.ip_address(ip).version == 6
    ping_bin = "ping6" if is_v6 and _has_ping6() else "ping"
    cmd = [ping_bin, "-c", str(attempts), "-W", str(int(timeout)), ip]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout * attempts + 3)
        return rc == 0
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False


_ping6_available: bool | None = None


def _has_ping6() -> bool:
    global _ping6_available
    if _ping6_available is None:
        import shutil
        _ping6_available = shutil.which("ping6") is not None
    return _ping6_available


async def _tcp_check(ip: str, ports: list[int], timeout: float) -> bool:
    for port in ports:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def _cache_get(ip: str) -> bool | None:
    entry = _ping_cache.get(ip)
    if not entry:
        return None
    is_up, checked_at = entry
    if datetime.utcnow() - checked_at > timedelta(minutes=settings.ping_cache_minutes):
        return None
    return is_up


def _prune_ping_cache() -> None:
    """Lazily drop expired entries; if still over the cap, evict the oldest
    half. Keeps the cache bounded without a background sweeper."""
    now = datetime.utcnow()
    ttl = timedelta(minutes=settings.ping_cache_minutes)
    for ip in [k for k, (_, ts) in _ping_cache.items() if now - ts > ttl]:
        _ping_cache.pop(ip, None)
    if len(_ping_cache) >= _PING_CACHE_MAX:
        oldest = sorted(_ping_cache, key=lambda k: _ping_cache[k][1])[: len(_ping_cache) // 2]
        for ip in oldest:
            _ping_cache.pop(ip, None)


def _cache_set(ip: str, is_up: bool) -> None:
    if len(_ping_cache) >= _PING_CACHE_MAX:
        _prune_ping_cache()
    _ping_cache[ip] = (is_up, datetime.utcnow())


async def is_reachable(
    ip: str,
    mode: str = "skip_unreachable",
    tcp_ports: list[int] | None = None,
    use_cache: bool = True,
    force: bool = False,
) -> bool:
    """Returns True if the IP should be considered reachable/in-use.

    mode=check_all always returns True (never skip).
    """
    if mode == "check_all":
        return True

    if use_cache and not force:
        cached = _cache_get(ip)
        if cached is not None:
            return cached

    is_up = await _icmp_ping(ip, settings.ping_timeout_seconds, settings.ping_attempts)
    if not is_up and mode == "tcp_fallback":
        is_up = await _tcp_check(ip, tcp_ports or DEFAULT_TCP_PORTS, settings.ping_timeout_seconds)

    _cache_set(ip, is_up)
    return is_up
