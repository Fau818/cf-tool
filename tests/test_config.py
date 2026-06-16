"""Tests for config load/save round-trip, defaults, and ~/.cf migration."""

import json
from pathlib import Path

import cf_tool.config as config_module
from cf_tool.config import CodeTemplate, Config, migrate_legacy_dir


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
    assert cfg.default_template is None


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
    assert loaded.default_template.alias == "cpp"


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


def test_migrate_legacy_dir(tmp_path, monkeypatch):
    legacy, config_dir, state_dir = _patch_paths(monkeypatch, tmp_path)
    legacy.mkdir()
    (legacy / "config").write_text(
        json.dumps({"template": [{"alias": "cpp", "path": str(legacy / "template.cpp")}]})
    )
    (legacy / "session").write_text("{}")
    (legacy / "template.cpp").write_text("int main() {}\n")

    notes = migrate_legacy_dir()

    assert len(notes) == 3
    assert not legacy.exists()
    assert (state_dir / "session").read_text() == "{}"
    assert (config_dir / "template.cpp").is_file()
    cfg = json.loads((config_dir / "config").read_text())
    # template paths pointing into ~/.cf follow the move
    assert cfg["template"][0]["path"] == str(config_dir / "template.cpp")


def test_migrate_noop_without_legacy(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert migrate_legacy_dir() == []


def test_migrate_keeps_existing_targets(tmp_path, monkeypatch):
    legacy, config_dir, _ = _patch_paths(monkeypatch, tmp_path)
    legacy.mkdir()
    (legacy / "config").write_text("old")
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text("new")

    notes = migrate_legacy_dir()

    assert (config_dir / "config").read_text() == "new"
    assert (legacy / "config").read_text() == "old"  # never overwritten
    assert any("in place" in n for n in notes)
