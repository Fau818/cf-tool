"""Which code file a command means: discovery by template suffix, ranking
against the target problem, and reading the file.

Like the Go tool, a command takes the only code file there is, and asks
when there are several. The question lists them for the target problem,
say 546D, in two groups, each file with its last edit time:

  this problem's files   546D.cpp  cf546d.py  546-D.cpp  546D_brute.cpp
                         546/D.cpp  546/D-v2.cpp  (D.cpp when the cwd is 546/)
                         anything in 546/D/, 546D/ or cf/contest/546/d/
  ── other files ──      D.cpp (the problem's letter) first, then the rest:
                         2171A.cpp  demo.cpp

Within a group the most recently edited file comes first, so the default
answer is the file of this problem that was touched last. With a known
contest, its folders below the cwd (546/, 546/D/, 546D/) are searched too,
and when the cwd is one of them, this problem's files around it (546D.cpp
next to 546/, D.cpp in 546/): the same files from anywhere in the project.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.cells import cell_len

from cf_tool import langs, ui
from cf_tool.config import CodeTemplate
from cf_tool.errors import CFError

_SEP = r"[\W_]*"  # what people put between the parts: 546-D, cf_546d
_TAIL = r"[\W_].*"  # a variant's tail after a separator: _brute, -v2, " copy"
_CONTEST_ANY = r"\d+"
_PROBLEM_ANY = r"[a-z]\d?"  # A, d, F1: problem indexes, when the target's is unknown

RELATED, SAME_LETTER, UNRELATED = 2, 1, 0


@dataclass(frozen=True)
class CodeFile:
    """A candidate: path relative to the cwd, indexes of templates whose
    suffix matches it, its rank for the target, and its modification time."""

    name: str
    indexes: tuple[int, ...]
    score: int = UNRELATED
    mtime: float = 0.0


class _Target:
    """Name patterns for one problem; an unknown contest/problem matches any."""

    def __init__(self, contest: str, problem: str) -> None:
        self.contest, self.problem = contest, problem
        c = re.escape(contest) if contest else _CONTEST_ANY
        p = re.escape(problem) if problem else _PROBLEM_ANY
        flags = re.IGNORECASE
        self._contest = re.compile(rf"(?:cf{_SEP})?{c}", flags)
        self._problem = re.compile(p, flags)
        self._full = re.compile(rf"(?:cf{_SEP})?{c}{_SEP}{p}", flags)
        # file names, which may carry a variant's tail
        self._named = re.compile(rf"(?:cf{_SEP})?{c}{_SEP}{p}(?:{_TAIL})?", flags)
        self._problem_named = re.compile(rf"{p}(?:{_TAIL})?", flags)

    def is_contest(self, name: str) -> bool:
        return bool(self._contest.fullmatch(name))

    def is_problem(self, name: str) -> bool:
        return bool(self._problem.fullmatch(name))

    def is_full(self, name: str) -> bool:
        return bool(self._full.fullmatch(name))

    def score(self, path: Path) -> int:
        """How clearly the file at path (absolute) is this problem's code:
        RELATED, SAME_LETTER or UNRELATED."""
        stem, parent, grand = path.stem, path.parent.name, path.parent.parent.name
        in_problem = (self.is_problem(parent) and self.is_contest(grand)) or self.is_full(parent)
        if (
            in_problem  # 546/D/main.cpp, 546D/sol.cpp, cf/contest/546/d/brute.cpp
            or self._named.fullmatch(stem)  # 546D.cpp, cf546d_brute.cpp
            # in the contest's folder: D.cpp, D-v2.cpp (D1.cpp is problem D1 there)
            or (self.is_contest(parent) and self._problem_named.fullmatch(stem))
        ):
            return RELATED
        if self.problem and self.is_problem(stem):
            return SAME_LETTER
        return UNRELATED

    def base(self, cwd: Path) -> Path | None:
        """The folder holding this problem's folders when cwd is one of them
        (546/, 546/D/, 546D/), else None."""
        if self.is_contest(cwd.name) or self.is_full(cwd.name):
            return cwd.parent
        if self.is_problem(cwd.name) and self.is_contest(cwd.parent.name):
            return cwd.parent.parent
        return None

    def folders(self, cwd: Path) -> list[Path]:
        """Folders below cwd (two levels at most) where this problem's code may live."""
        contest_dirs = [d for d in _subdirs(cwd) if self.is_contest(d.name)]
        found = list(contest_dirs)
        if self.is_contest(cwd.name):  # the cwd itself is the contest's folder
            contest_dirs.append(cwd)
        if self.problem:
            for base in contest_dirs:
                found += [d for d in _subdirs(base) if self.is_problem(d.name)]
            found += [d for d in _subdirs(cwd) if self.is_full(d.name)]
        return found


def _entries(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir())
    except OSError:
        return []


def _subdirs(folder: Path) -> list[Path]:
    return [e for e in _entries(folder) if e.is_dir() and not e.name.startswith(".")]


def _suffix_map(templates: list[CodeTemplate]) -> dict[str, list[int]]:
    ext_map: dict[str, list[int]] = {}
    for i, template in enumerate(templates):
        for suffix in dict.fromkeys(template.suffix):
            ext_map.setdefault("." + suffix, []).append(i)
    return ext_map


