"""Commands for problems and contests: get, race, new, listen, pick,
problems, contests, open."""

from __future__ import annotations

import re
import time
from pathlib import Path

import click
from rich.table import Table
from rich.text import Text

from cf_tool import languages, listen as listen_module, ui, views, workspace
from cf_tool.cli.common import (
    cf_command,
    client,
    open_url,
    settings,
    short,
    starter_language,
    starter_values,
    target_of,
    write_starter,
)
from cf_tool.cli.completion import complete_contests, complete_languages, complete_problems
from cf_tool.errors import CFError
from cf_tool.workspace import Target

# ┌──────────────────────────────────────────────────────────┐
# │                         cf get                           │
# └──────────────────────────────────────────────────────────┘


def set_up(target: Target, key: str, tries: int = 1) -> Path:
    """Fetch target's problems (tries times, 2 s apart, while there are none
    yet) and give each its folder: tests, info and starter code; returns the
    contest's folder."""
    for attempt in range(tries):
        try:
            found = client().fetch(target)
        except CFError:
            if attempt == tries - 1:
                raise
            found = []
        if found:
            break
        if attempt < tries - 1:
            time.sleep(2)  # NOTE: right at the start, the problems may not show yet
    if not found:
        wait = f"cf race {target.contest} waits for its start"
        raise CFError(f"{target.label} has no problems to see yet: {wait}")
    root = workspace.get_root(Path.cwd(), settings().root_folder())
    folders = []
    grid = Table.grid(padding=(0, 2))
    for column in ("folder", "name", "tests", "code", "notes"):
        grid.add_column(no_wrap=column != "notes")
    for problem in found:
        problem_target = target.with_problem(problem.index)
        folder = workspace.problem_folder(root, problem_target)
        if problem.samples:
            workspace.save_samples(folder, problem.samples)
        workspace.save_info(folder, problem.info)
        if problem.statement:
            workspace.save_statement(folder, problem.statement)
        code = write_starter(folder, problem_target, problem.info, key)
        folders.append(folder)
        count = len(problem.samples)
        notes = []
        if problem.error:
            notes.append(f"no samples: {problem.error}")
        if not problem.standard_io:
            notes.append("reads and writes files")
        if problem.info.interactive:
            notes.append("interactive: cf test needs an interactor")
        grid.add_row(
            Text(short(folder), style=f"bold {ui.ACCENT}"),
            Text(problem.info.name or problem.index),
            Text(f"{count} test{'s' if count != 1 else ''}", style=ui.MUTED),
            Text(code.name if code is not None else "", style=ui.MUTED),
            Text("; ".join(notes), style=ui.WARNING),
        )
    ui.console.print(grid)
    then = "cf test" if len(folders) == 1 else "cf test and cf submit there"
    ui.line(("→ ", "cyan bold"), (f"cd {short(folders[0])}", "bold"), (f", then {then}", "dim"))
    return folders[0].parent


@click.command()
@click.argument("specs", nargs=-1, metavar="CONTEST|PROBLEM|URL", shell_complete=complete_contests)
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="EXT",
    shell_complete=complete_languages,
    help="Starter code in this language.",
)
@cf_command
def get(specs: tuple[str, ...], language: str | None) -> None:
    """Set up a contest or a problem: a folder for each problem, with its
    samples as tests and your starter code.

    \b
    cf get 2050       every problem of contest 2050: 2050/a, 2050/b, ...
    cf get 2050b      one problem
    cf get URL        a contest's or a problem's page (gym, groups too)
    """
    target = target_of(specs)
    if not target.contest:
        raise CFError("Which contest or problem? Like cf get 2050, or cf get 2050b")
    set_up(target, starter_language(language))


@click.command()
@click.argument("specs", nargs=-1, metavar="CONTEST", shell_complete=complete_contests)
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="EXT",
    shell_complete=complete_languages,
    help="Starter code in this language.",
)
@cf_command
def race(specs: tuple[str, ...], language: str | None) -> None:
    """Count down to a contest's start, then open its problems and get them."""
    target = target_of(specs)
    if not target.contest:
        raise CFError("Which contest? Like cf race 2050")
    key = starter_language(language)  # NOTE: asked now, not when the contest starts
    contest = Target(target.kind, target.contest, "", target.group)
    ui.line(("Waiting for ", "cyan"), (contest.label, "bold"))
    client().race(contest)
    open_url(contest.problems_url(settings().host))
    set_up(contest, key, tries=5)


