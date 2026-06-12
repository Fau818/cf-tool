"""Local testing (`cf test`): run before_script / script / after_script,
feed in{i}.txt, compare with ans{i}.txt. Port of cmd/test.go.

Like the original, there is no time limit — interrupt a hung solution with
Ctrl+C. Output comparison strips per-line surrounding whitespace only.
"""

from __future__ import annotations

import difflib
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

import psutil

from cf_tool import templates, ui
from cf_tool.config import Config
from cf_tool.errors import CFError

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


def format_memory(num_bytes: float) -> str:
    if num_bytes > 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.3f}MB"
    if num_bytes > 1024:
        return f"{num_bytes / 1024:.3f}KB"
    return f"{int(num_bytes)}B"


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
    result = subprocess.run(shlex.split(script), cwd=cwd)
    if result.returncode != 0:
        raise CFError(f"exit status {result.returncode}")


def judge(sample_id: str, command: str, cwd: Path) -> bool:
    """Run one sample; print Passed/Failed line plus diff. Returns pass/fail."""
    in_path = cwd / f"in{sample_id}.txt"
    ans_path = cwd / f"ans{sample_id}.txt"

    peak = [0]
    stop = threading.Event()
    start = time.perf_counter()
    with in_path.open("rb") as stdin:
        process = subprocess.Popen(
            shlex.split(command), stdin=stdin, stdout=subprocess.PIPE, cwd=cwd
        )
        watcher = threading.Thread(target=_watch_memory, args=(process.pid, peak, stop))
        watcher.start()
        try:
            raw_out, _ = process.communicate()
        finally:
            stop.set()
            watcher.join()
    elapsed = time.perf_counter() - start

    if process.returncode != 0:
        raise CFError(f"Runtime Error #{sample_id} ... exit status {process.returncode}")

    try:
        ans = plain(ans_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        ans = ""
    out = plain(raw_out.decode(errors="replace"))

    passed = out == ans
    state = f"[green]Passed #{sample_id}[/green]" if passed else f"[red]Failed #{sample_id}[/red]"
    ui.console.print(f"{state} ... {elapsed:.3f}s {format_memory(peak[0])}")
    if not passed:
        ui.cyan("-----Input-----")
        ui.plain(in_path.read_text(encoding="utf-8", errors="replace").rstrip("\n"))
        ui.cyan("-----Output-----")
        ui.plain(out.rstrip("\n"))
        ui.cyan("-----Answer-----")
        ui.plain(ans.rstrip("\n"))
        ui.cyan("-----Diff-----")
        for line in difflib.unified_diff(out.splitlines(), ans.splitlines(), lineterm="", n=2):
            if line.startswith("-"):
                ui.console.print(line, style="red")
            elif line.startswith("+"):
                ui.console.print(line, style="green")
            elif not line.startswith(("---", "+++", "@@")):
                ui.plain(line)
    return passed


def run_test(cfg: Config, file_arg: str | None, cwd: Path) -> None:
    """`cf test [file]`: full flow from cmd/test.go."""
    if not cfg.template:
        raise CFError("You have to add at least one code template by `cf config`")
    samples = get_sample_ids(cwd)
    if not samples:
        raise CFError("Cannot find any sample file")
    filename, index = templates.get_one_code(file_arg, cfg.template, cwd)
    template = cfg.template[index]
    subs = templates.script_substitutions(filename)

    run_script(templates.substitute_script(template.before_script, **subs), cwd)
    script = templates.substitute_script(template.script, **subs)
    if not script:
        raise CFError("Invalid script command. Please check config file")
    for sample_id in samples:
        try:
            judge(sample_id, script, cwd)
        except CFError as e:
            ui.red(str(e))
    run_script(templates.substitute_script(template.after_script, **subs), cwd)
