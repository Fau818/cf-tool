"""CLI smoke tests (offline commands only), using an isolated HOME."""

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from cf_tool.cli import main


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point the XDG config/state paths (and the legacy ~/.cf) at a temp dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import cf_tool.config as config_module

    config_dir = tmp_path / ".config" / "cf"
    state_dir = tmp_path / ".local" / "state" / "cf"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "STATE_DIR", state_dir)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_dir / "config")
    monkeypatch.setattr(config_module, "SESSION_PATH", state_dir / "session")
    monkeypatch.setattr(config_module, "LEGACY_DIR", tmp_path / ".cf")
    import cf_tool.cli as cli_module
    import cf_tool.client as client_module

    monkeypatch.setattr(client_module, "SESSION_PATH", state_dir / "session")
    monkeypatch.setattr(cli_module, "_setup", lambda: _setup_isolated(tmp_path))
    return tmp_path


def _setup_isolated(home: Path):
    from cf_tool.client import Client
    from cf_tool.config import Config

    cfg = Config.load(home / ".config" / "cf" / "config")
    return cfg, Client(cfg, session_path=home / ".local" / "state" / "cf" / "session")


def write_config(home: Path, template: dict) -> None:
    config_dir = home / ".config" / "cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(json.dumps({"template": [template], "default": 0}))


PY_TEMPLATE = {
    "alias": "py",
    "lang": "31",
    "path": "",  # filled per-test
    "suffix": ["py"],
    "before_script": "",
    "script": f"{sys.executable} $%full%$",
    "after_script": "",
}


def test_help():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("config", "submit", "parse", "gen", "test", "watch", "race"):
        assert command in result.output


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0


def test_gen_and_test_flow(isolated_home, tmp_path, monkeypatch):
    template_file = tmp_path / "tpl.py"
    template_file.write_text("print(int(input()) * 2)  # by $%U%$\n")
    template = dict(PY_TEMPLATE, path=str(template_file))
    write_config(isolated_home, template)

    problem_dir = tmp_path / "cf" / "contest" / "1136" / "a"
    problem_dir.mkdir(parents=True)
    (problem_dir / "in1.txt").write_text("21\n")
    (problem_dir / "ans1.txt").write_text("42\n")
    monkeypatch.chdir(problem_dir)

    runner = CliRunner()
    result = runner.invoke(main, ["gen"])
    assert result.exit_code == 0, result.output
    assert (problem_dir / "a.py").exists()

    result = runner.invoke(main, ["test"])
    assert result.exit_code == 0, result.output
    assert "Passed #1" in result.output


def test_test_failure_exit_code(isolated_home, tmp_path, monkeypatch):
    template_file = tmp_path / "tpl.py"
    template_file.write_text("print('wrong')\n")
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(template_file)))

    problem_dir = tmp_path / "work"
    problem_dir.mkdir()
    (problem_dir / "a.py").write_text("print('wrong')\n")
    (problem_dir / "in1.txt").write_text("1\n")
    (problem_dir / "ans1.txt").write_text("right\n")
    monkeypatch.chdir(problem_dir)

    result = CliRunner().invoke(main, ["test"])
    assert result.exit_code == 0  # like the Go tool, failing samples don't fail the command
    assert "Failed #1" in result.output


def test_open_prints_url(isolated_home, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    result = CliRunner().invoke(main, ["open", "1136a"])
    assert result.exit_code == 0, result.output
    assert opened == ["https://codeforces.com/contest/1136/problem/a"]


def test_sid_without_history_errors(isolated_home):
    result = CliRunner().invoke(main, ["sid"])
    assert result.exit_code == 1
    assert "Submission ID" in result.output


def test_parse_gen_survives_a_failed_problem(isolated_home, tmp_path, monkeypatch):
    """gen-after-parse writes into every problem dir, even one whose samples failed."""
    from cf_tool import pages
    from cf_tool.client import Client
    from cf_tool.errors import CFError

    template_file = tmp_path / "tpl.py"
    template_file.write_text("print(1)\n")
    config_dir = isolated_home / ".config" / "cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(
        json.dumps(
            {"template": [dict(PY_TEMPLATE, path=str(template_file))], "gen_after_parse": True}
        )
    )

    def fake_parse_problem(self, url, path):
        from cf_tool.problem import ProblemInfo

        if url.endswith("/B"):
            raise CFError("Cannot parse sample with input 0 and output 0")
        return 1, True, ProblemInfo()

    monkeypatch.setattr(Client, "parse_problem", fake_parse_problem)
    monkeypatch.setattr(
        Client,
        "statis",
        lambda self, info: [pages.StatisInfo(i, "x", "", "", "0", "") for i in "AB"],
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["parse", "1136"])
    assert result.exit_code == 0, result.output
    assert "Failed B" in result.output
    contest = tmp_path / "cf" / "contest" / "1136"
    assert (contest / "a" / "a.py").exists() and (contest / "b" / "b.py").exists()


