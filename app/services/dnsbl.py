"""DNSBL/RBL check engine.

Builds the reversed-octet (IPv4) / reversed-nibble (IPv6) query name for a
zone, resolves it against a configurable resolver, and interprets the
returned A record(s) using each blacklist's return_code_map.

PRODUCTION NOTE (see PLANEJAMENTO doc section 2.3): Spamhaus, SORBS and
others block/degrade queries from public resolvers (8.8.8.8, 1.1.1.1) and
high-volume shared resolvers. In production point `dns_resolvers` at a
dedicated local Unbound instance with no forwarding to public resolvers.
This MVP defaults to the system resolver when none is configured, which is
fine for low-volume testing but NOT for production Spamhaus DQS usage.
"""
import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass, field

import dns.asyncresolver
import dns.exception
import dns.rdatatype
import dns.resolver

from app.config import Settings, get_settings

logger = logging.getLogger("dnsbl")

# Spamhaus returns 127.255.255.x when the querying resolver is blocked/misused.
# This must NEVER be interpreted as a real listing.
SPAMHAUS_ERROR_PREFIX = "127.255.255."

# A genuine DNSBL listing always answers inside 127.0.0.0/8. Anything else
# (a public IP, an RFC1918 address, a captive-portal wildcard) means the
# resolver hijacked the NXDOMAIN — not a real listing.
_LOOPBACK_NET = ipaddress.ip_network("127.0.0.0/8")


def _is_listing_code(code: str) -> bool:
    try:
        return ipaddress.ip_address(code) in _LOOPBACK_NET
    except ValueError:
        return False


@dataclass
class DNSBLResult:
    listed: bool
    codes: list[str] = field(default_factory=list)
    txt: str | None = None
    error: str | None = None


class RateLimiter:
    """Simple token-bucket per blacklist zone to respect rate_limit_qps.

    Buckets are keyed by zone, so their count is naturally bounded by the
    number of configured blacklists. The idle-eviction below is purely
    defensive against unexpected unbounded growth.
    """

    # Well above any realistic number of blacklist zones; only trips on anomaly.
    _MAX_BUCKETS = 1000
    _IDLE_EVICT_SECONDS = 3600

    def __init__(self):
        self._buckets: dict[str, tuple[float, float]] = {}  # zone -> (tokens, last_ts)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, zone: str) -> asyncio.Lock:
        if zone not in self._locks:
            self._locks[zone] = asyncio.Lock()
        return self._locks[zone]

    def _evict_idle(self, now: float) -> None:
        stale = [z for z, (_, ts) in self._buckets.items() if now - ts > self._IDLE_EVICT_SECONDS]
        for z in stale:
            self._buckets.pop(z, None)
            self._locks.pop(z, None)

    async def acquire(self, zone: str, qps: float):
        qps = max(qps, 0.1)
        lock = self._lock_for(zone)
        async with lock:
            tokens, last_ts = self._buckets.get(zone, (qps, time.monotonic()))
            now = time.monotonic()
            elapsed = now - last_ts
            tokens = min(qps, tokens + elapsed * qps)
            if tokens < 1:
                wait = (1 - tokens) / qps
                await asyncio.sleep(wait)
                tokens = 0
                now = time.monotonic()
            else:
                tokens -= 1
            self._buckets[zone] = (tokens, now)
            if len(self._buckets) > self._MAX_BUCKETS:
                self._evict_idle(now)


_rate_limiter = RateLimiter()


def _reverse_ipv4(ip: str) -> str:
    return ".".join(reversed(ip.split(".")))


def _reverse_ipv6(ip: str) -> str:
    expanded = ipaddress.ip_address(ip).exploded.replace(":", "")
    return ".".join(reversed(expanded))


def build_query_name(ip_or_domain: str, zone_template: str, dqs_key: str, is_domain: bool) -> str:
    zone = zone_template.replace("{key}", dqs_key)
    if is_domain:
        return f"{ip_or_domain}.{zone}"
    ip = ipaddress.ip_address(ip_or_domain)
    reversed_part = _reverse_ipv4(ip_or_domain) if ip.version == 4 else _reverse_ipv6(ip_or_domain)
    return f"{reversed_part}.{zone}"


def _get_resolver(settings: Settings) -> "dns.asyncresolver.Resolver":
    resolver = dns.asyncresolver.Resolver(configure=True)
    if settings.dns_resolvers.strip():
        resolver.nameservers = [r.strip() for r in settings.dns_resolvers.split(",") if r.strip()]
    resolver.timeout = settings.dns_timeout_seconds
    resolver.lifetime = settings.dns_timeout_seconds
    return resolver


