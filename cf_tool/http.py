"""HTTP transport: curl_cffi with Chrome TLS impersonation.

A Cloudflare interstitial (or Codeforces' own Turnstile gate) is raised as
CloudflareChallengeError; gateway.py then decides whether a browser may help.

Cookies travel as plain dicts so they can be persisted and handed over from
the browser without losing their domain/path/expiry:
    {"name", "value", "domain", "path", "secure", "expires"}  # expires: epoch or None
"""

from __future__ import annotations

import time
from http.cookiejar import Cookie
from typing import Any, Callable

from curl_cffi import requests as curl_requests

from cf_tool import pages
from cf_tool.errors import CFError, CloudflareChallengeError

IMPERSONATE = "chrome"
TIMEOUT = 30
RETRIES = 3

CookieDict = dict[str, Any]


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
        self.user_agent = ""
        self.set_user_agent(user_agent)
        self.load_cookies(cookies or [])

    # -------------------------------------------------------------- cookies

    def export_cookies(self) -> list[CookieDict]:
        """Every cookie in the jar, in the persistable dict form."""
        return [
            {
                "name": c.name,
                "value": c.value or "",
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "expires": c.expires,
            }
            for c in self._session.cookies.jar
        ]

    def load_cookies(self, cookies: list[CookieDict]) -> None:
        """Add cookies to the jar; already-expired ones are dropped."""
        now = time.time()
        for c in cookies:
            if c.get("expires") is not None and c["expires"] <= now:
                continue
            self._session.cookies.jar.set_cookie(_to_jar_cookie(c))

    def adopt_cookies(self, cookies: list[CookieDict]) -> None:
        """Merge cookies from elsewhere (the browser): each name replaces every
        cookie of that name, whatever domain it was filed under."""
        for name in {c["name"] for c in cookies}:
            self._session.cookies.delete(name)
        self.load_cookies(cookies)

    def clear_cookies(self, keep: Callable[[str], bool] | None = None) -> None:
        """Drop cookies, except those whose name satisfies keep."""
        jar = self._session.cookies.jar
        for c in list(jar):
            if keep is None or not keep(c.name):
                jar.clear(c.domain, c.path, c.name)

    def set_user_agent(self, user_agent: str) -> None:
        if user_agent:
            self.user_agent = user_agent
            self._session.headers["User-Agent"] = user_agent

    # ------------------------------------------------------------- requests

    def _request(self, method: str, url: str, **kwargs):
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            try:
                response = self._session.request(
                    method, url, allow_redirects=True, **kwargs  # type: ignore[arg-type]
                )
            except curl_requests.exceptions.RequestException as e:
                last_error = e
                if attempt < RETRIES - 1:
                    time.sleep(2**attempt)
                continue
            if is_challenge(response):
                raise CloudflareChallengeError()
            return response
        raise CFError(f"Request failed after {RETRIES} attempts: {last_error}")

    def get(self, url: str, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url: str, data: dict[str, str] | None = None, **kwargs):
        return self._request("POST", url, data=data, **kwargs)

    def get_json(self, url: str) -> dict[str, Any]:
        response = self.get(url)
        try:
            return response.json()
        except Exception as e:
            raise CFError(f"Invalid JSON from {url}: {e}") from e
