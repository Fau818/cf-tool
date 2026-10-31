"""Client operations against a fake gateway: the language check on submit,
and what parse keeps for cf test."""

from pathlib import Path

import pytest

from cf_tool import pages
from cf_tool.args import Info
from cf_tool.client import Client
from cf_tool.config import Config
from cf_tool.errors import CFError

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
    """Serves the submit form and accepts the POST."""

    def __init__(self, page: str = SUBMIT_PAGE) -> None:
        self.page, self.posted = page, []

    def get_authed(self, url: str) -> str:
        return self.page

    def form_tokens(self) -> tuple[str, str]:
        return "ftaa", "bfaa"

    def post(self, url: str, data: dict) -> str:
        self.posted.append(data)
        return SUBMITTED

    def save(self) -> None:
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    client = Client(Config(_path=tmp_path / "config"), session_path=tmp_path / "session")
    client.gw = FakeGateway()
    monkeypatch.setattr(client, "watch", lambda info, count, line: [pages.Submission(id=42)])
    return client


INFO = Info(problem_type="contest", contest_id="4", problem_id="A")


def test_submit_names_the_language(client, capsys):
    client.submit(INFO, "91", "int main() {}")
    assert client.gw.posted[0]["programTypeId"] == "91"
    assert "Language: GNU G++23 14.2 (64 bit, msys2)" in capsys.readouterr().out
    assert client.session.last_submission["submission_id"] == "42"


def test_a_language_the_form_lacks_is_replaced(client):
    asked = []

    def replace(lang_id, offered):
        asked.append((lang_id, sorted(offered)))
        return "91"

    client.submit(INFO, "89", "int main() {}", replace_language=replace)
    assert asked == [("89", ["54", "70", "91"])]
    assert client.gw.posted[0]["programTypeId"] == "91"


def test_a_language_the_form_lacks_without_a_replacer(client):
    with pytest.raises(CFError, match="doesn't offer language 89"):
        client.submit(INFO, "89", "int main() {}")
    assert client.gw.posted == []  # NOTE: nothing was sent


def test_a_form_without_a_language_list_is_not_checked(client):
    client.gw.page = SUBMIT_PAGE.split("<select")[0]
    client.submit(INFO, "89", "int main() {}")
    assert client.gw.posted[0]["programTypeId"] == "89"


PROBLEM_PAGE = (Path(__file__).parent / "fixtures" / "problem_2171a.html").read_text()


def test_parse_problem_keeps_what_cf_test_needs(client, tmp_path):
    from cf_tool.problem import ProblemInfo

    client.gw.page = PROBLEM_PAGE
    url = "https://codeforces.com/contest/2171/problem/A"
    count, standard_io, _ = client.parse_problem(url, tmp_path / "a")
    assert (count, standard_io) == (1, True)
    assert ProblemInfo.load(tmp_path / "a") == ProblemInfo(
        name="A. Shizuku Hoshikawa and Farm Legs",
        url=url,
        time_limit=1.0,
        memory_limit=256,
        interactive=False,
        cases=[([0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5])],
    )


def test_parse_warns_about_an_interactive_problem(client, tmp_path, monkeypatch, capsys):
    client.gw.page = (Path(__file__).parent / "fixtures" / "interactive_1520f1.html").read_text()
    info = Info(problem_type="contest", contest_id="1520", problem_id="F1", root_path=tmp_path)
    client.parse(info)
    assert "Interactive: cf test can't judge it." in capsys.readouterr().out


def test_contests_are_cached(client, tmp_path, monkeypatch):
    import time

    import cf_tool.config as config_module

    monkeypatch.setattr(config_module, "STATE_DIR", tmp_path / "state")
    now = time.time()
    contests = [
        {
            "id": 3,
            "name": "Later",
            "phase": "BEFORE",
            "startTimeSeconds": now + 7200,
            "durationSeconds": 7200,
        },
        {
            "id": 2,
            "name": "Soon",
            "phase": "BEFORE",
            "startTimeSeconds": now + 60,
            "durationSeconds": 7200,
        },
        {
            "id": 1,
            "name": "Old",
            "phase": "FINISHED",
            "startTimeSeconds": now - 9e5,
            "durationSeconds": 7200,
        },
        {"id": 4, "name": "Started since caching", "phase": "BEFORE", "startTimeSeconds": now - 60},
    ]
    calls = []

    def get_json(url):
        calls.append(url)
        return {"status": "OK", "result": contests}

    client.gw.get_json = get_json
    assert [c.name for c in client.contests()] == ["Soon", "Later"]
    assert [c.name for c in client.contests()] == ["Soon", "Later"]
    assert calls == ["https://codeforces.com/api/contest.list?gym=false"]  # NOTE: once


def test_api_errors(client):
    client.gw.get_json = lambda url: {"status": "FAILED", "comment": "Call limit exceeded"}
    with pytest.raises(CFError, match="Codeforces API: Call limit exceeded"):
        client.api("contest.list")


def _problem(contest_id, index, rating, *tags):
    from cf_tool.pages import ProblemsetProblem

    return ProblemsetProblem(contest_id, index, f"Problem {contest_id}{index}", rating, tags)


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
    import random

    from cf_tool.client import pick_problem

    seen = set()
    for seed in range(40):
        problem, pool = pick_problem(PROBLEMS, solved, rng=random.Random(seed), **options)
        assert pool == len(expected)
        if problem is not None:
            seen.add(problem.id)
    assert seen == expected


def test_api_calls_are_spaced(client, monkeypatch):
    import cf_tool.client as client_module

    clock = [100.0]
    slept = []
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: slept.append(seconds))
    client.gw.get_json = lambda url: {"status": "OK", "result": []}
    client.api("a")
    clock[0] += 0.5
    client.api("b")
    assert slept == [pytest.approx(1.6)]  # NOTE: 2.1 s apart


def test_solved_and_problemset(client, tmp_path, monkeypatch):
    import cf_tool.config as config_module

    monkeypatch.setattr(config_module, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr("cf_tool.client.API_INTERVAL", 0)
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
