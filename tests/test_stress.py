"""cf stress with Python programs: finding a difference, saving it, failures."""

import sys

import pytest

import cf_tool.judge as judge_module
from cf_tool.config import CodeTemplate
from cf_tool.errors import CFError
from cf_tool.judge import Check
from cf_tool.stress import Program, stress

PY = CodeTemplate(alias="py", suffix=["py"], script=f"{sys.executable} $%full%$")
GENERATOR = "import random, sys\nrandom.seed(int(sys.argv[1]))\nprint(random.randint(1, 20))\n"
BRUTE = "n = int(input())\nprint(sum(range(1, n + 1)))\n"
RIGHT = "n = int(input())\nprint(n * (n + 1) // 2)\n"


def programs(tmp_path, solution: str, generator: str = GENERATOR, brute: str = BRUTE):
    for name, code in (("gen.py", generator), ("brute.py", brute), ("a.py", solution)):
        (tmp_path / name).write_text(code)
    return [Program(name, PY) for name in ("gen.py", "brute.py", "a.py")]


def test_finds_a_difference_and_keeps_it(tmp_path, capsys):
    wrong = "n = int(input())\nprint(n * (n + 1) // 2 + (n == 7))\n"
    assert stress(tmp_path, *programs(tmp_path, wrong), tests=200) == "1"
    out = capsys.readouterr().out
    assert "Wrong answer on the test from seed" in out and "cf test 1 runs it again" in out
    assert (tmp_path / "in1.txt").read_text() == "7\n"
    assert (tmp_path / "ans1.txt").read_text() == "28\n"


def test_all_tests_pass(tmp_path, capsys):
    assert stress(tmp_path, *programs(tmp_path, RIGHT), tests=20, seed=5) is None
    assert "All 20 tests passed (seeds 5 to 24)" in capsys.readouterr().out
    assert not (tmp_path / "in1.txt").exists()


def test_a_crash_is_kept_too(tmp_path, capsys):
    crash = "n = int(input())\nassert n != 7\nprint(n * (n + 1) // 2)\n"
    assert stress(tmp_path, *programs(tmp_path, crash), tests=200) == "1"
    out = capsys.readouterr().out
    assert "Runtime Error" in out and "-----Input-----" in out


def test_a_hang_is_kept_too(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(judge_module, "timeout_for", lambda limit: 0.5)
    hang = "import time\nn = int(input())\nif n == 7: time.sleep(30)\nprint(n * (n + 1) // 2)\n"
    assert stress(tmp_path, *programs(tmp_path, hang), tests=200) == "1"
    assert "Time limit exceeded (killed after 0.5s)" in capsys.readouterr().out


def test_a_broken_generator_or_brute_force_stops(tmp_path):
    with pytest.raises(CFError, match=r"The generator \(seed 1\) crashed: .*boom"):
        stress(tmp_path, *programs(tmp_path, RIGHT, generator="raise SystemExit('boom')\n"))
    with pytest.raises(CFError, match=r"The brute force \(seed 1\) crashed"):
        stress(tmp_path, *programs(tmp_path, RIGHT, brute="1 / 0\n"))


def test_with_a_checker(tmp_path, capsys):
    # NOTE: several answers are right: any order of the numbers
    (tmp_path / "chk.py").write_text(
        "import sys\n"
        "inp, out, ans = (open(p).read().split() for p in sys.argv[1:])\n"
        "sys.exit(0 if sorted(out) == sorted(ans) else 1)\n"
    )
    generator = "import sys\nprint(sys.argv[1], int(sys.argv[1]) * 2)\n"
    brute = "print(*sorted(input().split(), key=int))\n"
    solution = "print(*sorted(input().split(), key=int, reverse=True))\n"
    check = Check(checker=f"{sys.executable} chk.py")
    found = stress(tmp_path, *programs(tmp_path, solution, generator, brute), tests=5, check=check)
    assert found is None and "All 5 tests passed" in capsys.readouterr().out


def test_builds_are_cleaned_up_whatever_happens(tmp_path):
    marker = tmp_path / "cleaned"
    (tmp_path / "clean.py").write_text("open('cleaned', 'a').write('x')\n")
    template = CodeTemplate(
        alias="py",
        suffix=["py"],
        script=f"{sys.executable} $%full%$",
        after_script=f"{sys.executable} clean.py",  # NOTE: Go's splitting: no quotes in quotes
    )
    for name, code in (("gen.py", "raise SystemExit(1)\n"), ("brute.py", BRUTE), ("a.py", RIGHT)):
        (tmp_path / name).write_text(code)
    with pytest.raises(CFError):
        stress(tmp_path, *(Program(name, template) for name in ("gen.py", "brute.py", "a.py")))
    assert marker.read_text() == "xxx"  # NOTE: all three programs' after_script ran
