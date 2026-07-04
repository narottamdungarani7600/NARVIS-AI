"""Shared URL safety helpers for the NARVIS Internet package."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

HostResolver = Callable[[str], Iterable[str]]

_PUBLIC_SCHEMES = {"http", "https"}
_BLOCKED_HOST_SUFFIXES = (".local", ".localdomain", ".internal", ".home", ".lan")


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe for public web access."""


def extract_domain(url: str) -> str:
    """Return the normalized hostname for a URL."""

    parsed = urlsplit(str(url).strip())
    return (parsed.hostname or "").lower()


def normalize_public_url(
    url: str,
    *,
    resolve_host: bool = False,
    resolver: HostResolver | None = None,
) -> str:
    """Normalize a URL and reject unsafe or non-public destinations."""

    candidate = _unwrap_redirect_url(url)
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in _PUBLIC_SCHEMES:
        raise UnsafeUrlError(f"unsupported URL scheme: {parsed.scheme or 'missing'}")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL is missing a hostname")

    _validate_hostname(hostname, resolve_host=resolve_host, resolver=resolver)
    normalized_host = hostname.rstrip(".").lower()
    netloc = normalized_host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _unwrap_redirect_url(url: str) -> str:
    """Unwrap common public-search redirect URLs to their final destination."""

    candidate = str(url).strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    if hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        for key in ("uddg", "rut"):
            values = query.get(key)
            if values:
                return unquote(values[0]).strip()
    return candidate


def _validate_hostname(
    hostname: str,
    *,
    resolve_host: bool,
    resolver: HostResolver | None,
) -> None:
    """Reject local, private, or otherwise unsafe hosts."""

    normalized = hostname.strip().lower().rstrip(".")
    if not normalized:
        raise UnsafeUrlError("hostname is empty")
    if normalized == "localhost" or normalized.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError(f"blocked local hostname: {normalized}")

    try:
        literal_address = ipaddress.ip_address(normalized)
    except ValueError:
        literal_address = None

    if literal_address is not None:
        _ensure_public_ip(literal_address)
        return

    if not resolve_host:
        return

    resolved_addresses = tuple((resolver or _resolve_host_addresses)(normalized))
    if not resolved_addresses:
        raise UnsafeUrlError(f"unable to resolve host: {normalized}")
    for address_text in resolved_addresses:
        _ensure_public_ip(ipaddress.ip_address(address_text))


def _resolve_host_addresses(hostname: str) -> tuple[str, ...]:
    """Resolve a hostname to concrete IP addresses."""

    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnsafeUrlError(f"unable to resolve host: {hostname}") from exc
    addresses = {
        info[4][0]
        for info in infos
        if isinstance(info, tuple) and len(info) >= 5 and isinstance(info[4], tuple) and info[4]
    }
    return tuple(sorted(addresses))


def _ensure_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Reject loopback, private, link-local, or other non-public IP addresses."""

    if not address.is_global:
        raise UnsafeUrlError(f"blocked non-public address: {address}")


__all__ = [
    "HostResolver",
    "UnsafeUrlError",
    "extract_domain",
    "normalize_public_url",
]
