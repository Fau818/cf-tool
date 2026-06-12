"""Tests for template substitution, code detection, and gen."""

from datetime import datetime
from pathlib import Path

import pytest

from cf_tool.config import CodeTemplate, Config
from cf_tool.errors import CFError
from cf_tool.templates import (
    gen,
    generate_file,
    get_code,
    get_one_code,
    rand_string,
    script_substitutions,
    substitute_code,
    substitute_script,
)

CPP = CodeTemplate(alias="cpp", lang="89", suffix=["cpp", "cc"], script="./$%file%$")
PY = CodeTemplate(alias="py", lang="31", suffix=["py"], script="python3 $%full%$")


def test_substitute_code():
    now = datetime(2026, 6, 11, 8, 5, 0)
    source = "// $%U%$ $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$:$%s%$"
    assert substitute_code(source, "tourist", now) == "// tourist 2026-06-11 08:05:00"


def test_substitute_script():
    script = "g++ $%full%$ -o $%file%$_$%rand%$ && cp $%path%$x ."
    out = substitute_script(script, path="dir/", full="a.cpp", file="a", rand="r4nd0m12")
    assert out == "g++ a.cpp -o a_r4nd0m12 && cp dir/x ."


def test_script_substitutions():
    subs = script_substitutions("a.cpp")
    assert (subs["path"], subs["full"], subs["file"]) == ("", "a.cpp", "a")
    assert len(subs["rand"]) == 8
    subs = script_substitutions("dir/b.test.py")
    assert (subs["path"], subs["full"], subs["file"]) == ("dir/", "b.test.py", "b.test")


def test_rand_string():
    s = rand_string(8)
    assert len(s) == 8 and all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in s)


def test_get_code_scans_cwd(tmp_path):
    (tmp_path / "a.cpp").touch()
    (tmp_path / "b.py").touch()
    (tmp_path / "in1.txt").touch()
    codes = get_code(None, [CPP, PY], tmp_path)
    assert [(c.name, c.indexes) for c in codes] == [("a.cpp", [0]), ("b.py", [1])]


def test_get_code_explicit_file(tmp_path):
    codes = get_code("sol.cc", [CPP, PY], tmp_path)
    assert [(c.name, c.indexes) for c in codes] == [("sol.cc", [0])]
    with pytest.raises(CFError, match="can not match any template"):
        get_code("sol.rs", [CPP, PY], tmp_path)


def test_get_one_code_unambiguous(tmp_path):
    (tmp_path / "a.cpp").touch()
    assert get_one_code(None, [CPP, PY], tmp_path) == ("a.cpp", 0)


def test_get_one_code_empty(tmp_path):
    with pytest.raises(CFError, match="Cannot find any code"):
        get_one_code(None, [CPP, PY], tmp_path)


def test_get_one_code_multiple_files_prompts(tmp_path, monkeypatch):
    (tmp_path / "a.cpp").touch()
    (tmp_path / "b.cpp").touch()
    monkeypatch.setattr("cf_tool.ui.choose_index", lambda n: 1)
    assert get_one_code(None, [CPP, PY], tmp_path) == ("b.cpp", 0)


def test_get_one_code_multiple_templates_prompts(tmp_path, monkeypatch):
    cpp17 = CodeTemplate(alias="cpp17", lang="54", suffix=["cpp"])
    (tmp_path / "a.cpp").touch()
    monkeypatch.setattr("cf_tool.ui.choose_index", lambda n: 1)
    assert get_one_code(None, [CPP, cpp17], tmp_path) == ("a.cpp", 1)


def test_generate_file_collision(tmp_path, capsys):
    problem_dir = tmp_path / "a"
    problem_dir.mkdir()
    first = generate_file("x", problem_dir, ".cpp")
    assert first == problem_dir / "a.cpp"
    second = generate_file("y", problem_dir, ".cpp")
    assert second == problem_dir / "a1.cpp"
    assert second.read_text() == "y"


def test_gen_uses_default_template(tmp_path):
    template_file = tmp_path / "tpl.cpp"
    template_file.write_text("// by $%U%$\n")
    cfg = Config(template=[CodeTemplate(alias="cpp", path=str(template_file), suffix=["cpp"])])
    problem_dir = tmp_path / "b"
    problem_dir.mkdir()
    out = gen(cfg, "tourist", problem_dir)
    assert out == problem_dir / "b.cpp"
    assert out.read_text() == "// by tourist\n"


def test_gen_no_templates(tmp_path):
    with pytest.raises(CFError, match="add at least one code template"):
        gen(Config(), "x", tmp_path)


def test_gen_unknown_alias(tmp_path):
    cfg = Config(template=[CodeTemplate(alias="cpp", path="/nope.cpp", suffix=["cpp"])])
    with pytest.raises(CFError, match="Cannot find any template with alias rs"):
        gen(cfg, "x", tmp_path, alias="rs")
