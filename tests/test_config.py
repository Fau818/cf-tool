"""Tests for config load/save round-trip, defaults, and the ~/.cf import."""

import json
import os
import stat
from pathlib import Path

import pytest

import cf_tool.config as config_module
from cf_tool.config import CodeTemplate, Config, import_legacy_dir, write_atomic
from cf_tool.errors import CFError


def test_defaults():
    cfg = Config()
    assert cfg.host == "https://codeforces.com"
    assert cfg.gen_after_parse is False
    assert cfg.folder_name == {
        "root": "cf",
        "contest": "contest",
        "gym": "gym",
        "group": "group",
        "acmsguru": "acmsguru",
    }
    with pytest.raises(CFError, match="add at least one code template"):
        cfg.default_template()


def test_load_missing_file(tmp_path):
    cfg = Config.load(tmp_path / "config")
    assert cfg.host == "https://codeforces.com"
    assert cfg.template == []


def test_round_trip(tmp_path):
    path = tmp_path / "config"
    cfg = Config.load(path)
    cfg.template.append(
        CodeTemplate(
            alias="cpp",
            lang="54",
            path="~/template/io.cpp",
            suffix=["cpp", "cc"],
            before_script="g++ $%full%$ -o $%file%$ -O2 -std=c++17",
            script="./$%file%$",
            after_script="rm $%file%$",
        )
    )
    cfg.default = 0
    cfg.gen_after_parse = True
    cfg.save()

    loaded = Config.load(path)
    assert loaded.template == cfg.template
    assert loaded.gen_after_parse is True
    assert loaded.default_template().alias == "cpp"


def test_default_index_clamped(tmp_path):
    path = tmp_path / "config"
    path.write_text(json.dumps({"default": 5, "template": []}))
    assert Config.load(path).default == 0


def test_unknown_template_keys_ignored(tmp_path):
    path = tmp_path / "config"
    path.write_text(json.dumps({"template": [{"alias": "py", "lang": "31", "no_such_key": 1}]}))
    cfg = Config.load(path)
    assert cfg.template[0].alias == "py"


def test_partial_folder_name_filled(tmp_path):
    path = tmp_path / "config"
    path.write_text(json.dumps({"folder_name": {"root": "codeforces"}}))
    cfg = Config.load(path)
    assert cfg.folder_name["root"] == "codeforces"
    assert cfg.folder_name["gym"] == "gym"


def test_broken_config_is_an_error_not_a_reset(tmp_path):
    path = tmp_path / "config"
    path.write_text('{"template": [')  # truncated
    with pytest.raises(CFError, match="broken"):
        Config.load(path)
    assert path.read_text() == '{"template": ['  # left alone for the user to fix


def test_suffix_string_is_split(tmp_path):
    path = tmp_path / "config"
    path.write_text(json.dumps({"template": [{"alias": "cpp", "suffix": "cpp cc"}]}))
    assert Config.load(path).template[0].suffix == ["cpp", "cc"]


def test_write_atomic_sets_mode_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "state" / "session"
    write_atomic(path, "{}", mode=0o600)
    write_atomic(path, '{"a": 1}', mode=0o600)
    assert path.read_text() == '{"a": 1}'
    if os.name == "posix":  # Windows has no such permission bits
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["session"]


def test_templates_by_alias():
    cfg = Config(
        template=[
            CodeTemplate(alias="cpp", lang="54"),
            CodeTemplate(alias="cpp", lang="89"),
            CodeTemplate(alias="py", lang="31"),
        ]
    )
    assert len(cfg.templates_by_alias("cpp")) == 2
    assert cfg.templates_by_alias("rs") == []


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy = tmp_path / ".cf"
    config_dir = tmp_path / ".config" / "cf"
    state_dir = tmp_path / ".local" / "state" / "cf"
    monkeypatch.setattr(config_module, "LEGACY_DIR", legacy)
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "STATE_DIR", state_dir)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_dir / "config")
    monkeypatch.setattr(config_module, "SESSION_PATH", state_dir / "session")
    return legacy, config_dir, state_dir


def test_import_copies_and_leaves_legacy_intact(tmp_path, monkeypatch):
    legacy, config_dir, state_dir = _patch_paths(monkeypatch, tmp_path)
    legacy.mkdir()
    (legacy / "config").write_text('{"template": []}')
    (legacy / "session").write_text("{}")

    notes = import_legacy_dir()

    assert len(notes) == 2
    # the Go tool keeps working: nothing under ~/.cf is moved or changed
    assert sorted(p.name for p in legacy.iterdir()) == ["config", "session"]
    assert (config_dir / "config").read_text() == '{"template": []}'
    if os.name == "posix":
        assert stat.S_IMODE((state_dir / "session").stat().st_mode) == 0o600
    # second run: everything is in place, nothing to say
    assert import_legacy_dir() == []


def test_import_noop_without_legacy(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert import_legacy_dir() == []


def test_import_never_overwrites(tmp_path, monkeypatch):
    legacy, config_dir, _ = _patch_paths(monkeypatch, tmp_path)
    legacy.mkdir()
    (legacy / "config").write_text("old")
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text("new")

    assert import_legacy_dir() == []
    assert (config_dir / "config").read_text() == "new"
