"""Where cf-tool keeps its files, and writing them safely.

The folders follow the XDG base directories:
- settings: $XDG_CONFIG_HOME/cf (config.toml, your starter code in templates/)
- state: $XDG_STATE_HOME/cf (the login session, caches of what Codeforces said)
- cache: $XDG_CACHE_HOME/cf (builds, cf-tool's bits/stdc++.h)

Read them as paths.CONFIG_DIR and so on at call time (tests point them elsewhere).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def _xdg(env_var: str, default: Path) -> Path:
    value = os.environ.get(env_var, "")
    return Path(value).expanduser() if value else default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "cf"
STATE_DIR = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "cf"
CACHE_DIR = _xdg("XDG_CACHE_HOME", Path.home() / ".cache") / "cf"


def config_file() -> Path:
    return CONFIG_DIR / "config.toml"


def templates_dir() -> Path:
    """Where your own starter code lives: template.cpp, brute.cpp, gen.py, ..."""
    return CONFIG_DIR / "templates"


def session_file() -> Path:
    return STATE_DIR / "session"


def write_atomic(path: Path, text: str, mode: int = 0o644) -> None:
    """Replace path with text in one step, created with the given permissions
    (a Ctrl-C mid-write never leaves a truncated file behind)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
