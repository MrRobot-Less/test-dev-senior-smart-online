from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )

    app_name: str = "test-dev-senior-smart-online"
    app_env: str = "development"
    debug: bool = False

    base_url: str = "https://example.com"
    browser: str = "chromium"
    headless: bool = True
    slow_mo: int = 0
    navigation_timeout_ms: int = 30_000

    retry_max_attempts: int = 3
    retry_wait_seconds: float = 2.0

    database_url: str = "sqlite+aiosqlite:///./app.db"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
