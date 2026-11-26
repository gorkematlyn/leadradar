"""Advertising research provider interface.

Every provider is independent: own configuration, execution logic, status handling,
parser and rate limit. Providers never fabricate results; when automated research is
not legitimately available they report ``unsupported`` and expose an official manual
research link instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import quote_plus

# Provider result states
FOUND = "found"
NO_RESULTS = "no_results"
MATCH_REQUIRED = "match_required"
NOT_CHECKED = "not_checked"
RATE_LIMITED = "rate_limited"
BLOCKED = "blocked"
UNSUPPORTED = "unsupported"
ERROR = "error"
STATES = {FOUND, NO_RESULTS, MATCH_REQUIRED, NOT_CHECKED, RATE_LIMITED, BLOCKED, UNSUPPORTED, ERROR}


@dataclass
class CompanyQuery:
    company_id: str
    name: str
    domain: str | None
    website: str | None
    country_iso2: str | None
    social_handles: dict[str, list[str]] = field(default_factory=dict)
    known_advertiser_ids: list[str] = field(default_factory=list)

    @property
    def terms(self) -> list[str]:
        t = [self.name]
        if self.domain:
            t.append(self.domain)
        return t


@dataclass
class FoundAdvertiser:
    platform_advertiser_id: str
    name: str
    match_confidence: float
    match_reasons: list[str]
    source_url: str | None = None


@dataclass
class FoundAd:
    platform_ad_id: str
    advertiser_id: str
    ad_format: str | None = None
    ad_text: str | None = None
    landing_page_url: str | None = None
    status: str | None = None  # active / inactive / unknown
    start_date: date | None = None
    end_date: date | None = None
    geographic_scope: list[str] = field(default_factory=list)
    source_url: str | None = None


@dataclass
class ProviderResult:
    status: str
    advertisers: list[FoundAdvertiser] = field(default_factory=list)
    ads: list[FoundAd] = field(default_factory=list)
    source_url: str | None = None
    search_scope: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    error: str | None = None
    researched_at: datetime | None = None


class Provider:
    key = "base"
    automated = False

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any], manual_template: str | None) -> None:
        self.config = config
        self.credentials = credentials
        self.manual_template = manual_template

    def is_configured(self) -> bool:
        return False

    def manual_url(self, q: CompanyQuery) -> str | None:
        if not self.manual_template:
            return None
        return self.manual_template.format(
            query=quote_plus(q.name), domain=quote_plus(q.domain or ""), country=(q.country_iso2 or "ALL").upper(),
        )

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q),
                              notes="Automated research is not available for this provider; use the official link.")
