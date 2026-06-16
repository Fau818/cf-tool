# cf-tool

Codeforces command-line tool — a Python port of [xalanq/cf-tool](https://github.com/xalanq/cf-tool)
that keeps the original's UX (directory layout, file detection, template scripts) while
handling today's Cloudflare-protected Codeforces.

## Highlights

- **Same workflow as the original**: `cf race` → code → `cf test` → `cf submit`, with
  contest/problem inferred from your directory and the file to submit auto-detected by
  template suffix.
- **Background login**: tries plain HTTP first (curl_cffi with Chrome TLS fingerprint),
  falls back to a headless browser, and only opens a visible browser window if
  Cloudflare absolutely demands it. Credentials are stored encrypted; expired sessions
  re-login silently.
- **Language-agnostic testing** via template scripts (`before_script` / `script` /
  `after_script`) — no hardcoded compilers.
- **Interactive prompts**: `cf config` and the file/template pickers use arrow-key
  menus with type-to-filter (e.g. filtering the language list); piped/non-TTY use
  falls back to plain numbered input.

## Install

```bash
uv venv && uv pip install .
# or: pip install .
```

Requires Python 3.13+ and a Chrome/Chromium install (only used when Cloudflare
requires a real browser).

## Quick start

```bash
cf config          # arrow-key menu: login, add a template (alias, suffixes, scripts), ...
cf race 1136       # countdown -> opens pages -> parses samples into ~/cf/contest/1136/
cd ~/cf/contest/1136/a
cf gen             # instantiate your default template as a.cpp
cf test            # run before_script, feed in1.txt..., compare with ans1.txt...
cf submit          # auto-detects a.cpp, submits, live-watches the verdict
```

## Commands

```
cf config                      configure login, templates, host, proxy, folder names
cf submit [-f file] [spec...]  submit code (auto-detect file/problem)
cf list [spec...]              problems of a contest with stats
cf parse [spec...]             download samples (in1.txt / ans1.txt)
cf gen [alias]                 generate code from a template
cf test [file]                 test against all in{i}.txt/ans{i}.txt pairs
cf watch [all] [spec...]       live table of your submissions
cf open / stand / sid          open problem / standings / submission in browser
cf race [spec...]              countdown, then open + parse the contest
cf pull [ac] [spec...]         download your submitted codes
cf clone [ac] [handle]         download all codes of a user
cf upgrade                     check for a newer release
```

A *specifier* is anything useful: `1136`, `1136a`, `a`, `gym 100001`, a full
problem/contest/group URL, etc. Without one, the contest/problem is inferred from the
current directory (layout `<root>/<contest|gym|group|acmsguru>/<contestID>/<problemID>/`,
root folder name defaults to `cf`).

### Template placeholders

In code (`cf gen`): `$%U%$` handle, `$%Y%$ $%M%$ $%D%$ $%h%$ $%m%$ $%s%$` date/time.
In scripts (`cf test`): `$%path%$`, `$%full%$` (a.cpp), `$%file%$` (a), `$%rand%$`.

Example C++ template config: before `g++ -O2 -o $%file%$ $%full%$`, script
`./$%file%$`, after `rm $%file%$`.

## Files

- `$XDG_CONFIG_HOME/cf/config` (default `~/.config/cf/config`) — templates, default
  template, host/proxy, folder names (JSON)
- `$XDG_STATE_HOME/cf/session` (default `~/.local/state/cf/session`) — handle,
  AES-GCM-encrypted password, cookies, last submission
- A legacy `~/.cf` directory is migrated automatically on first run

## Development

```bash
uv pip install ".[dev]"
pytest            # offline unit tests
black cf_tool/ tests/ && flake8 cf_tool/
```
