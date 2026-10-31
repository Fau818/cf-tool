# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cf-tool is a Python CLI for Codeforces: `cf get` sets up a contest's problems (folders,
samples, starter code), `cf test` builds and runs your code on them, `cf submit` submits
and shows the verdict. It began as a port of the Go [xalanq/cf-tool](https://github.com/xalanq/cf-tool),
but since 1.0.0 it follows its own model (no templates or scripts, one folder per
problem); don't reintroduce the Go tool's ways for fidelity's sake.

- Distribution name: `cf-tool-cli` (PyPI refuses `cf-tool` as too similar to `cftool`),
  package: `cf_tool`, CLI command: `cf`, repository: GitHub Fau818/cf-tool. Pushing a
  `v<version>` tag publishes to PyPI (`.github/workflows/release.yml`, trusted
  publishing); the GitHub release (`gh release create`, notes from CHANGELOG.md) is made
  by hand.
- Versions are PEP 440 (`1.0.0`, `1.1.0a1`), tags `v<version>`; bump `pyproject.toml` and
  `cf_tool/__init__.py` together, run `uv lock`, and add a CHANGELOG.md entry. `cf
  upgrade` reads GitHub releases (pre-releases only for users already on one).
- Supported Python: 3.10+ (CI runs 3.10–3.13 on Linux, 3.13 on macOS/Windows;
  Windows is experimental).

## Development Setup

```bash
uv sync --extra dev          # .venv from uv.lock (CI uses --locked: re-run `uv lock`
                             #   after changing dependencies)
uv run pytest                # offline unit tests (live tests are opt-in: -m live)
uv run pytest -m live        # tests/test_live.py: public pages vs the parsers (no login)
uv run pytest -m toolchain   # every language's starter, built with this machine's compilers
uv run black cf_tool/ tests/
uv run flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool/ tests/
uv tool install --reinstall .   # refresh the global `cf` (a copy: re-run after changes)
```

## Architecture

```
cf_tool/
├── cli/            # Click commands, grouped: problems (get race new listen pick
│                   #   problems contests open), testing (test stress), submitting
│                   #   (submit status pull clone), account (login logout), setup
│                   #   (config langs doctor upgrade), configure (cf config's menu:
│                   #   the first choice of each list is the recommended one,
│                   #   pre-selected), completion. Bodies stay thin;
│                   #   common.py: cf_command (CFError -> a red line; CF_DEBUG=1 adds the
│                   #   traceback), settings()/client() loaded once, finding the problem,
│                   #   the first-run language question, logging in on the spot.
│                   #   0.3's names are hidden aliases (ALIASES, stand, sid).
├── paths.py        # XDG folders (read as paths.X at call time: tests repoint them)
├── settings.py     # config.toml via tomlkit (comments survive edits); every key
│                   #   optional; migrate() turns 0.3's JSON config into it once
├── languages.py    # the language table (cpp c py java kt rs go) + config.toml's own:
│                   #   toolchain detection, build/run commands, -std from the submit
│                   #   language, the Codeforces language (choose_submit), starter
│                   #   code (render), Codeforces' language names (ext_of, LANGS)
├── workspace.py    # Target (contest/gym/group/acmsguru + URLs), parse_target,
│                   #   problem folders (.cf-problem.json, here(), locate()), tests
│                   #   (tests/<name>.in/.ans, 0.3's in<i>.txt), which code file
│                   #   (find_code/pick_code: the menu), read_source
├── build.py        # Program: cached builds in $XDG_CACHE_HOME/cf/build/<key>/
├── process.py      # running programs: own process group, tree killed on timeout,
│                   #   output cap, CPU time + peak memory from wait4; interact()
├── judge.py        # comparison (words by default), verdicts, checker, interactor,
│                   #   remembered results (cf submit warns), watch
├── stress.py  listen.py  doctor.py  views.py  ui.py  errors.py
└── codeforces/     # everything that talks to Codeforces:
    ├── client.py   #   fetch (a contest's /problems page in one request), submit
    │               #   (POST once), watch, pull, clone, API (2.1 s apart), languages
    ├── gateway.py  #   the way in: HTTP first, browser only on a challenge; tiered login
    ├── http.py     #   curl_cffi transport; 5xx/429 are errors (GET retried), one
    │               #   request at a time, cookies as full records
    ├── browser.py  #   DrissionPage: pass checks / log in through the real form
    ├── pages.py    #   ALL HTML/JSON parsing (regex + bs4)
    ├── session.py  #   $XDG_STATE_HOME/cf/session (0600)
    └── crypto.py   #   the saved password's AES-GCM obfuscation
```

### Key invariants

- **No hardcoded compilers outside languages.py**: test/submit/stress stay
  language-agnostic through `languages.setup()` and `build.Program`. A language is named
  by its extension; one setting per extension.
- **Local matches the judge**: C++'s `-std` comes from the Codeforces language it is
  submitted as (`cpp_standard`; the compiler is asked which spellings it takes, once per
  version, in STATE_DIR/tools.json); the 256 MB stack (macOS linker flag, Linux
  `RLIMIT_STACK`, MinGW `--stack`); outputs compared word by word like Codeforces'
  default checker, the statement's error/letter-case rules applied (`check_for`).
- **Builds never land in the user's folders**: the cache key covers source, commands,
  compiler banner and path; a C/C++ source with `#include "..."` is rebuilt every time.
- **Processes**: every run in its own process group; on a timeout the whole tree dies and
  nothing waits on its pipes afterwards; Ctrl-C kills the child (it is outside the
  terminal's group).
- **Problem identity lives in `.cf-problem.json`** (written by get, listen, pick --get);
  folder names are only a fallback (0.3's `cf/contest/2050/a`, `2050/a`, loose `2050A.cpp`).
- **Submitting the wrong file costs penalty**: with several candidates the menu always
  asks (best guess pre-selected, newest first) — never auto-pick; a target read off a
  file name, or a file named for another problem, needs a confirmation
  (`cli/submitting._submit_target`). Helpers (`gen.*`, `brute.*`, `checker.*`,
  `interactor.*`) are never candidates unless named.
- **A submission is POSTed once** (`http.post` never retries; `Uncertain` -> look on /my
  for a submission newer than the newest one before the POST; a challenge on the page a
  POST redirected to is `Uncertain` too).
- **No prompt without a terminal** (`ui.interactive()` false: CP Editor, pipes): the submit
  path, the file menu and the first-run language question decide or fail with a message,
  never wait on stdin.
- **Login tiers** (gateway.py `login()`): 1 plain HTTP GET+POST /enter (keeps Cloudflare
  cookies, drops old login ones) → 2 headless browser → 3 browser window. Since Oct 2026
  tier 1 never gets through (a check page stands in front of /enter), so tier 2 is the
  usual way in: a check page there is no reason for a warning.
  `LoginRejected` and `BrowserUnavailable` stop the climb — never open a window for those.
  `get_authed()` re-logs in once when the handle marker is missing; a 5xx page is an
  error, never "logged out".
- **Page fetches**: HTTP; on a challenge, solve it in a browser (headless, then window)
  and **merge** the cookies; once logged in, adopt only Cloudflare's cookies (the fresh
  profile's session is anonymous). Browser work, logins and session saves share one lock;
  requests run one at a time (curl_cffi writes the whole jar back after each request).
- **Gate markers**: Cloudflare's interstitial = `<title>Just a moment` / `_cf_chl_opt`;
  Codeforces' own Turnstile gate = `/data/turnstile`; its check in front of /enter (when
  cf_clearance is valid) = `Your browser is being checked`. Never use `challenge-platform`:
  every normal page embeds Cloudflare's `/cdn-cgi/challenge-platform/scripts/jsd/` script.
- **cf_clearance is bound to the User-Agent and IP**: cookies exported from the browser
  travel with its UA (`Gateway._adopt`), and the browser uses the configured proxy.
- **Cookies are full records** (name/value/domain/path/expires), adopted per name across
  domains; never flatten them to `{name: value}`.
- **One palette** (`ui.ACCENT/SUCCESS/WARNING/ERROR/MUTED`): plain color names in styles
  ("green", "bold cyan", "dim") are mapped to it by `ui.styled` (ui.line does it); messages
  go through `ui.success/info/warn/error` (✓ › ! ✗). Menu rows that show a setting are
  `ui.row(label, value, note)`: select() lines them up and colors the parts.
- **Prompts raise `ui.Canceled`** on Esc or Ctrl-C (cf_command prints "Canceled."); the
  settings menu catches it to go back a level.
- **Text output is never Rich markup** (and `Console(emoji=False)`): `ui.*` print
  literally; mixed styles via `ui.line()` or `Text` (sample I/O like `a[i]`, `[/]`, `:x:`
  must survive). Machine-read output (`cf config --path`) goes through `click.echo`.
- **CP Editor calls cf** (its src/Extensions/CFTool.cpp): it reads `v<x.y.z>` from
  `cf --version` (keep the `v`), runs `cf submit -f <file> <url>` from major version 1
  (`cf submit <contest> <problem> <file>` for 0.x, still understood), and reads
  `status: <verdict>` from stdout (unboxed when not a terminal). Keep all three working,
  and no prompts in that path.
- **questionary quirks** (`ui.select`): it paints the default as "selected" (reverse
  video) — cleared; Meta-Enter submits the hidden input line as "" — Esc is bound to
  cancel and non-item answers count as canceled. Off a terminal, menus are numbered from
  1 and Enter takes the default.
- **Parsing stays in codeforces/pages.py** with fixture-style unit tests in
  tests/test_pages.py — when Codeforces markup changes, fix it there only.
  `tests/fixtures/` holds pages trimmed from the live site (2026-10-12/31).
- **Language ids**: `languages.LANGS` is only a fallback; the submit form's list is the
  truth (remembered in STATE_DIR/languages.json each time it is read).
- **Language names**: the /my table and API say `C++20 (GCC 13-64)`, the submit menu
  `GNU G++20 ...`, old data `GNU C++17`; `languages.ext_of` must map all of them.

## Testing against real Codeforces

Unit tests are offline (browser and gateway logic run against fakes; the CLI tests use a
fake client). `tests/test_live.py` (`-m live`) fetches public pages over plain HTTP and
runs the parsers on them; a Cloudflare check on the connection skips a test. For live
verification beyond that use an isolated HOME/XDG_* so the real session is not touched,
old practice problems (e.g. problemset 4A / contest 1136), throttle polling to >=1s, and
vary submitted source (timestamp comment) to dodge the duplicate-submission rejection.
Never automate against a rated running contest. Chrome cannot start inside Claude Code's
sandbox, so browser tiers need the user to run the command.
