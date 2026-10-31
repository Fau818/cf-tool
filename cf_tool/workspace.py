"""Problems on disk, and which problem and which file a command means.

A contest gets a folder named for its id, each problem one inside it:

    2050/
      a/
        a.cpp              your code (any name; several files are fine)
        tests/1.in 1.ans   tests: the samples, and your own (any name, .in with .ans)
        .cf-problem.json   what cf get learned: the url, limits, comparison rules

The metadata file names the problem, so a command run anywhere inside knows
which one it is. Folders made by cf-tool 0.3 (cf/contest/2050/a/, with
in1.txt and ans1.txt) and loose files named for a problem (2050A.cpp,
2050/A.cpp) work too: those are read off their names.

When several code files could be the one meant, the user picks from a menu,
this problem's files first (named for it, or inside its folders), the most
recently edited first in each group, each with its edit time:

  this problem's files   2050A.cpp  cf2050a.py  2050-A.cpp  2050A_v2.cpp
                         2050/A.cpp  anything in 2050/a/, 2050A/ or cf/contest/2050/a/
  ── other files ──      A.cpp (the problem's letter) first, then the rest
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Collection, Sequence

from rich.cells import cell_len

from cf_tool import languages, ui
from cf_tool.errors import CFError

METADATA = ".cf-problem.json"
TESTS = "tests"


# ┌──────────────────────────────────────────────────────────┐
# │                         Targets                          │
# └──────────────────────────────────────────────────────────┘

_PROBLEM = r"[A-Za-z]{1,2}\d?"  # A, C1, AA: a problem's index
_URL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/contest/(?P<contest>\d+)(?:/problem/(?P<problem>\w+))?"), "contest"),
    (re.compile(r"/gym/(?P<contest>\d+)(?:/problem/(?P<problem>\w+))?"), "gym"),
    (re.compile(r"/problemset/problem/(?P<contest>\d+)/(?P<problem>\w+)"), "contest"),
    (
        re.compile(
            r"/group/(?P<group>\w{10})(?:/contest/(?P<contest>\d+)(?:/problem/(?P<problem>\w+))?)?"
        ),
        "group",
    ),
    (
        re.compile(r"/problemsets/acmsguru/problem/(?P<contest>\d+)/(?P<problem>\w+)"),
        "acmsguru",
    ),
]
_SPEC_RULES = [
    re.compile(rf"(?:cf)?(?P<contest>\d+)[-_ ]?(?P<problem>{_PROBLEM})", re.IGNORECASE),
    re.compile(r"(?P<contest>\d+)"),
    re.compile(rf"(?P<problem>{_PROBLEM})"),
]
ACMSGURU_CONTEST = "99999"


@dataclass(frozen=True)
class Target:
    """A contest, or a problem of one, on Codeforces."""

    kind: str = "contest"  # contest, gym, group or acmsguru
    contest: str = ""  # "2050"; acmsguru's problems all sit in 99999
    problem: str = ""  # "A", "C1": upper case
    group: str = ""  # a group's id, for kind "group"

    @property
    def label(self) -> str:
        """How messages name it: 2050A, contest 2050, gym 100001 B, acmsguru 100."""
        if self.kind == "acmsguru":
            return f"acmsguru {self.problem}".strip()
        if self.contest and self.problem:
            prefix = "gym " if self.kind == "gym" else ""
            return f"{prefix}{self.contest}{self.problem}"
        if self.contest:
            return f"{'gym' if self.kind == 'gym' else 'contest'} {self.contest}"
        return f"problem {self.problem}" if self.problem else "nothing"

    def with_problem(self, problem: str) -> "Target":
        return replace(self, problem=problem.upper())

    def _base(self, host: str) -> str:
        if self.kind == "acmsguru":
            return f"{host}/problemsets/acmsguru"
        if not self.contest:
            raise CFError("Which contest? Give one, like 2050, or run this in a problem folder")
        if self.kind == "gym":
            return f"{host}/gym/{self.contest}"
        if self.kind == "group":
            return f"{host}/group/{self.group}/contest/{self.contest}"
        return f"{host}/contest/{self.contest}"

    def _need_problem(self) -> None:
        if not self.problem:
            raise CFError(
                f"Which problem of {self.label}? Give one, like {self.contest or '2050'}A, "
                "or run this in its folder"
            )

    def contest_url(self, host: str) -> str:
        return self._base(host)

    def problem_url(self, host: str) -> str:
        self._need_problem()
        if self.kind == "acmsguru":
            return f"{host}/problemsets/acmsguru/problem/{ACMSGURU_CONTEST}/{self.problem}"
        return f"{self._base(host)}/problem/{self.problem}"

    def problems_url(self, host: str) -> str:
        """The page with every problem's statement."""
        return f"{self._base(host)}/problems"

    def submit_url(self, host: str) -> str:
        return f"{self._base(host)}/submit"

    def my_url(self, host: str) -> str:
        """Your submissions to the contest."""
        if self.kind == "acmsguru":
            raise CFError("acmsguru has no list of your submissions")
        return f"{self._base(host)}/my"

    def standings_url(self, host: str) -> str:
        return f"{self._base(host)}/standings"

    def countdown_url(self, host: str) -> str:
        return f"{self._base(host)}/countdown"

    def submission_url(self, host: str, submission_id: str) -> str:
        if self.kind == "acmsguru":
            return f"{host}/problemsets/acmsguru/submission/{ACMSGURU_CONTEST}/{submission_id}"
        return f"{self._base(host)}/submission/{submission_id}"

    def page_url(self, host: str) -> str:
        """The problem's page, or the contest's when there is no problem."""
        return self.problem_url(host) if self.problem else self.contest_url(host)


