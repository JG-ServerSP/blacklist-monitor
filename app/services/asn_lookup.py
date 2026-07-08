"""ASN lookup via Team Cymru's DNS-based IP-to-ASN mapping.

Uses plain DNS TXT queries (origin.cymru.com / asn.cymru.com), so it reuses
the same resolver path as dnsbl.py/diagnostics.py instead of adding an HTTP/
RDAP dependency.
"""
import ipaddress

import dns.asyncresolver
import dns.reversename

from app.config import Settings, get_settings


def _resolver(settings: Settings) -> dns.asyncresolver.Resolver:
    r = dns.asyncresolver.Resolver(configure=True)
    if settings.dns_resolvers.strip():
        r.nameservers = [x.strip() for x in settings.dns_resolvers.split(",") if x.strip()]
    r.timeout = settings.dns_timeout_seconds
    r.lifetime = settings.dns_timeout_seconds
    return r


def _origin_query_name(ip: str, version: int) -> str:
    if version == 4:
        octets = ip.split(".")
        return ".".join(reversed(octets)) + ".origin.asn.cymru.com"
    nibbles = dns.reversename.from_address(ip).to_text().rstrip(".").removesuffix(".ip6.arpa")
    return nibbles + ".origin6.asn.cymru.com"


async def lookup_asn(ip: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    result = {
        "ip": ip, "asn": None, "prefix": None, "country": None,
        "registry": None, "allocated": None, "holder": None, "error": None,
    }
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        result["error"] = "IP inválido"
        return result

    resolver = _resolver(settings)
    try:
        origin_answer = await resolver.resolve(_origin_query_name(ip, addr.version), "TXT")
        fields = [f.strip() for f in origin_answer[0].to_text().strip('"').split("|")]
        asn = fields[0].split()[0] if fields and fields[0] else None
        result.update({
            "asn": asn,
            "prefix": fields[1] if len(fields) > 1 else None,
            "country": fields[2] if len(fields) > 2 else None,
            "registry": fields[3] if len(fields) > 3 else None,
            "allocated": fields[4] if len(fields) > 4 else None,
        })
        if asn:
            asn_answer = await resolver.resolve(f"AS{asn}.asn.cymru.com", "TXT")
            asn_fields = [f.strip() for f in asn_answer[0].to_text().strip('"').split("|")]
            if len(asn_fields) > 4:
                result["holder"] = asn_fields[4]
    except Exception as exc:
        result["error"] = f"Consulta ASN falhou ({exc.__class__.__name__})"
    return result
