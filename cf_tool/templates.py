"""Template placeholder substitution, code-file detection, and `cf gen`.

Port of cmd/gen.go and the getCode/getOneCode helpers in cmd/cmd.go.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cf_tool import langs, ui
from cf_tool.config import CodeTemplate, Config
from cf_tool.errors import CFError

_RAND_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def rand_string(n: int = 8) -> str:
    return "".join(random.choice(_RAND_CHARS) for _ in range(n))


def substitute_code(source: str, handle: str, now: datetime | None = None) -> str:
    """Replace $%U%$ / $%Y%$ / $%M%$ / $%D%$ / $%h%$ / $%m%$ / $%s%$."""
    now = now or datetime.now()
    for placeholder, value in (
        ("$%U%$", handle),
        ("$%Y%$", f"{now.year}"),
        ("$%M%$", f"{now.month:02d}"),
        ("$%D%$", f"{now.day:02d}"),
        ("$%h%$", f"{now.hour:02d}"),
        ("$%m%$", f"{now.minute:02d}"),
        ("$%s%$", f"{now.second:02d}"),
    ):
        source = source.replace(placeholder, value)
    return source


def substitute_script(script: str, *, path: str, full: str, file: str, rand: str) -> str:
    """Replace $%path%$ / $%full%$ / $%file%$ / $%rand%$ in a template script."""
    for placeholder, value in (
        ("$%rand%$", rand),
        ("$%path%$", path),
        ("$%full%$", full),
        ("$%file%$", file),
    ):
        script = script.replace(placeholder, value)
    return script


def script_substitutions(filename: str) -> dict[str, str]:
    """Compute the $%path%$/$%full%$/$%file%$/$%rand%$ values for a code file."""
    directory, full = os.path.split(filename)
    path = directory + os.sep if directory else ""
    file, _ = os.path.splitext(full)
    return {"path": path, "full": full, "file": file, "rand": rand_string(8)}


@dataclass
class CodeList:
    """A code file plus the indexes of templates whose suffix matches it."""

    name: str
    indexes: list[int]


def _suffix_map(templates: list[CodeTemplate]) -> dict[str, list[int]]:
    ext_map: dict[str, list[int]] = {}
    for i, template in enumerate(templates):
        for suffix in dict.fromkeys(template.suffix):
            ext_map.setdefault("." + suffix, []).append(i)
    return ext_map


def get_code(filename: str | None, templates: list[CodeTemplate], cwd: Path) -> list[CodeList]:
    """List candidate code files: the explicit one, or every file in cwd whose
    extension matches some template suffix."""
    ext_map = _suffix_map(templates)

    if filename:
        ext = os.path.splitext(filename)[1]
        if ext in ext_map:
            return [CodeList(filename, ext_map[ext])]
        raise CFError(
            f"{filename} can not match any template. You could add a new template by `cf config`"
        )

    codes = []
    for entry in sorted(cwd.iterdir()):
        if entry.is_file() and entry.suffix in ext_map:
            codes.append(CodeList(entry.name, ext_map[entry.suffix]))
    return codes


def get_one_code(
    filename: str | None,
    templates: list[CodeTemplate],
    cwd: Path,
    langs_table: dict[str, str] | None = None,
) -> tuple[str, int]:
    """Resolve to exactly one (filename, template index), prompting on ambiguity."""
    codes = get_code(filename, templates, cwd)
    if not codes:
        raise CFError("Cannot find any code.\nMaybe you should add a new template by `cf config`")
    chosen = codes[0]
    if len(codes) > 1:
        chosen = ui.select(
            "Multiple files match. Which one?",
            [(code.name, code) for code in codes],
        )
    index = chosen.indexes[0]
    if len(chosen.indexes) > 1:
        index = ui.select(
            "Multiple languages match this file. Which one?",
            [(langs.name_of(templates[idx].lang, langs_table), idx) for idx in chosen.indexes],
        )
    return chosen.name, index


def template_path_for_alias(cfg: Config, alias: str) -> str:
    """Pick the template file for `cf gen <alias>`, prompting if ambiguous."""
    matching = cfg.templates_by_alias(alias)
    if not matching:
        raise CFError(f"Cannot find any template with alias {alias}")
    if len(matching) == 1:
        return matching[0].path
    return ui.select(
        f'Multiple templates with alias "{alias}". Which one?',
        [(template.path, template.path) for template in matching],
    )


def generate_file(source: str, current_path: Path, ext: str) -> Path:
    """Write source as <dirname><ext> in current_path, renaming on collision
    (a.cpp -> a1.cpp -> a2.cpp ...)."""
    base = current_path / current_path.resolve().name
    save_path = Path(f"{base}{ext}")
    i = 1
    while save_path.exists():
        tmp_path = Path(f"{base}{i}{ext}")
        ui.plain(f"{save_path.name} exists. Rename to {tmp_path.name}")
        save_path = tmp_path
        i += 1
    save_path.write_text(source, encoding="utf-8")
    ui.green(f"Generated! See {save_path.name}")
    return save_path


def gen(cfg: Config, handle: str, cwd: Path, alias: str | None = None) -> Path:
    """`cf gen [alias]`: instantiate a template into the current directory."""
    if not cfg.template:
        raise CFError("You have to add at least one code template by `cf config`")
    if alias:
        template_path = template_path_for_alias(cfg, alias)
    else:
        template_path = cfg.template[cfg.default].path
    template_file = Path(template_path).expanduser()
    try:
        source = template_file.read_text(encoding="utf-8")
    except OSError as e:
        raise CFError(f"Cannot read template {template_file}: {e}") from e
    return generate_file(substitute_code(source, handle), cwd, template_file.suffix)
