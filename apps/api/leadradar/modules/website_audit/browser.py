"""Playwright rendering stage (heavy). One isolated context per viewport; every request
goes through the egress proxy; downloads, permissions and service workers disabled;
no form submission, no navigation clicks (the only click is an optional, documented
cookie-consent "accept" test that never submits forms)."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from leadradar.modules.netsafe.policy import BlockedDestination, validate_url
from leadradar.modules.netsafe.proxy import get_egress_proxy
from leadradar.modules.website_audit.results import (
    BLOCKED,
    DETECTED,
    ERROR,
    FAILED,
    NOT_APPLICABLE,
    NOT_DETECTED,
    PASSED,
    UNKNOWN,
    EvidenceItem,
    RuleResult,
)

log = logging.getLogger(__name__)

CONSENT_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept", "button[data-testid=uc-accept-all-button]", ".cky-btn-accept",
    "#didomi-notice-agree-button", ".cmplz-accept", "#cookie_action_close_header", ".cc-allow", ".cc-accept",
]

AXE_PATHS = [os.environ.get("AXE_CORE_PATH", ""), "/opt/axe/node_modules/axe-core/axe.min.js",
             "/usr/lib/node_modules/axe-core/axe.min.js"]

CLS_INIT = """
window.__lrCLS = 0;
try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { if (!e.hadRecentInput) window.__lrCLS += e.value; } })
  .observe({type: 'layout-shift', buffered: true}); } catch (e) {}
