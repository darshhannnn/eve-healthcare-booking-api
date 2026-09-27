"""Application settings, loaded from environment variables and an optional .env file."""

from functools import lru_cache

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
    ADMIN_PASSWORD: str = "Admin@12345"
    ADMIN_FULL_NAME: str = "EVE Admin"

    SEED_DEMO_DATA: bool = False
    DEMO_USER_EMAIL: str = "demo@example.com"
    DEMO_USER_PASSWORD: str = "Demo@12345"

    # Fixed-window rate limit applied to auth endpoints (per client IP).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 30

    # Read-through cache for centres/tests listing endpoints.
    CACHE_BACKEND: str = "memory"  # "memory" | "redis"
    REDIS_URL: str = ""
    CACHE_CENTRES_TTL_SECONDS: int = 60

    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
