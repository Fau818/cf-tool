"""cf stress with Python programs: finding a difference, keeping it, failures."""

import sys

import pytest

from cf_tool import judge, paths
from cf_tool.build import Program
from cf_tool.errors import CFError
from cf_tool.judge import Check
from cf_tool.languages import Setup
from cf_tool.stress import stress
from cf_tool.workspace import tests_of

GENERATOR = "import random, sys\nrandom.seed(int(sys.argv[1]))\nprint(random.randint(1, 20))\n"
BRUTE = "n = int(input())\nprint(sum(range(1, n + 1)))\n"
RIGHT = "n = int(input())\nprint(n * (n + 1) // 2)\n"


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")


def python(path) -> Program:
    return Program(path, Setup("py", "Python", "python", None, (sys.executable, "{src}")))


def programs(tmp_path, solution: str, generator: str = GENERATOR, brute: str = BRUTE):
    for name, code in (("gen.py", generator), ("brute.py", brute), ("a.py", solution)):
        (tmp_path / name).write_text(code)
    return [python(tmp_path / name) for name in ("gen.py", "brute.py", "a.py")]


def test_finds_a_difference_and_keeps_it(tmp_path, capsys):
    wrong = "n = int(input())\nprint(n * (n + 1) // 2 + (n == 7))\n"
    saved = stress(tmp_path, *programs(tmp_path, wrong), tests=200)
    assert saved is not None and saved.name.startswith("stress-")
    out = capsys.readouterr().out
    assert "Wrong answer on the test from seed" in out and f"cf test {saved.name} runs it" in out
    assert saved.input.read_text() == "7\n" and saved.answer.read_text() == "28\n"
    assert [t.name for t in tests_of(tmp_path)] == [saved.name]


def test_all_tests_pass(tmp_path, capsys):
    assert stress(tmp_path, *programs(tmp_path, RIGHT), tests=20, seed=5) is None
    assert "All 20 tests passed (seeds 5 to 24)" in capsys.readouterr().out
    assert tests_of(tmp_path) == []


def test_a_crash_is_kept_too(tmp_path, capsys):
    crash = "n = int(input())\nassert n != 7\nprint(n * (n + 1) // 2)\n"
    assert stress(tmp_path, *programs(tmp_path, crash), tests=200) is not None
    out = capsys.readouterr().out
    assert "Runtime error (exit status 1)" in out and "-----Input-----" in out


def test_a_hang_is_kept_too(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(judge, "timeout_for", lambda limit: 0.5)
    hang = "import time\nn = int(input())\nif n == 7: time.sleep(30)\nprint(n * (n + 1) // 2)\n"
    assert stress(tmp_path, *programs(tmp_path, hang), tests=200) is not None
    assert "Time limit exceeded (killed after 0.5s)" in capsys.readouterr().out


def test_a_broken_generator_or_brute_force_stops(tmp_path):
    with pytest.raises(CFError, match=r"The generator \(seed 1\) failed \(exit status 1\): boom"):
        stress(tmp_path, *programs(tmp_path, RIGHT, generator="raise SystemExit('boom')\n"))
    with pytest.raises(CFError, match=r"The brute force \(seed 1\) failed"):
        stress(tmp_path, *programs(tmp_path, RIGHT, brute="1 / 0\n"))


def test_with_a_checker(tmp_path, capsys):
    # NOTE: several answers are right: any order of the numbers
    (tmp_path / "checker.py").write_text(
        "import sys\n"
        "inp, out, ans = (open(p).read().split() for p in sys.argv[1:])\n"
        "sys.exit(0 if sorted(out) == sorted(ans) else 1)\n"
    )
    generator = "import sys\nprint(sys.argv[1], int(sys.argv[1]) * 2)\n"
    brute = "print(*sorted(input().split(), key=int))\n"
    solution = "print(*sorted(input().split(), key=int, reverse=True))\n"
    check = Check(checker=python(tmp_path / "checker.py"))
    found = stress(tmp_path, *programs(tmp_path, solution, generator, brute), tests=5, check=check)
    assert found is None and "All 5 tests passed" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []
