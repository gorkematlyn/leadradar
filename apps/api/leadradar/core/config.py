"""Process configuration loaded from environment variables.

Only deployment-level settings live here. Everything an administrator can change at
runtime (domains, limits, priorities, retention, ...) is stored in PostgreSQL in the
``application_settings`` table and read through :mod:`leadradar.core.app_settings`.

No domain or public URL is configured here on purpose: the application is served from
whatever origin Dokploy routes to it.
"""

from __future__ import annotations

import base64
import ipaddress
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["production", "development", "test"] = "production"
    log_level: str = "INFO"

    database_url: str = Field(..., description="postgresql+psycopg://user:pass@host:5432/db")
    db_pool_size: int = 5
    db_max_overflow: int = 5

    session_secret: str = Field(..., min_length=32)
    app_encryption_key: str = Field(..., description="urlsafe base64 32-byte key (Fernet)")

    # Comma-separated CIDRs of reverse proxies whose X-Forwarded-* headers are trusted.
    # Defaults cover Docker bridge / overlay networks used by Dokploy's Traefik.
    trusted_proxies: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    # Worker identity and limits (defaults; administrators may lower them in settings).
    worker_queues: str = "analysis"
    worker_concurrency: int = 2
    worker_tmp_dir: str = "/tmp/leadradar"

    # Additional egress deny list for the network-safety proxy (e.g. the server's public IP).
    egress_deny_cidrs: str = ""
    egress_allowed_ports: str = "80,443"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return v

    @field_validator("app_encryption_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(v.encode())
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("APP_ENCRYPTION_KEY must be urlsafe base64") from exc
        if len(raw) != 32:
            raise ValueError("APP_ENCRYPTION_KEY must decode to 32 bytes (use scripts/generate-secrets.sh)")
        return v

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if self.app_env == "production" and self.session_secret.lower().startswith("change"):
            raise ValueError("SESSION_SECRET still has its example value")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(c.strip(), strict=False) for c in self.trusted_proxies.split(",") if c.strip()]

    @property
    def allowed_ports(self) -> set[int]:
        return {int(p) for p in self.egress_allowed_ports.split(",") if p.strip()}

    @property
    def extra_deny_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(c.strip(), strict=False) for c in self.egress_deny_cidrs.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
