from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Explicit result states. UNKNOWN / BLOCKED / ERROR / NOT_CHECKED never count as failures.
PASSED = "passed"
FAILED = "failed"
DETECTED = "detected"
NOT_DETECTED = "not_detected"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"
BLOCKED = "blocked"
ERROR = "error"
NOT_CHECKED = "not_checked"

CONFIRMED_DEFICIENCY = {FAILED}
NON_EVIDENCE = {UNKNOWN, BLOCKED, ERROR, NOT_CHECKED, NOT_APPLICABLE}


@dataclass
class EvidenceItem:
    kind: str
    label: str
    source_url: str | None = None
    selector: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    detection_method: str | None = None
    confidence: float | None = None
    limitations: str | None = None
    viewport: str | None = None
    blob: bytes | None = None
    blob_type: str | None = None
    blob_size: tuple[int, int] | None = None


@dataclass
class RuleResult:
    rule_key: str
    result: str
    page_url: str = ""
    value: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)


def merge_results(results: list[RuleResult]) -> dict[str, RuleResult]:
    """Keep one result per (rule, page); a later definitive result replaces an earlier
    non-evidence state (e.g. browser stage resolves an 'unknown')."""
    out: dict[str, RuleResult] = {}
    for r in results:
        key = f"{r.rule_key}|{r.page_url}"
        prev = out.get(key)
        if prev is None or prev.result in NON_EVIDENCE or (r.result not in NON_EVIDENCE and r.result == FAILED):
            out[key] = r
    return out
