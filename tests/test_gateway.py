"""Login tiers and the Cloudflare fallback, with a fake transport and browser.

The policy under test: HTTP first, then a background (headless) browser,
then a window; a credentials error or a missing Chrome stops the climb.
"""

import threading
import time

import pytest

from cf_tool import crypto, gateway
from cf_tool.browser import BrowserSession
from cf_tool.config import Config
from cf_tool.errors import (
    BrowserUnavailable,
    CFError,
    CloudflareChallengeError,
    LoginRejected,
)
from cf_tool.session import Session

HOST = "https://codeforces.com"
LOGGED_IN = '<script>var handle = "tourist";</script>'
LOGIN_FORM = "<form><script>csrf='abc'</script></form>"


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeTransport:
    """Answers by URL; a value of CloudflareChallengeError is raised instead."""

    def __init__(self, gets=None, posts=None):
        self.gets = dict(gets or {})
        self.posts = dict(posts or {})
        self.cookies: list[dict] = []
        self.user_agent = ""
        self.calls: list[str] = []

    def _answer(self, table, method, url):
        self.calls.append(f"{method} {url}")
        answer = table.get(url)
        if callable(answer) and answer is not CloudflareChallengeError:
            answer = answer()
        if answer is CloudflareChallengeError:
            raise CloudflareChallengeError()
        return FakeResponse(answer if answer is not None else "")

    def get(self, url, **kwargs):
        return self._answer(self.gets, "GET", url)

    def post(self, url, data=None, **kwargs):
        return self._answer(self.posts, "POST", url)

    def get_json(self, url):
        return {}

    def export_cookies(self):
        return list(self.cookies)

    def adopt_cookies(self, cookies):
        names = {c["name"] for c in cookies}
        self.cookies = [c for c in self.cookies if c["name"] not in names] + list(cookies)

    def clear_cookies(self, keep=None):
        self.cookies = [c for c in self.cookies if keep is not None and keep(c["name"])]

    def set_user_agent(self, user_agent):
        if user_agent:
            self.user_agent = user_agent


def cookie(name, value="v"):
    return {"name": name, "value": value, "domain": "codeforces.com", "path": "/"}


def make_gateway(tmp_path, transport, password="secret"):
    session = Session(tmp_path / "session", handle_or_email="tourist")
    session.password = crypto.encrypt_password("tourist", password)
    gw = gateway.Gateway(Config(), session)
    gw.http = transport
    return gw


def fake_browser(monkeypatch, *, login=None, fetch=None):
    """Patch browser.login / browser.fetch; returns the list of headless flags used."""
    used = []

    def _login(host, handle, password, *, headless, proxy=""):
        used.append(("login", headless))
        return login(headless)

    def _fetch(url, *, headless, proxy=""):
        used.append(("fetch", headless))
        return fetch(headless)

    monkeypatch.setattr(gateway.browser, "login", _login)
    monkeypatch.setattr(gateway.browser, "fetch", _fetch)
    return used


def browser_session(html=LOGGED_IN, cookies=None):
    return BrowserSession(
        cookies=cookies or [cookie("JSESSIONID", "fresh")], user_agent="UA/1", html=html
    )


# ---------------------------------------------------------------- login


def test_http_login_needs_no_browser(tmp_path, monkeypatch):
    transport = FakeTransport(
        gets={f"{HOST}/enter": LOGIN_FORM}, posts={f"{HOST}/enter": LOGGED_IN}
    )
    used = fake_browser(monkeypatch)
    gw = make_gateway(tmp_path, transport)

    assert gw.login() == "tourist"
    assert used == []
    assert gw.session.handle == "tourist"
    assert gw.session.ftaa and gw.session.bfaa == gateway.BFAA
    assert (tmp_path / "session").exists()


def test_http_login_keeps_only_cloudflare_cookies(tmp_path, monkeypatch):
    transport = FakeTransport(
        gets={f"{HOST}/enter": LOGIN_FORM}, posts={f"{HOST}/enter": LOGGED_IN}
    )
    transport.cookies = [cookie("cf_clearance"), cookie("__cf_bm"), cookie("JSESSIONID", "old")]
    fake_browser(monkeypatch)
    gw = make_gateway(tmp_path, transport)
    seen = []
    original = transport.get
    transport.get = lambda url, **kw: (
        seen.append([c["name"] for c in transport.cookies]),
        original(url),
    )[1]

    gw.login()

    assert seen[0] == ["cf_clearance", "__cf_bm"]  # old login cookies dropped, clearance kept


def test_blocked_http_falls_back_to_headless(tmp_path, monkeypatch):
    transport = FakeTransport(
        gets={f"{HOST}/enter": CloudflareChallengeError, HOST: LOGGED_IN},
    )
    used = fake_browser(monkeypatch, login=lambda headless: browser_session())
    gw = make_gateway(tmp_path, transport)

    assert gw.login() == "tourist"
    assert used == [("login", True)]  # never a window
    assert transport.user_agent == "UA/1"  # cf_clearance travels with its UA
    assert [c["value"] for c in gw.session.cookies] == ["fresh"]


def test_window_is_the_last_resort(tmp_path, monkeypatch):
    transport = FakeTransport(gets={f"{HOST}/enter": CloudflareChallengeError, HOST: LOGGED_IN})

    def login(headless):
        if headless:
            raise CFError("the Cloudflare check was not passed in time")
        return browser_session()

    used = fake_browser(monkeypatch, login=login)
    gw = make_gateway(tmp_path, transport)

    assert gw.login() == "tourist"
    assert used == [("login", True), ("login", False)]


