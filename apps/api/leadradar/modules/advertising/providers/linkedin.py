"""LinkedIn advertising research provider (independent module).

Automated research: unsupported. LinkedIn prohibits scraping; the Advertiser Transparency API requires an approved developer application and member OAuth.
The provider exposes the official manual research link (when one exists) and accepts
administrator-recorded, verified results via the manual research workflow.
"""

from __future__ import annotations

from leadradar.modules.advertising.providers.base import UNSUPPORTED, CompanyQuery, Provider, ProviderResult

REASON = "LinkedIn prohibits scraping; the Advertiser Transparency API requires an approved developer application and member OAuth."


class LinkedInProvider(Provider):
    key = "linkedin"
    automated = False

    def is_configured(self) -> bool:
        return False

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q), notes=REASON,
                              search_scope={"automated": False})
