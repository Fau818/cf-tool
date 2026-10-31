"""Languages: toolchains found on a fake machine, the commands made for
them, the Codeforces language each submits as, and starter code."""

import shutil
import subprocess
import sys
from datetime import datetime

import pytest

from cf_tool import build, languages, paths
from cf_tool.errors import CFError
from cf_tool.languages import (
    LANGUAGES,
    Machine,
    choose_submit,
    cpp_standard,
    family,
    render,
    setup,
    starter,
)
from cf_tool.settings import Settings

# a submit menu like Codeforces' in 2026 (ids made up)
OFFERED = {
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
    "20": "Haskell GHC 8.10.1",
}

GCC14 = "g++-14 (Ubuntu 14.2.0-4ubuntu2) 14.2.0"
APPLE = "Apple clang version 17.0.0 (clang-1700.0.13.3)"


def machine(banners: dict[str, str], platform: str = "linux") -> Machine:
    """A machine with these commands on PATH, each printing its version banner."""
    return Machine(
        which=lambda program: f"/bin/{program}" if program in banners else None,
        version=lambda program, flag: banners[program],
        platform=platform,
        accepts=None,  # NOTE: the standard by the compiler's version: nothing is run
    )


def labels(key: str, banners: dict[str, str], platform: str = "linux") -> list[str]:
    return [tool.label for tool in LANGUAGES[key].detect(machine(banners, platform))]


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
    return tmp_path


def settings_with(text: str = "") -> Settings:
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return Settings.load()


# ┌──────────────────────────────────────────────────────────┐
# │                        Detection                         │
# └──────────────────────────────────────────────────────────┘


def test_cpp_gcc_before_clang():
    banners = {
        "clang++": "clang version 18.1.3 (1ubuntu1)",
        "g++": "g++ (Ubuntu 13.2.0-23ubuntu4) 13.2.0",
        "g++-14": GCC14,
    }
    assert labels("cpp", banners) == ["GCC 14 (g++-14)", "GCC 13 (g++)", "Clang 18 (clang++)"]


def test_cpp_on_a_mac_without_gcc():
    assert labels("cpp", {"clang++": APPLE, "g++": APPLE}, "darwin") == [
        "Apple clang 17 (clang++)"  # NOTE: g++ is the same compiler
    ]


def test_c_and_python():
    assert labels("c", {"gcc": "gcc (GCC) 14.2.1 20240910"}) == ["GCC 14 (gcc)"]
    banners = {
        "python3": "Python 3.12.4",
        "python": "Python 3.12.4",  # the same one again
        "pypy3": "Python 3.10.14 (75b3de9d9035, Apr 21 2024, 10:46:43)",
    }
    assert labels("py", banners) == ["Python 3.12 (python3)", "PyPy 3.10 (pypy3)"]
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


def test_kotlin_rust_go():
    kotlinc = "info: kotlinc-jvm 2.1.0 (JRE 21.0.2+13-58)"
    assert labels("kt", {"kotlinc": kotlinc}) == []  # NOTE: it needs java too
    assert labels("kt", {"kotlinc": kotlinc, "java": 'openjdk version "21"'}) == [
        "Kotlin 2.1 (kotlinc)"
    ]
    assert labels("rs", {"rustc": "rustc 1.82.0 (f6e511eec 2024-10-15)"}) == ["Rust 1.82 (rustc)"]
    assert labels("go", {"go": "go version go1.23.2 linux/amd64"}) == ["Go 1.23 (go)"]


def test_apple_placeholders_are_left_alone(monkeypatch):
    # NOTE: running /usr/bin/g++ or java without their tools opens an installer
    ran = []

    def run(argv, **kwargs):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 2, "", "")  # NOTE: no developer tools, no JDK

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert languages._version_text("/usr/bin/g++", "--version") == ""
    assert languages._version_text("/usr/bin/java", "-version") == ""
    assert ran == [["xcode-select", "-p"], ["/usr/libexec/java_home"]]


