"""Running a program: input in, output out, and how it went.

Each program runs in a process group of its own, so a time limit kills
everything it started (a wrapper script, a forked child) and nothing is left
running afterwards; Ctrl-C reaches it through cf-tool. Output is read as it
comes, up to a cap: past it the run stops, the way the judge stops it with
"Output limit exceeded", instead of filling memory. CPU time and peak memory
come from the kernel's accounting for the finished program (wait4); Windows
gives wall time and polled memory.
"""

from __future__ import annotations

import collections
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Sequence

import psutil

from cf_tool.errors import CFError

try:
    import resource
except ImportError:  # Windows
    resource = None  # type: ignore[assignment]

OUTPUT_LIMIT = 64 * 1024 * 1024  # bytes a program may print before it is stopped
STDERR_KEPT = 64 * 1024  # the last bytes of its error output, kept for messages
STACK_LIMIT = 256 * 1024 * 1024  # bytes: the stack Codeforces gives
_CHUNK = 64 * 1024
_GRACE = 2.0  # seconds to wait for a killed program, and for its pipes to close

OK = "ok"
EXIT = "exit"  # a non-zero exit code
SIGNAL = "signal"  # killed by a signal: a crash
TIMEOUT = "timeout"
OUTPUT = "output"  # printed more than its output limit

# Windows' codes for the usual crashes, as unsigned exit codes
_WINDOWS_CRASHES = {
    0xC0000005: "access violation",
    0xC00000FD: "stack overflow",
    0xC0000094: "integer division by zero",
    0xC0000409: "stack buffer overrun",
}


@dataclass(frozen=True)
class Result:
    """How a run went."""

    status: str  # OK, EXIT, SIGNAL, TIMEOUT or OUTPUT
    code: int | None  # its exit code (negative: the number of the signal that killed it)
    stdout: bytes
    stderr: bytes  # its last STDERR_KEPT bytes
    cpu: float  # seconds of CPU time (wall time where the OS can't tell)
    wall: float  # seconds
    memory: int  # peak resident memory in bytes, 0 when unknown
    timeout: float | None = None  # the seconds it was allowed
    output_limit: int = OUTPUT_LIMIT

    @property
    def ok(self) -> bool:
        return self.status == OK

    def reason(self) -> str:
        """Why it didn't end well, in a few words: "exit status 1", "killed
        by SIGSEGV", "killed after 6s", "printed over 64 MB"."""
        if self.status == TIMEOUT:
            return f"killed after {self.timeout:g}s"
        if self.status == OUTPUT:
            return f"printed over {self.output_limit // (1024 * 1024)} MB"
        if self.status == SIGNAL and self.code is not None:
            try:
                return f"killed by {signal.Signals(-self.code).name}"
            except ValueError:
                return f"killed by signal {-self.code}"
        crash = _WINDOWS_CRASHES.get(self.code or 0)
        return crash or f"exit status {self.code}"


def split_command(command: str) -> list[str]:
    """The words of a command line. Whitespace separates them; a quote of
    either kind opens a span that the next quote of either kind closes.
    Nothing else is special: backslashes stay, so Windows paths survive."""
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


# ┌──────────────────────────────────────────────────────────┐
# │                        A program                         │
# └──────────────────────────────────────────────────────────┘


class Child:
    """A started program in a process group of its own, waited for by a
    thread; `done` is set once it ended, with its exit code, CPU time and
    peak memory filled in."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        stdin,
        stdout,
        stderr,
        big_stack: bool = False,
    ) -> None:
        options: dict = {}
        if os.name == "posix":
            options["start_new_session"] = True
            if big_stack and sys.platform.startswith("linux"):
                options["preexec_fn"] = _raise_stack
        else:
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        argv = list(argv)
        if os.name == "nt":
            argv[0] = shutil.which(argv[0]) or argv[0]  # NOTE: finds .bat and .cmd tools too
        try:
            self.process = subprocess.Popen(
                argv, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, **options
            )
        except OSError as e:
            raise CFError(f"Cannot run {argv[0]!r}: {e.strerror or e}") from e
        self.started = time.perf_counter()
        self.wall = 0.0
        self.cpu: float | None = None
        self.memory = 0
        self.done = threading.Event()
        threading.Thread(target=self._wait, daemon=True).start()
        if os.name != "posix":
            threading.Thread(target=self._poll_memory, daemon=True).start()

    def _wait(self) -> None:
        try:
            if os.name == "posix":
                _, status, usage = os.wait4(self.process.pid, 0)
                self.process.returncode = os.waitstatus_to_exitcode(status)
                self.cpu = usage.ru_utime + usage.ru_stime
                # NOTE: ru_maxrss is in kilobytes on Linux, in bytes on macOS
                self.memory = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                self._kill_group()  # NOTE: whatever it left running goes with it
            else:
                self.process.wait()
                self.cpu = _windows_cpu(self.process.pid)
        finally:
            self.wall = time.perf_counter() - self.started
            self.done.set()

    def kill(self) -> None:
        """Kill the program and everything it started."""
        if os.name == "posix":
            self._kill_group()
            return
        try:
            parent = psutil.Process(self.process.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except psutil.Error:
            pass

    def _kill_group(self) -> None:
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # NOTE: the group is gone already

    def _poll_memory(self) -> None:
        try:
            process = psutil.Process(self.process.pid)
            while not self.done.is_set():
                info = process.memory_info()
                self.memory = max(self.memory, getattr(info, "peak_wset", info.rss))
                time.sleep(0.01)
        except psutil.Error:
            pass


def _windows_cpu(pid: int) -> float | None:
    try:
        times = psutil.Process(pid).cpu_times()
        return times.user + times.system
    except psutil.Error:
        return None


def _raise_stack() -> None:
    """Give the program Codeforces' stack (runs in the child, before exec)."""
    assert resource is not None
    soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
    want = STACK_LIMIT if hard == resource.RLIM_INFINITY else min(STACK_LIMIT, hard)
    if soft != resource.RLIM_INFINITY and soft < want:
        resource.setrlimit(resource.RLIMIT_STACK, (want, hard))