# ┌──────────────────────────────────────────────────────────┐
# │                         cf new                           │
# └──────────────────────────────────────────────────────────┘


@click.command()
@click.argument("name", required=False)
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="EXT",
    shell_complete=complete_languages,
    help="The language, when NAME has none.",
)
@cf_command
def new(name: str | None, language: str | None) -> None:
    """Write a code file from your starter code into this folder.

    \b
    cf new            <problem>.<ext>, like a.cpp in 2050/a
    cf new brute      brute.cpp, from templates/brute.cpp when you have one
    cf new gen.py     gen.py: the extension picks the language
    """
    cwd = Path.cwd()
    folder = workspace.find_problem_folder(cwd)
    info = workspace.load_info(folder) if folder else None
    target = workspace.here(cwd)
    key = languages.language_key(name, settings()) if name and "." in name else None
    key = key or starter_language(language)
    stem = (
        Path(name).stem
        if name
        else (target.problem.lower() if target and target.problem else "main")
    )
    path = cwd / f"{stem}.{key}"
    if path.exists():
        raise CFError(f"{path.name} exists already")
    text, origin = languages.starter(key, settings(), stem)
    path.write_text(
        languages.render(text, starter_values(target, info)), encoding="utf-8", newline=""
    )
    source = "the built-in starter" if origin == "built-in" else short(origin)
    ui.line(("Wrote ", "green"), (path.name, "bold green"), (f" from {source}", "dim"))


# ┌──────────────────────────────────────────────────────────┐
# │                        cf listen                         │
# └──────────────────────────────────────────────────────────┘


@click.command()
@click.option(
    "--port",
    default=listen_module.DEFAULT_PORT,
    show_default=True,
    help="The port (one the extension sends to, or one added in its settings).",
)
@click.option("--keep", is_flag=True, help="Keep listening after a contest or a problem arrived.")
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="EXT",
    shell_complete=complete_languages,
    help="Starter code in this language.",
)
@cf_command
def listen(port: int, keep: bool, language: str | None) -> None:
    """Receive problems from the Competitive Companion browser extension.

    Run it, then click the extension's button on a problem or contest page:
    the problems land where cf get would put them, and cf fetches no page.
    """
    key = starter_language(language)
    root = workspace.get_root(Path.cwd(), settings().root_folder())
    listen_module.listen(
        root,
        lambda folder, target, info: write_starter(folder, target, info, key),
        port=port,
        keep=keep,
    )


# ┌──────────────────────────────────────────────────────────┐
# │                         cf pick                          │
# └──────────────────────────────────────────────────────────┘

# for Tab completion: the problemset's tags
TAGS = (
    "*special", "2-sat", "binary search", "bitmasks", "brute force", "chinese remainder theorem",
    "combinatorics", "communication", "constructive algorithms", "data structures",
    "dfs and similar", "divide and conquer", "dp", "dsu", "expression parsing", "fft", "flows",
    "games", "geometry", "graph matchings", "graphs", "greedy", "hashing", "implementation",
    "interactive", "math", "matrices", "meet-in-the-middle", "number theory", "probabilities",
    "schedules", "shortest paths", "sortings", "string suffix structures", "strings",
    "ternary search", "trees", "two pointers",
)  # fmt: skip


def _rating_range(ctx, param, value: str | None) -> tuple[int, int] | None:
    """--rating 1600 or 1400-1800 as (low, high)."""
    if value is None:
        return None
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
    if not match:
        raise click.BadParameter("a rating like 1600, or a range like 1400-1800")
    low, high = int(match.group(1)), int(match.group(2) or match.group(1))
    return min(low, high), max(low, high)


def _tags(ctx, param, incomplete: str):
    from cf_tool.cli.completion import words

    return words(incomplete, [*TAGS, *(f"!{tag}" for tag in TAGS)])


