"""
CLI interface for cf-tool using Click.
"""

import re

import click
from rich.console import Console

from cf import __version__

console = Console()


def parse_problem_id(args: tuple[str, ...]) -> tuple[str, str]:
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
    Parse a problem or entire contest and download test cases.

    \b
    Examples:
        cf parse 1000        # parse all problems in contest 1000
        cf parse 1000A       # parse problem A only
        cf parse 1000 A      # parse problem A only
    """
    from cf.parser import parse_problem, parse_contest
    from cf.config import Config

    if lang is None:
        cfg = Config()
        lang = cfg.get("default_language", "cpp")

    # Check if this is a contest-only parse (just a number, no problem letter)
    is_contest_parse = (
        len(problem) == 1 and problem[0].isdigit()
    )

    if is_contest_parse:
        contest_id = problem[0]
        try:
            with console.status(f"[bold green]Parsing contest {contest_id}..."):
                results = parse_contest(contest_id, lang, contest_type)

            console.print(f"[green]Successfully parsed {len(results)} problems from contest {contest_id}[/green]")
            for result in results:
                console.print(f"  {result['problem_id']}: {result['test_count']} test cases -> {result['directory']}")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise click.Abort()
    else:
        try:
            contest_id, problem_id = parse_problem_id(problem)
        except click.BadParameter as e:
            console.print(f"[red]Error: {e}[/red]")
            raise click.Abort()

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

        console.print("[green]Submitted[/green]")
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
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym", "problemset", "group"]),
              help="Contest type")
def open_problem(problem, contest_type):
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

    url = URL_PATTERNS[contest_type].format(cid=contest_id, pid=problem_id)
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


@cli.command("list")
@click.argument("contest_id")
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym"]),
              help="Contest type")
def list_problems(contest_id, contest_type):
    """
    List problems in a contest with statistics.

    \b
    Examples:
        cf list 1000
    """
    from rich.table import Table

    try:
        with console.status(f"[bold green]Fetching contest {contest_id}..."):
            from cf.scraper import CodeforceScraper

            scraper = CodeforceScraper()
            problems = scraper.fetch_contest_problems(contest_id, contest_type)

            # Also try to get solve counts from the API
            solve_counts = {}
            try:
                import cloudscraper
                client = cloudscraper.create_scraper()
                api_url = f"https://codeforces.com/api/contest.standings"
                params = {"contestId": contest_id, "from": 1, "count": 1}
                resp = client.get(api_url, params=params)
                data = resp.json()
                if data.get("status") == "OK":
                    for prob in data["result"].get("problems", []):
                        idx = prob.get("index", "")
                        solve_counts[idx] = prob.get("solvedCount", "")
            except Exception:
                pass

        table = Table(title=f"Contest {contest_id}")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Name", style="white")
        table.add_column("Solved", style="green", justify="right")

        for prob in problems:
            pid = prob["id"]
            name = prob["name"]
            solved = str(solve_counts.get(pid, "")) if solve_counts else ""
            table.add_row(pid, name, solved)

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym"]),
              help="Contest type")
def stand(contest_id, contest_type):
    """
    Open contest standings in browser.

    \b
    Examples:
        cf stand 1000
    """
    import webbrowser

    if contest_type == "gym":
        url = f"https://codeforces.com/gym/{contest_id}/standings"
    else:
        url = f"https://codeforces.com/contest/{contest_id}/standings"

    webbrowser.open(url)
    console.print(f"[green]Opened {url}[/green]")


@cli.command()
@click.argument("submission_id", required=False)
@click.option("--contest", "-c", "contest_id", default=None, help="Contest ID")
def sid(submission_id, contest_id):
    """
    Open submission page in browser.

    \b
    Examples:
        cf sid 12345678                  # open submission by ID
        cf sid --contest 1000            # open last submission in contest
    """
    import webbrowser

    if submission_id:
        url = f"https://codeforces.com/contest/{contest_id or '0'}/submission/{submission_id}"
        if not contest_id:
            # Try a generic submission URL
            url = f"https://codeforces.com/submission/{submission_id}"
        webbrowser.open(url)
        console.print(f"[green]Opened {url}[/green]")
    elif contest_id:
        url = f"https://codeforces.com/contest/{contest_id}/my"
        webbrowser.open(url)
        console.print(f"[green]Opened {url}[/green]")
    else:
        console.print("[red]Please provide a submission ID or --contest flag[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.option("--ac", "-a", is_flag=True, help="Only pull accepted solutions")
@click.option("--contest-type", "-t", default="contest",
              type=click.Choice(["contest", "gym"]),
              help="Contest type")
def pull(contest_id, ac, contest_type):
    """
    Pull your submissions from a contest.

    \b
    Examples:
        cf pull 1000         # pull all submissions
        cf pull 1000 --ac    # pull only accepted solutions
    """
    from cf.config import Config
    from cf.session import Session
    from pathlib import Path

    cfg = Config()
    handle = cfg.get("username")
    if not handle:
        console.print("[red]No username configured. Run 'cf config login' first.[/red]")
        raise click.Abort()

    try:
        with console.status(f"[bold green]Fetching submissions for {handle} in contest {contest_id}..."):
            import cloudscraper
            client = cloudscraper.create_scraper()
            api_url = "https://codeforces.com/api/contest.status"
            params = {
                "contestId": contest_id,
                "handle": handle,
                "from": 1,
                "count": 1000,
            }
            resp = client.get(api_url, params=params)
            data = resp.json()

            if data.get("status") != "OK":
                raise Exception(data.get("comment", "API request failed"))

            submissions = data.get("result", [])

        if not submissions:
            console.print("[yellow]No submissions found[/yellow]")
            return

        if ac:
            submissions = [s for s in submissions if s.get("verdict") == "OK"]
            if not submissions:
                console.print("[yellow]No accepted submissions found[/yellow]")
                return

        # Group by problem, keep best/latest per problem
        best = {}
        for sub in submissions:
            prob = sub.get("problem", {})
            idx = prob.get("index", "?")
            if idx not in best:
                best[idx] = sub
            elif sub.get("verdict") == "OK" and best[idx].get("verdict") != "OK":
                best[idx] = sub

        # Download source code for each
        session = Session()
        saved = 0
        for idx, sub in sorted(best.items()):
            sub_id = sub["id"]
            prob = sub.get("problem", {})
            prob_name = prob.get("name", idx)
            lang = sub.get("programmingLanguage", "unknown")

            # Determine file extension from language name
            ext = _lang_to_ext(lang)
            problem_dir = Path.cwd() / contest_id / idx
            problem_dir.mkdir(parents=True, exist_ok=True)
            filepath = problem_dir / f"solution{ext}"

            try:
                # Fetch source code from submission page
                sub_url = f"https://codeforces.com/contest/{contest_id}/submission/{sub_id}"
                resp = session.get(sub_url)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'lxml')
                source_elem = soup.find('pre', id='program-source-text')
                if source_elem:
                    filepath.write_text(source_elem.get_text())
                    verdict_str = "AC" if sub.get("verdict") == "OK" else sub.get("verdict", "?")
                    console.print(f"  [green]{idx}[/green] ({verdict_str}) -> {filepath}")
                    saved += 1
            except Exception as e:
                console.print(f"  [red]{idx}: Failed to download: {e}[/red]")

        console.print(f"\n[bold]Saved {saved} solution(s) to {contest_id}/[/bold]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("handle")
@click.option("--ac", "-a", is_flag=True, help="Only clone accepted solutions")
@click.option("--count", "-n", default=100, help="Number of submissions to fetch")
def clone(handle, ac, count):
    """
    Clone a user's recent submissions.

    \b
    Examples:
        cf clone tourist         # clone recent submissions
        cf clone tourist --ac    # clone accepted only
    """
    from pathlib import Path

    try:
        with console.status(f"[bold green]Fetching submissions for {handle}..."):
            import cloudscraper
            client = cloudscraper.create_scraper()
            api_url = "https://codeforces.com/api/user.status"
            params = {
                "handle": handle,
                "from": 1,
                "count": count,
            }
            resp = client.get(api_url, params=params)
            data = resp.json()

            if data.get("status") != "OK":
                raise Exception(data.get("comment", "API request failed"))

            submissions = data.get("result", [])

        if not submissions:
            console.print("[yellow]No submissions found[/yellow]")
            return

        if ac:
            submissions = [s for s in submissions if s.get("verdict") == "OK"]
            if not submissions:
                console.print("[yellow]No accepted submissions found[/yellow]")
                return

        # Group by contest+problem, keep latest per problem
        best = {}
        for sub in submissions:
            prob = sub.get("problem", {})
            cid = str(prob.get("contestId", "unknown"))
            idx = prob.get("index", "?")
            key = f"{cid}/{idx}"
            if key not in best:
                best[key] = sub
            elif sub.get("verdict") == "OK" and best[key].get("verdict") != "OK":
                best[key] = sub

        console.print(f"[cyan]Found {len(best)} unique problems[/cyan]")

        # Save solutions (source not available via API, just create stubs with metadata)
        saved = 0
        for key, sub in sorted(best.items()):
            prob = sub.get("problem", {})
            cid = str(prob.get("contestId", "unknown"))
            idx = prob.get("index", "?")
            lang = sub.get("programmingLanguage", "unknown")
            ext = _lang_to_ext(lang)

            problem_dir = Path.cwd() / handle / cid / idx
            problem_dir.mkdir(parents=True, exist_ok=True)

            info_file = problem_dir / "submission.json"
            import json
            info = {
                "id": sub.get("id"),
                "contestId": cid,
                "problem": idx,
                "name": prob.get("name", ""),
                "verdict": sub.get("verdict", ""),
                "language": lang,
                "time_ms": sub.get("timeConsumedMillis", 0),
                "memory_bytes": sub.get("memoryConsumedBytes", 0),
            }
            info_file.write_text(json.dumps(info, indent=2))
            saved += 1

        console.print(f"\n[bold]Saved metadata for {saved} submission(s) to {handle}/[/bold]")
        console.print("[dim]Note: Source code requires authenticated session. Use 'cf pull' for your own solutions.[/dim]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument("contest_id")
@click.option("--lang", "-l", default=None, help="Programming language")
def race(contest_id, lang):
    """
    Register for a contest, open problem pages, and auto-parse when it starts.

    \b
    Examples:
        cf race 1000
    """
    import webbrowser
    import time as time_mod
    from cf.config import Config
    from cf.session import Session

    if lang is None:
        cfg = Config()
        lang = cfg.get("default_language", "cpp")

    # Open contest page in browser
    contest_url = f"https://codeforces.com/contest/{contest_id}"
    webbrowser.open(contest_url)
    console.print(f"[cyan]Opened contest page: {contest_url}[/cyan]")

    # Try to register via API
    try:
        session = Session()
        if session.is_authenticated():
            reg_url = f"https://codeforces.com/contestRegistration/{contest_id}"
            webbrowser.open(reg_url)
            console.print("[cyan]Opened registration page[/cyan]")
        else:
            console.print("[yellow]Not logged in. Please register manually.[/yellow]")
    except Exception:
        console.print("[yellow]Could not open registration. Please register manually.[/yellow]")

    # Check if contest has started, if so parse immediately
    try:
        import cloudscraper
        client = cloudscraper.create_scraper()
        resp = client.get(f"https://codeforces.com/api/contest.list", params={"gym": "false"})
        data = resp.json()
        if data.get("status") == "OK":
            for c in data["result"]:
                if str(c.get("id")) == str(contest_id):
                    phase = c.get("phase", "")
                    if phase == "CODING":
                        console.print("[green]Contest is running! Parsing problems...[/green]")
                        from cf.parser import parse_contest
                        results = parse_contest(contest_id, lang)
                        console.print(f"[green]Parsed {len(results)} problems[/green]")
                        for r in results:
                            console.print(f"  {r['problem_id']}: {r['test_count']} tests")
                        return
                    elif phase == "BEFORE":
                        start_time = c.get("startTimeSeconds", 0)
                        now = int(time_mod.time())
                        remaining = start_time - now
                        if remaining > 0:
                            mins = remaining // 60
                            console.print(f"[yellow]Contest starts in {mins} minutes.[/yellow]")
                            console.print("[cyan]Waiting for contest to start... (Ctrl+C to cancel)[/cyan]")
                            try:
                                while int(time_mod.time()) < start_time:
                                    left = start_time - int(time_mod.time())
                                    m, s = divmod(left, 60)
                                    console.print(f"\r  [dim]{m:02d}:{s:02d} remaining[/dim]", end="")
                                    time_mod.sleep(1)
                                console.print("\n[green]Contest started! Parsing problems...[/green]")
                                time_mod.sleep(2)  # brief delay for problems to appear
                                from cf.parser import parse_contest
                                results = parse_contest(contest_id, lang)
                                console.print(f"[green]Parsed {len(results)} problems[/green]")
                                for r in results:
                                    console.print(f"  {r['problem_id']}: {r['test_count']} tests")
                            except KeyboardInterrupt:
                                console.print("\n[yellow]Cancelled waiting[/yellow]")
                        return
                    else:
                        console.print(f"[yellow]Contest phase: {phase}[/yellow]")
                        return
        console.print("[yellow]Could not find contest info. Parse manually when ready.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Could not check contest status: {e}[/yellow]")


def _lang_to_ext(lang_name: str) -> str:
    """Map Codeforces language name to file extension."""
    lang_lower = lang_name.lower()
    if "c++" in lang_lower or "g++" in lang_lower:
        return ".cpp"
    elif "python" in lang_lower or "pypy" in lang_lower:
        return ".py"
    elif "java" in lang_lower:
        return ".java"
    elif "kotlin" in lang_lower:
        return ".kt"
    elif "rust" in lang_lower:
        return ".rs"
    elif "go" in lang_lower:
        return ".go"
    elif "c#" in lang_lower:
        return ".cs"
    elif lang_lower.startswith("gnu c") or lang_lower.startswith("gcc"):
        return ".c"
    return ".txt"


@cli.command()
def upgrade():
    """Check for updates and show upgrade instructions."""
    from cf import __version__

    try:
        with console.status("[bold green]Checking for updates..."):
            import cloudscraper
            client = cloudscraper.create_scraper()
            resp = client.get("https://pypi.org/pypi/cf-tool/json", timeout=10)
            data = resp.json()
            latest = data["info"]["version"]

        if latest == __version__:
            console.print(f"[green]Already up to date (v{__version__})[/green]")
        else:
            console.print(f"[yellow]New version available: v{latest} (current: v{__version__})[/yellow]")
            console.print("  Run: [bold]pip install --upgrade cf-tool[/bold]")
    except Exception:
        console.print(f"[yellow]Could not check for updates. Current version: v{__version__}[/yellow]")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
