"""Application settings, loaded from environment variables and an optional .env file."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "EVE Healthcare API"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # SQLite by default so the project runs with zero setup; docker-compose
    # and production override this with a PostgreSQL URL.
    DATABASE_URL: str = "sqlite:///./eve_dev.db"

    JWT_SECRET_KEY: str = "dev-only-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # HMAC secret for /payments/webhook. Empty disables signature verification
    # (development only); docker-compose sets a default so the flow is exercised.
    WEBHOOK_SECRET: str = ""

    # Bootstrap admin account, created at startup when missing.
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "Admin@12345"  # MUST be overridden outside development
    ADMIN_FULL_NAME: str = "EVE Admin"

    SEED_DEMO_DATA: bool = False
    DEMO_USER_EMAIL: str = "demo@example.com"
    DEMO_USER_PASSWORD: str = "Demo@12345"

    # Fixed-window rate limit applied to auth endpoints (per client IP).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 30
    # Applied to mutating endpoints (create/cancel booking, create payment).
    RATE_LIMIT_MUTATIONS_PER_MINUTE: int = 60
    # Key rate limits on X-Forwarded-For (leftmost entry) instead of the socket
    # peer — enable ONLY behind a proxy that overwrites that header.
    TRUST_PROXY_HEADERS: bool = False

    # Gate /docs, /redoc and /openapi.json — set false in production.
    DOCS_ENABLED: bool = True

    # Read-through cache for centres/tests listing endpoints.
    CACHE_BACKEND: str = "memory"  # "memory" | "redis"
    REDIS_URL: str = ""
    CACHE_CENTRES_TTL_SECONDS: int = 60

    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    @model_validator(mode="after")
    def _fail_closed_on_insecure_defaults(self) -> "Settings":
        """Prevent accidental production deployments with weak defaults.

        * An empty WEBHOOK_SECRET disables signature verification — never
          acceptable outside the development sandbox.
        * Leaving ADMIN_PASSWORD at the shipped default means every attacker
          with the source already knows it.
        """
        if self.ENVIRONMENT != "development":
            _DEFAULT_ADMIN_PASSWORD = "Admin@12345"
            if self.ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD:
                raise ValueError(
                    "ADMIN_PASSWORD must be changed from the default value "
                    f"when ENVIRONMENT is '{self.ENVIRONMENT}'. "
                    "Set a strong password via the ADMIN_PASSWORD env variable."
                )
            if not self.WEBHOOK_SECRET:
                raise ValueError(
                    "WEBHOOK_SECRET must be set (non-empty) when ENVIRONMENT is "
                    f"'{self.ENVIRONMENT}'. An empty secret disables webhook "
                    "signature verification, which is only safe in local development."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
