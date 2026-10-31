"""The cf command end to end, offline: a fake client stands in for Codeforces,
real Python programs for your code."""

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from cf_tool import paths, ui, workspace
from cf_tool.cli import common, main
from cf_tool.codeforces import pages
from cf_tool.codeforces.client import FetchedProblem
from cf_tool.codeforces.session import Session
from cf_tool.errors import CFError
from cf_tool.workspace import ProblemInfo, Target

HOST = "https://codeforces.com"
DOUBLE = "print(int(input()) * 2)\n"


class FakeClient:
    """Codeforces, as the commands see it."""

    host = HOST

    def __init__(self, home: Path) -> None:
        self.session = Session(home / "session", handle="tourist")
        self.problems: dict[str, list[FetchedProblem]] = {}
        self.submitted: list[tuple[str, str, str]] = []
        self.logged_in = True
        self.watched: list[tuple] = []
        # what Codeforces says of the next submission, and shows of its tests
        self.verdict = pages.Submission(id=7, lang="PyPy 3-64", status="Accepted", end=True)
        self.details_of: dict[int, pages.SubmissionDetails] = {}
        self.mine: dict[int, Target] = {}  # NOTE: find_submission's answers

    @property
    def handle(self):
        return self.session.handle

    @property
    def can_log_in(self):
        return self.logged_in

    def fetch(self, target):
        return self.problems[target.label]

    def submit(self, target, source, choose_language, filename=""):
        lang_id, name = choose_language(
            {
                "91": "GNU G++23 14.2 (64 bit, msys2)",
                "70": "PyPy 3.10 (7.3.15, 64bit)",
                "31": "Python 3.13.2",
            }
        )
        self.submitted.append((filename, target.label, lang_id))
        return self.verdict

    def details(self, target, submission_id):
        return self.details_of.get(submission_id)

    def find_submission(self, submission_id):
        return self.mine.get(submission_id)

    def watch(self, target, count=10, problem="", single=False):
        self.watched.append((target.label, count, problem))
        return []

    def languages(self):
        from cf_tool import languages

        return languages.known_languages(), False

    def race(self, target):
        pass


def problem(contest: str, index: str, *samples: tuple[str, str]) -> FetchedProblem:
    url = f"{HOST}/contest/{contest}/problem/{index}"
    return FetchedProblem(
        index, ProblemInfo(name=f"{index}. Test", url=url, time_limit=2.0), list(samples)
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty cf-tool: its folders in tmp_path, a fake client, cwd in work/."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / ".config" / "cf")
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / ".local" / "state" / "cf")
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / ".cache" / "cf")
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    opened: list[str] = []
    common.reset()
    fake = FakeClient(tmp_path)
    common._client = fake
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    yield {"client": fake, "work": work, "opened": opened, "home": tmp_path}
    common.reset()


def settings_file(text: str) -> None:
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(text)
    common._settings = None


def python_language() -> None:
    """Python, run with this interpreter."""
    settings_file(f'language = "py"\n[py]\nrun = "{sys.executable} {{src}}"\n')


def run(*args: str, input: str | None = None):
    return CliRunner().invoke(main, list(args), input=input)


# ┌──────────────────────────────────────────────────────────┐
# │                        The basics                        │
# └──────────────────────────────────────────────────────────┘


def test_help_lists_the_new_names_only():
    result = run("--help")
    assert result.exit_code == 0
    for name in ("get", "test", "submit", "status", "open", "problems", "new", "langs"):
        assert f"  {name} " in result.output
    for old in ("parse", "gen", "watch", "stand", "sid"):
        assert f"  {old} " not in result.output


def test_version_as_cp_editor_reads_it():
    output = run("--version").output
    version = re.search(r"(?<=v)\d+\.\d+\.\d+", output).group()  # NOTE: CP Editor's regex
    assert version.split(".")[0] == "1"  # NOTE: so it submits with: cf submit -f <file> <url>


def test_old_settings_move_on_the_first_run(home):
    old = {"template": [{"alias": "py", "lang": "31", "suffix": ["py"], "path": ""}], "default": 0}
    (paths.CONFIG_DIR).mkdir(parents=True)
    (paths.CONFIG_DIR / "config").write_text(json.dumps(old))
    result = run("doctor")
    assert "Moved your settings" in result.output
    assert 'language = "py"' in paths.config_file().read_text()


# ┌──────────────────────────────────────────────────────────┐
# │                         cf get                           │
# └──────────────────────────────────────────────────────────┘


def test_get_a_contest(home):
    python_language()
    home["client"].problems["contest 2050"] = [
        problem("2050", "A", ("2\n", "4\n"), ("3\n", "6\n")),
        problem("2050", "B", ("1\n", "2\n")),
    ]
    result = run("get", "2050")
    assert result.exit_code == 0, result.output
    folder = home["work"] / "2050" / "a"
    assert [t.name for t in workspace.tests_of(folder)] == ["1", "2"]
    assert workspace.load_info(folder).target == Target("contest", "2050", "A")
    code = (folder / "a.py").read_text()
    assert "# A. Test" in code and f"# {HOST}/contest/2050/problem/A" in code
    assert (home["work"] / "2050" / "b" / "b.py").exists()
    assert "→ cd 2050/a, then cf test and cf submit there" in result.output