def test_versions_are_remembered(monkeypatch, tmp_path):
    tool = tmp_path / "bin" / "g++-14"
    tool.parent.mkdir()
    tool.write_text("")
    asked = []

    def version_text(where, flag):
        asked.append(where)
        return GCC14 if len(asked) > 1 else ""

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda program: str(tool))
    monkeypatch.setattr(languages, "_version_text", version_text)
    monkeypatch.setattr(languages, "_banners", None)
    assert languages._cached_version("g++-14", "--version") == ""  # NOTE: not remembered
    assert languages._cached_version("g++-14", "--version") == GCC14
    monkeypatch.setattr(languages, "_banners", None)  # NOTE: a new run reads the file
    assert languages._cached_version("g++-14", "--version") == GCC14
    assert len(asked) == 2


# ┌──────────────────────────────────────────────────────────┐
# │                        Commands                          │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.parametrize(
    "submit,kind,version,standard",
    [
        ("GNU G++23 14.2 (64 bit, msys2)", "gcc", (14, 2), "c++23"),
        ("GNU G++20 13.2 (64 bit, winlibs)", "gcc", (14, 2), "c++20"),
        ("GNU G++17 7.3.0", "clang", (18,), "c++17"),
        ("C++20 (GCC 13-64)", "gcc", (13,), "c++20"),
        ("GNU G++23 14.2", "gcc", (10, 2), "c++20"),  # NOTE: c++2b came with GCC 11
        ("GNU G++23 14.2", "gcc", (9, 4), "c++2a"),
        ("GNU G++23 14.2", "clang", (11,), "c++20"),
        ("GNU G++23 14.2", "apple clang", (15,), "c++2b"),
        ("GNU G++23 14.2", "apple clang", (17,), "c++23"),
        ("", "gcc", (14,), "c++23"),
    ],
)
def test_cpp_standard(submit, kind, version, standard):
    tool = languages.Tool("g++", "g++", kind=kind, version=version)
    assert cpp_standard(submit, tool) == standard


def test_the_compiler_is_asked_which_standards_it_takes():
    tool = languages.Tool("g++", "g++", kind="gcc", version=(14,))
    asked = []

    def accepts(program, std):
        asked.append(std)
        return std in ("c++2a", "c++17")

    assert cpp_standard("GNU G++23 14.2", tool, accepts) == "c++2a"
    assert asked == ["c++23", "c++2b", "c++20", "c++2a"]


def test_asking_is_remembered(monkeypatch):
    runs = []

    def run(argv, **kwargs):
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0 if "-std=c++20" in argv else 1, b"", b"")

    monkeypatch.setattr(shutil, "which", lambda program: "/opt/bin/g++")
    monkeypatch.setattr(languages, "_cached_version", lambda program, flag: "g++ (GCC) 10.2.1")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(languages, "_banners", None)
    assert not languages._accepts_std("g++", "c++23") and languages._accepts_std("g++", "c++20")
    assert languages._accepts_std("g++", "c++20") and len(runs) == 2  # NOTE: once each


def test_cpp_on_linux():
    s = setup("cpp", Settings(), offered=OFFERED, machine=machine({"g++-14": GCC14}))
    assert s.tool == "GCC 14 (g++-14)" and s.submit == ("5", "GNU G++23 14.2 (64 bit, msys2)")
    assert s.build == ("g++-14", "-std=c++23", "-O2", "-Wall", "{src}", "-o", "{exe}")
    assert s.run == ("{exe}",) and s.big_stack


def test_cpp_on_a_mac_brings_its_own_header():
    s = setup("cpp", Settings(), offered=OFFERED, machine=machine({"clang++": APPLE}, "darwin"))
    shim = languages.shim_folder()
    assert s.build == (
        "clang++",
        "-std=c++23",
        "-O2",
        "-Wall",
        "-Wl,-stack_size,0x10000000",
        f"-I{shim}",
        "{src}",
        "-o",
        "{exe}",
    )
    assert (shim / "bits" / "stdc++.h").read_text() == languages.STDCXX_SHIM


def test_cpp_on_windows():
    win = machine({"g++": "g++.exe (Rev2, Built by MSYS2) 14.2.0"}, "win32")
    assert "-Wl,--stack,268435456" in setup("cpp", Settings(), offered=OFFERED, machine=win).build


