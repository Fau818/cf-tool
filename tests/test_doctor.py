"""cf doctor: each check against fakes, and the command's output and exit code."""

from types import SimpleNamespace

import pytest

import cf_tool.config as config_module
from cf_tool import doctor
from cf_tool.config import CodeTemplate
from cf_tool.doctor import ERROR, OK, WARN, Finding
from cf_tool.errors import CFError, CloudflareChallengeError

LIVE = {"91": "GNU G++23 14.2 (64 bit, msys2)", "70": "PyPy 3.10 (7.3.15, 64bit)"}


def cpp(tmp_path, **changes) -> CodeTemplate:
    template_file = tmp_path / "template.cpp"
    template_file.write_text("int main() {}\n")
    fields = dict(
        alias="cpp",
        lang="91",
        path=str(template_file),
        suffix=["cpp"],
        before_script="g++-14 -std=c++20 -O2 -o $%file%$ $%full%$",
        script="./$%file%$",
        after_script="rm $%file%$",
    )
    return CodeTemplate(**{**fields, **changes})


def installed(*programs: str):
    return lambda program: f"/usr/bin/{program}" if program in programs else None


def test_a_ready_template(tmp_path):
    findings = doctor.check_template(cpp(tmp_path), LIVE, True, installed("g++-14", "rm"))
    assert findings == [Finding(OK, '"cpp": ready, submits as GNU G++23 14.2 (64 bit, msys2)')]


def test_a_template_checked_without_login(tmp_path):
    (finding,) = doctor.check_template(cpp(tmp_path), LIVE, False, installed("g++-14", "rm"))
    assert finding.text.endswith("(not checked: not logged in)")


def test_a_broken_template(tmp_path):
    template = cpp(tmp_path, path=str(tmp_path / "gone.cpp"), lang="89")
    findings = doctor.check_template(template, LIVE, True, installed("rm"), platform="darwin")
    assert [(f.level, f.text, f.fix) for f in findings] == [
        (
            ERROR,
            f'"cpp": no template file at {tmp_path / "gone.cpp"}',
            "cf config, then Add a language, sets it up again",
        ),
        (ERROR, '"cpp": g++-14 is not installed', "brew install gcc"),
        (ERROR, '"cpp": Codeforces no longer offers language 89', "cf submit offers a replacement"),
    ]


def test_interpreters_are_checked_too(tmp_path):
    template = cpp(
        tmp_path,
        alias="py",
        lang="70",
        suffix=["py"],
        before_script="",
        script="pypy3 $%full%$",
        after_script="",
    )
    (finding,) = doctor.check_template(template, LIVE, True, installed())
    assert finding.text == '"py": pypy3 is not installed'


def test_a_missing_shim(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "cf")
    shim = tmp_path / "cf" / "include"
    template = cpp(tmp_path, before_script=f"clang++ -I{shim} -o $%file%$ $%full%$")
    findings = doctor.check_template(template, LIVE, True, installed("clang++", "rm"))
    assert [f.text for f in findings] == ['"cpp": cf-tool\'s bits/stdc++.h is missing']


def fake_client(home=None, error=None, saved_login=False):
    def get(url, browser_fallback=True):
        if error:
            raise error
        return home

    session = SimpleNamespace(
        handle_or_email="me" if saved_login else "", password="x" if saved_login else ""
    )
    return SimpleNamespace(
        host="https://codeforces.com",
        gw=SimpleNamespace(get=get),
        session=session,
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
        (fake_client("<html/>"), ERROR, "Not logged in", False),
    ],
)
def test_check_login(client, level, text, logged_in):
    finding, ok = doctor.check_login(client)
    assert (finding.level, finding.text, ok) == (level, text, logged_in)


def test_check_chrome():
    assert doctor.check_chrome(lambda: "/opt/chrome").level == OK
    assert doctor.check_chrome(lambda: None).level == WARN


def test_doctor_command(monkeypatch):
    from click.testing import CliRunner

    import cf_tool.cli as cli_module
    from cf_tool.cli import main

    findings = [Finding(OK, "all good"), Finding(ERROR, "broken", "fix it like this")]
    monkeypatch.setattr(cli_module, "_setup", lambda: (None, None))
    monkeypatch.setattr(doctor, "run", lambda cfg, client: findings)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "✓ all good" in result.output and "✗ broken\n    fix it like this" in result.output


def test_doctor_reports_a_broken_config(monkeypatch):
    from click.testing import CliRunner

    import cf_tool.cli as cli_module
    from cf_tool.cli import main

    def broken():
        raise CFError("Config ~/.config/cf/config is broken (bad JSON). Fix or delete it.")

    monkeypatch.setattr(cli_module, "_setup", broken)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1 and "✗ Config ~/.config/cf/config is broken" in result.output
