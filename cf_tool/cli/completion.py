"""Tab completion: what each argument can be, from the folders around and the
contest list cf keeps. Never every number: only contests and problems that
have folders here (or are on now), and code files rather than every file.
Completers run on every Tab, so they stay quick and never raise or print."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Union

import click
from click.shell_completion import CompletionItem, get_completion_class

from cf_tool import languages, paths, workspace
from cf_tool.errors import CFError

Candidate = Union[str, tuple[str, str]]  # a value, or (value, what it is)
RECENT_CONTESTS = 8  # contests on or just over offered to cf get


def words(incomplete: str, candidates: Iterable[Candidate]) -> list[CompletionItem]:
    """Completions: the candidates that start with what was typed so far,
    each once, with what it is when known (zsh and fish show that)."""
    typed = incomplete.lower()
    items: dict[str, CompletionItem] = {}
    for candidate in candidates:
        value, about = candidate if isinstance(candidate, tuple) else (candidate, "")
        if value.lower().startswith(typed) and value not in items:
            items[value] = CompletionItem(value, help=about or None)
    return list(items.values())


def _subfolders(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def _problems_of(contest: Path) -> list[tuple[str, str]]:
    """A contest folder's problems: (folder name, problem name), a -> A. Watermelon."""
    found = []
    for child in _subfolders(contest):
        if (child / workspace.METADATA).is_file():
            info = workspace.load_info(child)
            found.append((child.name, info.name if info else ""))
    return found


def _contests_around(cwd: Path) -> dict[str, list[tuple[str, str]]]:
    """Contests with folders around, by id, with their problems: the one cwd
    is in, and those in cwd and in the root folder (2050/ holding 2050/a/)."""
    folders = []
    current = workspace.contest_folder(cwd)
    if current is not None:
        folders.append(current)
    for base in dict.fromkeys([cwd, _root()]):
        if base is not None:
            folders += [f for f in _subfolders(base) if f.name.isdigit()]
    contests: dict[str, list[tuple[str, str]]] = {}
    for folder in folders:
        problems = _problems_of(folder)
        if not problems:
            continue
        info = workspace.load_info(folder / problems[0][0])
        target = info.target if info else None
        contest = target.contest if target and target.kind != "acmsguru" else folder.name
        if contest.isdigit():
            contests.setdefault(contest, problems)
    return contests


def _root() -> Path | None:
    from cf_tool.settings import Settings

    try:
        return Settings.load().root_folder()
    except (CFError, OSError):
        return None


def _listed_contests() -> list[dict]:
    """The contest list cf keeps (from cf contests and cf get); [] without one."""
    try:
        data = json.loads((paths.STATE_DIR / "contests.json").read_text(encoding="utf-8"))
        return [c for c in data.get("result", []) if isinstance(c, dict) and "id" in c]
    except (OSError, ValueError, AttributeError):
        return []


def _named_by_files(cwd: Path) -> list[str]:
    """The problems this folder's code files are named for (2050A.cpp -> 2050A)."""
    found = []
    for name in _code_files(cwd):
        number, letter = workspace.named_target(name, cwd)
        if number and letter:
            found.append(f"{number}{letter}")
    return found


def _code_files(cwd: Path) -> list[str]:
    """The code files in cwd, helpers left out."""
    known = languages.code_extensions()
    try:
        entries = sorted(cwd.iterdir())
    except OSError:
        return []
    return [
        e.name
        for e in entries
        if e.suffix.lower() in known and e.is_file() and not workspace.is_helper(e.name)
    ]


def _earlier(ctx) -> tuple[str, ...]:
    """The arguments typed before the one being completed."""
    for name in ("specs", "args"):
        value = ctx.params.get(name)
        if value:
            return tuple(value)
    return ()


