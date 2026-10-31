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
