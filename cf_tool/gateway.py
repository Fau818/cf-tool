"""The way in to Codeforces: plain HTTP first, a browser only when Cloudflare
insists, and the tiered login.

Login tiers (first that works wins):
  1. HTTP — the Go tool's GET+POST /enter over curl_cffi. Needs no browser,
     but Cloudflare challenges /enter unless a cf_clearance is still valid.
  2. headless browser — passes the checks without showing anything.
  3. browser window — last resort, for when a human has to tick a box.
A credentials error (LoginRejected) stops at once, and so does a missing
Chrome (BrowserUnavailable): another tier would only fail the same way.

Pages are fetched the same way round: HTTP, and only on a challenge a
headless browser, then a window. Fetches may come from several threads
(parse, clone); browser work, logins and session saves are serialized by
one lock, and a login or challenge solved by one thread is reused by the
others instead of being repeated.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar
from urllib.parse import urlparse

from cf_tool import browser, crypto, pages, templates, ui
from cf_tool.config import Config
from cf_tool.errors import (
    BrowserUnavailable,
    CFError,
    CloudflareChallengeError,
    LoginRejected,
)
from cf_tool.http import Transport, is_cloudflare_cookie
from cf_tool.session import Session

T = TypeVar("T")

BFAA = "f1b3f18c715565b589b7823cda7448ce"


class Gateway:
    def __init__(self, cfg: Config, session: Session) -> None:
        self.cfg = cfg
        self.session = session
        self.http = Transport(
            proxy=cfg.proxy, user_agent=session.user_agent, cookies=session.cookies
        )
        self._lock = threading.RLock()
        # bumped by each successful login / challenge solve, so a thread that
        # waited on the lock can tell the work was done meanwhile
        self._login_count = 0
        self._solve_count = 0
        # a failure is remembered: other threads must not retry (and pop
        # more windows); a fresh `cf` run tries again
        self._login_error: CFError | None = None
        self._solve_error: CFError | None = None

    @property
    def host(self) -> str:
        return self.cfg.host

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
                    lambda headless: browser.fetch(url, headless=headless, proxy=self.cfg.proxy),
                )
            except CFError as e:
                self._solve_error = e
                raise
            # merge, not replace: the browser profile is fresh, and dropping
            # our login cookies here would log the user out
            self._adopt(solved, replace=False)
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

    def _adopt(self, solved: browser.BrowserSession, replace: bool) -> None:
        with self._lock:
            if replace:
                self.http.clear_cookies()
            self.http.adopt_cookies(solved.cookies)
            self.http.set_user_agent(solved.user_agent)
            self.save()

    # ---------------------------------------------------------------- login

    def form_tokens(self) -> tuple[str, str]:
        """(ftaa, bfaa) that Codeforces forms expect, created on first use."""
        with self._lock:
            self.session.ftaa = self.session.ftaa or templates.rand_string(18)
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
                raise CFError("You have to configure your handle and password by `cf config`")
            password = crypto.decrypt_password(session.handle_or_email, session.password)
            ui.cyan(f"Login {session.handle_or_email}...")
            try:
                with ui.status("Logging in over HTTP..."):
                    handle = self._login_http(password)
            except LoginRejected:
                raise
            except CFError as e:
                reason = str(e)
                if isinstance(e, CloudflareChallengeError):
                    reason = "Cloudflare guards the login page"
                ui.yellow(f"HTTP login is not possible right now ({reason}); using a browser.")
                handle = self._in_browser(
                    "Login", lambda headless: self._login_browser(password, headless)
                )
            session.handle = handle
            self.form_tokens()
            self._login_count += 1
            self.save()
            ui.green("Succeed!!")
            ui.green(f"Welcome {handle}~")
            return handle

    def _relogin(self, seen: int) -> None:
        with self._lock:
            if self._login_count != seen:
                return  # another thread logged in while this one waited
            if self._login_error is not None:
                raise self._login_error
            ui.red("Not logged. Try to login")
            try:
                self.login()
            except CFError as e:
                self._login_error = e
                raise

    def _login_http(self, password: str) -> str:
        session = self.session
        # a fresh login, like the Go tool's new cookie jar, but Cloudflare's
        # cookies stay: without a valid cf_clearance /enter is challenged
        self.http.clear_cookies(keep=is_cloudflare_cookie)
        body = self.http.get(f"{self.host}/enter").text
        if pages.has_turnstile(body):
            raise CFError("the login form wants a Turnstile check")
        csrf = pages.find_csrf(body)
        ftaa = templates.rand_string(18)
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
            proxy=self.cfg.proxy,
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
