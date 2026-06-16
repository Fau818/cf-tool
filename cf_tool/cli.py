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


def _config_login(client: Client) -> None:
    if client.handle:
        ui.green(f"Current user: {client.handle}")
    ui.cyan("Configure handle/email and password")
    ui.cyan("Note: The password is invisible, just type it correctly.")
    print("handle/email: ", end="", flush=True)
    handle_or_email = ui.scanline().strip()
    password = getpass.getpass("password: ")
    client.config_login(handle_or_email, password)


def _config_add_template(cfg: Config, client: Client) -> None:
    ui.cyan("Add a template")
    languages = client.languages()
    ui.cyan("Language list:")
    for lang_id, name in sorted(languages.items(), key=lambda kv: kv[1]):
        ui.plain(f"{lang_id:>5}: {name}")
    ui.cyan('Select a language (e.g. "89"): ')
    while True:
        lang = ui.scanline().strip()
        if lang in languages:
            ui.green(languages[lang])
            break
        ui.red("Invalid index. Please input again")

    ui.plain("""Template:
  You can insert some placeholders into your template code. When generate a code from the
  template, cf will replace all placeholders by following rules:

  $%U%$   Handle (e.g. xalanq)
  $%Y%$   Year   (e.g. 2019)
  $%M%$   Month  (e.g. 04)
  $%D%$   Day    (e.g. 09)
  $%h%$   Hour   (e.g. 08)
  $%m%$   Minute (e.g. 05)
  $%s%$   Second (e.g. 00)""")
    ui.cyan('Template absolute path(e.g. "~/template/io.cpp"): ')
    while True:
        path = ui.scanline().strip()
        expanded = Path(path).expanduser()
        if expanded.is_file():
            path = str(expanded)
            break
        ui.red(f"{path} is invalid. Please input again: ")

    ui.cyan("The suffix of template above will be added by default.")
    ui.cyan('Other suffix? (e.g. "cxx cc"), empty is ok: ')
    suffixes = ui.scanline().split()
    suffixes.append(Path(path).suffix.lstrip("."))
    suffix = list(dict.fromkeys(s for s in suffixes if s))

    ui.cyan('Template\'s alias (e.g. "cpp" "py"): ')
    while True:
        alias = ui.scanline().strip()
        if alias:
            break
        ui.red("Alias can not be empty. Please input again: ")

    ui.green("Script in template:")
    ui.plain("""Template will run 3 scripts in sequence when you run "cf test":
    - before_script   (execute once)
    - script          (execute the number of samples times)
    - after_script    (execute once)
  You could set "before_script" or "after_script" to empty string, meaning not executing.
  You have to run your program in "script" with standard input/output (no need to redirect).

  You can insert some placeholders in your scripts. When execute a script,
  cf will replace all placeholders by following rules:

  $%path%$   Path to source file (Excluding $%full%$, e.g. "/home/xalanq/")
  $%full%$   Full name of source file (e.g. "a.cpp")
  $%file%$   Name of source file (Excluding suffix, e.g. "a")
  $%rand%$   Random string with 8 character (including "a-z" "0-9")""")
    ui.cyan('Before script (e.g. "g++ $%full%$ -o $%file%$.exe -std=c++11"), empty is ok: ')
    before_script = ui.scanline().strip()
    ui.cyan('Script (e.g. "./$%file%$.exe" "python3 $%full%$"): ')
    while True:
        script = ui.scanline().strip()
        if script:
            break
        ui.red("Script can not be empty. Please input again: ")
    ui.cyan('After script (e.g. "rm $%file%$.exe"), empty is ok: ')
    after_script = ui.scanline().strip()

    cfg.template.append(
        CodeTemplate(alias, lang, path, suffix, before_script, script, after_script)
    )
    if ui.yes_or_no("Make it default (y/n)? "):
        cfg.default = len(cfg.template) - 1
    cfg.save()


