"""Deterministic OSM tag → industry matching using rules stored in the database."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class CompiledRule:
    industry_key: str
    rule_key: str
    classification: str
    all: tuple[tuple[str, str, Any], ...]
    any: tuple[tuple[str, str, Any], ...]
    exclude: tuple[tuple[str, str, Any], ...]


@lru_cache(maxsize=512)
def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _cond(c: dict[str, Any]) -> tuple[str, str, Any]:
    op = c.get("op", "eq")
    value = c.get("value")
    if op == "in":
        value = tuple(value or ())
    if op == "regex":
        _regex(value)  # validate early
    return (c["key"], op, value)


def compile_rules(rules: list[dict[str, Any]]) -> list[CompiledRule]:
    """``rules`` items: {industry_key, rule_key, classification, conditions}."""
    out = []
    for r in rules:
        cond = r["conditions"] or {}
        out.append(
            CompiledRule(
                industry_key=r["industry_key"],
                rule_key=r["rule_key"],
                classification=r.get("classification", "confident"),
                all=tuple(_cond(c) for c in cond.get("all", [])),
                any=tuple(_cond(c) for c in cond.get("any", [])),
                exclude=tuple(_cond(c) for c in cond.get("exclude", [])),
            )
        )
    return out


def _test(tags: dict[str, str], cond: tuple[str, str, Any]) -> bool:
    key, op, value = cond
    v = tags.get(key)
    if v is None:
        return False
    if op == "exists":
        return True
    if op == "eq":
        return v == value
    if op == "in":
        return v in value
    if op == "regex":
        return bool(_regex(value).search(v))
    return False


def rule_matches(rule: CompiledRule, tags: dict[str, str]) -> bool:
    if not rule.all and not rule.any:
        return False
    if not all(_test(tags, c) for c in rule.all):
        return False
    if rule.any and not any(_test(tags, c) for c in rule.any):
        return False
    return not any(_test(tags, c) for c in rule.exclude)


@dataclass(frozen=True)
class Match:
    industry_key: str
    rule_key: str
    classification: str


def match_industries(rules: list[CompiledRule], tags: dict[str, str]) -> list[Match]:
    """All matching industries; confident matches first. Deterministic order."""
    seen: dict[str, Match] = {}
    for rule in rules:
        if rule_matches(rule, tags):
            prev = seen.get(rule.industry_key)
            if prev is None or (prev.classification == "review" and rule.classification == "confident"):
                seen[rule.industry_key] = Match(rule.industry_key, rule.rule_key, rule.classification)
    return sorted(seen.values(), key=lambda m: (m.classification != "confident", m.industry_key))


def required_keys(rules: list[CompiledRule]) -> set[str]:
    """Tag keys that must be present for any rule to match (for the C++ KeyFilter)."""
    keys: set[str] = set()
    for r in rules:
        conds = [c for c in r.all if c[0] != "name"] or list(r.any)
        if conds:
            keys.add(conds[0][0])
    return keys


def is_chain(tags: dict[str, str]) -> bool:
    return bool(tags.get("brand:wikidata") or tags.get("brand") and tags.get("brand:wikipedia"))


def is_closed(tags: dict[str, str]) -> bool:
    return any(k.startswith(("disused:", "abandoned:", "was:")) for k in tags) or tags.get("opening_hours") == "closed"
