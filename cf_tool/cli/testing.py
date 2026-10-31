"""Commands that run your code: test and stress."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from cf_tool import judge, languages, process, stress as stress_module, ui, workspace
from cf_tool.build import Program
from cf_tool.cli.common import (
    build,
    cf_command,
    program,
    settings,
    short,
    target_of,
)
from cf_tool.cli.completion import complete_tests
from cf_tool.errors import CFError
from cf_tool.languages import Setup


def _comparison_options(command):
    """The options saying how output is compared with answers (cf test, cf stress)."""
    options = [
        click.option(
            "-e",
            "--epsilon",
            type=float,
            help="Accept numbers within this absolute or relative error.",
        ),
        click.option(
            "-i", "--ignore-case", is_flag=True, help="Accept answers in any letter case."
        ),
        click.option("--strict", is_flag=True, help="Compare trimmed lines, not just the words."),
        click.option("--exact", is_flag=True, help="Ignore what the statement allows."),
        click.option(
            "--checker",
            metavar="FILE|CMD",
            default="",
            help="Judge with a program, run as: CMD input output answer (exit 0: right).",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def helper(folder: Path, kind: str) -> Path | None:
    """The problem's helper of a kind (gen, brute, checker, interactor) in
    folder: gen.py, gen2.py, check_a.py; the newest when there are several."""
    known = languages.code_extensions(settings())
    found = [
        entry
        for entry in folder.glob("*.*")
        if entry.suffix.lower() in known
        and workspace.helper_kind(entry.name) == kind
        and entry.is_file()
    ]
    return max(found, key=lambda entry: entry.stat().st_mtime) if found else None


def _named_files(*specs: str) -> list[str]:
    """The files that FILE|CMD options name (python3 check_a.py -> check_a.py):
    they are helpers, never the code to test."""
    named = []
    for spec in filter(None, specs):
        words = [spec] if Path(spec).is_file() else process.split_command(spec)
        named += [str(Path(word).resolve()) for word in words if Path(word).is_file()]
    return named


def _program_or_command(spec: str, folder: Path) -> Program:
    """A code file (built like any other), or a command line to run as it is."""
    path = Path(spec)
    if path.is_file() and languages.language_key(path, settings()) is not None:
        return program(path.resolve())
    words = process.split_command(spec)
    if not words:
        raise CFError(f"Nothing to run in {spec!r}")
    # NOTE: it runs in the problem's folder (a program's own), even when the
    # \     command starts with a path to elsewhere (/usr/bin/python3 check.py)
    source = folder / Path(words[0]).name
    return Program(source, Setup("command", words[0], spec, None, tuple(words)))


def _checker(spec: str, folder: Path | None) -> Program | None:
    """The checker to judge with: the one given, else checker.* in the problem's folder."""
    if spec:
        return _program_or_command(spec, folder or Path.cwd())
    found = helper(folder, "checker") if folder else None
    return program(found) if found else None


def _problem_and_tests(args: tuple[str, ...]) -> tuple[Path, str | None, list[str]]:
    """(the problem's folder, the code file named, the tests named) from cf
    test's arguments, which may name a code file, a problem, and tests."""
    cwd = Path.cwd()
    known = languages.code_extensions(settings())
    files = [a for a in args if Path(a).suffix.lower() in known and Path(a).is_file()]
    if len(files) > 1:
        raise CFError(f"One code file at a time, not {' and '.join(files)}")
    file = files[0] if files else None
    here = workspace.find_problem_folder(Path(file).resolve().parent if file else cwd)
    here_tests = {t.name for t in workspace.tests_of(here)} if here else set()
    specs, names = [], []
    for arg in args:
        if arg == file:
            continue
        if arg in here_tests or arg.isdigit():
            names.append(arg)
        else:
            specs.append(arg)
    if specs:
        target = target_of(specs)
        folder = workspace.locate(target, cwd, settings().root_folder())
        if folder is None:
            raise CFError(f"No folder for {target.label} here: cf get {target.label} sets one up")
    elif here is not None:
        folder = here
    elif workspace.tests_of(cwd):
        folder = cwd  # NOTE: tests without cf-tool's metadata, cf-tool 0.3's folders
    else:
        raise CFError(
            "Not in a problem's folder: cd into one made by cf get, or name the problem "
            "(cf test 2050b)"
        )
    return folder, file, names


def _read_until_end() -> str:
    return sys.stdin.read()


def _add_test(folder: Path) -> workspace.Test:
    """Type in a new test, its input, then its answer (none: only run it)."""
    end = "Ctrl-Z, then Enter" if sys.platform == "win32" else "Ctrl-D"
    ui.cyan(f"The new test's input (end it with {end} on an empty line):")
    input_text = _read_until_end()
    if not input_text.strip():
        raise CFError("No input: no test added")
    ui.cyan(f"Its answer (end it with {end}; none: only run it):")
    test = workspace.add_test(folder, input_text, _read_until_end())
    saved = f"{test.input.name}" + (f" and {test.answer.name}" if test.answer else "")
    ui.green(f"Added the test {test.name}: tests/{saved}")
    return test


