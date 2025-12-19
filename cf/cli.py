"""
CLI interface for cf-tool using Click.
"""

import re
from typing import Tuple

import click
from rich.console import Console

from cf import __version__

console = Console()


def parse_problem_id(args: Tuple[str, ...]) -> Tuple[str, str]:
    """
    Parse contest_id and problem_id from arguments.

    Supports both formats:
    - Combined: "1000A" or "1000a"
    - Separate: "1000" "A"

    Args:
        args: Tuple of 1 or 2 arguments

    Returns:
        Tuple of (contest_id, problem_id)

    Raises:
        click.BadParameter: If format is invalid
    """
    if len(args) == 2:
        return args[0], args[1].upper()
    elif len(args) == 1:
        # Try to parse combined format like "1000A" or "1000a1"
        match = re.match(r'^(\d+)([A-Za-z]\d*)$', args[0])
        if match:
            return match.group(1), match.group(2).upper()
        else:
            raise click.BadParameter(
                f"Invalid format: '{args[0]}'. Use '1000A' or '1000 A'"
            )
    else:
        raise click.BadParameter("Expected 1 or 2 arguments for contest/problem")


@click.group()
@click.version_option(version=__version__, prog_name="cf")
def cli():
    """Codeforces CLI tool for competitive programming."""
    pass


