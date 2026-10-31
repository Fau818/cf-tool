# cf-tool 0.4.0 rewrite plan

Branch `v0.4` (delete this file before the release). Goal: drop the Go cf-tool's model and
ship a version that works out of the box.

## 1. Why rewrite (what the investigation found)

Fau's own `~/.config/cf/config` shows the problem:

- Two of its three templates (`cpp`, `cpp17`) claim `.cpp`, so every `cf test` and `cf submit`
  first asks which template to use.
- The default template, `cpp17`, has no compile script: `cf test` runs a stale (or missing)
  `./a`, which `cpp`'s after_script deletes. `cf doctor` calls it "ready".
- `cpp` compiles with `-std=c++23` but submits as G++20 (id 89): code that compiles here can
  get a compilation error on Codeforces.
- The 0.3.1 wizard hard-codes `-std=c++20` but submits as G++23, bakes the config folder's
  absolute path into the script, and writes the starter file before asking "Replace your
  template?".

The root cause: one "template" bundles four things — starter code, build/run scripts
(`before_script`/`script`/`after_script` with `$%full%$` placeholders), the Codeforces
language id, and suffixes plus an alias — and the user writes all of them by hand.

The Go tool's other baggage:

- Layout: deep `cf/contest/2050/a/` folders with `in1.txt`/`ans1.txt` next to the code; the
  problem is guessed from folder names, which needs the `folder_name` setting.
- Flow: parse and gen are two steps (plus a `gen_after_parse` switch); every `cf test`
  recompiles (about 1.5 s for C++), and builds land in the problem folder, removed by an rm
  script.
- Comparison: trimmed lines, stricter than Codeforces' checkers (an extra blank line or
  space fails).
- Interface: obscure command names (stand, sid, list, watch); a JSON config behind a menu.

What other tools do (oj, acc, cargo-compete, cpbooster, cph/cph-ng, CP Editor,
CompetiTest.nvim, ...):

- The file extension picks the language; defaults work; users change at most the compiler
  and its flags.
- The tool supplies the source and output paths; build and run are separate; no
  before/after hooks.
- A problem's identity lives in a data file, not in folder names; tests live in `tests/`
  (`.in` with `.ans`).
- The judge's language comes from its live list; builds are cached by source hash, outside
  the source folder.
- A submission's POST is never resent.

xalanq/cf-tool is archived; its issues complain about exactly these: two templates sharing
a suffix, stale language ids, folders too deep.

## 2. Decisions (Fau, 2026-10-31)

- **Layout**: one folder per problem: `2050/a/` holds `a.cpp`, `tests/1.in`, `tests/1.ans`
  and `.cf-problem.json`.
- **Settings**: `~/.config/cf/config.toml` first, commented, every key optional; `cf config`
  opens it in the editor; plus commands like `cf login` and `cf langs`.
- **Commands**: new names; the old names keep working as hidden aliases.
- **Also in 0.4.0**: `cf test --watch`, interactive problems (`--interactor`), publishing to
  PyPI.
- **Later**: inlining local `#include`s before submitting, verdicts through the API, a
  precompiled bits/stdc++.h.
- **Docs**: README rewritten as a whole, English only (no Chinese version).
- **Work in English** throughout (plans, code, comments, commits, docs).

## 3. New design

### Principles

1. No setup: the extension picks the language, compilers are found when needed; get and test
   work without logging in, and submit logs in on the spot.
2. One concept: a language. Built-in defaults; override only the key you care about.
3. Local matches the judge: `-std` follows the submit language; outputs are compared by
   tokens like Codeforces' default checkers, with the statement's error and letter-case
   rules.
4. Self-describing folders: `.cf-problem.json` names the problem; no root-folder setting.
5. Clean folders: builds live in a cache, an unchanged source isn't rebuilt, no cleanup
   scripts.

### Everyday use

```
cf get 2050        # 2050/a … 2050/h: samples + starter code (one request for the contest)
cd 2050/a
cf test            # build (cached) and run the samples; -w re-tests on save
cf submit          # logs in on the spot if needed, then shows the verdict live
cf test b          # works from 2050/ too
```

