"""Language presets: toolchain detection on a fake machine, the Codeforces
language each family submits as, and the files a preset writes."""

import shutil
import subprocess
import sys

import pytest

import cf_tool.config as config_module
from cf_tool import judge, langs, presets, templates
from cf_tool.config import CodeTemplate, Config
from cf_tool.presets import Machine, family, family_of, find

# a submit menu like Codeforces' in 2026 (ids made up)
LANGUAGES = {
    "1": "GNU GCC C11 5.1.0",
    "2": "Clang++20 Diagnostics",
    "3": "GNU G++17 7.3.0",
    "4": "GNU G++20 13.2 (64 bit, winlibs)",
    "5": "GNU G++23 14.2 (64 bit, msys2)",
    "6": "MS C++ 2017",
    "7": "Python 2.7.18",
    "8": "Python 3.13.2",
    "9": "PyPy 2.7.13 (7.3.0)",
    "10": "PyPy 3.6.9 (7.3.0)",
    "11": "PyPy 3.10 (7.3.15, 64bit)",
    "12": "Java 8 32bit",
    "13": "Java 21 64bit",
    "14": "Kotlin 1.9.21",
    "15": "Kotlin 2.2.0",
    "16": "Rust 1.75.0 (2021)",
    "17": "Rust 1.89.0 (2024)",
    "18": "Go 1.22.2",
    "19": "JavaScript V8 4.8.0",
}


def machine(banners: dict[str, str], platform: str = "linux") -> Machine:
    """A machine with these commands on PATH, each printing its version banner."""
    return Machine(
        which=lambda program: f"/bin/{program}" if program in banners else None,
        version=lambda program, flag: banners[program],
        platform=platform,
    )


def labels(preset_alias: str, banners: dict[str, str], platform: str = "linux") -> list[str]:
    return [t.label for t in find(preset_alias).detect(machine(banners, platform))]


# ┌──────────────────────────────────────────────────────────┐
# │                        Detection                         │
# └──────────────────────────────────────────────────────────┘


def test_cpp_gcc_before_clang():
    banners = {
        "clang++": "clang version 18.1.3 (1ubuntu1)",
        "g++": "g++ (Ubuntu 13.2.0-23ubuntu4) 13.2.0",
        "g++-14": "g++-14 (Ubuntu 14.2.0-4ubuntu2) 14.2.0",
    }
    assert labels("cpp", banners) == ["GCC 14 (g++-14)", "GCC 13 (g++)", "Clang 18 (clang++)"]


def test_cpp_on_a_mac_without_gcc():
    apple = "Apple clang version 17.0.0 (clang-1700.0.13.3)"
    chains = find("cpp").detect(machine({"clang++": apple, "g++": apple}, "darwin"))
    assert [t.label for t in chains] == ["Apple clang 17 (clang++)"]  # g++ is the same compiler
    (chain,) = chains
    assert chain.needs_shim
    assert f"-I{presets.shim_folder()}" in chain.before_script
    assert "-Wl,-stack_size,0x10000000" in chain.before_script  # NOTE: macOS's 8 MB stack


def test_cpp_on_a_mac_with_homebrew_gcc():
    banners = {
        "g++-14": "g++-14 (Homebrew GCC 14.2.0_1) 14.2.0",
        "clang++": "Apple clang version 17.0.0 (clang-1700.0.13.3)",
    }
    first = find("cpp").detect(machine(banners, "darwin"))[0]
    assert first.label == "GCC 14 (g++-14)"
    assert first.before_script == (
        "g++-14 -std=c++20 -O2 -Wall -Wl,-stack_size,0x10000000 -o $%file%$ $%full%$"
    )
    assert (first.script, first.after_script, first.needs_shim) == (
        "./$%file%$",
        "rm $%file%$",
        False,
    )


def test_cpp_on_windows():
    chain = find("cpp").detect(machine({"g++": "g++.exe (Rev2, Built by MSYS2) 14.2.0"}, "win32"))[
        0
    ]
    assert chain.before_script == "g++ -std=c++20 -O2 -Wall -o $%file%$.exe $%full%$"
    assert (chain.script, chain.after_script) == ("./$%file%$.exe", "")


