"""Codeforces submission languages: id -> name, and name -> file extension.

LANGS is a static fallback for display purposes; the authoritative list is
parsed live from the submit page's <select name="programTypeId"> when adding
a template (pages.parse_languages), since Codeforces retires IDs over time.
"""

from __future__ import annotations

import re

LANGS: dict[str, str] = {
    "43": "GNU GCC C11 5.1.0",
    "54": "GNU G++17 7.3.0",
    "73": "GNU G++20 13.2 (64 bit, winlibs)",
    "89": "GNU G++23 14.2 (64 bit, msys2)",
    "31": "Python 3.8.10",
    "70": "PyPy 3.10 (7.3.15, 64bit)",
    "87": "Java 21 64bit",
    "74": "Java 8 32bit",
    "75": "Rust 2021 (1.75.0)",
    "32": "Go 1.22.2",
    "48": "Kotlin 1.9.21",
    "55": "Node.js 15.8.0 (64bit)",
    "67": "Ruby 3.2.2",
    "9": "C# 8, .NET Core 3.1",
}

# Codeforces spells one language three ways: the submit menu ("GNU G++17
# 7.3.0"), the /my table and API ("C++17 (GCC 7-32)"), and older names the
# Go tool knew ("GNU C++17"). Rules are tried in order on the start of the
# name, so the more specific ones come first: Pascal before ".NET" C#,
# JavaScript before Java, C# / C++ before plain C. Extensions follow the Go
# tool's LangsExt.
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


def name_of(lang_id: str, langs: dict[str, str] | None = None) -> str:
    """Display name of a language id, from langs (default: the static table)."""
    table = langs or LANGS
    return table.get(lang_id, f"Unknown language (id {lang_id})")


def ext_of(lang_name: str) -> str:
    """Source file extension for a language name; "txt" when unknown."""
    name = lang_name.strip()
    for pattern, ext in _EXT_RULES:
        if pattern.match(name):
            return ext
    return "txt"
