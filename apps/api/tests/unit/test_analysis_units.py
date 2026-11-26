import json
from pathlib import Path

from leadradar.modules.advertising.providers.base import CompanyQuery
from leadradar.modules.advertising.providers.meta import parse_response
from leadradar.modules.crm.monitoring import diff_snapshots
from leadradar.modules.discovery.geofabrik import Extract, parse_index, plan_extracts
from leadradar.modules.discovery.matching import compile_rules, match_industries
from leadradar.modules.website_audit.engine import content_fingerprint
from leadradar.modules.website_audit.html_checks import (
    conversion_checks,
    parse_page,
    seo_checks,
    structure_checks,
)
from leadradar.modules.website_audit.lighthouse import parse_report
from leadradar.modules.website_audit.tracking import Observation, TechRule, detect
from leadradar.seeds.defaults import INDUSTRIES, TRACKING_TECHNOLOGIES

FIXTURES = Path(__file__).parent.parent / "fixtures"

RULES = compile_rules([{"industry_key": i["key"], "rule_key": r["key"], "classification": r["classification"],
                        "conditions": r["conditions"]} for i in INDUSTRIES for r in i["rules"]])


def test_osm_matching_rules():
    assert match_industries(RULES, {"name": "Smile", "amenity": "dentist"})[0].industry_key == "dental_clinics"
    m = match_industries(RULES, {"name": "Grand", "tourism": "hotel"})
    assert m[0].industry_key == "boutique_hotels" and m[0].classification == "review"
    assert match_industries(RULES, {"name": "Hilton", "tourism": "hotel", "brand": "Hilton"}) == []
    assert match_industries(RULES, {"amenity": "dentist"}) == []  # unnamed
    assert match_industries(RULES, {"name": "Cuts", "shop": "hairdresser"}) == []
    derm = match_industries(RULES, {"name": "Skin", "healthcare": "clinic", "healthcare:speciality": "dermatology"})
    assert derm[0].industry_key == "aesthetic_clinics" and derm[0].classification == "review"
    works = match_industries(RULES, {"name": "Steelworks", "man_made": "works"})
    assert works[0].classification == "review"


def test_osm_extraction_from_generated_pbf(tmp_path):
    import osmium

    path = str(tmp_path / "t.osm.pbf")
    w = osmium.SimpleWriter(path)
    w.add_node(osmium.osm.mutable.Node(id=1, location=(29.0, 41.0), tags={"name": "Smile Dental", "amenity": "dentist",
                                                                           "website": "https://smile.example"}))
    w.add_node(osmium.osm.mutable.Node(id=2, location=(29.001, 41.001), tags={"name": "Tree"}))
    for nid, (lon, lat) in enumerate([(4.0, 52.0), (4.001, 52.0), (4.001, 52.001), (4.0, 52.001)], start=10):
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat)))
    w.add_way(osmium.osm.mutable.Way(id=100, nodes=[10, 11, 12, 13, 10],
                                     tags={"name": "Oak Furniture", "shop": "furniture"}))
    w.close()
    from leadradar.modules.discovery.osm_extract import extract_pois

    pois = {p.source_key: p for p in extract_pois(path, RULES)}
    assert set(pois) == {"node/1", "way/100"}
    way = pois["way/100"]
    assert way.matches[0].industry_key == "furniture"
    assert abs(way.lat - 52.0005) < 1e-6 and abs(way.lon - 4.0005) < 1e-6


def test_geofabrik_plan_splits_large_countries():
    idx = parse_index({"features": [
        {"properties": {"id": "north-america", "urls": {"pbf": "u/na"}}},
        {"properties": {"id": "us", "parent": "north-america", "iso3166-1:alpha2": ["US"], "urls": {"pbf": "u/us"}}},
        {"properties": {"id": "us/texas", "parent": "us", "iso3166-2": ["US-TX"], "urls": {"pbf": "u/tx"}}},
        {"properties": {"id": "us/ohio", "parent": "us", "iso3166-2": ["US-OH"], "urls": {"pbf": "u/oh"}}},
        {"properties": {"id": "netherlands", "parent": "europe", "iso3166-1:alpha2": ["NL"], "urls": {"pbf": "u/nl"}}},
    ]})
    sizes = {"us": 10_000, "us/texas": 600, "us/ohio": 300, "netherlands": 900}

    def sizer(e: Extract) -> Extract:
        e.size = sizes.get(e.id)
        return e

    assert [e.id for e in plan_extracts(idx, "US", 1000, sizer=sizer)] == ["us/ohio", "us/texas"]
    assert [e.id for e in plan_extracts(idx, "NL", 1000, sizer=sizer)] == ["netherlands"]


