# cf-tool guide

The details behind the [README](../README.md). `cf <command> --help` says more about each
command.

- [On disk](#on-disk)
- [Testing](#testing)
- [Submitting](#submitting)
- [Settings](#settings)
- [Logging in](#logging-in)
- [With other tools](#with-other-tools)
- [Coming from cf-tool 0.3](#coming-from-cf-tool-03)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## On disk

```
2050/
  a/
    a.cpp              your code (any name; brute.cpp, gen.py and others can sit beside it)
    statement.md       the statement, as Markdown (formulas in TeX)
    tests/1.in 1.ans   the samples, and any tests you add
    .cf-problem.json   what cf knows about the problem: its link, limits and checker rules
  b/
    ...
```

Run from inside a contest's folder, `cf get` puts the next contest beside it. In a
contest's folder, a problem's letter is enough: `cf test b`, `cf submit b`.

When several code files could be meant, `cf test` and `cf submit` show a menu: this
problem's files first, the most recently edited first. A file named for another problem
asks for a yes before it is submitted. Helpers are never in the way: files whose names
start with `gen`, `brute`, `check` or `interactor` (`gen2.py`, `brute_c.cpp`, `checker.cpp`).

## Testing

`cf test` compares your output with each test's answer the way Codeforces' usual checker
does: word by word, so spaces and line breaks don't matter. When the statement accepts
numbers within an error (say 1e-6) or answers in any letter case, so does `cf test`. When it
accepts any right answer ("print any of them"), an output unlike the sample's is marked
`?` (differs), not wrong: check it yourself, or let a checker decide.

- `cf test 2` runs one test; `cf test 2 my` two of them.
- Your own tests go in `tests/` as `<name>.in` with `<name>.ans`. `cf test --add` asks for
  the input and the answer. A test without an `.ans` file is just run, and its output shown;
  `--accept` keeps that output as its answer.
- `cf test -w` tests again each time you save the code or a test.
- A test that runs a few times past the time limit is stopped; a run over the time or
  memory limit is flagged.
- `-e 1e-9` and `-i` accept an error or any letter case yourself, `--strict` compares
  trimmed lines, and `--exact` ignores what the statement allows.
- A checker decides by itself: `checker.cpp` (any language, or `check_a.py` and the like)
  in the problem's folder, or `--checker FILE` (or a command: `--checker "python3 chk.py"`).
  It runs as `checker input output answer` and exits with 0 when the output is right, like
  a testlib checker.

**Stress testing.** Put a generator `gen.py` and a brute force `brute.cpp` (any languages;
`gen2.py` or `brute_c.cpp` do too) in the problem's folder and run `cf stress`. The
generator prints one test for the seed it gets as its argument. The brute force's output is
that test's answer. The first test your solution fails is saved as `tests/stress-<seed>`,
so `cf test` keeps checking it. Each `cf stress` first checks those saved answers against
the brute force as it is now, and says which it updated.

**Interactive problems.** `cf test` runs your solution against an interactor:
`interactor.cpp` (any language) in the problem's folder, or `--interactor FILE`. It runs as
`interactor input output`, talks with your solution through their standard input and
output, and its exit code is the verdict (0 accepted, 1 wrong answer), as with testlib.

## Submitting

`cf submit` sends the code of the problem you're in and shows the verdict as it comes; it
asks first when that code failed its tests. The form is sent only once: if the answer is
lost, cf looks for the submission among yours instead of sending it again.

Once a contest is over, Codeforces shows your submission's failed test, and `cf submit`
prints it under the verdict: what the checker said, the input, your output and the answer
(the long ones cut short by Codeforces). A test shown in full is kept as `tests/cf-<n>`, so
`cf test` runs it from then on. `cf status <submission id>` does the same for an earlier
submission. When Python runs over a limit, cf suggests PyPy, which is usually several times
faster on Codeforces.

## Settings

Everything works without settings: cf finds your compiler, picks the newest Codeforces
language, and starts you from a built-in template. To change something, run `cf config`:

```
◆ cf-tool settings · tourist · ~/.config/cf/config.toml
   ── General ──
 ❯ 1) Language for new problems   C++
   2) Proxy                       none
   ── C++ ──
   3) Compiler                    GCC 14 (g++-14)  recommended
   4) Submitted as                GNU G++23 14.2 (64 bit, msys2)  recommended
   5) Build and run               the recommended commands  recommended
   6) Starter code                the built-in one  recommended
   ── Python ──
   7) Interpreter                 Python 3.13 (python3)  recommended
   8) Submitted as                PyPy 3.10 (7.3.15, 64bit)  recommended
   ...
   9) Edit config.toml in your editor
   0) Done
```

Every language installed here is in the same list. Each setting opens a list whose first
item is the recommended one, already selected, so Enter keeps it; Esc goes back.

- **Compiler.** The best one found here comes first (GCC before clang); the others found,
  or any program, are there too. C++ is compiled with the standard of the Codeforces
  language it is submitted as (or the newest your compiler knows), so code that compiles
  here compiles there.
- **Submitted as.** Codeforces' languages of that family by name, the newest first.
- **Build and run.** The recommended commands are shown; you can add flags of yours (like
  `-DLOCAL`) or write your own, with `{src}` for your code file and `{exe}` for the program
  built from it.
- **Starter code.** The built-in one, a file of yours, or the built-in one copied to
  `~/.config/cf/templates/` for you to change. `cf new brute` starts from
  `templates/brute.cpp` when you have one. In starter code, `{{name}}`, `{{url}}`,
  `{{problem}}`, `{{handle}}`, `{{date}}` and `{{time}}` are filled in.

Everything is saved in `~/.config/cf/config.toml`, where every setting is explained;
`cf config --edit` opens it in your editor. There you can also set `root =
"~/codeforces"` (where `cf get` puts contests), `host`, or add a language cf doesn't know,
as a table with `build`, `run` and `submit` (`[hs]`). `cf langs` shows what each language
uses.

## Logging in

`cf login` asks for your handle (or email) and password; `cf submit` asks too when you
aren't logged in. The password is saved encrypted, so an expired login renews itself.

Codeforces lets only browsers through its login page, so cf logs in with Chrome in the
background (a fresh one if the first gets stuck); only if a human has to click does a
browser window open. A wrong password stops right away. Without a terminal, `cf login`
reads the handle and the password from its input, one per line.

The login lives in `~/.local/state/cf/session` (readable only by you); `cf logout`
forgets it.

## With other tools

- **Competitive Companion.** With the [browser extension](https://github.com/jmerle/competitive-companion),
  run `cf listen` and click its button on a problem or contest page: the problems land
  where `cf get` puts them, and cf fetches no page.
- **CP Editor.** [CP Editor](https://cpeditor.org) submits through cf-tool: in its
  preferences, set the CF Tool path to what `which cf` prints.
- **Tab completion.** Commands, options, the contests and problems around you (with their
  names: `cf submit 2050 <Tab>` lists its problems), contests on now for `cf get`, test
  names and code files:

  ```bash
  eval "$(cf completion zsh)"     # in ~/.zshrc, after compinit
  eval "$(cf completion bash)"    # in ~/.bashrc (bash 4.4+)
  cf completion fish | source     # in ~/.config/fish/config.fish
  ```

  If `cf <Tab>` offers `apps`, `push` and the like, that is the completion for Cloud
  Foundry's `cf` from zsh-completions: load ours after it.

## Coming from cf-tool 0.3

- cf-tool is on PyPI now, as `cf-tool-cli`. Swap your install once: `uv tool uninstall
  cf-tool`, then `uv tool install cf-tool-cli` (or the same with pipx).
- Your settings move to `config.toml` by themselves on the first run: your starter files,
  your languages, host and proxy. Build scripts aren't needed any more; cf says what it
  left out.
- The commands have plain names: `get` (was `parse` and `gen`), `new` (`gen`), `status`
  (`watch`), `problems` (`list`), `open -s` (`stand`), `open --last` (`sid`). The old names
  still work.
- Problem folders are `2050/a/` with `tests/` now. Folders made by 0.3
  (`cf/contest/2050/a/` with `in1.txt` and `ans1.txt`) can still be tested and submitted.
- Your login carries over.

## Troubleshooting

- `cf doctor` checks compilers, settings, the login and Chrome, and says what to do.
- `CF_DEBUG=1 cf <command>` shows the full error.
- A browser window opened while logging in: Cloudflare wants a human check. Do it there;
  the rest is filled in for you.
- Behind a proxy, set `proxy` in `cf config`; the browser uses it too, since Cloudflare ties
  its check to your IP address.
- Something broke? Please say so in [Issues](https://github.com/Fau818/cf-tool/issues).

## Development

```bash
uv sync --extra dev
uv run pytest                  # offline tests
uv run pytest -m live          # the parsers against the real site (public pages only)
uv run pytest -m toolchain     # every language's starter, built with your compilers
uv run black cf_tool tests && uv run flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool tests
```
