"""
CLI interface for cf-tool using Click.
"""

import click
from rich.console import Console

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="cf")
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
@click.argument("contest_id")
@click.argument("problem_id")
@click.option("--lang", "-l", default=None, help="Programming language (cpp, py)")
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym", "problemset", "group"]),
              help="Contest type")
def parse(contest_id, problem_id, lang, contest_type):
    """Parse a problem and download test cases."""
    from cf.parser import parse_problem
    from cf.config import Config

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
        for i, result in enumerate(results, 1):
            if result['passed']:
                table.add_row(f"Test {i}", "[green]✓ PASSED[/green]", f"{result['time']:.3f}s")
                passed += 1
            else:
                table.add_row(f"Test {i}", "[red]✗ FAILED[/red]", f"{result['time']:.3f}s")
                if result.get('error'):
                    console.print(f"  [red]Error: {result['error']}[/red]")
                elif result.get('diff'):
                    console.print(f"  [yellow]Expected:[/yellow]\n{result['expected']}")
                    console.print(f"  [yellow]Got:[/yellow]\n{result['actual']}")

        console.print(table)
        console.print(f"\n[bold]Summary: {passed}/{len(results)} tests passed[/bold]")

        if passed < len(results):
            raise click.Abort()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.argument("problem_id")
@click.argument("file")
@click.option("--lang", "-l", default=None, help="Programming language")
def submit(contest_id, problem_id, file, lang):
    """Submit a solution to Codeforces."""
    from cf.submitter import submit_solution

    if not click.confirm(f"Submit {file} to problem {contest_id}/{problem_id}?"):
        console.print("[yellow]Submission cancelled[/yellow]")
        return

    try:
        with console.status("[bold green]Submitting solution..."):
            result = submit_solution(contest_id, problem_id, file, lang)

        console.print(f"[green]Submission successful![/green]")
        console.print(f"  Submission ID: {result['submission_id']}")
        console.print(f"  URL: {result['url']}")
    except Exception as e:
        console.print(f"[red]Submission failed: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.argument("problem_id")
@click.option("--lang", "-l", default=None, help="Programming language")
def gen(contest_id, problem_id, lang):
    """Generate code file from template."""
    from cf.template import generate_from_template
    from cf.config import Config

    if lang is None:
        cfg = Config()
        lang = cfg.get("default_language", "cpp")

    try:
        filepath = generate_from_template(contest_id, problem_id, lang)
        console.print(f"[green]Generated {filepath}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.argument("problem_id")
def open(contest_id, problem_id):
    """Open problem in web browser."""
    import webbrowser
    from cf.constants import URL_PATTERNS

    url = URL_PATTERNS['contest'].format(cid=contest_id, pid=problem_id)
    webbrowser.open(url)
    console.print(f"[green]Opened {url}[/green]")


@cli.command()
@click.argument("submission_id")
def watch(submission_id):
    """Watch submission status."""
    console.print(f"[yellow]Watching submission {submission_id}...[/yellow]")
    console.print("[yellow]Note: This feature is not yet implemented[/yellow]")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