def test_wrong_password_stops_at_http(tmp_path, monkeypatch):
    form_error = '<span class="error for__password">Invalid handle/email or password</span>'
    transport = FakeTransport(
        gets={f"{HOST}/enter": LOGIN_FORM}, posts={f"{HOST}/enter": form_error}
    )
    used = fake_browser(monkeypatch)
    gw = make_gateway(tmp_path, transport)

    with pytest.raises(LoginRejected, match="Invalid handle/email or password"):
        gw.login()
    assert used == []


def test_wrong_password_in_headless_never_opens_a_window(tmp_path, monkeypatch):
    transport = FakeTransport(gets={f"{HOST}/enter": CloudflareChallengeError})

    def login(headless):
        raise LoginRejected("Invalid handle/email or password")

    used = fake_browser(monkeypatch, login=login)
    gw = make_gateway(tmp_path, transport)

    with pytest.raises(LoginRejected):
        gw.login()
    assert used == [("login", True)]


def test_missing_chrome_never_tries_a_window(tmp_path, monkeypatch):
    transport = FakeTransport(gets={f"{HOST}/enter": CloudflareChallengeError})

    def login(headless):
        raise BrowserUnavailable("cannot start Chrome")

    used = fake_browser(monkeypatch, login=login)
    gw = make_gateway(tmp_path, transport)

    with pytest.raises(BrowserUnavailable):
        gw.login()
    assert used == [("login", True)]


def test_turnstile_on_the_form_skips_the_http_post(tmp_path, monkeypatch):
    form = LOGIN_FORM + '<div class="cf-turnstile" data-sitekey="x"></div>'
    transport = FakeTransport(gets={f"{HOST}/enter": form, HOST: LOGGED_IN})
    used = fake_browser(monkeypatch, login=lambda headless: browser_session())
    gw = make_gateway(tmp_path, transport)

    gw.login()
    assert not any(call.startswith("POST") for call in transport.calls)
    assert used == [("login", True)]


def test_login_without_credentials(tmp_path):
    gw = gateway.Gateway(Config(), Session(tmp_path / "session"))
    with pytest.raises(CFError, match="cf config"):
        gw.login()


# ------------------------------------------------------------- fetching


def test_challenge_solve_merges_cookies_and_keeps_login(tmp_path, monkeypatch):
    url = f"{HOST}/contest/4"
    answers = iter([CloudflareChallengeError, "content"])
    transport = FakeTransport(gets={url: lambda: next(answers)})
    transport.cookies = [cookie("JSESSIONID", "logged-in"), cookie("cf_clearance", "old")]
    used = fake_browser(
        monkeypatch, fetch=lambda headless: browser_session(cookies=[cookie("cf_clearance", "new")])
    )
    gw = make_gateway(tmp_path, transport)

    assert gw.get(url) == "content"
    assert used == [("fetch", True)]
    values = {c["name"]: c["value"] for c in transport.cookies}
    assert values == {"JSESSIONID": "logged-in", "cf_clearance": "new"}


def test_no_browser_when_fallback_disabled(tmp_path, monkeypatch):
    transport = FakeTransport(gets={HOST: CloudflareChallengeError})
    used = fake_browser(monkeypatch)
    gw = make_gateway(tmp_path, transport)
    with pytest.raises(CloudflareChallengeError):
        gw.get(HOST, browser_fallback=False)
    assert used == []


def test_get_authed_relogs_in_once(tmp_path, monkeypatch):
    url = f"{HOST}/contest/4/my"
    pages_seen = iter(["logged out", LOGGED_IN])
    transport = FakeTransport(
        gets={url: lambda: next(pages_seen), f"{HOST}/enter": LOGIN_FORM},
        posts={f"{HOST}/enter": LOGGED_IN},
    )
    fake_browser(monkeypatch)
    gw = make_gateway(tmp_path, transport)

    assert gw.get_authed(url) == LOGGED_IN
    assert transport.calls.count(f"POST {HOST}/enter") == 1


def test_parallel_fetches_share_one_challenge_solve(tmp_path, monkeypatch):
    url = f"{HOST}/contest/4/submission/1"
    solved = threading.Event()
    transport = FakeTransport(
        gets={url: lambda: "code" if solved.is_set() else CloudflareChallengeError}
    )

    def fetch(headless):
        time.sleep(0.2)  # let every thread pile up on the lock
        solved.set()
        return browser_session(cookies=[cookie("cf_clearance", "new")])

    used = fake_browser(monkeypatch, fetch=fetch)
    gw = make_gateway(tmp_path, transport)
    results = []
    threads = [threading.Thread(target=lambda: results.append(gw.get(url))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["code"] * 8
    assert used == [("fetch", True)]  # one browser, not eight


def test_failed_relogin_is_not_repeated_by_other_threads(tmp_path, monkeypatch):
    url = f"{HOST}/contest/4/problem/A"
    transport = FakeTransport(gets={url: "logged out", f"{HOST}/enter": CloudflareChallengeError})
    attempts = []

    def login(headless):
        attempts.append(headless)
        raise LoginRejected("Invalid handle/email or password")

    fake_browser(monkeypatch, login=login)
    gw = make_gateway(tmp_path, transport)
    for _ in range(3):
        with pytest.raises(LoginRejected):
            gw.get_authed(url)
    assert attempts == [True]
