"""TikTok advertising research provider (independent module).

Automated research: unsupported. The Commercial Content API requires an approved TikTok research/developer application; it is not enabled in this installation.
The provider exposes the official manual research link (when one exists) and accepts
administrator-recorded, verified results via the manual research workflow.
"""

from __future__ import annotations

from leadradar.modules.advertising.providers.base import UNSUPPORTED, CompanyQuery, Provider, ProviderResult

REASON = "The Commercial Content API requires an approved TikTok research/developer application; it is not enabled in this installation."


class TikTokProvider(Provider):
    key = "tiktok"
    automated = False

    def is_configured(self) -> bool:
        return False

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q), notes=REASON,
                              search_scope={"automated": False})
