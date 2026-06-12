"""Browser automation (DrissionPage) for what plain HTTP cannot do:
solving Cloudflare challenges and logging in past Turnstile.

Used headless first; the visible browser is the last resort. The cookies and
User-Agent exported here get transplanted into the curl_cffi transport —
cf_clearance is bound to the UA, so both must travel together.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from cf_tool import pages
from cf_tool.errors import CFError

_CHALLENGE_MARKERS = ("Just a moment", "challenge-platform", "cf-chl")
_CHALLENGE_TIMEOUT = 45
_LOGIN_TIMEOUT = 40


@dataclass
class BrowserSession:
    cookies: dict[str, str]
    user_agent: str
    html: str
    url: str


def _make_page(headless: bool):
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError as e:
        raise CFError("DrissionPage is required: pip install DrissionPage") from e

    options = ChromiumOptions()
    options.auto_port()
    options.set_argument("--no-first-run")
    options.set_argument("--no-default-browser-check")
    options.set_argument("--disable-infobars")
    options.set_argument("--disable-blink-features=AutomationControlled")
    if headless:
        options.headless()
    page = ChromiumPage(options)
    if headless:
        ua = page.run_js("return navigator.userAgent;") or ""
        if "HeadlessChrome" in ua:
            # cf_clearance is UA-bound: present a normal-Chrome UA from the start
            page.quit()
            options.set_user_agent(ua.replace("HeadlessChrome", "Chrome"))
            page = ChromiumPage(options)
    return page


def _is_challenge_page(page) -> bool:
    html = page.html or ""
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def _wait_challenge(page, timeout: float = _CHALLENGE_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_challenge_page(page):
            return True
        time.sleep(0.5)
    return False


def _bounced_home(requested: str, current: str) -> bool:
    """After solving a challenge Cloudflare sometimes redirects to the site
    root instead of the page we asked for."""
    req, cur = urlparse(requested), urlparse(current)
    return cur.path in ("", "/") and req.path not in ("", "/")


def _goto(page, url: str) -> None:
    """Navigate, wait out any challenge, retry once if bounced to the root."""
    page.get(url)
    if not _wait_challenge(page):
        raise CFError("Cloudflare challenge was not solved in time")
    if _bounced_home(url, page.url):
        page.get(url)
        if not _wait_challenge(page):
            raise CFError("Cloudflare challenge was not solved in time")


def _export(page) -> BrowserSession:
    cookies = {c["name"]: c["value"] for c in page.cookies()}
    user_agent = page.run_js("return navigator.userAgent;") or ""
    return BrowserSession(cookies=cookies, user_agent=user_agent, html=page.html, url=page.url)


def fetch(url: str, headless: bool) -> BrowserSession:
    """Visit a URL, waiting out any Cloudflare challenge, and export the session."""
    page = _make_page(headless)
    try:
        _goto(page, url)
        return _export(page)
    finally:
        try:
            page.quit()
        except Exception:
            pass


def login(host: str, handle_or_email: str, password: str, headless: bool) -> BrowserSession:
    """Log in through the real /enter form; returns the authenticated session."""
    page = _make_page(headless)
    try:
        _goto(page, f"{host}/enter")

        # Already logged in? Codeforces redirects away from /enter. (_goto
        # already retried the Cloudflare bounce-to-home, so a non-/enter URL
        # here really is the logged-in redirect — but verify via the handle.)
        if "/enter" not in page.url and pages.find_handle(page.html or ""):
            return _export(page)

        deadline = time.monotonic() + _LOGIN_TIMEOUT
        handle_input = None
        while time.monotonic() < deadline:
            handle_input = page.ele("#handleOrEmail", timeout=1)
            if handle_input:
                break
        if not handle_input:
            raise CFError("Could not find the login form")

        handle_input.clear()
        handle_input.input(handle_or_email)
        password_input = page.ele("#password", timeout=5)
        if not password_input:
            raise CFError("Could not find the password field")
        password_input.clear()
        password_input.input(password)
        remember = page.ele("#remember", timeout=1)
        if remember and not remember.attr("checked"):
            remember.click()
        submit = page.ele("@value=Login", timeout=2) or page.ele(
            'xpath://input[@type="submit"]', timeout=2
        )
        if submit:
            submit.click()
        else:
            password_input.input("\n")

        while time.monotonic() < deadline:
            if "/enter" not in page.url:
                return _export(page)
            error = page.ele(".error", timeout=0)
            if error and error.text:
                raise CFError(error.text)
            time.sleep(0.5)
        raise CFError("Login timed out (check handle/password)")
    finally:
        try:
            page.quit()
        except Exception:
            pass