@cli.group()
def config():
    """Configure cf-tool settings."""
    pass


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value."""
    from cf.config import Config

    cfg = Config()
    cfg.set(key, value)
    cfg.save()
    console.print(f"[green]Set {key} = {value}[/green]")


@config.command("get")
@click.argument("key")
def config_get(key):
    """Get a configuration value."""
    from cf.config import Config

    cfg = Config()
    value = cfg.get(key)
    if value is not None:
        console.print(f"{key} = {value}")
    else:
        console.print(f"[red]Key '{key}' not found[/red]")


@config.command("show")
def config_show():
    """Show all configuration."""
    from cf.config import Config

    cfg = Config()
    console.print("[bold]Current Configuration:[/bold]")
    for key, value in cfg.data.items():
        console.print(f"  {key}: {value}")


@config.command("login")
@click.option("--username", prompt=True, help="Codeforces username")
@click.option("--password", prompt=True, hide_input=True, help="Codeforces password")
def config_login(username, password):
    """Login to Codeforces."""
    from cf.session import Session
    from cf.config import Config

    cfg = Config()
    cfg.set("username", username)
    cfg.save()

    session = Session()
    try:
        session.login(username, password)
        console.print("[green]Successfully logged in![/green]")
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")


@cli.command()
@click.argument("problem", nargs=-1, required=True)
@click.option("--lang", "-l", default=None, help="Programming language (cpp, py)")
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym", "problemset", "group"]),
              help="Contest type")
def parse(problem, lang, contest_type):
    """
    Parse a problem and download test cases.

    \b
    Examples:
        cf parse 1000A
        cf parse 1000 A
    """
    from cf.parser import parse_problem
    from cf.config import Config

    try:
        contest_id, problem_id = parse_problem_id(problem)
    except click.BadParameter as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()

    if lang is None:
        cfg = Config()
        lang = cfg.get("default_language", "cpp")

    try:
        with console.status(f"[bold green]Parsing problem {contest_id}/{problem_id}..."):
            result = parse_problem(contest_id, problem_id, lang, contest_type)

        console.print(f"[green]Successfully parsed problem {result['problem_id']}[/green]")
        console.print(f"  Directory: {result['directory']}")
        console.print(f"  Test cases: {result['test_count']}")
        console.print(f"  Solution file: {result['solution_file']}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.option("--file", "-f", default=None, help="Solution file to test")
def test(file):
    """Test solution against sample test cases."""
    from cf.tester import run_tests

    try:
        results = run_tests(file)

        # Display results
        from rich.table import Table

        table = Table(title="Test Results")
        table.add_column("Test", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Time", style="magenta")

        passed = 0
        failed_details = []
        for i, result in enumerate(results, 1):
            if result['passed']:
                table.add_row(f"Test {i}", "[green]✓ PASSED[/green]", f"{result['time']:.3f}s")
                passed += 1
            else:
                table.add_row(f"Test {i}", "[red]✗ FAILED[/red]", f"{result['time']:.3f}s")
                if result.get('error'):
                    failed_details.append((i, 'error', result['error']))
                elif result.get('expected') is not None:
                    failed_details.append((i, 'diff', result['expected'], result['actual']))

        console.print(table)

        # Show failure details after the table
        for detail in failed_details:
            if detail[1] == 'error':
                console.print(f"\n[bold]Test {detail[0]}:[/bold] [red]{detail[2]}[/red]")
            else:
                console.print(f"\n[bold]Test {detail[0]}:[/bold]")
                console.print(f"  [yellow]Expected:[/yellow]\n{detail[2]}")
                console.print(f"  [yellow]Got:[/yellow]\n{detail[3]}")
        console.print(f"\n[bold]Summary: {passed}/{len(results)} tests passed[/bold]")

        if passed < len(results):
            raise click.Abort()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("problem", nargs=-1, required=True)
@click.option("--lang", "-l", default=None, help="Programming language")
def submit(problem, lang):
    """
    Submit a solution to Codeforces.

    \b
    Examples:
        cf submit 1000A
        cf submit 1000 A
        cf submit 1000A solution.cpp
        cf submit 1000 A solution.cpp
    """
    from cf.submitter import submit_solution
    from cf.utils import find_solution_file
    from cf.watcher import watch_submission
    from pathlib import Path

    # Parse arguments: can be (problem,) or (problem, file) or (contest, problem) or (contest, problem, file)
    args = list(problem)
    file = None

    # Check if last argument looks like a file
    if len(args) >= 2 and '.' in args[-1]:
        file = args.pop()

    try:
        contest_id, problem_id = parse_problem_id(tuple(args))
    except click.BadParameter as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()

    # Auto-detect file if not provided
    if file is None:
        problem_dir = Path.cwd() / contest_id / problem_id
        if problem_dir.exists():
            detected = find_solution_file(problem_dir)
            if detected:
                file = str(detected)
        if file is None:
            # Try current directory
            detected = find_solution_file(Path.cwd())
            if detected:
                file = str(detected)

    if file is None:
        console.print("[red]Error: No solution file found. Please specify a file.[/red]")
        raise click.Abort()

    if not click.confirm(f"Submit {file} to problem {contest_id}/{problem_id}?"):
        console.print("[yellow]Submission cancelled[/yellow]")
        return

    try:
        with console.status("[bold green]Submitting solution..."):
            result = submit_solution(contest_id, problem_id, file, lang)

        console.print(f"[green]Submitted[/green]")
        console.print()

        # Watch submission status
        watch_submission(contest_id, problem_id, result['submission_id'])

    except Exception as e:
        console.print(f"[red]Submission failed: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("problem", nargs=-1, required=True)
@click.option("--lang", "-l", default=None, help="Programming language")
def gen(problem, lang):
    """
    Generate code file from template.

    \b
    Examples:
        cf gen 1000A
        cf gen 1000 A
    """
    from cf.template import generate_from_template
    from cf.config import Config

    try:
        contest_id, problem_id = parse_problem_id(problem)
    except click.BadParameter as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()

    if lang is None:
        cfg = Config()
        lang = cfg.get("default_language", "cpp")

    try:
        filepath = generate_from_template(contest_id, problem_id, lang)
        console.print(f"[green]Generated {filepath}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command("open")
@click.argument("problem", nargs=-1, required=True)
def open_problem(problem):
    """
    Open problem in web browser.

    \b
    Examples:
        cf open 1000A
        cf open 1000 A
    """
    import webbrowser
    from cf.constants import URL_PATTERNS

    try:
        contest_id, problem_id = parse_problem_id(problem)
    except click.BadParameter as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()

    url = URL_PATTERNS['contest'].format(cid=contest_id, pid=problem_id)
    webbrowser.open(url)
    console.print(f"[green]Opened {url}[/green]")


@cli.command()
@click.argument("contest_id")
@click.argument("submission_id")
def watch(contest_id, submission_id):
    """
    Watch submission status.

    \b
    Examples:
        cf watch 1000 12345678
    """
    from cf.watcher import watch_submission, get_submission_status

    # Try to get problem_id from submission
    submission = get_submission_status(contest_id, submission_id)
    if submission:
        problem = submission.get("problem", {})
        problem_id = problem.get("index", "?")
    else:
        problem_id = "?"

    console.print(f"[cyan]Watching submission {submission_id}...[/cyan]")
    console.print()

    watch_submission(contest_id, problem_id, submission_id)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
