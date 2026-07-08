"""Quick diagnostics panel logic: rDNS/PTR/FCrDNS, SPF/DKIM/DMARC, port 25."""
import asyncio

import dns.asyncresolver
import dns.exception
import dns.resolver
import dns.reversename

from app.config import Settings, get_settings


def _resolver(settings: Settings) -> dns.asyncresolver.Resolver:
    r = dns.asyncresolver.Resolver(configure=True)
    if settings.dns_resolvers.strip():
        r.nameservers = [x.strip() for x in settings.dns_resolvers.split(",") if x.strip()]
    r.timeout = settings.dns_timeout_seconds
    r.lifetime = settings.dns_timeout_seconds
    return r


async def check_ptr(ip: str, settings: Settings) -> dict:
    resolver = _resolver(settings)
    try:
        rev_name = dns.reversename.from_address(ip)
        answer = await resolver.resolve(rev_name, "PTR")
        hostname = str(answer[0]).rstrip(".")
        return {"ok": True, "hostname": hostname, "detail": hostname}
    except Exception as exc:
        return {"ok": False, "hostname": None, "detail": f"Sem PTR ({exc.__class__.__name__})"}


async def check_fcrdns(ip: str, hostname: str | None, settings: Settings) -> dict:
    if not hostname:
        return {"ok": False, "detail": "Sem PTR para validar"}
    resolver = _resolver(settings)
    try:
        a_answer = await resolver.resolve(hostname, "A")
        forward_ips = {str(r) for r in a_answer}
        if ip in forward_ips:
            return {"ok": True, "detail": f"{hostname} resolve para {ip}"}
        return {"ok": False, "detail": f"{hostname} não resolve para {ip} (resolve para {', '.join(forward_ips)})"}
    except Exception as exc:
        return {"ok": False, "detail": f"Hostname não resolve A/AAAA ({exc.__class__.__name__})"}


async def check_spf(domain: str, settings: Settings) -> dict:
    resolver = _resolver(settings)
    try:
        answer = await resolver.resolve(domain, "TXT")
        for r in answer:
            txt = r.to_text().strip('"')
            if txt.lower().startswith("v=spf1"):
                return {"ok": True, "detail": txt}
        return {"ok": False, "detail": "Nenhum registro SPF encontrado"}
    except Exception as exc:
        return {"ok": False, "detail": f"Erro consultando TXT ({exc.__class__.__name__})"}


async def check_dkim(domain: str, settings: Settings, selector: str = "default") -> dict:
    resolver = _resolver(settings)
    name = f"{selector}._domainkey.{domain}"
    try:
        answer = await resolver.resolve(name, "TXT")
        for r in answer:
            txt = r.to_text().strip('"')
            if "v=dkim1" in txt.lower() or "p=" in txt.lower():
                return {"ok": True, "detail": f"{name}: {txt[:80]}"}
        return {"ok": False, "detail": f"Nenhum registro DKIM válido em {name}"}
    except Exception:
        return {"ok": False, "detail": f"Sem registro DKIM em seletor '{selector}' (verifique o seletor correto)"}


async def check_dmarc(domain: str, settings: Settings) -> dict:
    resolver = _resolver(settings)
    name = f"_dmarc.{domain}"
    try:
        answer = await resolver.resolve(name, "TXT")
        for r in answer:
            txt = r.to_text().strip('"')
            if txt.lower().startswith("v=dmarc1"):
                return {"ok": True, "detail": txt}
        return {"ok": False, "detail": "Nenhum registro DMARC encontrado"}
    except Exception:
        return {"ok": None, "detail": "Nenhum registro DMARC encontrado"}


async def check_port25(ip: str, timeout: float = 3.0) -> dict:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 25), timeout=timeout)
    except Exception:
        return {"ok": True, "detail": "Porta 25 fechada/filtrada"}

    # Um handshake TCP aceito não prova que exista um SMTP real do outro lado:
    # firewalls de saída de vários provedores de nuvem interceptam/aceitam a
    # porta 25 silenciosamente como filtro anti-spam, sem nunca repassar
    # tráfego SMTP de verdade. Só conta como "aberta" se vier o banner "220".
    try:
        banner = await asyncio.wait_for(reader.readline(), timeout=timeout)
    except Exception:
        banner = b""
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    if banner.startswith(b"220"):
        return {
            "ok": False,
            "detail": f"Porta 25 aberta, respondendo como SMTP (possível open relay / VPS comprometida): {banner.decode(errors='replace').strip()}",
        }
    return {
        "ok": True,
        "detail": "Conexão TCP aceita na porta 25, mas sem handshake SMTP (provável firewall de saída interceptando a porta, não um servidor SMTP real)",
    }


async def run_full_diagnostics(ip: str, domain: str | None = None, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    ptr = await check_ptr(ip, settings)
    fcrdns = await check_fcrdns(ip, ptr.get("hostname"), settings)
    port25 = await check_port25(ip)
    result = {
        "ptr": ptr,
        "fcrdns": fcrdns,
        "port25": port25,
    }
    lookup_domain = domain or ptr.get("hostname")
    if lookup_domain:
        spf, dkim, dmarc = await asyncio.gather(
            check_spf(lookup_domain, settings), check_dkim(lookup_domain, settings), check_dmarc(lookup_domain, settings)
        )
        result.update({"spf": spf, "dkim": dkim, "dmarc": dmarc})
    else:
        na = {"ok": None, "detail": "Sem domínio associado"}
        result.update({"spf": na, "dkim": na, "dmarc": na})
    return result
