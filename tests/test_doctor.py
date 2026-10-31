"""cf doctor's checks: languages, the login, Chrome."""

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from cf_tool import doctor, paths
from cf_tool.doctor import ERROR, OK, WARN, Finding
from cf_tool.errors import CFError, CloudflareChallengeError
from cf_tool.languages import Machine
from cf_tool.settings import Settings

LIVE = {"91": "GNU G++23 14.2 (64 bit, msys2)", "70": "PyPy 3.10 (7.3.15, 64bit)"}
GCC = Machine(
    which=lambda p: f"/bin/{p}" if p == "g++-14" else None,
    version=lambda p, f: "g++-14 (GCC) 14.2.0",
)
NOTHING = Machine(which=lambda p: None, version=lambda p, f: "", platform="linux")


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")


def settings_with(text: str) -> Settings:
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return Settings.load()


def test_a_ready_language():
    (finding,) = doctor.check_language("cpp", Settings(), LIVE, True, GCC)
    assert finding.level == OK
    assert finding.text == (
        "C++: GCC 14 (g++-14), submits as GNU G++23 14.2 (64 bit, msys2), "
        "starts from the built-in starter"
    )


def test_no_compiler():
    (finding,) = doctor.check_language("cpp", Settings(), LIVE, True, NOTHING)
    assert finding.level == ERROR and "No C++ compiler" in finding.text


def test_a_missing_starter_file(tmp_path):
    settings = settings_with(f'[cpp]\ntemplate = "{tmp_path / "gone.cpp"}"\n')
    findings = doctor.check_language("cpp", settings, LIVE, True, GCC)
    assert [f.level for f in findings] == [ERROR] and "doesn't exist" in findings[0].text


def test_a_language_codeforces_no_longer_offers():
    settings = settings_with('[cpp]\nsubmit = "54"\n')
    (finding,) = doctor.check_language("cpp", settings, LIVE, True, GCC)
    assert finding.level == WARN and "Codeforces doesn't offer 54" in finding.text
    (unchecked,) = doctor.check_language("cpp", settings, LIVE, False, GCC)
    assert unchecked.level == OK and "not checked" in unchecked.text


def fake_client(home=None, error=None, saved_login=False):
    def get(url, browser_fallback=True):
        if error:
            raise error
        return home

    return SimpleNamespace(
        host="https://codeforces.com",
        gw=SimpleNamespace(get=get),
        can_log_in=saved_login,
        languages=lambda: (LIVE, True),
    )


@pytest.mark.parametrize(
    "client,level,text,logged_in",
    [
        (fake_client('var handle = "tourist";'), OK, "Logged in as tourist", True),
        (
            fake_client(error=CloudflareChallengeError()),
            WARN,
            "Cloudflare is checking this connection right now",
            False,
        ),
        (
            fake_client(error=CFError("timed out")),
            WARN,
            "Cannot reach https://codeforces.com: timed out",
            False,
        ),
        (fake_client("<html/>", saved_login=True), WARN, "The saved login has expired", False),
        (fake_client("<html/>"), WARN, "Not logged in", False),
    ],
)
def test_check_login(client, level, text, logged_in):
    finding, ok = doctor.check_login(client)
    assert (finding.level, finding.text, ok) == (level, text, logged_in)


def test_check_chrome():
    assert doctor.check_chrome(lambda: "/opt/chrome").level == OK
    assert doctor.check_chrome(lambda: None).level == WARN


def test_the_doctor_command(monkeypatch):
    from cf_tool.cli import common, main

    findings = [Finding(OK, "all good"), Finding(ERROR, "broken", "fix it like this")]
    common.reset()
    monkeypatch.setattr(common, "client", lambda: None)
    monkeypatch.setattr(doctor, "run", lambda settings, client: findings)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "✓ all good" in result.output and "✗ broken\n    fix it like this" in result.output


def test_a_broken_settings_file_is_a_finding():
    from cf_tool.cli import common, main

    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text("language = \n")
    common.reset()
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1 and "isn't valid TOML" in result.output
