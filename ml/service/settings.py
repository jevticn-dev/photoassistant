"""Service configuration.

Environment variables only — no path, host or credential is written in the code.
Locally those variables come from the repository-root ``.env``; in a container
compose sets them. The service cannot tell the difference.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from the environment."""

    model_config = SettingsConfigDict(
        # Empty prefix: variables are named exactly as in .env, so answering
        # "where is this set" is a plain text search.
        env_prefix="",
        extra="ignore",
    )

    environment: str = "development"
    """Environment name. Returned by the health endpoint so it is clear which instance answered."""


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process.

    The cache is also the seam a test can use to substitute its own settings
    (``get_settings.cache_clear()``).
    """
    return Settings()
