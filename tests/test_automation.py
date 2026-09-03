from test_dev_senior_smart_online.automation import BrowserAutomation, NavigationError
from test_dev_senior_smart_online.config import Settings


def test_page_opens_with_title() -> None:
    settings = Settings(
        _env_file=None,
        base_url="data:text/html,<title>Hello Automation</title><h1>Hello</h1>",
    )
    with BrowserAutomation(settings) as automation:
        page = automation.open(settings.base_url)
        assert page.title() == "Hello Automation"
        assert page.locator("h1").inner_text() == "Hello"


class FakePage:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.title = ""

    def set_default_timeout(self, timeout: int) -> None:
        pass

    def goto(self, url: str, wait_until: str) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("navigation timed out")
        self.title = "Loaded"

    def close(self) -> None:
        pass


class FakeBrowser:
    def __init__(self, failures: int) -> None:
        self.remaining_failures = failures

    def new_page(self) -> FakePage:
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            return FakePage(failures=1)
        return FakePage(failures=0)


def test_open_retries_until_success(monkeypatch) -> None:
    settings = Settings(_env_file=None, retry_max_attempts=3, retry_wait_seconds=0.01)
    automation = BrowserAutomation(settings)
    monkeypatch.setattr(automation, "_browser", FakeBrowser(2))

    page = automation.open("https://example.com")

    assert page.title == "Loaded"


def test_open_gives_up_after_max_attempts(monkeypatch) -> None:
    settings = Settings(_env_file=None, retry_max_attempts=2, retry_wait_seconds=0.01)
    automation = BrowserAutomation(settings)
    monkeypatch.setattr(automation, "_browser", FakeBrowser(99))

    raised = False
    try:
        automation.open("https://example.com")
    except NavigationError:
        raised = True

    assert raised is True
