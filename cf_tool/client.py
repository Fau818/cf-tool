"""Codeforces client: session persistence, tiered login, and every network
operation (parse/submit/watch/pull/clone/...). Port of the Go client package.

Login tiers (first that works wins):
  0. existing cookies are still valid
  1. plain HTTP POST /enter (the original Go flow) over curl_cffi
  2. headless browser (DrissionPage) — solves Turnstile in the background
  3. visible browser — last resort, announced to the user
"""

from __future__ import annotations

import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from rich.live import Live
from rich.table import Table
from rich.text import Text

from cf_tool import browser, crypto, langs, pages, templates, ui
from cf_tool.args import Info
from cf_tool.config import SESSION_PATH, Config
from cf_tool.errors import CFError, CloudflareChallengeError, NotLoggedInError
from cf_tool.http import Transport

ERROR_SKIP = "Exists, skip"
ERROR_TOO_MANY_REQUESTS = "Too many requests"
_BFAA = "f1b3f18c715565b589b7823cda7448ce"

_INFO_KEYS = ("problem_type", "contest_id", "group_id", "problem_id", "submission_id")


class Client:
    def __init__(self, cfg: Config, session_path: Path = SESSION_PATH) -> None:
        self.cfg = cfg
        self._path = session_path
        data: dict = {}
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        self.handle: str = data.get("handle", "")
        self.handle_or_email: str = data.get("handle_or_email", "")
        self.password: str = data.get("password", "")  # encrypted (crypto.py)
        self.ftaa: str = data.get("ftaa", "")
        self.bfaa: str = data.get("bfaa", "")
        self.user_agent: str = data.get("user_agent", "")
        self.last_submission: dict | None = data.get("last_submission")
        self.http = Transport(
            proxy=cfg.proxy,
            user_agent=self.user_agent,
            cookies=data.get("cookies", {}),
            domain=urlparse(cfg.host).hostname or "",
        )

    @property
    def host(self) -> str:
        return self.cfg.host

    def save(self) -> None:
        data = {
            "handle": self.handle,
            "handle_or_email": self.handle_or_email,
            "password": self.password,
            "ftaa": self.ftaa,
            "bfaa": self.bfaa,
            "user_agent": self.user_agent,
            "cookies": self.http.cookies,
            "last_submission": self.last_submission,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self._path.chmod(0o600)

    # ------------------------------------------------------------ transport

    def _adopt_browser_session(self, session: browser.BrowserSession) -> None:
        self.http.set_cookies(session.cookies, replace=True)
        if session.user_agent:
            self.user_agent = session.user_agent
            self.http.set_user_agent(session.user_agent)
        self.save()

    def get_body(self, url: str) -> str:
        """GET with Cloudflare fallback: headless browser, then visible."""
        try:
            return self.http.get(url).text
        except CloudflareChallengeError:
            pass
        ui.yellow("Cloudflare challenge hit; solving in a background browser...")
        for headless in (True, False):
            if not headless:
                ui.yellow("Headless attempt failed; opening a visible browser window...")
            try:
                session = browser.fetch(url, headless=headless)
            except CFError:
                continue
            self._adopt_browser_session(session)
            try:
                return self.http.get(url).text
            except CloudflareChallengeError:
                # transport still blocked, but the browser page itself is real content
                if not any(m in session.html for m in ("Just a moment", "cf-chl")):
                    return session.html
        raise CloudflareChallengeError()

    def _authed_body(self, url: str) -> str:
        """GET a page that needs login; silently re-login once if logged out."""
        body = self.get_body(url)
        if pages.find_handle(body) is not None:
            return body
        ui.red("Not logged. Try to login\n")
        self.login()
        body = self.get_body(url)
        pages.require_handle(body)
        return body

    # ----------------------------------------------------------------- auth

    def login(self) -> None:
        """Tiered login with stored credentials."""
        if not self.handle_or_email or not self.password:
            raise CFError("You have to configure your handle and password by `cf config`")
        password = crypto.decrypt_password(self.handle_or_email, self.password)
        ui.cyan(f"Login {self.handle_or_email}...")

        try:
            if self._login_http(password):
                return
        except (CFError, CloudflareChallengeError) as e:
            ui.yellow(f"HTTP login failed ({e}); trying a headless browser...")
        else:
            ui.yellow("HTTP login failed; trying a headless browser...")
        try:
            if self._login_browser(password, headless=True):
                return
            ui.yellow("Headless login failed (browser session not authenticated); ")
        except CFError as e:
            ui.yellow(f"Headless login failed ({e}); ")
        ui.yellow("Opening a visible browser (Cloudflare Turnstile)...")
        if self._login_browser(password, headless=False):
            return
        raise CFError("Login failed on all tiers. Check your handle/password")

    def _welcome(self, handle: str) -> None:
        self.handle = handle
        self.save()
        ui.green("Succeed!!")
        ui.green(f"Welcome {handle}~")

    def _login_http(self, password: str) -> bool:
        body = self.http.get(f"{self.host}/enter").text
        handle = pages.find_handle(body)
        if handle:  # cookies were still valid
            self._welcome(handle)
            return True
        csrf = pages.find_csrf(body)
        ftaa = templates.rand_string(18)
        bfaa = _BFAA
        body = self.http.post(
            f"{self.host}/enter",
            data={
                "csrf_token": csrf,
                "action": "enter",
                "ftaa": ftaa,
                "bfaa": bfaa,
                "handleOrEmail": self.handle_or_email,
                "password": password,
                "_tta": "176",
                "remember": "on",
            },
        ).text
        handle = pages.find_handle(body)
        if not handle:
            error = pages.find_error_message(body)
            raise CFError(error or "Login failed")
        self.ftaa = ftaa
        self.bfaa = bfaa
        self._welcome(handle)
        return True

    def _login_browser(self, password: str, headless: bool) -> bool:
        session = browser.login(self.host, self.handle_or_email, password, headless=headless)
        self._adopt_browser_session(session)
        browser_handle = pages.find_handle(session.html)
        try:
            body = self.http.get(self.host).text
            handle = pages.find_handle(body)
        except CloudflareChallengeError:
            handle = None
        if not handle:
            if browser_handle:
                # the browser IS logged in; the exported cookies just don't
                # satisfy Cloudflare over curl_cffi (cf_clearance is bound to
                # the TLS fingerprint, not only the UA)
                raise CFError(
                    "browser login succeeded but the exported session "
                    "is rejected over HTTP (Cloudflare binding)"
                )
            return False
        if not self.ftaa:
            self.ftaa = templates.rand_string(18)
        if not self.bfaa:
            self.bfaa = _BFAA
        self._welcome(handle)
        return True

    def config_login(self, handle_or_email: str, password: str) -> None:
        """Store credentials (encrypted) and log in."""
        self.handle_or_email = handle_or_email
        self.password = crypto.encrypt_password(handle_or_email, password)
        self.save()
        self.login()

    # ---------------------------------------------------------------- parse

    def parse_problem(self, url: str, path: Path) -> tuple[int, bool]:
        """Download one problem's samples into path as in{i}.txt/ans{i}.txt."""
        body = self._authed_body(url)
        inputs, outputs = pages.find_samples(body)
        path.mkdir(parents=True, exist_ok=True)
        for i, (sample_in, sample_out) in enumerate(zip(inputs, outputs), start=1):
            (path / f"in{i}.txt").write_text(sample_in, encoding="utf-8")
            (path / f"ans{i}.txt").write_text(sample_out, encoding="utf-8")
        return len(inputs), pages.is_standard_io(body)

    def parse(self, info: Info) -> tuple[list[str], list[Path]]:
        ui.cyan("Parse " + info.hint())
        if info.problem_id:
            problem_ids = [info.problem_id]
        else:
            problem_ids = [p.id for p in self.statis(info)]
        contest_root = dataclasses.replace(info, problem_id="").path()
        ui.console.print(
            f"[cyan]The problem(s) will be saved to[/cyan] [green]{contest_root}[/green]"
        )
        paths = []
        for problem_id in problem_ids:
            path = contest_root / problem_id.lower()
            paths.append(path)
            ui.plain(f"Parsing {problem_id}")
            url = dataclasses.replace(info, problem_id=problem_id).problem_url(self.host)
            try:
                samples, standard_io = self.parse_problem(url, path)
            except CFError as e:
                ui.red(f"Failed {problem_id}. Error: {e}")
                continue
            warning = "" if standard_io else " [yellow]Non standard input output format.[/yellow]"
            ui.console.print(f"[green]Parsed {problem_id} with {samples} samples.[/green]{warning}")
        return problem_ids, paths

    # ----------------------------------------------------------------- list

    def statis(self, info: Info) -> list[pages.StatisInfo]:
        if info.problem_type == "acmsguru":
            raise CFError("Not support acmsguru")
        body = self._authed_body(info.problem_set_url(self.host))
        return pages.parse_problems(body)

    # ----------------------------------------------------------------- race

    def race(self, info: Info) -> None:
        ui.cyan("Race " + info.hint())
        if info.problem_type == "acmsguru":
            raise CFError("Not support acmsguru")
        url = info.problem_set_url(self.host) + "/countdown"
        body = self._authed_body(url)
        if "Go!</a>" not in body:
            count = pages.find_countdown(body)
            ui.green("Countdown: ")
            while count > 0:
                h, rem = divmod(count, 3600)
                m, s = divmod(rem, 60)
                print(f"\r{h:02d}:{m:02d}:{s:02d}", end="", flush=True)
                time.sleep(1)
                count -= 1
            print()
            time.sleep(0.9)

    # --------------------------------------------------------------- submit

    def submit(self, info: Info, lang_id: str, source: str) -> None:
        ui.cyan("Submit " + info.hint())
        url = info.submit_url(self.host)
        body = self._authed_body(url)
        handle = pages.require_handle(body)
        ui.plain(f"Current user: {handle}")
        csrf = pages.find_csrf(body)
        if not self.ftaa:
            self.ftaa = templates.rand_string(18)
        if not self.bfaa:
            self.bfaa = _BFAA
        body = self.http.post(
            f"{url}?csrf_token={csrf}",
            data={
                "csrf_token": csrf,
                "ftaa": self.ftaa,
                "bfaa": self.bfaa,
                "action": "submitSolutionFormSubmitted",
                "submittedProblemIndex": info.problem_id,
                "programTypeId": lang_id,
                "contestId": info.contest_id,
                "source": source,
                "tabSize": "4",
                "_tta": "594",
                "sourceCodeConfirmed": "true",
            },
        ).text
        error = pages.find_error_message(body)
        if error:
            raise CFError(error)
        message = pages.find_message(body)
        if message is None:
            raise CFError("Submit failed")
        if "submitted successfully" not in message:
            raise CFError(message)
        ui.green("Submitted")

        submissions = self.watch(info, count=1)
        self.handle = handle
        last = dataclasses.replace(info, submission_id=str(submissions[0].id))
        self.last_submission = {k: getattr(last, k) for k in _INFO_KEYS}
        self.save()

    # ---------------------------------------------------------------- watch

    def _submission_table(self, submissions: list[pages.Submission], problem_id: str) -> Table:
        table = Table(box=None, header_style="bold")
        for column in ("#", "when", "problem", "lang", "status", "time", "memory"):
            table.add_column(column, justify="center")
        for sub in submissions:
            if problem_id and sub.problem_index() != problem_id.lower():
                continue
            status, style = sub.styled_status()
            table.add_row(
                str(sub.id),
                sub.when,
                sub.name,
                sub.lang,
                Text(status, style=style),
                sub.parse_time(),
                sub.parse_memory(),
            )
        return table

    def watch(
        self, info: Info, count: int = 10, problem_filter: str = ""
    ) -> list[pages.Submission]:
        """Poll the my-submissions page every ~1s until all verdicts are final."""
        url = info.my_submission_url(self.host)
        submissions: list[pages.Submission] = []
        with Live(console=ui.console, auto_refresh=False) as live:
            while True:
                started = time.monotonic()
                body = self._authed_body(url)
                submissions = pages.parse_submissions(body, count)
                live.update(self._submission_table(submissions, problem_filter), refresh=True)
                if all(sub.end for sub in submissions):
                    return submissions
                elapsed = time.monotonic() - started
                if elapsed < 1:
                    time.sleep(1 - elapsed)

    # ----------------------------------------------------------- pull/clone

    def pull_code(self, url: str, base: Path, ext: str, rename: bool) -> Path:
        filename = Path(f"{base}{ext}")
        if rename:
            i = 1
            while filename.exists():
                filename = Path(f"{base}_{i}{ext}")
                i += 1
        elif filename.exists():
            raise CFError(ERROR_SKIP)

        body = self.get_body(url)
        message = pages.find_message(body)
        if message is not None:
            raise CFError(message)
        code = pages.find_code(body)
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text(code, encoding="utf-8")
        return filename

    def pull(self, info: Info, root_path: Path, ac: bool) -> None:
        ui.cyan("Pull " + info.hint())
        body = self._authed_body(info.my_submission_url(self.host))
        submissions = pages.parse_submissions(body)
        used = []
        for sub in submissions:
            problem_id = sub.name.split(" ")[0].lower()
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
        ui.console.print(self._submission_table(used, ""))

    def clone(self, handle: str, root_path: Path, ac: bool) -> None:
        ui.cyan(f"Clone all codes of {handle}. Only Accepted: {ac}")
        data = self.http.get_json(f"{self.host}/api/user.status?handle={handle}")
        if data.get("status") != "OK":
            raise CFError("Cannot get any submission")
        submissions = data["result"]
        total = len(submissions)
        ui.cyan(f"Total submissions: {total}")

        lock = Lock()
        counter = {"n": 0}

        def bump() -> int:
            with lock:
                counter["n"] += 1
                return counter["n"]

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
            ext = langs.ext_of(sub.get("programmingLanguage", ""))
            if ext == "txt":
                ui.red(
                    f"{bump()}/{total} Error {info.hint()}: Language "
                    f'"{sub.get("programmingLanguage", "")}" is not supported'
                )
                continue
            filename = submission_id
            if verdict != "OK":
                filename = f"{submission_id}_{verdict.lower()}_{sub.get('passedTestCount', 0)}"
            jobs.append((info.submission_url(self.host), info.path() / filename, f".{ext}"))

        def worker(job) -> None:
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

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, jobs))

    # ------------------------------------------------------------ languages

    def languages(self) -> dict[str, str]:
        """Live language list from the submit form; static fallback if not
        logged in / offline (no login is forced just for the list)."""
        try:
            body = self.get_body(f"{self.host}/problemset/submit")
            live = pages.parse_languages(body)
            if live:
                return live
        except (CFError, NotLoggedInError):
            pass
        return langs.LANGS
