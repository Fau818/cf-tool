"""Tests for specifier/path inference, mirroring xalanq/cf-tool semantics."""

from pathlib import Path

import pytest

from cf_tool.args import Info, parse_arg, parse_args, parse_path
from cf_tool.config import Config
from cf_tool.errors import CFError

HOST = "https://codeforces.com"


@pytest.fixture
def cfg():
    return Config()


# ---------------------------------------------------------------- parse_arg


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("contest", {"problemType": "contest"}),
        ("Contests", {"problemType": "contest"}),
        ("gym", {"problemType": "gym"}),
        ("GYMS", {"problemType": "gym"}),
        ("group", {"problemType": "group"}),
        ("acmsguru", {"problemType": "acmsguru"}),
        ("1136", {"contestID": "1136"}),
        ("123456", {"contestID": "123456"}),
        ("1136a", {"contestID": "1136", "problemID": "a"}),
        ("1136A1", {"contestID": "1136", "problemID": "A1"}),
        ("a", {"problemID": "a"}),
        ("C1", {"problemID": "C1"}),
        # 10 word chars match both the problem and the group regex; Go keeps both
        ("abcdefghij", {"problemID": "abcdefghij", "groupID": "abcdefghij"}),
        (
            "https://codeforces.com/contest/1136/problem/A",
            {"problemType": "contest", "contestID": "1136", "problemID": "A"},
        ),
        ("https://codeforces.com/contest/1136", {"problemType": "contest", "contestID": "1136"}),
        (
            "https://codeforces.com/gym/100001/problem/B",
            {"problemType": "gym", "contestID": "100001", "problemID": "B"},
        ),
        (
            "https://codeforces.com/problemset/problem/1136/A",
            {"problemType": "contest", "contestID": "1136", "problemID": "A"},
        ),
        (
            "https://codeforces.com/group/Cw4JRyRGXR/contest/269760/problem/A",
            {
                "problemType": "group",
                "groupID": "Cw4JRyRGXR",
                "contestID": "269760",
                "problemID": "A",
            },
        ),
        (
            "https://codeforces.com/contest/1136/submission/12345678",
            {"problemType": "contest", "contestID": "1136", "submissionID": "12345678"},
        ),
        (
            "https://codeforces.com/problemsets/acmsguru/problem/99999/123",
            {"problemType": "acmsguru", "contestID": "99999", "problemID": "123"},
        ),
        # Go quirk: the generic /submission/(\d+) regex runs after the acmsguru
        # one and overwrites submissionID with the first number it finds
        (
            "https://codeforces.com/problemsets/acmsguru/submission/99999/12345678",
            {"problemType": "acmsguru", "contestID": "99999", "submissionID": "99999"},
        ),
    ],
)
def test_parse_arg(arg, expected):
    assert parse_arg(arg) == expected


# --------------------------------------------------------------- parse_path


@pytest.mark.parametrize(
    "path,expected",
    [
        (
            "/home/u/cf/contest/1136/a",
            {"problemType": "contest", "contestID": "1136", "problemID": "a"},
        ),
        ("/home/u/cf/contest/1136", {"problemType": "contest", "contestID": "1136"}),
        ("/home/u/cf/contest", {"problemType": "contest"}),
        (
            "/home/u/cf/gym/100001/b",
            {"problemType": "gym", "contestID": "100001", "problemID": "b"},
        ),
        (
            "/home/u/cf/group/Cw4JRyRGXR/269760/a",
            {
                "problemType": "group",
                "groupID": "Cw4JRyRGXR",
                "contestID": "269760",
                "problemID": "a",
            },
        ),
        ("/home/u/cf/group/Cw4JRyRGXR", {"problemType": "group", "groupID": "Cw4JRyRGXR"}),
        ("/home/u/cf/acmsguru/123", {"problemType": "acmsguru", "problemID": "123"}),
        ("/home/u/work/project", {}),
        # root folder must be a full path component (deliberately stricter than Go)
        ("/home/u/mycf/contest/1136/a", {}),
        # deeper nesting still matches
        (
            "/very/deep/cf/contest/1136/a",
            {"problemType": "contest", "contestID": "1136", "problemID": "a"},
        ),
    ],
)
def test_parse_path(path, expected, cfg):
    assert parse_path(Path(path), cfg) == expected


def test_parse_path_custom_folder_names():
    cfg = Config(folder_name={"root": "codeforces", "contest": "round"})
    parsed = parse_path(Path("/h/codeforces/round/1136/a"), cfg)
    assert parsed == {"problemType": "contest", "contestID": "1136", "problemID": "a"}
    assert parse_path(Path("/h/cf/contest/1136/a"), cfg) == {}


# --------------------------------------------------------------- parse_args


def test_infer_everything_from_cwd(cfg):
    info = parse_args([], Path("/h/cf/contest/1136/a"), cfg)
    assert (info.problem_type, info.contest_id, info.problem_id) == ("contest", "1136", "a")
    assert info.root_path == Path("/h/cf/contest")


