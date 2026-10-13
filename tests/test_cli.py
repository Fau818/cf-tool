"""CLI smoke tests (offline commands only), using an isolated HOME."""

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from cf_tool.cli import main


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point the XDG config/state paths (and the legacy ~/.cf) at a temp dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import cf_tool.config as config_module

    config_dir = tmp_path / ".config" / "cf"
    state_dir = tmp_path / ".local" / "state" / "cf"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "STATE_DIR", state_dir)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_dir / "config")
    monkeypatch.setattr(config_module, "SESSION_PATH", state_dir / "session")
    monkeypatch.setattr(config_module, "LEGACY_DIR", tmp_path / ".cf")
    import cf_tool.cli as cli_module
    import cf_tool.client as client_module

    monkeypatch.setattr(client_module, "SESSION_PATH", state_dir / "session")
    monkeypatch.setattr(cli_module, "_setup", lambda: _setup_isolated(tmp_path))
    return tmp_path


def _setup_isolated(home: Path):
    from cf_tool.client import Client
    from cf_tool.config import Config

    cfg = Config.load(home / ".config" / "cf" / "config")
    return cfg, Client(cfg, session_path=home / ".local" / "state" / "cf" / "session")


def write_config(home: Path, template: dict) -> None:
    config_dir = home / ".config" / "cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(json.dumps({"template": [template], "default": 0}))


PY_TEMPLATE = {
    "alias": "py",
    "lang": "31",
    "path": "",  # filled per-test
    "suffix": ["py"],
    "before_script": "",
    "script": f"{sys.executable} $%full%$",
    "after_script": "",
}


def test_help():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("config", "submit", "parse", "gen", "test", "watch", "race"):
        assert command in result.output


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0


def test_gen_and_test_flow(isolated_home, tmp_path, monkeypatch):
    template_file = tmp_path / "tpl.py"
    template_file.write_text("print(int(input()) * 2)  # by $%U%$\n")
    template = dict(PY_TEMPLATE, path=str(template_file))
    write_config(isolated_home, template)

    problem_dir = tmp_path / "cf" / "contest" / "1136" / "a"
    problem_dir.mkdir(parents=True)
    (problem_dir / "in1.txt").write_text("21\n")
    (problem_dir / "ans1.txt").write_text("42\n")
    monkeypatch.chdir(problem_dir)

    runner = CliRunner()
    result = runner.invoke(main, ["gen"])
    assert result.exit_code == 0, result.output
    assert (problem_dir / "a.py").exists()

    result = runner.invoke(main, ["test"])
    assert result.exit_code == 0, result.output
    assert "Passed #1" in result.output


def test_test_failure_exit_code(isolated_home, tmp_path, monkeypatch):
    template_file = tmp_path / "tpl.py"
    template_file.write_text("print('wrong')\n")
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(template_file)))

    problem_dir = tmp_path / "work"
    problem_dir.mkdir()
    (problem_dir / "a.py").write_text("print('wrong')\n")
    (problem_dir / "in1.txt").write_text("1\n")
    (problem_dir / "ans1.txt").write_text("right\n")
    monkeypatch.chdir(problem_dir)

    result = CliRunner().invoke(main, ["test"])
    assert result.exit_code == 0  # like the Go tool, failing samples don't fail the command
    assert "Failed #1" in result.output


def test_open_prints_url(isolated_home, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    result = CliRunner().invoke(main, ["open", "1136a"])
    assert result.exit_code == 0, result.output
    assert opened == ["https://codeforces.com/contest/1136/problem/a"]


def test_sid_without_history_errors(isolated_home):
    result = CliRunner().invoke(main, ["sid"])
    assert result.exit_code == 1
    assert "Submission ID" in result.output


def test_parse_gen_survives_a_failed_problem(isolated_home, tmp_path, monkeypatch):
    """gen-after-parse writes into every problem dir, even one whose samples failed."""
    from cf_tool import pages
    from cf_tool.client import Client
    from cf_tool.errors import CFError

    template_file = tmp_path / "tpl.py"
    template_file.write_text("print(1)\n")
    config_dir = isolated_home / ".config" / "cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(
        json.dumps(
            {"template": [dict(PY_TEMPLATE, path=str(template_file))], "gen_after_parse": True}
        )
    )

    def fake_parse_problem(self, url, path):
        if url.endswith("/B"):
            raise CFError("Cannot parse sample with input 0 and output 0")
        return 1, True

    monkeypatch.setattr(Client, "parse_problem", fake_parse_problem)
    monkeypatch.setattr(
        Client,
        "statis",
        lambda self, info: [pages.StatisInfo(i, "x", "", "", "0", "") for i in "AB"],
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["parse", "1136"])
    assert result.exit_code == 0, result.output
    assert "Failed B" in result.output
    contest = tmp_path / "cf" / "contest" / "1136"
    assert (contest / "a" / "a.py").exists() and (contest / "b" / "b.py").exists()


def test_sid_with_go_style_last_submission(isolated_home, monkeypatch):
    state_dir = isolated_home / ".local" / "state" / "cf"
    state_dir.mkdir(parents=True)
    last = {
        "problem_type": "contest",
        "contest_id": "4",
        "group_id": "",
        "problem_id": "A",
        "submission_id": "123",
        "RootPath": "/x",  # written by the Go tool
    }
    (state_dir / "session").write_text(json.dumps({"last_submission": last}))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    result = CliRunner().invoke(main, ["sid"])
    assert result.exit_code == 0, result.output
    assert opened == ["https://codeforces.com/contest/4/submission/123"]


def test_submit_missing_file_is_a_clean_error(isolated_home, tmp_path, monkeypatch):
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["submit", "-f", "nope.py", "4a"])
    assert result.exit_code == 1
    assert "Cannot read nope.py" in result.output
    assert "Traceback" not in result.output


