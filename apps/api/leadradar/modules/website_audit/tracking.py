"""Tracking technology detection from static HTML, rendered DOM, script URLs, network
requests and runtime globals. A missing client-side signal is reported as
``not_detected`` — never as proof that tracking does not exist."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from leadradar.modules.website_audit.results import DETECTED, NOT_DETECTED, UNKNOWN

LIMITATIONS = (
    "Client-side observation only. Tags may be withheld until consent, loaded conditionally, "
    "restricted by region or browser, or implemented server-side; absence of a signal is not proof of absence."
)


@dataclass
class TechRule:
    key: str
    name: str
    category: str
    script_patterns: list[str]
    network_patterns: list[str]
    html_patterns: list[str]
    runtime_globals: list[str]
    id_patterns: list[str]


@dataclass
class Observation:
    html: str = ""  # static and/or rendered HTML
    script_urls: list[str] = field(default_factory=list)
    network_urls: list[str] = field(default_factory=list)
    runtime_globals: set[str] = field(default_factory=set)
    rendered: bool = False  # True when a browser stage contributed


@dataclass
class TechResult:
    technology: str
    name: str
    category: str
    status: str
    methods: list[str]
    evidence_urls: list[str]
    identifiers_redacted: list[str]
    confidence: float
    limitations: str


def redact_identifier(value: str) -> str:
    """Keep the prefix for readability, replace the rest with a short hash (no raw IDs stored)."""
    prefix = re.match(r"^[A-Z]{1,3}-", value)
    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"{prefix.group(0) if prefix else ''}…{digest}"


def _strip_query(url: str) -> str:
    return url.split("?")[0][:300]


def detect(rules: list[TechRule], obs: Observation) -> list[TechResult]:
    out: list[TechResult] = []
    for r in rules:
        methods: list[str] = []
        urls: list[str] = []
        for pat in r.script_patterns:
            hit = next((u for u in obs.script_urls if re.search(pat, u, re.IGNORECASE)), None)
            if hit:
                methods.append("script_url")
                urls.append(_strip_query(hit))
                break
        for pat in r.network_patterns:
            hit = next((u for u in obs.network_urls if re.search(pat, u, re.IGNORECASE)), None)
            if hit:
                methods.append("network_request")
                urls.append(_strip_query(hit))
                break
        for pat in r.html_patterns:
            if re.search(pat, obs.html, re.IGNORECASE):
                methods.append("html_pattern")
                break
        if any(g in obs.runtime_globals for g in r.runtime_globals):
            methods.append("runtime_global")
        ids: list[str] = []
        for pat in r.id_patterns:
            for m in re.finditer(pat, obs.html):
                ident = m.group(1) if m.groups() else m.group(0)
                red = redact_identifier(ident)
                if red not in ids:
                    ids.append(red)
                if len(ids) >= 3:
                    break
        if methods:
            # Network/runtime evidence shows the tag actually executed; HTML-only is weaker.
            conf = 0.95 if ("network_request" in methods or "runtime_global" in methods) else 0.75
            status = DETECTED
        else:
            conf = 0.6 if obs.rendered else 0.35
            status = NOT_DETECTED if obs.html else UNKNOWN
        out.append(TechResult(r.key, r.name, r.category, status, sorted(set(methods)), urls[:5], ids, conf, LIMITATIONS))
    return out
