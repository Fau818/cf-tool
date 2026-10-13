"""Exception types shared across cf-tool modules.

The login tiers (gateway.py) escalate on CFError, but stop at once on
LoginRejected (Codeforces said no — another tier would only repeat it) and on
BrowserUnavailable (no Chrome — a window would fail the same way).
"""


class CFError(Exception):
    """Base error: message is shown to the user in red, without a traceback."""


class NotLoggedInError(CFError):
    """Raised when Codeforces reports the session is not authenticated."""

    def __init__(self, message: str = "Not logged in. Please run `cf config` to login") -> None:
        super().__init__(message)


class CloudflareChallengeError(CFError):
    """Raised when a response is a Cloudflare/Turnstile check instead of real content."""

    def __init__(self, message: str = "Blocked by a Cloudflare challenge") -> None:
        super().__init__(message)


class LoginRejected(CFError):
    """Codeforces itself rejected the login (e.g. wrong handle or password)."""


class BrowserError(CFError):
    """The browser fallback failed while driving a page."""


class BrowserUnavailable(BrowserError):
    """Chrome/Chromium could not be started at all."""
