"""Local testing (`cf test`): run before_script / script / after_script,
feed in{i}.txt, compare with ans{i}.txt. Port of cmd/test.go.

As in the original: outputs are compared after trimming each line, the time
shown is the program's user CPU time (wall time where the OS can't report
it), and scripts are split into words by the Go tool's own rules, so a
config shared with the Go tool runs identically. Unlike it, a sample that
runs a few times past the problem's time limit is killed (the limit comes
from `cf parse`, see problem.py).
"""

from __future__ import annotations

import contextlib
import operator
import os
import re
import signal
import subprocess
import threading
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import psutil

from cf_tool import codefiles, templates, ui, views
from cf_tool.config import NO_TEMPLATE, Config
from cf_tool.errors import CFError
from cf_tool.problem import ProblemInfo

try:
    import resource
except ImportError:  # Windows
    resource = None

_IN_FILE_RE = re.compile(r"^in(\d+)\.txt$")


def get_sample_ids(cwd: Path) -> list[str]:
    """Ids of the samples here, numerically sorted: every in{i}.txt, with or
    without its ans{i}.txt."""
    ids = [match.group(1) for entry in cwd.iterdir() if (match := _IN_FILE_RE.match(entry.name))]
    return sorted(ids, key=int)


def add_sample(cwd: Path, input_text: str, answer: str) -> str:
    """Save a new sample as the next in{i}.txt (and ans{i}.txt, unless answer
    is empty); returns its id."""
    sample_id = str(max(map(int, get_sample_ids(cwd)), default=0) + 1)
    (cwd / f"in{sample_id}.txt").write_text(input_text, encoding="utf-8", newline="")
    if answer.strip():
        (cwd / f"ans{sample_id}.txt").write_text(answer, encoding="utf-8", newline="")
    return sample_id


def plain(text: str) -> str:
    """Per-line whitespace trim (exactly what the Go tool compares)."""
    return "".join(line.strip() + "\n" for line in text.splitlines())


def split_cmd(command: str) -> list[str]:
    """Words of a script, by the Go tool's splitCmd rules.

    Whitespace separates words; a quote of either kind opens a span that the
    next quote of either kind closes. Nothing else is special — unlike
    shlex, backslashes stay literal, so Windows paths survive.
    """
    words: list[str] = []
    word: list[str] = []
    quoted = False
    for char in command:
        if char.isspace() and not quoted:
            if word:
                words.append("".join(word))
                word.clear()
        elif char in "\"'":
            if quoted:
                words.append("".join(word))
                word.clear()
            quoted = not quoted
        else:
            word.append(char)
    if word:
        words.append("".join(word))
    return words


def format_memory(num_bytes: float) -> str:
    if num_bytes > 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.3f}MB"
    if num_bytes > 1024:
        return f"{num_bytes / 1024:.3f}KB"
    return f"{int(num_bytes)}B"


def _exit_reason(returncode: int) -> str:
    if returncode < 0:
        try:
            return f"killed by {signal.Signals(-returncode).name}"
        except ValueError:
            return f"killed by signal {-returncode}"
    return f"exit status {returncode}"


def _start(command: str, **kwargs) -> subprocess.Popen:
    argv = split_cmd(command)
    if not argv:
        raise CFError("Invalid script command. Please check config file")
    try:
        return subprocess.Popen(argv, **kwargs)
    except OSError as e:
        raise CFError(f"Cannot run {argv[0]!r}: {e.strerror or e}") from e


def _children_cpu() -> float:
    """User CPU seconds of all finished child processes so far."""
    assert resource is not None
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime


def _watch_memory(pid: int, peak: list[int], stop: threading.Event) -> None:
    try:
        process = psutil.Process(pid)
        while not stop.is_set():
            peak[0] = max(peak[0], process.memory_info().rss)
            time.sleep(0.005)
    except psutil.Error:
        pass


def run_script(script: str, cwd: Path) -> None:
    """Run a before/after script, echoing it first (stdout/stderr pass through)."""
    if not script:
        return
    ui.plain(script)
    process = _start(script, cwd=cwd, stdin=subprocess.DEVNULL)
    if process.wait() != 0:
        raise CFError(_exit_reason(process.returncode))


