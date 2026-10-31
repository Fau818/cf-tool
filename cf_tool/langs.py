"""Codeforces submission languages: id -> name, and name -> file extension.

LANGS is the fallback for when the live list can't be read (not logged in);
the authoritative one is parsed from the submit page's
<select name="programTypeId"> (pages.parse_languages), since Codeforces
retires and renumbers languages over time.
"""

from __future__ import annotations

import re

# NOTE: ids as Codeforces' submit form has them (checked against the cph
# \     extension's table, 2026-09); setup reads the live form when logged in
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


def family_name(ext: str) -> str:
    """Display name of the language family with this extension ("C++")."""
    return FAMILY_NAMES.get(ext, "Other")


def newest_first_key(name: str) -> tuple:
    """Sort key putting the highest version numbers in a name first."""
    return tuple(-int(n) for n in re.findall(r"\d+", name)), name


def by_family(languages: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """(id, name) languages grouped by file extension, each group newest first."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for lid, name in languages.items():
        groups.setdefault(ext_of(name), []).append((lid, name))
    return {
        ext: sorted(group, key=lambda item: newest_first_key(item[1]))
        for ext, group in groups.items()
    }


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
