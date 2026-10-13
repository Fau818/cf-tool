"""Browser helpers against fake DrissionPage pages (no Chrome needed).

The real thing can only be checked live; these pin down the decisions:
what counts as "still on a check page", and how login errors are classified.
"""

from pathlib import Path

import pytest

from cf_tool import browser
from cf_tool.errors import BrowserUnavailable, CFError, LoginRejected

FIXTURES = Path(__file__).parent / "fixtures"
PROBLEM = (FIXTURES / "problem_4a.html").read_text()
CHALLENGE = (FIXTURES / "challenge_enter.html").read_text()


class FakePage:
    def __init__(self, htmls, url="https://codeforces.com/contest/4/problem/A", js=None):
        self._htmls = list(htmls)
        self.url = url
        self.js = js or {}
        self.visited = []

    @property
    def html(self):
        return self._htmls.pop(0) if len(self._htmls) > 1 else self._htmls[0]

    def get(self, url):
        self.visited.append(url)

    def run_js(self, script):
        for key, value in self.js.items():
            if key in script:
                return value
        return None


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(browser, "_POLL", 0)


def deadline(seconds=1.0):
    return browser.time.monotonic() + seconds


def test_normal_page_with_bot_script_counts_as_passed():
    # the page carries /cdn-cgi/challenge-platform/... (Cloudflare's bot
    # script); this used to keep the browser waiting until its timeout
    page = FakePage([PROBLEM])
    browser._goto(page, page.url, deadline())  # returns at once instead of raising


def test_goto_waits_out_the_interstitial():
    page = FakePage([CHALLENGE, CHALLENGE, PROBLEM])
    browser._goto(page, page.url, deadline())
    assert page.visited == [page.url]


def test_goto_times_out_on_an_endless_challenge():
    page = FakePage([CHALLENGE])
    with pytest.raises(CFError, match="not passed in time"):
        browser._goto(page, page.url, deadline(0.05))


def test_goto_retries_once_after_a_bounce_home():
    page = FakePage([PROBLEM], url="https://codeforces.com/")
    browser._goto(page, "https://codeforces.com/contest/4", deadline())
    assert page.visited == ["https://codeforces.com/contest/4"] * 2


def test_wrong_password_is_rejected_not_escalated():
    page = FakePage(
        ["<form>"], js={"querySelectorAll('.error')": ["Invalid handle/email or password"]}
    )
    with pytest.raises(LoginRejected, match="Invalid handle"):
        browser._login_result(page, deadline())


def test_captcha_complaint_escalates():
    page = FakePage(["<form>"], js={"querySelectorAll('.error')": ["Please verify you are human"]})
    with pytest.raises(CFError) as caught:
        browser._login_result(page, deadline())
    assert not isinstance(caught.value, LoginRejected)


def test_launch_failure_is_browser_unavailable(monkeypatch):
    import DrissionPage

    def broken(*args, **kwargs):
        raise RuntimeError("The browser connection fails.\nTip: ...")

    monkeypatch.setattr(DrissionPage, "ChromiumPage", broken)
    with pytest.raises(BrowserUnavailable, match="cannot start Chrome"):
        browser._launch(headless=True, proxy="")


def test_driver_errors_become_browser_errors(monkeypatch):
    class Page:
        def quit(self):
            pass

    monkeypatch.setattr(browser, "_launch", lambda headless, proxy: Page())

    def action(page):
        raise KeyError("boom")

    with pytest.raises(browser.BrowserError, match="KeyError"):
        browser._run(True, "", action)
