"""Campaign execution, retention cleanup and bulk score recalculation handlers."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, exists, func, not_, or_, select

from leadradar.core.config import get_settings
from leadradar.db.models import (
    ActivityLog,
    AdvertisingResearchRun,
    CampaignRun,
    Company,
    CompanySnapshot,
    Country,
    Evidence,
    EvidenceBlob,
    Industry,
    Job,
    JobLog,
    Notification,
    ReportAsset,
    ReportVersion,
    RetentionPolicy,
    SavedCampaign,
    WebsiteAudit,
)
from leadradar.db.session import session_scope
from leadradar.jobs import queue
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler


def now() -> datetime:
    return datetime.now(UTC)


@handler("campaign_run")
def handle_campaign(ctx: JobContext) -> HandlerResult:
    cid = uuid.UUID(ctx.payload["campaign_id"])
    with session_scope() as db:
        c = db.get(SavedCampaign, cid)
        if c is None or not c.enabled:
            raise PermanentJobError("campaign missing or disabled")
        run = CampaignRun(campaign_id=c.id, status="running", trigger=ctx.payload.get("trigger", "manual"))
        db.add(run)
        db.flush()
        actions = c.actions or {}
        job_ids: list[uuid.UUID] = []
        countries = list(c.countries)
        if c.regions:
            countries += list(db.scalars(select(Country.iso2).where(Country.region_code.in_(c.regions),
                                                                    Country.enabled.is_(True))))
        countries = sorted(set(countries))
        if actions.get("import") and "geofabrik" in (c.discovery_sources or ["geofabrik"]):
            for iso in countries:
                country = db.get(Country, iso)
                if country and country.enabled:
                    j = queue.enqueue(db, "geofabrik_country_import", f"Campaign import: {country.name_en}",
                                      {"country": iso, "industries": c.industries or None},
                                      idempotency_key=f"geofabrik_country:{iso}", parent_id=ctx.job_id)
                    job_ids.append(j.id)
        audit_mode = actions.get("audit")
        if audit_mode in ("quick", "full") or actions.get("ads"):
            q = select(Company).where(Company.archived.is_(False), Company.do_not_contact.is_(False),
                                      Company.merged_into_id.is_(None), Company.permanently_closed.is_(False),
                                      Company.deleted_at.is_(None))
            if countries:
                q = q.where(Company.country_iso2.in_(countries))
            if c.industries:
                ids = list(db.scalars(select(Industry.id).where(Industry.key.in_(c.industries))))
                q = q.where(Company.primary_industry_id.in_(ids))
            if c.cities:
                q = q.where(func.lower(Company.city).in_([x.lower() for x in c.cities]))
            if audit_mode:
                q = q.where(Company.website_url.isnot(None), Company.analysis_status == "not_analyzed")
            companies = db.scalars(q.order_by(Company.created_at).limit(max(1, min(c.record_limit, 500)))).all()
            from leadradar.modules.advertising.service import start_research
            from leadradar.modules.website_audit.service import create_audit

            for comp in companies:
                if audit_mode:
                    _, job = create_audit(db, comp, audit_mode, priority=70)
                    job_ids.append(job.id)
                if actions.get("ads"):
                    for r in start_research(db, comp, actions.get("ad_platforms"), None):
                        if r.job_id:
                            job_ids.append(r.job_id)
        run.job_ids = job_ids
        run.stats = {"jobs": len(job_ids), "countries": countries}
        run.status, run.finished_at = "completed", now()
        c.last_run_at = now()
        if c.schedule_interval_hours:
            c.next_run_at = now() + timedelta(hours=c.schedule_interval_hours)
    return HandlerResult({"jobs": len(job_ids)})


def _policy(db, key: str) -> int | None:  # type: ignore[no-untyped-def]
    p = db.get(RetentionPolicy, key)
    if p is None or not p.enabled:
        return None
    return p.retention_days


@handler("retention_cleanup")
def handle_retention(ctx: JobContext) -> HandlerResult:
    stats: dict[str, int] = {}
    with session_scope() as db:
        days = _policy(db, "job_logs")
        if days:
            stats["job_logs"] = db.execute(delete(JobLog).where(JobLog.created_at < now() - timedelta(days=days))).rowcount or 0
            stats["jobs"] = db.execute(delete(Job).where(Job.finished_at < now() - timedelta(days=max(days, 30) * 3),
                                                         Job.status.in_(["completed", "cancelled"]))).rowcount or 0
        days = _policy(db, "audit_screenshots")
        if days:
            # Never delete evidence required by published reports or pending reviews.
            pending_audits = select(WebsiteAudit.id).where(WebsiteAudit.status == "action_required")
            report_blobs = select(ReportAsset.blob_id)
            referenced_pending = select(Evidence.blob_id).where(Evidence.audit_id.in_(pending_audits))
            q = delete(EvidenceBlob).where(
                EvidenceBlob.pinned.is_(False), EvidenceBlob.created_at < now() - timedelta(days=days),
                EvidenceBlob.content_type.like("image/%"), EvidenceBlob.id.not_in(report_blobs),
                EvidenceBlob.id.not_in(referenced_pending.where(Evidence.blob_id.isnot(None))),
            )
            stats["screenshots"] = db.execute(q).rowcount or 0
        days = _policy(db, "temp_pdfs")
        if days:
            unpublished = select(ReportVersion.id).where(ReportVersion.status != "approved")
            old = db.scalars(select(ReportAsset).where(ReportAsset.kind == "pdf",
                                                       ReportAsset.report_version_id.in_(unpublished),
                                                       ReportAsset.created_at < now() - timedelta(days=days))).all()
            for a in old:
                db.execute(delete(EvidenceBlob).where(EvidenceBlob.id == a.blob_id))
            stats["pdfs"] = len(old)
        days = _policy(db, "audit_history")
        if days:
            # Keep the latest audit per company and any audit whose evidence was approved for reports.
            latest = (select(WebsiteAudit.id).distinct(WebsiteAudit.company_id)
                      .order_by(WebsiteAudit.company_id, WebsiteAudit.created_at.desc()))
            stats["audits"] = db.execute(delete(WebsiteAudit).where(
                WebsiteAudit.created_at < now() - timedelta(days=days),
                WebsiteAudit.status.in_(["completed", "failed", "cancelled"]),
                not_(exists().where(and_(Evidence.audit_id == WebsiteAudit.id, Evidence.approved_for_reports.is_(True)))),
                WebsiteAudit.id.not_in(latest),
            )).rowcount or 0
        days = _policy(db, "ad_research_cache")
        if days:
            stats["ad_runs"] = db.execute(delete(AdvertisingResearchRun).where(
                AdvertisingResearchRun.created_at < now() - timedelta(days=days),
                AdvertisingResearchRun.status.in_(["error", "rate_limited", "not_checked", "no_results"]))).rowcount or 0
        days = _policy(db, "notifications")
        if days:
            stats["notifications"] = db.execute(delete(Notification).where(
                Notification.read_at.isnot(None), Notification.read_at < now() - timedelta(days=days))).rowcount or 0
        days = _policy(db, "activity_logs")
        if days:
            stats["activity_logs"] = db.execute(delete(ActivityLog).where(
                ActivityLog.created_at < now() - timedelta(days=days))).rowcount or 0
        days = _policy(db, "company_snapshots")
        if days:
            stats["snapshots"] = db.execute(delete(CompanySnapshot).where(
                CompanySnapshot.taken_at < now() - timedelta(days=days))).rowcount or 0
        from leadradar.modules.crm.trash import TRASH_DAYS, purge

        stats["trash_purged"] = purge(db, None, None, older_than_days=TRASH_DAYS)
        # Orphaned blobs (no evidence / report asset references) older than a day.
        stats["orphan_blobs"] = db.execute(delete(EvidenceBlob).where(
            EvidenceBlob.pinned.is_(False), EvidenceBlob.created_at < now() - timedelta(days=1),
            EvidenceBlob.id.not_in(select(Evidence.blob_id).where(Evidence.blob_id.isnot(None))),
            EvidenceBlob.id.not_in(select(ReportAsset.blob_id)),
        )).rowcount or 0
    from leadradar.modules.discovery.geofabrik import cleanup_abandoned

    stats["temp_files"] = cleanup_abandoned(os.path.join(get_settings().worker_tmp_dir, "osm"), 24)
    return HandlerResult(stats)


@handler("recalculate_scores")
def handle_recalc(ctx: JobContext) -> HandlerResult:
    """Recalculate scores from stored evidence only (no external requests)."""
    from leadradar.modules.scoring.service import load_profile, score_company

    ids = [uuid.UUID(x) for x in ctx.payload.get("company_ids") or []]
    with session_scope() as db:
        if not ids:
            ids = list(db.scalars(select(Company.id).where(Company.merged_into_id.is_(None), Company.deleted_at.is_(None),
                                                           or_(Company.last_audit_at.isnot(None),
                                                               Company.website_status == "verified_absent"))))
    total = len(ids)
    profile_key = ctx.payload.get("profile_key")
    for i in range(0, total, 100):
        with session_scope() as db:
            profile = load_profile(db, key=profile_key) if profile_key else None
            for cid in ids[i:i + 100]:
                c = db.get(Company, cid)
                if c is not None:
                    score_company(db, c, profile=profile)
        ctx.progress("recalculate", min(total, i + 100), total)
        ctx.raise_if_cancelled()
    return HandlerResult({"companies": total})
