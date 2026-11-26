"""Lightweight HTTP stage: availability, TLS, redirects, robots/sitemap, page sampling,
broken links/images. Runs before (and often instead of) expensive browser analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from leadradar.modules.netsafe.http import FetchResult, make_client, safe_fetch
from leadradar.modules.netsafe.policy import BlockedDestination, resolve_safe, validate_url
from leadradar.modules.website_audit.html_checks import PageInfo, parked_or_maintenance, parse_page
from leadradar.modules.website_audit.results import (
    BLOCKED,
    DETECTED,
    ERROR,
    FAILED,
    NOT_APPLICABLE,
    NOT_CHECKED,
    NOT_DETECTED,
    PASSED,
    UNKNOWN,
    EvidenceItem,
    RuleResult,
)

PRIORITY_PATHS = ("contact", "iletisim", "kontakt", "about", "hakkimizda", "services", "hizmetler", "booking",
                  "randevu", "shop", "products", "urunler")


@dataclass
class HttpStageOutput:
    results: list[RuleResult] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    final_url: str | None = None
    reachable: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    blocked: bool = False


def _ev_http(res: FetchResult) -> EvidenceItem:
    return EvidenceItem(
        "http_response", "HTTP response", res.final_url,
        data={"status": res.status, "hops": [h.__dict__ for h in res.hops], "elapsed_ms": res.elapsed_ms,
              "server": res.headers.get("server"), "content_type": res.headers.get("content-type"),
              "error": res.error},
        detection_method="http",
    )


def _with_scheme(url: str, scheme: str) -> str:
    p = urlsplit(url)
    return urlunsplit((scheme, p.netloc, p.path or "/", p.query, ""))


def run_http_stage(start_url: str, *, max_pages: int, timeout: float, max_bytes: int, max_redirects: int) -> HttpStageOutput:
    out = HttpStageOutput()
    try:
        target = validate_url(start_url)
    except BlockedDestination as exc:
        out.blocked = True
        out.results.append(RuleResult("site.reachable", BLOCKED, start_url, {"reason": exc.reason}))
        return out
    # DNS
    try:
        resolve_safe(target.host, target.port)
        out.results.append(RuleResult("site.dns_resolves", PASSED, start_url, {"host": target.host}))
    except BlockedDestination as exc:
        if exc.reason == "dns_failure":
            out.results.append(RuleResult("site.dns_resolves", FAILED, start_url, {"host": target.host},
                                          evidence=[EvidenceItem("http_response", "DNS lookup failed", start_url,
                                                                 data={"host": target.host}, detection_method="dns")]))
            out.results.append(RuleResult("site.reachable", FAILED, start_url, {"reason": "dns_failure"}))
        else:
            out.blocked = True
            out.results.append(RuleResult("site.reachable", BLOCKED, start_url, {"reason": exc.reason}))
        return out
    except OSError:
        out.results.append(RuleResult("site.dns_resolves", UNKNOWN, start_url))

    client = make_client(timeout)
    try:
        https_url = _with_scheme(start_url, "https")
        res = safe_fetch(https_url, client=client, max_bytes=max_bytes, max_redirects=max_redirects)
        ssl_ok: bool | None = None
        if res.tls_error:
            ssl_ok = False
            # Retry without verification only to learn whether content exists (never trusted otherwise).
            insecure = safe_fetch(https_url, max_bytes=max_bytes, max_redirects=max_redirects, timeout=timeout, verify=False)
            https_works = insecure.status is not None and insecure.status < 500
            res_for_content = safe_fetch(_with_scheme(start_url, "http"), client=client, max_bytes=max_bytes,
                                         max_redirects=max_redirects)
        elif res.status is not None:
            ssl_ok = True
            https_works = res.status < 500
            res_for_content = res
        else:
            https_works = False
            res_for_content = safe_fetch(_with_scheme(start_url, "http"), client=client, max_bytes=max_bytes,
                                         max_redirects=max_redirects)
        if res_for_content.blocked:
            out.blocked = True
            out.results.append(RuleResult("site.reachable", BLOCKED, start_url, {"reason": res_for_content.blocked}))
            return out
        out.results.append(RuleResult("site.https_available", PASSED if https_works else FAILED, https_url,
                                      {"status": res.status, "error": res.error}, evidence=[_ev_http(res)]))
        out.results.append(RuleResult("site.ssl_valid", NOT_APPLICABLE if ssl_ok is None and not https_works else
                                      (PASSED if ssl_ok else FAILED), https_url, {"tls_error": res.tls_error}))
        status = res_for_content.status
        reachable = status is not None and 200 <= status < 400 and bool(res_for_content.body)
        out.reachable = reachable
        out.final_url = res_for_content.final_url
        out.headers = res_for_content.headers
        out.metrics["http"] = {"status": status, "elapsed_ms": res_for_content.elapsed_ms,
                               "bytes": len(res_for_content.body), "truncated": res_for_content.truncated,
                               "redirects": len(res_for_content.hops) - 1}
        if status in (401, 403, 429) and not res_for_content.blocked:
            out.results.append(RuleResult("site.reachable", BLOCKED, start_url, {"status": status},
                                          params={"status": status}, evidence=[_ev_http(res_for_content)],
                                          confidence=0.5))
            return out
        out.results.append(RuleResult("site.reachable", PASSED if reachable else FAILED, start_url,
                                      {"status": status, "error": res_for_content.error}, params={"status": status},
                                      evidence=[_ev_http(res_for_content)]))
        hops = len(res_for_content.hops) - 1
        out.results.append(RuleResult("site.redirect_chain", PASSED if hops <= 2 else FAILED, start_url,
                                      {"hops": hops}, params={"hops": hops}))
        # HTTP -> HTTPS
        if https_works and ssl_ok:
            plain = safe_fetch(_with_scheme(start_url, "http"), client=client, method="HEAD", max_redirects=max_redirects)
            redirects_https = plain.final_url.startswith("https://") or any(
                (h.location or "").startswith("https://") for h in plain.hops)
            out.results.append(RuleResult("site.http_to_https", PASSED if redirects_https else
                                          (UNKNOWN if plain.status is None else FAILED), start_url,
                                          {"final": plain.final_url, "status": plain.status}))
        else:
            out.results.append(RuleResult("site.http_to_https", NOT_APPLICABLE, start_url))
        if not reachable:
            return out
        home = parse_page(res_for_content.final_url, res_for_content.text)
        out.pages.append(home)
        parked, maintenance = parked_or_maintenance(home)
        out.results.append(RuleResult("site.parked_domain", FAILED if len(parked) >= 1 else PASSED, home.url,
                                      {"indicators": parked}, confidence=0.9 if len(parked) >= 2 else 0.7,
                                      evidence=[EvidenceItem("html_snippet", "Parking indicators", home.url,
                                                             data={"indicators": parked}, detection_method="text_pattern")]
                                      if parked else []))
        out.results.append(RuleResult("site.maintenance_page", FAILED if maintenance else PASSED, home.url,
                                      {"indicators": maintenance}, confidence=0.7))
        # robots.txt / sitemap
        origin = f"{urlsplit(home.url).scheme}://{urlsplit(home.url).netloc}"
        robots = safe_fetch(origin + "/robots.txt", client=client, max_bytes=200_000)
        robots_ok = robots.status == 200 and b"<html" not in robots.body[:500].lower()
        out.results.append(RuleResult("seo.robots_txt", PASSED if robots_ok else FAILED, origin + "/robots.txt",
                                      {"status": robots.status}))
        sitemap_found = robots_ok and b"sitemap:" in robots.body.lower()
        if not sitemap_found:
            sm = safe_fetch(origin + "/sitemap.xml", client=client, method="GET", max_bytes=100_000)
            sitemap_found = sm.status == 200 and (b"<urlset" in sm.body or b"<sitemapindex" in sm.body)
        out.results.append(RuleResult("seo.sitemap", PASSED if sitemap_found else FAILED, origin, {"found": sitemap_found}))
        # favicon fallback
        fav = safe_fetch(origin + "/favicon.ico", client=client, method="HEAD")
        if fav.status == 200:
            out.results.append(RuleResult("tech.favicon", PASSED, home.url, {"favicon_ico": True}))
        # Additional pages (bounded)
        candidates = []
        for link in home.internal_links:
            path = urlsplit(link).path.lower()
            if link.rstrip("/") == home.url.rstrip("/") or any(path.endswith(ext) for ext in (".pdf", ".jpg", ".png", ".zip", ".docx")):
                continue
            prio = 0 if any(k in path for k in PRIORITY_PATHS) else 1
            candidates.append((prio, len(path), link))
        seen = {home.url.rstrip("/")}
        for _, _, link in sorted(candidates):
            if len(out.pages) >= max_pages:
                break
            if link.rstrip("/") in seen:
                continue
            seen.add(link.rstrip("/"))
            r = safe_fetch(link, client=client, max_bytes=max_bytes, max_redirects=max_redirects)
            if r.status == 200 and "html" in r.headers.get("content-type", "html"):
                out.pages.append(parse_page(r.final_url, r.text))
        # Broken internal links (sample) and static images
        out.results.extend(check_links(client, home, sorted({link for p in out.pages for link in p.internal_links})[:25]))
        out.results.extend(check_images(client, home, sorted({i for p in out.pages for i in p.images})[:20]))
        out.metrics["pages_sampled"] = len(out.pages)
        return out
    finally:
        client.close()


def check_links(client, home: PageInfo, links: list[str]) -> list[RuleResult]:  # type: ignore[no-untyped-def]
    broken, checked, errors = [], 0, 0
    for link in links:
        r = safe_fetch(link, client=client, method="HEAD", max_redirects=3)
        if r.status in (405, 501):
            r = safe_fetch(link, client=client, method="GET", max_bytes=20_000, max_redirects=3)
        if r.status is None:
            errors += 1
            continue
        checked += 1
        if r.status in (404, 410) or r.status >= 500:
            broken.append({"url": link, "status": r.status})
    if checked == 0:
        return [RuleResult("tech.broken_links", NOT_CHECKED if not links else UNKNOWN, home.url, {"errors": errors})]
    return [RuleResult("tech.broken_links", FAILED if broken else PASSED, home.url,
                       {"checked": checked, "broken": broken[:20]}, params={"count": len(broken)},
                       evidence=[EvidenceItem("network_request", "Broken links", home.url, data={"broken": broken[:20]},
                                              detection_method="http_head")] if broken else [])]


def check_images(client, home: PageInfo, images: list[str]) -> list[RuleResult]:  # type: ignore[no-untyped-def]
    broken, checked = [], 0
    for img in images:
        try:
            validate_url(img)
        except BlockedDestination:
            continue
        r = safe_fetch(img, client=client, method="HEAD", max_redirects=3)
        if r.status is None:
            continue
        checked += 1
        if r.status in (404, 410) or r.status >= 500:
            broken.append({"url": img, "status": r.status})
    if checked == 0:
        return [RuleResult("tech.broken_images", NOT_APPLICABLE if not images else UNKNOWN, home.url)]
    return [RuleResult("tech.broken_images", FAILED if broken else PASSED, home.url,
                       {"checked": checked, "broken": broken[:20]}, params={"count": len(broken)})]


def absolute(base: str, href: str) -> str:
    return urljoin(base, href)


__all__ = ["run_http_stage", "HttpStageOutput", "DETECTED", "NOT_DETECTED", "ERROR"]
