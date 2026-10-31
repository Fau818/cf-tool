"""`cf stress`: random tests until the solution and a brute force disagree.

A generator prints one test for the seed it gets as its argument, and the
brute force's output is that test's answer. The first test the solution
fails is saved as the next sample, so `cf test` keeps checking it. All three
are built and run by their templates' scripts, whatever their language."""

from __future__ import annotations

import contextlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from cf_tool import judge, templates, ui, views
from cf_tool.config import CodeTemplate
from cf_tool.errors import CFError
from cf_tool.judge import Check, same_output

GENERATOR_TIMEOUT = 10.0  # seconds
BRUTE_TIMEOUT = 60.0  # seconds: a brute force may be slow, just not stuck


@dataclass
class Program:
    """A code file and the template that builds and runs it."""

    filename: str
    template: CodeTemplate
    subs: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.subs = templates.script_substitutions(self.filename)  # NOTE: one $%rand%$ for all runs

    def build(self, cwd: Path) -> None:
        judge.run_script(templates.substitute_script(self.template.before_script, **self.subs), cwd)

    def clean(self, cwd: Path) -> None:
        judge.run_script(templates.substitute_script(self.template.after_script, **self.subs), cwd)

    def argv(self) -> list[str]:
        """The words that run it."""
        words = judge.split_cmd(templates.substitute_script(self.template.script, **self.subs))
        if not words:
            raise CFError(f"Nothing runs {self.filename}: its template's script is empty")
        return words


def _run(argv: list[str], stdin: bytes, cwd: Path, timeout: float) -> tuple[str, bytes, bytes]:
    """Run once; returns (how it ended: "ok", "crash" or "timeout", stdout, stderr)."""
    try:
        done = subprocess.run(argv, input=stdin, cwd=cwd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return "timeout", e.stdout or b"", e.stderr or b""
    except OSError as e:
        raise CFError(f"Cannot run {argv[0]!r}: {e.strerror or e}") from e
    return ("ok" if done.returncode == 0 else "crash"), done.stdout, done.stderr


def _accepted(test: bytes, got: bytes, want: bytes, check: Check, cwd: Path) -> tuple[bool, str]:
    """Whether the solution's output counts as the brute force's: (yes, what a checker said)."""
    if not check.checker:
        out, ans = (judge.plain(data.decode(errors="replace")) for data in (got, want))
        return same_output(out, ans, check), ""
    with tempfile.TemporaryDirectory(prefix="cf-stress-") as folder:
        in_path, ans_path = Path(folder) / "input.txt", Path(folder) / "answer.txt"
        in_path.write_bytes(test)
        ans_path.write_bytes(want)
        return judge._run_checker(check.checker, in_path, got, ans_path, cwd)


def _failed_on(test: bytes, what: str, outcome: str, out: bytes, err: bytes) -> CFError:
    """The error for a generator or brute force that didn't produce a test or
    its answer, with the test it was given (if any) shown first."""
    if test:
        ui.console.print(views.program_output(test.decode(errors="replace"), "Input"))
    said = (err or out).decode(errors="replace").strip()
    ended = {"crash": "crashed", "timeout": "ran too long"}[outcome]
    return CFError(f"The {what} {ended}" + (f": {said.splitlines()[-1]}" if said else ""))


def stress(
    cwd: Path,
    generator: Program,
    brute: Program,
    solution: Program,
    *,
    tests: int = 1000,
    seed: int = 1,
    check: Check = Check(),
    time_limit: float | None = None,
) -> str | None:
    """Run up to tests random tests; returns the id of the sample saved for
    the first one the solution fails (wrong answer, crash or timeout), or
    None when it passed them all. Steps:
    - build the three programs
    - per test: generate it from its seed, answer it with the brute force,
      run the solution, compare
    - clean up the three builds"""
    programs = (generator, brute, solution)
    for program in programs:
        program.build(cwd)
    timeout = judge.timeout_for(time_limit)
    try:
        with ui.status("Stress testing...") as show:
            for test_seed in range(seed, seed + tests):
                show(f"Test {test_seed - seed + 1} of {tests} (seed {test_seed})...")
                argv = generator.argv() + [str(test_seed)]
                outcome, test, err = _run(argv, b"", cwd, GENERATOR_TIMEOUT)
                if outcome != "ok":
                    raise _failed_on(b"", f"generator (seed {test_seed})", outcome, test, err)
                outcome, want, err = _run(brute.argv(), test, cwd, BRUTE_TIMEOUT)
                if outcome != "ok":
                    raise _failed_on(test, f"brute force (seed {test_seed})", outcome, want, err)
                outcome, got, err = _run(solution.argv(), test, cwd, timeout)
                said = ""
                if outcome == "ok":
                    passed, said = _accepted(test, got, want, check, cwd)
                    if passed:
                        continue
                return _report(cwd, test_seed, test, got, want, err, outcome, said, check, timeout)
    finally:
        for program in programs:
            with contextlib.suppress(CFError):  # NOTE: a cleanup failure mustn't hide the result
                program.clean(cwd)
    ui.green(f"All {tests} tests passed (seeds {seed} to {seed + tests - 1})")
    return None


def _report(
    cwd: Path,
    test_seed: int,
    test: bytes,
    got: bytes,
    want: bytes,
    err: bytes,
    outcome: str,
    said: str,
    check: Check,
    timeout: float,
) -> str:
    """Save the failing test as the next sample and show what went wrong;
    returns the sample's id."""
    test_text, want_text = test.decode(errors="replace"), want.decode(errors="replace")
    sample_id = judge.add_sample(cwd, test_text, want_text)
    verdict = {
        "ok": "Wrong answer",
        "crash": "Runtime Error",
        "timeout": f"Time limit exceeded (killed after {timeout:g}s)",
    }[outcome]
    ui.red(f"{verdict} on the test from seed {test_seed}")
    ui.green(f"Saved it as sample {sample_id}: cf test {sample_id} runs it again")
    if said:
        ui.line(("Checker: ", "red"), (said, ""))
    if outcome == "ok":
        out, ans = (judge.plain(text) for text in (got.decode(errors="replace"), want_text))
        alike = (
            (lambda o, a: same_output(o, a, check)) if not check.checker else (lambda o, a: o == a)
        )
        ui.console.print(
            views.failed_sample(test_text, out.splitlines(), ans.splitlines(), same=alike)
        )
    else:
        message = (err or b"").decode(errors="replace").strip()
        ui.console.print(views.program_output(test_text, "Input"))
        if message:
            ui.line(("stderr: ", "red"), (message.splitlines()[-1], ""))
    return sample_id
