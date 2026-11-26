"""Explainable, deterministic lead scoring.

    Category score = min(category maximum, sum of valid rule contributions)
    Lead score     = clamp(sum(category scores) - penalties, 0, 100)

* A rule contributes only if its signal is present and none of ``requires_absent`` is.
* Within an ``exclusive_group`` only the largest contribution counts (no double scoring
  of overlapping problems).
* Exclusions take precedence: an excluded company is classified ``excluded``.
* Signals are only emitted from confirmed evidence; unknown/blocked/unsupported/unchecked
  results never produce deficiency signals (see :mod:`signals`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Rule:
    key: str
    kind: str  # contribution | penalty | exclusion
    category: str | None
    signal: str
    points: int
    title_en: str
    title_tr: str
    explanation_en: str = ""
    explanation_tr: str = ""
    exclusive_group: str | None = None
    requires_absent: tuple[str, ...] = ()
    version: int = 1


@dataclass(frozen=True)
class ServiceRuleDef:
    key: str
    service: str
    signal: str
    points: int
    requires_all: tuple[str, ...] = ()
    requires_absent: tuple[str, ...] = ()
    needs_review: bool = False
    recommendation_en: str = ""
    recommendation_tr: str = ""
    version: int = 1


@dataclass
class ScoreResult:
    score: int
    classification: str
    excluded: bool
    breakdown: dict[str, Any]
    service_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    recommendations: list[dict[str, Any]] = field(default_factory=list)


def _applies(signal: str, requires_absent: tuple[str, ...], signals: set[str]) -> bool:
    return signal in signals and not any(s in signals for s in requires_absent)


def classify(score: int, thresholds: dict[str, int], confidence: int, min_conf_high: int, excluded: bool) -> str:
    if excluded:
        return "excluded"
    if score >= thresholds["high_priority"]:
        # Low-confidence companies are never auto-classified as high priority.
        return "high_priority" if confidence >= min_conf_high else "requires_review"
    if score >= thresholds["strong_potential"]:
        return "strong_potential"
    if score >= thresholds["requires_review"]:
        return "requires_review"
    return "low_priority"


def compute_score(
    rules: list[Rule],
    signals: set[str],
    category_limits: dict[str, int],
    thresholds: dict[str, int],
    *,
    confidence: int,
    min_confidence_for_high: int = 50,
    evidence: dict[str, list[str]] | None = None,
) -> ScoreResult:
    evidence = evidence or {}
    exclusions = [r for r in rules if r.kind == "exclusion" and r.signal in signals]
    penalties = [r for r in rules if r.kind == "penalty" and _applies(r.signal, r.requires_absent, signals)]
    contribs = [r for r in rules if r.kind == "contribution" and _applies(r.signal, r.requires_absent, signals)]
    # Exclusive groups: keep the highest-point rule per (category, group).
    best: dict[tuple[str | None, str], Rule] = {}
    applied: list[Rule] = []
    suppressed: list[dict[str, Any]] = []
    for r in sorted(contribs, key=lambda r: (-r.points, r.key)):
        if r.exclusive_group:
            k = (r.category, r.exclusive_group)
            if k in best:
                suppressed.append({"key": r.key, "reason": f"exclusive_group:{r.exclusive_group}", "kept": best[k].key})
                continue
            best[k] = r
        applied.append(r)
    categories: dict[str, dict[str, Any]] = {}
    for cat, limit in category_limits.items():
        items = [r for r in applied if r.category == cat]
        raw = sum(r.points for r in items)
        categories[cat] = {
            "limit": limit, "raw": raw, "score": min(limit, raw), "capped": raw > limit,
            "rules": [_rule_view(r, evidence) for r in sorted(items, key=lambda r: r.key)],
        }
    subtotal = sum(c["score"] for c in categories.values())
    penalty_total = sum(abs(r.points) for r in penalties)
    score = max(0, min(100, subtotal - penalty_total))
    excluded = bool(exclusions)
    breakdown = {
        "formula": "clamp(sum(min(limit, contributions)) - penalties, 0, 100)",
        "categories": categories,
        "subtotal": subtotal,
        "penalties": [_rule_view(r, evidence) for r in penalties],
        "penalty_total": penalty_total,
        "exclusions": [_rule_view(r, evidence) for r in exclusions],
        "suppressed_overlaps": suppressed,
        "signals": sorted(signals),
    }
    return ScoreResult(score, classify(score, thresholds, confidence, min_confidence_for_high, excluded), excluded, breakdown)


def _rule_view(r: Rule, evidence: dict[str, list[str]]) -> dict[str, Any]:
    return {"key": r.key, "signal": r.signal, "points": r.points, "title_en": r.title_en, "title_tr": r.title_tr,
            "explanation_en": r.explanation_en, "explanation_tr": r.explanation_tr, "version": r.version,
            "evidence": evidence.get(r.signal, [])[:10]}


def compute_service_scores(rules: list[ServiceRuleDef], signals: set[str], review_completed: bool) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    services: dict[str, dict[str, Any]] = {}
    recs: list[dict[str, Any]] = []
    for r in sorted(rules, key=lambda r: r.key):
        if not _applies(r.signal, r.requires_absent, signals):
            continue
        if any(s not in signals for s in r.requires_all):
            continue
        s = services.setdefault(r.service, {"score": 0, "provisional": False, "rules": []})
        s["score"] = min(100, s["score"] + r.points)
        if r.needs_review and not review_completed:
            s["provisional"] = True
        s["rules"].append({"key": r.key, "points": r.points, "signal": r.signal, "requires_all": list(r.requires_all),
                           "needs_review": r.needs_review, "version": r.version})
        recs.append({"service": r.service, "rule": r.key, "points": r.points, "text_en": r.recommendation_en,
                     "text_tr": r.recommendation_tr, "provisional": r.needs_review and not review_completed})
    # Services relying only on heuristic evidence before review stay provisional.
    for s in services.values():
        if not review_completed and all(x["needs_review"] or x["signal"].startswith(("mobile.", "review.")) for x in s["rules"]):
            s["provisional"] = True
    recs.sort(key=lambda x: (-services[x["service"]]["score"], x["service"], -x["points"]))
    return services, recs


def compute_confidence(components: dict[str, float], weights: dict[str, int]) -> tuple[int, dict[str, Any]]:
    total_w = sum(weights.values()) or 1
    value = sum(max(0.0, min(1.0, components.get(k, 0.0))) * w for k, w in weights.items()) / total_w
    detail = {k: {"value": round(components.get(k, 0.0), 3), "weight": w} for k, w in weights.items()}
    return round(value * 100), detail
