"""cf config's menu: the settings people change, each picked from a list
whose first choice is the recommended one (and pre-selected, so Enter takes
it), and saved in config.toml. The file stays open to editing too
(cf config --edit)."""

from __future__ import annotations

import copy
import dataclasses
import re
import shutil
from pathlib import Path

import click
from rich.cells import cell_len

from cf_tool import languages, paths, ui
from cf_tool.cli.common import ask_login, client, reset, settings, short
from cf_tool.errors import CFError
from cf_tool.settings import Settings

DEFAULT = ""  # the menu value for the recommended choice: the setting goes away
OTHER = "\0other"  # the menu value for "something not listed"
_WIDTH = 24  # columns for a menu label, so the current values line up


def _row(label: str, value: str) -> str:
    return label + " " * max(2, _WIDTH - cell_len(label)) + value


def _recommended(text: str) -> str:
    return f"{text} (recommended)"


def _offered() -> dict[str, str]:
    """Codeforces' languages: the submit form's when logged in, else the list read last."""
    offered, _ = client().languages()
    return offered


def _tools(key: str) -> list[languages.Tool]:
    language = languages.LANGUAGES.get(key)
    return language.detect(languages.Machine()) if language else []


def _commands(key: str, recommended: bool = False) -> tuple[str, str] | None:
    """(build, run) as cf-tool runs them now, or as it would without the
    settings that change them (recommended); None without a compiler."""
    current = settings()
    if recommended:
        current = copy.copy(current)
        conf = current.language_settings(key)
        plain = dataclasses.replace(conf, build=None, run=None, flags=())
        current.languages = {**current.languages, key: plain}
    try:
        setup = languages.setup(key, current)
    except CFError:
        return None
    return " ".join(setup.build or ()), " ".join(setup.run)


def _shown(command: str) -> str:
    """A command for reading: home as ~."""
    return command.replace(str(Path.home()), "~") if command else "(nothing to build)"


# ┌──────────────────────────────────────────────────────────┐
# │                   What each row shows                    │
# └──────────────────────────────────────────────────────────┘


def _submit_text(key: str, offered: dict[str, str]) -> str:
    conf = settings().language_settings(key)
    chosen = languages.choose_submit(key, conf.submit, offered)
    if chosen is None:
        return f"{conf.submit} (not offered any more)" if conf.submit else "nothing offered"
    return chosen[1] if conf.submit else _recommended(chosen[1])


def _compiler_text(key: str) -> str:
    conf = settings().language_settings(key)
    if conf.compiler:
        return conf.compiler
    tools = _tools(key)
    if not tools:
        return f"none found: {languages.LANGUAGES[key].install_hint()}"
    return _recommended(tools[0].label)


def _commands_text(key: str) -> str:
    conf = settings().language_settings(key)
    if conf.build is not None or conf.run is not None:
        return "your own"
    if conf.flags:
        return f"recommended, with {' '.join(conf.flags)}"
    return "recommended"


def _starter_text(key: str) -> str:
    try:
        _, origin = languages.starter(key, settings())
    except CFError:
        return f"{settings().language_settings(key).template} (missing)"
    return _recommended("built-in") if origin == "built-in" else short(origin)


# ┌──────────────────────────────────────────────────────────┐
# │                       Picking one                        │
# └──────────────────────────────────────────────────────────┘


def pick_language() -> None:
    current = settings()
    keys = [*languages.LANGUAGES, *(k for k in current.languages if k not in languages.LANGUAGES)]
    key = ui.select(
        "Which language do you write in? (cf get writes your starter code in it)",
        [(languages.display_name(k), k) for k in keys],
        default=current.language or "cpp",
    )
    current.update("language", key)


