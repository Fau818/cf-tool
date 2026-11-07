"""The login session ($XDG_STATE_HOME/cf/session, mode 0600): the handle, the
credentials (the password scrambled, see crypto.py), the cookies with the
User-Agent they were issued to, and the last submission (for cf open --last).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cf_tool import paths, ui
from cf_tool.codeforces.http import CookieDict

# what a submission is remembered by, for cf open --last
LAST_KEYS = ("kind", "contest", "problem", "group", "submission")


@dataclass
class Session:
    path: Path
    handle: str = ""
    handle_or_email: str = ""
    password: str = ""  # scrambled, see crypto.py
    ftaa: str = ""
    bfaa: str = ""
    user_agent: str = ""
    cookies: list[CookieDict] = field(default_factory=list)
    last_submission: dict[str, str] | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "Session":
        """The session stored at path; an empty one if missing or unreadable."""
        path = path or paths.session_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError) as e:
            ui.yellow(f"Ignoring the unreadable session {path} ({e}): run cf login again")
            return cls(path)
        if not isinstance(data, dict):
            ui.yellow(f"Ignoring the malformed session {path}: run cf login again")
            return cls(path)
        last = data.get("last_submission")
        return cls(
            path=path,
            handle=_text(data.get("handle")),
            handle_or_email=_text(data.get("handle_or_email")),
            password=_text(data.get("password")),
            ftaa=_text(data.get("ftaa")),
            bfaa=_text(data.get("bfaa")),
            user_agent=_text(data.get("user_agent")),
            cookies=_read_cookies(data.get("cookies")),
            last_submission=_read_last(last) if isinstance(last, dict) else None,
        )

    def save(self) -> None:
        data = {
            "handle": self.handle,
            "handle_or_email": self.handle_or_email,
            "password": self.password,
            "ftaa": self.ftaa,
            "bfaa": self.bfaa,
            "user_agent": self.user_agent,
            "cookies": self.cookies,
            "last_submission": self.last_submission,
        }
        paths.write_atomic(self.path, json.dumps(data, indent=2) + "\n", mode=0o600)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _read_cookies(raw: Any) -> list[CookieDict]:
    if not isinstance(raw, list):
        return []
    return [
        {
            "name": c["name"],
            "value": _text(c.get("value")),
            "domain": c["domain"],
            "path": _text(c.get("path")) or "/",
            "secure": bool(c.get("secure")),
            "expires": c.get("expires") if isinstance(c.get("expires"), (int, float)) else None,
        }
        for c in raw
        if isinstance(c, dict) and _text(c.get("name")) and _text(c.get("domain"))
    ]


def _read_last(last: dict) -> dict[str, str]:
    """The last submission, also as cf-tool 0.3 saved it (problem_type, contest_id, ...)."""
    old = {
        "kind": "problem_type",
        "contest": "contest_id",
        "problem": "problem_id",
        "group": "group_id",
        "submission": "submission_id",
    }
    return {key: _text(last.get(key, last.get(old[key]))) for key in LAST_KEYS}
