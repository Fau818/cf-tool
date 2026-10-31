"""cf test's judging: comparison, verdicts, limits, checkers, interactors,
remembered results."""

import sys
import textwrap

import pytest

from cf_tool import judge, paths
from cf_tool.build import Program
from cf_tool.judge import Check, check_for, run_tests, same_output
from cf_tool.languages import Setup
from cf_tool.workspace import ProblemInfo, Test, add_test, save_samples, tests_of

PY = sys.executable


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")


def python(tmp_path, code: str, name: str = "a.py") -> Program:
    """A Python program (Python needs no build)."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(code))
    return Program(path, Setup("py", "Python", "python", None, (PY, "{src}")))


def samples(tmp_path, *pairs):
    save_samples(tmp_path, list(pairs))
    return tests_of(tmp_path)


# ┌──────────────────────────────────────────────────────────┐
# │                       Comparison                         │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.parametrize(
    "out,ans,check,same",
    [
        ("YES\n", "YES\n", {}, True),
        ("1 2\n", "1\n2\n", {}, True),  # NOTE: words, like Codeforces' checker
        ("1  2 \n\n", "1 2\n", {}, True),
        ("1 2\n", "1\n2\n", {"strict": True}, False),
        ("1 2  \n\n", "1 2\n", {"strict": True}, True),  # NOTE: trimmed lines
        ("yes\n", "YES\n", {}, False),
        ("yes\n", "YES\n", {"ignore_case": True}, True),
        ("0.3333333\n", "0.33333333\n", {"epsilon": 1e-6}, True),  # NOTE: absolute error
        ("1000000.5\n", "1000000.0\n", {"epsilon": 1e-6}, True),  # NOTE: relative error
        ("0.334\n", "0.333\n", {"epsilon": 1e-6}, False),
        ("1 2.0000001\n", "1\n2\n", {"epsilon": 1e-6}, True),
        ("1 2\n", "1 2 3\n", {"epsilon": 1e-6}, False),
        ("Yes 1e-7\n", "YES 0\n", {"epsilon": 1e-6, "ignore_case": True}, True),
    ],
)
def test_same_output(out, ans, check, same):
    assert same_output(out, ans, Check(**check)) is same


def test_check_for(tmp_path):
    lenient = ProblemInfo(epsilon=1e-6, ignore_case=True)
    assert check_for(lenient) == Check(epsilon=1e-6, ignore_case=True)
    assert check_for(lenient, epsilon=1e-3) == Check(epsilon=1e-3, ignore_case=True)
    assert check_for(lenient, exact=True) == Check()
    assert check_for(lenient, exact=True, ignore_case=True) == Check(ignore_case=True)
    assert check_for(lenient, strict=True).strict
    checker = python(tmp_path, "", "checker.py")
    assert check_for(lenient, checker=checker) == Check(checker=checker)
    assert check_for(None) == Check()
    assert Check(epsilon=1e-6, ignore_case=True).describe() == (
        "Accepting numbers within 1e-06 and any letter case"
    )
    assert Check().describe() == ""


@pytest.mark.parametrize("limit,timeout", [(None, 10.0), (0.5, 2.5), (1, 3), (2, 6)])
def test_timeout_for(limit, timeout):
    assert judge.timeout_for(limit) == timeout


def test_format_memory():
    assert judge.format_memory(3 * 1024 * 1024 + 100_000) == "3.1 MB"
    assert judge.format_memory(2048) == "2 KB" and judge.format_memory(12) == "12 B"


# ┌──────────────────────────────────────────────────────────┐
# │                        Verdicts                          │
# └──────────────────────────────────────────────────────────┘


def test_passed_and_failed(tmp_path, capsys):
    program = python(tmp_path, "print(int(input()) * 2)")
    tests = samples(tmp_path, ("2\n", "4\n"), ("3\n", "7\n"))
    summary = run_tests(program, tests)
    assert (summary.passed, summary.failed) == (["1"], ["2"])
    out = capsys.readouterr().out
    assert "✓ 1" in out and "✗ 2" in out and "wrong answer" in out
    assert "1 of 2 passed" in out


def test_all_passed(tmp_path, capsys):
    program = python(tmp_path, "print(int(input()) * 2)")
    run_tests(program, samples(tmp_path, ("2\n", "4\n"), ("3\n", "6\n")))
    assert "All 2 passed" in capsys.readouterr().out


def test_a_crash_shows_what_it_printed(tmp_path, capsys):
    program = python(tmp_path, "print('partial', flush=True)\nraise SystemExit(3)")
    run_tests(program, samples(tmp_path, ("\n", "x\n")))
    out = capsys.readouterr().out
    assert "runtime error" in out and "exit status 3" in out and "partial" in out


def test_a_hung_solution_is_stopped(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(judge, "DEFAULT_TIMEOUT", 1.0)
    program = python(tmp_path, "while True: pass")
    summary = run_tests(program, samples(tmp_path, ("\n", "x\n")))
    assert summary.failed == ["1"]
    assert "time limit exceeded (killed after 1s)" in capsys.readouterr().out


def test_limits_are_flagged(tmp_path, capsys):
    program = python(
        tmp_path,
        "import time\nt = time.process_time()\nwhile time.process_time() - t < 0.3: pass\nprint(1)",
    )
    info = ProblemInfo(time_limit=0.1, memory_limit=1)
    run_tests(program, samples(tmp_path, ("\n", "1\n")), info=info)
    out = capsys.readouterr().out
    assert "over the 0.1s limit" in out and "over the 1 MB limit" in out


def test_brackets_stay_literal(tmp_path, capsys):
    program = python(tmp_path, "print('[red]x[/] :x:')")
    run_tests(program, samples(tmp_path, ("\n", "y\n")))
    out = capsys.readouterr().out
    assert "[red]x[/] :x:" in out  # NOTE: neither markup nor emoji


def test_the_statement_rules_are_used(tmp_path, capsys):
    program = python(tmp_path, "print('%.7f' % (1 / 3))")
    tests = samples(tmp_path, ("\n", "0.33333333\n"))
    info = ProblemInfo(epsilon=1e-6)
    run_tests(program, tests, info=info, check=check_for(info))
    out = capsys.readouterr().out
    assert "Accepting numbers within 1e-06" in out and "All 1 passed" in out
    run_tests(program, tests, info=info, check=check_for(info, exact=True))
    assert "0 of 1 passed" in capsys.readouterr().out


def test_another_answer_where_any_is_accepted_only_differs(tmp_path, capsys):
    program = python(tmp_path, "print(1, 0)")
    tests = samples(tmp_path, ("\n", "0 1\n"))
    info = ProblemInfo(any_answer=True)
    summary = run_tests(program, tests, info=info, check=check_for(info))
    out = capsys.readouterr().out
    assert summary.differs == ["1"] and summary.failed == []
    assert "? 1" in out and "differs from the sample's answer" in out and "wrong answer" not in out
    assert "0 of 1 passed, 1 differ from the samples' answers (check them)" in out
    summary = run_tests(program, tests, info=info, check=check_for(info, exact=True))
    assert summary.failed == ["1"]  # NOTE: --exact: the statement's rules don't apply


def test_a_checker(tmp_path, capsys):
    # NOTE: accepts the answer's numbers in any order, as a real checker might
    checker = python(
        tmp_path,
        """
        import sys
        inp, out, ans = (open(p).read().split() for p in sys.argv[1:])
        if sorted(out) != sorted(ans):
            sys.exit('wrong answer: not a permutation')
        print('ok', len(out), 'numbers')
        """,
        "checker.py",
    )
    program = python(tmp_path, "print(*reversed(input().split()))")
    tests = samples(tmp_path, ("1 2 3\n", "1 2 3\n"), ("4 5\n", "4 6\n"))
    summary = run_tests(program, tests, check=check_for(None, checker=checker))
    out = capsys.readouterr().out
    assert summary.passed == ["1"] and summary.failed == ["2"]
    assert "Judging with checker.py" in out and "ok 3 numbers" in out
    assert "checker: wrong answer: not a permutation" in out


def test_tests_without_an_answer(tmp_path, capsys):
    program = python(tmp_path, "print(int(input()) * 2)")
    samples(tmp_path, ("2\n", "4\n"))
    add_test(tmp_path, "21\n", "")
    summary = run_tests(program, tests_of(tmp_path))
    out = capsys.readouterr().out
    assert summary.ran == ["2"] and "42" in out
    assert "All 1 passed, 1 without an answer" in out
    run_tests(program, tests_of(tmp_path), accept=True)
    assert "Kept the output as the answer: 2.ans" in capsys.readouterr().out
    assert (tmp_path / "tests" / "2.ans").read_text() == "42\n"


def test_old_tests_keep_their_names(tmp_path):
    (tmp_path / "in1.txt").write_text("5\n")
    program = python(tmp_path, "print(int(input()) * 2)")
    run_tests(program, tests_of(tmp_path), accept=True)
    assert (tmp_path / "ans1.txt").read_text() == "10\n"


def test_a_multi_test_failure_names_its_case(tmp_path, capsys):
    program = python(tmp_path, "input()\nprint(1)\nprint(3)")
    tests = samples(tmp_path, ("2\n5\n6\n", "1\n2\n"))
    info = ProblemInfo(cases=[([0, 1, 2], [1, 2])])
    run_tests(program, tests, info=info)
    assert "Test case 2 of 2 differs" in capsys.readouterr().out


# ┌──────────────────────────────────────────────────────────┐
# │                      Interactive                         │
# └──────────────────────────────────────────────────────────┘

GUESS = """
import sys
lo, hi = 1, 100
while True:
    mid = (lo + hi) // 2
    print(mid, flush=True)
    answer = input()
    if answer == "=":
        break
    lo, hi = (mid + 1, hi) if answer == ">" else (lo, mid - 1)
"""

INTERACTOR = """
import sys
secret = int(open(sys.argv[1]).read())
for turn in range(10):
    guess = int(input())
    if guess == secret:
        print("=", flush=True)
        sys.exit(0)
    print(">" if secret > guess else "<", flush=True)
sys.stderr.write("too many guesses")
sys.exit(1)
"""


def test_an_interactive_problem(tmp_path, capsys):
    program = python(tmp_path, GUESS)
    interactor = python(tmp_path, INTERACTOR, "interactor.py")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "1.in").write_text("73\n")
    summary = run_tests(program, tests_of(tmp_path), interactor=interactor)
    assert summary.passed == ["1"]
    wrong = python(tmp_path, "while True:\n    print(1, flush=True)\n    input()", "b.py")
    summary = run_tests(wrong, tests_of(tmp_path), interactor=interactor)
    out = capsys.readouterr().out
    assert summary.failed == ["1"] and "wrong answer" in out and "too many guesses" in out


# ┌──────────────────────────────────────────────────────────┐
# │                  Remembered, watched                     │
# └──────────────────────────────────────────────────────────┘


def test_results_are_remembered_by_the_code(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("print(1)\n")
    assert judge.failed_tests(source) == []
    judge.remember(source, judge.Summary(passed=["1"], failed=["2"], ran=[]))
    assert judge.failed_tests(source) == ["2"]
    source.write_text("print(2)\n")  # NOTE: different code, no record
    assert judge.failed_tests(source) == []


def test_watch_runs_again_on_a_change(tmp_path, monkeypatch):
    source = tmp_path / "a.py"
    source.write_text("1")
    runs = []

    def run_once():
        runs.append(1)
        if len(runs) == 1:
            import os

            os.utime(source, (1, 1))  # NOTE: a save after the first run
        else:
            raise KeyboardInterrupt

    judge.watch(lambda: [source], run_once, interval=0.01)
    assert len(runs) == 2


def test_a_test_object_for_inputs_only(tmp_path):
    test = Test("x", tmp_path / "x.in", None)
    assert test.answer is None