def test_sid_with_go_style_last_submission(isolated_home, monkeypatch):
    state_dir = isolated_home / ".local" / "state" / "cf"
    state_dir.mkdir(parents=True)
    last = {
        "problem_type": "contest",
        "contest_id": "4",
        "group_id": "",
        "problem_id": "A",
        "submission_id": "123",
        "RootPath": "/x",  # written by the Go tool
    }
    (state_dir / "session").write_text(json.dumps({"last_submission": last}))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    result = CliRunner().invoke(main, ["sid"])
    assert result.exit_code == 0, result.output
    assert opened == ["https://codeforces.com/contest/4/submission/123"]


def test_submit_missing_file_is_a_clean_error(isolated_home, tmp_path, monkeypatch):
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["submit", "-f", "nope.py", "4a"])
    assert result.exit_code == 1
    assert "Cannot read nope.py" in result.output
    assert "Traceback" not in result.output


@pytest.fixture
def fake_submit(isolated_home, tmp_path, monkeypatch):
    """cf submit up to the network: records what would be submitted where and
    the file menus (names in order); answers confirmations from
    fake_submit["answers"] and menus with fake_submit["pick"], else defaults."""
    from cf_tool import ui
    from cf_tool.client import Client

    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    record = {"submitted": [], "questions": [], "answers": [], "menus": [], "pick": None}

    def submit(self, info, lang_id, source, filename="", replace_language=None):
        record["submitted"].append((filename, info.contest_id, info.problem_id))

    def confirm(message, *, default=False):
        record["questions"].append((message, default))
        return record["answers"].pop(0) if record["answers"] else default

    def select(message, choices, *, default=None, search=False):
        files = [c[1] for c in choices if not isinstance(c, ui.Heading)]
        record["menus"].append([f.name for f in files])
        return next(f for f in files if f.name == record["pick"]) if record["pick"] else default

    monkeypatch.setattr(Client, "submit", submit)
    monkeypatch.setattr(ui, "confirm", confirm)
    monkeypatch.setattr(ui, "select", select)
    record["dir"] = work
    return record


def make_code(root: Path, *names: str) -> None:
    """Code files, each modified a second after the one before."""
    for i, name in enumerate(names):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print(1)\n")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))


def test_submit_offers_the_files_best_first(fake_submit):
    make_code(fake_submit["dir"], "2171A.py", "546D.py", "demo.py")
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == [["546D.py", "demo.py", "2171A.py"]]
    assert fake_submit["submitted"] == [("546D.py", "546", "D")]
    assert fake_submit["questions"] == []


def test_submit_another_file_from_the_menu(fake_submit):
    make_code(fake_submit["dir"], "546D.py", "demo.py")
    fake_submit["pick"] = "demo.py"
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("demo.py", "546", "D")]
    assert fake_submit["questions"] == []  # demo.py is named for no other problem


def test_submit_finds_the_contest_folder(fake_submit):
    make_code(fake_submit["dir"], str(Path("546", "D.py")), "demo.py")
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == [[str(Path("546", "D.py")), "demo.py"]]
    assert fake_submit["submitted"] == [(str(Path("546", "D.py")), "546", "D")]


def test_submit_from_inside_the_problem_folder(fake_submit, monkeypatch):
    make_code(fake_submit["dir"], str(Path("546", "D", "solution.py")), "546D.py")
    monkeypatch.chdir(fake_submit["dir"] / "546" / "D")
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    up = str(Path("..", "..", "546D.py"))
    assert fake_submit["menus"] == [[up, "solution.py"]]
    assert fake_submit["submitted"] == [(up, "546", "D")]
    assert fake_submit["questions"] == []


