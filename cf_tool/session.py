"""Persisted login state ($XDG_STATE_HOME/cf/session): handle, encrypted
credentials, cookies with the User-Agent they were issued to, and the last
submission (for `cf sid`).

Three on-disk formats are read, so no upgrade logs anybody out:
  - current: "cookies" is a list of cookie dicts (see http.py)
  - cf-tool 0.2 (Python): "cookies" is a flat {name: value} dict
  - the Go tool: "cookies" is its cookie jar {eTLD+1: {key: entry}}, and
    last_submission carries an extra "RootPath". The password encryption is
    byte-compatible, so a Go tool's stored login carries straight over.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cf_tool import ui
from cf_tool.config import write_atomic
from cf_tool.http import CookieDict

INFO_KEYS = ("problem_type", "contest_id", "group_id", "problem_id", "submission_id")


@dataclass
class Session:
    path: Path
    handle: str = ""
    handle_or_email: str = ""
    password: str = ""  # encrypted, see crypto.py
    ftaa: str = ""
    bfaa: str = ""
    user_agent: str = ""
    cookies: list[CookieDict] = field(default_factory=list)
    last_submission: dict[str, str] | None = None

    @classmethod
    def load(cls, path: Path, domain: str) -> "Session":
        """Session stored at path; an empty one if missing or unreadable.
        domain (e.g. "codeforces.com") is given to old flat-format cookies."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError) as e:
            ui.yellow(f"Ignoring unreadable session {path} ({e}); you may have to login again")
            return cls(path)
        if not isinstance(data, dict):
            ui.yellow(f"Ignoring malformed session {path}; you may have to login again")
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
            cookies=_read_cookies(data.get("cookies"), domain),
            last_submission=(
                {key: _text(last.get(key)) for key in INFO_KEYS} if isinstance(last, dict) else None
            ),
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
        write_atomic(self.path, json.dumps(data, indent=2) + "\n", mode=0o600)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _read_cookies(raw: Any, domain: str) -> list[CookieDict]:
    if isinstance(raw, list):
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
    if not isinstance(raw, dict):
        return []
    if raw and all(isinstance(v, dict) for v in raw.values()):
        return _from_go_jar(raw)
    return [
        {"name": k, "value": v, "domain": domain, "path": "/", "secure": False, "expires": None}
        for k, v in raw.items()
        if isinstance(v, str)
    ]


def _from_go_jar(jar: dict[str, Any]) -> list[CookieDict]:
    cookies = []
    for entries in jar.values():
        for entry in entries.values():
            if not isinstance(entry, dict) or not _text(entry.get("Name")):
                continue
            domain = _text(entry.get("Domain")).lstrip(".")
            if not domain:
                continue
            cookies.append(
                {
                    "name": entry["Name"],
                    "value": _text(entry.get("Value")),
                    # Go files a domain cookie without the dot, flagged HostOnly=false
                    "domain": domain if entry.get("HostOnly") else "." + domain,
                    "path": _text(entry.get("Path")) or "/",
                    "secure": bool(entry.get("Secure")),
                    "expires": (
                        _go_time(_text(entry.get("Expires"))) if entry.get("Persistent") else None
                    ),
                }
            )
    return cookies


def _go_time(text: str) -> int | None:
    """Epoch seconds of a Go RFC 3339 timestamp (nanoseconds are cut to µs)."""
    match = re.fullmatch(r"(.+?:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})", text)
    if not match:
        return None
    head, fraction, zone = match.groups()
    # exactly six digits: Python 3.10's fromisoformat takes no other length
    micros = (fraction[1:] + "000000")[:6] if fraction else "000000"
    try:
        moment = datetime.fromisoformat(f"{head}.{micros}" + ("+00:00" if zone == "Z" else zone))
    except ValueError:
        return None
    return int(moment.timestamp())