def _kind_for(contest: str) -> str:
    return "gym" if len(contest) >= 6 else "contest"  # NOTE: gym ids start at 100000


def read_spec(spec: str) -> dict[str, str] | None:
    """What one argument names: a URL, 2050A, 2050 or A; None when it names
    nothing (so it may be a file or a test)."""
    text = spec.strip()
    if "/" in text:
        found: dict[str, str] = {}
        for pattern, kind in _URL_RULES:
            match = pattern.search(text)
            if match:
                found = {k: v for k, v in match.groupdict().items() if v}
                found["kind"] = kind
        if found.get("kind") == "acmsguru":
            found["contest"] = ACMSGURU_CONTEST
        return found or None
    for pattern in _SPEC_RULES:
        match = pattern.fullmatch(text)
        if match:
            return {k: v for k, v in match.groupdict().items() if v}
    return None


def parse_target(specs: Sequence[str], base: Target | None = None) -> Target:
    """The target that arguments name, with base (what the folder implies)
    filling in what they leave out; a problem letter alone keeps base's
    contest. Raises CFError when two arguments disagree or one is not a
    contest or a problem."""
    found: dict[str, str] = {}
    for spec in specs:
        parsed = read_spec(spec)
        if parsed is None:
            raise CFError(f'"{spec}" is not a contest or a problem (like 2050, 2050A or a URL)')
        for key, value in parsed.items():
            if key == "problem":
                value = value.upper()
            if found.get(key, value) != value:
                raise CFError(f"{found[key]} and {value} name different {key}s")
            found[key] = value
    base = base or Target()
    if "contest" not in found and "group" not in found:
        if not found:
            return base
        # NOTE: a letter alone is a problem of the contest we're in
        return Target(base.kind, base.contest, found.get("problem", base.problem), base.group)
    contest = found.get("contest", "")
    kind = found.get("kind") or _kind_for(contest)
    # NOTE: naming a contest means that contest, not base's problem in it
    return Target(kind, contest, found.get("problem", ""), found.get("group", ""))


# ┌──────────────────────────────────────────────────────────┐
# │                     Problem folders                      │
# └──────────────────────────────────────────────────────────┘

# per sample: the test case of each input line and of each answer line
Cases = tuple[list[int], list[int]]