@dataclass(frozen=True)
class Check:
    """How a sample's output is compared with its answer."""

    epsilon: float | None = None  # numbers within this, absolute or relative
    ignore_case: bool = False
    checker: str = ""  # a program run as: checker <input> <output> <answer>; exit 0: right

    def describe(self) -> str:
        """What this check accepts beyond the exact answer; "" when nothing."""
        if self.checker:
            return f"Judging with {self.checker}"
        allowed = []
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
    checker: str = "",
    exact: bool = False,
) -> Check:
    """How to compare: the options given win; unless exact, what the
    statement allows (saved by cf parse) fills in the rest."""
    if checker:
        return Check(checker=checker)
    if not exact and info is not None:
        epsilon = info.epsilon if epsilon is None else epsilon
        ignore_case = ignore_case or info.ignore_case
    return Check(epsilon=epsilon, ignore_case=ignore_case)


_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _tokens_match(got: str, want: str, epsilon: float) -> bool:
    """An output token against the answer's: numbers within epsilon, absolute
    or relative (as testlib checks them), anything else exactly."""
    if _NUMBER_RE.fullmatch(got) and _NUMBER_RE.fullmatch(want):
        return abs(float(got) - float(want)) <= epsilon * max(1.0, abs(float(want))) + 1e-15
    return got == want


def same_output(out: str, ans: str, check: Check) -> bool:
    """Whether out counts as ans (both trimmed per line already):
    - with an epsilon: token by token, numbers within it
    - otherwise line by line, in any letter case if allowed"""
    if check.ignore_case:
        out, ans = out.lower(), ans.lower()
    if check.epsilon is None:
        return out == ans
    got, want = out.split(), ans.split()
    return len(got) == len(want) and all(
        _tokens_match(g, w, check.epsilon) for g, w in zip(got, want)
    )


def _run_checker(
    checker: str, in_path: Path, output: bytes, ans_path: Path, cwd: Path
) -> tuple[bool, str]:
    """The checker's verdict on output: (right, what it said)."""
    fd, out_name = tempfile.mkstemp(prefix="cf-output-", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(output)
        argv = split_cmd(checker) + [str(in_path), out_name, str(ans_path)]
        try:
            done = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=60)
        except OSError as e:
            raise CFError(f"Cannot run the checker {argv[0]!r}: {e.strerror or e}") from e
        except subprocess.TimeoutExpired:
            return False, "the checker ran over 60s"
        said = (done.stderr or done.stdout).decode(errors="replace").strip()
        return done.returncode == 0, said
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out_name)


DEFAULT_TIMEOUT = 10.0  # seconds a sample may run when its time limit is unknown


def timeout_for(time_limit: float | None) -> float:
    """Seconds a sample may run before it is killed: a few times the limit."""
    if time_limit is None:
        return DEFAULT_TIMEOUT
    return max(
        3 * time_limit, time_limit + 2
    )  # NOTE: a slower machine than the judge's still passes


def judge(
    sample_id: str,
    command: str,
    cwd: Path,
    problem: ProblemInfo | None = None,
    check: Check = Check(),
    accept: bool = False,
) -> bool | None:
    """Run one sample and print its verdict; returns whether it passed, or
    None when it has no answer to pass:
    - output accepted by check: Passed, with time and memory (flagged over a limit)
    - running past its timeout: killed, Time limit exceeded
    - an exit status other than 0: Runtime Error, with what it printed
    - no ans{i}.txt: Ran, with the output (saved as the answer if accept)
    - other output: Failed, with a diff"""
    in_path = cwd / f"in{sample_id}.txt"
    ans_path = cwd / f"ans{sample_id}.txt"
    time_limit = problem.time_limit if problem else None
    memory_limit = problem.memory_limit if problem else None
    timeout = timeout_for(time_limit)

    peak = [0]
    stop = threading.Event()
    killed = False
    cpu_start = _children_cpu() if resource else 0.0
    wall_start = time.perf_counter()
    with in_path.open("rb") as stdin:
        process = _start(command, stdin=stdin, stdout=subprocess.PIPE, cwd=cwd)
        watcher = threading.Thread(target=_watch_memory, args=(process.pid, peak, stop))
        watcher.start()
        try:
            raw_out, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raw_out, _ = process.communicate()
            killed = True
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            stop.set()
            watcher.join()
    if resource:
        elapsed = _children_cpu() - cpu_start
    else:
        elapsed = time.perf_counter() - wall_start

    if killed:
        ui.line(
            (f"Time limit exceeded #{sample_id}", "red"), (f" ... killed after {timeout:g}s", "")
        )
        return False
    if process.returncode != 0:
        ui.red(f"Runtime Error #{sample_id} ... {_exit_reason(process.returncode)}")
        output = raw_out.decode(errors="replace")
        if output.strip():
            ui.console.print(views.program_output(output))
        return False

    usage = _usage(elapsed, peak[0], time_limit, memory_limit)
    if not ans_path.is_file():
        ui.line((f"Ran #{sample_id}", "cyan"), *usage)
        output = raw_out.decode(errors="replace")
        ui.console.print(views.program_output(output))
        if accept:
            ans_path.write_text(output, encoding="utf-8", newline="")
            ui.green(f"Saved the output as {ans_path.name}")
        return None
    ans = plain(ans_path.read_text(encoding="utf-8", errors="replace"))
    out = plain(raw_out.decode(errors="replace"))

    if check.checker:
        passed, said = _run_checker(check.checker, in_path, raw_out, ans_path, cwd)
    else:
        passed, said = same_output(out, ans, check), ""
    verdict = (f"Passed #{sample_id}", "green") if passed else (f"Failed #{sample_id}", "red")
    ui.line(verdict, *usage, *([(f" {said.splitlines()[0]}", "dim")] if said and passed else []))
    if not passed:
        if said:
            ui.line(("Checker: ", "red"), (said, ""))
        sample_input = in_path.read_text(encoding="utf-8", errors="replace")
        cases = problem.sample_cases(sample_id) if problem else None
        alike = operator.eq if check.checker else (lambda o, a: same_output(o, a, check))
        ui.console.print(
            views.failed_sample(sample_input, out.splitlines(), ans.splitlines(), cases, alike)
        )
    return passed


