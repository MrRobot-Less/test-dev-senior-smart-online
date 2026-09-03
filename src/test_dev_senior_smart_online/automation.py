from typing import Any

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from test_dev_senior_smart_online.config import Settings
from test_dev_senior_smart_online.logging_config import get_logger

logger = get_logger("automation")


class NavigationError(RuntimeError):
    pass


class BrowserAutomation:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.open = retry(
            retry=retry_if_exception_type(NavigationError),
            stop=stop_after_attempt(settings.retry_max_attempts),
            wait=wait_fixed(settings.retry_wait_seconds),
            reraise=True,
        )(self._open)

    def __enter__(self) -> BrowserAutomation:
        self._pw = sync_playwright().start()
        self._browser = getattr(self._pw, self._settings.browser).launch(
            headless=self._settings.headless,
            slow_mo=self._settings.slow_mo,
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def _open(self, url: str) -> Page:
        if self._browser is None:
            raise RuntimeError("automation not started")
        page = self._browser.new_page()
        page.set_default_timeout(self._settings.navigation_timeout_ms)
        try:
            page.goto(url, wait_until="load")
        except Exception as exc:
            page.close()
            logger.warning("navigation_failed", url=url, error=str(exc))
            raise NavigationError(f"failed to navigate to {url}") from exc
        return page
