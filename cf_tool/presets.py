"""Language presets: what `cf config` fills in, so that setting up a language
takes no compile scripts and no compiler names.

A preset is a language family (C++, Python, ...). Setting one up:
- finds the compilers or interpreters on this machine, best first
- picks the newest Codeforces language of the family
- writes a starter template into the config folder
The result is an ordinary CodeTemplate: the config keeps the Go tool's schema.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from cf_tool import config, langs
from cf_tool.config import CodeTemplate


@dataclass(frozen=True)
class Toolchain:
    """One way to build and run a language here: scripts for a compiler or
    interpreter found on this machine."""

    label: str  # "GCC 14 (g++-14)", shown in the menu
    before_script: str
    script: str
    after_script: str
    needs_shim: bool = False  # clang's C++ library has no bits/stdc++.h


def _version(program: str, flag: str) -> str:
    """First line of program's version text; "" when it won't run."""
    where = shutil.which(program)
    if where is None:
        return ""
    if sys.platform == "darwin" and Path(where).parent == Path("/usr/bin"):
        # NOTE: Apple's placeholder commands open an installer dialog
        # \     instead of running, unless their tools are installed
        if program in _XCODE_STUBS and not _succeeds(["xcode-select", "-p"]):
            return ""
        if program in _JAVA_STUBS and not _succeeds(["/usr/libexec/java_home"]):
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


@dataclass
class Machine:
    """What detection looks at: commands on PATH, their version text, the OS."""

    which: Callable[[str], "str | None"] = shutil.which
    version: Callable[[str, str], str] = _version
    platform: str = sys.platform


# ┌──────────────────────────────────────────────────────────┐
# │                        Detection                         │
# └──────────────────────────────────────────────────────────┘


def _native(platform: str) -> tuple[str, str, str]:
    """(output file, run script, cleanup script) for a compiled program."""
    if platform == "win32":
        return "$%file%$.exe", "./$%file%$.exe", ""  # NOTE: cmd's `del` is no program
    return "$%file%$", "./$%file%$", "rm $%file%$"


def _quote(arg: str) -> str:
    """arg as one word of a script (scripts split at spaces outside quotes)."""
    return f'"{arg}"' if any(c.isspace() for c in arg) else arg


def _gcc_family(machine: Machine, names: list[str], std: str, extra: str) -> list[Toolchain]:
    """Toolchains for the GCC/clang compilers among names (C or C++):
    - GCC before clang (Codeforces judges with GCC)
    - one entry per compiler (macOS's g++ is clang++ again)"""
    found: list[Toolchain] = []
    seen: set[str] = set()
    for program in names:
        banner = machine.version(program, "--version") if machine.which(program) else ""
        if not banner or banner in seen:
            continue
        seen.add(banner)
        clang = "clang" in banner.lower()
        number = re.search(r"\d+(?:\.\d+)+", banner)
        major = number.group().split(".")[0] if number else "?"
        kind = "Apple clang" if "apple" in banner.lower() else "Clang" if clang else "GCC"
        target, run, cleanup = _native(machine.platform)
        flags = [std, "-O2", "-Wall"]
        if machine.platform == "darwin":
            flags.append("-Wl,-stack_size,0x10000000")  # NOTE: 256 MB like Codeforces, not 8
        needs_shim = clang and std.startswith("-std=c++")
        if needs_shim:
            flags.append(_quote(f"-I{shim_folder()}"))
        compile_ = f"{program} {' '.join(flags)} -o {target} $%full%${extra}"
        found.append(Toolchain(f"{kind} {major} ({program})", compile_, run, cleanup, needs_shim))
    return sorted(found, key=lambda t: "clang" in t.label.lower())


def _cpp(machine: Machine) -> list[Toolchain]:
    names = [f"g++-{v}" for v in range(16, 10, -1)] + ["clang++", "g++"]
    return _gcc_family(machine, names, "-std=c++20", "")


def _c(machine: Machine) -> list[Toolchain]:
    names = [f"gcc-{v}" for v in range(16, 10, -1)] + ["clang", "gcc"]
    return _gcc_family(machine, names, "-std=c11", " -lm")


def _python(machine: Machine) -> list[Toolchain]:
    found: list[Toolchain] = []
    seen: set[str] = set()
    for program in ("python3", "python", "py", "pypy3"):
        banner = machine.version(program, "--version") if machine.which(program) else ""
        match = re.match(r"Python (3\.\d+)", banner)
        if not match or banner in seen:  # NOTE: python may be Python 2, or python3 again
            continue
        seen.add(banner)
        kind = "PyPy" if "pypy" in program else "Python"
        found.append(
            Toolchain(f"{kind} {match.group(1)} ({program})", "", f"{program} $%full%$", "")
        )
    return found


def _java(machine: Machine) -> list[Toolchain]:
    banner = machine.version("java", "-version") if machine.which("java") else ""
    match = re.search(r'version "(\d+)(?:\.(\d+))?', banner)
    if not match:
        return []
    major = (
        int(match.group(2) or 0) if match.group(1) == "1" else int(match.group(1))
    )  # NOTE: "1.8.0" is Java 8
    if major < 11:
        return []  # NOTE: running a .java file directly, whatever its class is named, needs 11+
    return [Toolchain(f"Java {major} (java)", "", "java $%full%$", "")]


def _kotlin(machine: Machine) -> list[Toolchain]:
    if not (machine.which("kotlinc") and machine.which("java")):
        return []
    match = re.search(r"kotlinc-jvm (\d+\.\d+)", machine.version("kotlinc", "-version"))
    if not match:
        return []
    cleanup = "" if machine.platform == "win32" else "rm $%file%$.jar"
    return [
        Toolchain(
            f"Kotlin {match.group(1)} (kotlinc)",
            "kotlinc $%full%$ -include-runtime -d $%file%$.jar",
            "java -jar $%file%$.jar",
            cleanup,
        )
    ]


def _rust(machine: Machine) -> list[Toolchain]:
    match = (
        re.search(r"rustc (\d+\.\d+)", machine.version("rustc", "--version"))
        if (machine.which("rustc"))
        else None
    )
    if not match:
        return []
    target, run, cleanup = _native(machine.platform)
    compile_ = f"rustc --edition 2021 -O -o {target} $%full%$"
    return [Toolchain(f"Rust {match.group(1)} (rustc)", compile_, run, cleanup)]


def _go(machine: Machine) -> list[Toolchain]:
    match = (
        re.search(r"go(\d+\.\d+)", machine.version("go", "version"))
        if (machine.which("go"))
        else None
    )
    if not match:
        return []
    target, run, cleanup = _native(machine.platform)
    return [Toolchain(f"Go {match.group(1)} (go)", f"go build -o {target} $%full%$", run, cleanup)]


# ┌──────────────────────────────────────────────────────────┐
# │                         Presets                          │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Preset:
    """A language family: how to find its tools, which Codeforces languages
    belong to it (by file extension) and which of those to submit as."""

    name: str  # "C++"
    alias: str  # template alias, also the starter's file name
    suffix: tuple[str, ...]  # file extensions; the first names the starter
    starter: str  # starter template source, with $%U%$-style placeholders
    detect: Callable[[Machine], list[Toolchain]]
    prefer: tuple[str, ...]  # patterns over Codeforces language names, best first
    exclude: str = ""  # pattern of Codeforces languages never to pick
    install: dict[str, str] = field(default_factory=dict)  # platform -> how to get a compiler

    @property
    def ext(self) -> str:
        return self.suffix[0]

    def install_hint(self, platform: str) -> str:
        """How to install this language's tools on platform."""
        return self.install.get(platform) or self.install["any"]


CPP_STARTER = """\
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    return 0;
}
"""

PYTHON_STARTER = """\
# $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
import sys

input = sys.stdin.readline


def main():
    pass


if __name__ == "__main__":
    main()
"""

JAVA_STARTER = """\
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
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
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
import java.io.*

fun main() {
    val input = BufferedReader(InputStreamReader(System.`in`))
    val out = PrintWriter(BufferedWriter(OutputStreamWriter(System.out)))

    out.flush()
}
"""

RUST_STARTER = """\
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
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
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
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

C_STARTER = """\
// $%U%$  $%Y%$-$%M%$-$%D%$ $%h%$:$%m%$
#include <stdio.h>

int main(void) {
    return 0;
}
"""

PRESETS: tuple[Preset, ...] = (
    Preset(
        "C++",
        "cpp",
        ("cpp", "cc", "cxx"),
        CPP_STARTER,
        _cpp,
        prefer=(r"G\+\+\d+.*64", r"G\+\+\d+"),
        exclude=r"Diagnostics|MS C\+\+|Microsoft|ZIP",
        install={
            "darwin": "brew install gcc",
            "win32": "install MSYS2 (msys2.org) and its mingw-w64 g++",
            "any": "install g++, e.g. sudo apt install g++",
        },
    ),
    Preset(
        "Python",
        "py",
        ("py",),
        PYTHON_STARTER,
        _python,
        # NOTE: Codeforces itself recommends PyPy: the same code often runs many times faster
        prefer=(r"PyPy 3.*64", r"PyPy 3", r"Python 3"),
        exclude=r"^(Python|PyPy) 2",
        install={"darwin": "brew install python", "any": "install Python 3 from python.org"},
    ),
    Preset(
        "Java",
        "java",
        ("java",),
        JAVA_STARTER,
        _java,
        prefer=(r"Java \d+.*64", r"Java \d+"),
        install={
            "darwin": "brew install openjdk",
            "any": "install a JDK 17 or newer, e.g. from adoptium.net",
        },
    ),
    Preset(
        "Kotlin",
        "kt",
        ("kt",),
        KOTLIN_STARTER,
        _kotlin,
        prefer=(r"Kotlin",),
        install={
            "darwin": "brew install kotlin",
            "any": "install kotlinc (kotlinlang.org) and a JDK",
        },
    ),
    Preset(
        "Rust",
        "rs",
        ("rs",),
        RUST_STARTER,
        _rust,
        prefer=(r"Rust.*2021", r"Rust"),  # NOTE: the edition rustc compiles here
        install={"any": "install Rust from rustup.rs"},
    ),
    Preset(
        "Go",
        "go",
        ("go",),
        GO_STARTER,
        _go,
        prefer=(r"Go \d",),
        install={"darwin": "brew install go", "any": "install Go from go.dev/dl"},
    ),
    Preset(
        "C",
        "c",
        ("c",),
        C_STARTER,
        _c,
        prefer=(r"C\d+",),
        install={
            "darwin": "brew install gcc",
            "win32": "install MSYS2 (msys2.org) and its mingw-w64 gcc",
            "any": "install gcc, e.g. sudo apt install gcc",
        },
    ),
)


def find(alias_or_ext: str) -> Preset | None:
    """The preset with this alias or file extension ("cpp", "cc", "py")."""
    key = alias_or_ext.lower().lstrip(".")
    return next((p for p in PRESETS if key == p.alias or key in p.suffix), None)


# ┌──────────────────────────────────────────────────────────┐
# │                   Codeforces languages                   │
# └──────────────────────────────────────────────────────────┘


def family(preset: Preset, languages: dict[str, str]) -> list[tuple[str, str]]:
    """The (id, name) Codeforces languages of preset's family, best first:
    - by the first preference pattern a name matches
    - then newest first, by the version numbers in the name"""
    members = [
        (lid, name)
        for lid, name in languages.items()
        if langs.ext_of(name) == preset.ext
        and not (preset.exclude and re.search(preset.exclude, name))
    ]

    def rank(item: tuple[str, str]):
        name = item[1]
        tier = next(
            (i for i, p in enumerate(preset.prefer) if re.search(p, name)), len(preset.prefer)
        )
        return tier, *langs.newest_first_key(name)

    return sorted(members, key=rank)


def family_of(template: CodeTemplate, languages: dict[str, str]) -> Preset | None:
    """The preset template belongs to: by its suffixes, else by its language's name."""
    for suffix in template.suffix:
        if (preset := find(suffix)) is not None:
            return preset
    name = languages.get(template.lang) or langs.LANGS.get(template.lang, "")
    return find(langs.ext_of(name)) if name else None


# ┌──────────────────────────────────────────────────────────┐
# │                          Files                           │
# └──────────────────────────────────────────────────────────┘


def shim_folder() -> Path:
    """The include folder holding cf-tool's bits/stdc++.h for clang."""
    return config.CONFIG_DIR / "include"


def write_shim() -> Path:
    """Write (or refresh) cf-tool's bits/stdc++.h; returns the header."""
    header = shim_folder() / "bits" / "stdc++.h"
    if not header.is_file() or header.read_text(encoding="utf-8") != STDCXX_SHIM:
        config.write_atomic(header, STDCXX_SHIM)
    return header


def write_starter(preset: Preset) -> Path:
    """The preset's starter template in the config folder; written only if
    missing, since it is the user's to edit."""
    path = config.CONFIG_DIR / "templates" / f"template.{preset.ext}"
    if not path.exists():
        config.write_atomic(path, preset.starter)
    return path


def make_template(preset: Preset, toolchain: Toolchain, lang_id: str) -> CodeTemplate:
    """The template setting up preset with toolchain, submitting as lang_id;
    its starter file (and clang's header) are written as needed."""
    if toolchain.needs_shim:
        write_shim()
    return CodeTemplate(
        alias=preset.alias,
        lang=lang_id,
        path=str(write_starter(preset)),
        suffix=list(preset.suffix),
        before_script=toolchain.before_script,
        script=toolchain.script,
        after_script=toolchain.after_script,
    )


STDCXX_SHIM = """\
// bits/stdc++.h for compilers without one (clang, Apple clang): every
// standard header, so `#include <bits/stdc++.h>` works as on Codeforces.
// Written by cf-tool (cf config); changes here are overwritten.
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
