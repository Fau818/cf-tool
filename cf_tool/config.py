"""Config management, mirroring xalanq/cf-tool's config package.

The JSON schema (keys, defaults) is kept identical to the Go tool so behavior
documented in its README applies here unchanged. Locations follow XDG instead
of the Go tool's ~/.cf: config in $XDG_CONFIG_HOME/cf, the session (cookies,
encrypted credentials) in $XDG_STATE_HOME/cf. On first run a Go tool's ~/.cf
is imported (copied, never moved: an installed Go cf keeps working).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cf_tool.errors import CFError

PROBLEM_TYPES = ("contest", "gym", "group", "acmsguru")
DEFAULT_HOST = "https://codeforces.com"
NO_TEMPLATE = "You have to add at least one code template by `cf config`"


def _xdg(env_var: str, default: Path) -> Path:
    value = os.environ.get(env_var, "")
    return Path(value).expanduser() if value else default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "cf"
STATE_DIR = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "cf"
CONFIG_PATH = CONFIG_DIR / "config"
SESSION_PATH = STATE_DIR / "session"
LEGACY_DIR = Path.home() / ".cf"


def write_atomic(path: Path, text: str, mode: int = 0o644) -> None:
    """Replace path with text in one step, created with the given permissions
    (a Ctrl-C mid-write never leaves a truncated file behind)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def import_legacy_dir() -> list[str]:
    """Copy config and session from the Go tool's ~/.cf where the XDG files
    don't exist yet. Returns human-readable notes for what was copied."""
    if not LEGACY_DIR.is_dir():
        return []
    notes = []
    for name, target, mode in (("config", CONFIG_PATH, 0o644), ("session", SESSION_PATH, 0o600)):
        source = LEGACY_DIR / name
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, mode)
            notes.append(f"copied {source} -> {target}")
    return notes


@dataclass
class CodeTemplate:
    """One code template. Scripts run in sequence on `cf test`:
    before_script once, script per sample, after_script once."""

    alias: str = ""
    lang: str = ""  # Codeforces programTypeId, e.g. "54"
    path: str = ""  # template source file
    suffix: list[str] = field(default_factory=list)  # file extensions, e.g. ["cpp", "cc"]
    before_script: str = ""
    script: str = ""
    after_script: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeTemplate":
        known = set(cls.__dataclass_fields__)
        values = {k: v for k, v in data.items() if k in known}
        if isinstance(values.get("suffix"), str):  # hand-edited "cpp" instead of ["cpp"]
            values["suffix"] = values["suffix"].split()
        return cls(**values)


@dataclass
class Config:
    template: list[CodeTemplate] = field(default_factory=list)
    default: int = 0  # index into template
    gen_after_parse: bool = False
    host: str = DEFAULT_HOST
    proxy: str = ""
    folder_name: dict[str, str] = field(default_factory=dict)
    _path: Path = field(default_factory=lambda: CONFIG_PATH, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._normalize()

    def _normalize(self) -> None:
        if not 0 <= self.default < max(len(self.template), 1):
            self.default = 0
        self.folder_name.setdefault("root", "cf")
        for problem_type in PROBLEM_TYPES:
            self.folder_name.setdefault(problem_type, problem_type)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Read the config; a missing file gives the defaults, a broken one
        is an error (rather than silently replacing the user's templates)."""
        path = Path(path or CONFIG_PATH)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(_path=path)
        except OSError as e:
            raise CFError(f"Cannot read config {path}: {e}") from e
        try:
            data = json.loads(text) if text.strip() else {}
            return cls(
                template=[CodeTemplate.from_dict(t) for t in data.get("template") or []],
                default=int(data.get("default", 0)),
                gen_after_parse=bool(data.get("gen_after_parse", False)),
                host=data.get("host") or DEFAULT_HOST,
                proxy=data.get("proxy") or "",
                folder_name=dict(data.get("folder_name") or {}),
                _path=path,
            )
        except (ValueError, TypeError, AttributeError) as e:
            raise CFError(f"Config {path} is broken ({e}). Fix or delete it.") from e

    def save(self) -> None:
        self._normalize()
        data = {
            "template": [asdict(t) for t in self.template],
            "default": self.default,
            "gen_after_parse": self.gen_after_parse,
            "host": self.host,
            "proxy": self.proxy,
            "folder_name": self.folder_name,
        }
        write_atomic(self._path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def templates_by_alias(self, alias: str) -> list[CodeTemplate]:
        return [t for t in self.template if t.alias == alias]

    def default_template(self) -> CodeTemplate:
        """The default template; CFError when there is none yet."""
        if not self.template:
            raise CFError(NO_TEMPLATE)
        return self.template[self.default]
