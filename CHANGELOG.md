# Changelog

## 0.4.0 (2026-11)

A new cf-tool: it no longer follows the Go cf-tool's model, and needs no setup.

- **No templates, no scripts.** The file extension picks the language, and cf finds the
  compiler (GCC first) when it needs one. Settings are optional, in a commented
  `~/.config/cf/config.toml` that `cf config` opens: the compiler, extra flags, the
  Codeforces language, your starter file, or whole build and run commands.
- **Local matches the judge.** C++ is compiled with the standard of the language it is
  submitted as (G++20 → `-std=c++20`; with an older compiler, the newest one it knows),
  with Codeforces' 256 MB stack. Outputs are compared word by word, like Codeforces' usual
  checker; the statement's error and letter-case rules apply on their own.
- **`cf get`** replaces `parse` and `gen`: one folder per problem (`2050/a/`) with its
  tests in `tests/` and your starter code, and a whole contest in a single request.
  A problem folder knows its problem (`.cf-problem.json`), so commands work anywhere
  inside it, and `cf test b` works from the contest's folder.
- **`cf test`** keeps builds in a cache (an unchanged file isn't compiled again), and
  outside your folders; `-w` tests again on every save; interactive problems run against
  an interactor; `checker.*` in the problem's folder judges by itself. A time limit
  stops everything the program started, and output past 64 MB stops it.
- **`cf submit`** logs in on the spot when needed, asks before sending code that failed
  its tests, and sends the form only once: if the answer is lost, it looks for a
  submission newer than the last one instead of sending it again. Without a terminal (CP
  Editor), it never waits for an answer nobody can give.
- **`cf stress`** finds `gen.*` and `brute.*` in the problem's folder.
- **New commands**: `login`, `logout`, `langs`, `new`, `problems`, `status`, `open -s`,
  `open --last`. The 0.3 names (`parse`, `gen`, `watch`, `list`, `stand`, `sid`) still
  work.
- **Fixes**: a server error (5xx, 429) no longer looks like a lapsed login (which logged
  in again and could open a browser window); passing a Cloudflare check while logged in no
  longer risks the session; requests no longer write stale cookies back; `cf listen` takes
  problems only from the extension, with a timeout; `:x:` in a sample stays text.
- **From 0.3**: the settings move to `config.toml` on the first run (starter files,
  languages, host, proxy); old problem folders still work; the login carries over. The Go
  tool's `~/.cf/session` is no longer imported.

## 0.3.1 (2026-10)

- **Language presets and a setup wizard**: `cf config` asks which language (C++,
  Python, Java, Kotlin, Rust, Go, C), finds the compiler, fills in the scripts and the
  newest Codeforces language of that family, and writes a starter template. On macOS:
  a `bits/stdc++.h` for clang and Codeforces' 256 MB stack. Languages set up by hand
  are picked by family too.
- **`cf doctor`** checks templates, compilers, the login and Chrome, and says how to
  fix what's wrong.
- **`cf test`** uses what `cf parse` now saves from the statement: it stops a sample a
  few times past the time limit, flags runs over a limit, and accepts what the
  statement accepts (numbers within its error, any letter case). `-e`, `-i`,
  `--exact` and `--checker CMD` (testlib-style) change how it compares. A failing
  multi-test sample names the test case that differs; a crashing program shows what
  it printed; interactive problems aren't judged. `cf test 2` runs one sample,
  `--add` types in a new one, and samples without an answer are run and shown
  (`--accept` keeps their output).
- **`cf stress GEN BRUTE`**: random tests until the solution and a brute force disagree;
  the first failing test becomes a sample.
- **`cf listen`** receives problems from the Competitive Companion browser extension:
  samples without fetching a Codeforces page.
- **`cf contests`** lists upcoming contests (`--ics` writes a calendar file); **`cf
  pick`** picks a problem you haven't solved, by rating and tags.
- **CP Editor** can submit through cf-tool: `cf --version` prints `cf-tool v…`, `cf
  submit 546 D a.cpp` takes the file as an argument, and the verdict comes as plain
  `status: …` lines when the output isn't a terminal.
- A yes/no question with no one to answer it (input from a pipe) takes its default.
- **`cf submit`** names the language it submits as; when Codeforces no longer offers
  the template's language, it offers that family's current ones.
- The built-in language table (used when not logged in) had wrong ids for G++23,
  Kotlin, Java 8 and C#; fixed.
- **Tab completion** for bash, zsh and fish (`cf completion`): commands, options,
  `cf gen` aliases, file names, and specifiers like `546D` from the current folder.
- Live checks against codeforces.com (`pytest -m live`, public pages only) tell when
  its markup drifts away from the parsers.
- CI runs on current GitHub Actions (checkout v7, setup-uv v10); the live checks also
  run weekly.

## 0.3.0a1 — first public alpha (2026-10)

A Python port of xalanq/cf-tool for today's Cloudflare-protected Codeforces.

- **Login from the terminal**: HTTP first, then a background browser, a browser window
  only as the last resort; a wrong password or a missing Chrome stops at once.
  Detection of Cloudflare's checks no longer mistakes every normal page for one.
- **`cf submit` finds the problem's files** — `546D.cpp`, `546/D.cpp`, `546/D/main.cpp`,
  the `cf gen` file — and lists them first, newest first, each with its edit time;
  it can read the problem off the file name, and double-checks before sending a file
  named for another problem.
- **Number keys** select items in every menu (plus arrows, and type-to-filter for long
  lists); Esc cancels.
- **`cf test`**: CPU time like the Go tool, a side-by-side diff for failed samples and a
  pass count; scripts are split by the Go tool's rules (Windows paths survive), and a
  missing compiler is a clear error, not a traceback.
- **`cf pull` / `cf clone`** recognize today's language names (`C++20 (GCC 13-64)`, …).
- **Coming from the Go tool**: `~/.cf` is copied (not moved), stored login included.
- `cf parse` fetches a contest's problems in parallel, also parses acmsguru samples, and
  keeps leading spaces in sample lines; the race countdown no longer drifts.
- Sessions are written atomically with mode 0600; a broken config is reported instead of
  being replaced by defaults.
- `cf upgrade` checks this repository's GitHub releases.
- Runs on Python 3.10–3.13.