def test_submit_the_only_file_without_a_menu(fake_submit):
    make_code(fake_submit["dir"], str(Path("546", "D", "solution.py")))
    result = CliRunner().invoke(main, ["submit", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["menus"] == []
    assert fake_submit["submitted"] == [(str(Path("546", "D", "solution.py")), "546", "D")]


def test_submit_reads_the_target_off_the_name_after_a_yes(fake_submit):
    (fake_submit["dir"] / "546D.py").write_text("print(1)\n")
    result = CliRunner().invoke(main, ["submit"])  # no specifier at all
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("546D.py", "546", "D")]
    assert fake_submit["questions"] == [("Submit 546D.py to CONTEST 546, problem D?", True)]


def test_submit_guards_against_another_problems_file(fake_submit):
    (fake_submit["dir"] / "2171A.py").write_text("print(1)\n")
    result = CliRunner().invoke(main, ["submit", "-f", "2171A.py", "546D"])
    assert result.exit_code == 1
    assert "Not submitted" in result.output
    assert fake_submit["submitted"] == []
    message, default = fake_submit["questions"][0]
    assert "2171A.py looks like 2171A" in message and default is False


def test_submit_another_problems_file_on_purpose(fake_submit):
    (fake_submit["dir"] / "2171A.py").write_text("print(1)\n")
    fake_submit["answers"].append(True)
    result = CliRunner().invoke(main, ["submit", "-f", "2171A.py", "546D"])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("2171A.py", "546", "D")]


@pytest.mark.parametrize(
    "older,newer",
    [
        ("0.3.0a1", "0.3.0a2"),
        ("0.3.0a2", "0.3.0b1"),
        ("0.3.0b1", "v0.3.0rc1"),
        ("0.3.0-rc.1", "0.3.0"),
        ("0.3.0", "0.3.1a1"),
        ("0.3", "0.3.0.1"),
        ("v0.9.9", "1.0.0"),
    ],
)
def test_version_order(older, newer):
    from cf_tool.cli import version_key

    assert version_key(older) < version_key(newer)


def test_version_key_rejects_junk():
    from cf_tool.cli import version_key

    assert version_key("nightly") is None
    assert version_key("0.3.0") == version_key("v0.3")


class _Releases:
    def __init__(self, releases, status=200):
        self.releases, self.status_code = releases, status

    def json(self):
        return self.releases


def _upgrade_with(monkeypatch, releases, current, status=200, sent=None):
    """cf upgrade against a fake releases list; the request headers go to sent."""
    import cf_tool.cli as cli_module
    from curl_cffi import requests as curl_requests

    def get(url, timeout, headers):
        if sent is not None:
            sent.update(headers)
        return _Releases(releases, status)

    monkeypatch.setattr(cli_module, "__version__", current)
    monkeypatch.setattr(curl_requests, "get", get)
    return CliRunner().invoke(main, ["upgrade"])


RELEASES = [
    {"tag_name": "v0.3.0a2", "prerelease": True, "draft": False},
    {"tag_name": "v0.4.0", "prerelease": False, "draft": True},  # drafts never count
    {"tag_name": "v0.3.0a1", "prerelease": True, "draft": False},
]


