"""Problems on disk: targets from arguments and folders, the problem
folder's metadata and tests, and which code file is meant."""

import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from cf_tool import ui, workspace
from cf_tool.errors import CFError
from cf_tool.settings import Settings
from cf_tool.workspace import (
    ProblemInfo,
    Target,
    add_test,
    edited,
    find_problem_folder,
    get_root,
    here,
    locate,
    named_target,
    parse_target,
    pick_code,
    read_source,
    save_info,
    save_samples,
    tests_of,
)

HOST = "https://codeforces.com"
OTHERS = "--"  # where the menu's "other files" heading sits
SETTINGS = Settings()


def p(*parts: str) -> str:
    return str(Path(*parts))


# ┌──────────────────────────────────────────────────────────┐
# │                         Targets                          │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.parametrize(
    "specs,target",
    [
        (["2050"], Target("contest", "2050")),
        (["2050a"], Target("contest", "2050", "A")),
        (["cf2050C1"], Target("contest", "2050", "C1")),
        (["2050-b"], Target("contest", "2050", "B")),
        (["2050", "a"], Target("contest", "2050", "A")),  # NOTE: how CP Editor calls cf submit
        (["100001"], Target("gym", "100001")),
        ([f"{HOST}/contest/2050/problem/A"], Target("contest", "2050", "A")),
        ([f"{HOST}/contest/2050"], Target("contest", "2050")),
        ([f"{HOST}/gym/100001/problem/B"], Target("gym", "100001", "B")),
        ([f"{HOST}/problemset/problem/4/A"], Target("contest", "4", "A")),
        (
            [f"{HOST}/group/Cw4JRyRGXR/contest/269760/problem/A"],
            Target("group", "269760", "A", "Cw4JRyRGXR"),
        ),
        ([f"{HOST}/problemsets/acmsguru/problem/99999/123"], Target("acmsguru", "99999", "123")),
        ([f"{HOST}/contest/2050/submission/1234"], Target("contest", "2050")),
    ],
)
def test_parse_target(specs, target):
    assert parse_target(specs) == target


def test_a_letter_is_a_problem_of_the_current_contest():
    base = Target("gym", "100001", "A")
    assert parse_target(["c"], base) == Target("gym", "100001", "C")
    assert parse_target([], base) == base
    assert parse_target(["2050"], base) == Target("contest", "2050")  # NOTE: not 2050A


def test_conflicting_and_unknown_arguments():
    with pytest.raises(CFError, match="2050 and 2051 name different contests"):
        parse_target(["2050a", "2051"])
    with pytest.raises(CFError, match='"a.cpp" is not a contest or a problem'):
        parse_target(["a.cpp"])


def test_urls_and_labels():
    target = Target("contest", "2050", "A")
    assert target.problem_url(HOST) == f"{HOST}/contest/2050/problem/A"
    assert target.problems_url(HOST) == f"{HOST}/contest/2050/problems"
    assert target.submit_url(HOST) == f"{HOST}/contest/2050/submit"
    assert target.my_url(HOST) == f"{HOST}/contest/2050/my"
    assert target.submission_url(HOST, "9") == f"{HOST}/contest/2050/submission/9"
    assert target.label == "2050A" and Target("gym", "100001", "B").label == "gym 100001B"
    group = Target("group", "7", "B", "Cw4JRyRGXR")
    assert group.standings_url(HOST) == f"{HOST}/group/Cw4JRyRGXR/contest/7/standings"
    sgu = Target("acmsguru", "99999", "123")
    assert sgu.problem_url(HOST) == f"{HOST}/problemsets/acmsguru/problem/99999/123"
    assert sgu.label == "acmsguru 123"
    with pytest.raises(CFError, match="Which problem of contest 2050"):
        Target("contest", "2050").problem_url(HOST)
    with pytest.raises(CFError, match="Which contest"):
        Target().contest_url(HOST)


# ┌──────────────────────────────────────────────────────────┐
# │                     Problem folders                      │
# └──────────────────────────────────────────────────────────┘


