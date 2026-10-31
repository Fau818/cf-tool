# cf-tool

[![CI](https://github.com/Fau818/cf-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Fau818/cf-tool/actions/workflows/ci.yml)

Codeforces from your terminal: get a contest's problems, test your code on their samples,
and submit it, without setting anything up first.

```console
$ cf get 2171
2171/a      A. Shizuku Hoshikawa and Farm Legs  1 test, a.cpp
2171/b      B. Yuu Koito and Minimum Absolute Sum  1 test, b.cpp
...
Next: cd 2171/a, then cf test and cf submit there
$ cd 2171/a
$ cf test
Built a.cpp with GCC 14 (g++-14) in 1.4s
✓ 1  0.002s  3.1 MB
All 1 passed
$ cf submit
Submitting 2171A (a.cpp) as GNU G++23 14.2 (64 bit, msys2), logged in as you
```

> [!NOTE]
> cf-tool is young. If something breaks, above all around logging in, please say so in
> [Issues](https://github.com/Fau818/cf-tool/issues).

## Install

You need Python 3.10 or newer, and a compiler or interpreter for your language
(`g++`, `python3`, ...). Google Chrome or Chromium is needed only when Cloudflare checks
the login.

```bash
uv tool install cf-tool       # or: pipx install cf-tool
```

`cf upgrade` tells you when there is a newer version.

## Getting started

1. **Get the problems.** `cf get 2050` makes a folder for each problem of contest 2050,
   with its samples and your starter code. `cf get 2050b` gets one problem. The first
   time, cf asks which language you write in.
2. **Test.** In a problem's folder, `cf test` builds your code and runs it on the
   samples. A build is kept, so an unchanged file isn't compiled again.
3. **Submit.** `cf submit` sends your code and shows the verdict as it comes. The first
   time, cf asks for your Codeforces handle and password.

A contest looks like this on disk:

```
2050/
  a/
    a.cpp              your code (any name; brute.cpp, gen.py and others can sit beside it)
    tests/1.in 1.ans   the samples, and any tests you add
    .cf-problem.json   what cf knows about the problem: its link, limits and checker rules
  b/
    ...
```

Run from inside a contest's folder, `cf get` puts the next contest beside it. In a
contest's folder, a problem's letter is enough: `cf test b`, `cf submit b`.

## Commands

| Command | What it does |
| --- | --- |
| `cf get 2050` / `cf get 2050b` | folders, samples and starter code for a contest or a problem (a URL works too) |
| `cf test [problem] [test...]` | build your code and run it on the problem's tests |
| `cf submit [problem] [file]` | submit, then show the verdict as it comes |
| `cf status` | your submissions to the contest, refreshed until they're judged |
| `cf race 2050` | count down to the start, then open the problems and get them |
| `cf open [problem]` | open the problem in the browser; `-s` the standings, `--last` your last submission |
| `cf problems [contest]` | a contest's problems, and how many solved each |
| `cf contests` | upcoming contests; `--ics file` saves them for your calendar |
| `cf pick -r 1600 -t dp` | a random problem you haven't solved; `--get` sets it up |
| `cf stress` | random tests until your code and a brute force disagree |
| `cf listen` | receive problems from the Competitive Companion browser extension |
| `cf new [name]` | a code file from your starter code: `cf new`, `cf new brute`, `cf new gen.py` |
| `cf pull [problem]` / `cf clone [handle]` | download the code of your (or anyone's) submissions |
| `cf login` / `cf logout` | log in to Codeforces, or forget the login |
| `cf langs` | how each language is built, run and submitted here |
| `cf config` | open the settings in your editor |
| `cf doctor` | check the setup and say how to fix what's wrong |
| `cf completion` | the Tab-completion script for your shell |

`cf <command> --help` says more about each.

When several code files could be meant, `cf test` and `cf submit` show a menu: this
problem's files first, the most recently edited first. A file named for another problem
asks for a yes before it is submitted.

## Testing

`cf test` compares your output with each test's answer the way Codeforces' usual checker
does: word by word, so spaces and line breaks don't matter. When the statement accepts
numbers within an error (say 1e-6) or answers in any letter case, so does `cf test`.

- `cf test 2` runs one test; `cf test 2 my` two of them.
- Your own tests go in `tests/` as `<name>.in` with `<name>.ans`. `cf test --add` asks for
  the input and the answer. A test without an `.ans` file is just run, and its output shown;
  `--accept` keeps that output as its answer.
- `cf test -w` tests again each time you save the code or a test.
- A test that runs a few times past the time limit is stopped; a run over the time or
  memory limit is flagged.
- `-e 1e-9` and `-i` accept an error or any letter case yourself, `--strict` compares
  trimmed lines, and `--exact` ignores what the statement allows.
- A checker decides by itself: `checker.cpp` (any language) in the problem's folder, or
  `--checker FILE`. It runs as `checker input output answer` and exits with 0 when the
  output is right, like a testlib checker.

**Stress testing.** Put a generator `gen.py` and a brute force `brute.cpp` (any languages)
in the problem's folder and run `cf stress`. The generator prints one test for the seed it
gets as its argument. The brute force's output is that test's answer. The first test your
solution fails is saved as `tests/stress-<seed>`, so `cf test` keeps checking it.

**Interactive problems.** `cf test` runs your solution against an interactor:
`interactor.cpp` (any language) in the problem's folder, or `--interactor FILE`. It runs as
`interactor input output`, talks with your solution through their standard input and
output, and its exit code is the verdict (0 accepted, 1 wrong answer), as with testlib.

## Settings

Everything works without settings. To change something, `cf config` opens
`~/.config/cf/config.toml`, where every setting is explained:

```toml
language = "cpp"          # what cf get writes starter code in

[cpp]                     # one table per language, named by its file extension
compiler = "g++-15"       # default: the best one found here, GCC first
flags = "-DLOCAL"         # added to the default flags
submit = "G++20"          # part of a Codeforces language's name, or its id
template = "~/cp/template.cpp"
```

- **Compilers.** cf finds them by itself, GCC first. C++ is compiled with the standard of
  the Codeforces language it is submitted as, so code that compiles here compiles there.
  `cf langs` shows what each language uses.
- **Submit language.** By default the newest one of the family (G++23 for C++, PyPy for
  Python). `cf langs --all` lists every language Codeforces offers, with its id.
- **Starter code.** Your own goes in `~/.config/cf/templates/template.cpp` (or set
  `template`). `cf new brute` starts from `templates/brute.cpp` when you have one. In
  starter code, `{{name}}`, `{{url}}`, `{{problem}}`, `{{handle}}`, `{{date}}` and
  `{{time}}` are filled in.
- **Full control.** `build = "..."` and `run = "..."` replace the commands for a language,
  with `{src}` (the code file) and `{exe}` (the program built from it). A table for an
  extension cf doesn't know (`[hs]`) adds a language.
- **Elsewhere.** `root = "~/codeforces"` makes `cf get` put contests there; `proxy` and
  `host` are there too.

## Logging in

`cf login` asks for your handle (or email) and password; `cf submit` asks too when you
aren't logged in. The password is saved encrypted, so an expired login renews itself.

Logging in tries plain HTTP first. When Cloudflare checks the login page, a browser does it
in the background, and only if Cloudflare wants a human to click does a browser window
open. A wrong password stops right away.

The login lives in `~/.local/state/cf/session` (readable only by you); `cf logout`
forgets it.

## With other tools

- **Competitive Companion.** With the [browser extension](https://github.com/jmerle/competitive-companion),
  run `cf listen` and click its button on a problem or contest page: the problems land
  where `cf get` puts them, and cf fetches no page.
- **CP Editor.** [CP Editor](https://cpeditor.org) submits through cf-tool: in its
  preferences, set the CF Tool path to what `which cf` prints.
- **Tab completion.** Commands, options, problem letters, test names and files:

  ```bash
  eval "$(cf completion zsh)"     # in ~/.zshrc, after compinit
  eval "$(cf completion bash)"    # in ~/.bashrc (bash 4.4+)
  cf completion fish | source     # in ~/.config/fish/config.fish
  ```

  If `cf <Tab>` offers `apps`, `push` and the like, that is the completion for Cloud
  Foundry's `cf` from zsh-completions: load ours after it.

## Coming from cf-tool 0.3

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
- Windows support is experimental; reports are very welcome.

## Development

```bash
uv sync --extra dev
uv run pytest                  # offline tests
uv run pytest -m live          # the parsers against the real site (public pages only)
uv run pytest -m toolchain     # every language's starter, built with your compilers
uv run black cf_tool tests && uv run flake8 --max-line-length=100 --extend-ignore=E203,W503 cf_tool tests
```

## Credits and license

cf-tool began as a port of [xalanq/cf-tool](https://github.com/xalanq/cf-tool) (MIT). It is
MIT licensed; see [LICENSE](LICENSE).
