from leadradar.modules.scoring.engine import (
    Rule,
    ServiceRuleDef,
    classify,
    compute_confidence,
    compute_score,
    compute_service_scores,
)
from leadradar.seeds.defaults import CATEGORY_LIMITS, SCORING_RULES, THRESHOLDS

RULES = [Rule(r["key"], r["kind"], r["category"], r["signal"], r["points"], r["title_en"], r["title_tr"],
              exclusive_group=r["exclusive_group"], requires_absent=tuple(r["requires_absent"])) for r in SCORING_RULES]


def score(signals, confidence=80):
    return compute_score(RULES, set(signals), CATEGORY_LIMITS, THRESHOLDS, confidence=confidence)


def test_category_limit_is_enforced():
    res = score(["mobile.layout_problems", "perf.score_below_50", "technical.critical_problems",
                 "conversion.relevant_deficiency", "tracking.meaningful_deficiency", "seo.basic_problems",
                 "review.visual_redesign"])
    cat = res.breakdown["categories"]["service_need"]
    assert cat["raw"] > 35 and cat["score"] == 35 and cat["capped"]


def test_no_website_blocks_website_failure_points():
    res = score(["website.verified_absent", "mobile.layout_problems", "perf.score_below_50", "seo.basic_problems"])
    rules = {r["key"] for r in res.breakdown["categories"]["service_need"]["rules"]}
    assert rules == {"need.no_website"}
    assert res.breakdown["categories"]["service_need"]["score"] == 20


def test_exclusive_group_keeps_largest_contribution_only():
    res = score(["website.verified_absent", "technical.critical_problems"])
    keys = [r["key"] for r in res.breakdown["categories"]["service_need"]["rules"]]
    assert keys == ["need.no_website"]


def test_commercial_activity_and_multi_platform():
    res = score(["ads.meta_active", "ads.google_active", "ads.multi_platform", "commercial.recent_activity"])
    assert res.breakdown["categories"]["commercial_activity"]["score"] == 30  # 34 capped at 30


def test_penalties_and_clamp():
    res = score(["company.chain", "review.unsuitable", "contact.phone"])
    assert res.score == 0  # 3 - 35 clamped
    assert res.breakdown["penalty_total"] == 35


def test_exclusion_takes_precedence():
    res = score(["ads.meta_active", "ads.google_active", "fit.priority_industry", "company.do_not_contact"])
    assert res.excluded and res.classification == "excluded"


def test_unknown_results_generate_no_points():
    res = score([])
    assert res.score == 0 and res.classification == "low_priority"


def test_low_confidence_never_auto_high_priority():
    signals = ["website.verified_absent", "ads.meta_active", "ads.google_active", "ads.multi_platform",
               "commercial.recent_activity", "fit.priority_industry", "fit.priority_country", "fit.service_match",
               "fit.recurring_potential", "contact.verified_email", "contact.phone", "contact.form", "contact.verified_social",
               "review.brand_improvement", "review.creative_improvement", "review.social_design"]
    high = score(signals, confidence=90)
    low = score(signals, confidence=20)
    assert high.score >= 80 and high.classification == "high_priority"
    assert low.score == high.score and low.classification == "requires_review"


def test_thresholds():
    assert classify(80, THRESHOLDS, 100, 50, False) == "high_priority"
    assert classify(60, THRESHOLDS, 100, 50, False) == "strong_potential"
    assert classify(40, THRESHOLDS, 100, 50, False) == "requires_review"
    assert classify(39, THRESHOLDS, 100, 50, False) == "low_priority"


def test_determinism():
    s = ["ads.meta_active", "seo.basic_problems", "contact.phone"]
    assert score(s).breakdown == score(list(reversed(s))).breakdown


def test_confidence_excludes_nothing_and_is_bounded():
    val, detail = compute_confidence({"a": 1.0, "b": 0.0, "c": 2.0}, {"a": 50, "b": 50, "c": 0})
    assert val == 50 and detail["c"]["weight"] == 0


def test_service_rules_combined_and_provisional():
    rules = [
        ServiceRuleDef("x", "meta_ads", "ads.meta_active", 30, requires_all=("tracking.meta_pixel_not_detected",)),
        ServiceRuleDef("y", "brand_identity", "review.brand_improvement", 60, needs_review=True),
    ]
    svc, recs = compute_service_scores(rules, {"ads.meta_active"}, False)
    assert "meta_ads" not in svc
    svc, recs = compute_service_scores(rules, {"ads.meta_active", "tracking.meta_pixel_not_detected",
                                               "review.brand_improvement"}, False)
    assert svc["meta_ads"]["score"] == 30 and not svc["meta_ads"]["provisional"]
    assert svc["brand_identity"]["provisional"]
    svc, _ = compute_service_scores(rules, {"review.brand_improvement"}, True)
    assert not svc["brand_identity"]["provisional"]