def problem(root: Path, target: Target, name: str = "") -> Path:
    folder = workspace.problem_folder(root, target)
    save_info(folder, ProblemInfo(name=name, url=target.problem_url(HOST), time_limit=2.0))
    return folder


def test_metadata_round_trip(tmp_path):
    info = ProblemInfo(
        name="A. Two Friends",
        url=f"{HOST}/contest/2050/problem/A",
        time_limit=1.0,
        memory_limit=256,
        interactive=False,
        ignore_case=True,
        epsilon=1e-6,
        cases=[([0, 1, 2], [1, 2]), None],
    )
    save_info(tmp_path, info)
    assert workspace.load_info(tmp_path) == info
    assert info.target == Target("contest", "2050", "A")
    assert info.sample_cases("1") == ([0, 1, 2], [1, 2]) and info.sample_cases("2") is None
    assert info.sample_cases("my") is None
    (tmp_path / workspace.METADATA).write_text("{broken")
    assert workspace.load_info(tmp_path) is None


def test_here(tmp_path):
    folder = problem(tmp_path, Target("contest", "2050", "A"))
    assert here(folder) == Target("contest", "2050", "A")
    (folder / "tests").mkdir()
    assert here(folder / "tests") == Target("contest", "2050", "A")
    assert here(folder.parent) == Target("contest", "2050")  # NOTE: the contest folder
    assert find_problem_folder(folder / "tests") == folder.resolve()


@pytest.mark.parametrize(
    "path,target",
    [
        (p("cf", "contest", "1136", "a"), Target("contest", "1136", "A")),
        (p("cf", "contest", "1136"), Target("contest", "1136")),
        (p("cf", "gym", "100001", "b"), Target("gym", "100001", "B")),
        (
            p("cf", "group", "Cw4JRyRGXR", "269760", "a"),
            Target("group", "269760", "A", "Cw4JRyRGXR"),
        ),
        (p("cf", "acmsguru", "123"), Target("acmsguru", "99999", "123")),
        (p("work", "2050", "C1"), Target("contest", "2050", "C1")),
        (p("work", "2050D"), Target("contest", "2050", "D")),
        (p("work", "project"), None),
    ],
)
def test_here_from_folder_names(tmp_path, path, target):
    folder = tmp_path / path
    folder.mkdir(parents=True)
    assert here(folder) == target


def test_get_root(tmp_path):
    folder = problem(tmp_path, Target("contest", "2050", "A"))
    assert get_root(folder) == tmp_path.resolve()  # NOTE: next to the contest folder
    assert get_root(folder.parent) == tmp_path.resolve()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert get_root(elsewhere) == elsewhere.resolve()
    assert get_root(elsewhere, tmp_path / "cp") == tmp_path / "cp"
    assert workspace.problem_folder(tmp_path, Target("contest", "2050", "C1")) == (
        tmp_path / "2050" / "c1"
    )
    sgu = workspace.problem_folder(tmp_path, Target("acmsguru", "99999", "123"))
    assert sgu == tmp_path / "acmsguru" / "123"


def test_locate(tmp_path):
    a = problem(tmp_path, Target("contest", "2050", "A"))
    b = problem(tmp_path, Target("contest", "2050", "B"))
    assert locate(Target("contest", "2050", "A"), a) == a.resolve()
    assert locate(Target("contest", "2050", "B"), a) == b.resolve()  # NOTE: a sibling
    assert locate(Target("contest", "2050", "B"), a.parent) == b.resolve()
    assert locate(Target("contest", "2050", "B"), tmp_path) == b.resolve()
    assert locate(Target("contest", "2051", "B"), a) is None
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert locate(Target("contest", "2050", "B"), elsewhere, tmp_path) == b.resolve()


def test_locate_old_folders(tmp_path):
    old = tmp_path / "cf" / "contest" / "1136" / "a"
    old.mkdir(parents=True)
    assert locate(Target("contest", "1136", "A"), tmp_path) == old
    assert locate(Target("contest", "1136", "A"), tmp_path / "cf" / "contest") == old


