"""Settings: config.toml, where every key is optional.

    language = "cpp"            # what cf get writes starter code in
    root = "~/codeforces"       # where cf get puts contests
    host = "https://codeforces.com"
    proxy = "socks5://127.0.0.1:1080"

    [cpp]                       # one table per language, by file extension
    compiler = "g++-15"
    flags = "-DLOCAL"
    submit = "G++20"            # part of a Codeforces language's name, or its id
    template = "~/cp/template.cpp"
    build = "g++ {src} -o {exe}"
    run = "{exe}"

tomlkit reads and writes it, so the user's comments and layout survive the
changes cf-tool makes (the language picked on the first cf get). The JSON
config of cf-tool 0.3 (the Go tool's schema) is turned into one on the first
run, see migrate().
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from cf_tool import paths
from cf_tool.errors import CFError
from cf_tool.process import split_command

DEFAULT_HOST = "https://codeforces.com"
TOP_KEYS = ("language", "root", "host", "proxy")
LANGUAGE_KEYS = ("compiler", "flags", "submit", "template", "build", "run")

DEFAULT_TEXT = """\
# cf-tool settings. Every line is optional: delete one to get its default back.

# The language `cf get` writes starter code in: cpp, c, py, java, kt, rs or go.
language = "{language}"

# Where `cf get` puts contests (default: the folder you run it in).
# root = "~/codeforces"

# host = "https://codeforces.com"
# The proxy for Codeforces (default: the environment's HTTPS_PROXY / ALL_PROXY).
# proxy = "socks5://127.0.0.1:1080"

# One table per language, named by its file extension; every key is optional.
# [cpp]
# compiler = "g++-15"             # default: the best one found here, GCC first
# flags = "-DLOCAL"               # added after the default flags
# submit = "G++20"                # part of a Codeforces language's name, or its id
#                                 # (cf langs --all lists them); default: the newest
# template = "~/cp/template.cpp"  # starter code for new problems
# build = "g++ -std=c++20 -O2 {{src}} -o {{exe}}"   # replaces the whole build command
# run = "{{exe}}"                   # replaces the run command
"""


@dataclass(frozen=True)
class LanguageSettings:
    """One language's table in config.toml; empty values mean the default."""

    compiler: str = ""
    flags: tuple[str, ...] = ()
    submit: str = ""
    template: str = ""
    build: tuple[str, ...] | None = None  # None: the built-in command; (): nothing to build
    run: tuple[str, ...] | None = None


@dataclass
class Settings:
    language: str = ""  # "" until picked
    root: str = ""
    host: str = DEFAULT_HOST
    proxy: str = ""
    languages: dict[str, LanguageSettings] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)  # unknown keys, worth telling the user
    path: Path | None = None  # where they are saved (None: paths.config_file())

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """The settings in config.toml; the defaults when it doesn't exist.
        Raises CFError for a file that isn't valid TOML or holds a wrong value."""
        path = path or paths.config_file()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path=path)
        except OSError as e:
            raise CFError(f"Cannot read {path}: {e.strerror or e}") from e
        try:
            data = tomlkit.parse(text).unwrap()
        except TOMLKitError as e:
            raise CFError(f"{path} isn't valid TOML: {e}") from e
        return _from_data(data, path)

    @property
    def file(self) -> Path:
        return self.path or paths.config_file()

    def language_settings(self, key: str) -> LanguageSettings:
        return self.languages.get(key, LanguageSettings())

    def root_folder(self) -> Path | None:
        """Where cf get puts contests, if set."""
        return Path(self.root).expanduser() if self.root else None

    def update(self, key: str, value: Any, table: str | None = None) -> None:
        """Set one setting (in a language's table when given) and save
        config.toml, keeping everything else in it as it was."""
        path = self.file
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        except OSError as e:
            raise CFError(f"Cannot read {path}: {e.strerror or e}") from e
        if not text:
            language = value if (key, table) == ("language", None) else self.language or "cpp"
            text = DEFAULT_TEXT.format(language=language)
        try:
            doc = tomlkit.parse(text)
        except TOMLKitError as e:
            raise CFError(f"{path} isn't valid TOML: {e}") from e
        if table is None:
            doc[key] = value
        else:
            if table not in doc:
                doc[table] = tomlkit.table()
            doc[table][key] = value  # type: ignore[index]
        new_text = tomlkit.dumps(doc)
        updated = _from_data(tomlkit.parse(new_text).unwrap(), path)
        paths.write_atomic(path, new_text)
        self.language, self.root, self.host, self.proxy = (
            updated.language,
            updated.root,
            updated.host,
            updated.proxy,
        )
        self.languages = updated.languages

    def write_default(self) -> Path:
        """Create config.toml with every setting explained, if it is missing;
        returns its path."""
        path = self.file
        if not path.exists():
            paths.write_atomic(path, DEFAULT_TEXT.format(language=self.language or "cpp"))
        return path


