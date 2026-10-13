# cf-tool

[![CI](https://github.com/Fau818/cf-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Fau818/cf-tool/actions/workflows/ci.yml)

A Codeforces command-line tool — a Python port of
[xalanq/cf-tool](https://github.com/xalanq/cf-tool) that keeps the original's workflow
(directory layout, template scripts, `cf race` → `cf test` → `cf submit`) and works with
today's Cloudflare-protected Codeforces, logging in from the terminal.

> [!WARNING]
> **Early alpha: very early days.** This is cf-tool's first public alpha (`0.3.0a1`).
> Expect bugs (above all around Cloudflare and logging in), rough edges, and behavior
> that may still change between releases. Try it on a practice problem before relying on
> it in a rated contest, and please report what breaks in
> [Issues](https://github.com/Fau818/cf-tool/issues).

## Highlights

- **Command-line login.** Plain HTTP first; if Cloudflare guards the login page, a
  background (headless) browser does it; a browser window opens only when Cloudflare
  insists on a human check. A wrong password stops right away. Credentials are stored
  encrypted, and an expired session logs in again by itself.
- **Finds the file you mean.** `cf submit 546D` lists the problem's files first
  (`546D.cpp`, `546/D/solution.cpp`, the `cf gen` file in `cf/contest/546/d/`), newest
  first with their edit times, and asks again before sending a file named for a
  different problem.
- **Local testing** with your own compile/run scripts (no hardcoded compilers): per
  sample CPU time and memory; a failed sample shows its output next to the answer.
- **Pleasant prompts.** Arrow keys, a number key per item, type-to-filter for long lists
  (like the languages); plain numbered input when not on a terminal.

## Install

Requires Python 3.10+ and Google Chrome or Chromium (used only to get past Cloudflare
at login; afterwards everything runs over plain HTTP).

```bash
uv tool install git+https://github.com/Fau818/cf-tool
# or: pipx install git+https://github.com/Fau818/cf-tool
```

To update later, `cf upgrade` tells you the command for the newest release.

## Quick start

```bash
cf config          # menu: login, add a template (alias, suffixes, scripts), ...
cf race 1136       # countdown -> opens pages -> parses samples into ./cf/contest/1136/
cd cf/contest/1136/a
cf gen             # your default template as a.cpp
cf test            # run your scripts on in1.txt..., compare with ans1.txt...
cf submit          # submits a.cpp, then shows the verdict live
```

## Commands

```
cf config                      configure login, templates, host, proxy, folder names
cf submit [-f file] [spec...]  submit code (picks the file, infers contest/problem)
cf list [spec...]              problems of a contest with stats
cf parse [spec...]             download samples (in1.txt / ans1.txt)
cf gen [alias]                 generate code from a template
cf test [file]                 test against all in{i}.txt/ans{i}.txt pairs
cf watch [all] [spec...]       live table of your submissions
cf open / stand / sid          open problem / standings / submission in a browser
cf race [spec...]              countdown, then open + parse the contest
cf pull [ac] [spec...]         download your submitted codes
cf clone [ac] [handle]         download all codes of a user
cf upgrade                     check GitHub for a newer release
```

A **specifier** is anything useful: `1136`, `1136a`, `a`, `gym 100001`, a full
problem/contest/group URL, etc. Without one, the contest/problem is inferred from the
current directory (layout `<root>/<contest|gym|group|acmsguru>/<contestID>/<problemID>/`,
root folder name defaults to `cf`).

### Which file `cf submit` sends

The code files (by template suffix) in the current directory are the candidates, and
for `cf submit 546D` also those in `546/`, `546/D/` and `546D/` below it; standing in
one of those folders, this problem's files around it count too (`../../546D.cpp` from
`546/D/`). The only one is sent as is; when there are several, you pick (Esc cancels),
from a list like this:

```
? Which file do you want to submit?
 » 1) 546D.cpp             today 18:09
   2) 546/D/solution.cpp   Mar 31
   ── other files ──
   3) demo.py              today 16:11
   4) 2171A.cpp            Jun 16
```

This problem's files come first: `546D.cpp`, `cf546d.py`, `546-D.cpp`, `546D_brute.cpp`,
`546/D.cpp`, and anything in `546/D/`, `546D/` or `cf/contest/546/d/`. The rest follow
(`D.cpp` first). Within each group the most recently edited file comes first, and the
top one is pre-selected. `-f file` skips the list. Without a specifier, contest and
problem can come from the chosen file's name (`546D.cpp`, `546/D.cpp`) after a
confirmation, and a file named for another problem than the one you asked for needs
an explicit yes.

### Templates

In code (`cf gen`): `$%U%$` handle, `$%Y%$ $%M%$ $%D%$ $%h%$ $%m%$ $%s%$` date/time.
In scripts (`cf test`): `$%path%$`, `$%full%$` (a.cpp), `$%file%$` (a), `$%rand%$`.

Example C++ template: before script `g++ -O2 -o $%file%$ $%full%$`, script
`./$%file%$`, after script `rm $%file%$`. Starter templates are in
[`templates/`](templates).

## Files

- `$XDG_CONFIG_HOME/cf/config` (default `~/.config/cf/config`) — templates, default
  template, host/proxy, folder names (JSON, same schema as the Go tool)
- `$XDG_STATE_HOME/cf/session` (default `~/.local/state/cf/session`, mode 0600) —
  handle, AES-GCM-encrypted password, cookies + the User-Agent they belong to, last
  submission

**Coming from the Go tool?** Its `~/.cf/config` and `~/.cf/session` are copied over on
first run, stored login included; `~/.cf` itself is left untouched.

## Troubleshooting

- `CF_DEBUG=1 cf <command>` prints the full traceback along with the error.
- A browser window opened during login: Cloudflare wants a human check — complete it
  there; the login form is filled in for you.
- Behind a proxy, set it in `cf config`: the browser uses the same proxy, since
  Cloudflare ties its clearance to the IP address.
- Windows support is experimental; reports are especially welcome.

## Development

```bash
uv sync --extra dev
uv run pytest      # offline tests; the browser and login logic run against fakes
uv run black cf_tool tests && uv run flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool tests
```

`tests/fixtures/` holds pages trimmed from the live site; when Codeforces changes its
markup, refresh them and fix `cf_tool/pages.py`.

## Credits & license

Built on the design of [xalanq/cf-tool](https://github.com/xalanq/cf-tool) (MIT).
cf-tool is MIT licensed — see [LICENSE](LICENSE).