def test_html_checks_on_fixture():
    html = (FIXTURES / "site_home.html").read_text()
    p = parse_page("https://acme.example/", html)
    res = {r.rule_key: r for r in seo_checks(p) + structure_checks(p, True) + conversion_checks([p], {"booking", "contact_form"})}
    assert res["seo.title"].result == "passed"
    assert res["seo.meta_description"].result == "failed"
    assert res["seo.h1"].result == "failed"  # two H1s
    assert res["tech.viewport_meta"].result == "passed"
    assert res["tech.mixed_content"].result == "failed"
    assert res["conv.tel_link"].result == "passed"
    assert res["conv.booking"].result == "passed"
    assert res["conv.quote_form"].result == "not_applicable"
    assert res["conv.contact_form"].result == "passed"
    assert res["seo.structured_data"].result == "passed"


def test_tracking_detection_and_uncertainty():
    rules = [TechRule(t["key"], t["name"], t["category"], t["script_patterns"], t["network_patterns"], t["html_patterns"],
                      t["runtime_globals"], t["id_patterns"]) for t in TRACKING_TECHNOLOGIES]
    html = (FIXTURES / "site_home.html").read_text()
    obs = Observation(html=html, script_urls=["https://www.googletagmanager.com/gtag/js?id=G-ABC1234567"],
                      network_urls=["https://www.facebook.com/tr?id=123"], runtime_globals={"fbq"}, rendered=True)
    res = {r.technology: r for r in detect(rules, obs)}
    assert res["ga4"].status == "detected"
    assert res["meta_pixel"].status == "detected" and res["meta_pixel"].confidence > 0.9
    assert res["linkedin_insight"].status == "not_detected"
    assert "not proof" in res["linkedin_insight"].limitations
    assert all("1234567890" not in i for i in res["meta_pixel"].identifiers_redacted)
    empty = {r.technology: r for r in detect(rules, Observation())}
    assert empty["ga4"].status == "unknown"


def test_lighthouse_parse_marks_lab_data():
    data = json.loads((FIXTURES / "lighthouse_min.json").read_text())
    out = parse_report("https://acme.example/", data)
    assert out.scores["performance"] == 42 and out.context["measurement"] == "lab"
    res = {r.rule_key: r.result for r in out.results}
    assert res["perf.lighthouse_performance"] == "failed" and res["perf.cls"] == "passed"


def test_meta_parse_requires_confirmation_when_ambiguous():
    q = CompanyQuery("1", "Acme Dental", "acme-dental.nl", None, "NL")
    data = {"data": [
        {"id": "1", "page_id": "p1", "page_name": "Acme Dental", "ad_creative_link_captions": ["acme-dental.nl"]},
        {"id": "2", "page_id": "p2", "page_name": "Acme Dental Group", "ad_creative_link_captions": ["other-shop.nl"]},
    ]}
    res = parse_response(data, q, None, {"countries": ["NL"]})
    assert res.status == "found" and res.advertisers[0].platform_advertiser_id == "p1"
    data["data"][1]["ad_creative_link_captions"] = ["acme-dental.nl"]
    assert parse_response(data, q, None, {"countries": ["NL"]}).status == "match_required"
    assert parse_response({"data": []}, q, None, {}).status == "no_results"


def test_change_detection_ignores_noise():
    a = {"website_url": "u", "reachable": True, "content_fingerprint": content_fingerprint("Hello 2026-01-01 id abcdef0123456789"),
         "performance": 50, "tracking": ["ga4"], "advertising": [], "lead_score": 40, "confidence": 50, "services": [], "source": {}}
    b = dict(a, content_fingerprint=content_fingerprint("Hello 2026-02-07 id 0123456789abcdef"), performance=55, lead_score=43)
    assert diff_snapshots(a, b, 8, 15) == []
    c = dict(a, advertising=["meta"], reachable=False)
    fields = {e["field"]: e for e in diff_snapshots(a, c, 8, 15)}
    assert fields["advertising"]["significance"] == "major" and "availability" in fields
