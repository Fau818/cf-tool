"""Tests for template substitution and gen."""

from datetime import datetime

import pytest

from cf_tool.config import CodeTemplate, Config
from cf_tool.errors import CFError
from cf_tool.templates import (
    gen,
    generate_file,
    rand_string,
    script_substitutions,
    substitute_code,
    substitute_script,
)


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
