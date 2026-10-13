"""Which code file: candidates grouped for the target problem, newest first;
the only one is taken, several are always offered."""

import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from cf_tool import codefiles, ui
from cf_tool.codefiles import edited, named_target, pick, read_source
from cf_tool.config import CodeTemplate
from cf_tool.errors import CFError

CPP = CodeTemplate(alias="cpp", lang="89", suffix=["cpp", "cc"], script="./$%file%$")
PY = CodeTemplate(alias="py", lang="31", suffix=["py"], script="python3 $%full%$")
TEMPLATES = [CPP, PY]
OTHERS = "--"  # where the menu's "other files" heading sits


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

    monkeypatch.setattr(codefiles.ui, "select", select)
    select.calls = calls
    return select


def submit_pick(cwd, contest="546", problem="D"):
    name, _ = pick(None, TEMPLATES, cwd, contest=contest, problem=problem, search_folders=True)
    return name


def p(*parts: str) -> str:
    return str(Path(*parts))


# ------------------------------------------------------- the menu


def test_the_screenshot_case(tmp_path, prompt):
    make(tmp_path, "2171A.cpp", "546D.cpp", "demo.cpp", "demo.py")
    assert submit_pick(tmp_path) == "546D.cpp"  # the pre-selected answer
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


def test_this_problems_newest_file_comes_first(tmp_path, prompt):
    make(tmp_path, "546D.cpp", "546D_brute.cpp", p("546", "D", "solution.cpp"))
    assert submit_pick(tmp_path) == p("546", "D", "solution.cpp")
    assert prompt.calls[0]["names"] == [p("546", "D", "solution.cpp"), "546D_brute.cpp", "546D.cpp"]


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
        p("546", "D1.cpp"),  # problem D1, not a copy of D
    ]


def test_cwd_is_the_contest_folder(tmp_path, prompt):
    contest = tmp_path / "546"
    make(contest, "D.cpp", "A.cpp", "brute.cpp")
    assert submit_pick(contest) == "D.cpp"
    assert prompt.calls[0]["names"] == ["D.cpp", OTHERS, "brute.cpp", "A.cpp"]


def test_go_layout_lists_the_folder_newest_first(tmp_path, prompt):
    problem_dir = tmp_path / "cf" / "contest" / "546" / "d"
    make(problem_dir, "brute.cpp", "gen.py", "d1.cpp", "d.cpp")
    assert submit_pick(problem_dir, problem="d") == "d.cpp"
    assert prompt.calls[0]["names"] == ["d.cpp", "d1.cpp", "gen.py", "brute.cpp"]


