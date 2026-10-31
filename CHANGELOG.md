# Changelog

## Unreleased

- **Language presets and a setup wizard**: `cf config` asks which language (C++,
  Python, Java, Kotlin, Rust, Go, C), finds the compiler, fills in the scripts and the
  newest Codeforces language of that family, and writes a starter template. On macOS:
  a `bits/stdc++.h` for clang and Codeforces' 256 MB stack. Languages set up by hand
  are picked by family too.
- **`cf doctor`** checks templates, compilers, the login and Chrome, and says how to
  fix what's wrong.
- **`cf test`** stops a sample that runs a few times past the problem's time limit
  (saved by `cf parse`), flags runs over the time or memory limit, shows what a
  crashing program printed, and won't judge interactive problems.
- **`cf test`** accepts what the statement accepts: numbers within its error, any
  letter case (found by `cf parse`); `-e`, `-i`, `--exact` and `--checker CMD`
  (testlib-style) override it. A failing multi-test sample names the test case that
  differs. `cf test 2` runs one sample, `--add` types in a new one, samples without
  an answer are run and shown, and `--accept` keeps their output.
- **`cf submit`** names the language it submits as; when Codeforces no longer offers
  the template's language, it offers that family's current ones.
- The built-in language table (used when not logged in) had wrong ids for G++23,
  Kotlin, Java 8 and C#; fixed.
- **Tab completion** for bash, zsh and fish (`cf completion`): commands, options,
  `cf gen` aliases, file names, and specifiers like `546D` from the current folder.
- Live checks against codeforces.com (`pytest -m live`, public pages only) tell when
  its markup drifts away from the parsers.
- CI runs on current GitHub Actions (checkout v7, setup-uv v10).

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