@dataclass
class ProblemInfo:
    """What cf get learned about a problem, kept in its folder."""

    name: str = ""  # "A. Two Friends"
    url: str = ""
    time_limit: float | None = None  # seconds
    memory_limit: int | None = None  # megabytes
    interactive: bool = False
    ignore_case: bool = False  # the statement accepts answers in any letter case
    epsilon: float | None = None  # the absolute or relative error it accepts
    any_answer: bool = False  # it accepts any right answer, the sample's being one
    cases: list[Cases | None] = field(default_factory=list)  # per sample: its lines' cases

    @property
    def target(self) -> Target | None:
        parsed = read_spec(self.url) if self.url else None
        return parse_target([self.url]) if parsed else None

    def sample_cases(self, test_name: str) -> Cases | None:
        """The cases of sample test_name, if the page marked them."""
        if not test_name.isdigit():
            return None
        index = int(test_name) - 1
        return self.cases[index] if 0 <= index < len(self.cases) else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def load_info(folder: Path) -> ProblemInfo | None:
    """The problem info saved in folder; None if there is none or it is unreadable."""
    try:
        data = json.loads((folder / METADATA).read_text(encoding="utf-8"))
        return ProblemInfo(
            name=str(data.get("name", "")),
            url=str(data.get("url", "")),
            time_limit=_number(data.get("time_limit")),
            memory_limit=_number(data.get("memory_limit")),
            interactive=bool(data.get("interactive", False)),
            ignore_case=bool(data.get("ignore_case", False)),
            epsilon=_number(data.get("epsilon")),
            any_answer=bool(data.get("any_answer", False)),
            cases=[(list(c[0]), list(c[1])) if c else None for c in data.get("cases", [])],
        )
    except (OSError, ValueError, TypeError, IndexError, AttributeError):
        return None


def save_info(folder: Path, info: ProblemInfo) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / METADATA).write_text(json.dumps(asdict(info), indent=2) + "\n", encoding="utf-8")


