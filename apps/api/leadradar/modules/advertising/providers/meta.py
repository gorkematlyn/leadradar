"""Meta Ad Library via the official Graph API ``ads_archive`` endpoint.

Requirements (administrator-provided, optional): a user access token of a Meta
developer account that completed Ad Library API identity verification.
Scope: ``ad_type=ALL`` returns all ads only for ads delivered to the EU (DSA); outside
the EU results are limited to political/issue ads, so a ``no_results`` outside the EU
is reported with that limitation and never as proof of no advertising.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.parse import urlencode, urlsplit

from leadradar.modules.advertising.providers.base import (
    BLOCKED,
    ERROR,
    FOUND,
    MATCH_REQUIRED,
    NO_RESULTS,
    NOT_CHECKED,
    RATE_LIMITED,
    CompanyQuery,
    FoundAd,
    FoundAdvertiser,
    Provider,
    ProviderResult,
)
from leadradar.modules.crm.normalize import name_similarity, normalize_domain
from leadradar.modules.netsafe.http import safe_fetch

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
      "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
FIELDS = "id,page_id,page_name,ad_delivery_start_time,ad_delivery_stop_time,ad_snapshot_url,ad_creative_bodies," \
         "ad_creative_link_captions,ad_creative_link_titles,publisher_platforms"


class MetaProvider(Provider):
    key = "meta"
    automated = True

    def is_configured(self) -> bool:
        return bool(self.credentials.get("access_token"))

    def research(self, q: CompanyQuery) -> ProviderResult:
        manual = self.manual_url(q)
        if not self.is_configured():
            return ProviderResult(NOT_CHECKED, source_url=manual,
                                  notes="No Ad Library API token configured; use the official link for manual research.")
        version = self.config.get("api_version", "v23.0")
        countries = [q.country_iso2.upper()] if q.country_iso2 else ["NL"]
        in_eu = all(c in EU for c in countries)
        params = {
            "access_token": self.credentials["access_token"], "search_terms": q.name[:100],
            "ad_reached_countries": json.dumps(countries), "ad_active_status": "ALL",
            "ad_type": "ALL" if in_eu else "POLITICAL_AND_ISSUE_ADS", "fields": FIELDS, "limit": 50,
        }
        url = f"https://graph.facebook.com/{version}/ads_archive?{urlencode(params)}"
        res = safe_fetch(url, max_bytes=3_000_000, timeout=30)
        scope = {"countries": countries, "ad_type": params["ad_type"], "search_terms": q.name,
                 "limitation": None if in_eu else "Outside the EU the API only covers political/issue ads."}
        if res.status is None:
            return ProviderResult(BLOCKED if res.blocked else ERROR, source_url=manual, search_scope=scope,
                                  error=res.error)
        try:
            data = json.loads(res.body or b"{}")
        except ValueError:
            return ProviderResult(ERROR, source_url=manual, search_scope=scope, error="invalid JSON response")
        if res.status != 200:
            err = (data.get("error") or {})
            code = err.get("code")
            status = RATE_LIMITED if code in (4, 17, 32, 613) or res.status == 429 else ERROR
            return ProviderResult(status, source_url=manual, search_scope=scope,
                                  error=f"{err.get('type', '')}: {err.get('message', '')}"[:300])
        return parse_response(data, q, manual, scope)


def _date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_response(data: dict, q: CompanyQuery, manual: str | None, scope: dict) -> ProviderResult:
    rows = data.get("data") or []
    if not rows:
        return ProviderResult(NO_RESULTS, source_url=manual, search_scope=scope,
                              notes="No matching ads within the documented search scope. This is not proof that the company never advertises.")
    pages: dict[str, dict] = {}
    ads: list[FoundAd] = []
    today = datetime.now(UTC).date()
    for r in rows:
        pid = str(r.get("page_id") or "")
        if not pid:
            continue
        captions = [c.lower() for c in (r.get("ad_creative_link_captions") or [])]
        page = pages.setdefault(pid, {"name": r.get("page_name") or pid, "domains": set()})
        for c in captions:
            d = normalize_domain(c)
            if d:
                page["domains"].add(d)
        stop = _date(r.get("ad_delivery_stop_time"))
        ads.append(FoundAd(
            platform_ad_id=str(r.get("id")), advertiser_id=pid, ad_format=",".join(r.get("publisher_platforms") or []) or None,
            ad_text=" | ".join(r.get("ad_creative_bodies") or [])[:2000] or None,
            landing_page_url=captions[0] if captions else None,
            status="active" if stop is None or stop >= today else "inactive",
            start_date=_date(r.get("ad_delivery_start_time")), end_date=stop,
            geographic_scope=scope["countries"], source_url=r.get("ad_snapshot_url"),
        ))
    advertisers = []
    for pid, page in pages.items():
        reasons = []
        sim = name_similarity(q.name, page["name"])
        conf = 0.6 * sim
        if sim >= 0.6:
            reasons.append(f"name_similarity_{sim:.2f}")
        if q.domain and q.domain in page["domains"]:
            conf += 0.4
            reasons.append("landing_domain_match")
        advertisers.append(FoundAdvertiser(pid, page["name"], round(min(conf, 1.0), 2), reasons,
                                           f"https://www.facebook.com/ads/library/?view_all_page_id={pid}"))
    advertisers.sort(key=lambda a: -a.match_confidence)
    strong = [a for a in advertisers if "landing_domain_match" in a.match_reasons and a.match_confidence >= 0.8]
    status = FOUND if len(strong) == 1 else MATCH_REQUIRED
    return ProviderResult(status, advertisers, ads, manual, scope,
                          notes=None if status == FOUND else "Ambiguous advertiser match: administrator confirmation required.")


def host(url: str) -> str:
    return urlsplit(url).hostname or ""
