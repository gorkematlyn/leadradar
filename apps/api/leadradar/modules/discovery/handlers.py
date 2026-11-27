"""Job handlers for discovery: Geofabrik country/extract imports and CSV imports."""

from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from leadradar.core.app_settings import get_setting
from leadradar.core.config import get_settings
from leadradar.db.models import Country, ImportRun, Industry, IndustryRule
from leadradar.db.session import session_scope
from leadradar.jobs import queue
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler
from leadradar.modules.crm.companies import RecordInput, upsert_record
from leadradar.modules.crm.notifications import notify
from leadradar.modules.crm.suppression import active_entries
from leadradar.modules.discovery import geofabrik
from leadradar.modules.discovery.matching import compile_rules, is_chain, is_closed
from leadradar.modules.discovery.osm_extract import ExtractedPoi, extract_pois

BATCH = 400


def load_rules(db, industry_keys: list[str] | None = None):  # type: ignore[no-untyped-def]
    q = (select(Industry.key, IndustryRule.key, IndustryRule.classification, IndustryRule.conditions)
         .join(IndustryRule, IndustryRule.industry_id == Industry.id)
         .where(Industry.enabled.is_(True), IndustryRule.enabled.is_(True)))
    if industry_keys:
        q = q.where(Industry.key.in_(industry_keys))
    return compile_rules([
        {"industry_key": ik, "rule_key": rk, "classification": cl, "conditions": cond}
        for ik, rk, cl, cond in db.execute(q).all()
    ])


def poi_to_record(poi: ExtractedPoi, iso2: str, region: str | None, run_id: uuid.UUID) -> RecordInput:
    t = poi.tags
    street = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x) or None
    socials = [t[k] for k in ("contact:facebook", "contact:instagram", "contact:linkedin", "contact:twitter",
                              "facebook", "instagram") if t.get(k)]
    socials = [s if s.startswith("http") else None for s in socials]
    ts = None
    if poi.timestamp:
        try:
            ts = datetime.fromisoformat(poi.timestamp)
        except ValueError:
            ts = None
    return RecordInput(
        source="osm", source_key=poi.source_key, name=t.get("name", "")[:300], country_iso2=iso2,
        industry_keys=[m.industry_key for m in poi.matches],
        classification=poi.matches[0].classification if poi.matches else "review",
        source_url=f"https://www.openstreetmap.org/{poi.osm_type}/{poi.osm_id}",
        legal_name=t.get("official_name"), region=t.get("addr:state") or t.get("addr:province") or region,
        city=t.get("addr:city") or t.get("addr:district"), address=street, postal_code=t.get("addr:postcode"),
        latitude=poi.lat, longitude=poi.lon,
        website=t.get("website") or t.get("contact:website") or t.get("url"),
        email=t.get("email") or t.get("contact:email"),
        phone=t.get("phone") or t.get("contact:phone") or t.get("contact:mobile"),
        socials=[s for s in socials if s], raw={"tags": t, "rule": poi.matches[0].rule_key if poi.matches else None},
        source_timestamp=ts, is_chain=is_chain(t), closed=is_closed(t), import_run_id=run_id,
    )