def find_problem_folder(start: Path) -> Path | None:
    """The problem folder start is in (or is): the nearest one up the tree
    holding a .cf-problem.json."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / METADATA).is_file():
            return folder
    return None


def _problem_children(folder: Path) -> list[Path]:
    """The problem folders directly inside folder (a contest folder's problems)."""
    return [child for child in _subdirs(folder) if (child / METADATA).is_file()]


def contest_folder(cwd: Path) -> Path | None:
    """The contest folder cwd is in: the parent of its problem folder, or cwd
    itself when problem folders sit directly in it."""
    problem = find_problem_folder(cwd)
    if problem is not None:
        return problem.parent
    return cwd.resolve() if _problem_children(cwd) else None


def _from_names(folder: Path) -> Target | None:
    """The target a folder's own path spells out, as cf-tool 0.3 laid them
    out (cf/contest/2050/a, cf/gym/100001, cf/group/<id>/7/b, cf/acmsguru/100)
    or as people name them (2050/a, 2050/A, 2050A)."""
    parts = folder.resolve().parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "acmsguru" and i + 1 < len(parts):
            return Target("acmsguru", ACMSGURU_CONTEST, parts[i + 1].upper())
        if parts[i] == "group" and i + 2 < len(parts) and re.fullmatch(r"\w{10}", parts[i + 1]):
            problem = parts[i + 3].upper() if i + 3 < len(parts) else ""
            if re.fullmatch(r"\d+", parts[i + 2]):
                return Target("group", parts[i + 2], problem, parts[i + 1])
    name = folder.name
    parent = folder.parent.name
    if re.fullmatch(_PROBLEM, name) and re.fullmatch(r"\d+", parent):
        return Target(_kind_for(parent), parent, name.upper())
    if match := re.fullmatch(rf"(?:cf)?(\d+)[-_]?({_PROBLEM})", name, re.IGNORECASE):
        return Target(_kind_for(match.group(1)), match.group(1), match.group(2).upper())
    if re.fullmatch(r"\d+", name):
        return Target(_kind_for(name), name)
    return None


def here(cwd: Path) -> Target | None:
    """The target the folder implies, in order:
    - the problem folder it is in (its .cf-problem.json)
    - the contest folder it is (one of its problems' metadata, without the problem)
    - the names of its path (cf-tool 0.3's folders, 2050/a)
    None when nothing says."""
    problem = find_problem_folder(cwd)
    if problem is not None:
        info = load_info(problem)
        if info is not None and info.target is not None:
            return info.target
    for child in _problem_children(cwd):
        info = load_info(child)
        if info is not None and info.target is not None:
            return replace(info.target, problem="")
    return _from_names(cwd)


def contest_folder_name(target: Target) -> str:
    return "acmsguru" if target.kind == "acmsguru" else target.contest


def get_root(cwd: Path, root: Path | None = None) -> Path:
    """Where cf get puts a contest's folder:
    - next to the current contest folder, when run inside one
    - the configured root
    - the current folder"""
    current = contest_folder(cwd)
    if current is None:
        named = _from_names(cwd)  # NOTE: a folder made before metadata, with its tests
        if named is not None and named.problem and tests_of(cwd):
            current = cwd.resolve().parent
        elif named is not None and any(tests_of(child) for child in _subdirs(cwd)):
            current = cwd.resolve()
    if current is not None:
        return current.parent
    return root if root is not None else cwd.resolve()


def problem_folder(root: Path, target: Target) -> Path:
    """Where a problem's folder goes under root: <contest>/<problem, lower case>."""
    return root / contest_folder_name(target) / target.problem.lower()


def locate(target: Target, cwd: Path, root: Path | None = None) -> Path | None:
    """The folder of a problem, found from cwd:
    - the problem folder cwd is in, if it is this problem's
    - in the current contest folder, or in cwd
    - under the configured root
    - cf-tool 0.3's cf/<kind>/<contest>/<problem> above cwd
    None when it has no folder."""
    if not target.problem:
        return None
    current = find_problem_folder(cwd)
    if current is not None and _is(current, target):
        return current
    places = [contest_folder(cwd), cwd.resolve()]
    if root is not None:
        places.append(root / contest_folder_name(target))
    for place in places:
        if place is None:
            continue
        for candidate in (
            place / target.problem.lower(),
            place / target.problem,
            place / contest_folder_name(target) / target.problem.lower(),
        ):
            if candidate.is_dir() and _is(candidate, target):
                return candidate
    for folder in (cwd.resolve(), *cwd.resolve().parents):
        for root_folder in (folder / "cf", folder) if folder.name == "cf" else (folder / "cf",):
            legacy = root_folder / _old_layout(target)
            if legacy.is_dir():
                return legacy
    return None


def _old_layout(target: Target) -> Path:
    """A problem's folder below cf-tool 0.3's root folder (cf/)."""
    problem = target.problem.lower()
    if target.kind == "acmsguru":
        return Path("acmsguru", problem)
    if target.kind == "group":
        return Path("group", target.group, target.contest, problem)
    return Path(target.kind, target.contest, problem)


def _is(folder: Path, target: Target) -> bool:
    """Whether folder is target's problem folder: by its metadata, else by its names."""
    info = load_info(folder)
    found = info.target if info is not None else _from_names(folder)
    return (
        found is not None
        and found.problem == target.problem
        and (not target.contest or found.contest == target.contest)
    )


# ┌──────────────────────────────────────────────────────────┐
# │                          Tests                           │
# └──────────────────────────────────────────────────────────┘


@dataclass(frozen=True)
class Test:
    __test__ = False  # NOTE: not a test class, to pytest

    name: str  # "1", "my", "stress-17"
    input: Path
    answer: Path | None  # None: a test that is only run


def _test_order(name: str) -> tuple:
    return (0, int(name), "") if name.isdigit() else (1, 0, name)


_OLD_INPUT_RE = re.compile(r"^in(\d+)\.txt$")


def tests_of(folder: Path) -> list[Test]:
    """A problem folder's tests, numbered ones first in order, then the rest
    by name:
    - tests/<name>.in, with tests/<name>.ans (none: a test that is only run)
    - cf-tool 0.3's in<i>.txt with ans<i>.txt, unless tests/ has that number"""
    tests_folder = folder / TESTS
    found: dict[str, Test] = {}
    for entry in _entries(folder):
        match = _OLD_INPUT_RE.match(entry.name)
        if match and entry.is_file():
            answer = folder / f"ans{match.group(1)}.txt"
            found[match.group(1)] = Test(
                match.group(1), entry, answer if answer.is_file() else None
            )
    if tests_folder.is_dir():
        for entry in tests_folder.iterdir():
            if entry.suffix == ".in" and entry.is_file():
                answer = entry.with_suffix(".ans")
                found[entry.stem] = Test(entry.stem, entry, answer if answer.is_file() else None)
    return sorted(found.values(), key=lambda test: _test_order(test.name))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def save_samples(folder: Path, samples: Sequence[tuple[str, str]]) -> list[Test]:
    """Write the samples as tests/1.in, 1.ans, ...; returns them as tests."""
    written = []
    for i, (sample_in, sample_ans) in enumerate(samples, start=1):
        test = Test(str(i), folder / TESTS / f"{i}.in", folder / TESTS / f"{i}.ans")
        _write(test.input, sample_in)
        _write(test.answer, sample_ans)  # type: ignore[arg-type]
        written.append(test)
    return written


def add_test(folder: Path, input_text: str, answer: str, name: str = "") -> Test:
    """Save a test: under name, else the next free number; without an answer
    (empty) it is a test that is only run. Returns it."""
    if not name:
        numbers = [int(t.name) for t in tests_of(folder) if t.name.isdigit()]
        name = str(max(numbers, default=0) + 1)
    tests_folder = folder / TESTS
    test = Test(name, tests_folder / f"{name}.in", None)
    _write(test.input, input_text)
    answer_path = tests_folder / f"{name}.ans"
    if answer.strip():
        _write(answer_path, answer)
        test = replace(test, answer=answer_path)
    elif answer_path.exists():
        answer_path.unlink()
    return test


# ┌──────────────────────────────────────────────────────────┐
# │                        Code files                        │
# └──────────────────────────────────────────────────────────┘

_SEP = r"[\W_]*"  # what people put between the parts: 2050-A, cf_2050a
_TAIL = r"[\W_].*"  # a variant's tail after a separator: _brute, -v2, " copy"
_CONTEST_ANY = r"\d+"
_PROBLEM_ANY = r"[a-z]\d?"  # A, d, F1: problem indexes, when the target's is unknown
# helpers of a problem's folder, not solutions: never offered unless named
HELPERS = ("gen", "brute", "checker", "interactor")

RELATED, SAME_LETTER, UNRELATED = 2, 1, 0


@dataclass(frozen=True)
class CodeFile:
    """A candidate: its path relative to the cwd, its language, its rank for
    the target, and when it was last edited."""

    name: str
    language: str
    score: int = UNRELATED
    mtime: float = 0.0


class _Names:
    """Name patterns for one problem; an unknown contest or problem matches any."""

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
            in_problem  # 2050/a/main.cpp, 2050A/sol.cpp, cf/contest/2050/a/brute.cpp
            or self._named.fullmatch(stem)  # 2050A.cpp, cf2050a_v2.cpp
            # in the contest's folder: A.cpp, A-v2.cpp (A1.cpp is problem A1 there)
            or (self.is_contest(parent) and self._problem_named.fullmatch(stem))
        ):
            return RELATED
        if self.problem and self.is_problem(stem):
            return SAME_LETTER
        return UNRELATED

    def base(self, cwd: Path) -> Path | None:
        """The folder holding this problem's folders when cwd is one of them
        (2050/, 2050/a/, 2050A/), else None."""
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