def test_shim_folder_with_spaces_stays_one_word(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "My Config" / "cf")
    chain = find("cpp").detect(machine({"clang++": "clang version 18.1.3"}))[0]
    words = judge.split_cmd(chain.before_script)
    assert f"-I{tmp_path / 'My Config' / 'cf' / 'include'}" in words


def test_c_links_math_and_needs_no_shim():
    chain = find("c").detect(machine({"gcc": "gcc (GCC) 14.2.1 20240910"}))[0]
    assert chain.before_script == "gcc -std=c11 -O2 -Wall -o $%file%$ $%full%$ -lm"
    assert not chain.needs_shim


def test_python():
    banners = {
        "python3": "Python 3.12.4",
        "python": "Python 3.12.4",  # the same one again
        "pypy3": "Python 3.10.14 (75b3de9d9035, Apr 21 2024, 10:46:43)",
    }
    chains = find("py").detect(machine(banners))
    assert [t.label for t in chains] == ["Python 3.12 (python3)", "PyPy 3.10 (pypy3)"]
    assert chains[0].script == "python3 $%full%$" and chains[0].before_script == ""


def test_python_2_is_no_python():
    assert labels("py", {"python": "Python 2.7.18"}) == []


@pytest.mark.parametrize(
    "banner,found",
    [
        ('openjdk version "21.0.2" 2024-01-16', ["Java 21 (java)"]),
        ('java version "17.0.10" 2024-01-16 LTS', ["Java 17 (java)"]),
        ('openjdk version "1.8.0_402"', []),  # NOTE: too old to run a .java file directly
        ("", []),
    ],
)
def test_java(banner, found):
    assert labels("java", {"java": banner}) == found


def test_kotlin_needs_java_too():
    kotlinc = "info: kotlinc-jvm 2.1.0 (JRE 21.0.2+13-58)"
    assert labels("kt", {"kotlinc": kotlinc}) == []
    chain = find("kt").detect(machine({"kotlinc": kotlinc, "java": 'openjdk version "21"'}))[0]
    assert chain.label == "Kotlin 2.1 (kotlinc)"
    assert chain.script == "java -jar $%file%$.jar"


def test_rust_and_go():
    assert labels("rs", {"rustc": "rustc 1.82.0 (f6e511eec 2024-10-15)"}) == ["Rust 1.82 (rustc)"]
    assert labels("go", {"go": "go version go1.23.2 linux/amd64"}) == ["Go 1.23 (go)"]
    assert labels("go", {}) == []


def test_version_leaves_apple_placeholders_alone(monkeypatch):
    # NOTE: running /usr/bin/g++ or java without their tools opens an installer
    ran = []

    def run(argv, **kwargs):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 2, "", "")  # NOTE: no developer tools, no JDK

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda program: f"/usr/bin/{program}")
    monkeypatch.setattr(subprocess, "run", run)
    assert presets._version("g++", "--version") == ""
    assert presets._version("java", "-version") == ""
    assert ran == [["xcode-select", "-p"], ["/usr/libexec/java_home"]]


def test_version_reads_stderr_too(monkeypatch):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, "", 'openjdk version "21.0.2"\nOpenJDK Runtime\n'
        )

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda program: f"/usr/bin/{program}")
    monkeypatch.setattr(subprocess, "run", run)
    assert presets._version("java", "-version") == 'openjdk version "21.0.2"'


# ┌──────────────────────────────────────────────────────────┐
# │                   Codeforces languages                   │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.parametrize(
    "alias,best,members",
    [
        ("cpp", "GNU G++23 14.2 (64 bit, msys2)", ["5", "4", "3"]),  # no Diagnostics, no MS C++
        ("py", "PyPy 3.10 (7.3.15, 64bit)", ["11", "10", "8"]),  # no Python 2
        ("java", "Java 21 64bit", ["13", "12"]),
        ("kt", "Kotlin 2.2.0", ["15", "14"]),
        ("rs", "Rust 1.75.0 (2021)", ["16", "17"]),  # NOTE: the edition compiled here
        ("go", "Go 1.22.2", ["18"]),
        ("c", "GNU GCC C11 5.1.0", ["1"]),
    ],
)
def test_family_best_first(alias, best, members):
    found = family(find(alias), LANGUAGES)
    assert [lid for lid, _ in found] == members
    assert found[0][1] == best


