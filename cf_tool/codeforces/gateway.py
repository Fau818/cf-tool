"""The way in to Codeforces: plain HTTP first, a browser only when Cloudflare
insists, and the tiered login.

Login tiers (first that works wins):
  1. HTTP — GET and POST /enter over curl_cffi. Needs no browser, but
     Cloudflare challenges /enter unless a cf_clearance is still valid.
  2. headless browser — passes the checks without showing anything.
  3. browser window — last resort, for when a human has to tick a box.
A credentials error (LoginRejected) stops at once, and so does a missing
Chrome (BrowserUnavailable): another tier would only fail the same way.

Pages are fetched the same way round: HTTP, and only on a challenge a
headless browser, then a window. Browser work, logins and session saves share
one lock; a login or a check passed once is reused, and a failure is not
retried within the run.
"""

from __future__ import annotations

import random
import threading
from typing import Callable, TypeVar
from urllib.parse import urlparse

from cf_tool import ui
from cf_tool.codeforces import browser, crypto, pages
from cf_tool.codeforces.http import Transport, is_cloudflare_cookie
from cf_tool.codeforces.session import Session
from cf_tool.errors import (
    BrowserUnavailable,
    CFError,
    CloudflareChallengeError,
    LoginRejected,
)

T = TypeVar("T")

BFAA = "f1b3f18c715565b589b7823cda7448ce"
LOGIN_COOKIES = ("X-User-Sha1", "X-User")  # NOTE: set only for a logged-in session


def _token(n: int) -> str:
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


