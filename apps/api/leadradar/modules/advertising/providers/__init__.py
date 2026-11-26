from leadradar.modules.advertising.providers.base import Provider
from leadradar.modules.advertising.providers.google import GoogleProvider
from leadradar.modules.advertising.providers.linkedin import LinkedInProvider
from leadradar.modules.advertising.providers.meta import MetaProvider
from leadradar.modules.advertising.providers.microsoft import MicrosoftProvider
from leadradar.modules.advertising.providers.openai import OpenAIProvider
from leadradar.modules.advertising.providers.tiktok import TikTokProvider

REGISTRY: dict[str, type[Provider]] = {
    "meta": MetaProvider,
    "google": GoogleProvider,
    "linkedin": LinkedInProvider,
    "tiktok": TikTokProvider,
    "microsoft": MicrosoftProvider,
    "openai": OpenAIProvider,
}