def pick_compiler(key: str) -> None:
    """A language's compiler (or interpreter): the best one found here, one
    of the others found, or a program named by hand."""
    tools = _tools(key)
    conf = settings().language_settings(key)
    choices = []
    if tools:
        choices.append((_recommended(tools[0].label), DEFAULT))
        choices += [(tool.label, tool.program) for tool in tools[1:]]
    else:
        ui.yellow(f"No compiler found here: {languages.LANGUAGES[key].install_hint()}")
    if conf.compiler and conf.compiler not in [value for _, value in choices]:
        choices.append((conf.compiler, conf.compiler))
    choices.append(("Another program...", OTHER))
    program = ui.select(
        f"Which {languages.display_name(key)} compiler?", choices, default=conf.compiler or DEFAULT
    )
    if program == OTHER:
        program = ui.text(
            "The program (on PATH, or its full path):",
            validate=lambda s: bool(shutil.which(s.strip())) or "Not found",
            allow_empty=False,
        )
    if program == DEFAULT:
        settings().remove("compiler", table=key)
    else:
        settings().update("compiler", program, table=key)


def pick_submit(key: str) -> None:
    """The Codeforces language a language is submitted as: the newest of
    its family, or another picked by name (saved as its id)."""
    offered = _offered()
    options = languages.family(key, offered)
    name = languages.display_name(key)
    if not options:
        ui.yellow(f"Codeforces offers no {name} language that cf-tool knows of")
        return
    conf = settings().language_settings(key)
    chosen = languages.choose_submit(key, conf.submit, offered) if conf.submit else None
    lang_id = ui.select(
        f"Submit {name} to Codeforces as:",
        [(_recommended(options[0][1]), DEFAULT)] + [(n, lid) for lid, n in options[1:]],
        default=chosen[0] if chosen and chosen != options[0] else DEFAULT,
        search=len(options) > ui.MAX_SHORTCUTS,
    )
    if lang_id == DEFAULT:
        settings().remove("submit", table=key)
    else:
        settings().update("submit", lang_id, table=key)


def pick_commands(key: str) -> None:
    """How a language is built and run: the recommended commands, those with
    flags of yours added, or commands of your own."""
    name = languages.display_name(key)
    conf = settings().language_settings(key)
    recommended = _commands(key, recommended=True)
    if recommended is None:
        ui.yellow(f"No {name} compiler found here: pick one first")
        return
    build, run = recommended
    ui.plain(f"Recommended:  build  {_shown(build)}\n              run    {_shown(run)}")
    ui.dim("({src} is your code file, {exe} the program built from it, kept out of your folder)")
    own = conf.build is not None or conf.run is not None
    action = ui.select(
        f"How should {name} be built and run?",
        [
            (_recommended("These"), DEFAULT),
            ("These, with flags of mine added (like -DLOCAL)...", "flags"),
            ("Commands of my own...", "own"),
        ],
        default="own" if own else "flags" if conf.flags else DEFAULT,
    )
    if action == "own":
        build_text = ui.text(
            "Build command (empty: nothing to build):",
            default=" ".join(conf.build) if conf.build is not None else build,
        )
        run_text = ui.text(
            "Run command:",
            default=" ".join(conf.run) if conf.run is not None else run,
            allow_empty=False,
        )
        settings().update("build", build_text, table=key)
        settings().update("run", run_text, table=key)
        settings().remove("flags", table=key)
        return
    flags = ui.text("Flags to add:", default=" ".join(conf.flags)) if action == "flags" else ""
    for setting in ("build", "run"):
        settings().remove(setting, table=key)
    if flags:
        settings().update("flags", flags, table=key)
    else:
        settings().remove("flags", table=key)


def pick_starter(key: str) -> None:
    """A language's starter code: the built-in one (or yours in
    templates/template.<ext>), a file of yours anywhere, or the built-in one
    copied to templates/ to change it."""
    own = paths.templates_dir() / f"template.{key}"
    usual = f"Yours: {short(own)}" if own.is_file() else _recommended("The built-in one")
    conf = settings().language_settings(key)
    choices = [(usual, DEFAULT)]
    if conf.template:
        choices.append((conf.template, conf.template))
    choices.append(("A file of mine...", OTHER))
    if not own.is_file() and key in languages.LANGUAGES:
        choices.append((f"The built-in one, copied to {short(own)} for me to change", "copy"))
    picked = ui.select(
        f"Starter code for {languages.display_name(key)}:",
        choices,
        default=conf.template or DEFAULT,
    )
    if picked == "copy":
        paths.write_atomic(own, languages.LANGUAGES[key].starter)
        settings().remove("template", table=key)
        ui.green(f"Wrote {short(own)}: change it as you like; cf get starts from it")
        return
    if picked == OTHER:
        picked = ui.path(
            "The file:",
            validate=lambda s: (bool(s.strip()) and Path(s.strip()).expanduser().is_file())
            or "Not a file",
        ).strip()
    if picked == DEFAULT:
        settings().remove("template", table=key)
    else:
        settings().update("template", picked, table=key)