@click.command()
@click.option(
    "-r", "--rating", callback=_rating_range, metavar="R|LOW-HIGH", help="e.g. 1600 or 1400-1800."
)
@click.option(
    "-t",
    "--tag",
    "tags",
    multiple=True,
    shell_complete=_tags,
    help='A tag it has (repeatable); "!tag" for one it hasn\'t.',
)
@click.option("--handle", default="", help="Whose solved problems to skip (default: yours).")
@click.option("--get", "get_it", is_flag=True, help="Set it up, as cf get does.")
@click.option("--open", "open_it", is_flag=True, help="Open it in the browser.")
@click.option(
    "-l",
    "--lang",
    "language",
    metavar="EXT",
    shell_complete=complete_languages,
    help="Starter code in this language.",
)
@cf_command
def pick(
    rating: tuple[int, int] | None,
    tags: tuple[str, ...],
    handle: str,
    get_it: bool,
    open_it: bool,
    language: str | None,
) -> None:
    """A random problem you haven't solved, by rating and tags, to practice on."""
    from cf_tool.codeforces.client import pick_problem

    c = client()
    handle = handle or c.handle
    with ui.status("Reading the problemset..."):
        problems = c.problemset()
        solved = c.solved(handle) if handle else set()
    if not handle:
        ui.yellow("Not logged in: solved problems aren't skipped (or give --handle).")
    low, high = rating or (None, None)
    problem, pool = pick_problem(problems, solved, low=low, high=high, tags=tags)
    if problem is None:
        raise CFError("No problem you haven't solved matches that")
    target = workspace.parse_target([problem.id])
    ui.line(
        (problem.id, "bold green"),
        (f"  {problem.name}", "bold"),
        (f"  rating {problem.rating}" if problem.rating else "  unrated", "cyan"),
    )
    ui.line((", ".join(problem.tags) or "no tags", "dim"))
    url = target.problem_url(c.host)
    ui.plain(f"{url}  (one of {pool} to pick from)")
    if open_it:
        open_url(url)
    if get_it:
        set_up(target, starter_language(language))


# ┌──────────────────────────────────────────────────────────┐
# │               cf problems, contests, open                │
# └──────────────────────────────────────────────────────────┘


@click.command()
@click.argument("specs", nargs=-1, metavar="[CONTEST]", shell_complete=complete_problems)
@cf_command
def problems(specs: tuple[str, ...]) -> None:
    """A contest's problems, with how many solved each (yours marked)."""
    target = target_of(specs)
    ui.console.print(views.problems_table(client().problem_rows(target)))


@click.command()
@click.option(
    "--ics",
    "ics_path",
    type=click.Path(dir_okay=False),
    help="Also save them as a calendar file (.ics) to import.",
)
@cf_command
def contests(ics_path: str | None) -> None:
    """Upcoming contests, soonest first."""
    c = client()
    upcoming = c.contests()
    if not upcoming:
        ui.plain("No contest is scheduled right now.")
        return
    ui.console.print(views.contests_table(upcoming, time.time()))
    if ics_path:
        Path(ics_path).write_text(
            views.to_ics(upcoming, c.host, time.time()), encoding="utf-8", newline=""
        )
        ui.green(f"Saved them to {ics_path}: import it into your calendar")


def _open(specs: tuple[str, ...], standings: bool, last: bool) -> None:
    host = settings().host
    urls = [spec for spec in specs if spec.startswith(("http://", "https://"))]
    if urls and not (standings or last):
        open_url(urls[0])
        return
    if last:
        saved = client().session.last_submission
        if not saved or not saved.get("submission"):
            raise CFError("No submission yet: cf submit remembers the last one")
        target = Target(
            saved["kind"] or "contest", saved["contest"], saved["problem"], saved["group"]
        )
        open_url(target.submission_url(host, saved["submission"]))
        return
    target = target_of(specs)
    open_url(target.standings_url(host) if standings else target.page_url(host))


@click.command("open")
@click.argument("specs", nargs=-1, metavar="[PROBLEM|CONTEST]", shell_complete=complete_problems)
@click.option("-s", "--standings", is_flag=True, help="The contest's standings.")
@click.option("--last", is_flag=True, help="Your last submission.")
@cf_command
def open_(specs: tuple[str, ...], standings: bool, last: bool) -> None:
    """Open the problem (or contest) here in the browser."""
    _open(specs, standings, last)


@click.command(hidden=True)
@click.argument("specs", nargs=-1)
@cf_command
def stand(specs: tuple[str, ...]) -> None:
    """cf open --standings (cf-tool 0.3's name)."""
    _open(specs, True, False)


@click.command(hidden=True)
@click.argument("specs", nargs=-1)
@cf_command
def sid(specs: tuple[str, ...]) -> None:
    """cf open --last (cf-tool 0.3's name)."""
    _open(specs, False, True)


COMMANDS = [get, race, new, listen, pick, problems, contests, open_, stand, sid]
