"""Builds the sanitized public data model for a report version.

Only fields on an explicit allow-list are copied. Internal lead/confidence scores, CRM
status, notes, tags, personal contact data, job logs, raw tracking identifiers and
infrastructure details are never included.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.db.models import (
    Advertisement,
    Advertiser,
    AdvertisingProvider,
    AuditFinding,
    AuditRule,
    Company,
    Evidence,
    Report,
    ReportAsset,
    ReportVersion,
    TrackingDetection,
    WebsiteAudit,
)

SECTIONS = ["summary", "performance", "mobile", "seo", "accessibility", "tracking", "screenshots", "advertising",
            "recommendations", "services", "methodology", "notes"]
CATEGORY_SECTION = {"availability": "summary", "technical": "summary", "performance": "performance", "visual": "mobile",
                    "seo": "seo", "accessibility": "accessibility", "conversion": "recommendations", "tracking": "tracking"}
SERVICE_NAMES = {
    "website_design": ("Website design & development", "Web sitesi tasarımı ve geliştirme"),
    "website_redesign": ("Website redesign", "Web sitesi yeniden tasarımı"),
    "landing_page": ("Landing page design", "Açılış sayfası tasarımı"),
    "ui_ux": ("UI/UX design", "UI/UX tasarımı"),
    "graphic_design": ("Graphic design", "Grafik tasarım"),
    "brand_identity": ("Brand identity design", "Marka kimliği tasarımı"),
    "social_media_design": ("Social media design", "Sosyal medya tasarımı"),
    "ad_creative": ("Advertising creative design", "Reklam kreatif tasarımı"),
    "meta_ads": ("Meta Ads management", "Meta Ads yönetimi"),
    "google_ads": ("Google Ads management", "Google Ads yönetimi"),
    "linkedin_ads": ("LinkedIn Ads management", "LinkedIn Ads yönetimi"),
    "conversion_tracking": ("Conversion tracking implementation", "Dönüşüm izleme kurulumu"),
    "technical_seo": ("Technical SEO", "Teknik SEO"),
    "ecommerce_optimization": ("E-commerce optimization", "E-ticaret optimizasyonu"),
}
METHODOLOGY = {
    "en": [
        "This report was produced with deterministic, rule-based checks; no artificial intelligence was used.",
        "Performance figures are Lighthouse laboratory measurements under a simulated mobile profile. They are not real-user field data.",
        "Tracking observations reflect what was visible to a browser at the time of testing. Tags may load only after consent, be implemented server-side, or vary by region; 'not detected' does not prove absence.",
        "Visual findings are measured heuristics confirmed by a reviewer. Advertising observations come from official public transparency sources and do not indicate spend or performance.",
    ],
    "tr": [
        "Bu rapor belirleyici, kural tabanlı kontrollerle hazırlanmıştır; yapay zekâ kullanılmamıştır.",
        "Performans değerleri, simüle edilmiş mobil profilde alınan Lighthouse laboratuvar ölçümleridir. Gerçek kullanıcı saha verisi değildir.",
        "İzleme gözlemleri test anında bir tarayıcının görebildiklerini yansıtır. Etiketler yalnızca onaydan sonra yüklenebilir, sunucu tarafında uygulanabilir veya bölgeye göre değişebilir; 'algılanmadı' yokluğu kanıtlamaz.",
        "Görsel bulgular bir inceleyici tarafından doğrulanan ölçülmüş sezgisel kontrollerdir. Reklam gözlemleri resmi, herkese açık şeffaflık kaynaklarından alınmıştır ve harcama ya da performans göstermez.",
    ],
}


def _fmt(template: str, params: dict[str, Any]) -> str:
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def build_content(db: Session, report: Report) -> tuple[dict[str, Any], list[tuple[str, Evidence]]]:
    company = db.get(Company, report.company_id)
    assert company is not None
    audit = db.scalar(select(WebsiteAudit).where(WebsiteAudit.company_id == company.id,
                                                 WebsiteAudit.status == "completed")
                      .order_by(WebsiteAudit.completed_at.desc()).limit(1))
    sections = [s for s in report.sections if s in SECTIONS]
    content: dict[str, Any] = {
        "schema": 1,
        "title": report.title,
        "company": {"name": company.name, "website": company.website_url if company.website_status != "verified_absent" else None},
        "audit_date": (audit.automated_completed_at or audit.created_at).date().isoformat() if audit else None,
        "updated_at": datetime.now(UTC).date().isoformat(),
        "sections": sections,
        "default_language": report.language,
        "findings": {s: [] for s in ("summary", "performance", "mobile", "seo", "accessibility", "tracking", "recommendations")},
        "branding": {k: v for k, v in (report.branding or {}).items() if k in ("name", "contact", "accent")},
        "attribution": "Map data © OpenStreetMap contributors (ODbL)" if any(
            s.source == "osm" for s in company.sources) else None,
    }
    assets: list[tuple[str, Evidence]] = []
    if audit is not None:
        rules = {r.key: r for r in db.scalars(select(AuditRule))}
        findings = db.scalars(select(AuditFinding).where(AuditFinding.audit_id == audit.id)
                              .order_by(AuditFinding.rule_key)).all()
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        for f in findings:
            rule = rules.get(f.rule_key)
            if rule is None or not rule.public_safe or f.result not in ("passed", "failed"):
                continue
            if f.admin_validated is False:
                continue  # reviewer rejected the finding
            if rule.category == "visual" and f.result == "failed" and f.admin_validated is not True:
                # heuristic visual failures are public only when confirmed in review
                responses_ok = True
                from leadradar.db.models import ReviewResponse

                r = db.scalar(select(ReviewResponse.answer).where(ReviewResponse.audit_id == audit.id,
                                                                  ReviewResponse.question_key == "visual_findings_valid"))
                responses_ok = r == "yes"
                if not responses_ok:
                    continue
            section = CATEGORY_SECTION.get(rule.category, "summary")
            params = dict(f.message_params or {})
            content["findings"][section].append({
                "key": rule.key, "result": f.result, "severity": rule.severity,
                "title": {"en": rule.title_en, "tr": rule.title_tr},
                "description": {"en": rule.description_en, "tr": rule.description_tr},
                "detail": {"en": _fmt(rule.result_template_en, params), "tr": _fmt(rule.result_template_tr, params)}
                if rule.result_template_en else None,
                "recommendation": {"en": rule.recommendation_en, "tr": rule.recommendation_tr}
                if f.result == "failed" and rule.recommendation_en not in ("", "—") else None,
            })
        for sec in content["findings"].values():
            sec.sort(key=lambda x: (x["result"] != "failed", sev_order.get(x["severity"], 9), x["key"]))
        lh = (audit.metrics or {}).get("lighthouse") or {}
        if lh.get("scores"):
            content["performance"] = {
                "measurement": "lab", "scores": lh.get("scores"), "metrics": lh.get("metrics"),
                "context": {k: (audit.context or {}).get("lighthouse", {}).get(k) for k in
                            ("lighthouse_version", "form_factor", "throttling_method", "fetch_time")},
            }
        tracking = db.scalars(select(TrackingDetection).where(TrackingDetection.audit_id == audit.id)).all()
        merged: dict[str, str] = {}
        for t in tracking:
            if t.status == "detected" or t.technology not in merged:
                merged[t.technology] = "detected" if t.status == "detected" or merged.get(t.technology) == "detected" else t.status
        from leadradar.db.models import TrackingTechnology

        names = {t.key: t.name for t in db.scalars(select(TrackingTechnology))}
        # Identifiers are intentionally omitted from public data.
        content["tracking"] = [{"name": names.get(k, k), "status": v} for k, v in sorted(merged.items())]
    if "screenshots" in sections:
        chosen = report.selected_evidence_ids or []
        q = select(Evidence).where(Evidence.company_id == company.id, Evidence.kind == "screenshot",
                                   Evidence.approved_for_reports.is_(True), Evidence.blob_id.isnot(None))
        if chosen:
            q = q.where(Evidence.id.in_(chosen))
        elif audit is not None:
            q = q.where(Evidence.audit_id == audit.id)
        content["screenshots"] = []
        for ev in db.scalars(q.limit(6)):
            pid = secrets.token_urlsafe(18)
            assets.append((pid, ev))
            content["screenshots"].append({"asset": pid, "caption": ev.label, "viewport": ev.viewport})
    if "advertising" in sections and report.selected_ad_ids:
        provs = {p.key: p.name for p in db.scalars(select(AdvertisingProvider))}
        ads = db.scalars(select(Advertisement).join(Advertiser, Advertiser.id == Advertisement.advertiser_id).where(
            Advertisement.id.in_(report.selected_ad_ids), Advertiser.company_id == company.id,
            Advertiser.match_status == "confirmed")).all()
        content["advertising"] = [{"platform": provs.get(a.platform, a.platform), "status": a.status,
                                   "format": a.ad_format, "text": (a.ad_text or "")[:500],
                                   "first_seen": a.source_start_date.isoformat() if a.source_start_date else None}
                                  for a in ads]
    if "services" in sections or "recommendations" in sections:
        svc = sorted(((k, v) for k, v in (company.service_scores or {}).items() if v.get("score", 0) >= 30
                      and not v.get("provisional")), key=lambda kv: -kv[1]["score"])
        content["services"] = [{"key": k, "name": {"en": SERVICE_NAMES.get(k, (k, k))[0], "tr": SERVICE_NAMES.get(k, (k, k))[1]}}
                               for k, _ in svc[:6]]
        from leadradar.db.models import LeadScore

        ls = db.scalar(select(LeadScore).where(LeadScore.company_id == company.id, LeadScore.stage == "final")
                       .order_by(LeadScore.calculated_at.desc()).limit(1))
        recs = [r for r in ((ls.breakdown or {}).get("recommendations") or [] if ls else []) if not r.get("provisional")]
        seen: set[str] = set()
        content["recommendations"] = []
        for r in recs:
            if r["text_en"] in seen:
                continue
            seen.add(r["text_en"])
            content["recommendations"].append({"en": r["text_en"], "tr": r["text_tr"]})
            if len(content["recommendations"]) >= 8:
                break
    if "methodology" in sections:
        content["methodology"] = METHODOLOGY
    if "notes" in sections and report.public_notes:
        content["public_notes"] = report.public_notes[:5000]
    return content, assets


def create_version(db: Session, report: Report) -> ReportVersion:
    content, assets = build_content(db, report)
    last = db.scalar(select(ReportVersion.version).where(ReportVersion.report_id == report.id)
                     .order_by(ReportVersion.version.desc()).limit(1)) or 0
    audit_id = None
    v = ReportVersion(report_id=report.id, version=last + 1, content=content, audit_id=audit_id, status="draft",
                      created_at=datetime.now(UTC))
    db.add(v)
    db.flush()
    for pid, ev in assets:
        db.add(ReportAsset(report_version_id=v.id, kind="screenshot", public_id=pid, blob_id=ev.blob_id,
                           caption=ev.label, created_at=datetime.now(UTC)))
    report.current_version_id = v.id
    db.flush()
    return v