@click.command()
@click.argument("args", nargs=-1, metavar="[PROBLEM|FILE] [TEST]...", shell_complete=complete_tests)
@click.option("-w", "--watch", "watch_it", is_flag=True, help="Test again whenever you save.")
@_comparison_options
@click.option("--interactor", metavar="FILE|CMD", default="", help="For an interactive problem.")
@click.option("--add", "add_one", is_flag=True, help="Type in a new test, then run it.")
@click.option(
    "--accept", is_flag=True, help="Keep the output of tests without an answer as theirs."
)
@cf_command
def test(
    args: tuple[str, ...],
    watch_it: bool,
    epsilon: float | None,
    ignore_case: bool,
    strict: bool,
    exact: bool,
    checker: str,
    interactor: str,
    add_one: bool,
    accept: bool,
) -> None:
    """Build your code and run it on the problem's tests.

    \b
    cf test           every test of the problem here
    cf test 2 my      the tests 2 and my
    cf test b         problem b of this contest
    cf test a.cpp     with this code file
    cf test -w        again whenever you save
    The statement's rules (numbers within an error, any letter case) apply
    on their own; the options change them.
    """
    folder, file, names = _problem_and_tests(args)
    info = workspace.load_info(folder)
    target = (info.target if info else None) or workspace.here(folder) or workspace.Target()
    if add_one:
        names = [_add_test(folder).name]
    found = workspace.tests_of(folder)
    if not found:
        raise CFError(
            f"{short(folder)} has no tests: cf get downloads the samples, cf test --add adds one"
        )
    unknown = [name for name in names if name not in {t.name for t in found}]
    if unknown:
        listed = ", ".join(t.name for t in found)
        raise CFError(f"No test {', '.join(unknown)} here (there are {listed})")
    tests = [t for t in found if t.name in names] if names else found
    chosen = {t.name for t in tests}

    interactor_program = None
    spec = interactor or str(helper(folder, "interactor") or "")
    if spec:
        interactor_program = _program_or_command(spec, folder)
    elif info and info.interactive:
        raise CFError(
            "This problem is interactive: cf test runs it against an interactor. Write one "
            "as interactor.cpp (any language) in its folder, or name one with --interactor"
        )

    if file:
        name, key = file, languages.language_key(file, settings())
        path = Path(file).resolve()
    else:
        name, key = workspace.pick_code(
            None,
            folder,
            settings(),
            contest=target.contest,
            problem=target.problem,
            action="test",
            exclude=_named_files(checker, interactor),
        )
        path = (folder / name).resolve()
    solution = program(path, key)
    check_program = _checker(checker, folder)

    def run_once() -> None:
        build(solution)
        for extra in (interactor_program, check_program):
            if extra is not None:
                build(extra)
        check = judge.check_for(
            info,
            epsilon=epsilon,
            ignore_case=ignore_case,
            strict=strict,
            exact=exact,
            checker=check_program,
        )
        current = [
            t for t in workspace.tests_of(folder) if t.name in chosen
        ]  # NOTE: read again: --accept may have given answers
        summary = judge.run_tests(
            solution, current, info=info, check=check, accept=accept, interactor=interactor_program
        )
        judge.remember(path, summary)
        # NOTE: an output unlike the sample's isn't confirmed right either
        if (summary.failed or summary.differs) and not watch_it:
            sys.exit(1)

    if not watch_it:
        run_once()
        return

    def watched() -> list[Path]:
        files = [path, *(t.input for t in tests), *(t.answer for t in tests if t.answer)]
        for extra in (interactor_program, check_program):
            if extra is not None:
                files.append(extra.source)
        return files

    judge.watch(watched, run_once)


@click.command()
@click.argument("generator", required=False, type=click.Path(exists=True, dir_okay=False))
@click.argument("brute", required=False, type=click.Path(exists=True, dir_okay=False))
@click.argument("solution", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("-n", "--tests", default=1000, show_default=True, help="Stop after this many tests.")
@click.option("--seed", default=1, show_default=True, help="The first test's seed (then +1).")
@_comparison_options
@cf_command
def stress(
    generator: str | None,
    brute: str | None,
    solution: str | None,
    tests: int,
    seed: int,
    epsilon: float | None,
    ignore_case: bool,
    strict: bool,
    exact: bool,
    checker: str,
) -> None:
    """Random tests until your solution and a brute force disagree; that
    test is saved among the problem's tests.

    \b
    GENERATOR prints one test for the seed it gets as its argument; BRUTE's
    output is the answer. They default to gen.* and brute.* in the problem's
    folder, the solution to your code there (any language for all three).
    """
    cwd = Path.cwd()
    folder = workspace.find_problem_folder(cwd) or cwd
    info = workspace.load_info(folder)
    target = (info.target if info else None) or workspace.here(folder) or workspace.Target()
    gen_path = Path(generator).resolve() if generator else helper(folder, "gen")
    brute_path = Path(brute).resolve() if brute else helper(folder, "brute")
    if gen_path is None:
        raise CFError("No generator: write gen.py (cf new gen.py) or another gen.*, or name one")
    if brute_path is None:
        raise CFError(
            "No brute force: write brute.cpp (cf new brute) or another brute.*, or name one"
        )
    if solution:
        solution_path = Path(solution).resolve()
    else:
        name, _ = workspace.pick_code(
            None,
            folder,
            settings(),
            contest=target.contest,
            problem=target.problem,
            action="stress test",
            exclude=(str(gen_path), str(brute_path), *_named_files(checker)),
        )
        solution_path = (folder / name).resolve()
    programs = [program(gen_path), program(brute_path), program(solution_path)]
    check_program = _checker(checker, folder)
    for each in [*programs, *([check_program] if check_program else [])]:
        build(each)
    check = judge.check_for(
        info,
        epsilon=epsilon,
        ignore_case=ignore_case,
        strict=strict,
        exact=exact,
        checker=check_program,
    )
    if check.any_answer:
        ui.yellow(
            "This problem accepts any right answer, so your output and the brute force's "
            "may differ and both be right: judge with a checker (check*.py or --checker)"
        )
    failed = stress_module.stress(
        folder,
        *programs,
        tests=tests,
        seed=seed,
        check=check,
        time_limit=info.time_limit if info else None,
    )
    if failed is not None:
        sys.exit(1)


COMMANDS = [test, stress]
