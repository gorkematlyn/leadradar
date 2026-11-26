"""Administrator-configurable settings stored in PostgreSQL.

Defaults are declared here and seeded idempotently; reading falls back to the default
when no row exists. Values changed by an administrator are flagged ``admin_customized``
and are never overwritten by later seeding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.db.models import ApplicationSetting


@dataclass(frozen=True)
class SettingDef:
    key: str
    default: Any
    kind: str  # int, float, bool, str, list, origin, hosts
    group: str
    min: float | None = None
    max: float | None = None
    secret: bool = False


DEFS: list[SettingDef] = [
    # Domains / origins
    SettingDef("security.allowed_hosts", [], "hosts", "domain"),
    SettingDef("report.public_origin", None, "origin", "domain"),
    # Sessions
    SettingDef("security.session_ttl_hours", 168, "int", "security", 1, 24 * 90),
    SettingDef("security.idle_timeout_minutes", 120, "int", "security", 5, 24 * 60),
    SettingDef("security.login_max_attempts", 5, "int", "security", 3, 50),
    SettingDef("security.login_lockout_minutes", 15, "int", "security", 1, 1440),
    # Resource limits
    SettingDef("limits.geofabrik_concurrency", 1, "int", "resources", 1, 2),
    SettingDef("limits.heavy_concurrency", 1, "int", "resources", 1, 4),
    SettingDef("limits.light_concurrency", 5, "int", "resources", 1, 20),
    SettingDef("limits.max_pages_per_company", 5, "int", "resources", 1, 20),
    SettingDef("limits.screenshots_per_site", 2, "int", "resources", 0, 6),
    SettingDef("limits.min_free_disk_gb", 15, "int", "resources", 1, 500),
    SettingDef("limits.max_screenshot_bytes", 450_000, "int", "resources", 50_000, 3_000_000),
    SettingDef("limits.http_timeout_seconds", 20, "int", "resources", 3, 120),
    SettingDef("limits.max_response_bytes", 5_000_000, "int", "resources", 100_000, 50_000_000),
    SettingDef("limits.max_redirects", 5, "int", "resources", 0, 10),
    SettingDef("limits.browser_timeout_seconds", 45, "int", "resources", 10, 300),
    SettingDef("limits.max_memory_percent", 85, "int", "resources", 50, 98),
    SettingDef("limits.max_cpu_percent", 90, "int", "resources", 50, 100),
    SettingDef("limits.max_evidence_storage_mb", 2048, "int", "resources", 100, 50_000),
    # Audit behaviour
    SettingDef("audit.lighthouse_enabled", True, "bool", "audit"),
    SettingDef("audit.consent_tests_enabled", True, "bool", "audit"),
    SettingDef("audit.desktop_viewport", "1366x900", "str", "audit"),
    SettingDef("audit.mobile_viewport", "390x844", "str", "audit"),
    SettingDef("audit.reuse_audit_days", 14, "int", "audit", 0, 365),
    # Discovery
    SettingDef("geofabrik.base_url", "https://download.geofabrik.de", "str", "discovery"),
    SettingDef("geofabrik.max_extract_bytes", 1_200_000_000, "int", "discovery", 50_000_000, 10_000_000_000),
    SettingDef("geofabrik.min_reimport_days", 7, "int", "discovery", 1, 365),
    SettingDef("discovery.initial_countries", ["TR", "NL", "DE", "GB", "US"], "list", "discovery"),
    SettingDef("discovery.initial_import_scheduled", False, "bool", "internal"),
    SettingDef("discovery.priority_countries", ["TR", "NL", "DE", "GB", "US"], "list", "discovery"),
    # Monitoring
    SettingDef("monitoring.recheck_days", 14, "int", "monitoring", 1, 365),
    SettingDef("monitoring.score_change_threshold", 8, "int", "monitoring", 1, 50),
    SettingDef("monitoring.performance_change_threshold", 15, "int", "monitoring", 1, 100),
    # Apify (optional)
    SettingDef("apify.enabled", False, "bool", "apify"),
    SettingDef("apify.token", None, "str", "apify", secret=True),
    SettingDef("apify.daily_budget_usd", 0.0, "float", "apify", 0, 10_000),
    SettingDef("apify.monthly_budget_usd", 0.0, "float", "apify", 0, 100_000),
    SettingDef("apify.max_cost_per_task_usd", 0.0, "float", "apify", 0, 1_000),
    SettingDef("apify.alert_percent", 80, "int", "apify", 1, 100),
    # Reports / branding
    SettingDef("report.branding_name", "", "str", "reports"),
    SettingDef("report.branding_contact", "", "str", "reports"),
    SettingDef("report.branding_accent", "#C5F35C", "str", "reports"),
]

DEF_BY_KEY = {d.key: d for d in DEFS}


def _coerce(d: SettingDef, value: Any) -> Any:
    if value is None:
        return None
    if d.kind == "int":
        v = int(value)
    elif d.kind == "float":
        v = float(value)
    elif d.kind == "bool":
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    elif d.kind in {"list", "hosts"}:
        if not isinstance(value, list):
            raise ValueError(f"{d.key} must be a list")
        v = [str(x).strip() for x in value if str(x).strip()]
        if d.kind == "hosts":
            from leadradar.core.origins import normalize_host

            v = [normalize_host(h) for h in v]
        return v
    elif d.kind == "origin":
        from leadradar.core.origins import validate_origin

        return validate_origin(str(value)) if str(value).strip() else None
    else:
        return str(value)
    if d.min is not None and v < d.min:
        raise ValueError(f"{d.key} must be >= {d.min}")
    if d.max is not None and v > d.max:
        raise ValueError(f"{d.key} must be <= {d.max}")
    return v


def get_setting(db: Session, key: str) -> Any:
    d = DEF_BY_KEY[key]
    row = db.get(ApplicationSetting, key)
    if row is None:
        return d.default
    if d.secret:
        return row.value  # encrypted; callers decrypt
    return row.value


def get_settings_map(db: Session, keys: list[str] | None = None) -> dict[str, Any]:
    wanted = keys or [d.key for d in DEFS]
    rows = {r.key: r for r in db.scalars(select(ApplicationSetting).where(ApplicationSetting.key.in_(wanted)))}
    out: dict[str, Any] = {}
    for k in wanted:
        d = DEF_BY_KEY[k]
        out[k] = rows[k].value if k in rows else d.default
    return out


def set_setting(db: Session, key: str, value: Any, *, admin: bool = True) -> Any:
    d = DEF_BY_KEY.get(key)
    if d is None:
        raise KeyError(key)
    if d.secret:
        from leadradar.core.security import encrypt_secret

        stored = encrypt_secret(str(value)) if value else None
    else:
        stored = _coerce(d, value)
    row = db.get(ApplicationSetting, key)
    if row is None:
        row = ApplicationSetting(key=key, value=stored, is_secret=d.secret, admin_customized=admin)
        db.add(row)
    else:
        row.value = stored
        row.admin_customized = row.admin_customized or admin
    db.flush()
    return stored


def public_settings_view(db: Session) -> dict[str, Any]:
    """Settings for the admin UI; secrets are reduced to a configured flag."""
    values = get_settings_map(db)
    out = {}
    for d in DEFS:
        if d.group == "internal":
            continue
        v = values[d.key]
        out[d.key] = {"value": (bool(v) if d.secret else v), "kind": d.kind, "group": d.group,
                      "secret": d.secret, "min": d.min, "max": d.max}
    return out
