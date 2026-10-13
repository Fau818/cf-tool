"""Real-browser fallback (DrissionPage) for what plain HTTP cannot do: get
past a Cloudflare / Turnstile check, and log in when the form demands one.

gateway.py runs these headless first and in a visible window only as a last
resort. Cookies and the User-Agent exported here go back to the HTTP
transport together: Cloudflare binds cf_clearance to the UA (and to the IP,
which is why the browser uses the configured proxy too).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

from cf_tool import pages
from cf_tool.errors import BrowserError, BrowserUnavailable, CFError, LoginRejected
from cf_tool.http import CookieDict

T = TypeVar("T")

# seconds for a whole fetch/login; a window may be waiting on a human click
TIMEOUT = {True: 45.0, False: 180.0}
_POLL = 0.5

_JS_USER_AGENT = "return navigator.userAgent;"
_JS_FORM_ERRORS = (
    "return Array.from(document.querySelectorAll('.error'))"
    ".map(e => e.textContent.trim()).filter(Boolean);"
)
_JS_TURNSTILE_TOKEN = (
    "const e = document.querySelector('[name=\"cf-turnstile-response\"]');"
    " return e ? e.value : '';"
)


@dataclass
class BrowserSession:
    cookies: list[CookieDict]
    user_agent: str
    html: str


def fetch(url: str, *, headless: bool, proxy: str = "") -> BrowserSession:
    """Visit url, wait out any Cloudflare/Turnstile check, export the session."""

    def action(page) -> BrowserSession:
        _goto(page, url, time.monotonic() + TIMEOUT[headless])
        return _export(page)

    return _run(headless, proxy, action)


def login(
    host: str, handle_or_email: str, password: str, *, headless: bool, proxy: str = ""
) -> BrowserSession:
    """Log in through the real /enter form; returns the logged-in session.

    Raises LoginRejected when Codeforces itself refuses the credentials.
    """

    def action(page) -> BrowserSession:
        deadline = time.monotonic() + TIMEOUT[headless]
        handle_input = _login_form(page, f"{host}/enter", deadline)
        password_input = _fill(page, handle_input, handle_or_email, password)
        if pages.has_turnstile(_html(page)) and not _wait(
            lambda: bool(_js(page, _JS_TURNSTILE_TOKEN)), deadline
        ):
            raise CFError("the Turnstile check on the login form was not passed in time")
        submit = page.ele("@value=Login", timeout=2) or page.ele(
            'xpath://input[@type="submit"]', timeout=2
        )
        if submit:
            submit.click()
        else:
            password_input.input("\n")
        return _login_result(page, deadline)

    return _run(headless, proxy, action)


# ------------------------------------------------------------------ helpers


def _run(headless: bool, proxy: str, action: Callable[[Any], T]) -> T:
    """Launch Chrome, run action(page), always quit; anything DrissionPage
    throws becomes a BrowserError (our own CFErrors pass through)."""
    page = _launch(headless, proxy)
    try:
        return action(page)
    except CFError:
        raise
    except Exception as e:
        raise BrowserError(f"{type(e).__name__}: {_first_line(e)}") from e
    finally:
        try:
            page.quit()
        except Exception:
            pass


def _launch(headless: bool, proxy: str):
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError as e:
        raise BrowserUnavailable("DrissionPage is missing: reinstall cf-tool") from e

    def options(user_agent: str = ""):
        opts = ChromiumOptions()
        opts.auto_port()  # private temporary profile, free debugging port
        for arg in (
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-blink-features=AutomationControlled",
        ):
            opts.set_argument(arg)
        if proxy:
            # the raw flag: ChromiumOptions.set_proxy() prints its own warnings
            opts.set_argument("--proxy-server", proxy)
        if user_agent:
            opts.set_user_agent(user_agent)
        if headless:
            opts.headless()
        return opts

    try:
        page = ChromiumPage(options())
        if headless:
            user_agent = page.run_js(_JS_USER_AGENT) or ""
            if "HeadlessChrome" in user_agent:
                # cf_clearance is UA-bound: present a normal-Chrome UA from the start
                page.quit()
                page = ChromiumPage(options(user_agent.replace("HeadlessChrome", "Chrome")))
        return page
    except Exception as e:
        raise BrowserUnavailable(
            f"cannot start Chrome ({_first_line(e)}). Is Google Chrome or Chromium installed?"
        ) from e


def _first_line(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


def _html(page) -> str:
    try:
        return page.html or ""
    except Exception:  # mid-navigation: the old document is gone
        return ""


def _js(page, script: str):
    try:
        return page.run_js(script)
    except Exception:
        return None


def _wait(ready: Callable[[], bool], deadline: float) -> bool:
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(_POLL)
    return False


def _bounced_home(requested: str, current: str) -> bool:
    """After solving a challenge Cloudflare sometimes redirects to the site
    root instead of the page we asked for."""
    req, cur = urlparse(requested), urlparse(current)
    return cur.path in ("", "/") and req.path not in ("", "/")


def _goto(page, url: str, deadline: float) -> None:
    """Navigate and wait until no check page is showing; retries once when
    the solved challenge bounced us to the site root."""
    for attempt in range(2):
        page.get(url)
        if not _wait(lambda: (html := _html(page)) != "" and not pages.is_gate(html), deadline):
            raise CFError("the Cloudflare check was not passed in time")
        if attempt or not _bounced_home(url, page.url):
            return


def _login_form(page, enter_url: str, deadline: float):
    """Open /enter and wait for the form; returns the handle input.

    Waits for the form itself rather than for "no gate": that works whatever
    check Cloudflare or Codeforces puts in front of it this week.
    """
    page.get(enter_url)
    retried = False
    while time.monotonic() < deadline:
        try:
            field = page.ele("#handleOrEmail", timeout=0)
            if field:
                return field
            if not retried and _bounced_home(enter_url, page.url):
                retried = True
                page.get(enter_url)
                continue
        except Exception:  # mid-navigation
            pass
        time.sleep(_POLL)
    if pages.is_gate(_html(page)):
        raise CFError("the Cloudflare check was not passed in time")
    raise CFError("could not find the login form")


def _fill(page, handle_input, handle_or_email: str, password: str):
    """Type the credentials, tick "remember me"; returns the password input."""
    handle_input.clear()
    handle_input.input(handle_or_email)
    password_input = page.ele("#password", timeout=5)
    if not password_input:
        raise CFError("could not find the password field")
    password_input.clear()
    password_input.input(password)
    remember = page.ele("#remember", timeout=1)
    if remember and not remember.attr("checked"):
        remember.click()
    return password_input


def _login_result(page, deadline: float) -> BrowserSession:
    """Wait for the outcome of submitting the login form."""
    while time.monotonic() < deadline:
        if pages.find_handle(_html(page)):
            return _export(page)
        errors = _js(page, _JS_FORM_ERRORS) or []
        if errors:
            message = str(errors[0])
            if pages.is_captcha_error(message):
                raise CFError(message)
            raise LoginRejected(message)
        time.sleep(_POLL)
    raise CFError("the login did not complete in time")


def _export(page) -> BrowserSession:
    cookies = []
    for c in page.cookies(all_info=True):
        expires = c.get("expires")
        cookies.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain") or urlparse(page.url).hostname or "",
                "path": c.get("path") or "/",
                "secure": bool(c.get("secure")),
                # CDP: seconds since epoch, -1 for a session cookie
                "expires": (
                    int(expires) if isinstance(expires, (int, float)) and expires > 0 else None
                ),
            }
        )
    user_agent = _js(page, _JS_USER_AGENT) or ""
    return BrowserSession(cookies=cookies, user_agent=user_agent, html=_html(page))
