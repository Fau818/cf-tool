"""Tab completion: what each argument can be, from the folder you're in.
Completers run on every Tab, so they stay quick and never raise or print."""

from __future__ import annotations

import os
from pathlib import Path

import click
from click.shell_completion import CompletionItem, get_completion_class

from cf_tool import languages, workspace
from cf_tool.errors import CFError


def words(incomplete: str, candidates) -> list[CompletionItem]:
    """Completions: the candidates that start with what was typed so far."""
    typed = incomplete.lower()
    return [CompletionItem(w) for w in dict.fromkeys(candidates) if w.lower().startswith(typed)]


def _problems_here() -> list[str]:
    """Problems this folder knows: the current contest's problem letters,
    and the problems its code files are named for (2050A)."""
    try:
        cwd = Path.cwd()
        found: list[str] = []
        contest = workspace.contest_folder(cwd)
        if contest is not None:
            found += sorted(
                child.name for child in contest.iterdir() if (child / workspace.METADATA).is_file()
            )
        known = languages.code_extensions()
        for entry in cwd.iterdir():
            if entry.suffix in known and entry.is_file():
                number, letter = workspace.named_target(entry.name, cwd)
                if number and letter:
                    found.append(f"{number}{letter}")
        return found
    except (CFError, OSError):
        return []  # NOTE: a broken folder only costs the suggestions


def complete_languages(ctx, param, incomplete: str) -> list[CompletionItem]:
    """The languages cf-tool knows, by their extension (cpp, py, ...)."""
    from cf_tool.settings import Settings

    try:
        extra = list(Settings.load().languages)
    except (CFError, OSError):
        extra = []
    return words(incomplete, [*languages.LANGUAGES, *extra])


def complete_problems(ctx, param, incomplete: str) -> list[CompletionItem]:
    return words(incomplete, _problems_here())


def complete_problems_and_files(ctx, param, incomplete: str) -> list[CompletionItem]:
    return [*words(incomplete, _problems_here()), CompletionItem(incomplete, type="file")]


def complete_tests(ctx, param, incomplete: str) -> list[CompletionItem]:
    """The tests of the problem here, the problems around, and file names."""
    try:
        folder = workspace.find_problem_folder(Path.cwd())
        tests = [t.name for t in workspace.tests_of(folder)] if folder else []
    except OSError:
        tests = []
    return [
        *words(incomplete, [*tests, *_problems_here()]),
        CompletionItem(incomplete, type="file"),
    ]


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