class _Reader(threading.Thread):
    """Reads a pipe to its end, keeping its first `limit` bytes (calling
    over() once there are more) or only its last `tail` bytes."""

    def __init__(
        self,
        pipe: IO[bytes],
        *,
        limit: int | None = None,
        tail: int | None = None,
        over: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.pipe, self.limit, self.tail, self.over = pipe, limit, tail, over
        self.chunks: collections.deque[bytes] = collections.deque()
        self.size = 0
        self.exceeded = False
        self.start()

    def run(self) -> None:
        fd = self.pipe.fileno()
        try:
            while chunk := os.read(fd, _CHUNK):
                if self.exceeded:
                    continue  # NOTE: still drained, so the program isn't blocked writing
                self.chunks.append(chunk)
                self.size += len(chunk)
                if self.limit is not None and self.size > self.limit:
                    self.exceeded = True
                    if self.over is not None:
                        self.over()
                while self.tail is not None and self.size - len(self.chunks[0]) >= self.tail:
                    self.size -= len(self.chunks.popleft())
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                self.pipe.close()

    def data(self) -> bytes:
        data = b"".join(list(self.chunks))
        if self.limit is not None:
            data = data[: self.limit]
        if self.tail is not None:
            data = data[-self.tail :]
        return data


def _feed(pipe: IO[bytes], data: bytes) -> None:
    """Write data to the program's input in the background, then close it."""

    def write() -> None:
        try:
            pipe.write(data)
        except OSError:
            pass  # NOTE: a program needn't read all of its input
        finally:
            with contextlib.suppress(OSError):
                pipe.close()

    threading.Thread(target=write, daemon=True).start()


# ┌──────────────────────────────────────────────────────────┐
# │                         Running                          │
# └──────────────────────────────────────────────────────────┘


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    stdin: bytes | Path | None = None,
    timeout: float | None,
    output_limit: int = OUTPUT_LIMIT,
    big_stack: bool = False,
) -> Result:
    """Run argv in cwd and wait for it to end; returns how it went.
    - stdin: bytes to feed it, a file to read from, or nothing (end of input)
    - running past timeout seconds, or printing over output_limit bytes,
      kills it along with everything it started
    - big_stack: Codeforces' 256 MB stack (where a process limit gives it)"""
    in_file = stdin.open("rb") if isinstance(stdin, Path) else None
    feed = stdin if isinstance(stdin, bytes) else None
    try:
        child = Child(
            argv,
            cwd=cwd,
            stdin=in_file or (subprocess.PIPE if feed is not None else subprocess.DEVNULL),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            big_stack=big_stack,
        )
    finally:
        if in_file is not None:
            in_file.close()  # NOTE: the program has a copy of its own
    try:
        out = _Reader(child.process.stdout, limit=output_limit, over=child.kill)
        err = _Reader(child.process.stderr, tail=STDERR_KEPT)
        if feed is not None:
            _feed(child.process.stdin, feed)
        finished = child.done.wait(timeout)
        if not finished:
            child.kill()
            child.done.wait(_GRACE)
    except BaseException:  # NOTE: Ctrl-C doesn't reach a program in its own process group
        child.kill()
        raise
    out.join(_GRACE)
    err.join(_GRACE)
    code = child.process.returncode
    if out.exceeded:
        status = OUTPUT
    elif not finished:
        status = TIMEOUT
    elif code == 0:
        status = OK
    elif code is not None and code < 0:
        status = SIGNAL
    else:
        status = EXIT
    return Result(
        status=status,
        code=code,
        stdout=out.data(),
        stderr=err.data(),
        cpu=child.cpu if child.cpu is not None else child.wall,
        wall=child.wall,
        memory=child.memory,
        timeout=timeout,
        output_limit=output_limit,
    )
