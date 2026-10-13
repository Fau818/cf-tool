"""Tests for the local judge: sample discovery, comparison, full test flow."""

import sys

import pytest

from cf_tool.config import CodeTemplate, Config
from cf_tool.errors import CFError
from cf_tool.judge import (
    format_memory,
    get_sample_ids,
    judge,
    plain,
    run_script,
    run_test,
    split_cmd,
)


def make_samples(tmp_path, cases):
    for i, (stdin, ans) in enumerate(cases, start=1):
        (tmp_path / f"in{i}.txt").write_text(stdin)
        (tmp_path / f"ans{i}.txt").write_text(ans)


def test_get_sample_ids(tmp_path):
    make_samples(tmp_path, [("1", "1"), ("2", "2")])
    (tmp_path / "in3.txt").write_text("no ans")  # unpaired: ignored
    (tmp_path / "in10.txt").write_text("10")
    (tmp_path / "ans10.txt").write_text("10")
    assert get_sample_ids(tmp_path) == ["1", "2", "10"]


def test_plain_trims_per_line_only():
    assert plain("a \n b\n") == "a\nb\n"
    assert plain("a\n\nb") == "a\n\nb\n"
    # trailing blank lines are NOT stripped (Go behavior)
    assert plain("5\n\n") == "5\n\n"
    assert plain("5\n") != plain("5\n\n")


def test_format_memory():
    assert format_memory(512) == "512B"
    assert format_memory(2048) == "2.000KB"
    assert format_memory(3 * 1024 * 1024) == "3.000MB"


CAT = f'{sys.executable} -c "import sys; sys.stdout.write(sys.stdin.read())"'


def test_judge_pass(tmp_path):
    make_samples(tmp_path, [("hello\n", "hello\n")])
    assert judge("1", CAT, tmp_path) is True


def test_judge_fail(tmp_path, capsys):
    make_samples(tmp_path, [("hello\n", "goodbye\n")])
    assert judge("1", CAT, tmp_path) is False
    captured = capsys.readouterr().out
    assert "Failed #1" in captured
    assert "-----Input-----" in captured
    assert "goodbye" in captured


def test_judge_whitespace_normalization(tmp_path):
    make_samples(tmp_path, [("x\n", "  x  \n")])
    assert judge("1", CAT, tmp_path) is True


def test_judge_runtime_error(tmp_path):
    make_samples(tmp_path, [("", "")])
    bomb = f'{sys.executable} -c "raise SystemExit(3)"'
    with pytest.raises(CFError, match="Runtime Error #1"):
        judge("1", bomb, tmp_path)


def test_run_test_full_flow(tmp_path, capsys):
    """End-to-end: echo-style solution via template scripts, in/ans pairs."""
    solution = tmp_path / "a.py"
    solution.write_text("print(int(input()) * 2)\n")
    make_samples(tmp_path, [("2\n", "4\n"), ("3\n", "6\n")])
    cfg = Config(
        template=[
            CodeTemplate(
                alias="py",
                lang="31",
                suffix=["py"],
                before_script="",
                script=f"{sys.executable} $%full%$",
                after_script="",
            )
        ]
    )
    run_test(cfg, None, tmp_path)
    captured = capsys.readouterr().out
    assert "Passed #1" in captured
    assert "Passed #2" in captured


def test_run_test_requires_samples(tmp_path):
    cfg = Config(template=[CodeTemplate(alias="py", suffix=["py"], script="x")])
    with pytest.raises(CFError, match="Cannot find any sample file"):
        run_test(cfg, None, tmp_path)


def test_run_test_requires_templates(tmp_path):
    with pytest.raises(CFError, match="add at least one code template"):
        run_test(Config(), None, tmp_path)


@pytest.mark.parametrize(
    "command,words",
    [
        ("g++ -O2 -o a a.cpp", ["g++", "-O2", "-o", "a", "a.cpp"]),
        # backslashes stay literal (shlex turned this into C:Usersmea.exe)
        (r"C:\Users\me\a.exe -v", [r"C:\Users\me\a.exe", "-v"]),
        ('python3 "my file.py"', ["python3", "my file.py"]),
        ("echo it's", ["echo", "its"]),  # Go: a lone quote just toggles, no error
        ('a"b c"d', ["ab c", "d"]),
        ("   ", []),
    ],
)
def test_split_cmd_matches_go(command, words):
    assert split_cmd(command) == words


def test_missing_program_is_a_clean_error(tmp_path):
    make_samples(tmp_path, [("1\n", "1\n")])
    with pytest.raises(CFError, match="Cannot run 'no-such-binary-xyz'"):
        judge("1", "no-such-binary-xyz", tmp_path)
    with pytest.raises(CFError, match="Cannot run 'no-such-compiler-xyz'"):
        run_script("no-such-compiler-xyz a.cpp", tmp_path)


def test_failed_sample_shows_brackets_literally(tmp_path, capsys):
    # Rich markup used to eat "[i]" / "[j]" and crash on "[/]"
    make_samples(tmp_path, [("arr[i] = [j] [/]\n", "something else\n")])
    assert judge("1", CAT, tmp_path) is False
    out = capsys.readouterr().out
    assert "arr[i] = [j] [/]" in out
    assert "something else" in out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_signal_is_reported(tmp_path):
    make_samples(tmp_path, [("", "")])
    suicide = f'{sys.executable} -c "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"'
    with pytest.raises(CFError, match="killed by SIGTERM"):
        judge("1", suicide, tmp_path)


def test_run_test_prints_a_summary(tmp_path, capsys):
    (tmp_path / "a.py").write_text("print(int(input()) * 2)\n")
    make_samples(tmp_path, [("2\n", "4\n"), ("3\n", "7\n")])
    cfg = Config(
        template=[
            CodeTemplate(alias="py", lang="31", suffix=["py"], script=f"{sys.executable} $%full%$")
        ]
    )
    run_test(cfg, None, tmp_path)
    assert "1/2 passed" in capsys.readouterr().out