# ┌──────────────────────────────────────────────────────────┐
# │                          Tests                           │
# └──────────────────────────────────────────────────────────┘


def test_tests_in_order(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("10", "2", "1", "my", "edge"):
        (tests / f"{name}.in").write_text("in\n")
        if name != "edge":
            (tests / f"{name}.ans").write_text("ans\n")
    (tests / "notes.txt").write_text("")
    found = tests_of(tmp_path)
    assert [t.name for t in found] == ["1", "2", "10", "edge", "my"]
    assert found[3].answer is None and found[0].answer == tests / "1.ans"


def test_old_tests(tmp_path):
    for i in (1, 2, 11):
        (tmp_path / f"in{i}.txt").write_text("in\n")
    (tmp_path / "ans1.txt").write_text("ans\n")
    found = tests_of(tmp_path)
    assert [(t.name, t.answer is not None) for t in found] == [
        ("1", True),
        ("2", False),
        ("11", False),
    ]


def test_old_tests_stay_beside_new_ones(tmp_path):
    # NOTE: cf get run in a 0.3 folder writes tests/; the user's own in3.txt must still run
    for i in (1, 2, 3):
        (tmp_path / f"in{i}.txt").write_text(f"old {i}\n")
    save_samples(tmp_path, [("new 1\n", "x\n"), ("new 2\n", "y\n")])
    found = tests_of(tmp_path)
    assert [t.name for t in found] == ["1", "2", "3"]
    assert found[0].input == tmp_path / "tests" / "1.in"  # NOTE: tests/ wins a clash
    assert found[2].input == tmp_path / "in3.txt"


def test_get_root_of_a_folder_made_before_metadata(tmp_path):
    old = tmp_path / "cf" / "contest" / "2050" / "a"
    old.mkdir(parents=True)
    (old / "in1.txt").write_text("1\n")
    assert get_root(old) == (tmp_path / "cf" / "contest").resolve()  # NOTE: not old/2050/a
    assert get_root(old.parent) == (tmp_path / "cf" / "contest").resolve()
    plain = tmp_path / "2024"
    plain.mkdir()
    assert get_root(plain) == plain.resolve()  # NOTE: digits alone don't make a contest


def test_save_and_add(tmp_path):
    save_samples(tmp_path, [("1\n", "2\n"), ("3\n", "6\n")])
    assert (tmp_path / "tests" / "2.ans").read_text() == "6\n"
    added = add_test(tmp_path, "5\n", "10\n")
    assert added.name == "3" and added.answer.read_text() == "10\n"
    only_run = add_test(tmp_path, "7\n", "  \n")
    assert only_run.name == "4" and only_run.answer is None
    named = add_test(tmp_path, "9\n", "18\n", name="stress-17")
    assert named.input == tmp_path / "tests" / "stress-17.in"
    assert [t.name for t in tests_of(tmp_path)] == ["1", "2", "3", "4", "stress-17"]


# ┌──────────────────────────────────────────────────────────┐
# │                        Code files                        │
# └──────────────────────────────────────────────────────────┘


def make(root: Path, *names: str) -> None:
    """Create files; later names get later modification times."""
    for i, name in enumerate(names):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))


@pytest.fixture
def prompt(monkeypatch):
    """Records each file menu as the names it lists (OTHERS for the heading)
    and answers with the file named prompt.answer, or the default."""
    calls = []

    def select(message, choices, *, default=None, search=False):
        files = [c[1] for c in choices if not isinstance(c, ui.Heading)]
        calls.append(
            {
                "names": [OTHERS if isinstance(c, ui.Heading) else c[1].name for c in choices],
                "labels": [c[0] for c in choices if not isinstance(c, ui.Heading)],
                "default": default.name if default else None,
            }
        )
        wanted = getattr(select, "answer", None)
        return next(f for f in files if f.name == wanted) if wanted else default

    monkeypatch.setattr(workspace.ui, "select", select)
    monkeypatch.setattr(workspace.ui, "interactive", lambda: True)
    select.calls = calls
    return select


