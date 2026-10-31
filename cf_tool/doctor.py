"""`cf doctor`: check the setup and say how to fix what's wrong, changing
nothing. It checks, in this order:
- each template: its file, the programs its scripts run, its language
- the login, over plain HTTP (no browser)
- Chrome, needed when Cloudflare checks the login"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cf_tool import browser, judge, langs, pages, presets, templates
from cf_tool.config import CodeTemplate, Config
from cf_tool.errors import CFError, CloudflareChallengeError

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass(frozen=True)
class Finding:
    level: str  # OK, WARN or ERROR
    text: str
    fix: str = ""  # how to put it right


def _programs(template: CodeTemplate) -> list[str]:
    """The installed programs a template's scripts start (not the one it builds)."""
    subs = {"path": "", "full": f"a.{(template.suffix or ['txt'])[0]}", "file": "a", "rand": "x"}
    found = []
    for script in (template.before_script, template.script, template.after_script):
        words = judge.split_cmd(templates.substitute_script(script, **subs))
        if words and not any(sep in words[0] for sep in "/\\"):  # NOTE: ./a was just built
            found.append(words[0])
    return list(dict.fromkeys(found))


def check_template(
    template: CodeTemplate,
    languages: dict[str, str],
    live: bool,
    which: Callable[[str], "str | None"] = shutil.which,
    platform: str = sys.platform,
) -> list[Finding]:
    """What's wrong with one template; all good: one OK. Errors:
    - its template file is missing
    - a program its scripts start isn't installed (with how to install it)
    - Codeforces doesn't offer its language (checked when logged in)
    - cf-tool's bits/stdc++.h, which it compiles with, is missing"""
    name = f'"{template.alias}"'
    preset = presets.family_of(template, languages)
    findings = []
    if not Path(template.path).expanduser().is_file():
        findings.append(
            Finding(
                ERROR,
                f"{name}: no template file at {template.path or '(none set)'}",
                "cf config, then Add a language, sets it up again",
            )
        )
    for program in _programs(template):
        if which(program) is None:
            hint = preset.install_hint(platform) if preset else f"install {program}"
            findings.append(Finding(ERROR, f"{name}: {program} is not installed", hint))
    if live and template.lang not in languages:
        findings.append(
            Finding(
                ERROR,
                f"{name}: Codeforces no longer offers language {template.lang}",
                "cf submit offers a replacement",
            )
        )
    shim = presets.shim_folder()
    if str(shim) in template.before_script and not (shim / "bits" / "stdc++.h").is_file():
        findings.append(
            Finding(
                ERROR,
                f"{name}: cf-tool's bits/stdc++.h is missing",
                "cf config, then Add a language, C++, writes it again",
            )
        )
    if not findings:
        language = languages.get(template.lang) or f"language {template.lang}"
        unchecked = "" if live else " (not checked: not logged in)"
        findings.append(Finding(OK, f"{name}: ready, submits as {language}{unchecked}"))
    return findings


def check_login(client) -> tuple[Finding, bool]:
    """Whether Codeforces sees the saved session logged in: (finding, logged in).
    - logged in: OK
    - Cloudflare checks this connection, or it fails: a warning
    - a saved login that expired: a warning (cf logs in again by itself)
    - no saved login: an error"""
    try:
        body = client.gw.get(client.host, browser_fallback=False)
    except CloudflareChallengeError:
        finding = Finding(
            WARN,
            "Cloudflare is checking this connection right now",
            "cf passes the check in a browser when it has to",
        )
        return finding, False
    except CFError as e:
        return Finding(WARN, f"Cannot reach {client.host}: {e}"), False
    handle = pages.find_handle(body)
    if handle:
        return Finding(OK, f"Logged in as {handle}"), True
    if client.session.handle_or_email and client.session.password:
        finding = Finding(
            WARN, "The saved login has expired", "the next command that needs it logs in again"
        )
        return finding, False
    return Finding(ERROR, "Not logged in", "cf config, then Login"), False


def check_chrome(find: Callable[[], "str | None"] = browser.find_chrome) -> Finding:
    """Whether Chrome is installed: OK, or a warning."""
    where = find()
    if where:
        return Finding(OK, f"Chrome: {where}")
    return Finding(
        WARN,
        "Chrome not found: logging in fails when Cloudflare checks it",
        "install Google Chrome or Chromium",
    )


def run(cfg: Config, client) -> list[Finding]:
    """Every finding, in the order cf doctor prints them."""
    login, logged_in = check_login(client)
    languages, live = client.languages() if logged_in else (langs.LANGS, False)
    findings = []
    if not cfg.template:
        findings.append(Finding(ERROR, "No language set up", "cf config"))
    for template in cfg.template:
        findings += check_template(template, languages, live)
    return findings + [login, check_chrome()]
