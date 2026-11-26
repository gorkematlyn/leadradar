"""SSRF protection policy shared by every outbound request made by workers.

Rules:
* only http/https URLs, no credentials in URLs;
* only allowed destination ports (default 80, 443) -> blocks Dokploy (3000), PostgreSQL (5432) ...;
* every resolved address must be a public unicast address: loopback, private, link-local,
  CGNAT, multicast, reserved, unspecified, documentation ranges and cloud metadata are
  rejected, plus any administrator-supplied deny CIDRs (e.g. the server's own public IP);
* internal Docker service names are rejected even before DNS resolution.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import idna

from leadradar.core.config import get_settings


class BlockedDestination(Exception):
    def __init__(self, reason: str, target: str = "") -> None:
        super().__init__(f"{reason}: {target}" if target else reason)
        self.reason = reason
        self.target = target


_EXTRA_BLOCKED = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # CGNAT (also Tailscale)
        "169.254.0.0/16",  # link-local + cloud metadata 169.254.169.254
        "192.0.0.0/24",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "64:ff9b::/96",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
        "fd00:ec2::254/128",
    )
]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "host.docker.internal",
    "gateway.docker.internal",
    "kubernetes.default",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".intranet", ".corp", ".docker")


def is_ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    if any(ip in net for net in _EXTRA_BLOCKED):
        return False
    return not any(ip in net for net in get_settings().extra_deny_networks)


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str  # ASCII (punycode) host
    port: int


def _test_allowed(host: str) -> bool:
    """Test-only escape hatch for local fixture servers. Inert unless APP_ENV=test."""
    import os

    if get_settings().app_env != "test":
        return False
    allowed = {h.strip() for h in os.environ.get("LEADRADAR_TEST_ALLOW_HOSTS", "").split(",") if h.strip()}
    return host in allowed


def check_hostname(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    if _test_allowed(host):
        return host
    if not host:
        raise BlockedDestination("empty_host")
    try:
        ascii_host = idna.encode(host, uts46=True).decode() if not host.isascii() else host
    except idna.IDNAError as exc:
        raise BlockedDestination("invalid_host", host) from exc
    try:
        ip = ipaddress.ip_address(ascii_host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if not is_ip_allowed(ip):
            raise BlockedDestination("blocked_ip", ascii_host)
        return ascii_host.strip("[]")
    if ascii_host in _BLOCKED_HOSTNAMES or ascii_host.endswith(_BLOCKED_SUFFIXES):
        raise BlockedDestination("blocked_hostname", ascii_host)
    if "." not in ascii_host:
        # Single-label names resolve to internal Docker services (api, db, postgres ...).
        raise BlockedDestination("single_label_hostname", ascii_host)
    return ascii_host


def check_port(port: int) -> None:
    if port not in get_settings().allowed_ports:
        raise BlockedDestination("blocked_port", str(port))


def validate_url(url: str) -> Target:
    if len(url) > 4096:
        raise BlockedDestination("url_too_long")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise BlockedDestination("blocked_scheme", scheme)
    if parts.username or parts.password:
        raise BlockedDestination("credentials_in_url")
    if not parts.hostname:
        raise BlockedDestination("missing_host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise BlockedDestination("invalid_port") from exc
    check_port(port)
    host = check_hostname(parts.hostname)
    return Target(scheme=scheme, host=host, port=port)


def resolve_safe(host: str, port: int) -> list[str]:
    """Resolve and require *every* address to be public (prevents mixed-record rebinding)."""
    host = check_hostname(host)
    check_port(port)
    if _test_allowed(host):
        return [socket.gethostbyname(host)]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedDestination("dns_failure", host) from exc
    addrs: list[str] = []
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not is_ip_allowed(ip):
            raise BlockedDestination("resolves_to_blocked_ip", f"{host} -> {addr}")
        if addr not in addrs:
            addrs.append(addr)
    if not addrs:
        raise BlockedDestination("dns_failure", host)
    return addrs
