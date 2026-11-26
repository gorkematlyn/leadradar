"""Multi-stage website audit orchestration and persistence.

Stages: HTTP (always) → static HTML checks → [full mode] Playwright render + axe +
screenshots + consent test → [full mode, optional] Lighthouse → tracking detection →
persist findings/evidence → preliminary score → Action Required (worker released).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import select

from leadradar.core.app_settings import get_settings_map
from leadradar.db.models import (
    AuditFinding,
    AuditRule,
    Company,
    Evidence,
    EvidenceBlob,
    Industry,
    SocialProfile,
    TrackingDetection,
    TrackingTechnology,
    WebsiteAudit,
    WebsiteProperty,
)
from leadradar.db.session import session_scope
from leadradar.modules.crm.normalize import detect_social, normalize_url
from leadradar.modules.website_audit import tracking as trk
from leadradar.modules.website_audit.html_checks import (
    conversion_checks,
    detect_platforms,
    seo_checks,
    structure_checks,
)
from leadradar.modules.website_audit.http_stage import run_http_stage
from leadradar.modules.website_audit.results import (
    BLOCKED,
    DETECTED,
    ERROR,
    FAILED,
    NOT_CHECKED,
    NOT_DETECTED,
    PASSED,
    UNKNOWN,
    EvidenceItem,
    RuleResult,
    merge_results,
)

ANALYTICS_TECH = {"ga4", "gtm", "microsoft_clarity", "hotjar"}


def now() -> datetime:
    return datetime.now(UTC)


def content_fingerprint(text: str) -> str:
    """Normalized fingerprint robust to timestamps, numbers, ids and whitespace."""
    t = text.lower()
    t = re.sub(r"\b[0-9a-f]{8,}\b", " ", t)
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"(cookie|çerez|consent|gdpr|kvkk)[^.]{0,200}", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t[:50_000].encode()).hexdigest()


def tracking_rules(db) -> list[trk.TechRule]:  # type: ignore[no-untyped-def]
    return [trk.TechRule(t.key, t.name, t.category, list(t.script_patterns), list(t.network_patterns),
                         list(t.html_patterns), list(t.runtime_globals), list(t.id_patterns))
            for t in db.scalars(select(TrackingTechnology).where(TrackingTechnology.enabled.is_(True)))]


def _store_blob(db, data: bytes, content_type: str, size: tuple[int, int] | None, retain_days: int) -> EvidenceBlob:  # type: ignore[no-untyped-def]
    digest = hashlib.sha256(data).hexdigest()
    blob = EvidenceBlob(content_type=content_type, size_bytes=len(data), sha256=digest, data=data,
                        width=size[0] if size else None, height=size[1] if size else None, created_at=now(),
                        retain_until=now() + timedelta(days=retain_days))
    db.add(blob)
    db.flush()
    return blob


def reuse_recent_audit(db, audit: WebsiteAudit, company: Company, days: int) -> bool:  # type: ignore[no-untyped-def]
    """Copy findings from a recent audit of the same verified web property."""
    if not company.website_property_id or days <= 0:
        return False
    prop = db.get(WebsiteProperty, company.website_property_id)
    if prop is None or prop.is_shared_platform:
        return False
    src = db.scalar(select(WebsiteAudit).where(
        WebsiteAudit.property_id == prop.id, WebsiteAudit.company_id != company.id, WebsiteAudit.mode == audit.mode,
        WebsiteAudit.status.in_(["action_required", "completed"]),
        WebsiteAudit.automated_completed_at >= now() - timedelta(days=days),
    ).order_by(WebsiteAudit.automated_completed_at.desc()).limit(1))
    if src is None:
        return False
    for attr in ("final_url", "pages_audited", "metrics", "context", "technologies", "content_fingerprint", "rule_versions"):
        setattr(audit, attr, getattr(src, attr))
    audit.reused_from_audit_id = src.id
    id_map: dict[int, int] = {}
    for f in db.scalars(select(AuditFinding).where(AuditFinding.audit_id == src.id)):
        nf = AuditFinding(audit_id=audit.id, rule_key=f.rule_key, rule_version=f.rule_version, result=f.result,
                          page_url=f.page_url, value=f.value, confidence=f.confidence, message_params=f.message_params,
                          created_at=now())
        db.add(nf)
        db.flush()
        id_map[f.id] = nf.id
    for e in db.scalars(select(Evidence).where(Evidence.audit_id == src.id)):
        db.add(Evidence(company_id=company.id, audit_id=audit.id, finding_id=id_map.get(e.finding_id or -1),
                        kind=e.kind, label=e.label, source_url=e.source_url, selector=e.selector, data=e.data,
                        blob_id=e.blob_id, detection_method=e.detection_method, rule_version=e.rule_version,
                        confidence=e.confidence, limitations=e.limitations, viewport=e.viewport, created_at=now()))
    for t in db.scalars(select(TrackingDetection).where(TrackingDetection.audit_id == src.id)):
        db.add(TrackingDetection(audit_id=audit.id, technology=t.technology, status=t.status,
                                 consent_state=t.consent_state, methods=t.methods, evidence_urls=t.evidence_urls,
                                 identifiers_redacted=t.identifiers_redacted, page_url=t.page_url,
                                 confidence=t.confidence, limitations=t.limitations, detected_at=t.detected_at))
    return True


def execute_audit(audit_id: uuid.UUID, progress) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    with session_scope() as db:
        audit = db.get(WebsiteAudit, audit_id)
        if audit is None:
            raise ValueError("audit not found")
        company = db.get(Company, audit.company_id)
        assert company is not None
        settings = get_settings_map(db)
        industry = db.get(Industry, company.primary_industry_id) if company.primary_industry_id else None
        features = set(industry.relevant_features or []) if industry else {"contact_form", "tel_link"}
        rules_meta = {r.key: (r.version, r.enabled) for r in db.scalars(select(AuditRule))}
        tech_rules = tracking_rules(db)
        audit.status = "running"
        audit.started_at = now()
        company.analysis_status = "running"
        start_url = audit.start_url or company.website_url
        mode = audit.mode
        force = bool((audit.context or {}).get("force"))
        if not start_url:
            audit.status = "action_required"
            audit.automated_completed_at = now()
            audit.error = "no_website_in_source"
            company.analysis_status = "action_required"
            db.add(AuditFinding(audit_id=audit.id, rule_key="site.reachable", result=NOT_CHECKED, page_url="",
                                value={"reason": "No website recorded. Verify manually before treating as absent."},
                                created_at=now()))
            return {"status": "action_required", "reason": "no_website"}
        if not force and reuse_recent_audit(db, audit, company, int(settings["audit.reuse_audit_days"])):
            audit.status = "action_required" if mode == "full" else "completed"
            audit.automated_completed_at = now()
            company.analysis_status = "action_required" if mode == "full" else company.analysis_status
            company.last_audit_at = now()
            return {"status": audit.status, "reused": str(audit.reused_from_audit_id)}
        audit.property_id = company.website_property_id
    timeout = int(settings["limits.http_timeout_seconds"])
    progress("http")
    http = run_http_stage(start_url, max_pages=int(settings["limits.max_pages_per_company"]), timeout=timeout,
                          max_bytes=int(settings["limits.max_response_bytes"]),
                          max_redirects=int(settings["limits.max_redirects"]))
    results: list[RuleResult] = list(http.results)
    metrics: dict[str, Any] = {"http": http.metrics.get("http"), "pages_sampled": http.metrics.get("pages_sampled", 0)}
    context: dict[str, Any] = {"mode": mode, "audited_at": now().isoformat(), "user_agent": "LeadRadarAudit/1.0"}
    technologies: list[dict] = []
    obs = trk.Observation()
    after_obs: trk.Observation | None = None
    browser_out = None
    if http.reachable and http.pages:
        home = http.pages[0]
        https = (http.final_url or "").startswith("https://")
        results += seo_checks(home)
        results += structure_checks(home, https)
        results += conversion_checks(http.pages, features)
        technologies = detect_platforms(home.html, http.headers)
        obs.html = "\n".join(p.html[:500_000] for p in http.pages)
        obs.script_urls = [s for p in http.pages for s in p.scripts]
        if mode == "full":
            progress("browser")
            try:
                from leadradar.modules.website_audit.browser import run_browser_stage

                browser_out = run_browser_stage(
                    http.final_url or start_url, desktop=settings["audit.desktop_viewport"],
                    mobile=settings["audit.mobile_viewport"], timeout_s=int(settings["limits.browser_timeout_seconds"]),
                    max_screenshot_bytes=int(settings["limits.max_screenshot_bytes"]),
                    screenshots=int(settings["limits.screenshots_per_site"]),
                    consent_test=bool(settings["audit.consent_tests_enabled"]),
                )
                results += browser_out.results
                context["browser"] = {"engine": "chromium", "version": browser_out.browser_version,
                                      "viewports": [{"name": r.name, "width": r.width, "height": r.height}
                                                    for r in browser_out.runs]}
                metrics["browser"] = {r.name: {"status": r.status, "cls_observed": (r.measure or {}).get("cls"),
                                               "error": r.error} for r in browser_out.runs}
                for r in browser_out.runs:
                    obs.html += "\n" + r.rendered_html
                    obs.script_urls += r.script_urls
                    obs.network_urls += r.network_urls
                    obs.runtime_globals |= set((r.measure or {}).get("globals", []))
                    obs.rendered = obs.rendered or bool(r.measure)
                    if r.consent_clicked:
                        after_obs = trk.Observation(html="", script_urls=[], network_urls=r.consent_after_urls,
                                                    runtime_globals=set(r.consent_after_globals), rendered=True)
                        context["consent_test"] = {"clicked_selector": r.consent_clicked,
                                                   "note": "Accepted the cookie banner only; no forms submitted."}
            except ImportError:
                results.append(RuleResult("tech.js_errors", NOT_CHECKED, start_url, {"reason": "browser unavailable"}))
            except Exception as exc:  # browser failures never fail the audit
                results.append(RuleResult("tech.js_errors", ERROR, start_url, {"error": str(exc)[:300]}))
            if settings["audit.lighthouse_enabled"]:
                progress("lighthouse")
                from leadradar.modules.website_audit.lighthouse import run_lighthouse

                lh = run_lighthouse(http.final_url or start_url, timeout_s=150)
                results += lh.results
                metrics["lighthouse"] = {"scores": lh.scores, "metrics": lh.metrics, "error": lh.error,
                                         "measurement": "lab"}
                context["lighthouse"] = lh.context
    progress("tracking")
    tech_results = trk.detect(tech_rules, obs) if obs.html else []
    after_results = trk.detect(tech_rules, after_obs) if after_obs else []
    detected_analytics = [t for t in tech_results + after_results if t.technology in ANALYTICS_TECH and t.status == DETECTED]
    if obs.html:
        results.append(RuleResult("track.analytics", PASSED if detected_analytics else (FAILED if obs.rendered else UNKNOWN),
                                  http.final_url or start_url,
                                  {"detected": sorted({t.name for t in detected_analytics}),
                                   "limitations": trk.LIMITATIONS}, 0.6 if not detected_analytics else 0.95))
        cmp = next((t for t in tech_results if t.technology == "cmp"), None)
        results.append(RuleResult("track.consent", DETECTED if cmp and cmp.status == DETECTED else NOT_DETECTED,
                                  http.final_url or start_url, {}))
    merged = merge_results(results)
    progress("persist")
    with session_scope() as db:
        audit = db.get(WebsiteAudit, audit_id)
        company = db.get(Company, audit.company_id)  # type: ignore[union-attr]
        assert audit is not None and company is not None
        retain = 30
        for rr in merged.values():
            version, enabled = rules_meta.get(rr.rule_key, (1, True))
            if not enabled:
                continue
            f = AuditFinding(audit_id=audit.id, rule_key=rr.rule_key, rule_version=version, result=rr.result,
                             page_url=rr.page_url[:2000], value=_json_safe(rr.value), confidence=rr.confidence,
                             message_params=_json_safe(rr.params), created_at=now())
            db.add(f)
            db.flush()
            for ev in rr.evidence:
                _persist_evidence(db, company.id, audit.id, f.id, ev, version, retain)
        if browser_out:
            for run in browser_out.runs:
                if run.screenshot:
                    _persist_evidence(db, company.id, audit.id, None, EvidenceItem(
                        "screenshot", f"{run.name.title()} screenshot", run.final_url, data={"viewport": run.name,
                        "width": run.width, "height": run.height}, detection_method="playwright", viewport=run.name,
                        blob=run.screenshot, blob_type="image/webp", blob_size=run.screenshot_size), None, retain)
        for state, rs in (("initial", tech_results), ("after_accept", after_results)):
            for t in rs:
                db.add(TrackingDetection(audit_id=audit.id, technology=t.technology, status=t.status,
                                         consent_state=state, methods=t.methods, evidence_urls=t.evidence_urls,
                                         identifiers_redacted=t.identifiers_redacted,
                                         page_url=http.final_url or start_url, confidence=t.confidence,
                                         limitations=t.limitations, detected_at=now()))
        if http.reachable:
            company.website_status = "verified"
            company.last_verified_at = now()
            _harvest_contacts(db, company, http.pages)
        audit.final_url = http.final_url
        audit.pages_audited = [p.url for p in http.pages]
        audit.metrics = _json_safe(metrics)
        audit.context = _json_safe({**(audit.context or {}), **context})
        audit.technologies = technologies
        audit.content_fingerprint = content_fingerprint(" ".join(p.text for p in http.pages[:1])) if http.pages else None
        audit.rule_versions = {k: v[0] for k, v in rules_meta.items()}
        audit.automated_completed_at = now()
        company.last_audit_at = now()
        if company.website_property_id:
            prop = db.get(WebsiteProperty, company.website_property_id)
            if prop:
                prop.last_audit_id = audit.id
        blocked = any(r.result == BLOCKED and r.rule_key == "site.reachable" for r in merged.values())
        if mode == "full":
            audit.status = "action_required"
            company.analysis_status = "action_required"
        else:
            audit.status = "completed"
            audit.completed_at = now()
            company.analysis_status = "completed" if company.analysis_status in ("running", "queued") else company.analysis_status
        db.flush()
        from leadradar.modules.scoring.service import score_company

        score_company(db, company, stage="preliminary", audit=audit)
        if mode == "full":
            from leadradar.modules.crm.notifications import notify

            notify(db, "review_required", "notifications.reviewRequired", {"company": company.name},
                   link=f"/review/{audit.id}", dedupe_key=f"review:{audit.id}")
        return {"status": audit.status, "findings": len(merged), "reachable": http.reachable, "blocked": blocked}


def _persist_evidence(db, company_id, audit_id, finding_id, ev: EvidenceItem, version, retain: int) -> None:  # type: ignore[no-untyped-def]
    blob_id = None
    if ev.blob:
        blob_id = _store_blob(db, ev.blob, ev.blob_type or "application/octet-stream", ev.blob_size, retain).id
    db.add(Evidence(company_id=company_id, audit_id=audit_id, finding_id=finding_id, kind=ev.kind, label=ev.label[:200],
                    source_url=(ev.source_url or "")[:2000] or None, selector=(ev.selector or "")[:500] or None,
                    data=_json_safe(ev.data), blob_id=blob_id, detection_method=ev.detection_method,
                    rule_version=version, confidence=ev.confidence, limitations=ev.limitations, viewport=ev.viewport,
                    created_at=now()))


def _harvest_contacts(db, company: Company, pages) -> None:  # type: ignore[no-untyped-def]
    """Record business contact channels published on the company's own website."""
    mails = sorted({unquote(m[7:].split("?")[0]).strip().lower() for p in pages for m in p.mailto_links})
    domain = company.canonical_domain
    for m in mails:
        if domain and m.endswith("@" + domain) or (domain and m.split("@")[-1].endswith("." + domain)):
            if not company.email:
                company.email = m[:320]
                fs = dict(company.field_sources or {})
                fs["email"] = {"source": "audit", "at": now().isoformat(), "confirmed": False}
                company.field_sources = fs
            if company.email == m:
                company.email_verified = True
            break
    for link in sorted({s for p in pages for s in p.social_links})[:10]:
        det = detect_social(link)
        if not det:
            continue
        platform, handle = det
        existing = db.scalar(select(SocialProfile).where(SocialProfile.company_id == company.id,
                                                         SocialProfile.platform == platform,
                                                         SocialProfile.handle == handle))
        n = normalize_url(link)
        if existing is None:
            db.add(SocialProfile(company_id=company.id, platform=platform, handle=handle, url=n.url if n else link,
                                 source="audit", verified=True))
        else:
            existing.verified = True


def _json_safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        if isinstance(v, str):
            return v.replace("\x00", "")[:20_000]
        return v
    return str(v)


__all__ = ["execute_audit", "content_fingerprint", "UNKNOWN", "NOT_DETECTED", "urlsplit"]
