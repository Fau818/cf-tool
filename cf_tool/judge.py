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

import re
import signal
import subprocess
import threading
import time
from pathlib import Path

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
    """Sample ids that have both in{i}.txt and ans{i}.txt, numerically sorted."""
    ids = []
    for entry in cwd.iterdir():
        match = _IN_FILE_RE.match(entry.name)
        if match and (cwd / f"ans{match.group(1)}.txt").is_file():
            ids.append(match.group(1))
    return sorted(ids, key=int)


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


DEFAULT_TIMEOUT = 10.0  # seconds a sample may run when its time limit is unknown


def timeout_for(time_limit: float | None) -> float:
    """Seconds a sample may run before it is killed: a few times the limit."""
    if time_limit is None:
        return DEFAULT_TIMEOUT
    return max(
        3 * time_limit, time_limit + 2
    )  # NOTE: a slower machine than the judge's still passes


def judge(sample_id: str, command: str, cwd: Path, problem: ProblemInfo | None = None) -> bool:
    """Run one sample and print its verdict; returns whether it passed.
    - output as the answer: Passed, with time and memory (flagged over a limit)
    - running past its timeout: killed, Time limit exceeded
    - an exit status other than 0: Runtime Error, with what it printed
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

    try:
        ans = plain(ans_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        ans = ""
    out = plain(raw_out.decode(errors="replace"))

    passed = out == ans
    over_time = time_limit is not None and elapsed > time_limit
    over_memory = memory_limit is not None and peak[0] > memory_limit * 1024 * 1024
    parts = [
        (f"Passed #{sample_id}", "green") if passed else (f"Failed #{sample_id}", "red"),
        (" ... ", ""),
        (f"{elapsed:.3f}s", "yellow" if over_time else ""),
        (" ", ""),
        (format_memory(peak[0]), "yellow" if over_memory else ""),
    ]
    if over_time:
        parts.append((f" (over the {time_limit:g}s limit)", "yellow"))
    if over_memory:
        parts.append((f" (over the {memory_limit} MB limit)", "yellow"))
    ui.line(*parts)
    if not passed:
        sample_input = in_path.read_text(encoding="utf-8", errors="replace")
        ui.console.print(views.failed_sample(sample_input, out.splitlines(), ans.splitlines()))
    return passed


def run_test(
    cfg: Config, file_arg: str | None, cwd: Path, contest: str = "", problem: str = ""
) -> None:
    """`cf test [file]`: full flow from cmd/test.go, plus a summary line.
    contest/problem (from the directory) help pick the right code file."""
    if not cfg.template:
        raise CFError(NO_TEMPLATE)
    samples = get_sample_ids(cwd)
    if not samples:
        raise CFError("Cannot find any sample file")
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

    run_script(templates.substitute_script(template.before_script, **subs), cwd)
    passed = 0
    for sample_id in samples:
        try:
            passed += judge(sample_id, script, cwd, info)
        except CFError as e:
            ui.red(str(e))
    style = "bold green" if passed == len(samples) else "bold red"
    ui.line((f"{passed}/{len(samples)} passed", style))
    run_script(templates.substitute_script(template.after_script, **subs), cwd)
