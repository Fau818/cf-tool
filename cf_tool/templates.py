"""Template placeholder substitution and `cf gen` (port of cmd/gen.go).

Which code file a command means lives in codefiles.py.
"""

from __future__ import annotations

import os
import random
from datetime import datetime
from pathlib import Path

from cf_tool import ui
from cf_tool.codefiles import read_source
from cf_tool.config import Config
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
    save_path.write_text(source, encoding="utf-8", newline="")
    ui.green(f"Generated! See {save_path.name}")
    return save_path


def gen(cfg: Config, handle: str, cwd: Path, alias: str | None = None) -> Path:
    """`cf gen [alias]`: instantiate a template into the current directory."""
    template_path = template_path_for_alias(cfg, alias) if alias else cfg.default_template().path
    template_file = Path(template_path).expanduser()
    source = read_source(template_file)
    return generate_file(substitute_code(source, handle), cwd, template_file.suffix)
