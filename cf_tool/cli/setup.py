"""Commands about cf-tool itself: config, langs, doctor, upgrade."""

from __future__ import annotations

import platform
import re
import sys

import click
from rich import box
from rich.table import Table
from rich.text import Text

from cf_tool import __version__, languages, paths, ui
from cf_tool.cli.common import cf_command, client, reset, settings, short, starter_language
from cf_tool.errors import CFError
from cf_tool.settings import Settings

REPOSITORY = "Fau818/cf-tool"


@click.command()
@click.option("--path", "path_only", is_flag=True, help="Print where the file is, and stop.")
@cf_command
def config(path_only: bool) -> None:
    """Open the settings (config.toml) in your editor; every setting in it
    is explained there, and all of them are optional."""
    path = paths.config_file()
    if path_only:
        click.echo(str(path))  # NOTE: never wrapped, for scripts
        return
    try:
        current = settings()
    except CFError as e:  # NOTE: a broken file is opened all the same, to fix it
        ui.yellow(str(e))
        current = None
    if current is not None and not path.exists():
        if not current.language and ui.interactive():
            starter_language()
        current.write_default()
    click.edit(filename=str(path))
    reset()
    try:
        reloaded = Settings.load(path)
    except CFError as e:
        raise CFError(f"{e}\nRun cf config again to fix it") from e
    for warning in reloaded.warnings:
        ui.yellow(warning)
    ui.green(f"Saved {short(path)}")


@click.command()
@click.option(
    "--all", "show_all", is_flag=True, help="Every language Codeforces offers, with its id."
)
@cf_command
def langs(show_all: bool) -> None:
    """The languages: what builds and runs each here, what it submits as,
    and its starter code."""
    current = settings()
    offered, live = client().languages() if show_all else (languages.known_languages(), False)
    if show_all:
        table = Table(box=box.ROUNDED, border_style="dim", header_style="bold cyan")
        for column in ("id", "Codeforces language", "files"):
            table.add_column(column)
        for ext, group in sorted(
            languages.by_family(offered).items(), key=lambda item: languages.family_name(item[0])
        ):
            for lid, name in group:
                table.add_row(lid, Text(name), f".{ext}" if ext != "txt" else "")
        ui.console.print(table)
        if not live:
            ui.yellow("Not logged in: this is the list read last (cf login reads the current one).")
        return
    table = Table(box=box.ROUNDED, border_style="dim", header_style="bold cyan")
    for column in ("language", "files", "builds and runs with", "submits as", "starter code"):
        table.add_column(column)
    keys = list(dict.fromkeys([*languages.LANGUAGES, *current.languages]))
    for key in keys:
        language = languages.LANGUAGES.get(key)
        files = " ".join(f".{ext}" for ext in (language.extensions if language else (key,)))
        try:
            setup = languages.setup(key, current, offered=offered)
            tool = Text(setup.tool)
            submits = Text(
                setup.submit[1] if setup.submit else "not offered",
                style="" if setup.submit else "yellow",
            )
        except CFError as e:
            hint = str(e).split(". To get one: ")
            tool = Text(f"missing: {hint[-1]}" if len(hint) > 1 else str(e), style="yellow")
            submits = Text("")
        try:
            _, origin = languages.starter(key, current)
            starter = "built-in" if origin == "built-in" else short(origin)
        except CFError:
            starter = "missing"
        name = languages.display_name(key) + (" *" if key == current.language else "")
        table.add_row(
            Text(name, style="bold" if key == current.language else ""),
            files,
            tool,
            submits,
            Text(starter),
        )
    ui.console.print(table)
    ui.dim(f"* cf get's language. Change any of these in {short(current.file)} (cf config).")
    ui.dim("cf langs --all lists the languages Codeforces offers.")


_MARKS = {"ok": ("✓ ", "green"), "warn": ("! ", "yellow"), "error": ("✗ ", "red")}


@click.command()
@cf_command
def doctor() -> None:
    """Check the setup (languages, compilers, login, Chrome) and say how to fix it."""
    from cf_tool import doctor as checks

    ui.plain(f"cf-tool {__version__}, Python {platform.python_version()}, {sys.platform}")
    try:
        findings = checks.run(settings(), client())
    except CFError as e:  # NOTE: a broken settings file is a finding too
        findings = [checks.Finding(checks.ERROR, str(e))]
    for finding in findings:
        ui.line(_MARKS[finding.level], (finding.text, ""))
        if finding.fix:
            ui.line(("    " + finding.fix, "cyan"))
    if any(finding.level == checks.ERROR for finding in findings):
        sys.exit(1)


_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)(?:[-._]?(a|alpha|b|beta|c|rc)[-._]?(\d*))?", re.I)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2}


def version_key(version: str) -> tuple[int, ...] | None:
    """Sortable form of "0.3.0", "v0.3.0a1", "0.3.0-rc.2" (PEP 440 order:
    0.3.0a1 < 0.3.0b1 < 0.3.0rc1 < 0.3.0); None if it is not a version."""
    match = _VERSION_RE.fullmatch(version.strip())
    if not match:
        return None
    release = [int(n) for n in match.group(1).split(".")]
    release += [0] * (4 - len(release))
    tag = (match.group(2) or "").lower()
    return (*release, _PRE_RANK.get(tag, 3), int(match.group(3) or 0))


@click.command()
@cf_command
def upgrade() -> None:
    """Check GitHub for a newer cf-tool release."""
    from curl_cffi import requests as curl_requests

    ui.cyan(f"Current version is {__version__}")
    url = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
    try:
        response = curl_requests.get(
            url,
            timeout=10,
            # NOTE: GitHub's API refuses requests without a User-Agent
            headers={
                "User-Agent": f"cf-tool/{__version__}",
                "Accept": "application/vnd.github+json",
            },
        )
    except Exception as e:
        raise CFError(f"Cannot reach GitHub: {e}") from e
    if response.status_code != 200:
        raise CFError(f"Cannot list the releases of {REPOSITORY} ({response.status_code})")
    current = version_key(__version__) or ()
    on_prerelease = current[-2:-1] != (3,)
    # NOTE: pre-releases are offered only to those already running one
    tags = [
        str(release.get("tag_name", ""))
        for release in response.json()
        if not release.get("draft") and (on_prerelease or not release.get("prerelease"))
    ]
    versions = [(key, tag) for tag in tags if (key := version_key(tag))]
    if not versions:
        raise CFError(f"No release of {REPOSITORY} is published on GitHub yet")
    latest_key, latest = max(versions)
    if latest_key <= current:
        ui.green("You already have the latest version")
        return
    ui.green(f"Latest version is {latest}. Upgrade with:")
    if latest_key[-2] == 3:  # NOTE: a release, not a pre-release: on PyPI
        ui.plain("  uv tool upgrade cf-tool        (or: pipx upgrade cf-tool)")
        ui.plain("Installed from GitHub:")
    ui.plain(f"  uv tool install --force git+https://github.com/{REPOSITORY}@{latest}")
    ui.plain(f"  (or: pipx install --force git+https://github.com/{REPOSITORY}@{latest})")


COMMANDS = [config, langs, doctor, upgrade]