def _usage(
    elapsed: float, peak: int, time_limit: float | None, memory_limit: int | None
) -> list[tuple[str, str]]:
    """Styled " ... 0.123s 4.5MB" for a verdict line, flagged over a limit."""
    over_time = time_limit is not None and elapsed > time_limit
    over_memory = memory_limit is not None and peak > memory_limit * 1024 * 1024
    parts = [
        (" ... ", ""),
        (f"{elapsed:.3f}s", "yellow" if over_time else ""),
        (" ", ""),
        (format_memory(peak), "yellow" if over_memory else ""),
    ]
    if over_time:
        parts.append((f" (over the {time_limit:g}s limit)", "yellow"))
    if over_memory:
        parts.append((f" (over the {memory_limit} MB limit)", "yellow"))
    return parts


def run_test(
    cfg: Config,
    file_arg: str | None,
    cwd: Path,
    contest: str = "",
    problem: str = "",
    *,
    samples: Sequence[str] = (),
    epsilon: float | None = None,
    ignore_case: bool = False,
    checker: str = "",
    exact: bool = False,
    accept: bool = False,
) -> None:
    """`cf test [file] [sample...]`: full flow from cmd/test.go, plus a summary.
    contest/problem (from the directory) help pick the right code file;
    samples picks which to run (all by default); the rest says how to compare
    (see check_for) and whether to keep the output of a sample without answer."""
    if not cfg.template:
        raise CFError(NO_TEMPLATE)
    found = get_sample_ids(cwd)
    if not found:
        raise CFError("Cannot find any sample file")
    unknown = [s for s in samples if s not in found]
    if unknown:
        raise CFError(f"No sample {', '.join(unknown)} here (there are {', '.join(found)})")
    samples = [s for s in found if s in samples] if samples else found
    info = ProblemInfo.load(cwd)
    if info is not None and info.interactive:
        raise CFError("This problem is interactive: its samples are a conversation, not an answer")
    # only files in cwd: the scripts run there, with $%full%$ relative to it
    filename, index = codefiles.pick(
        file_arg, cfg.template, cwd, contest=contest, problem=problem, action="test"
    )
    template = cfg.template[index]
    subs = templates.script_substitutions(filename)
    script = templates.substitute_script(template.script, **subs)
    if not script:
        raise CFError("Invalid script command. Please check config file")

    check = check_for(info, epsilon=epsilon, ignore_case=ignore_case, checker=checker, exact=exact)
    run_script(templates.substitute_script(template.before_script, **subs), cwd)
    if check.describe():
        ui.line((check.describe(), "dim"))
    verdicts = []
    for sample_id in samples:
        try:
            verdicts.append(judge(sample_id, script, cwd, info, check, accept))
        except CFError as e:
            ui.red(str(e))
            verdicts.append(False)
    judged = [v for v in verdicts if v is not None]
    summary = f"{sum(judged)}/{len(judged)} passed"
    if len(judged) < len(verdicts):
        summary += f", {len(verdicts) - len(judged)} without an answer"
    ui.line((summary, "bold green" if all(judged) else "bold red"))
    run_script(templates.substitute_script(template.after_script, **subs), cwd)
