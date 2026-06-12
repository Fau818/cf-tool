"""Config management at ~/.cf/config, mirroring xalanq/cf-tool's config package.

The JSON schema (keys, defaults) is kept identical to the Go tool so behavior
documented in its README applies here unchanged.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROBLEM_TYPES = ("contest", "gym", "group", "acmsguru")

CF_DIR = Path.home() / ".cf"
CONFIG_PATH = CF_DIR / "config"
SESSION_PATH = CF_DIR / "session"

DEFAULT_HOST = "https://codeforces.com"


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
    def from_dict(cls, data: dict) -> "CodeTemplate":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Config:
    template: list[CodeTemplate] = field(default_factory=list)
    default: int = 0  # index into template
    gen_after_parse: bool = False
    host: str = DEFAULT_HOST
    proxy: str = ""
    folder_name: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._path = CONFIG_PATH
        self._normalize()

    def _normalize(self) -> None:
        if not 0 <= self.default < max(len(self.template), 1):
            self.default = 0
        self.folder_name.setdefault("root", "cf")
        for problem_type in PROBLEM_TYPES:
            self.folder_name.setdefault(problem_type, problem_type)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        cfg = cls(
            template=[CodeTemplate.from_dict(t) for t in data.get("template", [])],
            default=data.get("default", 0),
            gen_after_parse=data.get("gen_after_parse", False),
            host=data.get("host", DEFAULT_HOST),
            proxy=data.get("proxy", ""),
            folder_name=dict(data.get("folder_name", {})),
        )
        cfg._path = Path(path)
        return cfg

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def templates_by_alias(self, alias: str) -> list[CodeTemplate]:
        return [t for t in self.template if t.alias == alias]

    @property
    def default_template(self) -> CodeTemplate | None:
        if not self.template:
            return None
        return self.template[self.default]