def find(
    templates: list[CodeTemplate],
    cwd: Path,
    contest: str = "",
    problem: str = "",
    search_folders: bool = False,
) -> list[CodeFile]:
    """Code files in cwd, ranked best first for the target problem. With
    search_folders and a known contest, also those in its folders below cwd,
    and when cwd is one of these folders, the problem's files around it."""
    suffixes = _suffix_map(templates)
    target = _Target(contest, problem)
    folders = [cwd]
    around: list[Path] = []  # of these folders' files, only this problem's count
    if search_folders and contest:
        folders += target.folders(cwd)
        base = target.base(cwd)
        if base is not None:
            around = [
                folder
                for folder in [base, *target.folders(base)]
                if folder != cwd and cwd not in folder.parents  # cwd and below: done
            ]
    found: dict[str, CodeFile] = {}
    for folder in folders + around:
        for entry in _entries(folder):
            if not (entry.is_file() and entry.suffix in suffixes):
                continue
            score = target.score(entry)
            if folder in around and score != RELATED:
                continue
            name = os.path.relpath(entry, cwd)  # ../../546D.cpp from 546/D/
            found[name] = CodeFile(
                name, tuple(suffixes[entry.suffix]), score, entry.stat().st_mtime
            )
    return sorted(found.values(), key=lambda f: (-f.score, -f.mtime, f.name))


def pick(
    filename: str | None,
    templates: list[CodeTemplate],
    cwd: Path,
    *,
    contest: str = "",
    problem: str = "",
    search_folders: bool = False,
    action: str = "submit",
    langs_table: dict[str, str] | None = None,
) -> tuple[str, int]:
    """Resolve to exactly one (file name, template index): the explicit file,
    the only candidate, or the user's pick among the candidates."""
    if filename:
        suffixes = _suffix_map(templates)
        ext = os.path.splitext(filename)[1]
        if ext not in suffixes:
            raise CFError(
                f"{filename} can not match any template. "
                "You could add a new template by `cf config`"
            )
        chosen = CodeFile(filename, tuple(suffixes[ext]))
    else:
        files = find(templates, cwd, contest, problem, search_folders)
        if not files:
            raise CFError(
                "Cannot find any code.\nMaybe you should add a new template by `cf config`"
            )
        chosen = _choose(files, action)

    index = chosen.indexes[0]
    if len(chosen.indexes) > 1:
        index = ui.select(
            f"{chosen.name} matches several templates. Which language?",
            [
                (
                    f"{templates[idx].alias}  ({langs.name_of(templates[idx].lang, langs_table)})",
                    idx,
                )
                for idx in chosen.indexes
            ],
        )
    return chosen.name, index


def _choose(files: list[CodeFile], action: str) -> CodeFile:
    """The file to use out of files (ranked best first): the only one, or
    the one the user picks, the best being pre-selected."""
    if len(files) == 1:
        return files[0]
    width = max(cell_len(f.name) for f in files)
    now = time.time()
    choices: list[ui.Choice | ui.Heading] = []
    for i, f in enumerate(files):
        if i and f.score < RELATED <= files[i - 1].score:
            choices.append(ui.Heading("── other files ──"))
        # names padded by display width, so the times line up
        label = f.name + " " * (width - cell_len(f.name)) + "  " + edited(f.mtime, now)
        choices.append((label, f))
    return ui.select(
        f"Which file do you want to {action}?",
        choices,
        default=files[0],
        search=len(files) > ui.MAX_SHORTCUTS,
    )


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def edited(mtime: float, now: float) -> str:
    """When a file was last changed, as the file menu says it: today 18:09,
    yesterday 16:11, Mar 31, or Mar 31 2025 for another year."""
    moment, today = datetime.fromtimestamp(mtime), datetime.fromtimestamp(now).date()
    days = (today - moment.date()).days
    if days == 0:
        return f"today {moment:%H:%M}"
    if days == 1:
        return f"yesterday {moment:%H:%M}"
    date = f"{_MONTHS[moment.month - 1]} {moment.day}"  # not %b, which follows the locale
    return date if moment.year == today.year else f"{date} {moment.year}"


_NAMED_RE = re.compile(rf"(?:cf{_SEP})?(\d+){_SEP}({_PROBLEM_ANY})(?:{_TAIL})?", re.IGNORECASE)
_CONTEST_RE = re.compile(rf"(?:cf{_SEP})?(\d+)", re.IGNORECASE)
_PROBLEM_RE = re.compile(rf"({_PROBLEM_ANY})(?:{_TAIL})?", re.IGNORECASE)


def named_target(name: str, cwd: Path) -> tuple[str, str]:
    """(contest, problem) that a code file's name or folders spell out, ""
    for what they don't: 546D.cpp, 546/D.cpp, 546/D/main.cpp -> ("546", "D");
    D.cpp -> ("", "D"); demo.cpp -> ("", "")."""
    path = Path(os.path.normpath(cwd / name))  # ../D.cpp: the real folder's name
    stem, parent, grand = path.stem, path.parent.name, path.parent.parent.name
    for text in (stem, parent):
        if match := _NAMED_RE.fullmatch(text):
            return match.group(1), match.group(2)
    for contest_text, problem_text in ((parent, stem), (grand, parent)):
        contest, problem = _CONTEST_RE.fullmatch(contest_text), _PROBLEM_RE.fullmatch(problem_text)
        if contest and problem:
            return contest.group(1), problem.group(1)
    if match := _PROBLEM_RE.fullmatch(stem):
        return "", match.group(1)
    return "", ""


def read_source(filename: str | Path) -> str:
    """Text of a code file: UTF-8 (with or without BOM), else GB18030 — the
    usual non-UTF-8 encoding of sources written on Chinese Windows setups."""
    try:
        data = Path(filename).read_bytes()
    except OSError as e:
        raise CFError(f"Cannot read {filename}: {e.strerror or e}") from e
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text, encoding = data.decode("gb18030"), "GB18030"
    except UnicodeDecodeError:
        text, encoding = data.decode("latin-1"), "Latin-1"  # decodes any bytes
    ui.yellow(f"{filename} is not UTF-8; read it as {encoding}")
    return text
