import ipaddress
from dataclasses import dataclass


class CIDRExpansionError(ValueError):
    pass


@dataclass
class ParsedEntry:
    addresses: list[str]
    cidr_label: str


def parse_entry(entry: str, max_expansion: int) -> ParsedEntry:
    """Parse a CIDR block, a range 'a-b', or a single IP (v4 or v6).

    Raises CIDRExpansionError if the entry is invalid or would expand
    beyond max_expansion addresses (safety cap against accidental /8 imports).
    """
    entry = entry.strip()
    if not entry:
        raise CIDRExpansionError("Entrada vazia")

    if "/" in entry:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise CIDRExpansionError(f"CIDR inválido: {entry}") from exc
        count = network.num_addresses
        if count > max_expansion:
            raise CIDRExpansionError(
                f"Bloco {entry} tem {count} endereços, acima do limite de segurança "
                f"de {max_expansion}. Ajuste o limite em Configurações se isso for intencional."
            )
        addresses = [str(ip) for ip in network.hosts()] or [str(network.network_address)]
        return ParsedEntry(addresses=addresses, cidr_label=str(network))

    if "-" in entry:
        start_s, end_s = (p.strip() for p in entry.split("-", 1))
        try:
            start = ipaddress.ip_address(start_s)
            # allow "a.b.c.d-e" shorthand for last octet
            if "." in end_s or ":" in end_s:
                end = ipaddress.ip_address(end_s)
            else:
                parts = start_s.split(".")
                parts[-1] = end_s
                end = ipaddress.ip_address(".".join(parts))
        except ValueError as exc:
            raise CIDRExpansionError(f"Range inválido: {entry}") from exc
        if int(end) < int(start):
            raise CIDRExpansionError("Fim do range menor que o início")
        count = int(end) - int(start) + 1
        if count > max_expansion:
            raise CIDRExpansionError(
                f"Range {entry} tem {count} endereços, acima do limite de segurança de {max_expansion}."
            )
        addresses = [str(ipaddress.ip_address(i)) for i in range(int(start), int(end) + 1)]
        return ParsedEntry(addresses=addresses, cidr_label=entry)

    try:
        ip = ipaddress.ip_address(entry)
    except ValueError as exc:
        raise CIDRExpansionError(f"IP inválido: {entry}") from exc
    return ParsedEntry(addresses=[str(ip)], cidr_label=str(ip))