def _problems(ctx, incomplete: str) -> list[Candidate]:
    """What a problem argument can name here:
    - after a contest's id (cf submit 2050 _): that contest's problems
    - the problems of the contest cwd is in, by letter
    - contests with folders around; once one's id is typed, its problems too
    - problems that code files here are named for (2050A.cpp)"""
    try:
        cwd = Path.cwd()
        contests = _contests_around(cwd)
        named = next((a for a in reversed(_earlier(ctx)) if a in contests), None)
        if named is not None:
            return list(contests[named])
        candidates: list[Candidate] = []
        current = workspace.contest_folder(cwd)
        if current is not None:
            candidates += _problems_of(current)
        names = {str(c["id"]): str(c.get("name", "")) for c in _listed_contests()}
        for contest, problems in contests.items():
            count = f"{len(problems)} problem{'s' if len(problems) > 1 else ''} here"
            candidates.append((contest, names.get(contest) or count))
            if incomplete == contest:
                candidates += [(f"{contest}{letter}", name) for letter, name in problems]
        return candidates + _named_by_files(cwd)
    except (CFError, OSError):
        return []  # NOTE: a broken folder only costs the suggestions


def _files(incomplete: str) -> list[CompletionItem]:
    """The code files here; for a path being typed (../, ~/), the shell's own
    file completion."""
    if incomplete.startswith((".", "~", "/")) or os.sep in incomplete or "/" in incomplete:
        return [CompletionItem(incomplete, type="file")]
    return words(incomplete, _code_files(Path.cwd()))


def complete_languages(ctx, param, incomplete: str) -> list[CompletionItem]:
    """The languages cf-tool knows, by their extension (cpp, py, ...)."""
    from cf_tool.settings import Settings

    try:
        extra = list(Settings.load().languages)
    except (CFError, OSError):
        extra = []
    return words(incomplete, [*languages.LANGUAGES, *extra])


def complete_problems(ctx, param, incomplete: str) -> list[CompletionItem]:
    return words(incomplete, _problems(ctx, incomplete))


def complete_contests(ctx, param, incomplete: str) -> list[CompletionItem]:
    """For cf get and cf race: the contests on now or about to start, those
    just over (from the contest list cf keeps), and the ones around."""
    now = time.time()
    listed = sorted(_listed_contests(), key=lambda c: -int(c.get("startTimeSeconds") or 0))
    soon = [
        c
        for c in listed
        if c.get("phase") == "BEFORE" and 0 <= (c.get("startTimeSeconds") or 0) - now < 86400
    ]
    started = [c for c in listed if c.get("phase") != "BEFORE"][:RECENT_CONTESTS]
    recent = [(str(c["id"]), str(c.get("name", ""))) for c in [*soon, *started]]
    return words(incomplete, [*_problems(ctx, incomplete), *recent])


def complete_problems_and_files(ctx, param, incomplete: str) -> list[CompletionItem]:
    """For cf submit: the problems around and the code files here."""
    return [*words(incomplete, _problems(ctx, incomplete)), *_files(incomplete)]


def complete_tests(ctx, param, incomplete: str) -> list[CompletionItem]:
    """For cf test: the tests of the problem here, the problems around, and
    the code files here."""
    try:
        folder = workspace.find_problem_folder(Path.cwd())
        tests = [t.name for t in workspace.tests_of(folder)] if folder else []
    except OSError:
        tests = []
    return [*words(incomplete, [*tests, *_problems(ctx, incomplete)]), *_files(incomplete)]


@click.command()
@click.argument("shell", required=False, type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str | None) -> None:
    """Print the Tab-completion script for bash, zsh or fish.

    \b
    zsh:   eval "$(cf completion zsh)"    in ~/.zshrc, after compinit
    bash:  eval "$(cf completion bash)"   in ~/.bashrc (bash 4.4+)
    fish:  cf completion fish | source    in ~/.config/fish/config.fish
    """
    from cf_tool.cli import main

    shell = shell or Path(os.environ.get("SHELL", "")).name
    script = get_completion_class(shell)
    if script is None:
        raise click.UsageError(
            f'Cannot tell your shell ("{shell}"): run cf completion zsh, bash or fish'
        )
    click.echo(script(main, {}, "cf", "_CF_COMPLETE").source())
