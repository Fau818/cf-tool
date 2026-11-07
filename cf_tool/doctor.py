"""cf doctor: check the setup and say how to fix what's wrong, changing
nothing. It checks, in this order:
- the settings file
- each language that matters (the one for starter code, those set in
  config.toml): its compiler, its starter file, what it submits as
- the login, over plain HTTP (no browser)
- Chrome, which logging in needs"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from cf_tool import languages
from cf_tool.codeforces import browser, pages
from cf_tool.errors import CFError, CloudflareChallengeError
from cf_tool.settings import Settings

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass(frozen=True)
class Finding:
    level: str  # OK, WARN or ERROR
    text: str
    fix: str = ""  # how to put it right


def check_language(
    key: str,
    settings: Settings,
    offered: Mapping[str, str],
    live: bool,
    machine: languages.Machine | None = None,
) -> list[Finding]:
    """What's wrong with one language; all good: one OK. Errors: no
    compiler, a missing starter file; a warning: Codeforces doesn't offer
    the language it is set to submit as (checked when logged in)."""
    name = languages.display_name(key)
    try:
        setup = languages.setup(key, settings, offered=offered, machine=machine)
    except CFError as e:
        return [Finding(ERROR, f"{name}: {e}")]
    findings = []
    try:
        _, origin = languages.starter(key, settings)
    except CFError as e:
        findings.append(Finding(ERROR, f"{name}: {e}", f"fix template in [{key}] of config.toml"))
        origin = ""
    if setup.submit is None:
        wanted = settings.language_settings(key).submit or name
        level = WARN if live else OK
        findings.append(
            Finding(
                level,
                f"{name}: Codeforces doesn't offer {wanted}"
                + ("" if live else " (not checked: not logged in)"),
                "cf submit lets you pick another" if live else "",
            )
        )
    if not findings:
        starter = "the built-in starter" if origin == "built-in" else origin
        unchecked = "" if live else " (the list isn't checked: not logged in)"
        findings.append(
            Finding(
                OK,
                f"{name}: {setup.tool}, submits as {setup.submit[1] if setup.submit else '?'}, "
                f"starts from {starter}{unchecked}",
            )
        )
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
    if client.can_log_in:
        finding = Finding(
            WARN, "The saved login has expired", "the next command that needs it logs in again"
        )
        return finding, False
    return Finding(WARN, "Not logged in", "cf login (cf submit also asks when it needs to)"), False


def check_chrome(find: Callable[[], "str | None"] = browser.find_chrome) -> Finding:
    """Whether Chrome is installed: OK, or a warning."""
    where = find()
    if where:
        return Finding(OK, f"Chrome: {where}")
    return Finding(
        WARN,
        "Chrome not found: logging in needs it",
        "install Google Chrome or Chromium",
    )


def run(settings: Settings, client) -> list[Finding]:
    """Every finding, in the order cf doctor prints them."""
    findings = [Finding(WARN, warning, "fix it in config.toml") for warning in settings.warnings]
    login, logged_in = check_login(client)
    offered, live = client.languages() if logged_in else (languages.known_languages(), False)
    keys = list(dict.fromkeys([settings.language or "cpp", *settings.languages]))
    if not settings.language:
        findings.append(Finding(OK, "No language picked yet: cf get asks for one"))
    for key in keys:
        findings += check_language(key, settings, offered, live)
    return findings + [login, check_chrome()]