def test_upgrade_offers_the_next_alpha_to_alpha_users(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.3.0a1")
    assert result.exit_code == 0, result.output
    assert "Latest version is v0.3.0a2" in result.output
    assert "git+https://github.com/Fau818/cf-tool@v0.3.0a2" in result.output


def test_upgrade_sends_a_user_agent(monkeypatch):
    sent = {}
    _upgrade_with(monkeypatch, RELEASES, "0.3.0a1", sent=sent)
    assert sent["User-Agent"] == "cf-tool/0.3.0a1"  # without one GitHub's API answers 403


def test_upgrade_up_to_date(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.3.0a2")
    assert "You already have the latest version" in result.output


def test_upgrade_stable_users_ignore_prereleases(monkeypatch):
    result = _upgrade_with(monkeypatch, RELEASES, "0.2.0")
    assert result.exit_code == 1
    assert "No release" in result.output


def test_upgrade_private_or_missing_repo(monkeypatch):
    result = _upgrade_with(monkeypatch, [], "0.3.0a1", status=404)
    assert result.exit_code == 1
    assert "Cannot list the releases" in result.output


def _completions(args: list[str], incomplete: str) -> list[str]:
    """What Tab offers after `cf <args> <incomplete>`."""
    from click.shell_completion import ShellComplete

    items = ShellComplete(main, {}, "cf", "_CF_COMPLETE").get_completions(args, incomplete)
    return [item.value for item in items]


def test_complete_commands():
    assert _completions([], "su") == ["submit"]


def test_complete_gen_aliases(isolated_home):
    write_config(isolated_home, dict(PY_TEMPLATE, path="tpl.py"))
    assert _completions(["gen"], "") == ["py"]


def test_complete_specifiers_from_code_files(isolated_home, tmp_path, monkeypatch):
    write_config(isolated_home, dict(PY_TEMPLATE, path="tpl.py"))
    work = tmp_path / "work"
    work.mkdir()
    for name in ("546D.py", "demo.py", "2171A.cpp", "notes.txt"):  # no template for .cpp
        (work / name).write_text("")
    monkeypatch.chdir(work)
    assert _completions(["parse"], "") == ["contest", "gym", "group", "acmsguru", "546D"]
    assert _completions(["submit"], "5") == ["546D", "5"]  # NOTE: and files: submit takes one
    assert _completions(["watch"], "a") == ["all", "acmsguru"]
    assert _completions(["clone"], "") == ["ac"]


def test_complete_file_arguments():
    from click.shell_completion import ShellComplete

    complete = ShellComplete(main, {}, "cf", "_CF_COMPLETE")
    assert [item.type for item in complete.get_completions(["submit", "-f"], "")] == ["file"]
    assert [item.type for item in complete.get_completions(["test"], "")] == ["file"]


def test_completion_script_is_only_the_script(isolated_home):
    (isolated_home / ".cf").mkdir()
    (isolated_home / ".cf" / "config").write_text("{}")  # a Go tool's config to import
    result = CliRunner().invoke(main, ["completion", "zsh"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("#compdef cf") and "_CF_COMPLETE" in result.output
    assert not (isolated_home / ".config" / "cf" / "config").exists()  # imported later


def test_completion_follows_the_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
    result = CliRunner().invoke(main, ["completion"])
    assert result.exit_code == 0 and "complete" in result.output
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    result = CliRunner().invoke(main, ["completion"])
    assert result.exit_code == 1 and "Cannot tell your shell" in result.output


@pytest.fixture
def answers(monkeypatch):
    """Scripted prompts. Each list holds the next answers for its kind of
    question: a select answer is the start of a label (None: the default).
    An unscripted question fails the test; answers["asked"] records them all."""
    from cf_tool import ui

    script = {"select": [], "confirm": [], "text": [], "asked": []}

    def select(message, choices, *, default=None, search=False):
        options = [c for c in choices if not isinstance(c, ui.Heading)]
        script["asked"].append((message, [label for label, _ in options]))
        wanted = script["select"].pop(0)
        if wanted is None:
            return options[0][1] if default is None else default
        return next(value for label, value in options if label.startswith(wanted))

    def confirm(message, *, default=False):
        script["asked"].append(message)
        return script["confirm"].pop(0)

    def text(message, **kwargs):
        script["asked"].append(message)
        return script["text"].pop(0)

    monkeypatch.setattr(ui, "select", select)
    monkeypatch.setattr(ui, "confirm", confirm)
    monkeypatch.setattr(ui, "text", text)
    monkeypatch.setattr(ui, "path", text)
    return script


def machine_with(monkeypatch, banners: dict[str, str], platform: str = "linux") -> None:
    """Toolchain detection sees only these commands, printing these banners."""
    from cf_tool import presets

    machine = presets.Machine(
        which=lambda program: f"/usr/bin/{program}" if program in banners else None,
        version=lambda program, flag: banners[program],
        platform=platform,
    )
    monkeypatch.setattr(presets, "Machine", lambda: machine)


def live_languages(monkeypatch, live: bool = True) -> None:
    from cf_tool import langs
    from cf_tool.client import Client
    from tests.test_presets import LANGUAGES

    monkeypatch.setattr(
        Client, "languages", lambda self: (LANGUAGES, True) if live else (langs.LANGS, False)
    )


def unanswered(script: dict) -> list:
    return [answer for kind in ("select", "confirm", "text") for answer in script[kind]]


def test_first_config_is_a_wizard(isolated_home, answers, monkeypatch):
    from cf_tool import presets
    from cf_tool.config import Config

    machine_with(monkeypatch, {"g++-14": "g++-14 (GCC) 14.2.0", "clang++": "clang version 18.1.3"})
    live_languages(monkeypatch)
    answers["confirm"] += [False, False]  # log in now? add another language?
    answers["select"] += ["C++", "GCC", None]  # the language, its compiler, submit as: the best
    result = CliRunner().invoke(main, ["config"])
    assert result.exit_code == 0, result.output
    assert unanswered(answers) == []
    (template,) = Config.load(isolated_home / ".config" / "cf" / "config").template
    assert (template.alias, template.lang, template.suffix) == ("cpp", "5", ["cpp", "cc", "cxx"])
    assert template.before_script == "g++-14 -std=c++20 -O2 -Wall -o $%file%$ $%full%$"
    assert Path(template.path).read_text() == presets.CPP_STARTER
    assert (
        "Added C++: GCC 14 (g++-14), submitting as GNU G++23 14.2 (64 bit, msys2)." in result.output
    )
    assert "All set" in result.output


def test_wizard_without_a_compiler(isolated_home, answers, monkeypatch):
    machine_with(monkeypatch, {})
    live_languages(monkeypatch)
    answers["confirm"] += [False, False]
    answers["select"] += ["Rust"]
    result = CliRunner().invoke(main, ["config"])
    assert result.exit_code == 0, result.output
    assert "No Rust compiler found. To get one: install Rust from rustup.rs" in result.output
    assert "No language set up yet" in result.output
    assert (isolated_home / ".config" / "cf" / "config").exists()  # NOTE: next time, the menu


def test_add_a_language_replacing_a_template(isolated_home, answers, monkeypatch):
    from cf_tool.config import Config

    write_config(isolated_home, dict(PY_TEMPLATE, path="tpl.py"))  # alias "py"
    machine_with(monkeypatch, {"python3": "Python 3.12.4", "pypy3": "Python 3.10.14 (75b3de)"})
    live_languages(monkeypatch)
    answers["select"] += ["Add a language", "Python", "PyPy", None, "Done"]
    answers["confirm"] += [True]  # replace the "py" template
    result = CliRunner().invoke(main, ["config"])
    assert result.exit_code == 0, result.output
    assert unanswered(answers) == []
    (template,) = Config.load(isolated_home / ".config" / "cf" / "config").template
    assert (template.script, template.lang) == ("pypy3 $%full%$", "11")  # PyPy 3.10 64bit


def test_clang_only_mac(isolated_home, answers, monkeypatch):
    machine_with(monkeypatch, {"clang++": "Apple clang version 17.0.0"}, "darwin")
    live_languages(monkeypatch, live=False)
    answers["confirm"] += [False, False]
    answers["select"] += ["C++", None]
    result = CliRunner().invoke(main, ["config"])
    assert result.exit_code == 0, result.output
    assert "Apple clang 17 (clang++) has no bits/stdc++.h, so cf-tool adds one." in result.output
    assert "For GCC, which Codeforces uses: brew install gcc" in result.output
    assert "built-in language list" in result.output
    assert (isolated_home / ".config" / "cf" / "include" / "bits" / "stdc++.h").is_file()


def test_pick_language_by_family_first(answers):
    from cf_tool import cli
    from tests.test_presets import LANGUAGES

    answers["select"] += ["Java", None]
    assert cli._pick_language(LANGUAGES) == "13"  # Java 21 64bit
    (family_question, families), (version_question, versions) = answers["asked"]
    assert families[:4] == ["C++  (5)", "Python  (5)", "Java  (2)", "Kotlin  (2)"]
    assert families[-1] == "JavaScript  (1)"  # NOTE: families without a preset follow, A to Z
    assert version_question == "Submit Java as:" and versions == ["Java 21 64bit", "Java 8 32bit"]


OFFERED = {
    "54": "GNU G++17 7.3.0",
    "91": "GNU G++23 14.2 (64 bit, msys2)",
    "4": "Free Pascal 3.2.2",
    "51": "PascalABC.NET 3.8.3",
}


def _template_config(tmp_path, **template):
    from cf_tool.config import CodeTemplate, Config

    cfg = Config(template=[CodeTemplate(**template)], _path=tmp_path / "config")
    return cfg, cfg.template[0]


def test_replace_a_retired_language(tmp_path, answers):
    from cf_tool import cli
    from cf_tool.config import Config

    cfg, template = _template_config(tmp_path, alias="cpp", lang="89", suffix=["cpp"])
    answers["select"] += [None]  # submit as: the best
    answers["confirm"] += [True]  # and keep it in the template
    assert cli._replace_language(cfg, template, "89", OFFERED) == "91"
    assert answers["asked"] == [
        (
            "The submit form doesn't offer GNU G++20 13.2 (64 bit, winlibs). Submit as:",
            ["GNU G++23 14.2 (64 bit, msys2)", "GNU G++17 7.3.0", "Don't submit"],
        ),
        'Use GNU G++23 14.2 (64 bit, msys2) in your "cpp" template from now on?',
    ]
    assert Config.load(tmp_path / "config").template[0].lang == "91"


def test_replace_a_language_this_time_only(tmp_path, answers):
    from cf_tool import cli

    cfg, template = _template_config(tmp_path, alias="cpp", lang="89", suffix=["cpp"])
    answers["select"] += ["GNU G++17"]
    answers["confirm"] += [False]
    assert cli._replace_language(cfg, template, "89", OFFERED) == "54"
    assert template.lang == "89" and not (tmp_path / "config").exists()


def test_replace_a_language_declined(tmp_path, answers):
    from cf_tool import cli
    from cf_tool.errors import CFError

    cfg, template = _template_config(tmp_path, alias="cpp", lang="89", suffix=["cpp"])
    answers["select"] += ["Don't submit"]
    with pytest.raises(CFError, match="Not submitted"):
        cli._replace_language(cfg, template, "89", OFFERED)


def test_replace_a_language_without_a_preset(tmp_path, answers):
    from cf_tool import cli
    from cf_tool.errors import CFError

    cfg, template = _template_config(tmp_path, alias="pas", lang="3", suffix=["pas"])
    answers["select"] += ["Free Pascal"]
    answers["confirm"] += [False]
    assert cli._replace_language(cfg, template, "3", OFFERED) == "4"
    assert answers["asked"][0][1] == ["PascalABC.NET 3.8.3", "Free Pascal 3.2.2", "Don't submit"]
    cfg, template = _template_config(tmp_path, alias="hs", lang="12", suffix=["hs"])
    with pytest.raises(CFError, match="doesn't offer Haskell GHC 8.10.1, nor anything like it"):
        cli._replace_language(cfg, template, "12", OFFERED)


def _test_folder(isolated_home, tmp_path, monkeypatch) -> Path:
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.py").write_text("print(int(input()) * 2)\n")
    for i, (inp, ans) in enumerate([("1\n", "2\n"), ("2\n", "5\n")], start=1):
        (work / f"in{i}.txt").write_text(inp)
        (work / f"ans{i}.txt").write_text(ans)
    monkeypatch.chdir(work)
    return work


def test_cf_test_picks_samples_by_number(isolated_home, tmp_path, monkeypatch):
    _test_folder(isolated_home, tmp_path, monkeypatch)
    result = CliRunner().invoke(main, ["test", "1"])
    assert result.exit_code == 0, result.output
    assert "Passed #1" in result.output and "#2" not in result.output
    result = CliRunner().invoke(main, ["test", "a.py", "b.py"])
    assert result.exit_code == 1 and "One code file at a time" in result.output


def test_cf_test_add(isolated_home, tmp_path, monkeypatch):
    import cf_tool.cli as cli_module

    work = _test_folder(isolated_home, tmp_path, monkeypatch)
    typed = iter(["21\n", "42\n"])
    monkeypatch.setattr(cli_module, "_read_until_eof", lambda: next(typed))
    result = CliRunner().invoke(main, ["test", "--add"])
    assert result.exit_code == 0, result.output
    assert "Added sample 3: in3.txt and ans3.txt" in result.output
    assert "Passed #3" in result.output and "#1" not in result.output
    assert (work / "ans3.txt").read_text() == "42\n"


def test_cf_test_add_needs_an_input(isolated_home, tmp_path, monkeypatch):
    import cf_tool.cli as cli_module

    _test_folder(isolated_home, tmp_path, monkeypatch)
    monkeypatch.setattr(cli_module, "_read_until_eof", lambda: "\n")
    result = CliRunner().invoke(main, ["test", "--add"])
    assert result.exit_code == 1 and "No input: no sample added" in result.output


def test_cf_stress_finds_the_solution_itself(isolated_home, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    write_config(isolated_home, dict(PY_TEMPLATE, path=str(tmp_path / "tpl.py")))
    (work / "gen.py").write_text("import sys\nprint(int(sys.argv[1]) % 10)\n")
    (work / "brute.py").write_text("print(int(input()) * 2)\n")
    (work / "sol.py").write_text("n = int(input())\nprint(n * 2 + (n == 3))\n")
    monkeypatch.chdir(work)
    result = CliRunner().invoke(main, ["stress", "gen.py", "brute.py", "-n", "10"])
    assert result.exit_code == 0, result.output
    assert "Wrong answer on the test from seed 3" in result.output
    assert (work / "in1.txt").read_text() == "3\n"


def test_cf_contests(isolated_home, tmp_path, monkeypatch):
    import time

    from cf_tool.client import Client
    from cf_tool.pages import Contest

    soon = Contest(2278, "Codeforces Round 1131 (Div. 3)", int(time.time()) + 3600, 8100, "BEFORE")
    monkeypatch.setattr(Client, "contests", lambda self: [soon])
    ics = tmp_path / "cf.ics"
    result = CliRunner().invoke(main, ["contests", "--ics", str(ics)])
    assert result.exit_code == 0, result.output
    assert "Codeforces Round 1131" in result.output and "2:15" in result.output
    assert "UID:contest-2278@codeforces.com" in ics.read_text()
    monkeypatch.setattr(Client, "contests", lambda self: [])
    assert "No contest is scheduled" in CliRunner().invoke(main, ["contests"]).output


@pytest.mark.parametrize(
    "value,expected",
    [("1600", (1600, 1600)), ("1400-1800", (1400, 1800)), ("1800-1400", (1400, 1800))],
)
def test_rating_range(value, expected):
    from cf_tool.cli import _rating_range

    assert _rating_range(None, None, value) == expected


def test_rating_range_rejects_words():
    import click

    from cf_tool.cli import _rating_range

    with pytest.raises(click.BadParameter):
        _rating_range(None, None, "hard")


def test_cf_pick(isolated_home, monkeypatch):
    from cf_tool.client import Client
    from cf_tool.pages import ProblemsetProblem

    problems = [
        ProblemsetProblem(4, "A", "Watermelon", 800, ("math", "brute force")),
        ProblemsetProblem(1, "A", "Theatre Square", 1000, ("math",)),
    ]
    monkeypatch.setattr(Client, "problemset", lambda self: problems)
    monkeypatch.setattr(Client, "solved", lambda self, handle: {(1, "A")})
    result = CliRunner().invoke(main, ["pick", "-t", "math", "--handle", "me"])
    assert result.exit_code == 0, result.output
    assert "4A  Watermelon  rating 800" in result.output
    assert "https://codeforces.com/contest/4/problem/A  (one of 1 to pick from)" in result.output
    result = CliRunner().invoke(main, ["pick", "-r", "3000", "--handle", "me"])
    assert result.exit_code == 1 and "No problem you haven't solved matches" in result.output


def test_version_as_cp_editor_reads_it():
    import re

    output = CliRunner().invoke(main, ["--version"]).output
    version = re.search(r"(?<=v)\d+\.\d+\.\d+", output).group()  # NOTE: CP Editor's regex
    assert version.split(".")[0] == "0"  # NOTE: so it submits with: cf submit 546 D <file>


def test_submit_as_cp_editor_calls_it(fake_submit):
    make_code(fake_submit["dir"], "sol.py", "other.py")
    full_path = str(fake_submit["dir"] / "sol.py")
    result = CliRunner().invoke(main, ["submit", "546", "D", full_path])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [(full_path, "546", "D")]
    assert fake_submit["menus"] == [] and fake_submit["questions"] == []


def test_submit_with_the_file_as_an_argument(fake_submit):
    make_code(fake_submit["dir"], "546D.py", "demo.py")
    result = CliRunner().invoke(main, ["submit", "demo.py", "546D"])  # NOTE: once silently ignored
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"] == [("demo.py", "546", "D")]
    url = "https://codeforces.com/contest/546/problem/D"
    result = CliRunner().invoke(main, ["submit", "-f", "demo.py", url])
    assert result.exit_code == 0, result.output
    assert fake_submit["submitted"][-1] == ("demo.py", "546", "D")
    result = CliRunner().invoke(main, ["submit", "-f", "demo.py", "546D.py", "546D"])
    assert result.exit_code == 1 and "Give the code file once" in result.output


def test_a_question_without_anyone_to_ask_takes_the_default(monkeypatch):
    from cf_tool import ui

    monkeypatch.setattr(ui, "interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(EOFError))
    assert ui.confirm("Submit it?", default=True) is True
    assert ui.confirm("Submit it anyway?", default=False) is False
