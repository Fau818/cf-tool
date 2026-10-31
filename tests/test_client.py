"""Client operations against a fake gateway: getting problems (one request
for a contest), submitting once, and the public API."""

import random
import time
from pathlib import Path

import pytest

from cf_tool import paths
from cf_tool.codeforces import client as client_module
from cf_tool.codeforces import pages
from cf_tool.codeforces.client import Client, pick_problem
from cf_tool.codeforces.http import Uncertain
from cf_tool.codeforces.session import Session
from cf_tool.errors import CFError
from cf_tool.settings import Settings
from cf_tool.workspace import ProblemInfo, Target

HOST = "https://codeforces.com"
FIXTURES = Path(__file__).parent / "fixtures"

SUBMIT_PAGE = """<script>var handle = "tourist";</script>
<meta name="X-Csrf-Token" content="x"/><span class="csrf-token" data-csrf='abc123'></span>
<form>csrf='abc123'
<select name="programTypeId">
  <option value="54">GNU G++17 7.3.0</option>
  <option value="91">GNU G++23 14.2 (64 bit, msys2)</option>
  <option value="70">PyPy 3.10 (7.3.15, 64bit)</option>
</select></form>"""

SUBMITTED = 'Codeforces.showMessage("Solution submitted successfully"); Codeforces.reformatTimes();'


class FakeGateway:
    """Serves pages by URL (a callable answer is called), records POSTs."""

    def __init__(self, pages_by_url=None, post=SUBMITTED) -> None:
        self.pages = dict(pages_by_url or {})
        self.post_answer = post
        self.posted: list[dict] = []
        self.fetched: list[str] = []

    def get(self, url, **kwargs):
        self.fetched.append(url)
        answer = self.pages.get(url, "")
        return answer() if callable(answer) else answer

    get_authed = get

    def form_tokens(self):
        return "ftaa", "bfaa"

    def post(self, url, data):
        self.posted.append(data)
        if isinstance(self.post_answer, Exception):
            raise self.post_answer
        return self.post_answer

    def save(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / "state")
    c = Client(Settings(), Session(tmp_path / "session"))
    c.gw = FakeGateway()
    return c


# ┌──────────────────────────────────────────────────────────┐
# │                         Problems                         │
# └──────────────────────────────────────────────────────────┘


def test_a_problem_from_its_page(client):
    url = f"{HOST}/contest/2171/problem/A"
    client.gw.pages[url] = (FIXTURES / "problem_2171a.html").read_text()
    (problem,) = client.fetch(Target("contest", "2171", "A"))
    assert problem.index == "A" and len(problem.samples) == 1 and problem.standard_io
    assert problem.info == ProblemInfo(
        name="A. Shizuku Hoshikawa and Farm Legs",
        url=url,
        time_limit=1.0,
        memory_limit=256,
        interactive=False,
        cases=[([0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5])],
    )


def test_a_contest_in_one_request(client):
    client.gw.pages[f"{HOST}/contest/2171/problems"] = (
        FIXTURES / "contest_2171_problems.html"
    ).read_text()
    found = client.fetch(Target("contest", "2171"))
    assert [p.index for p in found] == ["A", "B"]
    assert found[1].info.url == f"{HOST}/contest/2171/problem/B"
    assert all(p.samples for p in found)
    assert client.gw.fetched == [f"{HOST}/contest/2171/problems"]


def test_a_contest_without_the_problems_page(client):
    client.gw.pages[f"{HOST}/contest/2171"] = (FIXTURES / "contest_2171.html").read_text()
    client.gw.pages[f"{HOST}/contest/2171/problem/A"] = (
        FIXTURES / "problem_2171a.html"
    ).read_text()
    found = client.fetch(Target("contest", "2171"))
    assert found[0].samples and found[0].info.name.startswith("A.")
    assert found[1].error and not found[1].samples  # NOTE: its page couldn't be read


