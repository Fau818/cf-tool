"""The login session on disk, and the transport's cookie jar."""

import json
import os
import stat
import time

import pytest

from cf_tool.codeforces import http
from cf_tool.codeforces.http import ServerError, Transport, Uncertain
from cf_tool.codeforces.session import Session
from cf_tool.errors import CFError, CloudflareChallengeError

DOMAIN = "codeforces.com"


def test_round_trip_is_private(tmp_path):
    path = tmp_path / "state" / "session"
    session = Session(
        path,
        handle="h",
        cookies=[{"name": "a", "value": "1", "domain": DOMAIN}],
        last_submission={
            "kind": "contest",
            "contest": "4",
            "problem": "A",
            "group": "",
            "submission": "9",
        },
    )
    session.save()
    if os.name == "posix":  # NOTE: Windows has no such permission bits
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = Session.load(path)
    assert loaded.handle == "h" and loaded.cookies[0]["name"] == "a"
    assert loaded.last_submission == session.last_submission


def test_a_session_saved_by_cf_tool_03(tmp_path):
    path = tmp_path / "session"
    old = {
        "handle": "tourist",
        "cookies": [
            {"name": "X-User-Sha1", "value": "x", "domain": ".codeforces.com", "expires": 4e9},
            {"name": "broken"},  # NOTE: no domain: dropped
        ],
        "last_submission": {
            "problem_type": "gym",
            "contest_id": "100001",
            "group_id": "",
            "problem_id": "B",
            "submission_id": "7",
        },
    }
    path.write_text(json.dumps(old))
    session = Session.load(path)
    assert [c["name"] for c in session.cookies] == ["X-User-Sha1"]
    assert session.last_submission == {
        "kind": "gym",
        "contest": "100001",
        "problem": "B",
        "group": "",
        "submission": "7",
    }


def test_unreadable_session_starts_fresh(tmp_path, capsys):
    path = tmp_path / "session"
    path.write_text("{not json")
    session = Session.load(path)
    assert session.handle == "" and session.cookies == []
    assert "Ignoring the unreadable session" in capsys.readouterr().out


def test_missing_session(tmp_path):
    assert Session.load(tmp_path / "nope").cookies == []


# ┌──────────────────────────────────────────────────────────┐
# │                         The jar                          │
# └──────────────────────────────────────────────────────────┘


def jar_cookie(name, value, domain=DOMAIN, expires=None):
    return {"name": name, "value": value, "domain": domain, "path": "/", "expires": expires}


def test_expired_cookies_are_dropped():
    transport = Transport(
        cookies=[jar_cookie("old", "1", expires=time.time() - 60), jar_cookie("new", "2")]
    )
    assert [c["name"] for c in transport.export_cookies()] == ["new"]


def test_adopt_replaces_by_name_across_domains():
    transport = Transport(
        cookies=[jar_cookie("cf_clearance", "old"), jar_cookie("JSESSIONID", "keep")]
    )
    transport.adopt_cookies([jar_cookie("cf_clearance", "new", ".codeforces.com")])
    values = {(c["name"], c["value"]) for c in transport.export_cookies()}
    assert values == {("cf_clearance", "new"), ("JSESSIONID", "keep")}
    assert transport.has_cookie("JSESSIONID") and not transport.has_cookie("X-User-Sha1")


def test_clear_keeps_selected():
    transport = Transport(cookies=[jar_cookie("cf_clearance", "1"), jar_cookie("JSESSIONID", "2")])
    transport.clear_cookies(keep=http.is_cloudflare_cookie)
    assert [c["name"] for c in transport.export_cookies()] == ["cf_clearance"]
    transport.clear_cookies()
    assert transport.export_cookies() == []


def test_user_agent_is_remembered():
    transport = Transport(user_agent="UA/1")
    assert transport.user_agent == "UA/1"
    transport.set_user_agent("")
    assert transport.user_agent == "UA/1"


# ┌──────────────────────────────────────────────────────────┐
# │                  Errors are not content                  │
# └──────────────────────────────────────────────────────────┘


class Answer:
    def __init__(self, status, text="", headers=None, url=""):
        self.status_code, self.text, self.headers, self.url = status, text, headers or {}, url


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(http, "BACKOFF", 0.0)


def fake_session(transport, monkeypatch, answers):
    calls = []

    def request(method, url, **kwargs):
        calls.append(method)
        answer = answers[min(len(calls), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(transport._session, "request", request)
    return calls


def test_a_server_error_is_retried(monkeypatch, no_wait):
    transport = Transport()
    calls = fake_session(transport, monkeypatch, [Answer(502), Answer(200, "page")])
    assert transport.get("https://codeforces.com/").text == "page"
    assert calls == ["GET", "GET"]


def test_a_lasting_server_error_is_an_error(monkeypatch, no_wait):
    transport = Transport()
    fake_session(transport, monkeypatch, [Answer(503)])
    with pytest.raises(ServerError, match="a server error"):
        transport.get("https://codeforces.com/")
    fake_session(transport, monkeypatch, [Answer(429)])
    with pytest.raises(ServerError, match="too many requests"):
        transport.get("https://codeforces.com/")


def test_a_challenge_is_raised(monkeypatch, no_wait):
    transport = Transport()
    fake_session(transport, monkeypatch, [Answer(403, "", {"cf-mitigated": "challenge"})])
    with pytest.raises(CloudflareChallengeError):
        transport.get("https://codeforces.com/enter")


def test_a_post_is_sent_once(monkeypatch, no_wait):
    from curl_cffi.requests.exceptions import Timeout

    transport = Transport()
    calls = fake_session(transport, monkeypatch, [Timeout("timed out")])
    with pytest.raises(Uncertain, match="No answer from Codeforces"):
        transport.post("https://codeforces.com/contest/4/submit", data={})
    assert calls == ["POST"]
    calls = fake_session(transport, monkeypatch, [Answer(502)])
    with pytest.raises(Uncertain):
        transport.post("https://codeforces.com/contest/4/submit", data={})
    assert calls == ["POST"]
    assert issubclass(Uncertain, CFError)


def test_a_check_after_the_form_was_sent_is_uncertain(monkeypatch, no_wait):
    # NOTE: the POST got through; Cloudflare checked the page it redirected to
    transport = Transport()
    challenge = {"cf-mitigated": "challenge"}
    url = "https://codeforces.com/contest/4/submit?csrf_token=x"
    fake_session(
        transport, monkeypatch, [Answer(403, "", challenge, "https://codeforces.com/contest/4/my")]
    )
    with pytest.raises(Uncertain, match="after the form"):
        transport.post(url, data={})
    fake_session(transport, monkeypatch, [Answer(403, "", challenge, url)])
    with pytest.raises(CloudflareChallengeError):  # NOTE: stopped before Codeforces
        transport.post(url, data={})