@pytest.fixture
def fake_submit(isolated_home, tmp_path, monkeypatch):
    """cf submit up to the network: records what would be submitted where and
    the file menus (names in order); answers confirmations from
    fake_submit["answers"] and menus with fake_submit["pick"], else defaults."""
    from cf_tool import ui
    from cf_tool.client import Client

    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    record = {"submitted": [], "questions": [], "answers": [], "menus": [], "pick": None}

    def submit(self, info, lang_id, source, filename=""):
        record["submitted"].append((filename, info.contest_id, info.problem_id))

    def confirm(message, *, default=False):
        record["questions"].append((message, default))
        return record["answers"].pop(0) if record["answers"] else default

    def select(message, choices, *, default=None, search=False):
        files = [c[1] for c in choices if not isinstance(c, ui.Heading)]
        record["menus"].append([f.name for f in files])
        return next(f for f in files if f.name == record["pick"]) if record["pick"] else default

    monkeypatch.setattr(Client, "submit", submit)
    monkeypatch.setattr(ui, "confirm", confirm)
    monkeypatch.setattr(ui, "select", select)
    record["dir"] = work
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
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == [["546D.py", "demo.py", "2171A.py"]]
    assert fake_submit["submitted"] == [("546D.py", "546", "D")]
    assert fake_submit["questions"] == []


def test_submit_another_file_from_the_menu(fake_submit):
    make_code(fake_submit["dir"], "546D.py", "demo.py")
    fake_submit["pick"] = "demo.py"
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("demo.py", "546", "D")]
    assert fake_submit["questions"] == []  # demo.py is named for no other problem


def test_submit_finds_the_contest_folder(fake_submit):
    make_code(fake_submit["dir"], str(Path("546", "D.py")), "demo.py")
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == [[str(Path("546", "D.py")), "demo.py"]]
    assert fake_submit["submitted"] == [(str(Path("546", "D.py")), "546", "D")]


def test_submit_from_inside_the_problem_folder(fake_submit, monkeypatch):
    make_code(fake_submit["dir"], str(Path("546", "D", "solution.py")), "546D.py")
    monkeypatch.chdir(fake_submit["dir"] / "546" / "D")
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    up = str(Path("..", "..", "546D.py"))
    assert fake_submit["menus"] == [[up, "solution.py"]]
    assert fake_submit["submitted"] == [(up, "546", "D")]
    assert fake_submit["questions"] == []


def test_submit_the_only_file_without_a_menu(fake_submit):
    make_code(fake_submit["dir"], str(Path("546", "D", "solution.py")))
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == []
    assert fake_submit["submitted"] == [(str(Path("546", "D", "solution.py")), "546", "D")]


def test_submit_reads_the_target_off_the_name_after_a_yes(fake_submit):
    (fake_submit["dir"] / "546D.py").write_text("print(1)\n")
    result = CliRunner().invoke(main, ["submit"])  # no specifier at all
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("546D.py", "546", "D")]
    assert fake_submit["questions"] == [("Submit 546D.py to CONTEST 546, problem D?", True)]


def test_submit_guards_against_another_problems_file(fake_submit):
    (fake_submit["dir"] / "2171A.py").write_text("print(1)\n")
    result = CliRunner().invoke(main, ["submit", "-f", "2171A.py", "546D"])
    assert result.exit_code == 1
    assert "Not submitted" in result.output
    assert fake_submit["submitted"] == []
    message, default = fake_submit["questions"][0]
    assert "2171A.py looks like 2171A" in message and default is False


def test_submit_another_problems_file_on_purpose(fake_submit):
    (fake_submit["dir"] / "2171A.py").write_text("print(1)\n")
    fake_submit["answers"].append(True)
    result = CliRunner().invoke(main, ["submit", "-f", "2171A.py", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("2171A.py", "546", "D")]


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
    from cf_tool.cli import version_key

    assert version_key(older) < version_key(newer)


def test_version_key_rejects_junk():
    from cf_tool.cli import version_key

    assert version_key("nightly") is None
    assert version_key("0.3.0") == version_key("v0.3")


class _Releases:
    def __init__(self, releases, status=200):
        self.releases, self.status_code = releases, status

    def json(self):
        return self.releases


def _upgrade_with(monkeypatch, releases, current, status=200):
    import cf_tool.cli as cli_module
    from curl_cffi import requests as curl_requests

    monkeypatch.setattr(cli_module, "__version__", current)
    monkeypatch.setattr(curl_requests, "get", lambda url, timeout: _Releases(releases, status))
    return CliRunner().invoke(main, ["upgrade"])


RELEASES = [
    {"tag_name": "v0.3.0a2", "prerelease": True, "draft": False},
    {"tag_name": "v0.4.0", "prerelease": False, "draft": True},  # drafts never count
    {"tag_name": "v0.3.0a1", "prerelease": True, "draft": False},
]


def test_upgrade_offers_the_next_alpha_to_alpha_users(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.3.0a1")
    assert result.exit_code == 0, result.output
    assert "Latest version is v0.3.0a2" in result.output
    assert "git+https://github.com/Fau818/cf-tool@v0.3.0a2" in result.output


def test_upgrade_up_to_date(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.3.0a2")
    assert "You already have the latest version" in result.output


def test_upgrade_stable_users_ignore_prereleases(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.2.0")
    assert result.exit_code == 1
    assert "No release" in result.output


def test_upgrade_private_or_missing_repo(monkeypatch):
    result = _upgrade_with(monkeypatch, [], "0.3.0a1", status=404)
    assert result.exit_code == 1
    assert "Cannot list the releases" in result.output