def _list_templates(cfg: Config) -> None:
    for i, template in enumerate(cfg.template):
        star = "[green]*[/green]" if i == cfg.default else " "
        ui.console.print(f'{star}{i:2}: "{template.alias}" "{template.path}"')


def _config_remove_template(cfg: Config) -> None:
    ui.cyan("Remove a template")
    if not cfg.template:
        ui.red("There is no template. Please add one")
        return
    _list_templates(cfg)
    idx = ui.choose_index(len(cfg.template))
    cfg.template.pop(idx)
    if idx == cfg.default:
        cfg.default = 0
    elif idx < cfg.default:
        cfg.default -= 1
    cfg.save()


def _config_set_default(cfg: Config) -> None:
    ui.cyan("Set default template")
    if not cfg.template:
        ui.red("There is no template. Please add one")
        return
    _list_templates(cfg)
    cfg.default = ui.choose_index(len(cfg.template))
    cfg.save()


def _config_host(cfg: Config) -> None:
    ui.green(f"Current host domain is {cfg.host}")
    ui.cyan('Set a new host domain (e.g. "https://codeforces.com")')
    ui.cyan('Note: Don\'t forget the "http://" or "https://"')
    host_re = re.compile(r"https?://[\w\-]+(\.[\w\-]+)+/?")
    while True:
        host = ui.scanline().strip()
        if host_re.match(host):
            break
        ui.red(f'Invalid host "{host}"')
    cfg.host = host.rstrip("/")
    ui.green(f"New host domain is {cfg.host}")
    cfg.save()


def _config_proxy(cfg: Config) -> None:
    if cfg.proxy:
        ui.green(f"Current proxy is {cfg.proxy}")
    else:
        ui.green("Current proxy is based on environment")
    ui.cyan('Set a new proxy (e.g. "http://127.0.0.1:2333", "socks5://127.0.0.1:1080")')
    ui.cyan("Enter empty line if you want to use default proxy from environment")
    proxy_re = re.compile(r"[\w\-]+?://[\w\-]+(\.[\w\-]+)*(:\d+)?")
    while True:
        proxy = ui.scanline().strip()
        if not proxy or proxy_re.match(proxy):
            break
        ui.red(f'Invalid proxy "{proxy}"')
    cfg.proxy = proxy
    if proxy:
        ui.green(f"Current proxy is {proxy}")
    else:
        ui.green("Current proxy is based on environment")
    cfg.save()


def _config_folders(cfg: Config) -> None:
    ui.cyan("Set folders' name")
    ui.cyan("Enter empty line if you don't want to change the value")
    ui.green(f"Root path (current: {cfg.folder_name['root']})")
    if value := ui.scanline().strip():
        cfg.folder_name["root"] = value
    for problem_type in PROBLEM_TYPES:
        ui.green(f"{problem_type} path (current: {cfg.folder_name[problem_type]})")
        if value := ui.scanline().strip():
            cfg.folder_name[problem_type] = value
    cfg.save()


@main.command()
@cf_command
def config() -> None:
    """Configure handle, password, templates, host and folders."""
    cfg, client = _setup()
    ui.cyan("Configure the tool")
    ui.plain("0) login")
    ui.plain("1) add a template")
    ui.plain("2) delete a template")
    ui.plain("3) set default template")
    ui.plain('4) run "cf gen" after "cf parse"')
    ui.plain("5) set host domain")
    ui.plain("6) set proxy")
    ui.plain("7) set folders' name")
    index = ui.choose_index(8)
    if index == 0:
        _config_login(client)
    elif index == 1:
        _config_add_template(cfg, client)
    elif index == 2:
        _config_remove_template(cfg)
    elif index == 3:
        _config_set_default(cfg)
    elif index == 4:
        cfg.gen_after_parse = ui.yes_or_no('Run "cf gen" after "cf parse" (y/n)? ')
        cfg.save()
    elif index == 5:
        _config_host(cfg)
    elif index == 6:
        _config_proxy(cfg)
    elif index == 7:
        _config_folders(cfg)


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
