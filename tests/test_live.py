"""Checks against the real codeforces.com: does its markup still fit the
parsers? Opt-in: `uv run pytest -m live`.

Public pages only, fetched over plain HTTP the way cf fetches them: no login,
no session, nothing submitted, at most one request a second. The expected
values match the trimmed copies in tests/fixtures/ (taken 2026-10-12).
"""

from __future__ import annotations

import functools
import json
import re
import time

import pytest
from curl_cffi import requests as curl_requests

from cf_tool import langs, pages
from cf_tool.http import IMPERSONATE, TIMEOUT, is_challenge

pytestmark = pytest.mark.live

HOST = "https://codeforces.com"
_last_request = [0.0]


@functools.cache
def _session() -> curl_requests.Session:
    return curl_requests.Session(impersonate=IMPERSONATE, timeout=TIMEOUT)


def fetch(path: str, content: str) -> str:
    """Body of a public page, which must contain content.
    - Cloudflare checks this connection: the test is skipped
    - our challenge check fires on the real page: the test fails"""
    wait = _last_request[0] + 1 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    response = _session().get(HOST + path)
    _last_request[0] = time.monotonic()
    if is_challenge(response):
        assert content not in response.text, f"{path}: a normal page taken for a Cloudflare check"
        pytest.skip(f"Cloudflare checks this connection ({path})")
    assert content in response.text, f"{path}: no {content!r} in it (HTTP {response.status_code})"
    return response.text


def api(method: str) -> list:
    """The result of a public API call."""
    return json.loads(fetch(f"/api/{method}", '"status":"OK"'))["result"]


def test_samples_in_br_markup():
    page = fetch("/problemset/problem/4/A", "problem-statement")
    assert pages.find_samples(page) == (["8\n"], ["YES\n"])
    assert pages.is_standard_io(page)


def test_samples_in_line_markup():
    page = fetch("/contest/2171/problem/A", "problem-statement")
    assert pages.find_samples(page) == (["5\n2\n3\n4\n6\n100\n"], ["1\n0\n2\n2\n26\n"])


def test_file_io_problem():
    page = fetch("/problemset/problem/120/A", "problem-statement")
    assert pages.find_samples(page) == (["front\n1\n"], ["L\n"])
    assert not pages.is_standard_io(page)


def test_acmsguru_samples():
    page = fetch("/problemsets/acmsguru/problem/99999/100", "Sample")
    assert pages.find_samples(page) == (["5 3\n"], ["8\n"])


def test_contest_problem_list():
    problems = pages.parse_problems(fetch("/contest/2171", 'class="problems"'))
    assert len(problems) == 9 and problems[0].id == "A"
    assert problems[0].name == "Shizuku Hoshikawa and Farm Legs"
    assert (problems[0].io, problems[0].limit) == ("standard input/output", "1 s, 256 MB")


def test_submissions_table():
    subs = pages.parse_submissions(fetch("/contest/4/status", "data-submission-id"), 20)
    assert len(subs) == 20
    assert all(sub.id and sub.lang and sub.status != "Unknown" for sub in subs)


def test_language_names_have_extensions():
    names = {sub["programmingLanguage"] for sub in api("contest.status?contestId=4&count=300")}
    common = [n for n in names if re.search(r"C\+\+|G\+\+|Python|PyPy|Java\b|Kotlin|Rust", n)]
    assert common, names
    assert [n for n in common if langs.ext_of(n) == "txt"] == []


def test_countdown_of_the_next_contest():
    upcoming = [c for c in api("contest.list?gym=false") if c["phase"] == "BEFORE"]
    if not upcoming:
        pytest.skip("no upcoming contest")
    soonest = max(upcoming, key=lambda c: c["relativeTimeSeconds"])  # NOTE: negative before it
    seconds = pages.find_countdown(fetch(f"/contest/{soonest['id']}/countdown", "countdown"))
    assert abs(seconds + soonest["relativeTimeSeconds"]) < 120


def test_login_form():
    page = fetch("/enter", "handleOrEmail")
    assert pages.find_csrf(page)


def test_problem_header_and_cases():
    page = fetch("/contest/2171/problem/A", "problem-statement")
    assert pages.find_problem_header(page) == pages.ProblemHeader(
        "A. Shizuku Hoshikawa and Farm Legs", 1.0, 256, False
    )
    assert pages.find_sample_cases(page) == [([0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5])]
    assert pages.find_problem_header(
        fetch("/problemset/problem/1520/F1", "problem-statement")
    ).interactive
