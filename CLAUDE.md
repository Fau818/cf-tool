# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cf-tool is a Python CLI for competitive programming on Codeforces — a faithful port of the
Go-based [xalanq/cf-tool](https://github.com/xalanq/cf-tool). Fidelity to the original's UX
is a design goal: directory layout, specifier/path inference rules, template scripts, and
file naming (`in{i}.txt` / `ans{i}.txt`) all match the Go tool. When changing behavior,
check the Go originals first (reference copies in `.go_ref/`, gitignored).

- Distribution name: `cf-tool`, package: `cf_tool`, CLI command: `cf`. Published on
  GitHub (Fau818/cf-tool), not PyPI — the PyPI name is unclaimed, so never tell users
  to `pip install cf-tool`. Install: `uv tool install git+https://github.com/Fau818/cf-tool`.
- Versions are PEP 440 (`0.3.0a1`), tags `v<version>`; bump `pyproject.toml` and
  `cf_tool/__init__.py` together and add a CHANGELOG.md entry. `cf upgrade` reads
  GitHub releases (pre-releases only for users already on one).
- Supported Python: 3.10+ (CI runs 3.10–3.13 on Linux, 3.13 on macOS/Windows;
  Windows is experimental).

## Development Setup

```bash
uv sync --extra dev          # .venv from uv.lock (CI uses --locked: re-run `uv lock`
                             #   after changing dependencies)
uv run pytest                # offline unit tests (live tests are opt-in: -m live)
uv run black cf_tool/ tests/
uv run flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool/ tests/
uv tool install --reinstall .   # refresh the global `cf` (a copy: re-run after changes)
```

## Architecture

```
cf_tool/
├── cli.py        # Click commands; each body is thin (resolve Info -> one call).
│                 #   cf_command turns CFError/OSError into a red line
│                 #   (CF_DEBUG=1 also prints the traceback)
├── args.py       # parse_args(): specifier/path -> Info (port of cmd/args.go).
│                 #   Explicit args win; cwd fills blanks; >=6-digit id => gym;
│                 #   acmsguru rewrites contest->99999. Info builds all URLs/paths.
├── config.py     # XDG paths, atomic writes, config JSON (same schema as Go:
│                 #   template/default/gen_after_parse/host/...); first-run
│                 #   import of the Go tool's ~/.cf (copied, never moved)
├── session.py    # persisted login state ($XDG_STATE_HOME/cf/session, 0600);
│                 #   reads current / old-Python / Go-tool formats
├── gateway.py    # the way in: HTTP first, browser only on a challenge, and the
│                 #   tiered login; single-flight lock for threads
├── client.py     # Codeforces operations: parse, statis, race, submit, watch,
│                 #   pull, clone, languages (all network via Gateway)
├── http.py       # curl_cffi Transport (Chrome TLS impersonation), retry,
│                 #   challenge detection, cookie jar as persistable dicts
├── browser.py    # DrissionPage: pass checks / log in through the real form
│                 #   (one run per call; headless or windowed is the caller's say)
├── views.py      # Rich renderables: submission table/panel, problems, diff
├── crypto.py     # AES-GCM password obfuscation, byte-compatible with Go tool
├── pages.py      # ALL HTML/JSON parsing (regex + bs4): handle, csrf, samples,
│                 #   problems table, languages, submissions, countdown, gates
├── codefiles.py  # which code file: candidates by template suffix (+ the target's
│                 #   folders 546/, 546/D/, 546D/ for submit, and the problem's files
│                 #   around them when cwd is inside); the problem's files first,
│                 #   newest first, with edit times; source decoding
├── templates.py  # placeholder substitution, cf gen
├── judge.py      # cf test: before_script/script/after_script, in/ans pairs,
│                 #   per-line-trim comparison, CPU time + peak RSS, Go's splitCmd
├── langs.py      # static language-id fallback; language name -> file extension
├── ui.py         # markup-free console lines, spinner, questionary prompts with
│                 #   a plain typed-input fallback for no-TTY
└── errors.py     # CFError hierarchy (LoginRejected / BrowserUnavailable stop
                  #   the login escalation)
```

### Key invariants

- **Login tiers** (gateway.py `login()`): 1 plain HTTP GET+POST /enter (Go's
  ftaa/bfaa flow; keeps Cloudflare cookies, drops old login ones) → 2 headless browser
  → 3 browser window. `LoginRejected` (Codeforces refused the credentials) and
  `BrowserUnavailable` (no Chrome) stop the climb — never open a window for those.
  `get_authed()` re-logs in once when the handle marker is missing.
- **Page fetches**: HTTP; on a challenge, solve it in a browser (headless, then window)
  and **merge** the cookies (`replace=False`) — replacing would log the user out.
  Browser work, logins and session saves share one lock; a solve/login done by one
  thread is reused by the others, and a failure is not retried within the run.
- **Gate markers**: Cloudflare's interstitial = `<title>Just a moment` / `_cf_chl_opt`;
  Codeforces' own Turnstile gate = `/data/turnstile`. Never use `challenge-platform`:
  every normal page embeds Cloudflare's `/cdn-cgi/challenge-platform/scripts/jsd/` bot
  script (that marker once made every browser run time out).
- **cf_clearance is bound to the User-Agent and IP**: cookies exported from the browser
  travel with its UA (`Gateway._adopt`), and the browser uses the configured proxy.
- **Cookies are full records** (name/value/domain/path/expires), adopted per name across
  domains; never flatten them to `{name: value}` (duplicates, lost expiry).
- **Text output is never Rich markup**: `ui.*` print literally; mixed styles via
  `ui.line()` or `Text` (sample I/O like `a[i]` or `[/]` must survive).
- **Submitting the wrong file costs penalty**: with several candidates codefiles always
  asks (the user wants the menu, best guess pre-selected) — never auto-pick one; a
  target read off a file name, or a file named for another problem than the target,
  needs a confirmation (`cli._submit_target`). Keep the folder search bounded: the
  target's folders below cwd, and from inside them only the problem's own files above.
- **questionary quirks** (`ui.select`): it paints the default as "selected" (reverse
  video) — cleared; prompt_toolkit's Meta-Enter (Esc then Enter) submits the menu's
  hidden input line as "" — Esc is bound to cancel and non-item answers count as
  canceled.
- **Directory model**: `<root>/<type folder>/<contestID>/<problemID>/`, root folder
  name configurable (default `cf`). If no root is found among cwd ancestors, commands
  create `./cf/...` under cwd (Go behavior).
- **No hardcoded compilers**: test/submit are language-agnostic through template
  suffix matching and the three scripts. Don't add per-language logic.
- **Parsing stays in pages.py** with fixture-style unit tests in tests/test_pages.py —
  when Codeforces markup changes, fix it there only. `tests/fixtures/` holds pages
  trimmed from the live site (2026-10-12); refresh them when markup drifts.
- **Language names**: the /my table and API say `C++20 (GCC 13-64)`, the submit menu
  `GNU G++20 ...`, old data `GNU C++17`; `langs.ext_of` must map all of them.

## Testing against real Codeforces

Unit tests are offline (browser and gateway logic run against fakes). For live
verification use an isolated XDG_CONFIG_HOME/XDG_STATE_HOME so the real session is not
touched, old practice problems (e.g. problemset 4A / contest 1136), throttle polling to
>=1s, and vary submitted source (timestamp comment) to dodge the duplicate-submission
rejection. Never automate against a rated running contest. Chrome cannot start inside
Claude Code's sandbox, so browser tiers need the user to run the command.