def test_problem_folders_named_in_full(tmp_path, prompt):
    make(tmp_path, p("546D", "sol.cpp"), "demo.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == [p("546D", "sol.cpp"), OTHERS, "demo.cpp"]


def test_sub_problems_are_told_apart(tmp_path, prompt):
    make(tmp_path, "1520F1.cpp", "1520F2.cpp", "1520F.cpp")
    submit_pick(tmp_path, "1520", "F1")
    assert prompt.calls[0]["names"] == ["1520F1.cpp", OTHERS, "1520F.cpp", "1520F2.cpp"]
    submit_pick(tmp_path, "1520", "F")
    assert prompt.calls[1]["names"] == ["1520F.cpp", OTHERS, "1520F2.cpp", "1520F1.cpp"]


def test_a_bare_problem_letter_leads_the_other_files(tmp_path, prompt):
    make(tmp_path, "D.cpp", "demo.cpp")  # D of which contest? not this problem's group
    assert submit_pick(tmp_path) == "D.cpp"
    assert prompt.calls[0]["names"] == ["D.cpp", "demo.cpp"]


def test_other_contests_do_not_match(tmp_path, prompt):
    make(tmp_path, "1546D.cpp", "546D1.cpp", "5460D.cpp")
    submit_pick(tmp_path)
    assert prompt.calls[0]["names"] == ["5460D.cpp", "546D1.cpp", "1546D.cpp"]


def test_no_target_newest_first(tmp_path, prompt):
    make(tmp_path, "old.cpp", "new.cpp", "newest.py")
    pick(None, TEMPLATES, tmp_path)
    assert prompt.calls[0]["names"] == ["newest.py", "new.cpp", "old.cpp"]


def test_no_target_files_named_for_a_problem_first(tmp_path, prompt):
    make(tmp_path, "546D.cpp", "2171A.cpp", "demo.cpp")
    pick(None, TEMPLATES, tmp_path)
    assert prompt.calls[0]["names"] == ["2171A.cpp", "546D.cpp", OTHERS, "demo.cpp"]


def test_from_inside_the_problem_folder(tmp_path, prompt):
    make(tmp_path, p("546", "D", "solution.cpp"), "demo.cpp", "546D.cpp")
    assert submit_pick(tmp_path / "546" / "D") == p("..", "..", "546D.cpp")
    # this problem's files around the folder, not every file up there
    assert prompt.calls[0]["names"] == [p("..", "..", "546D.cpp"), "solution.cpp"]


def test_from_inside_the_contest_folder(tmp_path, prompt):
    make(tmp_path, "546D.cpp", p("546", "A.cpp"), p("546", "D", "solution.cpp"), "2171A.cpp")
    submit_pick(tmp_path / "546")
    assert prompt.calls[0]["names"] == [
        p("D", "solution.cpp"),
        p("..", "546D.cpp"),
        OTHERS,
        "A.cpp",  # the cwd's own files all count, as in the Go tool
    ]


def test_go_layout_looks_no_higher_than_its_tree(tmp_path, prompt):
    root = tmp_path / "cf" / "contest"
    make(tmp_path, "546D.cpp")  # beyond cf/contest/: not looked at
    make(root / "546" / "d", "d.cpp")
    assert submit_pick(root / "546" / "d", problem="d") == "d.cpp"
    assert prompt.calls == []


def test_the_only_file_is_taken(tmp_path, prompt):
    make(tmp_path, "demo.cpp")  # Go behavior: the only candidate needs no match
    assert submit_pick(tmp_path) == "demo.cpp"
    assert prompt.calls == []


def test_folders_only_searched_when_asked(tmp_path, prompt):
    make(tmp_path, p("546", "D.cpp"), "demo.cpp")
    name, _ = pick(None, TEMPLATES, tmp_path, contest="546", problem="D")  # cf test
    assert name == "demo.cpp"
    assert prompt.calls == []


def test_choose_by_answer(tmp_path, prompt):
    make(tmp_path, "546D.cpp", "546D_v2.cpp")
    prompt.answer = "546D.cpp"
    assert submit_pick(tmp_path) == "546D.cpp"


def test_labels_line_up_the_edit_times(tmp_path, prompt):
    make(tmp_path, "546D.cpp", p("546", "D", "solution.cpp"))
    submit_pick(tmp_path)
    when = edited(1_000_000, time.time())  # both files: a day in 1970
    longest = p("546", "D", "solution.cpp")
    assert prompt.calls[0]["labels"] == [
        f"{longest}  {when}",
        f"{'546D.cpp'.ljust(len(longest))}  {when}",
    ]


def test_edited():
    now = datetime(2026, 10, 12, 18, 30).timestamp()

    def at(*moment: int) -> str:
        return edited(datetime(*moment).timestamp(), now)

    assert at(2026, 10, 12, 18, 9) == "today 18:09"
    assert at(2026, 10, 12, 0, 0) == "today 00:00"
    assert at(2026, 10, 11, 16, 11) == "yesterday 16:11"
    assert at(2026, 10, 10, 23, 59) == "Oct 10"
    assert at(2026, 3, 31, 17, 19) == "Mar 31"
    assert at(2025, 12, 31, 9, 0) == "Dec 31 2025"
    assert at(2026, 10, 13, 9, 0) == "Oct 13"  # a clock ahead of this one


# ------------------------------------------------------- explicit / misc


def test_explicit_file(tmp_path):
    assert pick("sol.cc", TEMPLATES, tmp_path) == ("sol.cc", 0)
    with pytest.raises(CFError, match="can not match any template"):
        pick("sol.rs", TEMPLATES, tmp_path)


def test_nothing_to_pick(tmp_path):
    with pytest.raises(CFError, match="Cannot find any code"):
        pick(None, TEMPLATES, tmp_path)


def test_several_templates_for_one_file(tmp_path, monkeypatch):
    cpp17 = CodeTemplate(alias="cpp17", lang="54", suffix=["cpp"])
    make(tmp_path, "a.cpp")
    monkeypatch.setattr("cf_tool.ui.choose_index", lambda n: 1)
    assert pick(None, [CPP, cpp17], tmp_path) == ("a.cpp", 1)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("546D.cpp", ("546", "D")),
        ("cf546d.py", ("546", "d")),
        ("546-D_brute.cpp", ("546", "D")),
        ("1520F1.cpp", ("1520", "F1")),
        (str(Path("546", "D.cpp")), ("546", "D")),
        (str(Path("546", "D", "main.cpp")), ("546", "D")),
        (str(Path("546D", "sol.cpp")), ("546", "D")),
        ("D.cpp", ("", "D")),
        ("demo.cpp", ("", "")),
        ("go.py", ("", "")),
    ],
)
def test_named_target(tmp_path, name, expected):
    assert named_target(name, tmp_path) == expected


def test_named_target_of_files_above(tmp_path):
    problem_dir = tmp_path / "546" / "D"
    assert named_target(p("..", "..", "546D.cpp"), problem_dir) == ("546", "D")
    assert named_target(p("..", "D.cpp"), problem_dir) == ("546", "D")


def test_named_target_from_the_directory(tmp_path):
    problem_dir = tmp_path / "cf" / "contest" / "546" / "d"
    assert named_target("d.cpp", problem_dir) == ("546", "d")


def test_read_source_encodings(tmp_path, capsys):
    utf8 = tmp_path / "a.cpp"
    utf8.write_bytes("﻿// 注释\nint main(){}\n".encode("utf-8"))
    assert read_source(utf8) == "// 注释\nint main(){}\n"  # BOM dropped
    gbk = tmp_path / "b.cpp"
    gbk.write_bytes("// 中文注释\nint main(){}\n".encode("gbk"))
    assert read_source(gbk) == "// 中文注释\nint main(){}\n"
    assert "not UTF-8" in capsys.readouterr().out
    with pytest.raises(CFError, match="Cannot read"):
        read_source(tmp_path / "missing.cpp")