def test_an_interactive_problem(client):
    url = f"{HOST}/contest/1520/problem/F1"
    client.gw.pages[url] = (FIXTURES / "interactive_1520f1.html").read_text()
    (problem,) = client.fetch(Target("contest", "1520", "F1"))
    assert problem.info.interactive


# ┌──────────────────────────────────────────────────────────┐
# │                        Submitting                        │
# └──────────────────────────────────────────────────────────┘

TARGET = Target("contest", "4", "A")


@pytest.fixture
def submitting(client, monkeypatch):
    client.gw.pages[f"{HOST}/contest/4/submit"] = SUBMIT_PAGE
    monkeypatch.setattr(
        client, "watch", lambda target, count, single=False: [pages.Submission(id=42)]
    )
    return client


def test_submit(submitting, capsys):
    offered = []

    def choose(languages):
        offered.append(sorted(languages))
        return "91", languages["91"]

    submitting.submit(TARGET, "int main() {}", choose, filename="a.cpp")
    assert offered == [["54", "70", "91"]]
    assert submitting.gw.posted[0]["programTypeId"] == "91"
    out = capsys.readouterr().out
    assert "Submitting 4A (a.cpp) as GNU G++23 14.2 (64 bit, msys2) · tourist" in out
    assert submitting.session.last_submission == {
        "kind": "contest",
        "contest": "4",
        "problem": "A",
        "group": "",
        "submission": "42",
    }


def test_the_form_list_is_kept(submitting):
    from cf_tool import languages

    submitting.submit(TARGET, "x", lambda offered: ("54", offered["54"]))
    assert languages.known_languages()["91"] == "GNU G++23 14.2 (64 bit, msys2)"


def test_a_rejected_submission(submitting):
    submitting.gw.post_answer = (
        '<span class="error for__source">You have submitted exactly the same code before</span>'
    )
    with pytest.raises(CFError, match="exactly the same code"):
        submitting.submit(TARGET, "x", lambda offered: ("54", offered["54"]))


MY_PAGE = (FIXTURES / "submissions.html").read_text()  # NOTE: newest: 392264558, problem B


def test_a_lost_answer_is_looked_up_not_resent(submitting):
    """The submissions page tells whether the form arrived: only a submission
    newer than the newest one before the form was sent counts."""
    target = Target("contest", "2171", "B")
    submitting.gw.pages[f"{HOST}/contest/2171/submit"] = SUBMIT_PAGE
    submitting.gw.post_answer = Uncertain("No answer from Codeforces")
    older = MY_PAGE.replace("392264558", "392264000")
    seen = iter([older, MY_PAGE])  # NOTE: before the form, then after it
    submitting.gw.pages[f"{HOST}/contest/2171/my"] = lambda: next(seen)
    submitting.submit(target, "x", lambda offered: ("54", offered["54"]))
    assert len(submitting.gw.posted) == 1  # NOTE: sent once

    submitting.gw.pages[f"{HOST}/contest/2171/my"] = MY_PAGE  # NOTE: nothing new arrived
    with pytest.raises(CFError, match="didn't arrive"):
        submitting.submit(target, "x", lambda offered: ("54", offered["54"]))
    assert len(submitting.gw.posted) == 2


# ┌──────────────────────────────────────────────────────────┐
# │                        Public API                        │
# └──────────────────────────────────────────────────────────┘


def test_contests_are_cached(client):
    now = time.time()
    contests = [
        {"id": 3, "name": "Later", "phase": "BEFORE", "startTimeSeconds": now + 7200},
        {"id": 2, "name": "Soon", "phase": "BEFORE", "startTimeSeconds": now + 60},
        {"id": 1, "name": "Old", "phase": "FINISHED", "startTimeSeconds": now - 9e5},
        {"id": 4, "name": "Started since caching", "phase": "BEFORE", "startTimeSeconds": now - 60},
    ]
    calls = []

    def get_json(url):
        calls.append(url)
        return {"status": "OK", "result": contests}

    client.gw.get_json = get_json
    assert [c.name for c in client.contests()] == ["Soon", "Later"]
    assert [c.name for c in client.contests()] == ["Soon", "Later"]
    assert calls == [f"{HOST}/api/contest.list?gym=false"]  # NOTE: once