def test_get_keeps_the_statement(home):
    python_language()
    fetched = problem("2050", "A", ("2\n", "4\n"))
    fetched.statement = "# A. Test\n\nDouble it.\n"
    home["client"].problems["contest 2050"] = [fetched, problem("2050", "B", ("1\n", "2\n"))]
    assert run("get", "2050").exit_code == 0
    assert (home["work"] / "2050" / "a" / "statement.md").read_text() == "# A. Test\n\nDouble it.\n"
    assert not (home["work"] / "2050" / "b" / "statement.md").exists()  # NOTE: none was read


def test_get_again_keeps_your_code(home):
    python_language()
    home["client"].problems["2050A"] = [problem("2050", "A", ("2\n", "4\n"))]
    run("get", "2050a")
    code = home["work"] / "2050" / "a" / "a.py"
    code.write_text("mine\n")
    assert run("get", "2050a").exit_code == 0
    assert code.read_text() == "mine\n"


def test_get_from_inside_a_contest_puts_the_next_one_beside_it(home, monkeypatch):
    python_language()
    home["client"].problems["2050A"] = [problem("2050", "A", ("1\n", "2\n"))]
    home["client"].problems["2051A"] = [problem("2051", "A", ("1\n", "2\n"))]
    run("get", "2050a")
    monkeypatch.chdir(home["work"] / "2050" / "a")
    assert run("get", "2051a").exit_code == 0
    assert (home["work"] / "2051" / "a" / "tests" / "1.in").exists()


def test_the_first_get_asks_for_a_language(home, monkeypatch):
    asked = []

    def select(message, choices, *, default=None, search=False):
        asked.append(message)
        return "py"

    monkeypatch.setattr(ui, "select", select)
    monkeypatch.setattr(ui, "interactive", lambda: True)
    home["client"].problems["4A"] = [problem("4", "A", ("8\n", "YES\n"))]
    assert run("get", "4a").exit_code == 0
    assert asked and "Which language" in asked[0]
    assert (home["work"] / "4" / "a" / "a.py").exists()
    assert 'language = "py"' in paths.config_file().read_text()
    assert run("get", "4a", "-l", "cpp").exit_code == 0  # NOTE: this once, no question
    assert len(asked) == 1 and (home["work"] / "4" / "a" / "a.cpp").exists()


def test_off_a_terminal_the_first_get_writes_cpp(home):
    home["client"].problems["4A"] = [problem("4", "A", ("8\n", "YES\n"))]
    result = run("get", "4a")
    assert result.exit_code == 0 and "No language picked yet: writing C++" in result.output
    assert (home["work"] / "4" / "a" / "a.cpp").exists()
    assert not paths.config_file().exists()  # NOTE: nothing was picked, so nothing saved


def test_get_needs_a_contest(home):
    result = run("get")
    assert result.exit_code == 1 and "Which contest or problem?" in result.output


# ┌──────────────────────────────────────────────────────────┐
# │                         cf test                          │
# └──────────────────────────────────────────────────────────┘


@pytest.fixture
def contest(home):
    """Contest 2050 got, with a right a.py and a wrong b.py."""
    python_language()
    home["client"].problems["contest 2050"] = [
        problem("2050", "A", ("2\n", "4\n"), ("3\n", "6\n")),
        problem("2050", "B", ("2\n", "4\n")),
    ]
    run("get", "2050")
    (home["work"] / "2050" / "a" / "a.py").write_text(DOUBLE)
    (home["work"] / "2050" / "b" / "b.py").write_text("print(5)\n")
    return home


