"""Session persistence across the three on-disk formats, and the cookie jar."""

import json
import os
import stat
import time

from cf_tool.http import Transport
from cf_tool.session import Session

DOMAIN = "codeforces.com"

GO_SESSION = {
    "cookies": {
        "codeforces.com": {
            "codeforces.com;/;JSESSIONID": {
                "Name": "JSESSIONID",
                "Value": "ABC",
                "Domain": "codeforces.com",
                "Path": "/",
                "Secure": False,
                "HttpOnly": True,
                "Persistent": False,
                "HostOnly": True,
                "Expires": "0001-01-01T00:00:00Z",
            },
            "codeforces.com;/;X-User-Sha1": {
                "Name": "X-User-Sha1",
                "Value": "remember",
                "Domain": "codeforces.com",
                "Path": "/",
                "Secure": False,
                "Persistent": True,
                "HostOnly": False,
                "Expires": "2099-01-02T03:04:05.123456789+08:00",
            },
            "codeforces.com;/;old": {
                "Name": "old",
                "Value": "x",
                "Domain": "codeforces.com",
                "Path": "/",
                "Persistent": True,
                "HostOnly": True,
                "Expires": "2001-01-01T00:00:00Z",
            },
        }
    },
    "handle": "tourist",
    "handle_or_email": "tourist",
    "password": "00ff",
    "ftaa": "f",
    "bfaa": "b",
    "last_submission": {
        "problem_type": "contest",
        "contest_id": "1",
        "group_id": "",
        "problem_id": "A",
        "submission_id": "5",
        "RootPath": "/x/cf/contest",
    },
}


def test_go_session_carries_over(tmp_path):
    path = tmp_path / "session"
    path.write_text(json.dumps(GO_SESSION))
    session = Session.load(path, DOMAIN)

    assert (session.handle, session.handle_or_email, session.password) == ("tourist",) * 2 + (
        "00ff",
    )
    assert session.last_submission == {
        "problem_type": "contest",
        "contest_id": "1",
        "group_id": "",
        "problem_id": "A",
        "submission_id": "5",
    }  # Go's RootPath dropped
    by_name = {c["name"]: c for c in session.cookies}
    assert by_name["JSESSIONID"]["domain"] == "codeforces.com"  # host-only
    assert by_name["JSESSIONID"]["expires"] is None
    assert by_name["X-User-Sha1"]["domain"] == ".codeforces.com"  # domain cookie
    assert by_name["X-User-Sha1"]["expires"] > time.time()

    # and the transport accepts them (the Go jar used to crash every request)
    transport = Transport(cookies=session.cookies)
    names = sorted(c["name"] for c in transport.export_cookies())
    assert names == ["JSESSIONID", "X-User-Sha1"]  # the expired one is dropped


def test_python_02_flat_cookies(tmp_path):
    path = tmp_path / "session"
    path.write_text(
        json.dumps({"handle": "h", "cookies": {"JSESSIONID": "1", "cf_clearance": "2"}})
    )
    session = Session.load(path, DOMAIN)
    assert {(c["name"], c["value"], c["domain"]) for c in session.cookies} == {
        ("JSESSIONID", "1", DOMAIN),
        ("cf_clearance", "2", DOMAIN),
    }


def test_round_trip_is_private(tmp_path):
    path = tmp_path / "state" / "session"
    session = Session(path, handle="h", cookies=[{"name": "a", "value": "1", "domain": DOMAIN}])
    session.save()
    if os.name == "posix":  # Windows has no such permission bits
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = Session.load(path, DOMAIN)
    assert loaded.handle == "h"
    assert loaded.cookies[0]["name"] == "a"


def test_unreadable_session_starts_fresh(tmp_path, capsys):
    path = tmp_path / "session"
    path.write_text("{not json")
    session = Session.load(path, DOMAIN)
    assert session.handle == "" and session.cookies == []
    assert "Ignoring unreadable session" in capsys.readouterr().out


def test_missing_session(tmp_path):
    assert Session.load(tmp_path / "nope", DOMAIN).cookies == []


# ------------------------------------------------------------- the jar


def jar_cookie(name, value, domain=DOMAIN):
    return {"name": name, "value": value, "domain": domain, "path": "/"}


def test_adopt_replaces_by_name_across_domains():
    transport = Transport(
        cookies=[jar_cookie("cf_clearance", "old"), jar_cookie("JSESSIONID", "keep")]
    )
    transport.adopt_cookies([jar_cookie("cf_clearance", "new", ".codeforces.com")])
    values = {(c["name"], c["value"]) for c in transport.export_cookies()}
    assert values == {("cf_clearance", "new"), ("JSESSIONID", "keep")}


def test_clear_keeps_selected():
    transport = Transport(cookies=[jar_cookie("cf_clearance", "1"), jar_cookie("JSESSIONID", "2")])
    transport.clear_cookies(keep=lambda name: name.startswith("cf_"))
    assert [c["name"] for c in transport.export_cookies()] == ["cf_clearance"]
    transport.clear_cookies()
    assert transport.export_cookies() == []


def test_user_agent_is_remembered():
    transport = Transport(user_agent="UA/1")
    assert transport.user_agent == "UA/1"
    transport.set_user_agent("")
    assert transport.user_agent == "UA/1"
