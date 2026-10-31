"""Running programs: verdict, output, limits, and nothing left running."""

import os
import sys
import textwrap
import time

import psutil
import pytest

from cf_tool import process
from cf_tool.errors import CFError
from cf_tool.process import run, split_command

PY = sys.executable
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups and signals")


def script(tmp_path, code: str, name: str = "prog.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(code))
    return [PY, str(path)]


def test_output_and_usage(tmp_path):
    argv = script(tmp_path, "import sys; print(int(sys.stdin.read()) * 2)")
    result = run(argv, cwd=tmp_path, stdin=b"21\n", timeout=30)
    assert result.ok and result.stdout.strip() == b"42"
    assert result.cpu > 0 and result.wall > 0
    if os.name == "posix":
        assert result.memory > 1024 * 1024  # NOTE: a Python process takes megabytes


def test_input_from_a_file(tmp_path):
    (tmp_path / "1.in").write_text("hello\n")
    argv = script(tmp_path, "print(input().upper())")
    assert run(argv, cwd=tmp_path, stdin=tmp_path / "1.in", timeout=30).stdout == b"HELLO\n"


def test_no_input_is_end_of_input(tmp_path):
    argv = script(tmp_path, "import sys; print(repr(sys.stdin.read()))")
    assert run(argv, cwd=tmp_path, timeout=30).stdout == b"''\n"


def test_unread_input_does_not_hang(tmp_path):
    argv = script(tmp_path, "print('done')")  # NOTE: never reads its 10 MB of input
    result = run(argv, cwd=tmp_path, stdin=b"x" * (10 * 1024 * 1024), timeout=30)
    assert result.ok and result.stdout == b"done\n"


def test_exit_code_and_stderr(tmp_path):
    argv = script(tmp_path, "import sys; print('partial'); sys.exit('boom')")
    result = run(argv, cwd=tmp_path, timeout=30)
    assert result.status == process.EXIT and result.reason() == "exit status 1"
    assert result.stdout == b"partial\n" and b"boom" in result.stderr


@posix_only
def test_crash(tmp_path):
    argv = script(tmp_path, "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")
    result = run(argv, cwd=tmp_path, timeout=30)
    assert result.status == process.SIGNAL and result.reason() == "killed by SIGSEGV"


def test_runs_in_cwd(tmp_path):
    argv = script(tmp_path, "import os; print(os.getcwd())")
    out = run(argv, cwd=tmp_path, timeout=30).stdout.decode().strip()
    assert os.path.samefile(out, tmp_path)


def test_timeout_kills_it(tmp_path):
    argv = script(tmp_path, "import time; print('started', flush=True); time.sleep(60)")
    started = time.monotonic()
    result = run(argv, cwd=tmp_path, timeout=1)
    assert time.monotonic() - started < 10
    assert result.status == process.TIMEOUT and result.reason() == "killed after 1s"
    assert result.stdout == b"started\n"


@posix_only
def test_timeout_kills_what_it_started(tmp_path):
    # NOTE: the grandchild keeps stdout open: waiting on the pipe alone would hang
    argv = script(
        tmp_path,
        """
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        print(child.pid, flush=True)
        time.sleep(60)
        """,
    )
    started = time.monotonic()
    result = run(argv, cwd=tmp_path, timeout=1)
    assert time.monotonic() - started < 10 and result.status == process.TIMEOUT
    grandchild = int(result.stdout)
    deadline = time.monotonic() + 5
    while psutil.pid_exists(grandchild) and time.monotonic() < deadline:
        if psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE:
            break
        time.sleep(0.05)
    assert not psutil.pid_exists(grandchild) or (
        psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE
    )


@posix_only
def test_nothing_is_left_running(tmp_path):
    argv = script(
        tmp_path,
        """
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        print(child.pid)
        """,
    )
    result = run(argv, cwd=tmp_path, timeout=30)
    assert result.ok
    grandchild = int(result.stdout)
    time.sleep(0.2)
    alive = psutil.pid_exists(grandchild) and (
        psutil.Process(grandchild).status() != psutil.STATUS_ZOMBIE
    )
    assert not alive


def test_output_limit(tmp_path):
    argv = script(tmp_path, "import sys\nwhile True: sys.stdout.write('y' * 4096)")
    started = time.monotonic()
    result = run(argv, cwd=tmp_path, timeout=30, output_limit=1024 * 1024)
    assert time.monotonic() - started < 10
    assert result.status == process.OUTPUT and len(result.stdout) == 1024 * 1024
    assert result.reason() == "printed over 1 MB"


def test_stderr_keeps_its_end(tmp_path):
    argv = script(tmp_path, "import sys; sys.stderr.write('x' * 200000 + 'END')")
    result = run(argv, cwd=tmp_path, timeout=30)
    assert len(result.stderr) <= process.STDERR_KEPT and result.stderr.endswith(b"END")


def test_cannot_start(tmp_path):
    with pytest.raises(CFError, match="Cannot run 'no-such-program-here'"):
        run(["no-such-program-here"], cwd=tmp_path, timeout=5)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the stack limit is Linux's way")
def test_big_stack(tmp_path):
    argv = script(tmp_path, "import resource; print(resource.getrlimit(resource.RLIMIT_STACK)[0])")
    soft = int(run(argv, cwd=tmp_path, timeout=30, big_stack=True).stdout)
    assert soft == -1 or soft >= process.STACK_LIMIT


@pytest.mark.parametrize(
    "command,words",
    [
        ("g++ -O2 a.cpp", ["g++", "-O2", "a.cpp"]),
        ('"my prog" x', ["my prog", "x"]),
        ("a 'b c' d", ["a", "b c", "d"]),
        (r"C:\tools\g++.exe a.cpp", [r"C:\tools\g++.exe", "a.cpp"]),
        ("  spaced   out  ", ["spaced", "out"]),
        ("", []),
    ],
)
def test_split_command(command, words):
    assert split_command(command) == words