def test_test_in_the_problem_folder(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    result = run("test")
    assert result.exit_code == 0, result.output
    assert "✓ 1" in result.output and "✓ 2" in result.output and "All 2 passed" in result.output


def test_a_failing_test_fails_the_command(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "b")
    result = run("test")
    assert result.exit_code == 1 and "wrong answer" in result.output


def test_an_output_that_only_differs_is_not_confirmed(contest, monkeypatch):
    folder = contest["work"] / "2050" / "b"
    info = workspace.load_info(folder)
    info.any_answer = True
    workspace.save_info(folder, info)
    monkeypatch.chdir(folder)
    result = run("test")
    assert result.exit_code == 1 and "differs from the sample's answer" in result.output


def test_test_another_problem_of_the_contest(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050")
    assert run("test", "a").exit_code == 0
    monkeypatch.chdir(contest["work"] / "2050" / "b")
    result = run("test", "a")  # NOTE: from a sibling problem's folder
    assert result.exit_code == 0, result.output
    assert run("test", "2050a").exit_code == 0


def test_test_chosen_tests(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    result = run("test", "2")
    assert "✓ 2" in result.output and "✓ 1" not in result.output
    result = run("test", "7")
    assert result.exit_code == 1 and "No test 7 here (there are 1, 2)" in result.output


def test_test_add(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    result = run("test", "--add", input="5\n")
    assert result.exit_code == 0, result.output
    assert "Added the test 3" in result.output and "no answer to compare with" in result.output
    assert (contest["work"] / "2050" / "a" / "tests" / "3.in").read_text() == "5\n"


def test_test_outside_any_problem(home):
    result = run("test")
    assert result.exit_code == 1 and "Not in a problem's folder" in result.output


def test_test_an_interactive_problem_without_an_interactor(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    info = workspace.load_info(folder)
    info.interactive = True
    workspace.save_info(folder, info)
    monkeypatch.chdir(folder)
    result = run("test")
    assert result.exit_code == 1 and "This problem is interactive" in result.output


def test_test_an_old_folder(home, monkeypatch):
    python_language()
    folder = home["work"] / "cf" / "contest" / "4" / "a"
    folder.mkdir(parents=True)
    (folder / "in1.txt").write_text("4\n")
    (folder / "ans1.txt").write_text("8\n")
    (folder / "a.py").write_text(DOUBLE)
    monkeypatch.chdir(folder)
    result = run("test")
    assert result.exit_code == 0 and "All 1 passed" in result.output


def test_an_interactor_in_the_folder_is_used(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    (folder / "interactor.py").write_text(
        "import sys\nsecret = open(sys.argv[1]).read().split()[0]\n"
        "print(secret, flush=True)\nsys.exit(0 if input() == str(int(secret) * 2) else 1)\n"
    )
    monkeypatch.chdir(folder)
    result = run("test")  # NOTE: not marked interactive, but there is an interactor
    assert result.exit_code == 0, result.output
    assert "All 2 passed" in result.output


def test_watch_compares_with_an_answer_it_accepted(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    (folder / "tests" / "1.ans").unlink()

    def watch(files, run_once):
        run_once()  # NOTE: accepts 4 as the answer of test 1
        (folder / "a.py").write_text("print(5)\n")
        run_once()

    monkeypatch.setattr("cf_tool.cli.testing.judge.watch", watch)
    monkeypatch.chdir(folder)
    result = run("test", "-w", "--accept")
    assert "Kept the output as the answer: 1.ans" in result.output
    assert result.output.count("Kept the output") == 1 and "wrong answer" in result.output
    assert (folder / "tests" / "1.ans").read_text() == "4\n"


def test_stress_with_named_programs(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    (folder / "mygen.py").write_text("import sys\nprint(sys.argv[1])\n")
    (folder / "slow.py").write_text(DOUBLE)
    monkeypatch.chdir(folder)
    result = run("stress", "mygen.py", "slow.py", "-n", "5")  # NOTE: neither is the solution
    assert result.exit_code == 0, result.output
    assert "All 5 tests passed" in result.output


def test_a_checker_command_s_file_is_not_taken_for_the_code(contest, monkeypatch):
    folder = contest["work"] / "2050" / "b"  # NOTE: b.py prints 5, never the answer
    (folder / "checkA.py").write_text("import sys\nsys.exit(0)\n")
    monkeypatch.chdir(folder)
    result = run("test", "--checker", f"{sys.executable} checkA.py")  # NOTE: a full path first
    assert result.exit_code == 0, result.output
    assert f"Judging with {sys.executable} checkA.py" in " ".join(result.output.split())


def test_helpers_are_known_by_the_start_of_their_names(contest, monkeypatch):
    folder = contest["work"] / "2050" / "b"
    (folder / "check_b.py").write_text("import sys\nsys.exit(0)\n")
    (folder / "brute_b.py").write_text("print(4)\n")
    monkeypatch.chdir(folder)
    result = run("test")  # NOTE: b.py is the only code; check_b.py judges
    assert result.exit_code == 0, result.output
    assert "Judging with check_b.py" in result.output


def test_stress_finds_its_helpers(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    (folder / "gen.py").write_text("import sys\nprint(int(sys.argv[1]) % 7)\n")
    (folder / "brute.py").write_text(DOUBLE)
    (folder / "a.py").write_text("n = int(input())\nprint(n * 2 + (n == 5))\n")
    monkeypatch.chdir(folder)
    result = run("stress", "-n", "20")
    assert result.exit_code == 1 and "Wrong answer on the test from seed 5" in result.output
    assert (folder / "tests" / "stress-5.in").read_text() == "5\n"


# ┌──────────────────────────────────────────────────────────┐
# │                        cf submit                         │
# └──────────────────────────────────────────────────────────┘


@pytest.fixture
def fake_submit(home, monkeypatch):
    """cf submit up to the network: records the questions and the file menus,
    answers confirmations from record["answers"] and menus with record["pick"]."""
    python_language()
    record = {"questions": [], "answers": [], "menus": [], "pick": None, "terminal": True}

    def confirm(message, *, default=False):
        record["questions"].append((message, default))
        return record["answers"].pop(0) if record["answers"] else default

    def select(message, choices, *, default=None, search=False):
        files = [c[1] for c in choices if not isinstance(c, ui.Heading)]
        record["menus"].append([f.name for f in files])
        return next(f for f in files if f.name == record["pick"]) if record["pick"] else default

    monkeypatch.setattr(ui, "confirm", confirm)
    monkeypatch.setattr(ui, "select", select)
    monkeypatch.setattr(ui, "interactive", lambda: record["terminal"])
    record["dir"] = home["work"]
    record["submitted"] = home["client"].submitted
    return record


def make_code(root: Path, *names: str) -> None:
    """Code files, each modified a second after the one before."""
    for i, name in enumerate(names):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print(1)\n")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))


def test_submit_offers_the_files_best_first(fake_submit):
    make_code(fake_submit["dir"], "2171A.py", "546D.py", "demo.py")
    result = run("submit", "546D")
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == [["546D.py", "demo.py", "2171A.py"]]
    assert fake_submit["submitted"] == [("546D.py", "546D", "70")]
    assert fake_submit["questions"] == []


def test_submit_another_file_from_the_menu(fake_submit):
    make_code(fake_submit["dir"], "546D.py", "demo.py")
    fake_submit["pick"] = "demo.py"
    assert run("submit", "546D").exit_code == 0
    assert fake_submit["submitted"] == [("demo.py", "546D", "70")]


def test_submit_from_inside_the_problem_folder(fake_submit, monkeypatch):
    make_code(fake_submit["dir"], str(Path("546", "D", "solution.py")), "546D.py")
    monkeypatch.chdir(fake_submit["dir"] / "546" / "D")
    result = run("submit", "546D")
    assert result.exit_code == 0, result.output
    up = str(Path("..", "..", "546D.py"))
    assert fake_submit["menus"] == [[up, "solution.py"]]
    assert fake_submit["submitted"] == [(up, "546D", "70")]


def test_submit_in_a_problem_folder_made_by_get(fake_submit, monkeypatch):
    folder = fake_submit["dir"] / "2050" / "a"
    workspace.save_info(folder, ProblemInfo(url=f"{HOST}/contest/2050/problem/A"))
    make_code(folder, "brute.py", "gen.py", "a.py")
    monkeypatch.chdir(folder)
    result = run("submit")
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == []  # NOTE: the helpers are no candidates
    assert fake_submit["submitted"] == [("a.py", "2050A", "70")]
    monkeypatch.chdir(fake_submit["dir"] / "2050")
    assert run("submit", "a").exit_code == 0
    assert fake_submit["submitted"][-1][1:] == ("2050A", "70")


def test_submit_reads_the_target_off_the_name_after_a_yes(fake_submit):
    (fake_submit["dir"] / "546D.py").write_text("print(1)\n")
    result = run("submit")
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("546D.py", "546D", "70")]
    assert fake_submit["questions"] == [("Submit 546D.py to 546D?", True)]


def test_submit_guards_against_another_problems_file(fake_submit):
    (fake_submit["dir"] / "2171A.py").write_text("print(1)\n")
    result = run("submit", "-f", "2171A.py", "546D")
    assert result.exit_code == 1 and "Not submitted" in result.output
    message, default = fake_submit["questions"][0]
    assert "2171A.py looks like 2171A" in message and default is False
    fake_submit["answers"].append(True)
    assert run("submit", "-f", "2171A.py", "546D").exit_code == 0
    assert fake_submit["submitted"] == [("2171A.py", "546D", "70")]


def test_submit_as_cp_editor_calls_it(fake_submit):
    fake_submit["terminal"] = False  # NOTE: CP Editor runs cf without a terminal
    make_code(fake_submit["dir"], "sol.py", "other.py", "B.py")
    full_path = str(fake_submit["dir"] / "sol.py")
    result = run("submit", "546", "D", full_path)
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [(full_path, "546D", "70")]
    named_for_b = str(fake_submit["dir"] / "B.py")  # NOTE: both named: taken as meant
    result = run("submit", "546", "D", named_for_b)
    # NOTE: a long temporary path makes the line wrap
    assert result.exit_code == 0 and "submitting it to 546D as asked" in " ".join(
        result.output.split()
    )
    assert fake_submit["menus"] == [] and fake_submit["questions"] == []


@pytest.mark.parametrize(
    "url",
    [
        "https://codeforces.com/contest/546/problem/D",
        "https://codeforces.com/problemset/problem/546/D",
    ],
)
def test_submit_as_cp_editor_calls_cf_1(fake_submit, url):
    fake_submit["terminal"] = False
    make_code(fake_submit["dir"], "sol.py", "other.py")
    full_path = str(fake_submit["dir"] / "sol.py")
    result = run("submit", "-f", full_path, url)
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [(full_path, "546D", "70")]
    assert fake_submit["menus"] == [] and fake_submit["questions"] == []


def test_off_a_terminal_nothing_is_asked(fake_submit):
    fake_submit["terminal"] = False
    make_code(fake_submit["dir"], "546D.py")
    result = run("submit")  # NOTE: the problem would be read off the name
    assert (
        result.exit_code == 1 and "Which problem? Name it: cf submit 546D 546D.py" in result.output
    )
    make_code(fake_submit["dir"], "546D.py", "546D_v2.py")
    result = run("submit", "546D")
    assert result.exit_code == 1 and "Several code files could be meant" in result.output
    assert fake_submit["questions"] == [] and fake_submit["menus"] == []
    settings_file(f'language = "py"\n[py]\nrun = "{sys.executable} {{src}}"\nsubmit = "99"\n')
    result = run("submit", "546D", "546D.py")  # NOTE: 99 isn't offered: the family's best
    assert result.exit_code == 0, result.output
    assert "submitting as PyPy 3.10" in result.output
    assert fake_submit["submitted"][-1] == ("546D.py", "546D", "70")


def failed_on_test_3(cut: bool = False) -> pages.SubmissionDetails:
    detail = pages.TestDetail(3, "WRONG_ANSWER", "5\n" + "..." * cut, "9\n", "10\n", "wrong 1st")
    return pages.SubmissionDetails("Wrong answer on test 3", "(D) Test", detail)


def test_submit_shows_and_keeps_the_failed_test(fake_submit, home):
    folder = home["work"] / "546" / "d"
    folder.mkdir(parents=True)
    workspace.save_info(folder, ProblemInfo(url=f"{HOST}/contest/546/problem/D"))
    make_code(folder, "d.py")
    home["client"].verdict = pages.Submission(
        id=8, lang="PyPy 3-64", status="Wrong answer on test 3"
    )
    home["client"].details_of[8] = failed_on_test_3()
    result = run("submit", "546D", str(folder / "d.py"))
    assert result.exit_code == 0, result.output  # NOTE: CP Editor takes 1 for cf failing
    out = " ".join(result.output.split())
    assert "── test 3 ──" in out and "checker: wrong 1st" in out
    assert "Saved it as the test cf-3: cf test cf-3 runs it again" in out
    assert (folder / "tests" / "cf-3.in").read_text() == "5\n"
    assert (folder / "tests" / "cf-3.ans").read_text() == "10\n"


def test_a_cut_failed_test_is_shown_not_kept(fake_submit, home):
    folder = home["work"] / "546" / "d"
    folder.mkdir(parents=True)
    workspace.save_info(folder, ProblemInfo(url=f"{HOST}/contest/546/problem/D"))
    make_code(folder, "d.py")
    home["client"].verdict = pages.Submission(
        id=8, lang="Python 3", status="Wrong answer on test 3"
    )
    home["client"].details_of[8] = failed_on_test_3(cut=True)
    result = run("submit", "546D", str(folder / "d.py"))
    assert "cut short by Codeforces" in result.output and "Saved it" not in result.output
    assert not (folder / "tests").exists()


def test_cpython_over_a_limit_hears_of_pypy(fake_submit, home):
    make_code(fake_submit["dir"], "546D.py")
    home["client"].verdict = pages.Submission(
        id=9, lang="Python 3", status="Time limit exceeded on pretest 5"
    )
    result = run("submit", "546D", "546D.py")
    assert "cf submit -l pypy" in result.output and "── test" not in result.output


def test_status_of_one_submission(home):
    home["client"].mine[396876324] = Target("contest", "546", "D")
    home["client"].details_of[396876324] = failed_on_test_3()
    result = run("status", "396876324")
    assert result.exit_code == 0, result.output
    assert "Wrong answer on test 3" in result.output and "── test 3 ──" in result.output
    result = run("status", "396876325")
    assert result.exit_code == 1 and "isn't among your latest ones" in result.output


def test_submit_with_the_file_as_an_argument(fake_submit):
    make_code(fake_submit["dir"], "546D.py", "demo.py")
    assert run("submit", "demo.py", "546D").exit_code == 0
    assert fake_submit["submitted"] == [("demo.py", "546D", "70")]
    result = run("submit", "-f", "demo.py", "546D.py", "546D")
    assert result.exit_code == 1 and "Give the code file once" in result.output


def test_submit_in_the_language_asked_for(fake_submit):
    make_code(fake_submit["dir"], "546D.py")
    assert run("submit", "546D", "-l", "Python 3").exit_code == 0
    assert fake_submit["submitted"] == [("546D.py", "546D", "31")]


def test_submit_warns_about_code_that_failed(fake_submit, monkeypatch):
    from cf_tool import judge

    make_code(fake_submit["dir"], "546D.py")
    judge.remember(fake_submit["dir"] / "546D.py", judge.Summary([], ["2"], []))
    monkeypatch.setattr(ui, "interactive", lambda: True)
    result = run("submit", "546D")
    assert result.exit_code == 1 and "Not submitted" in result.output
    assert "This code failed the test 2 in cf test" in fake_submit["questions"][0][0]


def test_login_reads_a_piped_password_quietly(home):
    logins = []
    home["client"].login = lambda who, password: logins.append((who, password))
    result = run("login", input="Fau915\nsecret\n")
    assert result.exit_code == 0, result.output
    assert logins == [("Fau915", "secret")]
    assert "echo" not in result.output and "secret" not in result.output


def test_submit_without_a_login(fake_submit, home):
    fake_submit["terminal"] = False
    make_code(fake_submit["dir"], "546D.py")
    home["client"].logged_in = False
    result = run("submit", "546D")
    assert result.exit_code == 1 and "Not logged in: run cf login" in result.output


# ┌──────────────────────────────────────────────────────────┐
# │                     Other commands                       │
# └──────────────────────────────────────────────────────────┘


def test_new(contest, monkeypatch):
    folder = contest["work"] / "2050" / "a"
    (folder / "a.py").unlink()
    monkeypatch.chdir(folder)
    result = run("new")
    assert result.exit_code == 0, result.output
    assert "# A. Test" in (folder / "a.py").read_text()
    assert run("new").exit_code == 1  # NOTE: a.py exists
    templates = paths.templates_dir()
    templates.mkdir(parents=True)
    (templates / "brute.py").write_text("# brute for {{name}}\n")
    assert run("new", "brute.py").exit_code == 0
    assert (folder / "brute.py").read_text() == "# brute for A. Test\n"


def test_open(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    assert run("open").exit_code == 0
    assert run("open", "-s").exit_code == 0
    assert run("stand", "2051").exit_code == 0  # NOTE: cf-tool 0.3's name
    assert contest["opened"] == [
        f"{HOST}/contest/2050/problem/A",
        f"{HOST}/contest/2050/standings",
        f"{HOST}/contest/2051/standings",
    ]


def test_open_the_last_submission(home):
    result = run("open", "--last")
    assert result.exit_code == 1 and "No submission yet" in result.output
    home["client"].session.last_submission = {
        "kind": "gym",
        "contest": "100001",
        "problem": "B",
        "group": "",
        "submission": "77",
    }
    assert run("sid").exit_code == 0
    assert home["opened"] == [f"{HOST}/gym/100001/submission/77"]


def test_status_and_its_old_name(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    assert run("status").exit_code == 0
    assert run("watch", "--all").exit_code == 0
    assert run("watch", "all").exit_code == 0  # NOTE: as cf-tool 0.3 said it
    assert contest["client"].watched == [("2050A", 10, "A"), ("2050A", -1, "A"), ("2050A", -1, "A")]


def test_langs(home):
    result = run("langs")
    assert result.exit_code == 0, result.output
    for name in ("C++", "Python", "Rust", "built-in"):
        assert name in result.output


def test_config_path(home):
    result = run("config", "--path")
    assert result.output.strip() == str(paths.config_file())


def test_config_opens_a_broken_file_to_fix_it(home, monkeypatch):
    settings_file("language = \n")
    edited = []

    def edit(filename):
        edited.append(filename)
        Path(filename).write_text('language = "py"\n')  # NOTE: fixed in the editor

    monkeypatch.setattr("click.edit", edit)
    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(ui, "confirm", lambda message, *, default=False: True)
    result = run("config")
    assert result.exit_code == 0, result.output
    assert "isn't valid TOML" in result.output and "Saved" in result.output
    assert edited == [str(paths.config_file())]
    assert run("config", "--path").exit_code == 0


@pytest.fixture
def menu(home, monkeypatch):
    """cf config's menu, answered from menu["answers"]: per question, a
    function of its message and choices returning the value to pick."""
    record = {"answers": [], "asked": [], "texts": []}

    def select(message, choices, *, default=None, search=False):
        options = [c for c in choices if not isinstance(c, ui.Heading)]
        record["asked"].append((message, [label for label, _ in options], default))
        answer = record["answers"].pop(0)
        return answer(message, options) if callable(answer) else answer

    def text(message, *, default="", validate=None, allow_empty=True):
        return record["texts"].pop(0)

    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(ui, "select", select)
    monkeypatch.setattr(ui, "text", text)
    return record


def by_label(part):
    """An answer: the choice whose label has part in it."""
    return lambda message, options: next(value for label, value in options if part in label)


def test_config_menu_first_choices_are_recommended(menu):
    settings_file('language = "py"\n')
    menu["answers"] = [by_label("Submitted as"), by_label("Python 3.13"), "done"]
    assert run("config").exit_code == 0
    rows = menu["asked"][0][1]
    first = rows.index(next(row for row in rows if row.startswith("Submitted as")))
    assert "recommended" in rows[first] and "PyPy 3.10" in rows[first]  # NOTE: Python's, first
    message, labels, default = menu["asked"][1]
    assert labels[0].startswith("PyPy 3.10 (7.3.15, 64bit)") and "recommended" in labels[0]
    assert default == ""
    assert 'submit = "31"' in paths.config_file().read_text()  # NOTE: saved by its id
    menu["answers"] = [by_label("Submitted as"), by_label("recommended"), "done"]
    assert run("config").exit_code == 0
    assert "submit" not in paths.config_file().read_text().split("[py]")[-1]


def test_config_menu_build_and_run(menu):
    python_language()
    menu["answers"] = [by_label("Build and run"), "flags", "done"]
    menu["texts"] = ["-X dev"]
    assert run("config").exit_code == 0
    text = paths.config_file().read_text()
    assert 'flags = "-X dev"' in text and "run =" not in text  # NOTE: python_language's run went
    menu["answers"] = [by_label("Build and run"), "own", "done"]
    menu["texts"] = ["", "pypy3 {src}"]
    assert run("config").exit_code == 0
    conf = common.settings().language_settings("py")
    assert (conf.build, conf.run, conf.flags) == ((), ("pypy3", "{src}"), ())
    menu["answers"] = [by_label("Build and run"), "", "done"]
    assert run("config").exit_code == 0
    conf = common.settings().language_settings("py")
    assert (conf.build, conf.run, conf.flags) == (None, None, ())


def test_config_menu_starter_and_proxy(menu):
    settings_file('language = "cpp"\n')
    menu["answers"] = [by_label("Starter code"), "copy", by_label("Proxy"), "done"]
    menu["texts"] = ["socks5://127.0.0.1:1080"]
    assert run("config").exit_code == 0
    copied = paths.templates_dir() / "template.cpp"
    assert "bits/stdc++.h" in copied.read_text()
    assert common.settings().proxy == "socks5://127.0.0.1:1080"
    menu["answers"] = [by_label("Proxy"), by_label("Language for new"), "go", "done"]
    menu["texts"] = [""]
    assert run("config").exit_code == 0
    assert common.settings().proxy == "" and common.settings().language == "go"


def test_config_menu_needs_a_terminal(home):
    result = run("config")
    assert result.exit_code == 0 and "needs a terminal" in result.output


def test_contests(home, monkeypatch):
    now = time.time()
    home["client"].contests = lambda: [
        pages.Contest(2278, "Codeforces Round", int(now) + 3600, 7200, "BEFORE")
    ]
    result = run("contests", "--ics", "rounds.ics")
    assert result.exit_code == 0, result.output
    assert "Codeforces Round" in result.output
    assert "BEGIN:VCALENDAR" in (home["work"] / "rounds.ics").read_text()


def test_pick(home):
    home["client"].problemset = lambda: [
        pages.ProblemsetProblem(4, "A", "Watermelon", 800, ("math",))
    ]
    home["client"].solved = lambda handle: set()
    result = run("pick", "-r", "800")
    assert result.exit_code == 0 and "4A" in result.output and "Watermelon" in result.output
    result = run("pick", "-r", "3000")
    assert result.exit_code == 1 and "No problem you haven't solved matches" in result.output


@pytest.mark.parametrize(
    "older,newer",
    [
        ("0.3.0a1", "0.3.0a2"),
        ("0.3.0a2", "0.3.0b1"),
        ("0.3.0b1", "v0.3.0rc1"),
        ("0.3.0-rc.1", "0.3.0"),
        ("0.3.0", "0.3.1a1"),
        ("0.3", "0.3.0.1"),
        ("v0.9.9", "1.0.0"),
    ],
)
def test_version_order(older, newer):
    from cf_tool.cli.setup import version_key

    assert version_key(older) < version_key(newer)


class _Releases:
    def __init__(self, releases, status=200):
        self.releases, self.status_code = releases, status

    def json(self):
        return self.releases


def _upgrade_with(monkeypatch, releases, current, status=200, sent=None):
    from curl_cffi import requests as curl_requests

    import cf_tool.cli.setup as setup_module

    def get(url, timeout, headers):
        if sent is not None:
            sent.update(headers)
        return _Releases(releases, status)

    monkeypatch.setattr(setup_module, "__version__", current)
    monkeypatch.setattr(curl_requests, "get", get)
    return run("upgrade")


RELEASES = [
    {"tag_name": "v0.3.0a2", "prerelease": True, "draft": False},
    {"tag_name": "v0.4.0", "prerelease": False, "draft": True},  # NOTE: drafts never count
    {"tag_name": "v0.3.0a1", "prerelease": True, "draft": False},
]


def test_upgrade(monkeypatch):
    sent = {}
    result = _upgrade_with(monkeypatch, RELEASES, "0.3.0a1", sent=sent)
    assert "Latest version is v0.3.0a2" in result.output
    assert sent["User-Agent"] == "cf-tool/0.3.0a1"  # NOTE: without one GitHub's API answers 403
    assert "You already have the latest" in _upgrade_with(monkeypatch, RELEASES, "0.3.0a2").output
    result = _upgrade_with(monkeypatch, RELEASES, "0.2.0")
    assert result.exit_code == 1 and "No release" in result.output
    result = _upgrade_with(monkeypatch, [], "0.3.0a1", status=404)
    assert result.exit_code == 1 and "Cannot list the releases" in result.output
    stable = [{"tag_name": "v1.0.1", "prerelease": False, "draft": False}]
    result = _upgrade_with(monkeypatch, stable, "1.0.0")
    assert "uv tool upgrade cf-tool-cli" in result.output and "@v1.0.1" in result.output


# ┌──────────────────────────────────────────────────────────┐
# │                     Tab completion                       │
# └──────────────────────────────────────────────────────────┘


def _items(args: list[str], incomplete: str):
    """What Tab offers after `cf <args> <incomplete>`."""
    from click.shell_completion import ShellComplete

    return ShellComplete(main, {}, "cf", "_CF_COMPLETE").get_completions(args, incomplete)


def _completions(args: list[str], incomplete: str) -> list[str]:
    return [item.value for item in _items(args, incomplete)]


def _helps(args: list[str], incomplete: str) -> list[str]:
    """What zsh and fish show beside each completion."""
    return [item.help for item in _items(args, incomplete)]


def test_complete_commands():
    assert _completions([], "su") == ["submit"]


def test_complete_problems_and_tests(contest, monkeypatch):
    monkeypatch.chdir(contest["work"] / "2050")
    assert _completions(["test"], "") == ["a", "b", "2050"]
    monkeypatch.chdir(contest["work"] / "2050" / "a")
    assert _completions(["test"], "") == ["1", "2", "a", "b", "2050", "2050A", "a.py"]
    (contest["work"] / "546D.py").write_text("")
    monkeypatch.chdir(contest["work"])
    assert _completions(["get"], "5") == ["546D"]


def test_complete_contests_around_not_every_number(contest, monkeypatch):
    (contest["work"] / "546D.py").write_text("")
    (contest["work"] / "notes.txt").write_text("")
    monkeypatch.chdir(contest["work"])
    assert _completions(["submit"], "") == ["2050", "546D", "546D.py"]  # NOTE: no notes.txt
    assert _completions(["submit"], "2050") == ["2050", "2050a", "2050b"]
    assert _completions(["submit", "2050"], "") == ["a", "b", "546D.py"]  # NOTE: its problems
    assert _helps(["submit", "2050"], "")[:2] == ["A. Test", "B. Test"]
    assert [item.type for item in _items(["submit"], "../")] == ["file"]  # NOTE: a path


def test_complete_contests_on_now_for_cf_get(home, monkeypatch):
    now = int(time.time())
    listed = [
        {"id": 2282, "name": "Upcoming", "phase": "BEFORE", "startTimeSeconds": now + 3600},
        {"id": 2290, "name": "Next month", "phase": "BEFORE", "startTimeSeconds": now + 9**7},
        {"id": 2281, "name": "Running", "phase": "CODING", "startTimeSeconds": now - 600},
        {"id": 2275, "name": "Over", "phase": "FINISHED", "startTimeSeconds": now - 9**5},
    ]
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (paths.STATE_DIR / "contests.json").write_text(json.dumps({"result": listed}))
    assert _completions(["get"], "") == ["2282", "2281", "2275"]
    assert _helps(["get"], "228") == ["Upcoming", "Running"]


def test_completion_script_is_only_the_script(home):
    (paths.CONFIG_DIR).mkdir(parents=True)
    (paths.CONFIG_DIR / "config").write_text("{}")  # NOTE: an old config to move
    result = run("completion", "zsh")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("#compdef cf") and "_CF_COMPLETE" in result.output
    assert not paths.config_file().exists()  # NOTE: moved by the next command, not this one


def test_completion_follows_the_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
    result = run("completion")
    assert result.exit_code == 0 and "complete" in result.output
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    result = run("completion")
    assert result.exit_code != 0 and "Cannot tell your shell" in result.output


def test_a_question_without_anyone_to_ask_takes_the_default(monkeypatch):
    monkeypatch.setattr(ui, "interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(EOFError))
    assert ui.confirm("Submit it?", default=True) is True
    assert ui.confirm("Submit it anyway?", default=False) is False


def test_errors_are_one_red_line(home):
    result = run("submit", "-f", "nope.py", "4a")
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert isinstance(CFError("x"), Exception)


def test_race_waits_for_the_problems_to_show(home, monkeypatch):
    python_language()
    answers = [[], [], [problem("2050", "A", ("1\n", "2\n"))]]
    home["client"].fetch = lambda target: answers.pop(0)
    slept = []
    monkeypatch.setattr("cf_tool.cli.problems.time.sleep", lambda seconds: slept.append(seconds))
    result = run("race", "2050")
    assert result.exit_code == 0, result.output
    assert slept == [2, 2] and home["opened"] == [f"{HOST}/contest/2050/problems"]
    assert (home["work"] / "2050" / "a" / "tests" / "1.in").exists()


def test_a_language_no_longer_offered_is_picked_again(home, monkeypatch):
    settings_file(f'language = "py"\n[py]\nrun = "{sys.executable} {{src}}"\nsubmit = "99"\n')
    make_code(home["work"], "546D.py")
    menus = []

    def select(message, choices, *, default=None, search=False):
        menus.append((message, [label for label, _ in choices]))
        return "31"

    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(ui, "select", select)
    monkeypatch.setattr(ui, "confirm", lambda message, *, default=False: True)
    result = run("submit", "546D")
    assert result.exit_code == 0, result.output
    message, labels = menus[0]
    assert "Codeforces doesn't offer 99 here" in message
    assert labels == ["PyPy 3.10 (7.3.15, 64bit)", "Python 3.13.2", "Don't submit"]
    assert home["client"].submitted == [("546D.py", "546D", "31")]
    assert 'submit = "31"' in paths.config_file().read_text()  # NOTE: kept, after a yes


def test_config_menu_is_one_list(menu, monkeypatch):
    settings_file('language = "cpp"\n')

    def esc(message, options):
        raise ui.Canceled()

    menu["answers"] = [by_label("Compiler"), esc, esc]  # NOTE: back from the list, then out
    result = run("config")
    assert result.exit_code == 0, result.output
    first, labels, _ = menu["asked"][0]
    assert "tourist" in first  # NOTE: who is logged in, in the title
    assert not any("Login" in label or "Another language" in label for label in labels)
    assert not any(label.startswith("C\x1f") for label in labels)  # NOTE: C is C++'s
    assert [message for message, _, _ in menu["asked"]][2] == first  # NOTE: back in the menu
