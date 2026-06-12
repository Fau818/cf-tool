"""Specifier/path inference: maps command-line specifiers and the working
directory to (problem type, contest ID, group ID, problem ID, submission ID).

Port of cmd/args.go + client/info.go from xalanq/cf-tool. The regexes, the
precedence rules (explicit args win, path only fills blanks), the >=6-digit
contest-ID-means-gym heuristic, and the acmsguru 99999 rewrite are all kept
identical so directory layouts are interchangeable with the Go tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cf_tool.config import PROBLEM_TYPES, Config
from cf_tool.errors import CFError

PROBLEM_REG = r"\w+"
STRICT_PROBLEM_REG = r"[a-zA-Z]+\d*"
CONTEST_REG = r"\d+"
GROUP_REG = r"\w{10}"
SUBMISSION_REG = r"\d+"

# (pattern, problem type it implies, or ""). Evaluated in order, all of them;
# later matches overwrite earlier ones, except the bare type keywords (first
# four) which return immediately.
_ARG_SPECS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^contests?$", re.IGNORECASE), "contest"),
    (re.compile(r"^gyms?$", re.IGNORECASE), "gym"),
    (re.compile(r"^groups?$", re.IGNORECASE), "group"),
    (re.compile(r"^acmsguru$", re.IGNORECASE), "acmsguru"),
    (
        re.compile(
            rf"/contest/(?P<contestID>{CONTEST_REG})(/problem/(?P<problemID>{PROBLEM_REG}))?"
        ),
        "contest",
    ),
    (
        re.compile(rf"/gym/(?P<contestID>{CONTEST_REG})(/problem/(?P<problemID>{PROBLEM_REG}))?"),
        "gym",
    ),
    (
        re.compile(
            rf"/problemset/problem/(?P<contestID>{CONTEST_REG})/(?P<problemID>{PROBLEM_REG})"
        ),
        "contest",
    ),
    (
        re.compile(
            rf"/group/(?P<groupID>{GROUP_REG})"
            rf"(/contest/(?P<contestID>{CONTEST_REG})(/problem/(?P<problemID>{PROBLEM_REG}))?)?"
        ),
        "group",
    ),
    (
        re.compile(
            rf"/problemsets/acmsguru/problem/(?P<contestID>{CONTEST_REG})"
            rf"/(?P<problemID>{PROBLEM_REG})"
        ),
        "acmsguru",
    ),
    (
        re.compile(
            rf"/problemsets/acmsguru/submission/(?P<contestID>{CONTEST_REG})"
            rf"/(?P<submissionID>{SUBMISSION_REG})"
        ),
        "acmsguru",
    ),
    (re.compile(rf"/submission/(?P<submissionID>{SUBMISSION_REG})"), ""),
    (re.compile(rf"^(?P<contestID>{CONTEST_REG})(?P<problemID>{STRICT_PROBLEM_REG})$"), ""),
    (re.compile(rf"^(?P<contestID>{CONTEST_REG})$"), ""),
    (re.compile(rf"^(?P<problemID>{STRICT_PROBLEM_REG})$"), ""),
    (re.compile(rf"^(?P<groupID>{GROUP_REG})$"), ""),
]

ERROR_NEED_PROBLEM_ID = "You have to specify the Problem ID"
ERROR_NEED_CONTEST_ID = "You have to specify the Contest ID"
ERROR_NEED_GYM_ID = "You have to specify the Gym ID"
ERROR_NEED_GROUP_ID = "You have to specify the Group ID"
ERROR_NEED_SUBMISSION_ID = "You have to specify the Submission ID"


@dataclass
class Info:
    """Resolved target of a command, plus URL/path builders for it."""

    problem_type: str = ""  # contest | gym | group | acmsguru
    contest_id: str = ""
    group_id: str = ""
    problem_id: str = ""
    submission_id: str = ""
    # <root>/<folder_name[problem_type]>; problem dirs nest under this
    root_path: Path = field(default_factory=Path)

    def hint(self) -> str:
        text = self.problem_type.upper()
        if self.group_id:
            text += f" {self.group_id}"
        if self.problem_type != "acmsguru" and self.contest_id:
            sep = " " if self.problem_type != "group" else ", contest "
            text += f"{sep}{self.contest_id}"
        if self.problem_id:
            text += f", problem {self.problem_id}"
        if self.submission_id:
            text += f", submission {self.submission_id}"
        return text

    def path(self) -> Path:
        path = self.root_path
        if self.group_id:
            path = path / self.group_id
        if self.problem_type != "acmsguru" and self.contest_id:
            path = path / self.contest_id
        if self.problem_id:
            path = path / self.problem_id.lower()
        return path

    def _contest_error(self) -> CFError:
        if self.problem_type == "gym":
            return CFError(ERROR_NEED_GYM_ID)
        return CFError(ERROR_NEED_CONTEST_ID)

    def _contest_base_url(self, host: str) -> str:
        """host + /contest/<id> | /gym/<id> | /group/<g>/contest/<id>"""
        if not self.contest_id:
            raise self._contest_error()
        if self.problem_type == "gym":
            return f"{host}/gym/{self.contest_id}"
        if self.problem_type == "group":
            if not self.group_id:
                raise CFError(ERROR_NEED_GROUP_ID)
            return f"{host}/group/{self.group_id}/contest/{self.contest_id}"
        return f"{host}/contest/{self.contest_id}"

    def problem_set_url(self, host: str) -> str:
        if self.problem_type == "acmsguru":
            return f"{host}/problemsets/acmsguru"
        return self._contest_base_url(host)

    def problem_url(self, host: str) -> str:
        if not self.problem_id:
            raise CFError(ERROR_NEED_PROBLEM_ID)
        if self.problem_type == "acmsguru":
            if not self.contest_id:
                raise self._contest_error()
            return f"{host}/problemsets/acmsguru/problem/{self.contest_id}/{self.problem_id}"
        return f"{self._contest_base_url(host)}/problem/{self.problem_id}"

    def my_submission_url(self, host: str) -> str:
        if self.problem_type == "acmsguru":
            raise CFError("Not support acmsguru")
        return f"{self._contest_base_url(host)}/my"

    def submission_url(self, host: str) -> str:
        if not self.submission_id:
            raise CFError(ERROR_NEED_SUBMISSION_ID)
        if self.problem_type == "acmsguru":
            if not self.contest_id:
                raise self._contest_error()
            return f"{host}/problemsets/acmsguru/submission/{self.contest_id}/{self.submission_id}"
        return f"{self._contest_base_url(host)}/submission/{self.submission_id}"

    def standings_url(self, host: str) -> str:
        if self.problem_type == "acmsguru":
            return f"{host}/problemsets/acmsguru/standings"
        return f"{self._contest_base_url(host)}/standings"

    def submit_url(self, host: str) -> str:
        return f"{self.problem_set_url(host)}/submit"

    def open_url(self, host: str) -> str:
        if self.problem_type == "gym" and not self.contest_id:
            return f"{host}/gyms"
        if self.problem_type == "group":
            if not self.group_id:
                return f"{host}/groups"
            if not self.contest_id:
                return f"{host}/group/{self.group_id}"
        if self.problem_type == "acmsguru":
            if not self.problem_id:
                return f"{host}/problemsets/acmsguru/"
            return f"{host}/problemsets/acmsguru/problem/{self.contest_id}/{self.problem_id}"
        if not self.contest_id:
            return f"{host}/contests"
        if not self.problem_id:
            return self._contest_base_url(host)
        return self.problem_url(host)


def parse_arg(arg: str) -> dict[str, str]:
    """Classify one specifier (URL, '1136a', '1136', 'a', type keyword...)."""
    out: dict[str, str] = {}
    for k, (pattern, problem_type) in enumerate(_ARG_SPECS):
        match = pattern.search(arg)
        if not match:
            continue
        for name, value in match.groupdict().items():
            if value:
                out[name] = value
        if problem_type:
            out["problemType"] = problem_type
            if k < 4:  # bare type keyword: nothing else to extract
                return out
    return out


def parse_path(path: Path | str, cfg: Config) -> dict[str, str]:
    """Extract type/IDs from a directory path containing <root>/<type folder>/...

    Unlike the Go original, the root folder must sit at a path-component
    boundary (Go would also match e.g. "mycf/contest/...").
    """
    text = Path(path).as_posix() + "/"
    root = re.escape(cfg.folder_name["root"])
    out: dict[str, str] = {}
    id_regs = {
        "contest": rf"((?P<contestID>{CONTEST_REG})/((?P<problemID>{PROBLEM_REG})/)?)?",
        "gym": rf"((?P<contestID>{CONTEST_REG})/((?P<problemID>{PROBLEM_REG})/)?)?",
        "group": (
            rf"((?P<groupID>{GROUP_REG})/"
            rf"((?P<contestID>{CONTEST_REG})/((?P<problemID>{PROBLEM_REG})/)?)?)?"
        ),
        "acmsguru": rf"((?P<problemID>{PROBLEM_REG})/)?",
    }
    for problem_type in PROBLEM_TYPES:
        folder = re.escape(cfg.folder_name[problem_type])
        pattern = rf"(?:^|/){root}/{folder}/{id_regs[problem_type]}"
        match = re.search(pattern, text)
        if not match:
            continue
        for name, value in match.groupdict().items():
            if value:
                out[name] = value
        out["problemType"] = problem_type
    if (
        (out.get("problemType", "") not in ("", "group"))
        or out.get("groupID", "") == out.get("contestID", "")
        or out.get("groupID", "") == out.get("contestID", "") + out.get("problemID", "")
    ):
        out.pop("groupID", None)
    if out.get("groupID") and not out.get("problemType"):
        out["problemType"] = "group"
    return out


_FIELD_BY_GROUP = {
    "problemType": ("problem_type", "Problem Type"),
    "contestID": ("contest_id", "Contest ID"),
    "groupID": ("group_id", "Group ID"),
    "problemID": ("problem_id", "Problem ID"),
    "submissionID": ("submission_id", "Submission ID"),
}


def parse_args(specifiers: list[str], cwd: Path, cfg: Config) -> Info:
    """Resolve specifiers + working directory into an Info (port of parseArgs)."""
    info = Info()
    for arg in specifiers:
        parsed = parse_arg(arg)
        for group, (attr, label) in _FIELD_BY_GROUP.items():
            value = parsed.get(group)
            if not value:
                continue
            current = getattr(info, attr)
            if current and current != value:
                raise CFError(f"{label} conflicts: {current} {value}")
            setattr(info, attr, value)

    if not info.problem_type:
        parsed = parse_path(cwd, cfg)
        info.problem_type = parsed.get("problemType", "")
        for group, (attr, _) in _FIELD_BY_GROUP.items():
            if group != "problemType" and not getattr(info, attr) and parsed.get(group):
                setattr(info, attr, parsed[group])

    if info.problem_type in ("", "contest"):
        info.problem_type = "contest" if len(info.contest_id) < 6 else "gym"
    if info.problem_type == "acmsguru":
        if info.contest_id not in ("", "99999"):
            info.problem_id = info.contest_id
        info.contest_id = "99999"

    root = cfg.folder_name["root"]
    cwd = cwd.resolve()
    root_path = cwd / root  # no root folder among ancestors: create one under cwd
    path = cwd
    while True:
        if path.name == root:
            root_path = path
            break
        if path.parent == path:
            break
        path = path.parent
    info.root_path = root_path / cfg.folder_name[info.problem_type]
    return info