def test_family_from_the_built_in_list():
    best = {p.alias: family(p, langs.LANGS)[0][1] for p in presets.PRESETS}
    assert best == {
        "cpp": "GNU G++23 14.2 (64 bit, msys2)",
        "py": "PyPy 3.10 (7.3.15, 64bit)",
        "java": "Java 21 64bit",
        "kt": "Kotlin 1.9.21",
        "rs": "Rust 1.89.0 (2021)",
        "go": "Go 1.22.2",
        "c": "GNU GCC C11 5.1.0",
    }


def test_family_of_a_template():
    assert family_of(CodeTemplate(suffix=["cc"]), LANGUAGES).name == "C++"
    assert family_of(CodeTemplate(suffix=["hpp"], lang="13"), LANGUAGES).name == "Java"
    assert family_of(CodeTemplate(suffix=["txt"], lang="999"), LANGUAGES) is None


def test_find():
    assert find("cxx").name == "C++" and find(".py").name == "Python"
    assert find("pas") is None


# ┌──────────────────────────────────────────────────────────┐
# │                          Files                           │
# └──────────────────────────────────────────────────────────┘


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    folder = tmp_path / "cf"
    monkeypatch.setattr(config_module, "CONFIG_DIR", folder)
    return folder


def test_make_template(config_dir):
    preset = find("cpp")
    chain = preset.detect(machine({"clang++": "clang version 18.1.3"}))[0]
    template = presets.make_template(preset, chain, "5")
    assert template == CodeTemplate(
        alias="cpp",
        lang="5",
        path=str(config_dir / "templates" / "template.cpp"),
        suffix=["cpp", "cc", "cxx"],
        before_script=chain.before_script,
        script="./$%file%$",
        after_script="rm $%file%$",
    )
    assert (config_dir / "templates" / "template.cpp").read_text() == presets.CPP_STARTER
    assert (config_dir / "include" / "bits" / "stdc++.h").read_text() == presets.STDCXX_SHIM


def test_starter_is_the_users_once_written(config_dir):
    path = presets.write_starter(find("py"))
    path.write_text("# my own template\n")
    assert presets.write_starter(find("py")).read_text() == "# my own template\n"


def test_shim_is_kept_current(config_dir):
    header = presets.write_shim()
    header.write_text("// old\n")
    assert presets.write_shim().read_text() == presets.STDCXX_SHIM


def test_every_starter_fills_in():
    for preset in presets.PRESETS:
        code = templates.substitute_code(preset.starter, "tourist")
        assert "$%" not in code and "tourist" in code, preset.name


def test_presets_keep_the_go_tool_schema(config_dir):
    preset = find("py")
    chain = preset.detect(machine({"python3": "Python 3.12.4"}))[0]
    cfg = Config(template=[presets.make_template(preset, chain, "11")], _path=config_dir / "c")
    cfg.save()
    assert Config.load(config_dir / "c").template == cfg.template


# ┌──────────────────────────────────────────────────────────┐
# │                     Real toolchains                      │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.toolchain
@pytest.mark.parametrize("preset", presets.PRESETS, ids=lambda preset: preset.alias)
def test_starter_builds_and_runs(preset, config_dir, tmp_path):
    """Opt-in (`pytest -m toolchain`): every starter, with every toolchain this
    machine has for it, compiles, runs quietly, and cleans up."""
    chains = preset.detect(Machine())
    if not chains:
        pytest.skip(f"no {preset.name} toolchain here")
    work = tmp_path / "work"
    work.mkdir()
    for chain in chains:
        template = presets.make_template(preset, chain, "0")
        source = work / f"a.{preset.ext}"
        source.write_text(templates.substitute_code(preset.starter, "tourist"))
        subs = templates.script_substitutions(source.name)
        judge.run_script(templates.substitute_script(template.before_script, **subs), work)
        argv = judge.split_cmd(templates.substitute_script(template.script, **subs))
        done = subprocess.run(
            argv, cwd=work, input="1\n", capture_output=True, text=True, timeout=120
        )
        assert (done.returncode, done.stdout) == (0, ""), (chain.label, done.stderr)
        judge.run_script(templates.substitute_script(template.after_script, **subs), work)
        assert sorted(p.name for p in work.iterdir()) == [source.name], chain.label