def _text(value: Any, where: str) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        raise CFError(f'{where} should be text, like "..."')
    return value


def _words(value: Any, where: str) -> tuple[str, ...]:
    """A command or flags: one string (split like a command line) or a list of words."""
    if isinstance(value, str):
        return tuple(split_command(value))
    if isinstance(value, list) and all(isinstance(word, str) for word in value):
        return tuple(value)
    raise CFError(f'{where} should be text, like "...", or a list of words')


def _from_data(data: dict[str, Any], path: Path) -> Settings:
    """Settings from parsed config.toml data. Raises CFError for a wrong
    value; unknown keys become warnings."""
    settings = Settings(path=path)
    name = path.name
    for key, value in data.items():
        where = f"{name}: {key}"
        if isinstance(value, dict):
            settings.languages[key.lower().lstrip(".")] = _language_from(
                value, f"{name}: [{key}]", settings
            )
        elif key == "language":
            settings.language = _text(value, where).strip().lower().lstrip(".")
        elif key == "root":
            settings.root = _text(value, where).strip()
        elif key == "host":
            host = _text(value, where).strip().rstrip("/")
            if not re.match(r"https?://[\w.-]+(:\d+)?$", host):
                raise CFError(f'{where} should be like "https://codeforces.com"')
            settings.host = host
        elif key == "proxy":
            settings.proxy = _text(value, where).strip()
        else:
            settings.warnings.append(f'{name}: unknown setting "{key}"')
    return settings


def _language_from(data: dict[str, Any], where: str, settings: Settings) -> LanguageSettings:
    values: dict[str, Any] = {}
    for key, value in data.items():
        place = f"{where} {key}"
        if key in ("compiler", "template"):
            values[key] = _text(value, place).strip()
        elif key == "submit":
            values[key] = _text(value, place).strip()
        elif key in ("flags", "build", "run"):
            values[key] = _words(value, place)
        else:
            settings.warnings.append(f'{where}: unknown setting "{key}"')
    return LanguageSettings(**values)


# ┌──────────────────────────────────────────────────────────┐
# │                   From cf-tool 0.3                       │
# └──────────────────────────────────────────────────────────┘


def old_config_files() -> list[Path]:
    """Where cf-tool 0.3 (and the Go tool) kept their JSON config."""
    return [paths.CONFIG_DIR / "config", Path.home() / ".cf" / "config"]