@handler("geofabrik_country_import")
def handle_country_import(ctx: JobContext) -> dict:
    """Plan a country's extracts and enqueue one sequential extract job per region."""
    iso2 = ctx.payload["country"].upper()
    with session_scope() as db:
        country = db.get(Country, iso2)
        if country is None:
            raise PermanentJobError(f"unknown country {iso2}")
        if not country.enabled:
            country.import_status = "disabled"
            return {"skipped": "country disabled"}
        base = get_setting(db, "geofabrik.base_url")
        max_bytes = int(get_setting(db, "geofabrik.max_extract_bytes"))
        overrides = list(country.geofabrik_ids or [])
        country.import_status = "planning"
    ctx.progress("load_index")
    index = geofabrik.load_index(base)
    ctx.progress("plan_extracts")
    plan = geofabrik.plan_extracts(index, iso2, max_bytes, overrides or None)
    previous: uuid.UUID | None = None
    job_ids = []
    with session_scope() as db:
        for i, ext in enumerate(plan):
            run = ImportRun(source="geofabrik", country_iso2=iso2, extract_id=ext.id, extract_url=ext.pbf_url,
                            status="queued", file_size=ext.size, source_timestamp=ext.last_modified)
            db.add(run)
            db.flush()
            job = queue.enqueue(
                db, "geofabrik_extract_import", f"Import {ext.name} ({iso2})",
                {"country": iso2, "extract_id": ext.id, "pbf_url": ext.pbf_url, "size": ext.size,
                 "last_modified": ext.last_modified.isoformat() if ext.last_modified else None,
                 "import_run_id": str(run.id), "industries": ctx.payload.get("industries"),
                 "region_name": ext.name if len(plan) > 1 else None, "force": ctx.payload.get("force", False),
                 "include_without_website": ctx.payload.get("include_without_website", False)},
                idempotency_key=f"geofabrik_extract:{ext.id}", parent_id=ctx.job_id,
                depends_on=[previous] if previous else [], concurrency_key="geofabrik_download",
                priority=50 + i,
            )
            run.job_id = job.id
            previous = job.id
            job_ids.append(str(job.id))
        country = db.get(Country, iso2)
        country.import_status = "queued"  # type: ignore[union-attr]
    return {"extracts": [e.id for e in plan], "jobs": job_ids}


