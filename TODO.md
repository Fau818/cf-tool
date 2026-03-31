# cf-tool Feature TODO List

Feature comparison between the original Go-based [cf-tool](https://github.com/xalanq/cf-tool) and this Python rewrite.

## Legend

- [x] Implemented
- [~] Partially implemented
- [ ] Not implemented

## Commands

### [x] `config` - Configuration Management

- [x] `config set <key> <value>` - Set a config value
- [x] `config get <key>` - Get a config value
- [x] `config show` - Show all config
- [x] `config login` - Login to Codeforces (browser-based, Cloudflare bypass)
- [x] `config wizard` - Interactive setup wizard
- [x] `config add-template` / `config remove-template` / `config templates` - Template management
- [ ] Proxy settings configuration
- [ ] Folder naming configuration (custom directory patterns)

### [x] `parse` - Parse Problems & Download Test Cases

- [x] Parse single problem: `cf parse 1000A` or `cf parse 1000 A`
- [x] Download sample test cases (in/out files)
- [x] Generate solution file from template
- [x] Support contest/gym/problemset/group types
- [x] Parse entire contest: `cf parse 1000` (download all problems A-Z)

### [x] `gen` - Generate Code from Template

- [x] Generate solution file with template substitution
- [x] Support `$PROBLEM$` and `$CONTEST$` variables
- [x] Template alias selection (`--alias` flag)
- [x] Filename collision handling with numeric suffixes
- [x] Auto-detect from current directory
- [ ] Additional template variables ($%path%$, $%full%$, $%file%$, $%rand%$)

### [x] `test` - Local Testing

- [x] Auto-detect solution file
- [x] Run against all sample test cases
- [x] Color-coded pass/fail results
- [x] Execution time display
- [x] Whitespace-normalized comparison
- [x] Pre-test script execution (before_script config)
- [x] Post-test script execution (after_script config)
- [ ] Custom checker support

### [x] `submit` - Submit Solution

- [x] Submit to Codeforces with CSRF handling
- [x] Auto-detect solution file and language
- [x] Confirmation prompt before submission
- [x] Auto-watch submission after submit
- [x] Auto-detect from current directory
- [x] Auto re-login on session expiry

### [x] `watch` - Watch Submissions

- [x] Poll submission status via Codeforces API
- [x] Real-time status display with Rich
- [x] Color-coded verdicts (AC, WA, TLE, etc.)
- [x] Watch latest submission without specifying ID: `cf watch 1000`
- [x] `--all` flag to list recent submissions

### [x] `open` - Open in Browser

- [x] Open problem page in browser
- [x] Support contest/gym/problemset/group types via `--contest-type`
- [x] Open contest page when in contest directory
- [x] Auto-detect contest/problem from current directory

### [x] `race` - Join Contest

- [x] Open contest page and registration in browser
- [x] Auto-parse all problems when contest starts
- [x] Countdown timer to contest start
- [ ] Automatic registration (currently opens registration page)

### [x] `stand` - View Standings

- [x] Open standings page in browser
- [x] Support contest/gym types

### [x] `sid` - Open Submission Page

- [x] Open specific submission by ID
- [x] Open contest submissions page via `--contest` flag

### [x] `pull` - Pull Accepted Solutions

- [x] Download solutions from past contests
- [x] Filter by accepted status (`--ac` flag)
- [x] Organize by contest/problem directory structure

### [x] `clone` - Clone User Submissions

- [x] Clone submission history for a given user handle
- [x] Filter accepted-only solutions (`--ac` flag)
- [x] Organize by contest structure
- [ ] Download full source code (requires auth; currently saves metadata)

### [x] `list` - Display Problem List

- [x] Show formatted table of problems in a contest
- [x] Display problem ID, name, solved count
- [ ] Color-code by user's acceptance status (green=AC, red=WA)

### [x] `upgrade` - Check for Updates

- [x] Query PyPI for latest version
- [x] Compare with current version
- [x] Prompt user to run `pip install --upgrade cf-tool`

## Cross-Cutting Features

### [x] Directory Context Detection

- [x] Auto-detect contest_id/problem_id from current working directory
- [x] Allow running `cf submit`, `cf open`, `cf gen` without explicit problem ID when inside a problem directory

### [x] Enhanced Template System

- [x] Multiple named templates with aliases
- [x] Add/remove/list templates via config subcommands
- [x] Template alias selection in gen command
- [ ] Custom compile/run scripts per template
- [ ] More template variables (author, date, file paths)

### [x] Improved Error Handling

- [x] Auto re-login on session expiry (interactive prompt)
- [x] Retry logic for transient network failures (exponential backoff)
- [x] Better error messages from session/scraper

## Remaining Nice-to-Haves

- [ ] Proxy settings
- [ ] Folder naming configuration
- [ ] Custom checker support for test
- [ ] More template variables
- [ ] Color-code problem list by user's AC/WA status
- [ ] Download full source in clone command (auth required)
- [ ] Automatic contest registration in race command