# a helper is named for its kind (check and generator count too), then a digit,
# _ or - and anything, or nothing more: gen.py, gen2.py, brute_c.cpp, check_a.py
_HELPER_RE = re.compile(
    r"(generator|gen|brute|checker|check|interactor)(?:[\d_-].*)?", re.IGNORECASE
)


def helper_kind(name: str) -> str | None:
    """Which of a problem's helpers a file is (one of HELPERS), or None for
    other code: gen2.py -> gen, check_a.py -> checker, general.cpp -> None."""
    match = _HELPER_RE.fullmatch(Path(name).stem)
    if match is None:
        return None
    word = match.group(1).lower()
    return {"generator": "gen", "check": "checker"}.get(word, word)


def is_helper(name: str) -> bool:
    """Whether a file is one of a problem's helpers (gen.py, brute_c.cpp, ...)."""
    return helper_kind(name) is not None


def find_code(
    cwd: Path,
    settings,
    contest: str = "",
    problem: str = "",
    exclude: Collection[str] = (),
) -> list[CodeFile]:
    """Code files for the target problem, ranked best first: those in cwd,
    and with a known contest, those in its folders below cwd, and when cwd is
    one of these folders, the problem's files around it. Helpers (gen.*,
    brute.*, ...) and the files in exclude are left out."""
    cwd = cwd.resolve()
    skip = {(cwd / name).resolve() for name in exclude}  # NOTE: relative to cwd, or absolute
    extensions = languages.code_extensions(settings)
    names = _Names(contest, problem)
    folders = [cwd]
    around: list[Path] = []  # of these folders' files, only this problem's count
    if contest:
        folders += names.folders(cwd)
        base = names.base(cwd)
        if base is not None:
            around = [
                folder
                for folder in [base, *names.folders(base)]
                if folder != cwd and cwd not in folder.parents  # NOTE: cwd and below: done
            ]
    found: dict[str, CodeFile] = {}
    for folder in folders + around:
        for entry in _entries(folder):
            if not (entry.suffix.lower() in extensions and entry.is_file()):
                continue
            if is_helper(entry.name):
                continue
            score = names.score(entry)
            if folder in around and score != RELATED:
                continue
            if entry.resolve() in skip:
                continue
            name = os.path.relpath(entry, cwd)  # NOTE: ../../2050A.cpp from 2050/a/
            key = languages.language_key(entry, settings)
            if key is None:
                continue
            found[name] = CodeFile(name, key, score, entry.stat().st_mtime)
    return sorted(found.values(), key=lambda f: (-f.score, -f.mtime, f.name))


