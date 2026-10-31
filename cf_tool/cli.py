"""Click CLI mirroring the original cf-tool command surface:

  cf config | submit | list | parse | gen | test | watch | open | stand
     | sid | race | pull | clone | upgrade

Each command body stays thin: parse specifiers via args.parse_args, then call
one client/judge/templates function. Errors end up in cf_command: a red
message instead of a traceback (CF_DEBUG=1 shows the traceback too).
"""

from __future__ import annotations

import functools
import getpass
import os
import platform
import re
import sys
import traceback
import webbrowser
from pathlib import Path

import click
from click.shell_completion import CompletionItem, get_completion_class

from cf_tool import __version__, codefiles, judge, langs, presets, templates, ui, views
from cf_tool import config as config_module
from cf_tool.args import Info, parse_args
from cf_tool.client import Client
from cf_tool.config import PROBLEM_TYPES, CodeTemplate, Config
from cf_tool.errors import CFError

REPOSITORY = "Fau818/cf-tool"


def _setup() -> tuple[Config, Client]:
    cfg = Config.load()
    return cfg, Client(cfg)


def _resolve(specifiers: tuple[str, ...], cfg: Config) -> Info:
    return parse_args(list(specifiers), Path.cwd(), cfg)


def _open_url(url: str) -> None:
    ui.green(f"Open {url}")
    webbrowser.open(url)


def _fail(message: str) -> None:
    if os.environ.get("CF_DEBUG"):
        traceback.print_exc()
    ui.red(message)
    sys.exit(1)


