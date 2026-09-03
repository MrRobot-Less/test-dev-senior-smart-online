from test_dev_senior_smart_online.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name == "test-dev-senior-smart-online"
    assert settings.base_url == "https://example.com"
    assert settings.headless is True
    assert settings.browser == "chromium"
    assert settings.retry_max_attempts == 3


def test_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_BASE_URL", "https://example.org")
    monkeypatch.setenv("APP_HEADLESS", "false")
    monkeypatch.setenv("APP_RETRY_MAX_ATTEMPTS", "5")
    settings = Settings(_env_file=None)
    assert settings.base_url == "https://example.org"
    assert settings.headless is False
    assert settings.retry_max_attempts == 5
