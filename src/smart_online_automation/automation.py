from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from smart_online_automation.config import Settings
from smart_online_automation.logging_config import get_logger

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

    async def __aenter__(self) -> BrowserAutomation:
        self._pw = await async_playwright().start()
        self._browser = await getattr(self._pw, self._settings.browser).launch(
            headless=self._settings.headless,
            slow_mo=self._settings.slow_mo,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning("browser_close_falhou", error=str(exc))
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception as exc:
                logger.warning("playwright_stop_falhou", error=str(exc))

    async def _open(self, url: str) -> Page:
        if self._browser is None:
            raise RuntimeError("automation not started")
        page = await self._browser.new_page()
        page.set_default_timeout(self._settings.navigation_timeout_ms)
        try:
            await page.goto(url, wait_until="load")
        except Exception as exc:
            await page.close()
            logger.warning("navigation_failed", url=url, error=str(exc))
            raise NavigationError(f"failed to navigate to {url}") from exc
        return page