def test_api_errors(client):
    client.gw.get_json = lambda url: {"status": "FAILED", "comment": "Call limit exceeded"}
    with pytest.raises(CFError, match="Codeforces API: Call limit exceeded"):
        client.api("contest.list")


def test_api_calls_are_spaced(client, monkeypatch):
    clock = [100.0]
    slept = []
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: slept.append(seconds))
    client.gw.get_json = lambda url: {"status": "OK", "result": []}
    client.api("a")
    clock[0] += 0.5
    client.api("b")
    assert slept == [pytest.approx(1.6)]  # NOTE: 2.1 s apart


def _problem(contest_id, index, rating, *tags):
    return pages.ProblemsetProblem(contest_id, index, f"Problem {contest_id}{index}", rating, tags)


PROBLEMS = [
    _problem(1, "A", 800, "math"),
    _problem(2, "B", 1500, "dp", "greedy"),
    _problem(3, "C", 1600, "dp", "interactive"),
    _problem(4, "D", None, "dp"),
    _problem(5, "E", 1500, "dp", "*special"),
    _problem(6, "F", 1400, "dp"),
]


@pytest.mark.parametrize(
    "solved,options,expected",
    [
        (set(), {}, {"1A", "2B", "3C", "4D", "6F"}),  # NOTE: never a joke (*special)
        (set(), {"low": 1400, "high": 1600}, {"2B", "3C", "6F"}),  # NOTE: unrated out
        (set(), {"low": 1500}, {"2B"}),
        (set(), {"tags": ["dp", "!interactive"]}, {"2B", "4D", "6F"}),
        ({(2, "B"), (6, "F")}, {"tags": ["dp"], "low": 1400, "high": 1600}, {"3C"}),
        (set(), {"tags": ["*special"]}, {"5E"}),
        ({(1, "A")}, {"tags": ["math"]}, set()),
    ],
)
def test_pick_problem(solved, options, expected):
    seen = set()
    for seed in range(40):
        problem, pool = pick_problem(PROBLEMS, solved, rng=random.Random(seed), **options)
        assert pool == len(expected)
        if problem is not None:
            seen.add(problem.id)
    assert seen == expected


def test_solved_and_problemset(client, tmp_path, monkeypatch):
    monkeypatch.setattr(client_module, "API_INTERVAL", 0)
    answers = {
        "problemset.problems": {
            "problems": [
                {
                    "contestId": 4,
                    "index": "A",
                    "name": "Watermelon",
                    "rating": 800,
                    "tags": ["math"],
                }
            ]
        },
        "user.status?handle=me": [
            {"verdict": "OK", "problem": {"contestId": 4, "index": "A"}},
            {"verdict": "WRONG_ANSWER", "problem": {"contestId": 5, "index": "B"}},
        ],
    }
    client.gw.get_json = lambda url: {"status": "OK", "result": answers[url.rsplit("/api/", 1)[1]]}
    (problem,) = client.problemset()
    assert (problem.id, problem.rating, problem.tags) == ("4A", 800, ("math",))
    assert client.solved("me") == {(4, "A")}
    assert (tmp_path / "state" / "problemset.json").is_file()  # NOTE: kept for a day


def test_logout_keeps_cloudflare_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / "state")
    session = Session(
        tmp_path / "session",
        handle="tourist",
        handle_or_email="tourist",
        password="00ff",
        cookies=[
            {"name": "cf_clearance", "value": "1", "domain": "codeforces.com"},
            {"name": "X-User-Sha1", "value": "2", "domain": "codeforces.com"},
        ],
    )
    c = Client(Settings(), session)
    c.logout()
    saved = Session.load(tmp_path / "session")
    assert (saved.handle, saved.password) == ("", "")
    assert [cookie["name"] for cookie in saved.cookies] == ["cf_clearance"]
