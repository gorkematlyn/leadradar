"""OpenAI advertising research provider (independent module).

Automated research: unsupported. No official public ChatGPT advertising library or transparency research source was identified.
The provider exposes the official manual research link (when one exists) and accepts
administrator-recorded, verified results via the manual research workflow.
"""

from __future__ import annotations

from leadradar.modules.advertising.providers.base import UNSUPPORTED, CompanyQuery, Provider, ProviderResult

REASON = "No official public ChatGPT advertising library or transparency research source was identified."


class OpenAIProvider(Provider):
    key = "openai"
    automated = False

    def is_configured(self) -> bool:
        return False

    def research(self, q: CompanyQuery) -> ProviderResult:
        return ProviderResult(UNSUPPORTED, source_url=self.manual_url(q), notes=REASON,
                              search_scope={"automated": False})
