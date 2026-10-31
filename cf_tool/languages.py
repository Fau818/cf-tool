"""Languages: how each one is built and run here, and what it is submitted as.

A language is named by its file extension (cpp, py, ...). cf-tool knows seven,
and config.toml can change any part of one, or add one:
- the compiler or interpreter: found on this machine, best first, unless set
- the build and run commands: made for it, unless set in full
- the Codeforces language: the setting, else the newest of its family
- the starter code for new problems: the setting, else a built-in one
C++ is compiled with the -std of the Codeforces language it is submitted as,
so code that compiles here compiles there too.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from cf_tool import paths
from cf_tool.errors import CFError

if TYPE_CHECKING:
    from cf_tool.settings import Settings


# ┌──────────────────────────────────────────────────────────┐
# │                   Codeforces languages                   │
# └──────────────────────────────────────────────────────────┘

# NOTE: ids as Codeforces' submit form has them (checked against the cph
# \     extension's table, 2026-09); the live list replaces it once read
LANGS: dict[str, str] = {
    "43": "GNU GCC C11 5.1.0",
    "52": "Clang++17 Diagnostics",
    "50": "GNU G++14 6.4.0",
    "54": "GNU G++17 7.3.0",
    "61": "GNU G++17 9.2.0 (64 bit, msys 2)",
    "89": "GNU G++20 13.2 (64 bit, winlibs)",
    "91": "GNU G++23 14.2 (64 bit, msys2)",
    "59": "Microsoft Visual C++ 2017",
    "65": "C# 8, .NET Core 3.1",
    "79": "C# 10, .NET SDK 6.0",
    "9": "C# Mono 6.8",
    "28": "D DMD32 v2.105.0",
    "32": "Go 1.22.2",
    "12": "Haskell GHC 8.10.1",
    "87": "Java 21 64bit",
    "60": "Java 11.0.6",
    "36": "Java 8 32bit",
    "83": "Kotlin 1.7.20",
    "88": "Kotlin 1.9.21",
    "19": "OCaml 4.02.1",
    "3": "Delphi 7",
    "4": "Free Pascal 3.2.2",
    "51": "PascalABC.NET 3.8.3",
    "13": "Perl 5.20.1",
    "6": "PHP 8.1.7",
    "7": "Python 2.7.18",
    "31": "Python 3.13.2",
    "40": "PyPy 2.7.13 (7.3.0)",
    "41": "PyPy 3.6.9 (7.3.0)",
    "70": "PyPy 3.10 (7.3.15, 64bit)",
    "67": "Ruby 3.2.2",
    "75": "Rust 1.89.0 (2021)",
    "98": "Rust 1.89.0 (2024)",
    "20": "Scala 2.12.8",
    "34": "JavaScript V8 4.8.0",
    "55": "Node.js 15.8.0 (64bit)",
}

# Codeforces spells one language three ways: the submit menu ("GNU G++17
# 7.3.0"), the /my table and the API ("C++17 (GCC 7-32)"), and older names
# ("GNU C++17"). Rules are tried in order on the start of a name, so the more
# specific ones come first: Pascal before ".NET" C#, JavaScript before Java,
# C# and C++ before plain C.
_EXT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), ext)
    for p, ext in [
        (r"PascalABC|Delphi|FPC|Free Pascal", "pas"),
        (r"JavaScript|Node\.js|V8", "js"),
        (r"Java\b", "java"),
        (r"Kotlin", "kt"),
        (r"(Mono |MS )?C#", "cs"),
        (r"F#", "fs"),
        (r"(Microsoft )?Q#", "qs"),
        (r".*(C\+\+|G\+\+)", "cpp"),  # GNU G++17, C++20 (GCC 13-64), Clang++17, MS C++
        (r"(GNU )?(GCC )?C\d*\b", "c"),  # GNU C11, GNU GCC C11 5.1.0, C11 (GCC ...)
        (r"Python|PyPy", "py"),
        (r"Rust", "rs"),
        (r"Go\b", "go"),
        (r"Haskell", "hs"),
        (r"OCaml", "ml"),
        (r"Scala", "scala"),
        (r"D\b", "d"),
        (r"Perl", "pl"),
        (r"PHP", "php"),
        (r"Ruby", "rb"),
        (r"(Active)?Tcl", "tcl"),
        (r"Befunge", "bf"),
        (r"Pike", "pike"),
        (r"Io\b", "io"),
        (r"Factor", "factor"),
        (r"(Open)?Cobol", "cbl"),
        (r"Ada\b", "adb"),
        (r"FALSE\b", "f"),
        (r"Secret", "secret_171"),
    ]
]

# family display names by file extension; unknown names are "Other" (txt)
FAMILY_NAMES = {
    "cpp": "C++",
    "c": "C",
    "py": "Python",
    "java": "Java",
    "kt": "Kotlin",
    "rs": "Rust",
    "go": "Go",
    "cs": "C#",
    "fs": "F#",
    "qs": "Q#",
    "js": "JavaScript",
    "pas": "Pascal",
    "hs": "Haskell",
    "ml": "OCaml",
    "scala": "Scala",
    "d": "D",
    "pl": "Perl",
    "php": "PHP",
    "rb": "Ruby",
    "tcl": "Tcl",
    "bf": "Befunge",
    "pike": "Pike",
    "io": "Io",
    "factor": "Factor",
    "cbl": "COBOL",
    "adb": "Ada",
    "f": "FALSE",
    "secret_171": "Secret",
}


def ext_of(lang_name: str) -> str:
    """Source file extension for a Codeforces language name; "txt" when unknown."""
    name = lang_name.strip()
    for pattern, ext in _EXT_RULES:
        if pattern.match(name):
            return ext
    return "txt"


def family_name(ext: str) -> str:
    """Display name of the language family with this extension ("C++")."""
    return FAMILY_NAMES.get(ext, "Other")


def newest_first_key(name: str) -> tuple:
    """Sort key putting the highest version numbers in a name first."""
    return tuple(-int(n) for n in re.findall(r"\d+", name)), name


def by_family(languages: Mapping[str, str]) -> dict[str, list[tuple[str, str]]]:
    """(id, name) languages grouped by file extension, each group newest first."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for lid, name in languages.items():
        groups.setdefault(ext_of(name), []).append((lid, name))
    return {
        ext: sorted(group, key=lambda item: newest_first_key(item[1]))
        for ext, group in groups.items()
    }


