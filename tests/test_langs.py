"""Language name -> extension, against the names Codeforces really uses."""

import pytest

from cf_tool.langs import LANGS, ext_of, name_of

# programmingLanguage values seen in the API / the /my table (2026-10-12)
MY_TABLE_NAMES = {
    "C++23 (GCC 14-64, msys2)": "cpp",
    "C++20 (GCC 13-64)": "cpp",
    "C++17 (GCC 7-32)": "cpp",
    "GNU C11": "c",
    "PyPy 3-64": "py",
    "PyPy 3": "py",
    "Python 3": "py",
    "Java 21": "java",
    "Java 8": "java",
    "JavaScript": "js",
    "Node.js": "js",
    "Rust 2024": "rs",
    "C# 10": "cs",
    "C# 13": "cs",
    "Kotlin 1.9": "kt",
}

# names from the submit menu and from the Go tool's tables
OTHER_NAMES = {
    "GNU G++17 7.3.0": "cpp",
    "GNU G++23 14.2 (64 bit, msys2)": "cpp",
    "GNU C++17": "cpp",
    "GNU C++11 5 ZIP": "cpp",
    "Clang++17 Diagnostics": "cpp",
    "MS C++ 2017": "cpp",
    "Microsoft Visual C++ 2010": "cpp",
    "GNU GCC C11 5.1.0": "c",
    "C# Mono 5.18": "cs",
    "Mono C#": "cs",
    "C# 8, .NET Core 3.1": "cs",
    "PascalABC.NET 3.4.2": "pas",
    "Delphi 7": "pas",
    "Free Pascal 3.0.2": "pas",
    "FPC": "pas",
    "D DMD32 v2.086.0": "d",
    "Go 1.22.2": "go",
    "Haskell GHC 8.6.3": "hs",
    "OCaml 4.02.1": "ml",
    "Ocaml": "ml",
    "Scala 2.12.8": "scala",
    "Perl 5.20.1": "pl",
    "PHP 7.2.13": "php",
    "Ruby 2.0.0p645": "rb",
    "JavaScript V8 4.8.0": "js",
    "Java 1.8.0_162": "java",
    "Java 8 ZIP": "java",
    "Microsoft Q#": "qs",
    "ActiveTcl 8.5": "tcl",
    "Io-2008-01-07 (Win32)": "io",
    "OpenCobol 1.0": "cbl",
    "Ada GNAT 4": "adb",
    "Secret_171": "secret_171",
    "FALSE": "f",
}


@pytest.mark.parametrize("name,ext", [*MY_TABLE_NAMES.items(), *OTHER_NAMES.items()])
def test_ext_of(name, ext):
    assert ext_of(name) == ext


@pytest.mark.parametrize("name", ["", "Picat 0.9", "Roco", "Mysterious Language", "J"])
def test_unknown_is_txt(name):
    assert ext_of(name) == "txt"


def test_every_builtin_language_has_an_extension():
    assert all(ext_of(name) != "txt" for name in LANGS.values())


def test_name_of():
    assert name_of("89") == LANGS["89"]
    assert name_of("1", {"1": "X"}) == "X"
    assert "Unknown" in name_of("nope")