def test_settings_change_the_commands():
    settings = settings_with('[cpp]\ncompiler = "g++-13"\nflags = "-DLOCAL"\nsubmit = "G++17"\n')
    banners = {"g++-13": "g++-13 (GCC) 13.3.0", "g++-14": GCC14}
    s = setup("cpp", settings, offered=OFFERED, machine=machine(banners))
    assert s.submit == ("3", "GNU G++17 7.3.0") and s.tool == "g++-13"
    assert s.build == ("g++-13", "-std=c++17", "-O2", "-Wall", "-DLOCAL", "{src}", "-o", "{exe}")


def test_build_and_run_set_in_full():
    settings = settings_with('[cpp]\nbuild = "make {name}"\nrun = "./{name}"\n')
    s = setup("cpp", settings, offered=OFFERED, machine=machine({"g++-14": GCC14}))
    assert (s.build, s.run) == (("make", "{name}"), ("./{name}",))
    nothing = settings_with('[py]\nbuild = ""\nrun = "pypy3 -O {src}"\n')
    s = setup("py", nothing, offered=OFFERED, machine=machine({"python3": "Python 3.12.4"}))
    assert (s.build, s.run) == (None, ("pypy3", "-O", "{src}"))


def test_a_compiler_that_is_not_installed():
    settings = settings_with('[cpp]\ncompiler = "g++-99"\n')
    with pytest.raises(CFError, match="g\\+\\+-99, the compiler set for \\[cpp\\]"):
        setup("cpp", settings, offered=OFFERED, machine=machine({"g++-14": GCC14}))


def test_no_compiler_says_how_to_get_one():
    with pytest.raises(CFError, match="No C\\+\\+ compiler or interpreter found.*brew install gcc"):
        setup("cpp", Settings(), offered=OFFERED, machine=machine({}, "darwin"))


def test_a_language_from_the_settings():
    settings = settings_with(
        '[hs]\nbuild = "ghc -O2 {src} -o {exe}"\nrun = "{exe}"\nsubmit = "Haskell"\n'
    )
    s = setup("hs", settings, offered=OFFERED, machine=machine({}))
    assert s.name == "Haskell" and s.submit == ("20", "Haskell GHC 8.10.1")
    assert s.build == ("ghc", "-O2", "{src}", "-o", "{exe}") and s.run == ("{exe}",)
    with pytest.raises(CFError, match="cf-tool doesn't know .pas files"):
        setup("pas", Settings(), offered=OFFERED, machine=machine({}))


def test_python_tests_with_pypy_when_submitting_pypy():
    banners = {"python3": "Python 3.12.4", "pypy3": "Python 3.10.14 (75b3de9d9035)"}
    s = setup("py", Settings(), offered=OFFERED, machine=machine(banners))
    assert s.submit == ("11", "PyPy 3.10 (7.3.15, 64bit)") and s.run == ("pypy3", "{src}")
    cpython = settings_with('[py]\nsubmit = "Python 3"\n')
    assert setup("py", cpython, offered=OFFERED, machine=machine(banners)).run == (
        "python3",
        "{src}",
    )


def test_java_commands(tmp_path):
    jdk = machine({"java": 'openjdk version "21.0.2"', "javac": "javac 21.0.2"})
    source = tmp_path / "a.java"
    source.write_text("import java.util.*;\npublic final class Main {}\n")
    s = setup("java", Settings(), source=source, offered=OFFERED, machine=jdk)
    assert s.build == ("javac", "-encoding", "UTF-8", "-d", "{dir}", "{copy}")
    assert s.run == ("java", "-cp", "{dir}", "Main")
    assert s.copy_as == "Main.java"  # NOTE: javac wants Main in Main.java, not a.java
    source.write_text("class Solution {}\n")  # NOTE: no public class to name
    s = setup("java", Settings(), source=source, offered=OFFERED, machine=jdk)
    assert (s.build, s.run) == (None, ("java", "{src}"))


