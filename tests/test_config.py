"""Tests for config load/save round-trip and defaults."""

import json
from pathlib import Path

from cf_tool.config import CodeTemplate, Config


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
