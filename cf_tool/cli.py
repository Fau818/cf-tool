"""Click CLI mirroring the original cf-tool command surface:

  cf config | submit | list | parse | gen | test | watch | open | stand
     | sid | race | pull | clone | upgrade

Each command body stays thin: parse specifiers via args.parse_args, then call
one client/judge/templates function.
"""

from __future__ import annotations

import functools
import getpass
import re
import sys
import webbrowser
from pathlib import Path

import click

from cf_tool import __version__, judge, templates, ui
from cf_tool import config as config_module
from cf_tool.args import Info, parse_args
from cf_tool.client import Client
from cf_tool.config import PROBLEM_TYPES, CodeTemplate, Config
from cf_tool.errors import CFError


def _setup() -> tuple[Config, Client]:
    cfg = Config.load()
    return cfg, Client(cfg)


def _resolve(specifiers: tuple[str, ...], cfg: Config) -> Info:
    return parse_args(list(specifiers), Path.cwd(), cfg)


def _open_url(url: str) -> None:
    ui.green(f"Open {url}")
    webbrowser.open(url)


def cf_command(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except CFError as e:
            ui.red(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(1)

    return wrapper


@click.group()
@click.version_option(__version__, prog_name="cf")
def main() -> None:
    """Codeforces Tool (cf). A Python port of xalanq/cf-tool.

    Run "cf config" first to set your handle, password and code templates.
    If you want to compete, the best command is "cf race".
    """
    for note in config_module.migrate_legacy_dir():
        ui.yellow(f"config migration: {note}")


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


def _config_add_template(cfg: Config, client: Client) -> None:
    ui.cyan("Add a template")
    languages = client.languages()
    lang = ui.select(
        "Language (type to filter):",
        [
            (f"{lid:>3}  {name}", lid)
            for lid, name in sorted(languages.items(), key=lambda kv: kv[1])
        ],
        search=True,
    )
    ui.green(f"{lang}  {languages.get(lang, '')}")

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
    ui.cyan("Empty line uses the proxy from the environment.")
    proxy = ui.text(
        'Proxy (e.g. "http://127.0.0.1:2333", "socks5://127.0.0.1:1080"):',
        default=cfg.proxy,
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
    """Configure handle, password, templates, host and folders."""
    cfg, client = _setup()
    while True:
        gen_state = "on" if cfg.gen_after_parse else "off"
        action = ui.select(
            "Configure cf-tool:",
            [
                ("Login", "login"),
                ("Add a template", "add"),
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
            "add": lambda: _config_add_template(cfg, client),
            "delete": lambda: _config_remove_template(cfg),
            "default": lambda: _config_set_default(cfg),
            "gen": lambda: _config_toggle_gen(cfg),
            "host": lambda: _config_host(cfg),
            "proxy": lambda: _config_proxy(cfg),
            "folders": lambda: _config_folders(cfg),
        }[action]()


# ----------------------------------------------------------------- commands


@main.command()
@click.option("-f", "--file", "file_arg", default=None, help='Path to file, e.g. "a.cpp"')
@click.argument("specifiers", nargs=-1)
@cf_command
def submit(file_arg: str | None, specifiers: tuple[str, ...]) -> None:
    """Submit a solution (auto-detects file, contest and problem)."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    filename, index = templates.get_one_code(file_arg, cfg.template, Path.cwd())
    source = Path(filename).read_text(encoding="utf-8")
    client.submit(info, cfg.template[index].lang, source)


@main.command("list")
@click.argument("specifiers", nargs=-1)
@cf_command
def list_(specifiers: tuple[str, ...]) -> None:
    """List problems' stats of a contest."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    problems = client.statis(info)
    from rich.table import Table
    from rich.text import Text

    table = Table(box=None, header_style="bold")
    for column in ("#", "problem", "passed", "limit", "IO"):
        table.add_column(column, justify="center")
    for prob in problems:
        style = ""
        if "accepted" in prob.state:
            style = "black on green"
        elif "rejected" in prob.state:
            style = "black on red"
        table.add_row(
            *(Text(v, style=style) for v in (prob.id, prob.name, prob.passed, prob.limit, prob.io))
        )
    ui.console.print(table)


@main.command()
@click.argument("specifiers", nargs=-1)
@cf_command
def parse(specifiers: tuple[str, ...]) -> None:
    """Download samples into <root>/<type>/<contest>/<problem>/."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    source, ext = "", ""
    if cfg.gen_after_parse:
        if not cfg.template:
            raise CFError("You have to add at least one code template by `cf config`")
        template_path = Path(cfg.template[cfg.default].path).expanduser()
        ext = template_path.suffix
        source = templates.substitute_code(template_path.read_text(encoding="utf-8"), client.handle)
    _, paths = client.parse(info)
    if cfg.gen_after_parse:
        for path in paths:
            templates.generate_file(source, path, ext)


@main.command()
@click.argument("alias", required=False)
@cf_command
def gen(alias: str | None) -> None:
    """Generate a code file from a template into the current directory."""
    cfg, client = _setup()
    templates.gen(cfg, client.handle, Path.cwd(), alias)


@main.command()
@click.argument("file_arg", metavar="[FILE]", required=False)
@cf_command
def test(file_arg: str | None) -> None:
    """Compile and run the solution against all in{i}.txt/ans{i}.txt pairs."""
    cfg, _ = _setup()
    judge.run_test(cfg, file_arg, Path.cwd())


@main.command()
@click.argument("specifiers", nargs=-1)
@cf_command
def watch(specifiers: tuple[str, ...]) -> None:
    """Watch the last 10 submissions of a contest ("cf watch all" for all)."""
    show_all = "all" in specifiers
    specifiers = tuple(s for s in specifiers if s != "all")
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    client.watch(info, count=-1 if show_all else 10, problem_filter=info.problem_id)


@main.command("open")
@click.argument("specifiers", nargs=-1)
@cf_command
def open_(specifiers: tuple[str, ...]) -> None:
    """Open the problem (or contest) page in the browser."""
    cfg, _ = _setup()
    info = _resolve(specifiers, cfg)
    _open_url(info.open_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1)
@cf_command
def stand(specifiers: tuple[str, ...]) -> None:
    """Open the standings page in the browser."""
    cfg, _ = _setup()
    info = _resolve(specifiers, cfg)
    _open_url(info.standings_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1)
@cf_command
def sid(specifiers: tuple[str, ...]) -> None:
    """Open a submission page (defaults to your last submission)."""
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    if not info.submission_id and client.last_submission:
        info = Info(**client.last_submission, root_path=info.root_path)
    _open_url(info.submission_url(cfg.host))


@main.command()
@click.argument("specifiers", nargs=-1)
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
@click.argument("specifiers", nargs=-1)
@cf_command
def pull(specifiers: tuple[str, ...]) -> None:
    """Pull your (latest or "ac") submission codes into ./<problem>/."""
    ac = "ac" in specifiers
    specifiers = tuple(s for s in specifiers if s != "ac")
    cfg, client = _setup()
    info = _resolve(specifiers, cfg)
    client.pull(info, Path.cwd(), ac)


@main.command()
@click.argument("args", nargs=-1, metavar="[ac] [HANDLE]")
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


@main.command()
@cf_command
def upgrade() -> None:
    """Check PyPI for a newer cf-tool release."""
    from curl_cffi import requests as curl_requests

    ui.cyan(f"Current version is {__version__}")
    try:
        data = curl_requests.get("https://pypi.org/pypi/cf-tool/json", timeout=10).json()
        latest = data["info"]["version"]
    except Exception:
        raise CFError("Cannot fetch the latest version from PyPI")
    if latest == __version__:
        ui.green("You already have the latest version")
    else:
        ui.green(f"Latest version is {latest}. Upgrade with:")
        ui.plain("  uv pip install -U cf-tool   (or: pip install -U cf-tool)")


if __name__ == "__main__":
    main()
