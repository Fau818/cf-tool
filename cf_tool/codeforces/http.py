"""HTTP transport: curl_cffi with Chrome TLS impersonation.

A Cloudflare interstitial (or Codeforces' own Turnstile gate) is raised as
CloudflareChallengeError; gateway.py then decides whether a browser may help.
A server error (5xx) or "too many requests" (429) is never content: a GET is
tried again a little later, a POST never is (it may have arrived).

Requests run one at a time: curl_cffi copies the whole cookie jar into each
request and writes it all back afterwards, so overlapping requests would put
stale cookies back (a fresh login undone).

Cookies travel as plain dicts so they can be persisted and handed over from
the browser without losing their domain/path/expiry:
    {"name", "value", "domain", "path", "secure", "expires"}  # expires: epoch or None
"""

from __future__ import annotations

import threading
import time
from http.cookiejar import Cookie
from typing import Any, Callable
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

from cf_tool.codeforces import pages
from cf_tool.errors import CFError, CloudflareChallengeError

IMPERSONATE = "chrome"
TIMEOUT = 30
RETRIES = 3
BACKOFF = 2.0  # seconds before the first retry, doubled for each next one

CookieDict = dict[str, Any]


class ServerError(CFError):
    """Codeforces answered with an error page (5xx or 429), not content."""

    def __init__(self, status: int) -> None:
        reason = "too many requests" if status == 429 else "a server error"
        super().__init__(f"Codeforces is answering with {reason} ({status}); try again soon")
        self.status = status


class Uncertain(CFError):
    """A POST got no answer: it may or may not have reached Codeforces."""


def is_challenge(response) -> bool:
    """True when the response is a check page instead of the content."""
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    text = response.text
    if response.status_code in (403, 503) and pages.is_cloudflare_challenge(text):
        return True
    # Codeforces' own Turnstile gate is served with 200
    return pages.is_verification_gate(text)


def is_cloudflare_cookie(name: str) -> bool:
    """cf_clearance, __cf_bm, _cfuvid, ...: Cloudflare's, not Codeforces' login."""
    return name.startswith(("cf_", "__cf", "_cf"))


def _to_jar_cookie(c: CookieDict) -> Cookie:
    domain = c["domain"]
    return Cookie(
        version=0,
        name=c["name"],
        value=c["value"],
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=domain.startswith("."),
        domain_initial_dot=domain.startswith("."),
        path=c.get("path") or "/",
        path_specified=True,
        secure=bool(c.get("secure")),
        expires=c.get("expires"),
        discard=c.get("expires") is None,
        comment=None,
        comment_url=None,
        rest={},
    )


class Transport:
    def __init__(
        self,
        proxy: str = "",
        user_agent: str = "",
        cookies: list[CookieDict] | None = None,
    ) -> None:
        self._session = curl_requests.Session(impersonate=IMPERSONATE, timeout=TIMEOUT)
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}
        self._lock = threading.RLock()  # NOTE: one request (or cookie change) at a time
        self.user_agent = ""
        self.set_user_agent(user_agent)
        self.load_cookies(cookies or [])

    # -------------------------------------------------------------- cookies

    def export_cookies(self) -> list[CookieDict]:
        """Every cookie in the jar, in the persistable dict form."""
        with self._lock:
            return [
                {
                    "name": c.name,
                    "value": c.value or "",
                    "domain": c.domain,
                    "path": c.path,
                    "secure": c.secure,
                    "expires": c.expires,
                }
                for c in list(self._session.cookies.jar)
            ]

    def load_cookies(self, cookies: list[CookieDict]) -> None:
        """Add cookies to the jar; already-expired ones are dropped."""
        now = time.time()
        with self._lock:
            for c in cookies:
                if c.get("expires") is not None and c["expires"] <= now:
                    continue
                self._session.cookies.jar.set_cookie(_to_jar_cookie(c))

    def adopt_cookies(self, cookies: list[CookieDict]) -> None:
        """Merge cookies from elsewhere (the browser): each name replaces every
        cookie of that name, whatever domain it was filed under."""
        with self._lock:
            for name in {c["name"] for c in cookies}:
                self._session.cookies.delete(name)
            self.load_cookies(cookies)

    def clear_cookies(self, keep: Callable[[str], bool] | None = None) -> None:
        """Drop cookies, except those whose name satisfies keep."""
        with self._lock:
            jar = self._session.cookies.jar
            for c in list(jar):
                if keep is None or not keep(c.name):
                    jar.clear(c.domain, c.path, c.name)

    def has_cookie(self, name: str) -> bool:
        with self._lock:
            return any(c.name == name for c in list(self._session.cookies.jar))

    def set_user_agent(self, user_agent: str) -> None:
        if user_agent:
            with self._lock:
                self.user_agent = user_agent
                self._session.headers["User-Agent"] = user_agent

    # ------------------------------------------------------------- requests

    def _send(self, method: str, url: str, **kwargs):
        with self._lock:
            response = self._session.request(
                method, url, allow_redirects=True, **kwargs  # type: ignore[arg-type]
            )
        if is_challenge(response):
            challenge = CloudflareChallengeError()
            # NOTE: checked on a page redirected to: the request itself got through
            final = getattr(response, "url", "") or url
            moved = urlparse(final).path != urlparse(url).path
            challenge.redirected = moved  # type: ignore[attr-defined]
            raise challenge
        if response.status_code >= 500 or response.status_code == 429:
            raise ServerError(response.status_code)
        return response

    def get(self, url: str, **kwargs):
        """GET url, tried again (after a growing pause) when the connection
        fails or Codeforces answers with a server error."""
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            if attempt:
                time.sleep(BACKOFF * 2 ** (attempt - 1))
            try:
                return self._send("GET", url, **kwargs)
            except (curl_requests.exceptions.RequestException, ServerError) as e:
                last_error = e
        if isinstance(last_error, ServerError):
            raise last_error
        raise CFError(f"Cannot reach Codeforces ({_first_line(last_error)})")

    def post(self, url: str, data: dict[str, str] | None = None, **kwargs):
        """POST a form, once: raises Uncertain when the answer was lost, since
        the form may have arrived (a submission must not be sent twice)."""
        try:
            return self._send("POST", url, data=data, **kwargs)
        except curl_requests.exceptions.RequestException as e:
            raise Uncertain(f"No answer from Codeforces ({_first_line(e)})") from e
        except ServerError as e:
            raise Uncertain(str(e)) from e
        except CloudflareChallengeError as e:
            if getattr(e, "redirected", False):
                raise Uncertain("Cloudflare checked the page shown after the form") from e
            raise  # NOTE: stopped before Codeforces: safe to send again once passed

    def get_json(self, url: str) -> dict[str, Any]:
        response = self.get(url)
        try:
            return response.json()
        except Exception as e:
            raise CFError(f"Invalid JSON from {url}: {e}") from e


def _first_line(error: Exception | None) -> str:
    text = str(error or "").strip()
    return text.splitlines()[0] if text else type(error).__name__