def test_rust_edition_follows_the_submit_language():
    rust = machine({"rustc": "rustc 1.86.0 (05f9846f8 2025-03-31)"})
    s = setup("rs", Settings(), offered=OFFERED, machine=rust)
    assert s.submit == ("17", "Rust 1.89.0 (2024)") and "2024" in s.build
    old = machine({"rustc": "rustc 1.82.0 (f6e511eec 2024-10-15)"})
    assert "2021" in setup("rs", Settings(), offered=OFFERED, machine=old).build


def test_kotlin_and_go_commands():
    kotlin = machine({"kotlinc": "info: kotlinc-jvm 2.1.0", "java": 'openjdk version "21"'})
    s = setup("kt", Settings(), offered=OFFERED, machine=kotlin)
    assert s.build == ("kotlinc", "{src}", "-include-runtime", "-d", "{dir}/{name}.jar")
    assert s.run == ("java", "-jar", "{dir}/{name}.jar")
    s = setup("go", Settings(), offered=OFFERED, machine=machine({"go": "go version go1.23.2"}))
    assert (s.build, s.run) == (("go", "build", "-o", "{exe}", "{src}"), ("{exe}",))


def test_language_key():
    settings = settings_with('[hs]\nrun = "runghc {src}"\n[cc]\nrun = "./{name}"\n')
    assert languages.language_key("a.cxx") == "cpp" and languages.language_key(".py") == "py"
    assert languages.language_key("A.CPP") == "cpp"
    assert (
        languages.language_key("a.hs") is None and languages.language_key("a.hs", settings) == "hs"
    )
    assert languages.language_key("x.cc", settings) == "cc"  # NOTE: its own table wins
    assert ".hs" in languages.code_extensions(settings) and ".cpp" in languages.code_extensions()


# ┌──────────────────────────────────────────────────────────┐
# │                   Codeforces languages                   │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.parametrize(
    "key,best,members",
    [
        ("cpp", "GNU G++23 14.2 (64 bit, msys2)", ["5", "4", "3"]),  # no Diagnostics, no MS C++
        ("py", "PyPy 3.10 (7.3.15, 64bit)", ["11", "10", "8"]),  # no Python 2
        ("java", "Java 21 64bit", ["13", "12"]),
        ("kt", "Kotlin 2.2.0", ["15", "14"]),
        ("rs", "Rust 1.89.0 (2024)", ["17", "16"]),
        ("go", "Go 1.22.2", ["18"]),
        ("c", "GNU GCC C11 5.1.0", ["1"]),
    ],
)
def test_family_best_first(key, best, members):
    found = family(key, OFFERED)
    assert [lid for lid, _ in found] == members and found[0][1] == best


def test_the_built_in_list_has_every_family():
    best = {key: family(key, languages.LANGS)[0][1] for key in LANGUAGES}
    assert best == {
        "cpp": "GNU G++23 14.2 (64 bit, msys2)",
        "c": "GNU GCC C11 5.1.0",
        "py": "PyPy 3.10 (7.3.15, 64bit)",
        "java": "Java 21 64bit",
        "kt": "Kotlin 1.9.21",
        "rs": "Rust 1.89.0 (2024)",
        "go": "Go 1.22.2",
    }


@pytest.mark.parametrize(
    "key,spec,chosen",
    [
        ("cpp", "", "5"),
        ("cpp", "89", None),  # NOTE: not offered here
        ("cpp", "20", "4"),  # NOTE: id 20 is Haskell: as part of a name, G++20
        ("hs", "20", "20"),
        ("cpp", "3", "3"),
        ("cpp", "G++20", "4"),
        ("cpp", "c++20", "4"),  # NOTE: C++ and G++ are the same here
        ("cpp", "gnu g++17", "3"),
        ("cpp", "Clang++20", "2"),  # NOTE: outside the family, still found when named
        ("py", "python", "8"),
        ("py", "Ruby", None),
        ("hs", "", "20"),
    ],
)
def test_choose_submit(key, spec, chosen):
    found = choose_submit(key, spec, OFFERED)
    assert (found[0] if found else None) == chosen


def test_the_list_read_last_is_kept():
    assert languages.known_languages() == languages.LANGS
    languages.remember_languages({"1": "GNU G++99"})
    assert languages.known_languages() == {"1": "GNU G++99"}


