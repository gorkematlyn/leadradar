"""Lighthouse lab audit via the Node CLI (installed only in the analysis image).

Results are *laboratory* measurements under a simulated mobile profile; they are not
real-user field data (CrUX) and are labelled accordingly everywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - fixed argv, no shell
import tempfile
from dataclasses import dataclass, field
from typing import Any

from leadradar.modules.netsafe.policy import validate_url
from leadradar.modules.netsafe.proxy import get_egress_proxy
from leadradar.modules.website_audit.browser import chromium_args
from leadradar.modules.website_audit.results import (
    ERROR,
    FAILED,
    NOT_CHECKED,
    PASSED,
    UNKNOWN,
    EvidenceItem,
    RuleResult,
)


@dataclass
class LighthouseOutput:
    available: bool
    scores: dict[str, float | None] = field(default_factory=dict)
    metrics: dict[str, float | None] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    results: list[RuleResult] = field(default_factory=list)


def lighthouse_binary() -> str | None:
    return os.environ.get("LIGHTHOUSE_BIN") or shutil.which("lighthouse")


def chrome_path() -> str | None:
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return pw.chromium.executable_path
    except Exception:
        return None


def run_lighthouse(url: str, timeout_s: int = 120) -> LighthouseOutput:
    validate_url(url)
    binary = lighthouse_binary()
    chrome = chrome_path()
    if not binary or not chrome:
        out = LighthouseOutput(False, error="lighthouse or chromium not installed in this worker")
        out.results = [RuleResult(k, NOT_CHECKED, url, {"reason": out.error}) for k in
                       ("perf.lighthouse_performance", "perf.lcp", "perf.cls", "perf.tbt", "a11y.lighthouse_accessibility")]
        return out
    proxy = get_egress_proxy()
    flags = " ".join(["--headless=new", "--no-sandbox" if os.environ.get("LEADRADAR_BROWSER_SANDBOX", "0") != "1" else "",
                      *chromium_args(proxy.url)]).strip()
    with tempfile.TemporaryDirectory(prefix="lr-lh-") as tmp:
        report = os.path.join(tmp, "report.json")
        argv = [binary, url, "--output=json", f"--output-path={report}", "--quiet",
                "--only-categories=performance,accessibility,best-practices,seo", "--form-factor=mobile",
                "--throttling-method=simulate", f"--max-wait-for-load={min(timeout_s, 60) * 1000}",
                f"--chrome-flags={flags}", "--disable-full-page-screenshot"]
        env = {**os.environ, "CHROME_PATH": chrome, "HOME": tmp}
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout_s, env=env, check=False)  # noqa: S603
        except subprocess.TimeoutExpired:
            out = LighthouseOutput(True, error="lighthouse timed out")
            out.results = [RuleResult("perf.lighthouse_performance", ERROR, url, {"error": out.error})]
            return out
        if proc.returncode != 0 or not os.path.exists(report):
            out = LighthouseOutput(True, error=(proc.stderr or b"").decode(errors="ignore")[-400:])
            out.results = [RuleResult("perf.lighthouse_performance", ERROR, url, {"error": out.error})]
            return out
        with open(report, encoding="utf-8") as fh:
            data = json.load(fh)
    return parse_report(url, data)


def parse_report(url: str, data: dict[str, Any]) -> LighthouseOutput:
    cats = data.get("categories", {})
    audits = data.get("audits", {})

    def score(k: str) -> float | None:
        s = (cats.get(k) or {}).get("score")
        return round(s * 100) if isinstance(s, (int, float)) else None

    def metric(k: str) -> float | None:
        v = (audits.get(k) or {}).get("numericValue")
        return round(v, 3) if isinstance(v, (int, float)) else None

    out = LighthouseOutput(True)
    out.scores = {"performance": score("performance"), "accessibility": score("accessibility"),
                  "best_practices": score("best-practices"), "seo": score("seo")}
    out.metrics = {"fcp_ms": metric("first-contentful-paint"), "lcp_ms": metric("largest-contentful-paint"),
                   "cls": metric("cumulative-layout-shift"), "tbt_ms": metric("total-blocking-time"),
                   "speed_index_ms": metric("speed-index")}
    env = data.get("environment", {})
    cfg = data.get("configSettings", {})
    out.context = {
        "measurement": "lab", "lighthouse_version": data.get("lighthouseVersion"),
        "user_agent": env.get("hostUserAgent"), "benchmark_index": env.get("benchmarkIndex"),
        "form_factor": cfg.get("formFactor"), "throttling_method": cfg.get("throttlingMethod"),
        "throttling": cfg.get("throttling"), "screen_emulation": cfg.get("screenEmulation"),
        "fetch_time": data.get("fetchTime"), "final_url": data.get("finalDisplayedUrl") or data.get("finalUrl"),
    }
    ev = EvidenceItem("lighthouse", "Lighthouse lab summary", url, data={"scores": out.scores, "metrics": out.metrics,
                      "context": out.context}, detection_method="lighthouse",
                      limitations="Laboratory measurement under simulated throttling; not real-user field data.")
    perf = out.scores["performance"]
    out.results.append(RuleResult("perf.lighthouse_performance", UNKNOWN if perf is None else (PASSED if perf >= 50 else FAILED),
                                  url, {"score": perf}, params={"score": perf}, evidence=[ev]))
    lcp, cls, tbt = out.metrics["lcp_ms"], out.metrics["cls"], out.metrics["tbt_ms"]
    out.results.append(RuleResult("perf.lcp", UNKNOWN if lcp is None else (PASSED if lcp <= 2500 else FAILED), url,
                                  {"lcp_ms": lcp}, params={"seconds": round((lcp or 0) / 1000, 1)}))
    out.results.append(RuleResult("perf.cls", UNKNOWN if cls is None else (PASSED if cls <= 0.1 else FAILED), url,
                                  {"cls": cls}, params={"cls": cls}))
    out.results.append(RuleResult("perf.tbt", UNKNOWN if tbt is None else (PASSED if tbt <= 200 else FAILED), url,
                                  {"tbt_ms": tbt}, params={"ms": tbt}))
    acc = out.scores["accessibility"]
    out.results.append(RuleResult("a11y.lighthouse_accessibility", UNKNOWN if acc is None else
                                  (PASSED if acc >= 80 else FAILED), url, {"score": acc}, params={"score": acc}))
    return out