def known_languages() -> dict[str, str]:
    """Codeforces' languages, id -> name: the list last read from the submit
    form, else the built-in table."""
    try:
        saved = json.loads((paths.STATE_DIR / "languages.json").read_text(encoding="utf-8"))
        languages = saved["languages"]
        if isinstance(languages, dict) and languages:
            return {str(k): str(v) for k, v in languages.items()}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(LANGS)


def remember_languages(languages: Mapping[str, str]) -> None:
    """Keep the submit form's list for later runs (setup without logging in)."""
    if languages:
        data = {"fetched": time.time(), "languages": dict(languages)}
        paths.write_atomic(paths.STATE_DIR / "languages.json", json.dumps(data, indent=1) + "\n")


# ┌──────────────────────────────────────────────────────────┐
# │                Compilers and interpreters                │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Tool:
    """A compiler or interpreter found here."""

    program: str  # the command: "g++-14"
    label: str  # shown to the user: "GCC 14 (g++-14)"
    banner: str = ""  # the first line of its version text
    kind: str = ""  # "gcc", "clang", "apple clang", "python", "pypy", ...
    version: tuple[int, ...] = ()  # (14, 2, 0); () when unknown


def _version_text(where: str, flag: str) -> str:
    """First line of what `where flag` prints; "" when it won't run."""
    if sys.platform == "darwin" and Path(where).parent == Path("/usr/bin"):
        name = Path(where).name
        # NOTE: Apple's placeholder commands open an installer dialog
        # \     instead of running, unless their tools are installed
        if name in _XCODE_STUBS and not _succeeds(["xcode-select", "-p"]):
            return ""
        if name in _JAVA_STUBS and not _succeeds(["/usr/libexec/java_home"]):
            return ""
    try:
        done = subprocess.run([where, flag], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (done.stdout or done.stderr).strip()  # NOTE: java and kotlinc print to stderr
    return text.splitlines()[0] if done.returncode == 0 and text else ""


_XCODE_STUBS = {"cc", "c++", "gcc", "g++", "clang", "clang++", "python3"}
_JAVA_STUBS = {"java", "javac"}


def _succeeds(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_banners: dict[str, str] | None = None  # what tools said, kept in STATE_DIR/tools.json


def _tool_cache() -> dict[str, str]:
    global _banners
    if _banners is None:
        try:
            loaded = json.loads((paths.STATE_DIR / "tools.json").read_text(encoding="utf-8"))
            _banners = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            _banners = {}
    return _banners


def _remember(key: str, value: str) -> None:
    cache = _tool_cache()
    cache[key] = value
    try:
        paths.write_atomic(paths.STATE_DIR / "tools.json", json.dumps(cache, indent=1) + "\n")
    except OSError:
        pass


def _cached_version(program: str, flag: str) -> str:
    """_version_text of the program on PATH, remembered across runs while the
    program file stays the same (macOS's /usr/bin stand-ins are always asked)."""
    where = shutil.which(program)
    if where is None:
        return ""
    try:
        stat = os.stat(where)
    except OSError:
        return ""
    if sys.platform == "darwin" and Path(where).parent == Path("/usr/bin"):
        return _version_text(where, flag)  # NOTE: they forward to whichever tools are selected
    key = f"{where}|{flag}|{stat.st_mtime_ns}|{stat.st_size}"
    cache = _tool_cache()
    if key in cache:
        return cache[key]
    banner = _version_text(where, flag)
    if banner:  # NOTE: a failure isn't remembered: the tool may be installed later
        _remember(key, banner)
    return banner


def _accepts_std(program: str, std: str) -> bool:
    """Whether the C++ compiler program takes -std=std; asked once per
    compiler version (by compiling nothing with it)."""
    where = shutil.which(program)
    banner = _cached_version(program, "--version") if where else ""
    if not where or not banner:
        return False
    key = f"std|{banner}|{std}"
    cache = _tool_cache()
    if key in cache:
        return cache[key] == "yes"
    try:
        done = subprocess.run(
            [where, f"-std={std}", "-x", "c++", "-fsyntax-only", "-"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    _remember(key, "yes" if done.returncode == 0 else "no")
    return done.returncode == 0


@dataclass
class Machine:
    """What detection looks at: commands on PATH, their version text, the OS,
    and which -std a C++ compiler takes (None: judged by its version)."""

    which: Callable[[str], "str | None"] = shutil.which
    version: Callable[[str, str], str] = _cached_version
    platform: str = sys.platform
    accepts: "Callable[[str, str], bool] | None" = _accepts_std


def _numbers(text: str) -> tuple[int, ...]:
    """The first dotted version number in text: (14, 2, 0); () when none."""
    match = re.search(r"\d+(?:\.\d+)+", text)
    return tuple(int(n) for n in match.group().split(".")) if match else ()


def _gcc_family(machine: Machine, names: list[str]) -> list[Tool]:
    """The GCC and clang compilers among names (C or C++):
    - GCC before clang (Codeforces judges with GCC)
    - one per compiler (macOS's g++ is clang++ again)"""
    found: list[Tool] = []
    seen: set[str] = set()
    for program in names:
        banner = machine.version(program, "--version") if machine.which(program) else ""
        if not banner or banner in seen:
            continue
        seen.add(banner)
        low = banner.lower()
        kind = "apple clang" if "apple" in low else "clang" if "clang" in low else "gcc"
        version = _numbers(banner)
        title = {"apple clang": "Apple clang", "clang": "Clang", "gcc": "GCC"}[kind]
        label = f"{title} {version[0] if version else '?'} ({program})"
        found.append(Tool(program, label, banner, kind, version))
    return sorted(found, key=lambda tool: tool.kind != "gcc")


def _detect_cpp(machine: Machine) -> list[Tool]:
    names = [f"g++-{v}" for v in range(16, 10, -1)] + ["clang++", "g++"]
    return _gcc_family(machine, names)


def _detect_c(machine: Machine) -> list[Tool]:
    names = [f"gcc-{v}" for v in range(16, 10, -1)] + ["clang", "gcc"]
    return _gcc_family(machine, names)


def _detect_python(machine: Machine) -> list[Tool]:
    found: list[Tool] = []
    seen: set[str] = set()
    for program in ("python3", "python", "py", "pypy3"):
        banner = machine.version(program, "--version") if machine.which(program) else ""
        match = re.match(r"Python (3\.\d+)", banner)
        if not match or banner in seen:  # NOTE: python may be Python 2, or python3 again
            continue
        seen.add(banner)
        kind = "pypy" if "pypy" in program else "python"
        label = f"{'PyPy' if kind == 'pypy' else 'Python'} {match.group(1)} ({program})"
        found.append(Tool(program, label, banner, kind, _numbers(banner)))
    return found


def _detect_java(machine: Machine) -> list[Tool]:
    banner = machine.version("java", "-version") if machine.which("java") else ""
    match = re.search(r'version "(\d+)(?:\.(\d+))?', banner)
    if not match:
        return []
    major = (
        int(match.group(2) or 0) if match.group(1) == "1" else int(match.group(1))
    )  # NOTE: "1.8.0" is Java 8
    if major < 11:
        return []  # NOTE: running a .java file directly, whatever its class, needs 11+
    kind = "jdk" if machine.which("javac") else "jre"
    return [Tool("java", f"Java {major} (java)", banner, kind, (major,))]


def _detect_kotlin(machine: Machine) -> list[Tool]:
    if not (machine.which("kotlinc") and machine.which("java")):
        return []
    banner = machine.version("kotlinc", "-version")
    match = re.search(r"kotlinc-jvm (\d+\.\d+)", banner)
    if not match:
        return []
    return [
        Tool("kotlinc", f"Kotlin {match.group(1)} (kotlinc)", banner, "kotlin", _numbers(banner))
    ]


def _detect_rust(machine: Machine) -> list[Tool]:
    banner = machine.version("rustc", "--version") if machine.which("rustc") else ""
    match = re.search(r"rustc (\d+\.\d+)", banner)
    if not match:
        return []
    return [Tool("rustc", f"Rust {match.group(1)} (rustc)", banner, "rust", _numbers(banner))]


def _detect_go(machine: Machine) -> list[Tool]:
    banner = machine.version("go", "version") if machine.which("go") else ""
    match = re.search(r"go(\d+\.\d+)", banner)
    if not match:
        return []
    return [Tool("go", f"Go {match.group(1)} (go)", banner, "go", _numbers(match.group(1)))]


# ┌──────────────────────────────────────────────────────────┐
# │                  Build and run commands                  │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Context:
    """What a language's commands depend on besides the tool."""

    platform: str
    submit_name: str = ""  # the Codeforces language it is submitted as ("" unknown)
    flags: tuple[str, ...] = ()  # the user's extra flags
    source: Path | None = None  # the code file, when there is one (Java's class name)
    accepts: "Callable[[str, str], bool] | None" = None  # see Machine.accepts


# (build command, or None when nothing is built; run command). Words may hold
# the placeholders {src} {exe} {dir} {name} {class} {copy}, filled in by build.py.
Commands = tuple["list[str] | None", "list[str]"]


def _stack_flags(platform: str) -> list[str]:
    """Linker flags giving a C/C++ program Codeforces' 256 MB stack (on Linux
    a process limit does it instead, see process.py)."""
    if platform == "darwin":
        return ["-Wl,-stack_size,0x10000000"]
    if platform == "win32":
        return ["-Wl,--stack,268435456"]
    return []


# each C++ standard's spellings for -std, the current one first
_STD_SPELLINGS = {
    26: ("c++26", "c++2c"),
    23: ("c++23", "c++2b"),
    20: ("c++20", "c++2a"),
    17: ("c++17", "c++1z"),
    14: ("c++14", "c++1y"),
    11: ("c++11", "c++0x"),
}
# the first major version of each compiler that knows each spelling
_FIRST_KNOWN = {
    "gcc": {"c++23": 11, "c++2b": 11, "c++20": 10, "c++2a": 8, "c++17": 5, "c++1z": 5},
    "clang": {"c++23": 17, "c++2b": 12, "c++20": 10, "c++2a": 5, "c++17": 5, "c++1z": 3},
    "apple clang": {"c++23": 16, "c++2b": 13, "c++20": 12, "c++2a": 10, "c++17": 10, "c++1z": 6},
}


def cpp_standard(
    submit_name: str,
    tool: Tool | None = None,
    accepts: Callable[[str, str], bool] | None = None,
) -> str:
    """The -std value for C++ submitted as submit_name ("GNU G++20 13.2" ->
    c++20; unknown -> C++23): the newest spelling of that standard, or of an
    older one, that tool takes. In order:
    - asking the compiler (accepts), when it can be asked
    - by the compiler's version, when it is known
    - the standard's own name"""
    match = re.search(r"\+\+\s*(\d{2})\b", submit_name)
    year = int(match.group(1)) if match else 23
    year = max((y for y in _STD_SPELLINGS if y <= year), default=11)
    spellings = [
        s for y in sorted(_STD_SPELLINGS, reverse=True) if y <= year for s in _STD_SPELLINGS[y]
    ]
    if tool is not None and accepts is not None:
        for spelling in spellings:
            if accepts(tool.program, spelling):
                return spelling
    first = _FIRST_KNOWN.get(tool.kind, {}) if tool is not None and tool.version else {}
    if first:
        major = tool.version[0]  # type: ignore[union-attr]
        for spelling in spellings:
            if spelling in first and major >= first[spelling]:
                return spelling
    return spellings[0]


def _cpp_commands(tool: Tool, ctx: Context) -> Commands:
    build = [
        tool.program,
        f"-std={cpp_standard(ctx.submit_name, tool, ctx.accepts)}",
        "-O2",
        "-Wall",
    ]
    build += _stack_flags(ctx.platform)
    if "clang" in tool.kind:
        build.append(f"-I{shim_folder()}")  # NOTE: clang's own library has no bits/stdc++.h
    build += [*ctx.flags, "{src}", "-o", "{exe}"]
    return build, ["{exe}"]


def _c_commands(tool: Tool, ctx: Context) -> Commands:
    match = re.search(r"\bC(\d{2})\b", ctx.submit_name)
    build = [tool.program, f"-std=c{match.group(1) if match else '11'}", "-O2", "-Wall"]
    build += _stack_flags(ctx.platform)
    build += [*ctx.flags, "{src}", "-o", "{exe}", "-lm"]
    return build, ["{exe}"]


def _python_commands(tool: Tool, ctx: Context) -> Commands:
    return None, [tool.program, *ctx.flags, "{src}"]


_JAVA_CLASS_RE = re.compile(r"\bpublic\s+(?:final\s+|abstract\s+)*class\s+(\w+)")


def java_main_class(source: Path) -> str | None:
    """The public class of a Java file; None when it has none (or is unreadable)."""
    try:
        match = _JAVA_CLASS_RE.search(source.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return match.group(1) if match else None


def _java_commands(tool: Tool, ctx: Context) -> Commands:
    """javac into the build folder, then java with the public class; without
    javac, or no public class to name, java runs the file itself."""
    main_class = java_main_class(ctx.source) if ctx.source is not None else None
    if tool.kind != "jdk" or (ctx.source is not None and main_class is None):
        return None, ["java", *ctx.flags, "{src}"]
    # NOTE: javac wants a public class in a file of its name (a.java holds Main):
    # \     it compiles a copy named for the class (see Setup.copy_as)
    build = ["javac", "-encoding", "UTF-8", *ctx.flags, "-d", "{dir}", "{copy}"]
    return build, ["java", "-cp", "{dir}", main_class or "{class}"]


def _kotlin_commands(tool: Tool, ctx: Context) -> Commands:
    build = [tool.program, "{src}", "-include-runtime", *ctx.flags, "-d", "{dir}/{name}.jar"]
    return build, ["java", "-jar", "{dir}/{name}.jar"]


def _rust_commands(tool: Tool, ctx: Context) -> Commands:
    match = re.search(r"\((20\d\d)\)", ctx.submit_name)
    edition = match.group(1) if match else "2021"
    if edition == "2024" and tool.version and tool.version < (1, 85):
        edition = "2021"  # NOTE: rustc learned the 2024 edition in 1.85
    build = [tool.program, "--edition", edition, "-O", *ctx.flags, "-o", "{exe}", "{src}"]
    return build, ["{exe}"]


def _go_commands(tool: Tool, ctx: Context) -> Commands:
    return [tool.program, "build", *ctx.flags, "-o", "{exe}", "{src}"], ["{exe}"]


# ┌──────────────────────────────────────────────────────────┐
# │                      The languages                       │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Language:
    """A language cf-tool knows: how to find its tools, how they build and
    run a file, which Codeforces languages belong to it and which to prefer."""

    key: str  # "cpp": its file extension, and its table in config.toml
    name: str  # "C++"
    extensions: tuple[str, ...]  # ("cpp", "cc", "cxx")
    detect: Callable[[Machine], list[Tool]]
    commands: Callable[[Tool, Context], Commands]
    starter: str  # built-in starter code
    prefer: tuple[str, ...] = ()  # patterns over Codeforces language names, best first
    exclude: str = ""  # a pattern of Codeforces languages never to pick
    install: Mapping[str, str] = field(default_factory=dict)  # platform -> how to get a tool
    big_stack: bool = False  # runs with Codeforces' stack (see process.py)

    def install_hint(self, platform: str = sys.platform) -> str:
        """How to install this language's tools on platform."""
        return self.install.get(platform) or self.install["any"]


CPP_STARTER = """\
// {{name}}
// {{url}}
#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    return 0;
}
"""

C_STARTER = """\
// {{name}}
// {{url}}
#include <stdio.h>

int main(void) {
    return 0;
}
"""

PYTHON_STARTER = """\
# {{name}}
# {{url}}
import sys

input = sys.stdin.readline


def main():
    pass


main()
"""

JAVA_STARTER = """\
// {{name}}
// {{url}}
import java.io.*;
import java.util.*;

public class Main {
    public static void main(String[] args) throws IOException {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintWriter out = new PrintWriter(new BufferedWriter(new OutputStreamWriter(System.out)));

        out.flush();
    }
}
"""

KOTLIN_STARTER = """\
// {{name}}
// {{url}}
import java.io.*

fun main() {
    val input = BufferedReader(InputStreamReader(System.`in`))
    val out = PrintWriter(BufferedWriter(OutputStreamWriter(System.out)))

    out.flush()
}
"""

RUST_STARTER = """\
// {{name}}
// {{url}}
use std::io::{self, BufWriter, Read, Write};

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut tokens = input.split_ascii_whitespace();
    let mut out = BufWriter::new(io::stdout().lock());

    let _ = tokens.next();
    out.flush().unwrap();
}
"""

GO_STARTER = """\
// {{name}}
// {{url}}
package main

import (
\t"bufio"
\t"fmt"
\t"os"
)

func main() {
\tin := bufio.NewReader(os.Stdin)
\tout := bufio.NewWriter(os.Stdout)
\tdefer out.Flush()

\tvar n int
\tfmt.Fscan(in, &n)
}
"""

LANGUAGES: dict[str, Language] = {
    language.key: language
    for language in (
        Language(
            "cpp",
            "C++",
            ("cpp", "cc", "cxx"),
            _detect_cpp,
            _cpp_commands,
            CPP_STARTER,
            prefer=(r"G\+\+\d+.*64", r"G\+\+\d+"),
            exclude=r"Diagnostics|MS C\+\+|Microsoft|ZIP",
            install={
                "darwin": "brew install gcc",
                "win32": "install MSYS2 (msys2.org) and its mingw-w64 g++",
                "any": "install g++, e.g. sudo apt install g++",
            },
            big_stack=True,
        ),
        Language(
            "c",
            "C",
            ("c",),
            _detect_c,
            _c_commands,
            C_STARTER,
            prefer=(r"C\d+",),
            install={
                "darwin": "brew install gcc",
                "win32": "install MSYS2 (msys2.org) and its mingw-w64 gcc",
                "any": "install gcc, e.g. sudo apt install gcc",
            },
            big_stack=True,
        ),
        Language(
            "py",
            "Python",
            ("py",),
            _detect_python,
            _python_commands,
            PYTHON_STARTER,
            # NOTE: Codeforces itself recommends PyPy: the same code often runs many times faster
            prefer=(r"PyPy 3.*64", r"PyPy 3", r"Python 3"),
            exclude=r"^(Python|PyPy) 2",
            install={"darwin": "brew install python", "any": "install Python 3 from python.org"},
        ),
        Language(
            "java",
            "Java",
            ("java",),
            _detect_java,
            _java_commands,
            JAVA_STARTER,
            prefer=(r"Java \d+.*64", r"Java \d+"),
            install={
                "darwin": "brew install openjdk",
                "any": "install a JDK 17 or newer, e.g. from adoptium.net",
            },
        ),
        Language(
            "kt",
            "Kotlin",
            ("kt",),
            _detect_kotlin,
            _kotlin_commands,
            KOTLIN_STARTER,
            prefer=(r"Kotlin",),
            install={
                "darwin": "brew install kotlin",
                "any": "install kotlinc (kotlinlang.org) and a JDK",
            },
        ),
        Language(
            "rs",
            "Rust",
            ("rs",),
            _detect_rust,
            _rust_commands,
            RUST_STARTER,
            prefer=(r"Rust",),
            install={"any": "install Rust from rustup.rs"},
        ),
        Language(
            "go",
            "Go",
            ("go",),
            _detect_go,
            _go_commands,
            GO_STARTER,
            prefer=(r"Go \d",),
            install={"darwin": "brew install go", "any": "install Go from go.dev/dl"},
        ),
    )
}


def language_key(ext_or_path: str | Path, settings: "Settings | None" = None) -> str | None:
    """The language a file extension (or file) belongs to: a config.toml
    table named for exactly that extension, else the built-in language that
    has it; None when neither does."""
    name = Path(str(ext_or_path)).name.lower()
    if name.startswith(".") and name.count(".") == 1:
        ext = name[1:]  # NOTE: ".py", an extension on its own
    else:
        ext = Path(name).suffix[1:] if "." in name else name
    if not ext:
        return None
    if settings is not None and ext in settings.languages:
        return ext
    return next((key for key, lang in LANGUAGES.items() if ext in lang.extensions), None)


def code_extensions(settings: "Settings | None" = None) -> set[str]:
    """The file extensions of code cf-tool can build and run, with a dot."""
    found = {f".{ext}" for lang in LANGUAGES.values() for ext in lang.extensions}
    if settings is not None:
        found |= {f".{key}" for key in settings.languages}
    return found


def display_name(key: str) -> str:
    """ "C++" for cpp; a language from config.toml goes by its family name."""
    language = LANGUAGES.get(key)
    if language is not None:
        return language.name
    name = family_name(key)
    return name if name != "Other" else f".{key}"


# ┌──────────────────────────────────────────────────────────┐
# │                  The language to submit                  │
# └──────────────────────────────────────────────────────────┘


def family(key: str, offered: Mapping[str, str]) -> list[tuple[str, str]]:
    """The (id, name) Codeforces languages of a language's family, best first:
    - by the first of its preference patterns a name matches
    - then newest first, by the version numbers in the name"""
    language = LANGUAGES.get(key)
    prefer = language.prefer if language else ()
    exclude = language.exclude if language else ""
    members = [
        (lid, name)
        for lid, name in offered.items()
        if ext_of(name) == key and not (exclude and re.search(exclude, name))
    ]

    def rank(item: tuple[str, str]):
        name = item[1]
        tier = next((i for i, p in enumerate(prefer) if re.search(p, name)), len(prefer))
        return tier, *newest_first_key(name)

    return sorted(members, key=rank)


def _normal(text: str) -> str:
    """A language name for matching: no case, no spaces, C++ written G++."""
    return re.sub(r"\s+", "", text.lower()).replace("c++", "g++")


def choose_submit(key: str, spec: str, offered: Mapping[str, str]) -> tuple[str, str] | None:
    """The (id, name) to submit a language as, among offered:
    - spec empty: the best of its family
    - spec an id of its family (any id, for a language from config.toml)
    - otherwise: the best language of the family whose name contains spec
      ("G++20"; a number like 20 too), also among the ones never picked by
      themselves (Clang++20 Diagnostics)
    Never another family's language: None when nothing offered fits."""
    options = family(key, offered)
    if not spec:
        return options[0] if options else None
    custom = key not in LANGUAGES  # NOTE: from config.toml: its family is unknown
    if spec.isdigit() and spec in offered and (custom or ext_of(offered[spec]) == key):
        return spec, offered[spec]
    wanted = _normal(spec)
    matches = [item for item in options if wanted in _normal(item[1])]
    if not matches and not spec.isdigit():
        others = [
            item
            for item in offered.items()
            if (custom or ext_of(item[1]) == key) and wanted in _normal(item[1])
        ]
        matches = sorted(others, key=lambda item: newest_first_key(item[1]))
    return matches[0] if matches else None


# ┌──────────────────────────────────────────────────────────┐
# │                         Setting up                       │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Setup:
    """How a language is built, run and submitted here."""

    key: str  # "cpp"
    name: str  # "C++"
    tool: str  # what builds or runs it: "GCC 14 (g++-14)", or the command from config.toml
    build: tuple[str, ...] | None  # None: nothing to build
    run: tuple[str, ...]
    fingerprint: str = ""  # the tool's version text: part of the build cache key
    submit: tuple[str, str] | None = None  # the (id, name) it is submitted as, when known
    big_stack: bool = False  # run with Codeforces' stack
    copy_as: str = ""  # the name {copy} gives the code in the build folder ("": its own)


def setup(
    key: str,
    settings: "Settings",
    *,
    source: Path | None = None,
    offered: Mapping[str, str] | None = None,
    machine: Machine | None = None,
) -> Setup:
    """How to build and run a language here, and what to submit it as. Steps:
    - the Codeforces language: the setting `submit`, else the family's best
    - the tool: the setting `compiler`, else the best one found here
    - the commands made for that tool and language, unless `build`/`run` are set
    Raises CFError when no tool is found (with how to install one), or for an
    unknown language without a `run` setting."""
    machine = machine or Machine()
    language = LANGUAGES.get(key)
    conf = settings.language_settings(key)
    offered = offered if offered is not None else known_languages()
    submit = choose_submit(key, conf.submit, offered)
    submit_name = submit[1] if submit else ""
    build_words = list(conf.build) if conf.build is not None else None
    run_words = list(conf.run) if conf.run is not None else None

    if language is None:
        if not run_words:
            raise CFError(
                f"cf-tool doesn't know .{key} files: give [{key}] a run command in "
                f"{paths.config_file()}"
            )
        return Setup(
            key,
            display_name(key),
            " ".join(run_words),
            tuple(build_words) if build_words else None,
            tuple(run_words),
            fingerprint=" ".join(build_words or run_words),
            submit=submit,
        )

    if conf.compiler:
        tool = _configured_tool(language, conf.compiler, machine)
    else:
        tools = language.detect(machine)
        if not tools:
            raise CFError(
                f"No {language.name} compiler or interpreter found. To get one: "
                f"{language.install_hint(machine.platform)}"
            )
        tool = tools[0]
        if key == "py" and "pypy" in submit_name.lower():
            tool = next((t for t in tools if t.kind == "pypy"), tool)  # NOTE: test as judged
    ctx = Context(machine.platform, submit_name, conf.flags, source, machine.accepts)
    build, run = language.commands(tool, ctx)
    if "clang" in tool.kind and key == "cpp" and conf.build is None:
        write_shim()
    if conf.build is not None:
        build = build_words or None
    if run_words:
        run = run_words
    main_class = java_main_class(source) if key == "java" and source is not None else None
    return Setup(
        key,
        language.name,
        tool.label,
        tuple(build) if build else None,
        tuple(run),
        fingerprint=tool.banner or tool.program,
        submit=submit,
        big_stack=language.big_stack,
        copy_as=f"{main_class}.java" if main_class else "",
    )


def _configured_tool(language: Language, program: str, machine: Machine) -> Tool:
    """The tool named by `compiler` in config.toml, as detection would see it."""
    if not machine.which(program):
        raise CFError(
            f"{program}, the compiler set for [{language.key}] in {paths.config_file()}, "
            "is not installed"
        )
    flag = {"java": "-version", "kt": "-version", "go": "version"}.get(language.key, "--version")
    banner = machine.version(program, flag)
    low = banner.lower()
    if language.key in ("cpp", "c"):
        kind = "apple clang" if "apple" in low else "clang" if "clang" in low else "gcc"
    elif language.key == "py":
        kind = "pypy" if "pypy" in low or "pypy" in program else "python"
    elif language.key == "java":
        kind = "jdk" if machine.which("javac") else "jre"
    else:
        kind = language.key
    return Tool(program, program, banner, kind, _numbers(banner))


# ┌──────────────────────────────────────────────────────────┐
# │                       Starter code                       │
# └──────────────────────────────────────────────────────────┘


def starter(key: str, settings: "Settings", name: str = "template") -> tuple[str, str]:
    """The starter code for a new file of a language, and where it came from
    (a path, or "built-in"). In order:
    - templates/<name>.<ext> in the config folder, for a name other than
      "template" (cf new brute)
    - the setting `template`
    - templates/template.<ext>
    - the built-in starter (none for a language from config.toml: "")"""
    from cf_tool.workspace import read_source

    folder = paths.templates_dir()
    if name != "template":
        named = folder / f"{name}.{key}"
        if named.is_file():
            return read_source(named), str(named)
    conf = settings.language_settings(key)
    if conf.template:
        path = Path(conf.template).expanduser()
        if not path.is_file():
            raise CFError(
                f"The starter file for [{key}] in {paths.config_file()}, {path}, doesn't exist"
            )
        return read_source(path), str(path)
    default = folder / f"template.{key}"
    if default.is_file():
        return read_source(default), str(default)
    language = LANGUAGES.get(key)
    return (language.starter if language else ""), "built-in"


_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
# cf-tool 0.3's placeholders, still filled in
_OLD_PLACEHOLDERS = {
    "$%U%$": "handle",
    "$%Y%$": "year",
    "$%M%$": "month",
    "$%D%$": "day",
    "$%h%$": "hour",
    "$%m%$": "minute",
    "$%s%$": "second",
}
_EMPTY_COMMENT_RE = re.compile(r"\s*(//|#|--|;)?\s*")


def render(text: str, values: Mapping[str, str], now: datetime | None = None) -> str:
    """Starter code with its placeholders filled in: {{handle}} {{date}}
    {{time}} {{problem}} {{name}} {{url}}, and the old $%U%$ style. A comment
    line left empty (no problem to name, say) is dropped; an unknown
    placeholder stays as it is."""
    now = now or datetime.now()
    values = {
        "handle": "",
        "problem": "",
        "name": "",
        "url": "",
        "date": f"{now:%Y-%m-%d}",
        "time": f"{now:%H:%M}",
        "year": f"{now.year}",
        "month": f"{now.month:02d}",
        "day": f"{now.day:02d}",
        "hour": f"{now.hour:02d}",
        "minute": f"{now.minute:02d}",
        "second": f"{now.second:02d}",
        **values,
    }
    lines = []
    for line in text.splitlines(keepends=True):
        filled = _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), line)
        for placeholder, name in _OLD_PLACEHOLDERS.items():
            filled = filled.replace(placeholder, values.get(name, ""))
        if filled != line and _EMPTY_COMMENT_RE.fullmatch(filled.rstrip("\r\n")):
            continue  # NOTE: a line of placeholders with nothing to fill in
        lines.append(filled)
    return "".join(lines)


# ┌──────────────────────────────────────────────────────────┐
# │                bits/stdc++.h for clang                   │
# └──────────────────────────────────────────────────────────┘


def shim_folder() -> Path:
    """The include folder holding cf-tool's bits/stdc++.h for clang."""
    return paths.CACHE_DIR / "include"


def write_shim() -> Path:
    """Write (or refresh) cf-tool's bits/stdc++.h; returns the header."""
    header = shim_folder() / "bits" / "stdc++.h"
    try:
        current = header.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current != STDCXX_SHIM:
        paths.write_atomic(header, STDCXX_SHIM)
    return header


STDCXX_SHIM = """\
// bits/stdc++.h for compilers without one (clang, Apple clang): every
// standard header, so `#include <bits/stdc++.h>` works as on Codeforces.
// Written by cf-tool; changes here are overwritten.
#ifndef CF_TOOL_BITS_STDCXX_H
#define CF_TOOL_BITS_STDCXX_H

#include <cassert>
#include <cctype>
#include <cerrno>
#include <cfloat>
#include <cinttypes>
#include <climits>
#include <clocale>
#include <cmath>
#include <csetjmp>
#include <csignal>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <cwchar>
#include <cwctype>

#include <algorithm>
#include <array>
#include <atomic>
#include <bitset>
#include <chrono>
#include <complex>
#include <condition_variable>
#include <deque>
#include <exception>
#include <fstream>
#include <functional>
#include <initializer_list>
#include <iomanip>
#include <ios>
#include <iosfwd>
#include <iostream>
#include <istream>
#include <iterator>
#include <limits>
#include <list>
#include <locale>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <numeric>
#include <ostream>
#include <queue>
#include <random>
#include <ratio>
#include <regex>
#include <set>
#include <sstream>
#include <stack>
#include <stdexcept>
#include <streambuf>
#include <string>
#include <system_error>
#include <thread>
#include <tuple>
#include <type_traits>
#include <typeindex>
#include <typeinfo>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <valarray>
#include <vector>

#if __cplusplus >= 201703L
#include <any>
#include <charconv>
#include <optional>
#include <string_view>
#include <variant>
#endif

#if __cplusplus >= 202002L
#include <bit>
#include <compare>
#include <concepts>
#include <numbers>
#include <span>
#if __has_include(<ranges>)
#include <ranges>
#endif
#endif

#endif
"""
