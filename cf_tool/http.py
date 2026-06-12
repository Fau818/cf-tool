"""HTTP transport: curl_cffi with Chrome TLS impersonation.

The real-browser TLS/HTTP2 fingerprint usually avoids Cloudflare challenges
outright; when one does appear we raise CloudflareChallengeError and the
client falls back to a browser (browser.py) to mint fresh clearance cookies.
"""

from __future__ import annotations

import time

from curl_cffi import requests as curl_requests

from cf_tool.errors import CFError, CloudflareChallengeError

IMPERSONATE = "chrome"
TIMEOUT = 30
RETRIES = 3


def is_challenge(response) -> bool:
    if response.status_code not in (403, 503):
        return False
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    text = response.text
    return "Just a moment" in text or "cf-chl" in text or "challenge-platform" in text


class Transport:
    def __init__(
        self,
        proxy: str = "",
        user_agent: str = "",
        cookies: dict[str, str] | None = None,
        domain: str = "",
    ) -> None:
        # cookies must carry the host domain: curl_cffi does not send
        # domain-less jar entries at all
        self._domain = domain
        self._session = curl_requests.Session(impersonate=IMPERSONATE, timeout=TIMEOUT)
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}
        if user_agent:
            self._session.headers["User-Agent"] = user_agent
        self.set_cookies(cookies or {})

    @property
    def cookies(self) -> dict[str, str]:
        return dict(self._session.cookies)

    def set_cookies(self, cookies: dict[str, str], replace: bool = False) -> None:
        if replace:
            self._session.cookies.clear()
        for name, value in cookies.items():
            if self._domain:
                self._session.cookies.set(name, value, domain=self._domain)
            else:
                self._session.cookies.set(name, value)

    def set_user_agent(self, user_agent: str) -> None:
        if user_agent:
            self._session.headers["User-Agent"] = user_agent

    def _request(self, method: str, url: str, **kwargs):
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            try:
                response = self._session.request(method, url, allow_redirects=True, **kwargs)
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

    def post(self, url: str, data: dict | None = None, **kwargs):
        return self._request("POST", url, data=data, **kwargs)

    def get_json(self, url: str) -> dict:
        response = self.get(url)
        try:
            return response.json()
        except Exception as e:
            raise CFError(f"Invalid JSON from {url}: {e}") from e
