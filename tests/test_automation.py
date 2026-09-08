import pytest

from smart_online_automation.automation import BrowserAutomation, NavigationError
from smart_online_automation.config import Settings


@pytest.mark.asyncio
async def test_page_opens_with_title() -> None:
    settings = Settings(
        _env_file=None,
        portal_url="data:text/html,<title>Hello Automation</title><h1>Hello</h1>",
        headless=True,
    )
    async with BrowserAutomation(settings) as automation:
        page = await automation.open(settings.portal_url)
        assert await page.title() == "Hello Automation"
        assert await page.locator("h1").inner_text() == "Hello"
        await page.close()


class FakePage:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.title = ""

    def set_default_timeout(self, timeout: int) -> None:
        pass

    async def goto(self, url: str, wait_until: str) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("navigation timed out")
        self.title = "Loaded"

    async def close(self) -> None:
        pass


class FakeBrowser:
    def __init__(self, failures: int) -> None:
        self.remaining_failures = failures

    async def new_page(self) -> FakePage:
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            return FakePage(failures=1)
        return FakePage(failures=0)


class FakeBrowserQuebraNoClose:
    async def close(self) -> None:
        raise RuntimeError("Connection closed while reading from the drive")


class FakePlaywrightQuebraNoStop:
    async def stop(self) -> None:
        raise RuntimeError("stop falhou")


@pytest.mark.asyncio
async def test_fechamento_nao_quebra_quando_close_falha() -> None:
    settings = Settings(_env_file=None)
    automation = BrowserAutomation(settings)
    automation._browser = FakeBrowserQuebraNoClose()
    automation._pw = FakePlaywrightQuebraNoStop()

    await automation.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_open_retries_until_success(monkeypatch) -> None:
    settings = Settings(_env_file=None, retry_max_attempts=3, retry_wait_seconds=0.01)
    automation = BrowserAutomation(settings)
    monkeypatch.setattr(automation, "_browser", FakeBrowser(2))

    page = await automation.open("https://example.com")

    assert page.title == "Loaded"


@pytest.mark.asyncio
async def test_open_gives_up_after_max_attempts(monkeypatch) -> None:
    settings = Settings(_env_file=None, retry_max_attempts=2, retry_wait_seconds=0.01)
    automation = BrowserAutomation(settings)
    monkeypatch.setattr(automation, "_browser", FakeBrowser(99))

    raised = False
    try:
        await automation.open("https://example.com")
    except NavigationError:
        raised = True

    assert raised is True