class Gateway:
    def __init__(self, host: str, proxy: str, session: Session) -> None:
        self.host = host
        self.proxy = proxy
        self.session = session
        self.http = Transport(proxy=proxy, user_agent=session.user_agent, cookies=session.cookies)
        self._lock = threading.RLock()
        # bumped by each successful login / challenge solve, so a thread that
        # waited on the lock can tell the work was done meanwhile
        self._login_count = 0
        self._solve_count = 0
        # a failure is remembered: other threads must not retry (and pop
        # more windows); a fresh `cf` run tries again
        self._login_error: CFError | None = None
        self._solve_error: CFError | None = None

    def save(self) -> None:
        with self._lock:
            self.session.cookies = self.http.export_cookies()
            self.session.user_agent = self.http.user_agent
            self.session.save()

    # ------------------------------------------------------------- fetching

    def get(self, url: str, *, browser_fallback: bool = True) -> str:
        """Body of url. A Cloudflare check is passed in a browser (headless,
        then a window), unless browser_fallback is False."""
        seen = self._solve_count
        try:
            return self.http.get(url).text
        except CloudflareChallengeError:
            if not browser_fallback:
                raise
        solved = self._solve(url, seen)
        try:
            return self.http.get(url).text
        except CloudflareChallengeError:
            # the transport is still refused, but the browser saw the content
            if solved is not None and not pages.is_gate(solved.html):
                return solved.html
            raise

    def get_authed(self, url: str) -> str:
        """Body of a page that needs login; logs in again once if the session lapsed."""
        seen = self._login_count
        body = self.get(url)
        if pages.find_handle(body) is not None:
            return body
        self._relogin(seen)
        body = self.get(url)
        pages.require_handle(body)
        return body

    def post(self, url: str, data: dict[str, str]) -> str:
        """POST a form. A challenged POST never reached Codeforces, so after
        passing the check in a browser it is safe to send it once more."""
        seen = self._solve_count
        try:
            return self.http.post(url, data=data).text
        except CloudflareChallengeError:
            self._solve(url, seen)
        return self.http.post(url, data=data).text

    def get_json(self, url: str) -> dict:
        return self.http.get_json(url)

    def _solve(self, url: str, seen: int) -> browser.BrowserSession | None:
        """Pass the check on url in a browser and adopt its cookies; None if
        another thread already did so while this one waited."""
        with self._lock:
            if self._solve_count != seen:
                return None
            if self._solve_error is not None:
                raise self._solve_error
            try:
                solved = self._in_browser(
                    "Cloudflare check",
                    lambda headless: browser.fetch(url, headless=headless, proxy=self.proxy),
                )
            except CFError as e:
                self._solve_error = e
                raise
            # NOTE: merged, not replaced; and once logged in, only Cloudflare's
            # \     cookies: the fresh browser profile's own session is anonymous
            logged_in = any(self.http.has_cookie(name) for name in LOGIN_COOKIES)
            self._adopt(solved, replace=False, only_cloudflare=logged_in)
            self._solve_count += 1
            return solved

    def _in_browser(self, what: str, run: Callable[[bool], T]) -> T:
        """run(headless=True); if that fails, run(headless=False) in a window."""
        try:
            with ui.status(f"{what}: working in a background browser..."):
                return run(True)
        except (LoginRejected, BrowserUnavailable):
            raise
        except CFError as e:
            ui.yellow(f"The background browser did not make it ({e}).")
        ui.yellow(
            f"{what}: opening a browser window. If Cloudflare shows a check there, "
            "complete it; everything else is filled in for you."
        )
        with ui.status(f"{what}: waiting for the browser window..."):
            return run(False)

    def _adopt(
        self, solved: browser.BrowserSession, replace: bool, only_cloudflare: bool = False
    ) -> None:
        with self._lock:
            if replace:
                self.http.clear_cookies()
            cookies = solved.cookies
            if only_cloudflare:
                cookies = [c for c in cookies if is_cloudflare_cookie(c["name"])]
            self.http.adopt_cookies(cookies)
            self.http.set_user_agent(solved.user_agent)
            self.save()

    # ---------------------------------------------------------------- login

    def form_tokens(self) -> tuple[str, str]:
        """(ftaa, bfaa) that Codeforces forms expect, created on first use."""
        with self._lock:
            self.session.ftaa = self.session.ftaa or _token(18)
            self.session.bfaa = self.session.bfaa or BFAA
            return self.session.ftaa, self.session.bfaa

    def set_credentials(self, handle_or_email: str, password: str) -> None:
        """Store the credentials (password encrypted) for later logins."""
        with self._lock:
            self.session.handle_or_email = handle_or_email
            self.session.password = crypto.encrypt_password(handle_or_email, password)
            self._login_error = None
            self.save()

    def login(self) -> str:
        """Log in with the stored credentials, tier by tier; returns the handle."""
        with self._lock:
            session = self.session
            if not session.handle_or_email or not session.password:
                raise CFError("Not logged in: run cf login")
            password = crypto.decrypt_password(session.handle_or_email, session.password)
            ui.cyan(f"Logging in as {session.handle_or_email}...")
            try:
                with ui.status("Logging in over HTTP..."):
                    handle = self._login_http(password)
            except LoginRejected:
                raise
            except CFError as e:
                # NOTE: a check in front of the login page is the usual reason, and
                # \     the browser gets past it: no warning for that
                if not isinstance(e, CloudflareChallengeError):
                    ui.yellow(f"HTTP login is not possible right now ({e}); using a browser.")
                handle = self._in_browser(
                    "Login", lambda headless: self._login_browser(password, headless)
                )
            session.handle = handle
            self.form_tokens()
            self._login_count += 1
            self.save()
            ui.green(f"Logged in as {handle}")
            return handle

    def _relogin(self, seen: int) -> None:
        with self._lock:
            if self._login_count != seen:
                return  # another thread logged in while this one waited
            if self._login_error is not None:
                raise self._login_error
            ui.cyan("The saved login has expired")
            try:
                self.login()
            except CFError as e:
                self._login_error = e
                raise

    def _login_http(self, password: str) -> str:
        session = self.session
        # NOTE: a fresh login, but Cloudflare's cookies stay: without a valid
        # \     cf_clearance /enter is challenged
        self.http.clear_cookies(keep=is_cloudflare_cookie)
        body = self.http.get(f"{self.host}/enter").text
        if pages.has_turnstile(body) or pages.is_browser_check(body):
            raise CloudflareChallengeError("the login page wants a browser check")
        csrf = pages.find_csrf(body)
        ftaa = _token(18)
        body = self.http.post(
            f"{self.host}/enter",
            data={
                "csrf_token": csrf,
                "action": "enter",
                "ftaa": ftaa,
                "bfaa": BFAA,
                "handleOrEmail": session.handle_or_email,
                "password": password,
                "_tta": "176",
                "remember": "on",
            },
        ).text
        handle = pages.find_handle(body)
        if handle:
            session.ftaa, session.bfaa = ftaa, BFAA
            return handle
        error = pages.find_error_message(body)
        if error and not pages.is_captcha_error(error):
            raise LoginRejected(error)
        raise CFError(error or "Codeforces did not accept the login")

    def _login_browser(self, password: str, headless: bool) -> str:
        solved = browser.login(
            self.host,
            self.session.handle_or_email,
            password,
            headless=headless,
            proxy=self.proxy,
        )
        self._adopt(solved, replace=True)
        try:
            handle = pages.find_handle(self.http.get(self.host).text)
        except CloudflareChallengeError:
            handle = None
        if handle:
            return handle
        if pages.find_handle(solved.html):
            raise CFError(
                "logged in inside the browser, but Codeforces refused the "
                "exported cookies over HTTP"
            )
        raise CFError("the browser session is not logged in")


def host_domain(host: str) -> str:
    """Hostname of the configured host URL, e.g. "codeforces.com"."""
    return urlparse(host).hostname or ""
