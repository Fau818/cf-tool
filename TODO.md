# cf-tool Feature TODO List

Feature comparison between the original Go-based [cf-tool](https://github.com/xalanq/cf-tool) and this Python rewrite.

## Legend

- [x] Implemented
- [~] Partially implemented
- [ ] Not implemented

## Commands

### [~] `config` - Configuration Management

- [x] `config set <key> <value>` - Set a config value
- [x] `config get <key>` - Get a config value
- [x] `config show` - Show all config
- [x] `config login` - Login to Codeforces (browser-based, Cloudflare bypass)
- [ ] Interactive config menu (original has a guided setup wizard)
- [ ] Template management: add/delete templates with aliases
- [ ] Template management: set default template
- [ ] Proxy settings configuration
- [ ] Folder naming configuration (custom directory patterns)

### [~] `parse` - Parse Problems & Download Test Cases

- [x] Parse single problem: `cf parse 1000A` or `cf parse 1000 A`
- [x] Download sample test cases (in/out files)
- [x] Generate solution file from template
- [x] Support contest/gym/problemset/group types
- [x] Parse entire contest: `cf parse 1000` (download all problems A-Z)
- [ ] Auto-detect contest/problem from current directory

### [x] `gen` - Generate Code from Template

- [x] Generate solution file with template substitution
- [x] Support `$PROBLEM$` and `$CONTEST$` variables
- [ ] Template alias selection (choose from multiple templates)
- [ ] Filename collision handling with numeric suffixes
- [ ] Additional template variables ($%path%$, $%full%$, $%file%$, $%rand%$)

### [~] `test` - Local Testing

- [x] Auto-detect solution file
- [x] Run against all sample test cases
- [x] Color-coded pass/fail results
- [x] Execution time display
- [x] Whitespace-normalized comparison
- [ ] Pre-test script execution (BeforeScript)
- [ ] Post-test script execution (AfterScript)
- [ ] Custom checker support

### [x] `submit` - Submit Solution

- [x] Submit to Codeforces with CSRF handling
- [x] Auto-detect solution file and language
- [x] Confirmation prompt before submission
- [x] Auto-watch submission after submit

### [~] `watch` - Watch Submissions

- [x] Poll submission status via Codeforces API
- [x] Real-time status display with Rich
- [x] Color-coded verdicts (AC, WA, TLE, etc.)
- [ ] Watch recent N submissions without specifying submission ID
- [ ] `--all` flag to watch all submissions

### [~] `open` - Open in Browser

- [x] Open problem page in browser
- [x] Support contest/gym/problemset/group types via `--contest-type`
- [ ] Open contest page (not just single problem)
- [ ] Auto-detect contest/problem from current directory

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

### [ ] Directory Context Detection

- [ ] Auto-detect contest_id/problem_id from current working directory
- [ ] Allow running `cf test`, `cf submit`, etc. without explicit problem ID when inside a problem directory

### [ ] Enhanced Template System

- [ ] Multiple named templates with aliases
- [ ] Custom compile/run scripts per template
- [ ] More template variables (author, date, file paths)

### [ ] Improved Error Handling

- [ ] Auto re-login on session expiry
- [ ] Better network error messages
- [ ] Retry logic for transient failures