"""


@dataclass
class ViewportRun:
    name: str
    width: int
    height: int
    status: int | None = None
    final_url: str | None = None
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[dict] = field(default_factory=list)
    network_urls: list[str] = field(default_factory=list)
    script_urls: list[str] = field(default_factory=list)
    measure: dict[str, Any] = field(default_factory=dict)
    axe: dict[str, Any] | None = None
    screenshot: bytes | None = None
    screenshot_size: tuple[int, int] | None = None
    rendered_html: str = ""
    error: str | None = None
    consent_after_urls: list[str] = field(default_factory=list)
    consent_after_globals: list[str] = field(default_factory=list)
    consent_clicked: str | None = None


@dataclass
class BrowserOutput:
    runs: list[ViewportRun]
    browser_version: str | None
    results: list[RuleResult]


def _viewport(spec: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        w, h = spec.lower().split("x")
        return int(w), int(h)
    except ValueError:
        return default


def to_webp(png_or_jpeg: bytes, max_bytes: int) -> tuple[bytes, tuple[int, int]]:
    from PIL import Image

    img = Image.open(io.BytesIO(png_or_jpeg)).convert("RGB")
    size = img.size
    for quality in (72, 60, 48, 36):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=4)
        if buf.tell() <= max_bytes:
            return buf.getvalue(), size
        if quality == 48:
            img = img.resize((max(1, size[0] * 3 // 4), max(1, size[1] * 3 // 4)))
            size = img.size
    return buf.getvalue(), size


def _axe_source() -> str | None:
    for p in AXE_PATHS:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return fh.read()
    return None


def chromium_args(proxy_url: str) -> list[str]:
    return [
        f"--proxy-server={proxy_url}",
        "--proxy-bypass-list=<-loopback>",  # also proxy (and therefore refuse) loopback
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--no-first-run",
        "--mute-audio",
        "--disable-features=Translate,MediaRouter,OptimizationHints",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--force-webrtc-ip-handling-policy",
    ]


def run_browser_stage(url: str, *, desktop: str, mobile: str, timeout_s: int, max_screenshot_bytes: int,
                      screenshots: int, consent_test: bool) -> BrowserOutput:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    validate_url(url)
    proxy = get_egress_proxy()
    measure_js = resources.files("leadradar.modules.website_audit").joinpath("browser_measure.js").read_text("utf-8")
    axe_src = _axe_source()
    runs: list[ViewportRun] = []
    version = None
    sandbox = os.environ.get("LEADRADAR_BROWSER_SANDBOX", "0") == "1"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=chromium_args(proxy.url), chromium_sandbox=sandbox,
                                     timeout=30_000, executable_path=os.environ.get("CHROME_PATH") or None)
        version = browser.version
        try:
            specs = [("mobile", *_viewport(mobile, (390, 844)), True), ("desktop", *_viewport(desktop, (1366, 900)), False)]
            for idx, (name, w, h, is_mobile) in enumerate(specs):
                run = ViewportRun(name, w, h)
                runs.append(run)
                ctx = browser.new_context(
                    viewport={"width": w, "height": h}, is_mobile=is_mobile, has_touch=is_mobile,
                    device_scale_factor=2 if is_mobile else 1, accept_downloads=False, java_script_enabled=True,
                    service_workers="block", ignore_https_errors=False, permissions=[],
                    user_agent=None if not is_mobile else (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1 LeadRadarAudit/1.0"),
                )
                ctx.set_default_timeout(timeout_s * 1000)
                ctx.add_init_script(CLS_INIT)
                page = ctx.new_page()

                def on_console(msg, run=run):  # type: ignore[no-untyped-def]
                    if msg.type == "error" and len(run.console_errors) < 30:
                        run.console_errors.append(msg.text[:300])

                page.on("console", on_console)
                page.on("pageerror", lambda exc, run=run: len(run.page_errors) < 30 and run.page_errors.append(str(exc)[:300]))
                page.on("request", lambda req, run=run: len(run.network_urls) < 2000 and run.network_urls.append(req.url[:500]))

                def on_failed(req, run=run):  # type: ignore[no-untyped-def]
                    if len(run.failed_requests) < 50:
                        run.failed_requests.append({"url": req.url[:300], "type": req.resource_type,
                                                    "error": (req.failure or "")[:120]})

                page.on("requestfailed", on_failed)

                def on_response(resp, run=run):  # type: ignore[no-untyped-def]
                    if resp.status >= 400 and len(run.failed_requests) < 50:
                        run.failed_requests.append({"url": resp.url[:300], "type": resp.request.resource_type,
                                                    "status": resp.status})
                    if resp.request.resource_type == "script":
                        run.script_urls.append(resp.url[:500])

                page.on("response", on_response)
                # Never follow navigations to blocked destinations or non-http(s) schemes.
                page.on("download", lambda d: d.cancel())
                try:
                    resp = page.goto(url, wait_until="load", timeout=timeout_s * 1000)
                    run.status = resp.status if resp else None
                    run.final_url = page.url
                    try:
                        validate_url(page.url)
                    except BlockedDestination:
                        run.error = "redirected to blocked destination"
                        ctx.close()
                        continue
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except PlaywrightError:
                        pass
                    page.wait_for_timeout(1500)
                    run.measure = page.evaluate(measure_js)
                    run.rendered_html = page.content()[:1_500_000]
                    if axe_src:
                        try:
                            page.add_script_tag(content=axe_src)
                            run.axe = page.evaluate(
                                "async () => { const r = await axe.run(document, {resultTypes: ['violations'], "
                                "runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}}); return {violations: r.violations.map(v => "
                                "({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 5).map(n => n.target.join(' '))}))}; }"
                            )
                        except PlaywrightError as exc:
                            run.axe = {"error": str(exc)[:200]}
                    if idx < max(screenshots, 0):
                        shot = page.screenshot(type="jpeg", quality=85, full_page=False, timeout=15000)
                        run.screenshot, run.screenshot_size = to_webp(shot, max_screenshot_bytes)
                    if consent_test and name == "desktop":
                        for selector in CONSENT_ACCEPT_SELECTORS:
                            el = page.query_selector(selector)
                            if el and el.is_visible():
                                before = len(run.network_urls)
                                el.click(timeout=3000, no_wait_after=True)
                                page.wait_for_timeout(3500)
                                run.consent_clicked = selector
                                run.consent_after_urls = run.network_urls[before:]
                                run.consent_after_globals = page.evaluate(
                                    "() => ['fbq','ttq','uetq','pintrk','clarity','hj','google_tag_manager','gtag',"
                                    "'_linkedin_data_partner_ids'].filter(g => typeof window[g] !== 'undefined')")
                                break
                except PlaywrightError as exc:
                    run.error = str(exc).splitlines()[0][:300]
                finally:
                    ctx.close()
        finally:
            browser.close()
    return BrowserOutput(runs, version, evaluate_runs(runs))


def _ev(run: ViewportRun, label: str, data: dict, selector: str | None = None, method: str = "dom_measurement",
        limitations: str | None = None) -> EvidenceItem:
    return EvidenceItem("dom_measurement", label, run.final_url, selector, data, method, None, limitations, run.name)


HEURISTIC = "Deterministic heuristic; confirm visually in review before treating as a defect."


def evaluate_runs(runs: list[ViewportRun]) -> list[RuleResult]:
    out: list[RuleResult] = []
    mobile = next((r for r in runs if r.name == "mobile"), None)
    desktop = next((r for r in runs if r.name == "desktop"), None)
    ok_runs = [r for r in runs if r.measure]
    if not ok_runs:
        err = "; ".join(filter(None, (r.error for r in runs))) or "render failed"
        state = BLOCKED if "blocked" in err.lower() or "ERR_TUNNEL" in err or "403" in err else ERROR
        for key in ("visual.horizontal_overflow", "visual.small_text", "visual.tap_targets", "tech.js_errors",
                    "tech.failed_requests", "a11y.axe"):
            out.append(RuleResult(key, state, runs[0].final_url or "" if runs else "", {"error": err}))
        return out
    page_url = (mobile or desktop).final_url or ""  # type: ignore[union-attr]
    if mobile and mobile.measure:
        m = mobile.measure
        vw = m["viewport"]["width"]
        overflow_px = m["viewport"]["scrollWidth"] - vw
        has_overflow = overflow_px > 8 and bool(m["overflow"])
        out.append(RuleResult("visual.horizontal_overflow", FAILED if has_overflow else PASSED, page_url,
                              {"overflow_px": overflow_px, "offenders": m["overflow"]}, 0.85, {"px": overflow_px},
                              [_ev(mobile, "Horizontal overflow", {"scrollWidth": m["viewport"]["scrollWidth"],
                                   "viewportWidth": vw, "offenders": m["overflow"]},
                                   m["overflow"][0]["selector"] if m["overflow"] else None, limitations=HEURISTIC)]
                              if has_overflow else []))
        ratio = m["smallText"] / m["textElements"] if m["textElements"] else 0
        out.append(RuleResult("visual.small_text", FAILED if ratio > 0.2 else PASSED, page_url,
                              {"ratio": round(ratio, 2), "examples": m["smallTextExamples"]}, 0.8,
                              {"percent": round(ratio * 100)},
                              [_ev(mobile, "Small text", {"ratio": ratio, "examples": m["smallTextExamples"]},
                                   limitations=HEURISTIC)] if ratio > 0.2 else []))
        small_ratio = m["smallTargetCount"] / m["interactiveCount"] if m["interactiveCount"] else 0
        out.append(RuleResult("visual.tap_targets", FAILED if small_ratio > 0.25 and m["smallTargetCount"] >= 5 else PASSED,
                              page_url, {"small": m["smallTargetCount"], "total": m["interactiveCount"],
                                         "examples": m["smallTargets"]}, 0.75, {"count": m["smallTargetCount"]}))
        out.append(RuleResult("visual.overlapping", FAILED if len(m["overlaps"]) >= 2 else PASSED, page_url,
                              {"overlaps": m["overlaps"]}, 0.6))
        out.append(RuleResult("visual.clipped_text", FAILED if len(m["clipped"]) >= 3 else PASSED, page_url,
                              {"clipped": m["clipped"]}, 0.6))
        out.append(RuleResult("visual.offscreen_elements", FAILED if len(m["offscreen"]) >= 3 else PASSED, page_url,
                              {"elements": m["offscreen"]}, 0.6))
        navs = m["nav"]
        crowded = [n for n in navs if n["width"] > vw + 4 or (n["visibleLinks"] > 7 and n["rows"] > 2)]
        out.append(RuleResult("visual.mobile_navigation", NOT_APPLICABLE if not navs else
                              (FAILED if crowded and not m["navToggle"] else PASSED), page_url,
                              {"nav": navs, "toggle": m["navToggle"]}, 0.6))
        non_cookie = [o for o in m["overlays"] if not o["cookie"]]
        out.append(RuleResult("visual.blocking_overlay", FAILED if non_cookie else PASSED, page_url,
                              {"overlays": m["overlays"]}, 0.7))
    for run in ok_runs:
        m = run.measure
        if m["brokenImages"]:
            out.append(RuleResult("tech.broken_images", FAILED, run.final_url or "", {"broken": m["brokenImages"]},
                                  params={"count": len(m["brokenImages"])}))
    font_errors = sum(r.measure.get("fontErrors", 0) for r in ok_runs)
    out.append(RuleResult("visual.font_loading", FAILED if font_errors else PASSED, page_url, {"errors": font_errors}))
    js = [e for r in ok_runs for e in r.page_errors]
    out.append(RuleResult("tech.js_errors", FAILED if js else PASSED, page_url, {"errors": js[:10],
                          "console_errors": [e for r in ok_runs for e in r.console_errors][:10]},
                          params={"count": len(js)},
                          evidence=[EvidenceItem("dom_measurement", "JavaScript errors", page_url,
                                                 data={"errors": js[:10]}, detection_method="pageerror")] if js else []))
    first_party = [f for r in ok_runs for f in r.failed_requests
                   if f.get("type") in ("script", "stylesheet", "font", "image", "document") and f.get("status", 500) != 403
                   and "net::ERR_ABORTED" not in f.get("error", "")]
    out.append(RuleResult("tech.failed_requests", FAILED if len(first_party) >= 2 else PASSED, page_url,
                          {"failed": first_party[:20]}, params={"count": len(first_party)}))
    axe_runs = [r for r in ok_runs if r.axe and "violations" in r.axe]
    if axe_runs:
        violations = {v["id"]: v for r in axe_runs for v in r.axe["violations"]}  # type: ignore[index]
        serious = [v for v in violations.values() if v.get("impact") in ("serious", "critical")]
        contrast = violations.get("color-contrast")
        out.append(RuleResult("a11y.axe", FAILED if serious else PASSED, page_url,
                              {"violations": list(violations.values())[:20]}, params={"count": len(serious)},
                              evidence=[EvidenceItem("dom_measurement", "axe-core violations", page_url,
                                                     data={"violations": serious[:10]}, detection_method="axe-core",
                                                     limitations="axe-core covers a subset of WCAG; automated checks cannot assess all criteria.")]
                              if serious else []))
        out.append(RuleResult("visual.contrast", FAILED if contrast else PASSED, page_url,
                              {"nodes": contrast["nodes"] if contrast else []}))
    else:
        out.append(RuleResult("a11y.axe", UNKNOWN, page_url, {"reason": "axe-core unavailable"}))
        out.append(RuleResult("visual.contrast", UNKNOWN, page_url))
    return out


__all__ = ["run_browser_stage", "BrowserOutput", "ViewportRun", "DETECTED", "NOT_DETECTED"]
