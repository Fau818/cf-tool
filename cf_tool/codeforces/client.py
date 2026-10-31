"""Codeforces operations: problems and their samples, contests, submitting and
watching verdicts, the code of your submissions, and the public API.

Getting in (HTTP, Cloudflare, logging in) is gateway.py's job, drawing
views.py's. Pages that anybody may read are fetched without logging in;
when one turns out to need a login (a group's contest), the saved login is
used.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from rich.live import Live
from rich.text import Text

from cf_tool import languages, paths, ui, views
from cf_tool.codeforces import pages
from cf_tool.codeforces.gateway import Gateway
from cf_tool.codeforces.http import Uncertain, is_cloudflare_cookie
from cf_tool.codeforces.session import LAST_KEYS, Session
from cf_tool.errors import CFError
from cf_tool.settings import Settings
from cf_tool.workspace import ProblemInfo, Target

CONTESTS_MAX_AGE = 1800  # seconds: the contest list rarely changes
PROBLEMSET_MAX_AGE = 86400  # seconds: new problems come with new contests
API_INTERVAL = 2.1  # seconds between API calls
POLL_INTERVAL = 1.0  # seconds between looks at the verdicts
TOO_MANY_REQUESTS_WAIT = 300  # seconds clone waits when Codeforces asks it to slow down


@dataclass
class FetchedProblem:
    """A problem as its page shows it."""

    index: str  # "A"
    info: ProblemInfo
    samples: list[tuple[str, str]] = field(default_factory=list)  # (input, answer)
    standard_io: bool = True
    error: str = ""  # why its samples couldn't be read; "" when they were


class Client:
    def __init__(self, settings: Settings, session: Session | None = None) -> None:
        self.settings = settings
        self.session = session if session is not None else Session.load()
        self.gw = Gateway(settings.host, settings.proxy, self.session)
        self._languages: tuple[dict[str, str], bool] | None = None
        self._last_api = float("-inf")  # time.monotonic() of the last API call

    @property
    def host(self) -> str:
        return self.settings.host

    @property
    def handle(self) -> str:
        return self.session.handle

    @property
    def can_log_in(self) -> bool:
        """Whether a login is saved (cf login was run)."""
        return bool(self.session.handle_or_email and self.session.password)

    # ┌──────────────────────────────────────────────────────────┐
    # │                         Account                          │
    # └──────────────────────────────────────────────────────────┘

    def login(self, handle_or_email: str, password: str) -> str:
        """Save the credentials (encrypted) and log in; returns the handle."""
        self._languages = None  # NOTE: once logged in, the live list can be read
        self.gw.set_credentials(handle_or_email, password)
        return self.gw.login()

    def logout(self) -> None:
        """Forget the login: credentials and cookies (Cloudflare's stay)."""
        self.gw.http.clear_cookies(keep=is_cloudflare_cookie)
        self.session.handle = self.session.handle_or_email = self.session.password = ""
        self.gw.save()

    def _get(self, url: str) -> str:
        """A page anybody may read; with the saved login when it needs one."""
        body = self.gw.get(url)
        if pages.find_handle(body) is None and self.can_log_in and pages.wants_login(body):
            body = self.gw.get_authed(url)
        return body

    # ┌──────────────────────────────────────────────────────────┐
    # │                         Problems                         │
    # └──────────────────────────────────────────────────────────┘

    def fetch(self, target: Target) -> list[FetchedProblem]:
        """The problems target names, with their samples:
        - a problem: its page
        - a contest: its all-problems page, one request for every problem
        - a contest without that page: its problem list, then each problem's page"""
        if target.problem:
            url = target.problem_url(self.host)
            return [_read_problem(target.problem, self._get(url), url)]
        body = self._get(target.problems_url(self.host))
        parts = pages.split_problems(body)
        if parts:
            return [
                _read_problem(index, part, target.with_problem(index).problem_url(self.host))
                for index, part in parts
            ]
        found = []
        for row in self.problem_rows(target):
            url = target.with_problem(row.id).problem_url(self.host)
            try:
                found.append(_read_problem(row.id, self._get(url), url))
            except CFError as e:
                found.append(
                    FetchedProblem(row.id, ProblemInfo(name=row.name, url=url), error=str(e))
                )
        return found

    def problem_rows(self, target: Target) -> list[pages.ProblemRow]:
        """A contest's problems with their solve counts (yours marked when logged in)."""
        if target.kind == "acmsguru":
            raise CFError("acmsguru has no contest page")
        url = target.contest_url(self.host)
        body = self.gw.get_authed(url) if self.can_log_in else self._get(url)
        return pages.parse_problems(body)

    def race(self, target: Target) -> None:
        """Count down to the contest's start (nothing to wait for once it began)."""
        if target.kind == "acmsguru":
            raise CFError("acmsguru has no contests to race")
        body = self._get(target.countdown_url(self.host))
        if "Go!</a>" in body or 'class="countdown"' not in body:
            return
        # NOTE: against a fixed deadline: sleeping 1 s per tick would drift late
        deadline = time.monotonic() + pages.find_countdown(body)
        with Live(console=ui.console, auto_refresh=False, transient=True) as live:
            while (remaining := deadline - time.monotonic()) > 0:
                h, rest = divmod(math.ceil(remaining), 3600)
                m, s = divmod(rest, 60)
                live.update(
                    Text.assemble(("Starts in ", "cyan"), (f"{h:02d}:{m:02d}:{s:02d}", "bold")),
                    refresh=True,
                )
                time.sleep(remaining - math.floor(remaining) or 1)  # NOTE: until the next tick
        time.sleep(0.9)

    # ┌──────────────────────────────────────────────────────────┐
    # │                        Submitting                        │
    # └──────────────────────────────────────────────────────────┘

    def submit(
        self,
        target: Target,
        source: str,
        choose_language: Callable[[dict[str, str]], tuple[str, str]],
        filename: str = "",
    ) -> pages.Submission:
        """Submit source, then watch its verdict; returns the judged submission.
        choose_language(offered) names the (id, name) to submit as, given the
        languages the form offers. The form is sent once: when its answer is
        lost, the submissions page tells whether it arrived."""
        if not target.problem:
            target._need_problem()
        url = target.submit_url(self.host)
        body = self.gw.get_authed(url)
        handle = pages.require_handle(body)
        offered = pages.parse_languages(body)
        if offered:
            languages.remember_languages(offered)
        lang_id, lang_name = choose_language(offered or languages.known_languages())
        shown = f" ({filename})" if filename else ""
        ui.line(
            ("Submitting ", "cyan"),
            (target.label, "bold"),
            (f"{shown} as {lang_name}, logged in as {handle}", "cyan"),
        )
        csrf = pages.find_csrf(body)
        ftaa, bfaa = self.gw.form_tokens()
        before = self._newest(target)  # NOTE: tells a lost answer's submission from older ones
        try:
            body = self.gw.post(
                f"{url}?csrf_token={csrf}",
                data={
                    "csrf_token": csrf,
                    "ftaa": ftaa,
                    "bfaa": bfaa,
                    "action": "submitSolutionFormSubmitted",
                    "submittedProblemIndex": target.problem,
                    "programTypeId": lang_id,
                    "contestId": target.contest,
                    "source": source,
                    "tabSize": "4",
                    "_tta": "594",
                    "sourceCodeConfirmed": "true",
                },
            )
        except Uncertain as e:
            ui.yellow(f"{e}: looking for the submission among yours...")
            if not self._arrived(target, before):
                raise CFError(
                    "The submission doesn't show up among yours: it didn't arrive. "
                    "Submit it again."
                ) from e
        else:
            error = pages.find_error_message(body)
            if error:
                raise CFError(error)
            message = pages.find_message(body)
            if message is None or "submitted successfully" not in message:
                raise CFError(message or "Codeforces did not take the submission")
        submission = self.watch(target, count=1, single=True)[0]
        self.session.handle = handle
        last = {"kind": target.kind, "contest": target.contest, "problem": target.problem}
        last.update(group=target.group, submission=str(submission.id))
        self.session.last_submission = {key: last.get(key, "") for key in LAST_KEYS}
        self.gw.save()
        return submission

    def _newest(self, target: Target) -> int:
        """The id of your newest submission to the contest; 0 when there is none."""
        try:
            return pages.parse_submissions(self.gw.get_authed(target.my_url(self.host)), 1)[0].id
        except CFError:
            return 0

    def _arrived(self, target: Target, before: int) -> bool:
        """Whether your newest submission to the contest came after the one
        numbered before, and is to target's problem."""
        try:
            newest = pages.parse_submissions(self.gw.get_authed(target.my_url(self.host)), 1)[0]
        except CFError:
            return False
        return newest.id > before and newest.problem_index() == target.problem.lower()

    def watch(
        self, target: Target, count: int = 10, problem: str = "", single: bool = False
    ) -> list[pages.Submission]:
        """Look at your submissions to the contest about once a second until
        every verdict is final; returns them. single shows the newest as a
        panel (after submitting), otherwise a table of the latest ones."""
        url = target.my_url(self.host)

        def render(submissions: list[pages.Submission]):
            if single:  # NOTE: unboxed for a pipe: CP Editor reads "status: ..." from it
                return views.submission_panel(submissions[0], boxed=ui.console.is_terminal)
            return views.submission_table(submissions, problem)

        # transient while judging; the final state is then printed in full
        # (a live display gets cut to the terminal height)
        with Live(console=ui.console, auto_refresh=False, transient=True) as live:
            while True:
                started = time.monotonic()
                submissions = pages.parse_submissions(self.gw.get_authed(url), count)
                if all(sub.end for sub in submissions):
                    break
                live.update(render(submissions), refresh=True)
                elapsed = time.monotonic() - started
                if elapsed < POLL_INTERVAL:
                    time.sleep(POLL_INTERVAL - elapsed)
        ui.console.print(render(submissions))
        return submissions

    # ┌──────────────────────────────────────────────────────────┐
    # │                   Code of submissions                    │
    # └──────────────────────────────────────────────────────────┘

    def _code(self, url: str) -> str:
        body = self.gw.get(url)
        message = pages.find_message(body)
        if message is not None:
            raise CFError(message)
        return pages.find_code(body)

    def pull(self, target: Target, folder_of: Callable[[str], Path], ac: bool) -> list[Path]:
        """Save the code of your submissions to target (a problem, or every
        problem of a contest) into folder_of(problem index), as
        <problem>_<submission id>.<ext>; returns the files written. ac:
        accepted ones only."""
        body = self.gw.get_authed(target.my_url(self.host))
        saved = []
        for sub in pages.parse_submissions(body):
            index = sub.problem_index()
            if target.problem and index != target.problem.lower():
                continue
            if ac and not ("Accepted" in sub.status or "Pretests passed" in sub.status):
                continue
            ext = languages.ext_of(sub.lang)
            if ext == "txt":
                continue
            path = folder_of(index.upper()) / f"{index}_{sub.id}.{ext}"
            if path.exists():
                continue
            try:
                code = self._code(target.submission_url(self.host, str(sub.id)))
            except CFError as e:
                ui.red(f"Submission {sub.id}: {e}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="utf-8", newline="")
            ui.green(f"Saved {path}")
            saved.append(path)
        return saved

    def clone(self, handle: str, folder: Path, ac: bool) -> int:
        """Save the code of every submission of handle into
        folder/<handle>/<contest>/<problem>/<id>[_<verdict>].<ext>, skipping
        files already there; returns how many were saved."""
        submissions = self.api(f"user.status?handle={handle}")
        total, saved = len(submissions), 0
        ui.cyan(f"{handle} has {total} submissions")
        for done, sub in enumerate(submissions, start=1):
            verdict = sub.get("verdict", "")
            if ac and verdict != "OK":
                continue
            ext = languages.ext_of(sub.get("programmingLanguage", ""))
            contest = str(sub.get("contestId", "acmsguru"))
            index = str(sub.get("problem", {}).get("index", "")).lower()
            name = str(sub["id"]) + ("" if verdict == "OK" else f"_{verdict.lower()}")
            path = folder / handle / contest / index / f"{name}.{ext}"
            if ext == "txt" or path.exists():
                continue
            kind = "gym" if len(contest) >= 6 else "contest"
            target = Target(kind, contest)
            if contest == "acmsguru":
                target = Target("acmsguru", "99999")
            while True:
                try:
                    code = self._code(target.submission_url(self.host, str(sub["id"])))
                    break
                except CFError as e:
                    if "too many requests" not in str(e).lower():
                        ui.red(f"{done}/{total} {sub['id']}: {e}")
                        code = None
                        break
                    ui.yellow(f"Codeforces asks to slow down: waiting {TOO_MANY_REQUESTS_WAIT}s")
                    time.sleep(TOO_MANY_REQUESTS_WAIT)
            if code is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="utf-8", newline="")
            saved += 1
            ui.green(f"{done}/{total} Saved {path}")
        return saved

    # ┌──────────────────────────────────────────────────────────┐
    # │                        Public API                        │
    # └──────────────────────────────────────────────────────────┘

    def api(self, method: str):
        """The result of a public API call ("contest.list?gym=false")."""
        wait = self._last_api + API_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)  # NOTE: the API allows one call every 2 seconds
        try:
            data = self.gw.get_json(f"{self.host}/api/{method}")
        finally:
            self._last_api = time.monotonic()
        if data.get("status") != "OK":
            raise CFError(f"Codeforces API: {data.get('comment') or 'the call failed'}")
        return data["result"]

    def contests(self) -> list[pages.Contest]:
        """Contests that haven't started yet, soonest first."""
        result = _cached(
            paths.STATE_DIR / "contests.json",
            CONTESTS_MAX_AGE,
            lambda: self.api("contest.list?gym=false"),
        )
        now = time.time()
        upcoming = [
            c for c in pages.parse_contests(result) if c.phase == "BEFORE" and c.start > now
        ]
        return sorted(upcoming, key=lambda c: c.start)

    def problemset(self) -> list[pages.ProblemsetProblem]:
        """Every problem of the problemset."""
        result = _cached(
            paths.STATE_DIR / "problemset.json",
            PROBLEMSET_MAX_AGE,
            lambda: self.api("problemset.problems"),
        )
        return pages.parse_problemset(result)

    def solved(self, handle: str) -> set[tuple[int, str]]:
        """(contest id, index) of the problems handle has solved."""
        return pages.parse_solved(self.api(f"user.status?handle={handle}"))

    def languages(self) -> tuple[dict[str, str], bool]:
        """(id -> name, is_live): the submit form's list when logged in, else
        the one read last (or the built-in table); read once per run. Never
        opens a browser for it."""
        if self._languages is None:
            try:
                body = self.gw.get(f"{self.host}/problemset/submit", browser_fallback=False)
                live = pages.parse_languages(body)
            except CFError:
                live = {}
            if live:
                languages.remember_languages(live)
            self._languages = (live, True) if live else (languages.known_languages(), False)
        return self._languages