def pick_code(
    filename: str | None,
    cwd: Path,
    settings,
    *,
    contest: str = "",
    problem: str = "",
    action: str = "submit",
    exclude: Collection[str] = (),
) -> tuple[str, str]:
    """Exactly one (code file, language): the file named, the only candidate,
    or the user's pick among the candidates (the best pre-selected)."""
    if filename:
        key = languages.language_key(filename, settings)
        if key is None:
            raise CFError(
                f"cf-tool doesn't know what language {filename} is in: give its "
                f"extension a table with build and run commands in {settings.file}"
            )
        return filename, key
    files = find_code(cwd, settings, contest, problem, exclude)
    if not files:
        where = f" for {contest}{problem}" if contest and problem else ""
        raise CFError(f"No code file{where} here. cf new writes one from your starter code")
    chosen = _choose(files, action)
    return chosen.name, chosen.language


def _choose(files: list[CodeFile], action: str) -> CodeFile:
    """The file to use out of files (ranked best first): the only one, or
    the one the user picks, the best being pre-selected."""
    if len(files) == 1:
        return files[0]
    if not ui.interactive():  # NOTE: a menu nobody can answer would wait forever
        names = ", ".join(f.name for f in files[:4]) + (", ..." if len(files) > 4 else "")
        raise CFError(
            f"Several code files could be meant ({names}): name the one to {action}. "
            "Files named gen*, brute*, check* or interactor* (gen2.py, brute_c.cpp) "
            "are helpers, never in the way"
        )
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
    date = f"{_MONTHS[moment.month - 1]} {moment.day}"  # NOTE: not %b, which follows the locale
    return date if moment.year == today.year else f"{date} {moment.year}"


_NAMED_RE = re.compile(rf"(?:cf{_SEP})?(\d+){_SEP}({_PROBLEM_ANY})(?:{_TAIL})?", re.IGNORECASE)
_CONTEST_RE = re.compile(rf"(?:cf{_SEP})?(\d+)", re.IGNORECASE)
_PROBLEM_RE = re.compile(rf"({_PROBLEM_ANY})(?:{_TAIL})?", re.IGNORECASE)


def named_target(name: str, cwd: Path) -> tuple[str, str]:
    """(contest, problem) that a code file's name or folders spell out, ""
    for what they don't: 2050A.cpp, 2050/A.cpp, 2050/a/main.cpp -> ("2050",
    "A"); A.cpp -> ("", "A"); demo.cpp -> ("", "")."""
    path = Path(os.path.normpath(cwd / name))  # NOTE: ../A.cpp: the real folder's name
    stem, parent, grand = path.stem, path.parent.name, path.parent.parent.name
    for text in (stem, parent):
        if match := _NAMED_RE.fullmatch(text):
            return match.group(1), match.group(2).upper()
    for contest_text, problem_text in ((parent, stem), (grand, parent)):
        contest, problem = _CONTEST_RE.fullmatch(contest_text), _PROBLEM_RE.fullmatch(problem_text)
        if contest and problem:
            return contest.group(1), problem.group(1).upper()
    if match := _PROBLEM_RE.fullmatch(stem):
        return "", match.group(1).upper()
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
        text, encoding = data.decode("latin-1"), "Latin-1"  # NOTE: decodes any bytes
    ui.yellow(f"{filename} is not UTF-8; read it as {encoding}")
    return text