def cf_command(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except CFError as e:
            _fail(str(e))
        except OSError as e:  # unreadable/unwritable files and the like
            _fail(str(e))
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(1)

    return wrapper


@click.group()
@click.version_option(__version__, prog_name="cf")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Codeforces Tool (cf). A Python port of xalanq/cf-tool.

    Run "cf config" first to set your handle, password and code templates.
    If you want to compete, the best command is "cf race".
    """
    if ctx.invoked_subcommand == "completion":
        return  # NOTE: its output is a script the shell evaluates; notes would break it
    try:
        notes = config_module.import_legacy_dir()
    except OSError as e:
        notes = [f"could not import ~/.cf ({e})"]
    for note in notes:
        ui.yellow(f"Go cf-tool settings: {note}")


# ------------------------------------------------------------------- config


_TEMPLATE_PLACEHOLDERS = """\
You can insert placeholders into your template code; "cf gen" replaces them:

  $%U%$   Handle (e.g. xalanq)        $%h%$   Hour   (e.g. 08)
  $%Y%$   Year   (e.g. 2019)         $%m%$   Minute (e.g. 05)
  $%M%$   Month  (e.g. 04)           $%s%$   Second (e.g. 00)
  $%D%$   Day    (e.g. 09)"""

_SCRIPT_PLACEHOLDERS = """\
Template runs 3 scripts in sequence on "cf test":
    before_script   (once)   script   (once per sample)   after_script   (once)
  Leave before/after empty to skip. Run your program in "script" with plain
  stdin/stdout. Script placeholders:

  $%path%$   Dir of source file (e.g. "/home/xalanq/")
  $%full%$   Full source name   (e.g. "a.cpp")
  $%file%$   Source name, no suffix (e.g. "a")
  $%rand%$   Random 8-char string (a-z 0-9)"""


def _config_login(client: Client) -> None:
    if client.handle:
        ui.green(f"Current user: {client.handle}")
    handle_or_email = ui.text(
        "Handle or email:", validate=lambda s: bool(s.strip()) or "Can not be empty"
    )
    ui.cyan("The password is invisible, just type it correctly.")
    password = getpass.getpass("password: ")
    client.config_login(handle_or_email, password)


def _short(path: str | Path) -> str:
    """path with the home folder written as ~, for messages."""
    text, home = str(path), str(Path.home())
    return "~" + text[len(home) :] if text == home or text.startswith(home + os.sep) else text


def _languages(client: Client) -> dict[str, str]:
    """Codeforces' languages, with a note when the list is cf-tool's own."""
    languages, live = client.languages()
    if not live:
        ui.yellow(
            "Not logged in: using cf-tool's built-in language list (log in for the current one)."
        )
    return languages


def _pick_language(languages: dict[str, str], preset: presets.Preset | None = None) -> str:
    """A Codeforces language id, picked by family, then version (best first):
    - with a preset: among its family
    - otherwise, or when the list lacks that family: the family first"""
    options = presets.family(preset, languages) if preset else []
    if not options:
        groups = langs.by_family(languages)
        order = [p.ext for p in presets.PRESETS if p.ext in groups]
        order += sorted((ext for ext in groups if ext not in order), key=langs.family_name)
        ext = ui.select(
            "Which language?",
            [(f"{langs.family_name(ext)}  ({len(groups[ext])})", ext) for ext in order],
        )
        preset = presets.find(ext)
        best = presets.family(preset, languages) if preset else []
        options = best + [member for member in groups[ext] if member not in best]
    family = preset.name if preset else langs.family_name(langs.ext_of(options[0][1]))
    return ui.select(
        f"Submit {family} as:",
        [(name, lid) for lid, name in options],
        default=options[0][0],
        search=len(options) > ui.MAX_SHORTCUTS,
    )


def _config_add_language(cfg: Config, client: Client) -> bool:
    """Set up a language from its preset; returns whether a template was added.
    - a compiler found here; several: the user picks
    - the Codeforces language of that family; the best is pre-selected
    - a starter template written to the config folder"""
    preset = ui.select(
        "Which language?",
        [(p.name, p) for p in presets.PRESETS] + [("Something else (your own scripts)", None)],
    )
    if preset is None:
        _config_add_template(cfg, client)
        return True
    machine = presets.Machine()
    with ui.status(f"Looking for {preset.name} compilers..."):
        chains = preset.detect(machine)
    if not chains:
        ui.red(
            f"No {preset.name} compiler found. To get one: {preset.install_hint(machine.platform)}"
        )
        return False
    chain = chains[0]
    if len(chains) > 1:
        chain = ui.select(
            f"Which {preset.name} compiler?", [(c.label, c) for c in chains], default=chain
        )
    if chain.needs_shim:
        ui.yellow(f"{chain.label} has no bits/stdc++.h, so cf-tool adds one.")
        if all(c.needs_shim for c in chains):
            ui.yellow(f"For GCC, which Codeforces uses: {preset.install_hint(machine.platform)}")
    languages = _languages(client)
    lang = _pick_language(languages, preset)
    template = presets.make_template(preset, chain, lang)
    same = next((i for i, t in enumerate(cfg.template) if t.alias == template.alias), None)
    if same is not None:
        if not ui.confirm(f'Replace your "{template.alias}" template?', default=False):
            return False
        cfg.template[same] = template
    else:
        cfg.template.append(template)
        if len(cfg.template) == 1 or ui.confirm(
            f"Use {preset.name} by default (cf gen, cf parse)?", default=False
        ):
            cfg.default = len(cfg.template) - 1
    cfg.save()
    ui.green(f"Added {preset.name}: {chain.label}, submitting as {languages.get(lang, lang)}.")
    ui.plain(f"Your template: {_short(template.path)} (cf gen copies it; edit it freely)")
    return True


def _config_wizard(cfg: Config, client: Client) -> None:
    """The first `cf config`: log in, set up languages, then say what's next."""
    ui.cyan("Welcome to cf-tool! Two steps: log in, then pick your languages.")
    if client.handle:
        ui.green(f"Logged in as {client.handle}")
    elif ui.confirm("Log in to Codeforces now?", default=True):
        try:
            _config_login(client)
        except CFError as e:
            ui.red(str(e))
            ui.yellow("Not logged in; `cf config` can log in later.")
    added = False
    while True:
        added = _config_add_language(cfg, client) or added
        if not ui.confirm("Add another language?", default=False):
            break
    cfg.save()  # NOTE: the config file now exists, so the next `cf config` shows the menu
    if added:
        ui.green("All set. Next: cf parse 4A, cd cf/contest/4/a, then cf gen, cf test, cf submit.")
    else:
        ui.yellow("No language set up yet: run `cf config` again once a compiler is installed.")


def _config_add_template(cfg: Config, client: Client) -> None:
    """Set up a language by hand: template file, suffixes, alias and scripts."""
    ui.cyan("Add a template")
    lang = _pick_language(_languages(client))

    ui.plain(_TEMPLATE_PLACEHOLDERS)
    path = ui.path(
        "Template file (e.g. ~/template/io.cpp):",
        validate=lambda s: Path(s.strip()).expanduser().is_file() or "Not an existing file",
    )
    path = str(Path(path).expanduser())

    ui.cyan("The template's own suffix is added automatically.")
    extra = ui.text('Other suffixes? (e.g. "cxx cc"), empty is ok:')
    suffixes = [*extra.split(), Path(path).suffix.lstrip(".")]
    suffix = list(dict.fromkeys(s for s in suffixes if s))

    alias = ui.text(
        'Alias (e.g. "cpp" "py"):',
        validate=lambda s: bool(s.strip()) or "Alias can not be empty",
        allow_empty=False,
    )

    ui.green("Scripts:")
    ui.plain(_SCRIPT_PLACEHOLDERS)
    before_script = ui.text('Before script (e.g. "g++ $%full%$ -o $%file%$"), empty is ok:')
    script = ui.text(
        'Script (e.g. "./$%file%$" "python3 $%full%$"):',
        validate=lambda s: bool(s.strip()) or "Script can not be empty",
        allow_empty=False,
    )
    after_script = ui.text('After script (e.g. "rm $%file%$"), empty is ok:')

    cfg.template.append(
        CodeTemplate(alias, lang, path, suffix, before_script, script, after_script)
    )
    if not cfg.template[:-1] or ui.confirm("Make it the default template?", default=True):
        cfg.default = len(cfg.template) - 1
    cfg.save()
    ui.green(f'Added template "{alias}".')


def _template_label(cfg: Config, i: int) -> str:
    template = cfg.template[i]
    star = "* " if i == cfg.default else "  "
    return f"{star}{template.alias}  ({template.path})"


def _pick_template(cfg: Config, message: str) -> int | None:
    if not cfg.template:
        ui.red("There is no template. Please add one")
        return None
    return ui.select(
        message,
        [(_template_label(cfg, i), i) for i in range(len(cfg.template))],
        default=cfg.default,
    )


def _config_remove_template(cfg: Config) -> None:
    idx = _pick_template(cfg, "Delete which template?")
    if idx is None:
        return
    removed = cfg.template.pop(idx)
    if idx == cfg.default:
        cfg.default = 0
    elif idx < cfg.default:
        cfg.default -= 1
    cfg.save()
    ui.green(f'Removed template "{removed.alias}".')


def _config_set_default(cfg: Config) -> None:
    idx = _pick_template(cfg, "Set which template as default?")
    if idx is None:
        return
    cfg.default = idx
    cfg.save()
    ui.green(f'Default is now "{cfg.template[idx].alias}".')


def _config_host(cfg: Config) -> None:
    host_re = re.compile(r"https?://[\w\-]+(\.[\w\-]+)+/?")
    host = ui.text(
        "Host domain (include http:// or https://):",
        default=cfg.host,
        validate=lambda s: bool(host_re.match(s.strip())) or "Invalid host",
        allow_empty=False,
    )
    cfg.host = host.rstrip("/")
    cfg.save()
    ui.green(f"New host domain is {cfg.host}")


def _config_proxy(cfg: Config) -> None:
    proxy_re = re.compile(r"[\w\-]+?://[\w\-]+(\.[\w\-]+)*(:\d+)?")
    ui.green(
        f"Current proxy is {cfg.proxy}" if cfg.proxy else "Current proxy is based on environment"
    )
    ui.cyan("Empty line uses the proxy from the environment.")
    proxy = ui.text(
        'Proxy (e.g. "http://127.0.0.1:2333", "socks5://127.0.0.1:1080"):',
        validate=lambda s: (not s.strip()) or bool(proxy_re.match(s.strip())) or "Invalid proxy",
    )
    cfg.proxy = proxy
    cfg.save()
    ui.green(f"Current proxy is {proxy}" if proxy else "Current proxy is based on environment")


def _config_folders(cfg: Config) -> None:
    ui.cyan("Empty line keeps the current value.")
    cfg.folder_name["root"] = (
        ui.text("Root folder:", default=cfg.folder_name["root"]) or cfg.folder_name["root"]
    )
    for problem_type in PROBLEM_TYPES:
        current = cfg.folder_name[problem_type]
        cfg.folder_name[problem_type] = (
            ui.text(f"{problem_type} folder:", default=current) or current
        )
    cfg.save()
    ui.green("Saved folder names.")


def _config_toggle_gen(cfg: Config) -> None:
    cfg.gen_after_parse = ui.confirm(
        'Run "cf gen" automatically after "cf parse"?', default=cfg.gen_after_parse
    )
    cfg.save()


@main.command()
@cf_command
def config() -> None:
    """Log in and set up languages (a short wizard the first time); also
    templates, host, proxy and folders."""
    cfg, client = _setup()
    if not cfg.path.exists():
        _config_wizard(cfg, client)
        return
    while True:
        gen_state = "on" if cfg.gen_after_parse else "off"
        action = ui.select(
            "Configure cf-tool:",
            [
                ("Login", "login"),
                ("Add a language", "add"),
                ("Delete a template", "delete"),
                ("Set default template", "default"),
                (f'Toggle "gen after parse"  [{gen_state}]', "gen"),
                ("Set host domain", "host"),
                ("Set proxy", "proxy"),
                ("Set folders' name", "folders"),
                ("Done", "done"),
            ],
        )
        if action == "done":
            break
        {
            "login": lambda: _config_login(client),
            "add": lambda: _config_add_language(cfg, client),
            "delete": lambda: _config_remove_template(cfg),
            "default": lambda: _config_set_default(cfg),
            "gen": lambda: _config_toggle_gen(cfg),
            "host": lambda: _config_host(cfg),
            "proxy": lambda: _config_proxy(cfg),
            "folders": lambda: _config_folders(cfg),
        }[action]()


# --------------------------------------------------------------- completion


_TYPE_WORDS = ("contest", "gym", "group", "acmsguru")


def _words(incomplete: str, words) -> list[CompletionItem]:
    """Completions: the words that start with what was typed so far."""
    typed = incomplete.lower()
    return [CompletionItem(w) for w in dict.fromkeys(words) if w.lower().startswith(typed)]


def _offer(*words: str):
    """A Tab completer that offers exactly these words."""
    return lambda ctx, param, incomplete: _words(incomplete, words)


def _problems_here() -> list[str]:
    """Specifiers (546D) that code files in the current folder are named for."""
    try:
        suffixes = {f".{s}" for template in Config.load().template for s in template.suffix}
        cwd = Path.cwd()
        names = [
            codefiles.named_target(entry.name, cwd)
            for entry in cwd.iterdir()
            if entry.suffix in suffixes and entry.is_file()
        ]
    except (CFError, OSError):
        return []  # NOTE: a broken config or folder only costs the suggestions
    return sorted(
        f"{contest}{problem.upper()}" for contest, problem in names if contest and problem
    )


def _specifiers(*extra: str):
    """A Tab completer for specifiers. It offers:
    - the extra words (all, ac)
    - the problem types (contest, gym, ...)
    - the problems this folder's code files are named for (546D)"""
    return lambda ctx, param, incomplete: _words(
        incomplete, [*extra, *_TYPE_WORDS, *_problems_here()]
    )


def _aliases(ctx, param, incomplete: str) -> list[CompletionItem]:
    """Tab completions for `cf gen`: the template aliases, each with its file."""
    try:
        templates = Config.load().template
    except CFError:
        return []
    paths: dict[str, str] = {}
    for template in templates:
        paths.setdefault(template.alias, template.path)
    return [CompletionItem(a, help=p) for a, p in paths.items() if a.startswith(incomplete)]


@main.command()
@click.argument("shell", required=False, type=click.Choice(["bash", "zsh", "fish"]))
@cf_command
def completion(shell: str | None) -> None:
    """Print the Tab-completion script for bash, zsh or fish.

    \b
    zsh:   eval "$(cf completion zsh)"    in ~/.zshrc
    bash:  eval "$(cf completion bash)"   in ~/.bashrc (bash 4.4+)
    fish:  cf completion fish | source    in ~/.config/fish/config.fish
    """
    shell = shell or Path(os.environ.get("SHELL", "")).name
    script = get_completion_class(shell)
    if script is None:
        raise CFError(f'Cannot tell your shell ("{shell}"): run `cf completion zsh`, bash or fish')
    click.echo(script(main, {}, "cf", "_CF_COMPLETE").source())


# ----------------------------------------------------------------- commands


@main.command()
@click.option(
    "-f",
    "--file",
    "file_arg",
    default=None,
    type=click.Path(dir_okay=False),
    help='Path to file, e.g. "a.cpp"',
)
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def submit(file_arg: str | None, specifiers: tuple[str, ...]) -> None:
    """Submit a solution (auto-detects file, contest and problem)."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    filename, index = codefiles.pick(
        file_arg,
        cfg.template,
        Path.cwd(),
        contest=info.contest_id,
        problem=info.problem_id,
        search_folders=True,
    )
    info = _submit_target(info, filename, specifiers, cfg)
    source = codefiles.read_source(filename)
    template = cfg.template[index]
    client.submit(
        info,
        template.lang,
        source,
        filename=filename,
        replace_language=lambda lang_id, offered: _replace_language(
            cfg, template, lang_id, offered
        ),
    )


def _replace_language(cfg: Config, template: CodeTemplate, lang_id: str, offered: dict) -> str:
    """The language to submit as when the submit form lacks lang_id (retired,
    or not allowed in this contest): the user's pick from the template's
    family there, best first; kept in the template after a yes."""
    old = langs.LANGS.get(lang_id) or f"language {lang_id}"
    preset = presets.family_of(template, offered)
    if preset is not None:
        options = presets.family(preset, offered)
    else:
        groups = langs.by_family(offered)
        exts = [*template.suffix, langs.ext_of(old)]
        options = next((groups[ext] for ext in exts if ext in groups and ext != "txt"), [])
    if not options:
        raise CFError(f"The submit form doesn't offer {old}, nor anything like it")
    new_id = ui.select(
        f"The submit form doesn't offer {old}. Submit as:",
        [(name, lid) for lid, name in options] + [("Don't submit", None)],
        default=options[0][0],
    )
    if new_id is None:
        raise CFError("Not submitted")
    name = offered[new_id]
    if ui.confirm(f'Use {name} in your "{template.alias}" template from now on?', default=True):
        template.lang = new_id
        cfg.save()
    return new_id


def _label(contest: str, problem: str) -> str:
    """546D, problem D or contest 546: what a file name points at."""
    if contest and problem:
        return f"{contest}{problem.upper()}"
    return f"problem {problem.upper()}" if problem else f"contest {contest}"


def _submit_target(info: Info, filename: str, specifiers: tuple[str, ...], cfg: Config) -> Info:
    """The problem to submit filename to: info, its gaps filled in from what
    the file's name says. Both a file named for another problem and a target
    read off the name need a yes first."""
    contest, problem = codefiles.named_target(filename, Path.cwd())
    clash = (info.contest_id and contest and contest != info.contest_id) or (
        info.problem_id and problem and problem.lower() != info.problem_id.lower()
    )
    if clash:
        question = f"{filename} looks like {_label(contest, problem)}. Submit it to {info.hint()}?"
        if not ui.confirm(question, default=False):
            raise CFError("Not submitted")
        return info
    missing = [
        value
        for value, known in ((contest, info.contest_id), (problem, info.problem_id))
        if value and not known
    ]
    if not missing:
        return info
    info = _resolve(specifiers + tuple(missing), cfg)
    if not ui.confirm(f"Submit {filename} to {info.hint()}?", default=True):
        raise CFError("Not submitted")
    return info


_MARKS = {"ok": ("✓ ", "green"), "warn": ("! ", "yellow"), "error": ("✗ ", "red")}


@main.command()
@cf_command
def doctor() -> None:
    """Check the setup (languages, compilers, login, Chrome) and say how to fix it."""
    from cf_tool import doctor as checks

    ui.plain(f"cf-tool {__version__}, Python {platform.python_version()}, {sys.platform}")
    try:
        cfg, client = _setup()
        findings = checks.run(cfg, client)
    except CFError as e:  # NOTE: a broken config is a finding too
        findings = [checks.Finding(checks.ERROR, str(e))]
    for finding in findings:
        ui.line(_MARKS[finding.level], (finding.text, ""))
        if finding.fix:
            ui.line(("    " + finding.fix, "cyan"))
    if any(finding.level == checks.ERROR for finding in findings):
        sys.exit(1)


@main.command("list")
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def list_(specifiers: tuple[str, ...]) -> None:
    """List problems' stats of a contest."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    ui.console.print(views.problems_table(client.statis(info)))


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def parse(specifiers: tuple[str, ...]) -> None:
    """Download samples into <root>/<type>/<contest>/<problem>/."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    source, ext = "", ""
    if cfg.gen_after_parse:
        template_path = Path(cfg.default_template().path).expanduser()
        ext = template_path.suffix
        source = templates.substitute_code(codefiles.read_source(template_path), client.handle)
    _, paths = client.parse(info)
    if cfg.gen_after_parse:
        for path in paths:
            templates.generate_file(source, path, ext)


@main.command()
@click.argument("alias", required=False, shell_complete=_aliases)
@cf_command
def gen(alias: str | None) -> None:
    """Generate a code file from a template into the current directory."""
    cfg, client = _setup()
    templates.gen(cfg, client.handle, Path.cwd(), alias)


def _test_args(ctx, param, incomplete: str) -> list[CompletionItem]:
    """Tab completions for `cf test`: the samples here, then file names."""
    try:
        samples = judge.get_sample_ids(Path.cwd())
    except OSError:
        samples = []
    return [*_words(incomplete, samples), CompletionItem(incomplete, type="file")]


def _read_until_eof() -> str:
    """Text typed (or piped) in until end of input."""
    return sys.stdin.read()


def _add_sample(cwd: Path) -> str:
    """Type in a new sample, its input, then its answer (none: run it
    without one); returns its id."""
    end = "Ctrl-Z, then Enter" if sys.platform == "win32" else "Ctrl-D"
    ui.cyan(f"Input of the new sample (end with {end} on an empty line):")
    input_text = _read_until_eof()
    if not input_text.strip():
        raise CFError("No input: no sample added")
    ui.cyan(f"Its answer (end with {end}; none: just run it):")
    answer = _read_until_eof()
    sample_id = judge.add_sample(cwd, input_text, answer)
    saved = f"in{sample_id}.txt" + (f" and ans{sample_id}.txt" if answer.strip() else "")
    ui.green(f"Added sample {sample_id}: {saved}")
    return sample_id


@main.command()
@click.argument("args", nargs=-1, metavar="[FILE] [SAMPLE]...", shell_complete=_test_args)
@click.option(
    "-e", "--epsilon", type=float, help="Accept numbers within this absolute or relative error."
)
@click.option("-i", "--ignore-case", is_flag=True, help="Accept answers in any letter case.")
@click.option(
    "--checker",
    metavar="CMD",
    default="",
    help="Judge with a program, run as: CMD input output answer (exit 0: right).",
)
@click.option("--exact", is_flag=True, help="Compare exactly, whatever the statement allows.")
@click.option("--add", "add_one", is_flag=True, help="Type in a new sample, then test it.")
@click.option(
    "--accept", is_flag=True, help="Keep the output of samples without an answer as their answer."
)
@cf_command
def test(
    args: tuple[str, ...],
    epsilon: float | None,
    ignore_case: bool,
    checker: str,
    exact: bool,
    add_one: bool,
    accept: bool,
) -> None:
    """Compile and run the solution on the samples (in{i}.txt, ans{i}.txt).

    \b
    cf test          every sample
    cf test 2 3      samples 2 and 3
    cf test a.cpp    with this code file
    When cf parse found the statement accepts numbers within an error or any
    letter case, so does cf test; options say otherwise.
    """
    files = [arg for arg in args if not arg.isdigit()]
    if len(files) > 1:
        raise CFError(f"One code file at a time, not {' and '.join(files)}")
    samples = [arg for arg in args if arg.isdigit()]
    cfg = Config.load()
    cwd = Path.cwd()
    if add_one:
        samples = [_add_sample(cwd)]
    info = _resolve((), cfg)  # the directory may say which problem this is
    judge.run_test(
        cfg,
        files[0] if files else None,
        cwd,
        info.contest_id,
        info.problem_id,
        samples=samples,
        epsilon=epsilon,
        ignore_case=ignore_case,
        checker=checker,
        exact=exact,
        accept=accept,
    )


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers("all"))
@cf_command
def watch(specifiers: tuple[str, ...]) -> None:
    """Watch the last 10 submissions of a contest ("cf watch all" for all)."""
    show_all = "all" in specifiers
    specifiers = tuple(s for s in specifiers if s != "all")
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    client.watch(info, count=-1 if show_all else 10, problem_filter=info.problem_id)


@main.command("open")
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def open_(specifiers: tuple[str, ...]) -> None:
    """Open the problem (or contest) page in the browser."""
    cfg, _ = _setup()
    info = _resolve(specifiers, cfg)
    _open_url(info.open_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def stand(specifiers: tuple[str, ...]) -> None:
    """Open the standings page in the browser."""
    cfg, _ = _setup()
    info = _resolve(specifiers, cfg)
    _open_url(info.standings_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@cf_command
def sid(specifiers: tuple[str, ...]) -> None:
    """Open a submission page (defaults to your last submission)."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    if not info.submission_id and client.last_submission:
        info = Info(**client.last_submission, root_path=info.root_path)
    _open_url(info.submission_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers())
@click.pass_context
@cf_command
def race(ctx: click.Context, specifiers: tuple[str, ...]) -> None:
    """Countdown to the contest start, then open pages and parse samples."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    client.race(info)
    url = info.problem_set_url(cfg.host)
    _open_url(url)
    _open_url(url + "/problems")
    ctx.invoke(parse, specifiers=specifiers)


@main.command()
@click.argument("specifiers", nargs=-1, shell_complete=_specifiers("ac"))
@cf_command
def pull(specifiers: tuple[str, ...]) -> None:
    """Pull your (latest or "ac") submission codes into ./<problem>/."""
    ac = "ac" in specifiers
    specifiers = tuple(s for s in specifiers if s != "ac")
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    client.pull(info, Path.cwd(), ac)


@main.command()
@click.argument("args", nargs=-1, metavar="[ac] [HANDLE]", shell_complete=_offer("ac"))
@cf_command
def clone(args: tuple[str, ...]) -> None:
    """Clone all submission codes of a user."""
    ac = "ac" in args
    rest = [a for a in args if a != "ac"]
    _, client = _setup()
    handle = rest[0] if rest else client.handle
    if not handle:
        raise CFError("You have to specify a handle (or login first)")
    client.clone(handle, Path.cwd(), ac)


_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)(?:[-._]?(a|alpha|b|beta|c|rc)[-._]?(\d*))?", re.I)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2}


def version_key(version: str) -> tuple[int, ...] | None:
    """Sortable form of "0.3.0", "v0.3.0a1", "0.3.0-rc.2" (PEP 440 order:
    0.3.0a1 < 0.3.0b1 < 0.3.0rc1 < 0.3.0); None if it is not a version."""
    match = _VERSION_RE.fullmatch(version.strip())
    if not match:
        return None
    release = [int(n) for n in match.group(1).split(".")]
    release += [0] * (4 - len(release))
    tag = (match.group(2) or "").lower()
    return (*release, _PRE_RANK.get(tag, 3), int(match.group(3) or 0))


@main.command()
@cf_command
def upgrade() -> None:
    """Check GitHub for a newer cf-tool release."""
    from curl_cffi import requests as curl_requests

    ui.cyan(f"Current version is {__version__}")
    url = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
    try:
        response = curl_requests.get(
            url,
            timeout=10,
            # GitHub's API refuses requests without a User-Agent
            headers={
                "User-Agent": f"cf-tool/{__version__}",
                "Accept": "application/vnd.github+json",
            },
        )
    except Exception as e:
        raise CFError(f"Cannot reach GitHub: {e}") from e
    if response.status_code != 200:
        raise CFError(f"Cannot list the releases of {REPOSITORY} ({response.status_code})")
    current = version_key(__version__) or ()
    on_prerelease = current[-2:-1] != (3,)
    # pre-releases are offered only to those already running one
    tags = [
        str(release.get("tag_name", ""))
        for release in response.json()
        if not release.get("draft") and (on_prerelease or not release.get("prerelease"))
    ]
    versions = [(key, tag) for tag in tags if (key := version_key(tag))]
    if not versions:
        raise CFError(f"No release of {REPOSITORY} is published on GitHub yet")
    latest_key, latest = max(versions)
    if latest_key <= current:
        ui.green("You already have the latest version")
        return
    ui.green(f"Latest version is {latest}. Upgrade with:")
    ui.plain(f"  uv tool install --force git+https://github.com/{REPOSITORY}@{latest}")
    ui.plain(f"  (or: pipx install --force git+https://github.com/{REPOSITORY}@{latest})")
