"""Codeforces submission language IDs.

LANGS is a static fallback for display purposes; the authoritative list is
parsed live from the submit page's <select name="programTypeId"> when adding
a template (pages.parse_languages), since Codeforces retires IDs over time.
"""

from __future__ import annotations

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

# Display-name prefix -> source file extension (mirrors Go's LangsExt,
# prefix-matched so version suffixes don't matter).
_EXT_BY_PREFIX: list[tuple[str, str]] = [
    ("GNU GCC", "c"),
    ("GNU G++", "cpp"),
    ("Clang", "cpp"),
    ("MS C++", "cpp"),
    ("Microsoft Visual C++", "cpp"),
    ("Mono C#", "cs"),
    ("C#", "cs"),
    ("D ", "d"),
    ("Go ", "go"),
    ("Haskell", "hs"),
    ("Java", "java"),
    ("Kotlin", "kt"),
    ("OCaml", "ml"),
    ("Delphi", "pas"),
    ("Free Pascal", "pas"),
    ("FPC", "pas"),
    ("PascalABC", "pas"),
    ("Perl", "pl"),
    ("PHP", "php"),
    ("Python", "py"),
    ("PyPy", "py"),
    ("Ruby", "rb"),
    ("Rust", "rs"),
    ("Scala", "scala"),
    ("JavaScript", "js"),
    ("Node.js", "js"),
]


def name_of(lang_id: str, langs: dict[str, str] | None = None) -> str:
    table = langs or LANGS
    return table.get(lang_id, f"Unknown language (id {lang_id})")


def ext_of(lang_name: str) -> str:
    for prefix, ext in _EXT_BY_PREFIX:
        if lang_name.startswith(prefix):
            return ext
    return "txt"
