"""Commands for submissions: submit, status, pull, clone."""

from __future__ import annotations

from pathlib import Path

import click

from cf_tool import judge, languages, ui, workspace
from cf_tool.cli.common import (
    cf_command,
    client,
    code_file_among,
    ensure_login,
    problem_folder_of,
    settings,
    target_of,
)
from cf_tool.cli.completion import complete_problems, complete_problems_and_files
from cf_tool.errors import CFError
from cf_tool.workspace import Target


def _label(contest: str, problem: str) -> str:
    """2050A, problem A or contest 2050: what a file name points at."""
    if contest and problem:
        return f"{contest}{problem}"
    return f"problem {problem}" if problem else f"contest {contest}"


def _submit_target(target: Target, filename: str, specs: tuple[str, ...]) -> Target:
    """The problem to submit filename to: target, its gaps filled in from what
    the file's name says. Both a file named for another problem and a target
    read off the name need a yes first."""
    contest, problem = workspace.named_target(filename, Path.cwd())
    clash = (target.contest and contest and contest != target.contest) or (
        target.problem and problem and problem != target.problem
    )
    if clash:
        question = f"{filename} looks like {_label(contest, problem)}. Submit it to {target.label}?"
        if not ui.confirm(question, default=False):
            raise CFError("Not submitted")
        return target
    missing = [
        value
        for value, known in ((contest, target.contest), (problem, target.problem))
        if value and not known
    ]
    if not missing:
        return target
    target = target_of(specs + tuple(missing))
    if not ui.confirm(f"Submit {filename} to {target.label}?", default=True):
        raise CFError("Not submitted")
    return target


def _language_chooser(key: str, path: Path, asked: str):
    """choose_language for Client.submit: the language asked for (-l) or set
    for the file's language, else the family's best; when the form offers
    none of those, the user picks one of the family (and may keep it)."""

    def choose(offered: dict[str, str]) -> tuple[str, str]:
        conf = settings().language_settings(key)
        spec = asked or conf.submit
        chosen = languages.choose_submit(key, spec, offered)
        if chosen is not None:
            return chosen
        options = languages.family(key, offered)
        if not options:
            wanted = spec or languages.display_name(key)
            raise CFError(f"Codeforces doesn't offer {wanted} here, nor anything like it")
        old = languages.known_languages().get(spec, spec) if spec else languages.display_name(key)
        lang_id = ui.select(
            f"Codeforces doesn't offer {old} here. Submit {path.name} as:",
            [(name, lid) for lid, name in options] + [("Don't submit", None)],
            default=options[0][0],
        )
        if lang_id is None:
            raise CFError("Not submitted")
        if not asked and ui.confirm(
            f"Submit {languages.display_name(key)} as {offered[lang_id]} from now on?", default=True
        ):
            settings().update("submit", lang_id, table=key)
        return lang_id, offered[lang_id]

    return choose


@click.command()
@click.argument(
    "args", nargs=-1, metavar="[PROBLEM] [FILE]", shell_complete=complete_problems_and_files
)
@click.option(
    "-f", "--file", "file_arg", type=click.Path(dir_okay=False), help="The code file to submit."
)
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="NAME|ID",
    default="",
    help="The Codeforces language, this once.",
)
@cf_command
def submit(args: tuple[str, ...], file_arg: str | None, language: str) -> None:
    """Submit your code, then show the verdict as it comes.

    \b
    cf submit             the code of the problem here
    cf submit b           problem b of this contest
    cf submit 2050b a.cpp this file to that problem
    With several code files around, you pick one (Esc cancels).
    """
    named, specs = code_file_among(args)
    if named and file_arg:
        raise CFError("Give the code file once: as -f or as an argument")
    file_arg = file_arg or named
    cwd = Path.cwd()
    target = target_of(specs)
    folder = problem_folder_of(target) if target.problem else workspace.find_problem_folder(cwd)
    if file_arg:
        filename, key = workspace.pick_code(file_arg, cwd, settings())
        path = Path(file_arg).resolve()
    else:
        search = folder or cwd
        name, key = workspace.pick_code(
            None, search, settings(), contest=target.contest, problem=target.problem
        )
        path = (search / name).resolve()
        filename = str(Path(name)) if search == cwd else _relative(path, cwd)
    target = _submit_target(target, filename, specs)
    failed = judge.failed_tests(path)
    if failed and ui.interactive():
        tests = ", ".join(failed[:3]) + (" ..." if len(failed) > 3 else "")
        if not ui.confirm(
            f"This code failed the test {tests} in cf test. Submit it anyway?", default=False
        ):
            raise CFError("Not submitted")
    c = client()
    ensure_login(c)
    source = workspace.read_source(path)
    c.submit(target, source, _language_chooser(key, path, language), filename=filename)


def _relative(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd.resolve()))
    except ValueError:
        return str(path)


@click.command()
@click.argument("specs", nargs=-1, metavar="[PROBLEM|CONTEST]", shell_complete=complete_problems)
@click.option("--all", "show_all", is_flag=True, help="All of them, not the last 10.")
@cf_command
def status(specs: tuple[str, ...], show_all: bool) -> None:
    """Your submissions to the contest, refreshed until they're judged."""
    target = target_of(specs)
    c = client()
    ensure_login(c)
    c.watch(target, count=-1 if show_all else 10, problem=target.problem)


@click.command()
@click.argument("specs", nargs=-1, metavar="[PROBLEM|CONTEST]", shell_complete=complete_problems)
@click.option("--ac", is_flag=True, help="Accepted ones only.")
@cf_command
def pull(specs: tuple[str, ...], ac: bool) -> None:
    """Download the code of your submissions into the problems' folders."""
    target = target_of(specs)
    c = client()
    ensure_login(c)
    root = workspace.get_root(Path.cwd(), settings().root_folder())

    def folder_of(index: str) -> Path:
        problem = target.with_problem(index)
        return problem_folder_of(problem) or workspace.problem_folder(root, problem)

    if not c.pull(target, folder_of, ac):
        raise CFError("No code to download")


@click.command()
@click.argument("handle", required=False)
@click.option("--ac", is_flag=True, help="Accepted ones only.")
@cf_command
def clone(handle: str | None, ac: bool) -> None:
    """Download the code of every submission of a user (default: you)."""
    c = client()
    handle = handle or c.handle
    if not handle:
        raise CFError("Whose? Give a handle, or log in with cf login")
    saved = c.clone(handle, Path.cwd(), ac)
    ui.green(f"Saved {saved} file{'s' if saved != 1 else ''}")


COMMANDS = [submit, status, pull, clone]