def test_ext_of_every_spelling():
    for name, ext in [
        ("GNU G++17 7.3.0", "cpp"),
        ("C++20 (GCC 13-64)", "cpp"),
        ("GNU C11", "c"),
        ("PyPy 3-64", "py"),
        ("Java 21", "java"),
        ("JavaScript", "js"),
        ("Rust 2024", "rs"),
        ("C# 10", "cs"),
        ("PascalABC.NET 3.8.3", "pas"),
        ("Befunge", "bf"),
        ("Something new", "txt"),
    ]:
        assert languages.ext_of(name) == ext, name


# ┌──────────────────────────────────────────────────────────┐
# │                       Starter code                       │
# └──────────────────────────────────────────────────────────┘


def test_render():
    now = datetime(2026, 10, 31, 1, 33, 7)
    values = {"name": "A. Two Friends", "url": "https://codeforces.com/contest/2050/problem/A"}
    assert render("// {{name}}\n// {{ url }}\nint x;\n", values, now) == (
        "// A. Two Friends\n// https://codeforces.com/contest/2050/problem/A\nint x;\n"
    )
    old = "// $%U%$ $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$:$%s%$\n"
    assert render(old, {"handle": "tourist"}, now) == "// tourist 2026-10-31 01:33:07\n"
    # NOTE: nothing to fill in: the comment line goes, other placeholders stay
    assert render("# {{url}}\nx = '{{other}}'\n", {}, now) == "x = '{{other}}'\n"


def test_starter_sources(folders):
    settings = Settings()
    text, origin = starter("cpp", settings)
    assert origin == "built-in" and "bits/stdc++.h" in text
    templates = paths.templates_dir()
    templates.mkdir(parents=True)
    (templates / "template.cpp").write_text("// mine\n")
    (templates / "brute.cpp").write_text("// brute\n")
    assert starter("cpp", settings) == ("// mine\n", str(templates / "template.cpp"))
    assert starter("cpp", settings, "brute")[0] == "// brute\n"
    assert starter("cpp", settings, "gen")[0] == "// mine\n"  # NOTE: no gen.cpp: the usual one
    own = folders / "t.cpp"
    own.write_text("// set\n")
    configured = settings_with(f'[cpp]\ntemplate = "{own}"\n')
    assert starter("cpp", configured) == ("// set\n", str(own))
    own.unlink()
    with pytest.raises(CFError, match="doesn't exist"):
        starter("cpp", configured)
    assert starter("hs", settings) == ("", "built-in")


def test_every_starter_fills_in():
    for language in LANGUAGES.values():
        code = render(language.starter, {"name": "A. X", "url": "https://x"})
        assert "{{" not in code and "A. X" in code, language.name


def test_shim_is_kept_current():
    header = languages.write_shim()
    header.write_text("// old\n")
    assert languages.write_shim().read_text() == languages.STDCXX_SHIM


# ┌──────────────────────────────────────────────────────────┐
# │                     Real toolchains                      │
# └──────────────────────────────────────────────────────────┘


@pytest.mark.toolchain
@pytest.mark.parametrize("key", list(LANGUAGES))
def test_starter_builds_and_runs(key, tmp_path):
    """Opt-in (`pytest -m toolchain`): every starter, with every toolchain this
    machine has for its language, builds and runs quietly."""
    language = LANGUAGES[key]
    tools = language.detect(Machine())
    if not tools:
        pytest.skip(f"no {language.name} toolchain here")
    for tool in tools:
        settings = settings_with(f'[{key}]\ncompiler = "{tool.program}"\n')
        work = tmp_path / tool.program
        work.mkdir()
        source = work / f"a.{key}"
        source.write_text(render(language.starter, {"name": "A. Test", "url": "https://x"}))
        program = build.Program(source, setup(key, settings, source=source))
        program.build()
        result = program.run(stdin=b"1\n", timeout=120)
        assert (result.status, result.stdout) == ("ok", b""), (tool.label, result.stderr)
        assert sorted(p.name for p in work.iterdir()) == [source.name], tool.label