def test_arg_overrides_path(cfg):
    info = parse_args(["b"], Path("/h/cf/contest/1136/a"), cfg)
    assert (info.contest_id, info.problem_id) == ("1136", "b")


def test_explicit_specifiers_outside_root(cfg):
    info = parse_args(["1136", "a"], Path("/h/somewhere"), cfg)
    assert (info.problem_type, info.contest_id, info.problem_id) == ("contest", "1136", "a")
    # no root among ancestors: a root folder is created under cwd
    assert info.root_path == Path("/h/somewhere/cf/contest")


def test_combined_specifier(cfg):
    info = parse_args(["1136a"], Path("/h"), cfg)
    assert (info.contest_id, info.problem_id) == ("1136", "a")


def test_conflicting_specifiers(cfg):
    with pytest.raises(CFError, match="Problem ID conflicts"):
        parse_args(["1136a", "b"], Path("/h"), cfg)


def test_six_digit_contest_is_gym(cfg):
    assert parse_args(["100001"], Path("/h"), cfg).problem_type == "gym"
    # Go quirk: the length heuristic overrides even an explicit "contest" keyword
    assert parse_args(["contest", "123456"], Path("/h"), cfg).problem_type == "gym"
    assert parse_args(["gym", "123"], Path("/h"), cfg).problem_type == "gym"


def test_acmsguru_rewrites_contest_to_problem(cfg):
    info = parse_args(["acmsguru", "123"], Path("/h"), cfg)
    assert (info.problem_type, info.contest_id, info.problem_id) == ("acmsguru", "99999", "123")


def test_url_specifier(cfg):
    info = parse_args(["https://codeforces.com/contest/1136/problem/A"], Path("/h"), cfg)
    assert (info.problem_type, info.contest_id, info.problem_id) == ("contest", "1136", "A")


def test_group_cwd(cfg):
    info = parse_args([], Path("/h/cf/group/Cw4JRyRGXR/269760/a"), cfg)
    assert info.problem_type == "group"
    assert info.group_id == "Cw4JRyRGXR"
    assert info.path() == Path("/h/cf/group/Cw4JRyRGXR/269760/a")


def test_path_type_not_consulted_when_arg_sets_type(cfg):
    # a type-bearing specifier disables path inference entirely (Go behavior)
    info = parse_args(["gym"], Path("/h/cf/contest/1136/a"), cfg)
    assert info.problem_type == "gym"
    assert info.contest_id == ""


# ------------------------------------------------------------ Info helpers


def test_path_lowercases_problem_id(cfg):
    info = parse_args(["1136A"], Path("/h"), cfg)
    assert info.path() == Path("/h/cf/contest/1136/a")
    assert info.problem_id == "A"  # original case kept for URLs


def test_urls():
    info = Info(problem_type="contest", contest_id="1136", problem_id="A")
    assert info.problem_url(HOST) == f"{HOST}/contest/1136/problem/A"
    assert info.problem_set_url(HOST) == f"{HOST}/contest/1136"
    assert info.submit_url(HOST) == f"{HOST}/contest/1136/submit"
    assert info.standings_url(HOST) == f"{HOST}/contest/1136/standings"
    assert info.my_submission_url(HOST) == f"{HOST}/contest/1136/my"

    gym = Info(problem_type="gym", contest_id="100001", problem_id="B")
    assert gym.problem_url(HOST) == f"{HOST}/gym/100001/problem/B"

    group = Info(problem_type="group", group_id="Cw4JRyRGXR", contest_id="269760", problem_id="A")
    assert group.problem_url(HOST) == f"{HOST}/group/Cw4JRyRGXR/contest/269760/problem/A"

    acm = Info(problem_type="acmsguru", contest_id="99999", problem_id="123")
    assert acm.problem_url(HOST) == f"{HOST}/problemsets/acmsguru/problem/99999/123"


def test_url_errors():
    with pytest.raises(CFError, match="Contest ID"):
        Info(problem_type="contest").problem_set_url(HOST)
    with pytest.raises(CFError, match="Gym ID"):
        Info(problem_type="gym").problem_set_url(HOST)
    with pytest.raises(CFError, match="Problem ID"):
        Info(problem_type="contest", contest_id="1136").problem_url(HOST)
    with pytest.raises(CFError, match="Group ID"):
        Info(problem_type="group", contest_id="269760", problem_id="A").problem_url(HOST)


def test_open_url_fallbacks():
    assert Info(problem_type="contest").open_url(HOST) == f"{HOST}/contests"
    assert Info(problem_type="gym").open_url(HOST) == f"{HOST}/gyms"
    assert Info(problem_type="group").open_url(HOST) == f"{HOST}/groups"
    assert Info(problem_type="contest", contest_id="1136").open_url(HOST) == f"{HOST}/contest/1136"


def test_hint():
    info = Info(problem_type="contest", contest_id="1136", problem_id="a")
    assert info.hint() == "CONTEST 1136, problem a"
