# Changelog

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
