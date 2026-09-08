from smart_online_automation.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name == "smart-online-automation"
    assert settings.portal_url.startswith("https://portal-sitram.sefaz.ce.gov.br")
    assert settings.headless is True
    assert settings.browser == "chromium"
    assert settings.retry_max_attempts == 3


def test_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_PORTAL_URL", "https://portal.example.org")
    monkeypatch.setenv("APP_HEADLESS", "false")
    monkeypatch.setenv("APP_RETRY_MAX_ATTEMPTS", "5")
    settings = Settings(_env_file=None)
    assert settings.portal_url == "https://portal.example.org"
    assert settings.headless is False
    assert settings.retry_max_attempts == 5