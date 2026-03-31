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
- [ ] Parse entire contest: `cf parse 1000` (download all problems A-Z)
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
- [ ] Open contest page (not just single problem)
- [ ] Auto-detect contest/problem from current directory

### [ ] `race` - Join Contest

- [ ] Register user for a contest
- [ ] Open contest page and problems in browser
- [ ] Auto-parse all problems when contest starts
- [ ] Countdown timer to contest start

### [ ] `stand` - View Standings

- [ ] Open standings page in browser
- [ ] Support contest/gym types

### [ ] `sid` - Open Submission Page

- [ ] Open specific submission by ID
- [ ] Open last submission (no ID required)
- [ ] Support viewing submission details

### [ ] `pull` - Pull Accepted Solutions

- [ ] Download solutions from past contests
- [ ] Filter by accepted status (`--ac` flag)
- [ ] Organize by contest/problem directory structure

### [ ] `clone` - Clone User Submissions

- [ ] Clone submission history for a given user handle
- [ ] Filter accepted-only solutions
- [ ] Organize by contest structure

### [ ] `list` - Display Problem List

- [ ] Show formatted table of problems in a contest
- [ ] Display problem ID, name, solved count, time limit
- [ ] Color-code by user's acceptance status (green=AC, red=WA)

### [ ] `upgrade` - Check for Updates

- [ ] Query PyPI for latest version
- [ ] Compare with current version
- [ ] Prompt user to run `pip install --upgrade cf-tool`

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
