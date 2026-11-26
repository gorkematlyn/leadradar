"""Trusted reverse proxy handling, origin validation and host-header protection.

The application has no configured domain. The public host is taken from the request,
but only:

* ``X-Forwarded-*`` headers are honoured exclusively when the direct peer is a trusted
  proxy (``TRUSTED_PROXIES``);
* host values must be syntactically valid hostnames (no injection of paths, credentials,
  whitespace, ...);
* if the administrator configured ``security.allowed_hosts`` the host must be listed.

Absolute URLs for public reports use the admin-configured report origin first, then the
validated request origin.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import idna

from leadradar.core.config import get_settings

_HOST_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")


class HostValidationError(ValueError):
    pass


def normalize_host(host: str) -> str:
    """Return a lower-case ASCII host (with optional :port) or raise."""
    host = host.strip().lower()
    if not host or any(c in host for c in "/\\@?#% \t\r\n"):
        raise HostValidationError("invalid host")
    port = None
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            raise HostValidationError("invalid host")
        name, rest = host[1:end], host[end + 1 :]
        ipaddress.IPv6Address(name)
        if rest:
            if not rest.startswith(":"):
                raise HostValidationError("invalid host")
            port = rest[1:]
        name = f"[{name}]"
    else:
        if host.count(":") > 1:
            raise HostValidationError("invalid host")
        name, _, port = host.partition(":")
        try:
            ipaddress.IPv4Address(name)
        except ValueError:
            try:
                name = idna.encode(name, uts46=True).decode() if not name.isascii() else name
            except idna.IDNAError as exc:
                raise HostValidationError("invalid host") from exc
            if not _HOST_RE.match(name):
                raise HostValidationError("invalid host") from None
    if port:
        if not port.isdigit() or not (0 < int(port) < 65536):
            raise HostValidationError("invalid port")
        return f"{name}:{port}"
    return name


def validate_origin(origin: str) -> str:
    parts = urlsplit(origin.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise HostValidationError("origin must be http(s)://host[:port]")
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
        raise HostValidationError("origin must not contain path, query or credentials")
    return f"{parts.scheme}://{normalize_host(parts.netloc)}"


def is_trusted_proxy(peer: str | None) -> bool:
    if not peer:
        return False
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(ip in net for net in get_settings().trusted_proxy_networks)


@dataclass
class RequestOrigin:
    scheme: str
    host: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"


def resolve_request_origin(headers: dict[str, str], peer: str | None, allowed_hosts: list[str]) -> RequestOrigin:
    """Determine the external origin of a request. Raises HostValidationError."""
    trusted = is_trusted_proxy(peer)
    host_header = headers.get("host", "")
    scheme = "http"
    if trusted:
        fwd_host = headers.get("x-forwarded-host")
        if fwd_host:
            host_header = fwd_host.split(",")[0]
        fwd_proto = headers.get("x-forwarded-proto")
        if fwd_proto:
            scheme = fwd_proto.split(",")[0].strip().lower()
    if scheme not in {"http", "https"}:
        raise HostValidationError("invalid scheme")
    host = normalize_host(host_header)
    if allowed_hosts:
        bare = host.rsplit(":", 1)[0] if not host.startswith("[") else host
        if host not in allowed_hosts and bare not in allowed_hosts:
            raise HostValidationError("host not allowed")
    return RequestOrigin(scheme=scheme, host=host)


def origin_matches(origin_header: str | None, expected: RequestOrigin) -> bool:
    if not origin_header:
        return False
    try:
        return validate_origin(origin_header) == expected.origin
    except HostValidationError:
        return False