def pick_proxy() -> None:
    current = settings()
    proxy = ui.text(
        'Proxy, like "socks5://127.0.0.1:1080" (empty: none, or the environment\'s):',
        default=current.proxy,
        validate=lambda s: (not s.strip())
        or bool(re.fullmatch(r"[\w+-]+://[\w.-]+(:\d+)?/?", s.strip()))
        or "Like http://127.0.0.1:7890",
    )
    if proxy:
        current.update("proxy", proxy)
    else:
        current.remove("proxy")


def edit_file() -> None:
    """Open config.toml in the editor; check it once closed."""
    path = paths.config_file()
    current: Settings | None
    try:
        current = settings()
    except CFError as e:  # NOTE: a broken file is opened all the same, to fix it
        ui.yellow(str(e))
        current = None
    if current is not None and not path.exists():
        current.write_default()
    click.edit(filename=str(path))
    reset()
    try:
        reloaded = Settings.load(path)
    except CFError as e:
        raise CFError(f"{e}\nRun cf config --edit again to fix it") from e
    for warning in reloaded.warnings:
        ui.yellow(warning)
    ui.green(f"Saved {short(path)}")


# ┌──────────────────────────────────────────────────────────┐
# │                        The menus                         │
# └──────────────────────────────────────────────────────────┘

_PICKERS = {
    "compiler": pick_compiler,
    "submit": pick_submit,
    "commands": pick_commands,
    "template": pick_starter,
}


def _language_rows(key: str, offered: dict[str, str], prefix: str) -> list[tuple[str, tuple]]:
    rows = [(_row(f"{prefix}submitted as", _submit_text(key, offered)), ("submit", key))]
    if key in languages.LANGUAGES:  # NOTE: a language of config.toml's own: edit the file
        rows = [
            (_row(f"{prefix}compiler", _compiler_text(key)), ("compiler", key)),
            *rows,
            (_row(f"{prefix}build and run", _commands_text(key)), ("commands", key)),
            (_row(f"{prefix}starter code", _starter_text(key)), ("template", key)),
        ]
    return rows


def _do(action) -> None:
    if isinstance(action, tuple):
        _PICKERS[action[0]](action[1])
    elif action == "language":
        pick_language()
    elif action == "proxy":
        pick_proxy()
    elif action == "login":
        ask_login(client())
    elif action == "edit":
        edit_file()


def language_menu(key: str) -> None:
    """The settings of one language, until Back."""
    action = None
    while True:
        rows = _language_rows(key, _offered(), "")
        values = [value for _, value in rows]
        action = ui.select(
            f"{languages.display_name(key)} settings:",
            [*rows, ("Back", "back")],
            default=action if action in values else values[0],
        )
        if action == "back":
            return
        _do(action)


def menu() -> None:
    """cf config: the settings, until Done."""
    action = "language"
    while True:
        current = settings()
        key = current.language or "cpp"
        name = languages.display_name(key)
        rows = [
            (
                _row("Language", name if current.language else f"not picked yet ({name})"),
                "language",
            ),
            *_language_rows(key, _offered(), f"{name} "),
            ("Another language's settings...", "other"),
            (_row("Proxy", current.proxy or "none"), "proxy"),
            (_row("Login", client().handle or "not logged in"), "login"),
            ("Edit config.toml in your editor", "edit"),
            ("Done", "done"),
        ]
        values = [value for _, value in rows]
        action = ui.select(
            f"Settings (saved in {short(current.file)}); Enter changes one:",
            rows,
            default=action if action in values else "language",
        )
        if action == "done":
            return
        if action == "other":
            keys = [
                *languages.LANGUAGES,
                *(k for k in current.languages if k not in languages.LANGUAGES),
            ]
            other = ui.select(
                "Which language?", [(languages.display_name(k), k) for k in keys if k != key]
            )
            language_menu(other)
            continue
        _do(action)
