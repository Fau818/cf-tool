"""cf test: run the built code on each test, compare what it prints with the
answer, and report.

Outputs are compared the way Codeforces' usual checker compares them: word
by word, so spaces and line breaks don't matter. What the statement allows
widens that (cf get saved it, see check_for): numbers within an error, any
letter case. --strict compares trimmed lines instead, and a checker program
(run as `checker input output answer`, testlib's order) decides by itself.
An interactive problem runs against an interactor (`interactor input
output`), whose exit code is the verdict.

The results are kept by the code's hash, so cf submit can tell when this
exact code failed its tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from cf_tool import paths, process, ui, views
from cf_tool.build import Program
from cf_tool.errors import CFError
from cf_tool.workspace import ProblemInfo, Test

DEFAULT_TIMEOUT = 10.0  # seconds a test may run when the time limit is unknown
CHECKER_TIMEOUT = 60.0  # seconds
RESULTS_KEPT = 200  # code versions whose results are remembered


def timeout_for(time_limit: float | None) -> float:
    """Seconds a test may run before it is stopped: a few times the limit."""
    if time_limit is None:
        return DEFAULT_TIMEOUT
    return max(3 * time_limit, time_limit + 2)  # NOTE: a slower machine than the judge's passes


# ┌──────────────────────────────────────────────────────────┐
# │                       Comparison                         │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Check:
    """How a test's output is compared with its answer."""

    epsilon: float | None = None  # numbers within this, absolute or relative
    ignore_case: bool = False
    strict: bool = False  # trimmed lines, not words
    checker: Program | None = None  # a built checker that decides instead

    def describe(self) -> str:
        """What this check accepts beyond the exact words of the answer; ""
        when nothing."""
        if self.checker is not None:
            return f"Judging with {self.checker.label}"
        allowed = []
        if self.strict:
            allowed.append("only the answer's exact lines")
        if self.epsilon is not None:
            allowed.append(f"numbers within {self.epsilon:g}")
        if self.ignore_case:
            allowed.append("any letter case")
        return "Accepting " + " and ".join(allowed) if allowed else ""


def check_for(
    info: ProblemInfo | None,
    *,
    epsilon: float | None = None,
    ignore_case: bool = False,
    strict: bool = False,
    exact: bool = False,
    checker: Program | None = None,
) -> Check:
    """How to compare: the options given win; unless exact, what the
    statement allows (saved by cf get) fills in the rest."""
    if checker is not None:
        return Check(checker=checker)
    if not exact and info is not None:
        epsilon = info.epsilon if epsilon is None else epsilon
        ignore_case = ignore_case or info.ignore_case
    return Check(epsilon=epsilon, ignore_case=ignore_case, strict=strict)


def trimmed(text: str) -> str:
    """Each line without its surrounding spaces, and no blank lines at the end."""
    return "".join(line.strip() + "\n" for line in text.rstrip().splitlines())


_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _words_match(got: str, want: str, epsilon: float) -> bool:
    """An output word against the answer's: numbers within epsilon, absolute
    or relative (as testlib checks them), anything else exactly."""
    if _NUMBER_RE.fullmatch(got) and _NUMBER_RE.fullmatch(want):
        return abs(float(got) - float(want)) <= epsilon * max(1.0, abs(float(want))) + 1e-15
    return got == want


def same_output(out: str, ans: str, check: Check) -> bool:
    """Whether out counts as ans:
    - strict: the same trimmed lines
    - with an epsilon: word by word, numbers within it
    - otherwise: the same words
    each in any letter case when allowed"""
    if check.ignore_case:
        out, ans = out.lower(), ans.lower()
    if check.strict:
        return trimmed(out) == trimmed(ans)
    got, want = out.split(), ans.split()
    if check.epsilon is None:
        return got == want
    return len(got) == len(want) and all(
        _words_match(g, w, check.epsilon) for g, w in zip(got, want)
    )


