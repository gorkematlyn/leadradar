"""Safe HTTP fetching with per-hop redirect validation and response size limits."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from leadradar.modules.netsafe.policy import BlockedDestination, validate_url
from leadradar.modules.netsafe.proxy import get_egress_proxy

USER_AGENT = "Mozilla/5.0 (compatible; LeadRadarAudit/1.0; +site-audit)"


@dataclass
class Hop:
    url: str
    status: int
    location: str | None = None


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    truncated: bool = False
    hops: list[Hop] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    blocked: str | None = None
    tls_error: bool = False

    @property
    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def make_client(timeout: float = 20.0, verify: bool = True) -> httpx.Client:
    proxy = get_egress_proxy()
    return httpx.Client(
        proxy=proxy.url,
        timeout=httpx.Timeout(timeout, connect=10.0),
        follow_redirects=False,
        verify=verify,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,tr;q=0.8"},
        trust_env=False,
    )


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    max_bytes: int = 5_000_000,
    max_redirects: int = 5,
    timeout: float = 20.0,
    client: httpx.Client | None = None,
    verify: bool = True,
) -> FetchResult:
    result = FetchResult(requested_url=url, final_url=url, status=None)
    own = client is None
    client = client or make_client(timeout, verify=verify)
    started = time.monotonic()
    current = url
    try:
        for _ in range(max_redirects + 1):
            try:
                validate_url(current)
            except BlockedDestination as exc:
                result.blocked = exc.reason
                result.error = f"blocked: {exc.reason}"
                return result
            try:
                with client.stream(method, current) as resp:
                    result.status = resp.status_code
                    result.final_url = str(resp.url)
                    result.headers = {k.lower(): v for k, v in resp.headers.items()}
                    if resp.status_code == 403 and resp.headers.get("content-length") == "0" and not resp.headers.get("server"):
                        # Our own proxy refused (blocked after DNS resolution).
                        result.blocked = "egress_policy"
                    if resp.is_redirect and resp.headers.get("location"):
                        location = urljoin(current, resp.headers["location"])
                        result.hops.append(Hop(current, resp.status_code, location))
                        current = location
                        continue
                    result.hops.append(Hop(current, resp.status_code))
                    chunks: list[bytes] = []
                    size = 0
                    if method != "HEAD":
                        for chunk in resp.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                result.truncated = True
                                chunks.append(chunk[: max(0, max_bytes - (size - len(chunk)))])
                                break
                            chunks.append(chunk)
                    result.body = b"".join(chunks)
                    return result
            except httpx.ProxyError as exc:
                result.error = f"proxy: {exc}"
                result.blocked = "egress_policy" if "403" in str(exc) else None
                return result
            except httpx.ConnectError as exc:
                msg = str(exc)
                result.tls_error = "CERTIFICATE" in msg.upper() or "SSL" in msg.upper()
                result.error = f"connect: {msg[:300]}"
                return result
            except httpx.HTTPError as exc:
                result.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                return result
        result.error = "too_many_redirects"
        return result
    finally:
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        if own:
            client.close()
