"""CLI smoke tests (offline commands only), using an isolated HOME."""

import json
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
