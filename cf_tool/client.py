"""Codeforces operations: parse, list, race, submit, watch, pull, clone and
the language list. Port of the Go client package; getting in (HTTP,
Cloudflare, login) is gateway.py's job, drawing is views.py's.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Sequence

from rich.live import Live
from rich.text import Text

from cf_tool import langs, pages, ui, views
from cf_tool.args import ERROR_NEED_PROBLEM_ID, Info
from cf_tool import config as config_module
from cf_tool.config import SESSION_PATH, Config, write_atomic
from cf_tool.errors import CFError
from cf_tool.gateway import Gateway, host_domain
from cf_tool.problem import ProblemInfo
from cf_tool.session import INFO_KEYS, Session

ERROR_SKIP = "Exists, skip"
ERROR_TOO_MANY_REQUESTS = "Too many requests"
PARSE_THREADS = 8
CONTESTS_MAX_AGE = 1800  # seconds: the contest list rarely changes
PROBLEMSET_MAX_AGE = 86400  # seconds: new problems come with new contests
API_INTERVAL = 2.1  # seconds between API calls
CLONE_THREADS = 16


class Client:
    def __init__(self, cfg: Config, session_path: Path | None = None) -> None:
        self.cfg = cfg
        self.session = Session.load(session_path or SESSION_PATH, host_domain(cfg.host))
        self.gw = Gateway(cfg, self.session)
        self._languages: tuple[dict[str, str], bool] | None = None
        self._last_api = float("-inf")  # time.monotonic() of the last API call

    @property
    def host(self) -> str:
        return self.cfg.host

    @property
    def handle(self) -> str:
        return self.session.handle

    @property
    def last_submission(self) -> dict[str, str] | None:
        return self.session.last_submission

    def config_login(self, handle_or_email: str, password: str) -> None:
        """Store credentials (encrypted) and log in."""
        self._languages = None  # NOTE: logged in, the live list becomes readable
        self.gw.set_credentials(handle_or_email, password)
        self.gw.login()

    # ---------------------------------------------------------------- parse

    def parse_problem(self, url: str, path: Path) -> tuple[int, bool, ProblemInfo]:
        """Download one problem's samples into path as in{i}.txt/ans{i}.txt,
        and what cf test needs to know about it (problem.py); returns (sample
        count, standard input/output?, that info)."""
        body = self.gw.get_authed(url)
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
        path.mkdir(parents=True, exist_ok=True)
        info.save(path)  # NOTE: before the samples, which may fail to parse
        inputs, outputs = pages.find_samples(body)
        for i, (sample_in, sample_out) in enumerate(zip(inputs, outputs), start=1):
            (path / f"in{i}.txt").write_text(sample_in, encoding="utf-8", newline="")
            (path / f"ans{i}.txt").write_text(sample_out, encoding="utf-8", newline="")
        return len(inputs), pages.is_standard_io(body), info

    def parse(self, info: Info) -> tuple[list[str], list[Path]]:
        """Parse one problem, or every problem of the contest concurrently;
        returns (problem ids, their directories)."""
        ui.cyan("Parse " + info.hint())
        if info.problem_id:
            problem_ids = [info.problem_id]
        else:
            problem_ids = [p.id for p in self.statis(info)]
        contest_root = dataclasses.replace(info, problem_id="").path()
        ui.line(("The problem(s) will be saved to ", "cyan"), (str(contest_root), "green"))
        paths = [contest_root / problem_id.lower() for problem_id in problem_ids]
        for path in paths:
            # up front, like Go: "gen after parse" writes into every one,
            # even where the samples could not be parsed
            path.mkdir(parents=True, exist_ok=True)

        def work(problem_id: str, path: Path) -> None:
            url = dataclasses.replace(info, problem_id=problem_id).problem_url(self.host)
            try:
                samples, standard_io, problem = self.parse_problem(url, path)
            except CFError as e:
                ui.red(f"Failed {problem_id}. Error: {e}")
                return
            noun = "sample" if samples == 1 else "samples"
            parts = [(f"Parsed {problem_id} with {samples} {noun}.", "green")]
            if not standard_io:
                parts.append((" Non standard input output format.", "yellow"))
            if problem.interactive:
                parts.append((" Interactive: cf test can't judge it.", "yellow"))
            ui.line(*parts)

        with ThreadPoolExecutor(max_workers=min(PARSE_THREADS, len(problem_ids))) as pool:
            list(pool.map(work, problem_ids, paths))
        return problem_ids, paths

    # ----------------------------------------------------------------- list

    def statis(self, info: Info) -> list[pages.StatisInfo]:
        if info.problem_type == "acmsguru":
            raise CFError("Not support acmsguru")
        body = self.gw.get_authed(info.problem_set_url(self.host))
        return pages.parse_problems(body)

    # ----------------------------------------------------------------- race

    def race(self, info: Info) -> None:
        """Count down to the contest start (no-op once it has begun)."""
        ui.cyan("Race " + info.hint())
        if info.problem_type == "acmsguru":
            raise CFError("Not support acmsguru")
        body = self.gw.get_authed(info.problem_set_url(self.host) + "/countdown")
        if "Go!</a>" in body:
            return
        # against a fixed deadline: sleeping 1s per tick would drift late
        deadline = time.monotonic() + pages.find_countdown(body)
        with Live(console=ui.console, auto_refresh=False, transient=True) as live:
            while (remaining := deadline - time.monotonic()) > 0:
                h, rest = divmod(math.ceil(remaining), 3600)
                m, s = divmod(rest, 60)
                live.update(
                    Text.assemble(("Countdown: ", "green"), (f"{h:02d}:{m:02d}:{s:02d}", "bold")),
                    refresh=True,
                )
                time.sleep(remaining - math.floor(remaining) or 1)  # until the next tick
        time.sleep(0.9)

    # --------------------------------------------------------------- submit

    def submit(
        self,
        info: Info,
        lang_id: str,
        source: str,
        filename: str = "",
        replace_language: Callable[[str, dict[str, str]], str] | None = None,
    ) -> None:
        """Submit source, then watch its verdict; filename is only shown.
        When the submit form doesn't offer lang_id, replace_language(lang_id,
        offered) names the one to use instead; without it that's an error."""
        if filename:
            ui.line(("Submit ", "cyan"), (filename, "bold green"), (f" to {info.hint()}", "cyan"))
        else:
            ui.cyan("Submit " + info.hint())
        if not info.problem_id:
            raise CFError(ERROR_NEED_PROBLEM_ID)
        url = info.submit_url(self.host)
        body = self.gw.get_authed(url)
        handle = pages.require_handle(body)
        ui.plain(f"Current user: {handle}")
        offered = pages.parse_languages(body)
        if offered and lang_id not in offered:
            if replace_language is None:
                raise CFError(f"The submit form doesn't offer language {lang_id}")
            lang_id = replace_language(lang_id, offered)
        if offered:
            ui.plain(f"Language: {offered.get(lang_id, lang_id)}")
        csrf = pages.find_csrf(body)
        ftaa, bfaa = self.gw.form_tokens()
        body = self.gw.post(
            f"{url}?csrf_token={csrf}",
            data={
                "csrf_token": csrf,
                "ftaa": ftaa,
                "bfaa": bfaa,
                "action": "submitSolutionFormSubmitted",
                "submittedProblemIndex": info.problem_id,
                "programTypeId": lang_id,
                "contestId": info.contest_id,
                "source": source,
                "tabSize": "4",
                "_tta": "594",
                "sourceCodeConfirmed": "true",
            },
        )
        error = pages.find_error_message(body)
        if error:
            raise CFError(error)
        message = pages.find_message(body)
        if message is None:
            raise CFError("Submit failed")
        if "submitted successfully" not in message:
            raise CFError(message)
        ui.green("Submitted")

        submissions = self.watch(info, count=1, line=True)
        self.session.handle = handle
        last = dataclasses.replace(info, submission_id=str(submissions[0].id))
        self.session.last_submission = {key: getattr(last, key) for key in INFO_KEYS}
        self.gw.save()

    # ---------------------------------------------------------------- watch

    def watch(
        self, info: Info, count: int = 10, problem_filter: str = "", line: bool = False
    ) -> list[pages.Submission]:
        """Poll the my-submissions page about once a second until every verdict
        is final; returns the submissions.

        line=True shows the newest submission as a detail panel (the view
        after submit, like the Go tool); otherwise a table of recent ones.
        """
        url = info.my_submission_url(self.host)

        def render(submissions: list[pages.Submission]):
            if line:  # NOTE: unboxed for a pipe: CP Editor reads "status: ..." from it
                return views.submission_panel(submissions[0], boxed=ui.console.is_terminal)
            return views.submission_table(submissions, problem_filter)

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
                if elapsed < 1:
                    time.sleep(1 - elapsed)
        ui.console.print(render(submissions))
        return submissions

    # ----------------------------------------------------------- pull/clone

    def pull_code(self, url: str, base: Path, ext: str, rename: bool) -> Path:
        """Save one submission's source as <base><ext>; returns the file."""
        filename = Path(f"{base}{ext}")
        if rename:
            i = 1
            while filename.exists():
                filename = Path(f"{base}_{i}{ext}")
                i += 1
        elif filename.exists():
            raise CFError(ERROR_SKIP)

        body = self.gw.get(url)
        message = pages.find_message(body)
        if message is not None:
            raise CFError(message)
        code = pages.find_code(body)
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text(code, encoding="utf-8", newline="")
        return filename

    def pull(self, info: Info, root_path: Path, ac: bool) -> None:
        ui.cyan("Pull " + info.hint())
        body = self.gw.get_authed(info.my_submission_url(self.host))
        submissions = pages.parse_submissions(body)
        used = []
        for sub in submissions:
            problem_id = sub.problem_index()
            if info.problem_id and info.problem_id.lower() != problem_id:
                continue
            if ac and not ("Accepted" in sub.status or "Pretests passed" in sub.status):
                continue
            ext = langs.ext_of(sub.lang)
            if ext == "txt":
                continue
            if info.problem_id:
                base = root_path / problem_id
            else:
                base = root_path / problem_id / problem_id
            sub_info = dataclasses.replace(info, submission_id=str(sub.id))
            try:
                filename = self.pull_code(
                    sub_info.submission_url(self.host), base, f".{ext}", rename=True
                )
                ui.green(f"Saved {filename}")
                used.append(sub)
            except CFError as e:
                ui.red(f"Error {sub_info.hint()}: {e}")
        if not used:
            raise CFError("Cannot find any code to save")
        ui.cyan("These submissions' codes have been saved.")
        ui.console.print(views.submission_table(used))

    def clone(self, handle: str, root_path: Path, ac: bool) -> None:
        ui.cyan(f"Clone all codes of {handle}. Only Accepted: {ac}")
        data = self.gw.get_json(f"{self.host}/api/user.status?handle={handle}")
        if data.get("status") != "OK":
            raise CFError("Cannot get any submission")
        submissions = data["result"]
        total = len(submissions)
        ui.cyan(f"Total submissions: {total}")

        lock, done = Lock(), 0

        def bump() -> int:
            """Count one more submission handled; returns the count."""
            nonlocal done
            with lock:
                done += 1
                return done

        jobs = []
        for sub in submissions:
            verdict = sub.get("verdict", "")
            contest_id = str(int(sub["contestId"])) if "contestId" in sub else "99999"
            submission_id = str(int(sub["id"]))
            problem_id = sub["problem"]["index"].lower()
            problem_type = "contest"
            if contest_id == "99999":
                problem_type = "acmsguru"
            elif len(contest_id) >= 6:
                problem_type = "gym"
            info = Info(
                problem_type=problem_type,
                contest_id=contest_id,
                problem_id=problem_id,
                submission_id=submission_id,
                root_path=root_path / handle / problem_type,
            )
            if ac and verdict != "OK":
                ui.green(f"{bump()}/{total} Skip {info.hint()}: Not an accepted code")
                continue
            language = sub.get("programmingLanguage", "")
            ext = langs.ext_of(language)
            if ext == "txt":
                ui.red(
                    f'{bump()}/{total} Error {info.hint()}: Language "{language}" is not supported'
                )
                continue
            filename = submission_id
            if verdict != "OK":
                filename = f"{submission_id}_{verdict.lower()}_{sub.get('passedTestCount', 0)}"
            jobs.append((info.submission_url(self.host), info.path() / filename, f".{ext}"))

        def worker(job: tuple[str, Path, str]) -> None:
            url, base, ext = job
            while True:
                try:
                    filename = self.pull_code(url, base, ext, rename=False)
                    ui.green(f"{bump()}/{total} Saved {filename}")
                except CFError as e:
                    if str(e) == ERROR_SKIP:
                        ui.yellow(f"{bump()}/{total} Exist {url}: Skip.")
                    elif str(e) == ERROR_TOO_MANY_REQUESTS:
                        ui.red(f"Error {url}: {e}. Waiting 500 seconds to continue.")
                        time.sleep(500)
                        continue
                    else:
                        ui.red(f"{bump()}/{total} Error {url}: {e}")
                return

        with ThreadPoolExecutor(max_workers=CLONE_THREADS) as pool:
            list(pool.map(worker, jobs))

    # ------------------------------------------------------------ contests

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
            config_module.STATE_DIR / "contests.json",
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
            config_module.STATE_DIR / "problemset.json",
            PROBLEMSET_MAX_AGE,
            lambda: self.api("problemset.problems"),
        )
        return pages.parse_problemset(result)

    def solved(self, handle: str) -> set[tuple[int, str]]:
        """(contest id, index) of the problems handle has solved."""
        return pages.parse_solved(self.api(f"user.status?handle={handle}"))

    # ------------------------------------------------------------ languages

    def languages(self) -> tuple[dict[str, str], bool]:
        """(id -> name, is_live): the submit form's list when logged in, else
        the built-in table; read once per run. Never opens a browser for it."""
        if self._languages is None:
            try:
                body = self.gw.get(f"{self.host}/problemset/submit", browser_fallback=False)
                live = pages.parse_languages(body)
            except CFError:
                live = {}
            self._languages = (live, True) if live else (langs.LANGS, False)
        return self._languages


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
    write_atomic(path, json.dumps({"fetched": time.time(), "result": result}))
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
