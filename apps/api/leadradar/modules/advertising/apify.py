"""Optional Apify provider with cost controls.

Disabled until an administrator stores a token, enables the provider, configures an
Actor and sets non-zero budgets. Paid runs are blocked when any configured limit
(per task, daily, monthly) would be exceeded. Estimated and provider-reported costs are
stored separately; Actor pricing is never assumed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadradar.core.app_settings import get_setting
from leadradar.core.security import decrypt_secret
from leadradar.db.models import ApifyActorConfig, ImportRun, ProviderUsage
from leadradar.db.session import session_scope
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler
from leadradar.modules.crm.notifications import notify
from leadradar.modules.netsafe.http import make_client

API = "https://api.apify.com/v2"


class BudgetExceeded(PermanentJobError):
    pass


def spent(db: Session, since: datetime) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(func.coalesce(ProviderUsage.actual_cost_usd,
                                                              ProviderUsage.estimated_cost_usd)), 0))
                  .where(ProviderUsage.provider == "apify", ProviderUsage.occurred_at >= since))
    return Decimal(str(v or 0))


def check_budget(db: Session, actor: ApifyActorConfig) -> dict[str, Any]:
    if not get_setting(db, "apify.enabled"):
        raise BudgetExceeded("Apify provider is disabled")
    daily = Decimal(str(get_setting(db, "apify.daily_budget_usd") or 0))
    monthly = Decimal(str(get_setting(db, "apify.monthly_budget_usd") or 0))
    per_task = min(Decimal(str(get_setting(db, "apify.max_cost_per_task_usd") or 0)), Decimal(str(actor.max_cost_usd)))
    if daily <= 0 or monthly <= 0 or per_task <= 0:
        raise BudgetExceeded("Apify budgets are not configured; paid tasks are blocked")
    now = datetime.now(UTC)
    day = spent(db, now - timedelta(days=1))
    month = spent(db, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    if day + per_task > daily:
        raise BudgetExceeded(f"daily budget would be exceeded ({day} + {per_task} > {daily})")
    if month + per_task > monthly:
        raise BudgetExceeded(f"monthly budget would be exceeded ({month} + {per_task} > {monthly})")
    alert = int(get_setting(db, "apify.alert_percent") or 80)
    if month >= monthly * alert / 100:
        notify(db, "budget", "notifications.budgetAlert", {"provider": "Apify", "spent": float(month),
               "budget": float(monthly)}, severity="warning", link="/usage", dedupe_key="apify_budget_alert")
    return {"per_task": per_task, "day": day, "month": month}


def validate_input(actor: ApifyActorConfig, overrides: dict[str, Any]) -> dict[str, Any]:
    allowed = set(actor.allowed_input_keys or [])
    bad = set(overrides) - allowed
    if bad:
        raise PermanentJobError(f"input keys not allowed for this Actor: {', '.join(sorted(bad))}")
    data = {**(actor.input_template or {}), **overrides}
    if len(json.dumps(data)) > 20_000:
        raise PermanentJobError("Actor input too large")
    return data


@handler("apify_run")
def handle_apify(ctx: JobContext) -> HandlerResult:
    actor_id = uuid.UUID(ctx.payload["actor_config_id"])
    with session_scope() as db:
        actor = db.get(ApifyActorConfig, actor_id)
        if actor is None or not actor.enabled:
            raise PermanentJobError("Actor configuration missing or disabled")
        budget = check_budget(db, actor)
        token_enc = get_setting(db, "apify.token")
        if not token_enc:
            raise PermanentJobError("Apify token not configured")
        token = decrypt_secret(token_enc)
        run_input = validate_input(actor, ctx.payload.get("input") or {})
        actor_ref, max_items, purpose = actor.actor_id, actor.max_items, actor.purpose
        mapping = dict(actor.field_mapping or {})
        usage = ProviderUsage(provider="apify", kind="actor_run", description=f"{actor.name} ({actor.actor_id})",
                              estimated_cost_usd=budget["per_task"], status="running", occurred_at=datetime.now(UTC),
                              units={"max_items": max_items})
        db.add(usage)
        db.flush()
        usage_id = usage.id
    headers = {"Authorization": f"Bearer {token}"}
    params = f"?waitForFinish=60&maxItems={max_items}&maxTotalChargeUsd={budget['per_task']}"
    with make_client(timeout=90) as client:
        resp = client.post(f"{API}/acts/{quote(actor_ref, safe='~')}/runs{params}", json=run_input, headers=headers)
        if resp.status_code >= 400:
            raise PermanentJobError(f"Apify run failed: HTTP {resp.status_code}")
        run = resp.json().get("data", {})
        run_id = run.get("id")
        for _ in range(40):
            if run.get("status") in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            ctx.progress("apify:running")
            ctx.raise_if_cancelled()
            resp = client.get(f"{API}/actor-runs/{run_id}?waitForFinish=60", headers=headers)
            run = resp.json().get("data", {})
        items: list[dict] = []
        if run.get("status") == "SUCCEEDED" and run.get("defaultDatasetId"):
            r = client.get(f"{API}/datasets/{run['defaultDatasetId']}/items?clean=true&limit={max_items}", headers=headers)
            if r.status_code == 200:
                items = r.json()[:max_items]
    with session_scope() as db:
        usage = db.get(ProviderUsage, usage_id)
        usage.reference, usage.status = run_id, run.get("status")  # type: ignore[union-attr]
        actual = run.get("usageTotalUsd")
        if isinstance(actual, (int, float)):
            usage.actual_cost_usd, usage.cost_confirmed = Decimal(str(actual)), True  # type: ignore[union-attr]
        usage.units = {"items": len(items), "max_items": max_items}  # type: ignore[union-attr]
    imported = 0
    if purpose == "discovery" and items and mapping.get("name"):
        from leadradar.modules.crm.companies import RecordInput, upsert_record
        from leadradar.modules.crm.suppression import active_entries

        with session_scope() as db:
            ir = ImportRun(source="apify", status="completed", stats={}, started_at=datetime.now(UTC))
            db.add(ir)
            db.flush()
            supp = active_entries(db)
            for i, it in enumerate(items):
                def g(k: str, it: dict = it) -> Any:
                    path = mapping.get(k)
                    return it.get(path) if path else None
                if not g("name"):
                    continue
                rec = RecordInput(source="apify", source_key=f"{actor_ref}:{g('id') or run_id + ':' + str(i)}",
                                  name=str(g("name"))[:300], country_iso2=(ctx.payload.get("country") or None),
                                  industry_keys=[ctx.payload["industry"]] if ctx.payload.get("industry") else [],
                                  classification="review", website=g("website"), phone=g("phone"),
                                  email=g("email"), address=g("address"), city=g("city"),
                                  latitude=g("latitude"), longitude=g("longitude"),
                                  raw={k: v for k, v in it.items() if isinstance(v, (str, int, float, bool))},
                                  import_run_id=ir.id)
                upsert_record(db, rec, supp)
                imported += 1
            ir.stats, ir.finished_at = {"items": len(items), "imported": imported}, datetime.now(UTC)
    return HandlerResult({"run_id": run_id, "status": run.get("status"), "items": len(items), "imported": imported,
                          "cost_usd": run.get("usageTotalUsd")})