def _run_checker(checker: Program, test: Test, output: bytes) -> tuple[bool, str]:
    """The checker's verdict on output: (right, what it said)."""
    fd, out_name = tempfile.mkstemp(prefix="cf-output-", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(output)
        answer = str(test.answer) if test.answer is not None else os.devnull
        result = process.run(
            [*checker.argv(), str(test.input), out_name, answer],
            cwd=checker.source.parent,
            timeout=CHECKER_TIMEOUT,
        )
    finally:
        try:
            os.unlink(out_name)
        except OSError:
            pass
    said = (result.stderr or result.stdout).decode(errors="replace").strip()
    if result.status == process.TIMEOUT:
        return False, f"the checker ran over {CHECKER_TIMEOUT:g}s"
    return result.ok, said


# ┌──────────────────────────────────────────────────────────┐
# │                         Reports                          │
# └──────────────────────────────────────────────────────────┘


def format_memory(num_bytes: float) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{int(num_bytes)} B"


def _usage(result: process.Result, info: ProblemInfo | None) -> list[tuple[str, str]]:
    """Styled "  0.012s  3.1 MB" for a verdict line, flagged over a limit."""
    time_limit = info.time_limit if info else None
    memory_limit = info.memory_limit if info else None
    over_time = time_limit is not None and result.cpu > time_limit
    over_memory = memory_limit is not None and result.memory > memory_limit * 1024 * 1024
    parts = [("  ", ""), (f"{result.cpu:.3f}s", "yellow" if over_time else "dim")]
    if result.memory:
        parts += [("  ", ""), (format_memory(result.memory), "yellow" if over_memory else "dim")]
    if over_time:
        parts.append((f"  over the {time_limit:g}s limit", "yellow"))
    if over_memory:
        parts.append((f"  over the {memory_limit} MB limit", "yellow"))
    return parts


def _verdict(mark: str, style: str, test: Test, *rest: tuple[str, str]) -> None:
    ui.line((f"{mark} ", style), (test.name, "bold"), *rest)


def _show_failure(result: process.Result) -> None:
    """What a program printed before it failed: its output, and its last error line."""
    output = result.stdout.decode(errors="replace")
    if output.strip():
        ui.console.print(views.program_output(output))
    message = result.stderr.decode(errors="replace").strip()
    if message:
        ui.line(("stderr: ", "red"), (message.splitlines()[-1], ""))


# ┌──────────────────────────────────────────────────────────┐
# │                         Running                          │
# └──────────────────────────────────────────────────────────┘


def run_test(
    program: Program,
    test: Test,
    *,
    info: ProblemInfo | None = None,
    check: Check = Check(),
    accept: bool = False,
) -> bool | None:
    """Run one test and print its verdict; returns whether it passed, or None
    when it has no answer to pass:
    - output that counts as the answer: passed, with time and memory
    - running past its timeout: time limit exceeded
    - printing past the output limit: output limit exceeded
    - a crash or an exit code other than 0: runtime error, with what it printed
    - no answer: its output is shown (and kept as the answer with accept)
    - other output: wrong answer, with output and answer side by side"""
    timeout = timeout_for(info.time_limit if info else None)
    result = program.run(stdin=test.input, timeout=timeout)
    if result.status == process.TIMEOUT:
        _verdict("✗", "red", test, ("  time limit exceeded", "red"), (f" ({result.reason()})", ""))
        return False
    if result.status == process.OUTPUT:
        _verdict(
            "✗", "red", test, ("  output limit exceeded", "red"), (f" ({result.reason()})", "")
        )
        return False
    usage = _usage(result, info)
    if not result.ok:
        _verdict(
            "✗", "red", test, *usage, ("  runtime error", "red"), (f" ({result.reason()})", "")
        )
        _show_failure(result)
        return False
    output = result.stdout.decode(errors="replace")
    if test.answer is None:
        _verdict("•", "cyan", test, *usage, ("  no answer to compare with", "dim"))
        ui.console.print(views.program_output(output))
        if accept:
            answer = test.input.with_suffix(".ans")
            if test.input.name.startswith("in") and test.input.suffix == ".txt":
                answer = test.input.with_name(f"ans{test.name}.txt")  # NOTE: cf-tool 0.3's names
            answer.write_text(output, encoding="utf-8", newline="")
            ui.green(f"Kept the output as the answer: {answer.name}")
        return None
    answer_text = test.answer.read_text(encoding="utf-8", errors="replace")
    if check.checker is not None:
        passed, said = _run_checker(check.checker, test, result.stdout)
    else:
        passed, said = same_output(output, answer_text, check), ""
    if passed:
        note = [(f"  {said.splitlines()[0]}", "dim")] if said else []
        _verdict("✓", "green", test, *usage, *note)
        return True
    _verdict("✗", "red", test, *usage, ("  wrong answer", "red"))
    if said:
        ui.line(("checker: ", "red"), (said, ""))
    sample_input = test.input.read_text(encoding="utf-8", errors="replace")
    cases = info.sample_cases(test.name) if info else None
    if check.strict or check.checker is not None:
        out_lines, ans_lines = trimmed(output).splitlines(), trimmed(answer_text).splitlines()
    else:
        out_lines, ans_lines = output.strip().splitlines(), answer_text.strip().splitlines()
    ui.console.print(
        views.failed_sample(
            sample_input,
            out_lines,
            ans_lines,
            cases,
            lambda o, a: (
                same_output(o, a, check) if check.checker is None else o.strip() == a.strip()
            ),
        )
    )
    return False


INTERACTOR_VERDICTS = {1: "wrong answer", 2: "presentation error", 3: "the interactor failed"}


def run_interactive(
    program: Program, interactor: Program, test: Test, *, info: ProblemInfo | None = None
) -> bool:
    """Run one test of an interactive problem against the interactor and
    print the verdict; returns whether it passed. The interactor gets the
    test's input and answer files, and its exit code is the verdict."""
    timeout = timeout_for(info.time_limit if info else None)
    fd, out_name = tempfile.mkstemp(prefix="cf-interactor-", suffix=".txt")
    os.close(fd)
    try:
        extra = [str(test.input), out_name] + ([str(test.answer)] if test.answer else [])
        solution, judge = process.interact(
            program.argv(),
            [*interactor.argv(), *extra],
            cwd=interactor.source.parent,
            solution_cwd=program.source.parent,
            timeout=timeout,
            big_stack=program.setup.big_stack,
        )
    finally:
        try:
            os.unlink(out_name)
        except OSError:
            pass
    said = judge.stderr.decode(errors="replace").strip()
    usage = _usage(solution, info)
    if judge.status == process.TIMEOUT and solution.status == process.TIMEOUT:
        _verdict(
            "✗", "red", test, ("  time limit exceeded", "red"), (f" ({solution.reason()})", "")
        )
        return False
    if judge.status == process.TIMEOUT:
        _verdict("✗", "red", test, *usage, ("  the interactor waited for more", "red"))
        return False
    if not judge.ok:  # NOTE: its verdict comes first: it may be why the solution failed
        verdict = INTERACTOR_VERDICTS.get(judge.code or 0, f"the interactor's {judge.reason()}")
        _verdict("✗", "red", test, *usage, (f"  {verdict}", "red"))
        if said:
            ui.line(("interactor: ", "red"), (said, ""))
        return False
    if solution.status == process.TIMEOUT:
        _verdict("✗", "red", test, ("  didn't end after the interactor finished", "red"))
        return False
    if not solution.ok:
        _verdict(
            "✗", "red", test, *usage, ("  runtime error", "red"), (f" ({solution.reason()})", "")
        )
        _show_failure(solution)
        return False
    note = [(f"  {said.splitlines()[0]}", "dim")] if said else []
    _verdict("✓", "green", test, *usage, *note)
    return True


@dataclass
class Summary:
    passed: list[str]
    failed: list[str]
    ran: list[str]  # tests without an answer


def run_tests(
    program: Program,
    tests: Sequence[Test],
    *,
    info: ProblemInfo | None = None,
    check: Check = Check(),
    accept: bool = False,
    interactor: Program | None = None,
) -> Summary:
    """Run the tests one by one, then print how many passed; returns which
    passed and which didn't."""
    summary = Summary([], [], [])
    if check.describe():
        ui.line((check.describe(), "dim"))
    for test in tests:
        try:
            if interactor is not None:
                verdict: bool | None = run_interactive(program, interactor, test, info=info)
            else:
                verdict = run_test(program, test, info=info, check=check, accept=accept)
        except CFError as e:
            ui.red(f"{test.name}: {e}")
            verdict = False
        {True: summary.passed, False: summary.failed, None: summary.ran}[verdict].append(test.name)
    judged = len(summary.passed) + len(summary.failed)
    if judged:
        text = (
            f"All {judged} passed"
            if not summary.failed
            else f"{len(summary.passed)} of {judged} passed"
        )
        if summary.ran:
            text += f", {len(summary.ran)} without an answer"
        mark = ("✗ ", "red bold") if summary.failed else ("✓ ", "green bold")
        ui.line(mark, (text, "bold"))
    return summary


# ┌──────────────────────────────────────────────────────────┐
# │                Remembered results, watching              │
# └──────────────────────────────────────────────────────────┘


def _code_key(source: Path) -> str:
    return hashlib.sha256(source.read_bytes()).hexdigest()[:32]


def remember(source: Path, summary: Summary) -> None:
    """Keep how this exact code did on its tests (for cf submit's warning)."""
    path = paths.STATE_DIR / "results.json"
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(results, dict):
            results = {}
    except (OSError, ValueError):
        results = {}
    try:
        key = _code_key(source)
    except OSError:
        return
    results.pop(key, None)
    results[key] = {"failed": summary.failed, "passed": summary.passed, "when": time.time()}
    kept = dict(list(results.items())[-RESULTS_KEPT:])
    try:
        paths.write_atomic(path, json.dumps(kept) + "\n")
    except OSError:
        pass


def failed_tests(source: Path) -> list[str]:
    """The tests this exact code failed when last tested; [] when it passed
    them or wasn't tested."""
    try:
        results = json.loads((paths.STATE_DIR / "results.json").read_text(encoding="utf-8"))
        entry = results.get(_code_key(source)) or {}
        return [str(name) for name in entry.get("failed", [])]
    except (OSError, ValueError, AttributeError):
        return []


def watch(
    files: Callable[[], list[Path]], run_once: Callable[[], None], interval: float = 0.3
) -> None:
    """Run run_once now, and again each time one of files() changes, until
    Ctrl-C."""

    def stamps() -> list[tuple[str, int]]:
        found = []
        for path in files():
            try:
                found.append((str(path), path.stat().st_mtime_ns))
            except OSError:
                pass
        return found

    last = None
    try:
        while True:
            current = stamps()  # NOTE: taken before the run, so a save during it counts
            if current != last:
                if last is not None:
                    ui.line(("── changed: testing again ──", "dim"))
                last = current
                try:
                    run_once()
                except CFError as e:
                    ui.red(str(e))
                ui.line(("Watching for changes (Ctrl-C ends it)", "dim"))
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