@handler("geofabrik_extract_import")
def handle_extract_import(ctx: JobContext) -> dict:
    p = ctx.payload
    iso2 = p["country"]
    run_id = uuid.UUID(p["import_run_id"])
    tmp_dir = os.path.join(get_settings().worker_tmp_dir, "osm")
    with session_scope() as db:
        country = db.get(Country, iso2)
        if country is None or not country.enabled:
            raise PermanentJobError("country disabled; import stopped")
        reserve = int(get_setting(db, "limits.min_free_disk_gb"))
        min_days = int(get_setting(db, "geofabrik.min_reimport_days"))
        run = db.get(ImportRun, run_id)
        run.status, run.started_at = "running", run.started_at or datetime.now(UTC)  # type: ignore[union-attr]
        country.import_status = "running"
        # Skip unchanged extracts (respect Geofabrik bandwidth) unless forced.
        last = db.scalar(select(ImportRun).where(
            ImportRun.extract_id == p["extract_id"], ImportRun.status == "completed", ImportRun.id != run_id,
        ).order_by(ImportRun.finished_at.desc()))
        rules = load_rules(db, p.get("industries"))
        suppression = active_entries(db)
    if not rules:
        raise PermanentJobError("no enabled industry rules")
    lm = datetime.fromisoformat(p["last_modified"]) if p.get("last_modified") else None
    if last and not p.get("force") and lm and last.source_timestamp and last.source_timestamp >= lm and \
            last.finished_at and datetime.now(UTC) - last.finished_at < timedelta(days=min_days):
        with session_scope() as db:
            run = db.get(ImportRun, run_id)
            run.status, run.finished_at = "skipped", datetime.now(UTC)  # type: ignore[union-attr]
            run.stats = {"reason": "unchanged since last import"}  # type: ignore[union-attr]
        return {"skipped": "unchanged"}
    path = None
    try:
        ext = geofabrik.Extract(id=p["extract_id"], name=p["extract_id"], parent=None, pbf_url=p["pbf_url"],
                                iso2=[iso2], iso3166_2=[], size=p.get("size"))
        geofabrik.check_disk(tmp_dir, int(ext.size or 0), reserve)
        ctx.progress("download", 0, ext.size)

        def dl_progress(done: int, total: int | None) -> None:
            if done % (32 << 20) < (1 << 20):
                ctx.progress("download", done, total)

        path = geofabrik.download(ext, tmp_dir, progress=dl_progress, should_stop=lambda: ctx.cancelled)
        ctx.log("info", "download verified", path=os.path.basename(path))
        ctx.progress("extract", 0, None)  # total unknown: no fabricated percentage
        stats = {"matched": 0, "created": 0, "updated": 0, "unchanged": 0, "matched_existing": 0,
                 "duplicate_candidates": 0, "skipped_no_name": 0, "skipped_no_website": 0}
        with_no_site = bool(p.get("include_without_website", False))
        resume_after = int(ctx.checkpoint_data.get("processed", 0))
        processed = 0
        batch: list[ExtractedPoi] = []

        def flush(items: list[ExtractedPoi]) -> None:
            with session_scope() as db:
                for poi in items:
                    rec = poi_to_record(poi, iso2, p.get("region_name"), run_id)
                    if not rec.name:
                        stats["skipped_no_name"] += 1
                        continue
                    if not with_no_site and not rec.website:
                        stats["skipped_no_website"] += 1
                        continue
                    out = upsert_record(db, rec, suppression)
                    key = {"created": "created", "updated": "updated", "unchanged": "unchanged",
                           "matched": "matched_existing"}[out.action]
                    stats[key] += 1
                    stats["duplicate_candidates"] += out.duplicate_candidates

        for poi in extract_pois(path, rules, progress=lambda s, n: ctx.progress(f"extract:{s}", n),
                                should_stop=lambda: ctx.cancelled):
            processed += 1
            stats["matched"] += 1
            if processed <= resume_after:
                continue  # idempotent upserts make re-processing safe; skip to save time
            batch.append(poi)
            if len(batch) >= BATCH:
                flush(batch)
                batch = []
                ctx.progress("import", processed)
                ctx.checkpoint({"processed": processed})
                ctx.raise_if_cancelled()
        if batch:
            flush(batch)
        ctx.raise_if_cancelled()
        with session_scope() as db:
            run = db.get(ImportRun, run_id)
            run.status, run.finished_at, run.stats = "completed", datetime.now(UTC), stats  # type: ignore[union-attr]
            run.source_timestamp = lm  # type: ignore[union-attr]
            country = db.get(Country, iso2)
            country.last_import_at = datetime.now(UTC)  # type: ignore[union-attr]
            country.last_source_timestamp = lm  # type: ignore[union-attr]
            pending = db.scalar(select(ImportRun.id).where(ImportRun.country_iso2 == iso2,
                                                           ImportRun.status.in_(["queued", "running"]),
                                                           ImportRun.id != run_id).limit(1))
            if pending is None:
                country.import_status = "completed"  # type: ignore[union-attr]
                notify(db, "import_completed", "notifications.importCompleted",
                       {"country": iso2, "created": stats["created"]}, severity="success", link="/discovery")
        return stats
    finally:
        # Raw OSM files are deleted after processing (success or failure of the parse step).
        # A partially downloaded ``.part`` file is kept so a retry can resume it.
        if path and os.path.exists(path):
            os.remove(path)


def _import_failed(ctx: JobContext, outcome: str) -> None:
    run_id = ctx.payload.get("import_run_id")
    with session_scope() as db:
        if run_id:
            run = db.get(ImportRun, uuid.UUID(run_id))
            if run:
                run.status = "cancelled" if outcome == "cancelled" else "failed"
                run.finished_at = datetime.now(UTC)
        country = db.get(Country, ctx.payload.get("country", ""))
        if country:
            country.import_status = "failed" if outcome == "failed" else "cancelled"
        if outcome == "failed":
            notify(db, "import_failed", "notifications.importFailedRegion",
                   {"country": ctx.payload.get("country"), "region": ctx.payload.get("region_name") or ctx.payload.get("extract_id"),
                    "job_id": str(ctx.job_id)},
                   severity="error", link=f"/jobs/{ctx.job_id}", dedupe_key=f"import_failed:{ctx.job_id}")


from leadradar.jobs.runtime import FAILURE_HOOKS, SPECIFIC_FAILURE_NOTIFICATIONS  # noqa: E402

FAILURE_HOOKS["geofabrik_extract_import"] = _import_failed
SPECIFIC_FAILURE_NOTIFICATIONS.add("geofabrik_extract_import")

# --- CSV import --------------------------------------------------------------------------