### Layout

```
2050/                  contest folder
  a/                   problem folder
    a.cpp              starter code; not written when the folder has code in that language
    tests/1.in 1.ans   samples; your own tests too: any name, .in with .ans
    .cf-problem.json   url, name, limits, interactive, error, letter case, sample line cases
```

- **Where**: run from inside a contest or problem folder, `cf get` puts new contests next to
  the current contest folder; with `root` set, under root; otherwise in the current folder.
- **Other kinds**: gym → `<gym id>/`; group → `<contest id>/` (the group id is in the
  metadata); acmsguru → `acmsguru/<problem>/`.
- **Running `cf get` again** refreshes tests and metadata, never code.
- **Helpers**: `gen.*`, `brute.*`, `checker.*`, `interactor.*` are not candidates for
  test/submit; `cf stress` uses them by default.
- **0.3 folders** (`in1.txt`/`ans1.txt`, `cf/contest/x/y/`) can still be tested and
  submitted; loose files like `546D.cpp` keep working.
- **Several candidate files**: same rule as now — always the menu, this problem's files
  first, newest first, with edit times.

### Settings: `~/.config/cf/config.toml`

Read and written with tomlkit, so comments survive.

```toml
language = "cpp"              # what cf get writes starter code in (asked on the first cf get)
# root = "~/codeforces"       # where cf get puts contests (default: the current folder)
# host = "https://codeforces.com"
# proxy = "socks5://127.0.0.1:1080"   # default: the environment's

# [cpp]                       # one table per language, by file extension
# compiler = "g++-15"         # default: found on this machine, GCC first
# flags = "-DLOCAL"           # added after the default flags
# submit = "G++20"            # Codeforces language: a name (or part of one) or an id; default: the newest
# template = "~/cp/template.cpp"
# build = "g++ -std=c++20 {src} -o {exe}"   # full control: replaces the built-in build command
# run = "{exe}"
```

- **Placeholders**: build and run commands get `{src}`, `{exe}`, `{dir}`, `{name}`; starter
  code gets `{{handle}}`, `{{date}}`, `{{time}}`, `{{problem}}`, `{{name}}`, `{{url}}`. The old
  `$%U%$` style is still replaced.
- **Languages cf-tool doesn't know**: a table like `[hs]` with `build`, `run` and `submit`.

### Languages (languages.py, from presets.py + langs.py)

- **Built in**: C++, C, Python, Java, Kotlin, Rust, Go.
- **Toolchain detection**: as now (macOS `/usr/bin` placeholder programs, GCC first, dedupe
  by version banner); results cached in `STATE_DIR` per PATH.
- **C++ flags**:
  - `-std` from the submit language (G++17/20/23 → c++17/20/23; `c++2b` on old compilers);
  - a 256 MB stack: a linker flag on macOS, the child's `RLIMIT_STACK` on Linux, `--stack`
    on MinGW;
  - clang's bits/stdc++.h added with `-I` at build time, never written into the settings.
- **Python**: when submitting as PyPy and pypy3 is installed, tests run with it.
- **Submit language**: the configured `submit`; otherwise the newest fitting one of the
  family from Codeforces' live list (the one read last; the built-in table before any).

### Build and run (build.py)

- **Cache**: `$XDG_CACHE_HOME/cf/build/<key>/`, keyed by a hash of the source, the build
  command and the compiler's banner; a source with `#include "…"` is rebuilt every time;
  entries older than 7 days are pruned.
- **Paths**: `{src}` is the real path (fixes `../a.cpp` and `tools/gen.py` running the
  wrong file).
- **Running**:
  - its own process group; on a timeout the whole tree is killed, and nothing waits
    forever on its output afterwards;
  - output is capped; past the cap it is "Output limit exceeded";
  - CPU time, and the peak memory of the whole process tree.

### Testing (judge.py)

