"""cf stress: random tests until the solution and a brute force disagree.

A generator prints one test for the seed it gets as its argument, and the
brute force's output is that test's answer. The first test the solution
fails is saved among the problem's tests (tests/stress-<seed>), so cf test
keeps checking it. All three are built and run like any code file, in any
language cf-tool knows.
"""

from __future__ import annotations

from pathlib import Path

from cf_tool import judge, process, ui, views, workspace
from cf_tool.build import Program
from cf_tool.errors import CFError
from cf_tool.judge import Check, same_output

GENERATOR_TIMEOUT = 10.0  # seconds
BRUTE_TIMEOUT = 60.0  # seconds: a brute force may be slow, just not stuck


def _failed_on(test: bytes, what: str, result: process.Result) -> CFError:
    """The error for a generator or brute force that didn't produce a test or
    its answer, with the test it was given (if any) shown first."""
    if test:
        ui.console.print(views.program_output(test.decode(errors="replace"), "Input"))
    said = (result.stderr or result.stdout).decode(errors="replace").strip()
    return CFError(
        f"The {what} failed ({result.reason()})" + (f": {said.splitlines()[-1]}" if said else "")
    )


def _accepted(test: bytes, got: bytes, want: bytes, check: Check, folder: Path) -> tuple[bool, str]:
    """Whether the solution's output counts as the brute force's: (yes, what a checker said)."""
    if check.checker is None:
        out, ans = (data.decode(errors="replace") for data in (got, want))
        return same_output(out, ans, check), ""
    scratch = workspace.Test("stress", folder / ".cf-stress.in", folder / ".cf-stress.ans")
    try:
        scratch.input.write_bytes(test)
        scratch.answer.write_bytes(want)  # type: ignore[union-attr]
        return judge._run_checker(check.checker, scratch, got)
    finally:
        for path in (scratch.input, scratch.answer):
            try:
                path.unlink()  # type: ignore[union-attr]
            except OSError:
                pass


def stress(
    folder: Path,
    generator: Program,
    brute: Program,
    solution: Program,
    *,
    tests: int = 1000,
    seed: int = 1,
    check: Check = Check(),
    time_limit: float | None = None,
) -> workspace.Test | None:
    """Run up to `tests` random tests (all three programs built already);
    returns the test saved for the first one the solution fails (wrong
    answer, crash or time limit), or None when it passed them all. Per test:
    - the generator prints it, from its seed
    - the brute force answers it
    - the solution runs on it, and its output is compared with that answer"""
    timeout = judge.timeout_for(time_limit)
    with ui.status("Stress testing...") as show:
        for test_seed in range(seed, seed + tests):
            show(f"Test {test_seed - seed + 1} of {tests} (seed {test_seed})...")
            made = process.run(
                [*generator.argv(), str(test_seed)],
                cwd=generator.source.parent,
                timeout=GENERATOR_TIMEOUT,
            )
            if not made.ok:
                raise _failed_on(b"", f"generator (seed {test_seed})", made)
            answer = brute.run(stdin=made.stdout, timeout=BRUTE_TIMEOUT)
            if not answer.ok:
                raise _failed_on(made.stdout, f"brute force (seed {test_seed})", answer)
            result = solution.run(stdin=made.stdout, timeout=timeout)
            said = ""
            if result.ok:
                passed, said = _accepted(made.stdout, result.stdout, answer.stdout, check, folder)
                if passed:
                    continue
            return _report(folder, test_seed, made.stdout, result, answer.stdout, said, check)
    ui.green(f"All {tests} tests passed (seeds {seed} to {seed + tests - 1})")
    return None


def _report(
    folder: Path,
    test_seed: int,
    test: bytes,
    result: process.Result,
    want: bytes,
    said: str,
    check: Check,
) -> workspace.Test:
    """Save the failing test among the problem's tests and show what went
    wrong; returns the saved test."""
    test_text, want_text = test.decode(errors="replace"), want.decode(errors="replace")
    saved = workspace.add_test(folder, test_text, want_text, name=f"stress-{test_seed}")
    verdict = {
        process.OK: "Wrong answer",
        process.TIMEOUT: "Time limit exceeded",
        process.OUTPUT: "Output limit exceeded",
    }.get(result.status, "Runtime error")
    detail = "" if result.ok else f" ({result.reason()})"
    ui.red(f"{verdict}{detail} on the test from seed {test_seed}")
    ui.green(f"Saved it as the test {saved.name}: cf test {saved.name} runs it again")
    if said:
        ui.line(("checker: ", "red"), (said, ""))
    if result.ok:
        output = result.stdout.decode(errors="replace")
        ui.console.print(
            views.failed_sample(
                test_text,
                output.strip().splitlines(),
                want_text.strip().splitlines(),
                same=lambda o, a: same_output(o, a, check),
            )
        )
    else:
        ui.console.print(views.program_output(test_text, "Input"))
        message = result.stderr.decode(errors="replace").strip()
        if message:
            ui.line(("stderr: ", "red"), (message.splitlines()[-1], ""))
    return saved