CSV_FIELDS = {"name", "website", "email", "phone", "address", "city", "region", "postal_code", "country",
              "industry", "latitude", "longitude", "legal_name", "facebook", "instagram", "linkedin"}


@handler("csv_import")
def handle_csv_import(ctx: JobContext) -> HandlerResult:
    """payload: {content: str (CSV text, size-limited at upload), mapping: {field: column}, default_country, default_industry}"""
    p = ctx.payload
    mapping: dict[str, str] = p["mapping"]
    unknown = set(mapping) - CSV_FIELDS
    if unknown or "name" not in mapping:
        raise PermanentJobError("invalid mapping: 'name' is required; unknown fields: " + ", ".join(sorted(unknown)))
    reader = csv.DictReader(io.StringIO(p["content"]), delimiter=p.get("delimiter") or ",")
    stats = {"rows": 0, "created": 0, "updated": 0, "unchanged": 0, "matched_existing": 0, "errors": 0,
             "duplicate_candidates": 0}
    errors: list[str] = []
    run_id = uuid.UUID(p["import_run_id"])
    with session_scope() as db:
        suppression = active_entries(db)
        industries = {k.lower(): k for k in db.scalars(select(Industry.key))}
        industries.update({n.lower(): k for n, k in db.execute(select(Industry.name_en, Industry.key))})
        industries.update({n.lower(): k for n, k in db.execute(select(Industry.name_tr, Industry.key))})
    rows = list(reader)
    ctx.progress("import", 0, len(rows))
    for start in range(0, len(rows), 200):
        with session_scope() as db:
            for i, row in enumerate(rows[start:start + 200], start=start + 1):
                def g(f: str, row: dict = row) -> str | None:
                    col = mapping.get(f)
                    v = (row.get(col) or "").strip() if col else ""
                    return v or None
                try:
                    name = g("name")
                    if not name:
                        raise ValueError("missing name")
                    ind = g("industry") or p.get("default_industry")
                    ind_key = industries.get(ind.lower()) if ind else None
                    country = (g("country") or p.get("default_country") or "").upper()[:2] or None
                    lat, lon = g("latitude"), g("longitude")
                    rec = RecordInput(
                        source="csv", source_key=f"{p['import_run_id']}:{i}", name=name, country_iso2=country,
                        industry_keys=[ind_key] if ind_key else [], classification="confident", website=g("website"),
                        email=g("email"), phone=g("phone"), address=g("address"), city=g("city"), region=g("region"),
                        postal_code=g("postal_code"), legal_name=g("legal_name"),
                        latitude=float(lat) if lat else None, longitude=float(lon) if lon else None,
                        socials=[x for x in (g("facebook"), g("instagram"), g("linkedin")) if x],
                        raw={k: v for k, v in row.items() if k}, import_run_id=run_id,
                    )
                    with db.begin_nested():
                        out = upsert_record(db, rec, suppression)
                    key = {"created": "created", "updated": "updated", "unchanged": "unchanged",
                           "matched": "matched_existing"}[out.action]
                    stats[key] += 1
                    stats["duplicate_candidates"] += out.duplicate_candidates
                except Exception as exc:  # row-level errors are reported, not fatal
                    stats["errors"] += 1
                    if len(errors) < 50:
                        errors.append(f"row {i}: {exc}")
                stats["rows"] += 1
        ctx.progress("import", stats["rows"], len(rows))
        ctx.raise_if_cancelled()
    with session_scope() as db:
        run = db.get(ImportRun, run_id)
        if run:
            run.status, run.finished_at, run.stats = "completed", datetime.now(UTC), {**stats, "errors_sample": errors}
        # Drop the CSV content from the job payload once processed (data minimization).
        from leadradar.db.models import Job

        job = db.get(Job, ctx.job_id)
        if job:
            job.payload = {k: v for k, v in job.payload.items() if k != "content"}
        notify(db, "import_completed", "notifications.csvImportCompleted", {"rows": stats["rows"]},
               severity="success", link="/companies")
    return HandlerResult({**stats, "errors_sample": errors})
