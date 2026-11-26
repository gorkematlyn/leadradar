"""Google advertising research provider (independent module).

Automated research: unsupported. Google Ads Transparency Center has no public API; automated scraping is not permitted by Google's terms.
The provider exposes the official manual research link (when one exists) and accepts
administrator-recorded, verified results via the manual research workflow.
"""

from __future__ import annotations

from leadradar.modules.advertising.providers.base import UNSUPPORTED, CompanyQuery, Provider, ProviderResult

REASON = "Google Ads Transparency Center has no public API; automated scraping is not permitted by Google's terms."


class GoogleProvider(Provider):
    key = "google"
    automated = False

    def is_configured(self) -> bool:
        return False

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q), notes=REASON,
                              search_scope={"automated": False})
