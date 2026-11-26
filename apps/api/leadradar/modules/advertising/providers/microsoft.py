"""Microsoft advertising research provider (independent module).

Automated research: unsupported. Microsoft documents an EU/EEA Ad Library API, but its parameters were not verified for this release; automated research stays disabled.
The provider exposes the official manual research link (when one exists) and accepts
administrator-recorded, verified results via the manual research workflow.
"""

from __future__ import annotations

from leadradar.modules.advertising.providers.base import UNSUPPORTED, CompanyQuery, Provider, ProviderResult

REASON = "Microsoft documents an EU/EEA Ad Library API, but its parameters were not verified for this release; automated research stays disabled."


class MicrosoftProvider(Provider):
    key = "microsoft"
    automated = False

    def is_configured(self) -> bool:
        return False

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q), notes=REASON,
                              search_scope={"automated": False})
