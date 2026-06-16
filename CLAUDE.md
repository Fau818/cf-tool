# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cf-tool is a Python CLI for competitive programming on Codeforces — a faithful port of the
Go-based [xalanq/cf-tool](https://github.com/xalanq/cf-tool). Fidelity to the original's UX
is a design goal: directory layout, specifier/path inference rules, template scripts, and
file naming (`in{i}.txt` / `ans{i}.txt`) all match the Go tool. When changing behavior,
check the Go originals first (reference copies in `.go_ref/`, gitignored).

- Distribution name: `cf-tool` (PyPI), package: `cf_tool`, CLI command: `cf`

## Development Setup

```bash
uv venv && uv pip install ".[dev]"

uv pip install .   # NON-editable install: rebuild after code changes

pytest             # offline unit tests (live tests are opt-in: pytest -m live)
black cf_tool/ tests/
flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool/
```

## Architecture

```
cf_tool/
├── cli.py        # Click commands; each body is thin (resolve Info -> one call)
├── args.py       # parse_args(): specifier/path -> Info (port of cmd/args.go).
│                 #   Explicit args win; cwd fills blanks; >=6-digit id => gym;
│                 #   acmsguru rewrites contest->99999. Info builds all URLs/paths.
├── config.py     # XDG config/state paths + ~/.cf migration; config JSON (same
│                 #   schema as Go: template/default/gen_after_parse/host/...)
├── client.py     # session state ($XDG_STATE_HOME/cf/session) + network ops:
│                 #   login tiers, parse, statis, race, submit, watch, pull, clone
├── http.py       # curl_cffi Transport (Chrome TLS impersonation), retry,
│                 #   Cloudflare challenge detection -> CloudflareChallengeError
├── browser.py    # DrissionPage: solve challenges / login past Turnstile
│                 #   (headless first, visible last); exports cookies+UA
├── crypto.py     # AES-GCM password obfuscation, byte-compatible with Go tool
├── pages.py      # ALL HTML/JSON parsing (regex + bs4): handle, csrf, samples,
│                 #   problems table, languages select, submissions, countdown
├── templates.py  # placeholder substitution, code-file detection (by template
│                 #   suffix, interactive pick on ambiguity), cf gen
├── judge.py      # cf test: before_script/script/after_script, in/ans pairs,
│                 #   per-line-trim comparison, time+peak-RSS display
├── langs.py      # static language-id fallback (live list parsed from submit page)
├── ui.py         # Rich console output + questionary prompts (select/text/
│                 #   path/confirm) with a plain typed-input fallback for no-TTY
└── errors.py     # CFError hierarchy
```

### Key invariants

- **Login tiers** (client.py `login()`): 0 cookies still valid → 1 plain HTTP POST
  /enter (ftaa/bfaa flow) → 2 headless browser → 3 visible browser. Any page fetched
  via `_authed_body()` auto-relogins once when the handle marker is missing.
- **cf_clearance is bound to the User-Agent**: cookies exported from the browser must
  travel together with its UA (`_adopt_browser_session`). Never set one without the other.
- **Directory model**: `<root>/<type folder>/<contestID>/<problemID>/`, root folder
  name configurable (default `cf`). If no root is found among cwd ancestors, commands
  create `./cf/...` under cwd (Go behavior).
- **No hardcoded compilers**: test/submit are language-agnostic through template
  suffix matching and the three scripts. Don't add per-language logic.
- **Parsing stays in pages.py** with fixture-style unit tests in tests/test_pages.py —
  when Codeforces markup changes, fix it there only.

## Testing against real Codeforces

Unit tests are offline. For live verification use old practice problems (e.g.
problemset 4A / contest 1136), throttle polling to >=1s, and vary submitted source
(timestamp comment) to dodge the duplicate-submission rejection. Never automate
against a rated running contest.