def _read_problem(index: str, body: str, url: str) -> FetchedProblem:
    """A problem's statement page (or its part of the all-problems page)."""
    header = pages.find_problem_header(body)
    info = ProblemInfo(
        name=header.name,
        url=url,
        time_limit=header.time_limit,
        memory_limit=header.memory_limit,
        interactive=header.interactive,
        ignore_case=header.ignore_case,
        epsilon=header.epsilon,
        cases=pages.find_sample_cases(body),
    )
    try:
        inputs, outputs = pages.find_samples(body)
    except CFError as e:
        return FetchedProblem(
            index.upper(), info, standard_io=pages.is_standard_io(body), error=str(e)
        )
    return FetchedProblem(
        index.upper(), info, list(zip(inputs, outputs)), pages.is_standard_io(body)
    )


def _cached(path: Path, max_age: float, fetch: Callable[[], Any]) -> Any:
    """fetch()'s result, kept in path and reused while it is younger than
    max_age seconds (an unreadable copy is fetched again)."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if 0 <= time.time() - saved["fetched"] < max_age:
            return saved["result"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = fetch()
    paths.write_atomic(path, json.dumps({"fetched": time.time(), "result": result}))
    return result


def pick_problem(
    problems: list[pages.ProblemsetProblem],
    solved: set[tuple[int, str]],
    *,
    low: int | None = None,
    high: int | None = None,
    tags: Sequence[str] = (),
    rng: random.Random | None = None,
) -> tuple[pages.ProblemsetProblem | None, int]:
    """A random problem to practice on, and how many there were to pick from.
    It is:
    - not solved yet, and not a joke (*special) unless that tag is asked for
    - rated from low to high, when given (unrated problems are then out)
    - tagged with every tag given, and with no tag given as "!tag" either"""
    wanted = {tag for tag in tags if not tag.startswith("!")}
    avoided = {tag[1:] for tag in tags if tag.startswith("!")} | ({"*special"} - wanted)
    pool = [
        p
        for p in problems
        if (p.contest_id, p.index) not in solved
        and wanted <= set(p.tags)
        and not avoided & set(p.tags)
        and (low is None or (p.rating is not None and low <= p.rating <= (high or low)))
    ]
    return ((rng or random).choice(pool) if pool else None), len(pool)
