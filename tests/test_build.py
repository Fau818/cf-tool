"""Builds: cached by source and command, rebuilt when either changes, kept
out of the code's folder."""

import os
import sys
import time

import pytest

from cf_tool import build, paths
from cf_tool.build import BuildFailed, Program, fill
from cf_tool.languages import Setup

PY = sys.executable
# a "compiler" that logs each run, then copies the source to {dir}/prog.py
COMPILE = (
    "import shutil, sys\n"
    "open(sys.argv[3], 'a').write('built\\n')\n"
    "if 'syntax error' in open(sys.argv[1]).read():\n"
    "    sys.exit('a.x:1: error: syntax error')\n"
    "shutil.copy(sys.argv[1], sys.argv[2])\n"
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(build, "_pruned", False)
    return tmp_path / "cache"


def fake_setup(log, fingerprint="fake 1.0") -> Setup:
    return Setup(
        key="x",
        name="X",
        tool="fake",
        build=(PY, "-c", COMPILE, "{src}", "{dir}/prog.py", str(log)),
        run=(PY, "{dir}/prog.py"),
        fingerprint=fingerprint,
    )


def builds(log) -> int:
    return len(log.read_text().splitlines()) if log.exists() else 0


def test_build_once_then_cached(tmp_path, cache):
    source = tmp_path / "a.x"
    source.write_text("print('hi')\n")
    log = tmp_path / "log"
    first = Program(source, fake_setup(log)).build()
    assert not first.cached and builds(log) == 1
    program = Program(source, fake_setup(log))
    assert program.build().cached and builds(log) == 1
    assert program.run(timeout=30).stdout == b"hi\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.x", "cache", "log"]  # NOTE: no build


def test_a_change_builds_again(tmp_path, cache):
    source = tmp_path / "a.x"
    log = tmp_path / "log"
    source.write_text("print(1)\n")
    Program(source, fake_setup(log)).build()
    source.write_text("print(2)\n")
    program = Program(source, fake_setup(log))
    assert not program.build().cached and program.run(timeout=30).stdout == b"2\n"
    Program(source, fake_setup(log, fingerprint="fake 2.0")).build()  # NOTE: a new compiler
    assert builds(log) == 3


def test_local_includes_build_every_time(tmp_path, cache):
    source = tmp_path / "a.x"
    source.write_text('#include "lib.h"\nprint(1)\n')
    log = tmp_path / "log"
    Program(source, fake_setup(log)).build()
    assert not Program(source, fake_setup(log)).build().cached and builds(log) == 2


def test_failed_build(tmp_path, cache):
    source = tmp_path / "a.x"
    source.write_text("syntax error\n")
    with pytest.raises(BuildFailed, match="a.x doesn't compile") as failed:
        Program(source, fake_setup(tmp_path / "log")).build()
    assert "error: syntax error" in failed.value.output
    assert list((cache / "build").iterdir()) == []  # NOTE: no half-built folder stays


def test_nothing_to_build(tmp_path, cache):
    source = tmp_path / "a.py"
    source.write_text("print('py')\n")
    setup = Setup("py", "Python", "python3", None, (PY, "{src}"))
    program = Program(source, setup)
    assert program.build().cached
    assert program.argv() == [PY, str(source)]
    assert program.run(timeout=30).stdout == b"py\n"


def test_old_builds_are_pruned(tmp_path, cache):
    old = cache / "build" / "old"
    old.mkdir(parents=True)
    (old / ".built").write_text("")
    stamp = time.time() - build.MAX_AGE - 60
    os.utime(old / ".built", (stamp, stamp))
    source = tmp_path / "a.x"
    source.write_text("print(1)\n")
    Program(source, fake_setup(tmp_path / "log")).build()
    assert not old.exists()


def test_fill():
    values = {"src": "/w/a.cpp", "exe": "/c/a", "dir": "/c", "name": "a"}
    assert fill(("g++", "{src}", "-o", "{exe}", "-I{dir}/inc", "{other}"), values) == [
        "g++",
        "/w/a.cpp",
        "-o",
        "/c/a",
        "-I/c/inc",
        "{other}",
    ]


def test_a_header_change_in_an_include_folder_builds_again(tmp_path, cache):
    library = tmp_path / "lib"
    library.mkdir()
    header = library / "mylib.h"
    header.write_text("// 1\n")
    source = tmp_path / "a.x"
    source.write_text("print(1)\n")
    log = tmp_path / "log"
    setup = fake_setup(log)
    setup = Setup(**{**setup.__dict__, "build": (*setup.build, f"-I{library}")})
    Program(source, setup).build()
    assert Program(source, setup).build().cached
    header.write_text("// 2, a little longer\n")
    assert not Program(source, setup).build().cached and builds(log) == 2


def test_a_build_finished_meanwhile_is_kept(tmp_path, cache, monkeypatch):
    # NOTE: two cf at once: the one that finishes second leaves the first's build alone
    source = tmp_path / "a.x"
    source.write_text("print(1)\n")
    program = Program(source, fake_setup(tmp_path / "log"))
    real_run = build.process.run

    def run(argv, **options):
        result = real_run(argv, **options)
        folder = program._folder
        folder.mkdir(parents=True)
        (folder / "prog.py").write_text("print('first')\n")
        (folder / ".built").write_text("")
        return result

    monkeypatch.setattr(build.process, "run", run)
    program.build()
    monkeypatch.setattr(build.process, "run", real_run)
    assert program.run(timeout=30).stdout == b"first\n"
    assert [p.name for p in (cache / "build").iterdir()] == [program._folder.name]