- **Comparison**: tokens by default; widened automatically when the statement allows an
  error or any letter case.
  - Letter-case detection gets stricter: "In any case, …" must not count.
  - `--strict` compares trimmed lines (0.3's behavior), `-e`/`-i` widen by hand,
    `--checker CMD` runs a checker with testlib's argument order.
- **Output**: one ✓/✗ line per test with time and memory, limits flagged; a failure shows
  output and answer side by side, only the failing case of a multi-test sample.
- **Results are recorded** by source hash; `cf submit` asks first when this exact code
  failed its tests.
- **`--watch`**: rebuild and re-run when the code or a test is saved; Ctrl-C ends it.
- **`--add` / `--accept`** stay. New tests get the next number; a stress failure is saved as
  `tests/stress-<seed>`.
- **Interactive problems**: `cf test --interactor X`, used automatically when the folder has
  `interactor.*`.
  - The interactor runs as `interactor <input> <output>` (testlib's convention), its stdin
    and stdout wired to the solution;
  - its exit code is the verdict: 0 accepted, 1 wrong answer, 2 presentation error, 3 fail;
  - without an interactor, the problem isn't judged (as now).

### The Codeforces side (cf_tool/codeforces/)

- **Kept**: the three login tiers, the Cloudflare handling, full cookie records, page
  parsing, submitting, listen, contests, pick, CP Editor compatibility — all tested live.
- **Session**: same file and format, so an upgrade doesn't log anybody out.
- **Fetching**: `cf get <contest>` reads `/contest/<id>/problems` once for every problem (the
  current parsers handle that page); per problem only when that fails.

Problems the review found, fixed in phase 2:

1. **A server error looks like a lapsed login**: 5xx/429 pages count as content, then as
   logged out: cookies are wiped, the login retried, and a browser window opens. They become
   transport errors, retried with backoff.
2. **A submission can be sent twice**: the POST is resent after a timeout. It is never
   resent; when the outcome is unknown, `/my` is checked for the new submission.
3. **Concurrent requests write stale cookies back**: requests and cookie-jar edits get a
   lock.
4. **Passing a check can replace the logged-in session**: the browser exports an anonymous
   JSESSIONID. A solve adopts only Cloudflare's cookies and the UA (to confirm live).
5. **listen**: a socket timeout, JSON only, requests from web pages (http/https Origin)
   rejected; a URL that isn't a problem is rejected instead of overwriting the current
   folder's samples.
6. **Smaller**: Rich turns `:x:` into an emoji (`Console(emoji=False)`); Ctrl-C must stop
   clone promptly, and its 500 s wait must be interruptible; when the browser relaunch fails,
   the first Chrome is left running.

### Commands

| Command | What it does |
| --- | --- |
| `cf get <contest\|problem\|URL> [-l LANG]` | folders, samples, starter code (replaces parse + gen) |
| `cf race <contest>` | countdown; at the start, get + open the problems |
| `cf test [problem\|file] [test…]` | run the tests: `-w`, `--add`, `--accept`, `-e`, `-i`, `--strict`, `--checker`, `--interactor` |
| `cf stress [gen] [brute] [solution]` | stress test: `-n`, `--seed` |
| `cf submit [problem] [file] [-l LANG]` | submit, then the verdict live |
| `cf status [problem] [--all]` | your submissions, refreshed live (replaces watch) |
| `cf open [problem\|contest] [--standings\|--last]` | open in the browser (replaces stand, sid) |
| `cf problems [contest]` | a contest's problems and solve counts (replaces list) |
| `cf new [name]` | a code file from your template (replaces gen) |
| `cf login` / `cf logout` | log in, log out |
| `cf langs [--all]` | per language: the compiler, what it submits as, the starter file |
| `cf config` | open config.toml in the editor, check it afterwards |
| `cf contests` / `pick` / `listen` / `pull` / `clone` / `doctor` / `upgrade` / `completion` | kept |

- Hidden aliases: parse→get, gen→new, watch→status, list→problems,
  stand→open --standings, sid→open --last.
- The CP Editor contract stays: `cf --version` prints `cf-tool v0.4.0`;
  `cf submit <cid> <idx> <file>`; `status: …` lines when not on a terminal.

### Migration

- **Settings**: 0.3's JSON config becomes config.toml on the first run; `~/.cf/config` has
  the same schema and is handled too.
  - Carried over: the default language, each language's starter file, the submit language
    id, host, proxy.
  - Not carried over: build scripts (generated now). The conversion lists what was dropped;
    the old file stays as it is.
- **Starter files**: unchanged; the old placeholders are still replaced.
- **Go tool**: `~/.cf/session` is no longer imported (the Go tool can't log in anyway).

## 4. Code layout

```
cf_tool/
  cli/            commands by group: __init__ (group, aliases, errors), problems, testing,
                  submitting, account, setup, misc
  settings.py     config.toml, defaults, validation, migration
  languages.py    the language table, toolchain detection, -std, the Codeforces language,
                  starter code
  workspace.py    problem and contest folders, metadata, test files, targets, candidate
                  files (replaces args, codefiles, problem, templates)
  build.py        cached builds, running processes (process group, output cap, time, memory)
  judge.py        comparison, one test, the test flow, watch, interactor
  stress.py  listen.py  views.py  ui.py  errors.py
  codeforces/     client gateway http browser pages session crypto
```

Also:

- Remove the "Port of cmd/xxx.go" notes and the Go compatibility branches (the Go cookie jar
  and old session formats, `folder_name`, the root-folder search).
- Tests rewritten per module; a fixture for the all-problems page.
- CLAUDE.md, README and CHANGELOG rewritten.

## 5. Phases (each: tests green, black and flake8 clean, then a commit on v0.4; no push)

0. **Prep** (done): the v0.4 branch; the dev venv fixed (the stale 0.2.0 install replaced by
   an editable one); the tomlkit dependency; this plan.
1. **Core model**: settings (with migration), languages, workspace, build, each with tests.
2. **Commands onto the new core**:
   - in order: get, race, listen, new, pick; test (with watch and the interactor), stress;
     submit, status, login, logout; open, problems, pull, clone, contests;
   - the network fixes above; the old modules deleted.
3. **UX**:
   - langs, config, doctor, completion;
   - the first-run language question, logging in on the spot, the warning before submitting
     failed code;
   - one output style and clear error messages.
4. **Docs and release prep**:
   - **README rewritten as a whole** (Fau's request): from scratch for the new version, so a
     new user understands it at first read; everything old or useless deleted (the Go port,
     templates and scripts, placeholders, old command names, the old layout). Outline:
     1. one sentence and an example;
     2. install;
     3. three steps (get, test, submit);
     4. the commands;
     5. testing: comparison, your own tests, --watch, stress, interactive problems;
     6. settings: config.toml, all optional;
     7. logging in;
     8. Competitive Companion, CP Editor, Tab completion;
     9. upgrading from 0.3;
     10. troubleshooting;
     11. development (last, short).
   - CHANGELOG, CLAUDE.md, version 0.4.0;
   - a PyPI publishing workflow (trusted publishing) in CI;
   - **independent review** (Fau's request): once code and docs are written, a fresh agent
     that took no part in the rewrite reviews all of `main..v0.4`.
     - Scope: correctness bugs, security, the CP Editor contract, the 0.3 migration, Windows
       paths, agreement with this plan, missing tests, README against actual behavior;
     - it gets the code, not my conclusions;
     - I verify each finding, fix the real ones, get the tests green again and commit; the
       report says what was fixed and what didn't hold up.
5. **Acceptance** (needs Fau):
   - all tests, the toolchain tests (CI on Linux and macOS), the live tests;
   - a real login and submission on a practice problem from Fau's terminal;
   - then Fau decides on merging, the tag, the release and PyPI.

## 6. Rules while unattended

- Commit on v0.4 only; no push, tag or release.
- No logging in, no submitting; the network only for public pages (live tests).
- 1Password can't sign while locked, so unattended commits are unsigned (`--no-gpg-sign`);
  they get re-signed (or squashed into a few signed commits) with Fau before merging into
  main.