def interpret_codes(codes: list[str], return_code_map: dict, default_severity: str) -> tuple[str | None, str]:
    """Returns (sublist, severity) for the first matching/most severe code."""
    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    best_sublist = None
    best_severity = default_severity
    best_rank = -1
    for code in codes:
        mapping = return_code_map.get(code)
        if mapping:
            sub = mapping.get("sublist")
            sev = mapping.get("severity", default_severity)
        else:
            sub, sev = None, default_severity
        rank = severity_rank.get(sev, 0)
        if rank > best_rank:
            best_rank = rank
            best_sublist = sub
            best_severity = sev
    return best_sublist, best_severity


async def check_zone(
    ip_or_domain: str,
    zone_template: str,
    dqs_key: str,
    is_domain: bool,
    rate_limit_qps: float,
    settings: Settings | None = None,
    fetch_txt: bool = True,
) -> DNSBLResult:
    settings = settings or get_settings()
    query_name = build_query_name(ip_or_domain, zone_template, dqs_key, is_domain)
    await _rate_limiter.acquire(zone_template, rate_limit_qps)
    resolver = _get_resolver(settings)

    try:
        answer = await resolver.resolve(query_name, "A")
        codes = [str(r) for r in answer]
    except dns.resolver.NXDOMAIN:
        return DNSBLResult(listed=False)
    except dns.resolver.NoAnswer:
        return DNSBLResult(listed=False)
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        # A single slow/dropped UDP reply from the resolver is common and not
        # a real blacklist condition, so retry once before surfacing an error.
        try:
            answer = await resolver.resolve(query_name, "A")
            codes = [str(r) for r in answer]
        except dns.resolver.NXDOMAIN:
            return DNSBLResult(listed=False)
        except dns.resolver.NoAnswer:
            return DNSBLResult(listed=False)
        except Exception:
            return DNSBLResult(listed=False, error=f"DNS resolution error: {exc}")
    except Exception as exc:  # defensive: never let one bad zone break the whole run
        return DNSBLResult(listed=False, error=str(exc))

    if any(c.startswith(SPAMHAUS_ERROR_PREFIX) for c in codes):
        return DNSBLResult(
            listed=False,
            codes=codes,
            error=(
                "Spamhaus returned a resolver error code (127.255.255.x) — "
                "query blocked/misconfigured, not a real listing."
            ),
        )

    # Guard against resolver NXDOMAIN hijacking (captive portals, ISP wildcards,
    # DNS64): a real listing always answers in 127.0.0.0/8. Treat anything else
    # as "not listed" (with a warning) rather than an error, so it doesn't fire
    # a false check-failure alert.
    if not any(_is_listing_code(c) for c in codes):
        logger.warning(
            "DNSBL %s answered %s for %s outside 127.0.0.0/8 — likely resolver "
            "hijack, treating as NOT listed", query_name, codes, ip_or_domain,
        )
        return DNSBLResult(listed=False, codes=codes)

    txt = None
    if fetch_txt:
        try:
            txt_answer = await resolver.resolve(query_name, "TXT")
            txt = "; ".join(r.to_text().strip('"') for r in txt_answer)
        except Exception:
            txt = None

    return DNSBLResult(listed=True, codes=codes, txt=txt)


async def check_ip_against_blacklists(
    ip: str, blacklists: list, settings: Settings | None = None, concurrency: int = 10
) -> dict[int, DNSBLResult]:
    """blacklists: list of Blacklist ORM objects (already filtered to enabled + matching type)."""
    from app.crypto import safe_decrypt

    settings = settings or get_settings()
    sem = asyncio.Semaphore(concurrency)
    results: dict[int, DNSBLResult] = {}

    async def run_one(bl):
        async with sem:
            if bl.requires_key and bl.api_key_encrypted:
                key = safe_decrypt(bl.api_key_encrypted)
                if key is None:
                    # corrupted/rotated per-blacklist key: fall back to the
                    # global DQS key instead of breaking the whole batch.
                    logger.warning("Blacklist %s: could not decrypt api_key, falling back to global DQS key", bl.name)
                    key = settings.spamhaus_dqs_key
            else:
                key = settings.spamhaus_dqs_key
            if bl.requires_key and not key:
                results[bl.id] = DNSBLResult(listed=False, error=f"{bl.name}: DQS key required but not configured")
                return
            is_domain = bl.type.value == "domain"
            res = await check_zone(ip, bl.zone, key, is_domain, bl.rate_limit_qps, settings=settings)
            results[bl.id] = res

    await asyncio.gather(*(run_one(bl) for bl in blacklists))
    return results
