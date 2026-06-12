"""Exception types shared across cf-tool modules."""


class CFError(Exception):
    """Base error: message is shown to the user in red, without a traceback."""


class NotLoggedInError(CFError):
    """Raised when Codeforces reports the session is not authenticated."""

    def __init__(self, message: str = "Not logged in. Please run `cf config` to login") -> None:
        super().__init__(message)


class CloudflareChallengeError(CFError):
    """Raised when a response is a Cloudflare challenge page instead of real content."""

    def __init__(self, message: str = "Blocked by a Cloudflare challenge") -> None:
        super().__init__(message)