def submit_pick(cwd, contest="546", problem="D"):
    name, _ = pick_code(None, cwd, SETTINGS, contest=contest, problem=problem)
    return name


def test_the_screenshot_case(tmp_path, prompt):
    make(tmp_path, "2171A.cpp", "546D.cpp", "demo.cpp", "demo.py")
    assert submit_pick(tmp_path) == "546D.cpp"  # NOTE: the pre-selected answer
    assert prompt.calls[0]["names"] == ["546D.cpp", OTHERS, "demo.py", "demo.cpp", "2171A.cpp"]
    assert prompt.calls[0]["default"] == "546D.cpp"


def test_the_demo_project(tmp_path, prompt):
    make(tmp_path, p("546", "D", "solution.cpp"), "2171A.cpp", "demo.cpp", "demo.py", "546D.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == [
        "546D.cpp",
        p("546", "D", "solution.cpp"),
        OTHERS,
        "demo.py",
        "demo.cpp",
        "2171A.cpp",
    ]


@pytest.mark.parametrize(
    "name", ["546d.cpp", "cf546D.cpp", "CF_546_D.cpp", "546-D.cc", "546 D.py", "546D_v2.cpp"]
)
def test_spellings_of_the_name(tmp_path, prompt, name):
    make(tmp_path, name, "demo.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == [name, OTHERS, "demo.cpp"]


def test_the_contest_folder(tmp_path, prompt):
    make(tmp_path, p("546", "D.cpp"), p("546", "D-v2.cpp"), p("546", "D1.cpp"), "2171A.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == [
        p("546", "D-v2.cpp"),
        p("546", "D.cpp"),
        OTHERS,
        "2171A.cpp",
        p("546", "D1.cpp"),  # NOTE: problem D1, not a copy of D
    ]


def test_a_problem_folder_with_helpers(tmp_path, prompt):
    folder = tmp_path / "2050" / "a"
    make(folder, "brute.cpp", "gen.py", "checker.cpp", "a.cpp")
    assert submit_pick(folder, "2050", "A") == "a.cpp"
    assert prompt.calls == []  # NOTE: the helpers are no candidates
    make(folder, "a2.cpp")
    os.utime(folder / "a2.cpp", (2_000_000, 2_000_000))
    submit_pick(folder, "2050", "A")
    assert prompt.calls[0]["names"] == ["a2.cpp", "a.cpp"]


def test_sub_problems_are_told_apart(tmp_path, prompt):
    make(tmp_path, "1520F1.cpp", "1520F2.cpp", "1520F.cpp")
    submit_pick(tmp_path, "1520", "F1")
    assert prompt.calls[0]["names"] == ["1520F1.cpp", OTHERS, "1520F.cpp", "1520F2.cpp"]


def test_other_contests_do_not_match(tmp_path, prompt):
    make(tmp_path, "1546D.cpp", "546D1.cpp", "5460D.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == ["5460D.cpp", "546D1.cpp", "1546D.cpp"]


def test_no_target_newest_first(tmp_path, prompt):
    make(tmp_path, "old.cpp", "new.cpp", "newest.py", "notes.txt")
    pick_code(None, tmp_path, SETTINGS)
    assert prompt.calls[0]["names"] == ["newest.py", "new.cpp", "old.cpp"]


def test_from_inside_the_problem_folder(tmp_path, prompt):
    make(tmp_path, p("546", "D", "solution.cpp"), "demo.cpp", "546D.cpp")
    assert submit_pick(tmp_path / "546" / "D") == p("..", "..", "546D.cpp")
    # NOTE: this problem's files around the folder, not every file up there
    assert prompt.calls[0]["names"] == [p("..", "..", "546D.cpp"), "solution.cpp"]


def test_from_inside_the_contest_folder(tmp_path, prompt):
    make(tmp_path, "546D.cpp", p("546", "A.cpp"), p("546", "D", "solution.cpp"), "2171A.cpp")
    submit_pick(tmp_path / "546")
    assert prompt.calls[0]["names"] == [
        p("D", "solution.cpp"),
        p("..", "546D.cpp"),
        OTHERS,
        "A.cpp",
    ]


def test_the_only_file_is_taken(tmp_path, prompt):
    make(tmp_path, "demo.cpp")
    assert submit_pick(tmp_path) == "demo.cpp" and prompt.calls == []


def test_choose_by_answer(tmp_path, prompt):
    make(tmp_path, "546D.cpp", "546D_v2.cpp")
    prompt.answer = "546D.cpp"
    assert submit_pick(tmp_path) == "546D.cpp"


def test_labels_line_up_the_edit_times(tmp_path, prompt):
    make(tmp_path, "546D.cpp", p("546", "D", "solution.cpp"))
    submit_pick(tmp_path)
    when = edited(1_000_000, time.time())
    longest = p("546", "D", "solution.cpp")
    assert prompt.calls[0]["labels"] == [
        f"{longest}  {when}",
        f"{'546D.cpp'.ljust(len(longest))}  {when}",
    ]


def test_explicit_file_and_none(tmp_path):
    assert pick_code("sol.cc", tmp_path, SETTINGS) == ("sol.cc", "cpp")
    with pytest.raises(CFError, match="doesn't know what language sol.hs is in"):
        pick_code("sol.hs", tmp_path, SETTINGS)
    with pytest.raises(CFError, match="No code file for 2050A here"):
        pick_code(None, tmp_path, SETTINGS, contest="2050", problem="A")


def test_excluded_files_are_no_candidates(tmp_path, prompt):
    make(tmp_path, "slow.cpp", "a.cpp")
    name, _ = pick_code(None, tmp_path, SETTINGS, exclude=("./slow.cpp",))
    assert name == "a.cpp" and prompt.calls == []


def test_edited():
    now = datetime(2026, 10, 12, 18, 30).timestamp()

    def at(*moment: int) -> str:
        return edited(datetime(*moment).timestamp(), now)

    assert at(2026, 10, 12, 18, 9) == "today 18:09"
    assert at(2026, 10, 11, 16, 11) == "yesterday 16:11"
    assert at(2026, 3, 31, 17, 19) == "Mar 31"
    assert at(2025, 12, 31, 9, 0) == "Dec 31 2025"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("546D.cpp", ("546", "D")),
        ("cf546d.py", ("546", "D")),
        ("546-D_brute.cpp", ("546", "D")),
        ("1520F1.cpp", ("1520", "F1")),
        (p("546", "D.cpp"), ("546", "D")),
        (p("546", "D", "main.cpp"), ("546", "D")),
        (p("546D", "sol.cpp"), ("546", "D")),
        ("D.cpp", ("", "D")),
        ("demo.cpp", ("", "")),
    ],
)
def test_named_target(tmp_path, name, expected):
    assert named_target(name, tmp_path) == expected


def test_read_source_encodings(tmp_path, capsys):
    utf8 = tmp_path / "a.cpp"
    utf8.write_bytes("﻿// 注释\nint main(){}\n".encode("utf-8"))
    assert read_source(utf8) == "// 注释\nint main(){}\n"  # NOTE: BOM dropped
    gbk = tmp_path / "b.cpp"
    gbk.write_bytes("// 中文注释\nint main(){}\n".encode("gbk"))
    assert read_source(gbk) == "// 中文注释\nint main(){}\n"
    assert "not UTF-8" in capsys.readouterr().out
    with pytest.raises(CFError, match="Cannot read"):
        read_source(tmp_path / "missing.cpp")


def test_no_menu_off_a_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.ui, "interactive", lambda: False)
    make(tmp_path, "a.cpp", "b.cpp")
    with pytest.raises(CFError, match=r"Several code files could be meant \(b.cpp, a.cpp\)"):
        pick_code(None, tmp_path, SETTINGS)