def migrate(sources: list[Path] | None = None, target: Path | None = None) -> list[str]:
    """Write config.toml from an old JSON config when there is no config.toml
    yet; returns what to tell the user ([] when there was nothing to do).
    Carried over: the default language, each language's starter file and
    Codeforces language, host and proxy; scripts only for languages cf-tool
    doesn't know (it builds the others itself now). The old file is left as
    it was."""
    from cf_tool import languages

    target = target or paths.config_file()
    if target.exists():
        return []
    source = next((p for p in (sources or old_config_files()) if p.is_file()), None)
    if source is None:
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8") or "{}")
        templates = [t for t in data.get("template") or [] if isinstance(t, dict)]
        default = int(data.get("default", 0))
    except (OSError, ValueError, TypeError, AttributeError) as e:
        return [f"Could not read your old settings in {source} ({e}); starting afresh."]

    def key_of(template: dict) -> str:
        suffixes = template.get("suffix") or []
        if isinstance(suffixes, str):
            suffixes = suffixes.split()
        for suffix in suffixes:
            if (key := languages.language_key(str(suffix))) is not None:
                return key
        name = languages.LANGS.get(str(template.get("lang", "")), "")
        ext = languages.ext_of(name) if name else "txt"
        if ext in languages.LANGUAGES:
            return ext
        first = str(suffixes[0]) if suffixes else ext
        return first.lower().lstrip(".")

    chosen: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []  # (alias, its language)
    default_key = key_of(templates[default]) if 0 <= default < len(templates) else ""
    for i, template in enumerate(templates):
        key = key_of(template)
        if key in chosen and i != default:
            skipped.append((str(template.get("alias", "?")), key))
            continue
        if key in chosen:
            skipped.append((str(chosen[key].get("alias", "?")), key))
        chosen[key] = template

    doc = tomlkit.parse(DEFAULT_TEXT.format(language=default_key or "cpp"))
    host = str(data.get("host") or "").rstrip("/")
    if host and host != DEFAULT_HOST:
        doc["host"] = host
    if data.get("proxy"):
        doc["proxy"] = str(data["proxy"])
    carried: list[str] = []
    dropped_scripts: list[str] = []
    for key, template in chosen.items():
        table = tomlkit.table()
        if template.get("path"):
            table["template"] = str(template["path"])
        if str(template.get("lang", "")).strip():
            table["submit"] = str(template["lang"]).strip()
        if key in languages.LANGUAGES:
            if template.get("before_script") or template.get("script"):
                dropped_scripts.append(str(template.get("alias", key)))
        else:
            if template.get("before_script"):
                table["build"] = _new_placeholders(str(template["before_script"]))
            if template.get("script"):
                table["run"] = _new_placeholders(str(template["script"]))
        if len(table):
            doc[key] = table
            shown = []
            for name, value in table.items():
                language = languages.LANGS.get(str(value)) if name == "submit" else None
                shown.append(f"{name} = {value}" + (f" ({language})" if language else ""))
            carried.append(f"[{key}] " + ", ".join(shown))
    paths.write_atomic(target, tomlkit.dumps(doc))

    notes = [f"Moved your settings from {source} to {target}:"]
    if default_key:
        notes.append(f'  language = "{default_key}"')
    notes += [f"  {line}" for line in carried]
    if host and host != DEFAULT_HOST:
        notes.append(f'  host = "{host}"')
    if data.get("proxy"):
        notes.append(f'  proxy = "{data["proxy"]}"')
    if dropped_scripts:
        notes.append(
            "Not carried over: the build and run scripts of "
            + ", ".join(f'"{alias}"' for alias in dropped_scripts)
            + " (cf-tool finds your compilers itself now; cf langs shows what it uses)."
        )
    for alias, key in skipped:
        kept = str(chosen[key].get("alias", "?"))
        notes.append(
            f'Not carried over: the template "{alias}" ({languages.display_name(key)} has one '
            f'setting now, and "{kept}" was kept).'
        )
    return notes


def _new_placeholders(script: str) -> str:
    """A 0.3 script with 0.4's placeholders. It runs in the code's folder, so
    the file's own folder ($%path%$) is no longer needed."""
    for old, new in (("$%full%$", "{src}"), ("$%file%$", "{name}"), ("$%rand%$", "{name}")):
        script = script.replace(old, new)
    return script.replace("$%path%$", "")
