"""The JSON examples in docs/osm-rules*.md must be valid rules and behave as documented."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from leadradar.modules.discovery.matching import compile_rules, match_industries, required_keys

DOCS = Path(__file__).resolve().parents[4] / "docs"
FILES = ["osm-rules.md", "osm-rules.tr.md"]


def _rules(name: str) -> list[dict]:
    text = (DOCS / name).read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    return [{"industry_key": "consulting_firms", "rule_key": f"r{i}", "classification": "confident", "conditions": b}
            for i, b in enumerate(blocks)]


@pytest.mark.parametrize("name", FILES)
def test_doc_examples_compile_and_use_structural_keys(name):
    rules = _rules(name)
    assert len(rules) == 3
    compiled = compile_rules(rules)
    # Every example has a structural (non-name) key, so the import pre-filter can select places.
    assert required_keys(compiled) == {"office"}


@pytest.mark.parametrize("name", FILES)
def test_doc_examples_match_as_described(name):
    compiled = compile_rules(_rules(name))

    def hits(tags):
        return {m.rule_key for r in compiled for m in match_industries([r], tags)}

    assert hits({"office": "consulting", "name": "Aksoy Partners"}) == {"r0"}
    assert hits({"office": "consulting"}) == set()  # a name is required
    assert hits({"office": "tax_advisor", "name": "Demir"}) == {"r1"}
    assert hits({"office": "company", "name": "Yılmaz Danışmanlık"}) == {"r2"}
    assert hits({"office": "company", "name": "DANIŞMAN Ltd"}) == {"r2"}
    assert hits({"office": "travel_agent", "name": "Euro Visa Services"}) == {"r2"}
    assert hits({"office": "company", "name": "Big Advisory", "brand:wikidata": "Q1"}) == set()  # chains excluded
    assert hits({"shop": "bakery", "name": "Danışman Fırın"}) == set()
