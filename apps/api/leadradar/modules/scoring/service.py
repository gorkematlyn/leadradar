"""Collects evidence-based signals for a company and persists versioned scores.

Recalculation never repeats external research: it only re-reads stored evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.core.app_settings import get_setting
from leadradar.db.models import (
    Advertisement,
    Advertiser,
    AdvertisingResearchRun,
    AuditFinding,
    AuditRule,
    Company,
    CompanySource,
    Country,
    Evidence,
    Industry,
    LeadScore,
    ReviewQuestion,
    ReviewResponse,
    ScoreOverride,
    ScoringProfile,
    ScoringRule,
    ServiceRule,
    ServiceScore,
    SocialProfile,
    TrackingDetection,
    WebsiteAudit,
)
from leadradar.modules.crm.companies import SOURCE_RELIABILITY
from leadradar.modules.scoring.engine import (
    Rule,
    ServiceRuleDef,
    compute_confidence,
    compute_score,
    compute_service_scores,
)
from leadradar.modules.website_audit.results import DETECTED, FAILED, NOT_APPLICABLE, PASSED

AD_SIGNAL = {"meta": "ads.meta_active", "google": "ads.google_active", "linkedin": "ads.linkedin_active",
             "tiktok": "ads.tiktok_active", "microsoft": "ads.microsoft_active"}
B2B_INDUSTRIES = {"b2b_manufacturers", "construction"}
DEFINITIVE = {"passed", "failed", "detected", "not_detected"}


@dataclass
class SignalContext:
    signals: set[str] = field(default_factory=set)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    confidence_components: dict[str, float] = field(default_factory=dict)
    review_completed: bool = False
    audit: WebsiteAudit | None = None

    def add(self, signal: str, ref: str | None = None) -> None:
        self.signals.add(signal)
        if ref:
            self.evidence.setdefault(signal, [])
            if ref not in self.evidence[signal]:
                self.evidence[signal].append(ref)


def latest_audit(db: Session, company: Company) -> WebsiteAudit | None:
    return db.scalar(select(WebsiteAudit).where(
        WebsiteAudit.company_id == company.id, WebsiteAudit.status.in_(["action_required", "completed"])
    ).order_by(WebsiteAudit.created_at.desc()).limit(1))


def collect_signals(db: Session, company: Company, profile: ScoringProfile, stage: str,
                    audit: WebsiteAudit | None = None) -> SignalContext:
    ctx = SignalContext()
    audit = audit or latest_audit(db, company)
    ctx.audit = audit
    industry = db.get(Industry, company.primary_industry_id) if company.primary_industry_id else None
    relevant_industry_key = industry.key if industry else None
    # --- company-level signals ------------------------------------------------------------
    if company.website_status == "verified_absent":
        ctx.add("website.verified_absent", "company.website_status")
    if company.is_chain:
        ctx.add("company.chain", "company.is_chain")
    if company.permanently_closed:
        ctx.add("company.permanently_closed", "company.permanently_closed")
    if company.do_not_contact:
        ctx.add("company.do_not_contact", "suppression")
    if company.rejected:
        ctx.add("company.rejected", "company.rejected")
    if industry is not None and not industry.enabled:
        ctx.add("company.excluded_industry", f"industry:{industry.key}")
    excluded_domains = set(get_setting(db, "scoring.excluded_domains") or [])
    if company.canonical_domain and company.canonical_domain in excluded_domains:
        ctx.add("company.excluded_domain", company.canonical_domain)
    if industry is not None and industry.is_priority:
        ctx.add("fit.priority_industry", f"industry:{industry.key}")
    priority_countries = set(get_setting(db, "discovery.priority_countries") or [])
    country = db.get(Country, company.country_iso2) if company.country_iso2 else None
    if country is not None and (country.is_priority or country.iso2 in priority_countries):
        ctx.add("fit.priority_country", f"country:{country.iso2}")
    if industry is not None:
        focus = set(profile.service_focus or [])
        if not focus or focus & set(industry.relevant_services or []):
            ctx.add("fit.service_match", f"industry:{industry.key}")
        if industry.key in B2B_INDUSTRIES:
            ctx.add("industry.b2b", f"industry:{industry.key}")
    if company.phone:
        ctx.add("contact.phone", "company.phone")
    if company.email and company.email_verified:
        ctx.add("contact.verified_email", "company.email")
    if db.scalar(select(SocialProfile.id).where(SocialProfile.company_id == company.id, SocialProfile.verified.is_(True)).limit(1)):
        ctx.add("contact.verified_social", "social_profiles")
    # --- audit findings -------------------------------------------------------------------
    applicable = 0
    definitive = 0
    failed_ids: list[int] = []
    if audit is not None:
        rules = {r.key: r for r in db.scalars(select(AuditRule))}
        findings = db.scalars(select(AuditFinding).where(AuditFinding.audit_id == audit.id)).all()
        responses = {r.question_key: r.answer for r in db.scalars(
            select(ReviewResponse).where(ReviewResponse.audit_id == audit.id))}
        ctx.review_completed = audit.status == "completed"
        visual_valid = responses.get("visual_findings_valid")
        for f in findings:
            rule = rules.get(f.rule_key)
            if rule is None:
                continue
            if rule.applicable_industries and relevant_industry_key not in rule.applicable_industries:
                continue
            if f.result != NOT_APPLICABLE:
                applicable += 1
                if f.result in DEFINITIVE:
                    definitive += 1
            if f.result != FAILED or f.admin_validated is False:
                continue  # only confirmed failures emit deficiency signals
            failed_ids.append(f.id)
            for sig in rule.emits_signals:
                if sig == "mobile.layout_problems" and stage == "final" and not (
                    f.admin_validated is True or visual_valid == "yes"
                ):
                    continue  # final score requires confirmation of heuristic visual findings
                if sig == "conversion.relevant_deficiency" and f.confidence < 0.7:
                    continue
                ctx.add(sig, f"finding:{f.id}")
        by_key = {f.rule_key: f for f in findings}
        if (by_key.get("conv.contact_form") and by_key["conv.contact_form"].result == PASSED):
            ctx.add("contact.form", f"finding:{by_key['conv.contact_form'].id}")
        if not company.phone and by_key.get("conv.tel_link") and by_key["conv.tel_link"].result == PASSED:
            ctx.add("contact.phone", f"finding:{by_key['conv.tel_link'].id}")
        if by_key.get("conv.email_link") and by_key["conv.email_link"].result == PASSED and company.email:
            ctx.add("contact.verified_email", f"finding:{by_key['conv.email_link'].id}")
        if by_key.get("conv.social_links") and by_key["conv.social_links"].result == DETECTED:
            ctx.add("contact.verified_social", f"finding:{by_key['conv.social_links'].id}")
        eco = by_key.get("conv.ecommerce")
        chk = by_key.get("conv.checkout")
        if (eco and eco.result == DETECTED and eco.confidence >= 0.8) or (chk and chk.result == DETECTED):
            ctx.add("commerce.ecommerce_active", f"finding:{(eco or chk).id}")  # type: ignore[union-attr]
        # Tracking detections (any consent state counts as detected).
        detections = db.scalars(select(TrackingDetection).where(TrackingDetection.audit_id == audit.id)).all()
        status_by_tech: dict[str, str] = {}
        for d in detections:
            if d.status == DETECTED or d.technology not in status_by_tech:
                status_by_tech[d.technology] = d.status if status_by_tech.get(d.technology) != DETECTED else DETECTED
        if status_by_tech.get("meta_pixel") == "not_detected":
            ctx.add("tracking.meta_pixel_not_detected", "tracking:meta_pixel")
        if status_by_tech.get("google_ads_conversion") == "not_detected":
            ctx.add("tracking.google_ads_conversion_not_detected", "tracking:google_ads_conversion")
        # review answers
        questions = {q.key: q for q in db.scalars(select(ReviewQuestion))}
        for key, answer in responses.items():
            q = questions.get(key)
            if q is None:
                continue
            if answer == "yes" and q.yes_signal:
                ctx.add(q.yes_signal, f"review:{key}")
            elif answer == "no" and q.no_signal:
                ctx.add(q.no_signal, f"review:{key}")
    # --- advertising ------------------------------------------------------------------------
    platforms_active = set()
    runs = db.scalars(select(AdvertisingResearchRun).where(AdvertisingResearchRun.company_id == company.id)
                      .order_by(AdvertisingResearchRun.created_at.desc())).all()
    latest_by_platform: dict[str, AdvertisingResearchRun] = {}
    for r in runs:
        latest_by_platform.setdefault(r.platform, r)
    for platform, run in latest_by_platform.items():
        if run.status == "found" and run.active_ads_verified:
            confirmed = db.scalar(select(Advertiser.id).where(Advertiser.company_id == company.id,
                                                              Advertiser.platform == platform,
                                                              Advertiser.match_status == "confirmed").limit(1))
            if confirmed or run.method == "manual":
                platforms_active.add(platform)
                if platform in AD_SIGNAL:
                    ctx.add(AD_SIGNAL[platform], f"ad_run:{run.id}")
    if platforms_active:
        ctx.add("ads.any_active", "advertising")
    if len(platforms_active) >= 2:
        ctx.add("ads.multi_platform", "advertising")
    recent_cut = datetime.now(UTC) - timedelta(days=90)
    recent = db.scalar(select(Advertisement.id).join(Advertiser, Advertiser.id == Advertisement.advertiser_id).where(
        Advertiser.company_id == company.id, Advertiser.match_status == "confirmed",
        Advertisement.last_observed_at >= recent_cut).limit(1))
    if recent or platforms_active:
        ctx.add("commercial.recent_activity", "advertising")
    if platforms_active or "commerce.ecommerce_active" in ctx.signals:
        ctx.add("fit.recurring_potential", "advertising_or_ecommerce")
    # Tracking deficiency in the context of active ads.
    if "ads.meta_active" in ctx.signals and "tracking.meta_pixel_not_detected" in ctx.signals:
        ctx.add("tracking.meaningful_deficiency", "tracking:meta_pixel")
    if "ads.google_active" in ctx.signals and "tracking.google_ads_conversion_not_detected" in ctx.signals:
        ctx.add("tracking.meaningful_deficiency", "tracking:google_ads_conversion")
    # --- confidence components ------------------------------------------------------------
    sources = db.scalars(select(CompanySource.source).where(CompanySource.company_id == company.id)).all()
    c = ctx.confidence_components
    c["source_reliability"] = max((SOURCE_RELIABILITY.get(s, 30) for s in sources), default=30) / 100
    confirmed_fields = any(v.get("confirmed") for v in (company.field_sources or {}).values())
    c["identity_verification"] = 1.0 if confirmed_fields else (0.6 if company.website_status == "verified" else 0.3)
    c["audit_coverage"] = (definitive / applicable) if applicable else (1.0 if company.website_status == "verified_absent" else 0.0)
    if company.website_status == "verified_absent":
        c["website_completeness"] = 1.0
    elif audit is not None:
        m = audit.metrics or {}
        c["website_completeness"] = (0.3 if m.get("http") else 0) + (0.45 if m.get("browser") else 0) + (
            0.25 if (m.get("lighthouse") or {}).get("scores") else 0)
    else:
        c["website_completeness"] = 0.0
    checked = [r for r in latest_by_platform.values() if r.status not in ("not_checked", "error", "rate_limited", "blocked")]
    c["ad_match"] = min(1.0, len(checked) / 3)
    if failed_ids:
        # A failed finding counts as evidenced when it has an evidence item or stored measurements.
        with_items = set(db.scalars(select(Evidence.finding_id).where(Evidence.finding_id.in_(failed_ids))).all())
        with_values = set(db.scalars(select(AuditFinding.id).where(AuditFinding.id.in_(failed_ids),
                                                                   AuditFinding.value != {})).all())
        c["evidence"] = len(with_items | with_values) / len(failed_ids)
    else:
        c["evidence"] = 0.6 if audit is not None else 0.0
    c["review"] = 1.0 if ctx.review_completed else 0.0
    if audit is not None:
        age = (datetime.now(UTC) - (audit.automated_completed_at or audit.created_at)).days
        c["freshness"] = 1.0 if age <= 30 else 0.6 if age <= 90 else 0.3 if age <= 180 else 0.0
    else:
        c["freshness"] = 0.0
    return ctx


def load_profile(db: Session, profile_id: uuid.UUID | None = None, key: str | None = None) -> ScoringProfile:
    prof = None
    if profile_id:
        prof = db.get(ScoringProfile, profile_id)
    if prof is None and key:
        prof = db.scalar(select(ScoringProfile).where(ScoringProfile.key == key))
    if prof is None:
        default_key = get_setting(db, "scoring.default_profile") or "general"
        prof = db.scalar(select(ScoringProfile).where(ScoringProfile.key == default_key)) or db.scalar(
            select(ScoringProfile).where(ScoringProfile.is_default.is_(True)))
    if prof is None:
        raise RuntimeError("no scoring profile configured")
    return prof


def load_rules(db: Session, profile: ScoringProfile) -> list[Rule]:
    return [Rule(r.key, r.kind, r.category, r.signal, r.points, r.title_en, r.title_tr, r.explanation_en,
                 r.explanation_tr, r.exclusive_group, tuple(r.requires_absent or []), r.version)
            for r in db.scalars(select(ScoringRule).where(ScoringRule.profile_id == profile.id, ScoringRule.enabled.is_(True)))]


def load_service_rules(db: Session) -> list[ServiceRuleDef]:
    return [ServiceRuleDef(r.key, r.service, r.signal, r.points, tuple(r.requires_all or []),
                           tuple(r.requires_absent or []), r.needs_review, r.recommendation_en, r.recommendation_tr,
                           r.version)
            for r in db.scalars(select(ServiceRule).where(ServiceRule.enabled.is_(True)))]


def score_company(db: Session, company: Company, *, stage: str | None = None, audit: WebsiteAudit | None = None,
                  profile: ScoringProfile | None = None, persist: bool = True) -> dict[str, Any]:
    if profile is None:
        industry = db.get(Industry, company.primary_industry_id) if company.primary_industry_id else None
        profile = load_profile(db, industry.scoring_profile_id if industry else None)
    audit = audit or latest_audit(db, company)
    if stage is None:
        stage = "final" if audit is not None and audit.status == "completed" else "preliminary"
        if audit is None and company.website_status == "verified_absent":
            stage = "final"
    ctx = collect_signals(db, company, profile, stage, audit)
    confidence, conf_detail = compute_confidence(ctx.confidence_components, profile.confidence_weights)
    result = compute_score(load_rules(db, profile), ctx.signals, profile.category_limits, profile.thresholds,
                           confidence=confidence, min_confidence_for_high=profile.min_confidence_for_high_priority,
                           evidence=ctx.evidence)
    services, recs = compute_service_scores(load_service_rules(db), ctx.signals, ctx.review_completed)
    result.breakdown["confidence"] = {"score": confidence, "components": conf_detail,
                                      "note": "Evidence quality and completeness, not a probability of conversion."}
    result.breakdown["profile"] = {"id": str(profile.id), "key": profile.key, "version": profile.version}
    result.breakdown["stage"] = stage
    result.breakdown["recommendations"] = recs
    now = datetime.now(UTC)
    if persist:
        ls = LeadScore(company_id=company.id, audit_id=audit.id if audit else None, profile_id=profile.id,
                       profile_version=profile.version, stage=stage, score=result.score,
                       classification=result.classification, confidence=confidence, excluded=result.excluded,
                       breakdown=result.breakdown, signals=sorted(ctx.signals), calculated_at=now)
        db.add(ls)
        db.flush()
        for svc, data in services.items():
            db.add(ServiceScore(lead_score_id=ls.id, service=svc, score=data["score"], provisional=data["provisional"],
                                rules=data["rules"]))
        if stage == "final":
            company.final_lead_score = result.score
        else:
            company.preliminary_lead_score = result.score
        company.confidence_score = confidence
        company.service_scores = {k: {"score": v["score"], "provisional": v["provisional"]} for k, v in services.items()}
        override = db.scalar(select(ScoreOverride).where(ScoreOverride.company_id == company.id,
                                                         ScoreOverride.active.is_(True)).order_by(ScoreOverride.created_at.desc()))
        company.effective_lead_score = override.override_score if override else result.score
        company.score_classification = result.classification if not override else classify_override(
            override.override_score, profile, result.excluded)
        db.flush()
    return {"score": result.score, "classification": result.classification, "confidence": confidence,
            "excluded": result.excluded, "breakdown": result.breakdown, "services": services, "stage": stage}


def classify_override(score: int, profile: ScoringProfile, excluded: bool) -> str:
    from leadradar.modules.scoring.engine import classify

    return classify(score, profile.thresholds, 100, 0, excluded)
