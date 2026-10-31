"""cf config's menu: every setting in one list, grouped by language. Each
setting opens a list whose first choice is the recommended one (already
selected, so Enter keeps it); Esc goes back. Everything is saved in
config.toml, which stays open to editing too (cf config --edit)."""

from __future__ import annotations

import copy
import dataclasses
import re
import shutil
from pathlib import Path

import click

from cf_tool import languages, paths, ui
from cf_tool.cli.common import client, reset, settings, short
from cf_tool.errors import CFError
from cf_tool.settings import Settings

DEFAULT = ""  # the menu value for the recommended choice: the setting goes away
OTHER = "\0other"  # the menu value for "something not listed"
RECOMMENDED = "recommended"

# the languages the menus offer; C is left to its files (.c still works),
# since hardly anybody picks it over C++
LISTED = [key for key in languages.LANGUAGES if key != "c"]


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


def _compiler_row(key: str) -> str:
    conf = settings().language_settings(key)
    label = "Interpreter" if key == "py" else "Compiler"
    if conf.compiler:
        return ui.row(label, conf.compiler)
    tools = _tools(key)
    if not tools:
        return ui.row(label, f"none found: {languages.LANGUAGES[key].install_hint()}")
    return ui.row(label, tools[0].label, RECOMMENDED)


def _submit_row(key: str, offered: dict[str, str]) -> str:
    conf = settings().language_settings(key)
    chosen = languages.choose_submit(key, conf.submit, offered)
    if chosen is None:
        value = f"{conf.submit}, not offered any more" if conf.submit else "nothing offered"
        return ui.row("Submitted as", value)
    return ui.row("Submitted as", chosen[1], "" if conf.submit else RECOMMENDED)


def _commands_row(key: str) -> str:
    conf = settings().language_settings(key)
    if conf.build is not None or conf.run is not None:
        return ui.row("Build and run", "your own commands")
    if conf.flags:
        return ui.row("Build and run", f"recommended + {' '.join(conf.flags)}")
    return ui.row("Build and run", "the recommended commands", RECOMMENDED)


def _starter_row(key: str) -> str:
    try:
        _, origin = languages.starter(key, settings())
    except CFError:
        return ui.row("Starter code", f"{settings().language_settings(key).template} (missing)")
    if origin == "built-in":
        return ui.row("Starter code", "the built-in one", RECOMMENDED)
    return ui.row("Starter code", short(origin))


# ┌──────────────────────────────────────────────────────────┐
# │                       Picking one                        │
# └──────────────────────────────────────────────────────────┘


def pick_language() -> None:
    current = settings()
    keys = [*LISTED, *(k for k in current.languages if k not in languages.LANGUAGES)]
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
        choices.append((ui.row(tools[0].label, "", RECOMMENDED), DEFAULT))
        choices += [(tool.label, tool.program) for tool in tools[1:]]
    else:
        ui.warn(f"No compiler found here: {languages.LANGUAGES[key].install_hint()}")
    if conf.compiler and conf.compiler not in [value for _, value in choices]:
        choices.append((conf.compiler, conf.compiler))
    choices.append(("Another program...", OTHER))
    program = ui.select(
        f"Which {languages.display_name(key)} compiler?", choices, default=conf.compiler or DEFAULT
    )
    if program == OTHER:
        program = ui.path(
            "The program (its name on PATH, or its path; Tab completes):",
            validate=lambda s: bool(shutil.which(str(Path(s.strip()).expanduser())))
            or "Not a program that runs",
        )
        program = str(Path(program).expanduser()) if "/" in program else program
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
        ui.warn(f"Codeforces offers no {name} language that cf-tool knows of")
        return
    conf = settings().language_settings(key)
    chosen = languages.choose_submit(key, conf.submit, offered) if conf.submit else None
    lang_id = ui.select(
        f"Submit {name} to Codeforces as:",
        [(ui.row(options[0][1], "", RECOMMENDED), DEFAULT)] + [(n, lid) for lid, n in options[1:]],
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
        ui.warn(f"No {name} compiler found here: pick one first")
        return
    build, run = recommended
    ui.line(("Recommended  ", "dim"), ("build  ", "dim"), (_shown(build), "cyan"))
    ui.line(("             ", "dim"), ("run    ", "dim"), (_shown(run), "cyan"))
    ui.dim("{src} is your code file, {exe} the program built from it (kept out of your folder)")
    own = conf.build is not None or conf.run is not None
    action = ui.select(
        f"How should {name} be built and run?",
        [
            (ui.row("These", "", RECOMMENDED), DEFAULT),
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
    conf = settings().language_settings(key)
    if own.is_file():
        choices = [(ui.row(f"Yours: {short(own)}", "", RECOMMENDED), DEFAULT)]
    else:
        choices = [(ui.row("The built-in one", "", RECOMMENDED), DEFAULT)]
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
        ui.success(f"Wrote {short(own)}: change it as you like; cf get starts from it")
        return
    if picked == OTHER:
        picked = ui.path(
            "The file (Tab completes):",
            validate=lambda s: (bool(s.strip()) and Path(s.strip()).expanduser().is_file())
            or "Not a file",
        )
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
        ui.warn(str(e))
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
        ui.warn(warning)
    ui.success(f"Saved {short(path)}")


# ┌──────────────────────────────────────────────────────────┐
# │                        The menu                          │
# └──────────────────────────────────────────────────────────┘

_PICKERS = {
    "compiler": pick_compiler,
    "submit": pick_submit,
    "commands": pick_commands,
    "template": pick_starter,
}


def _shown_languages() -> tuple[list[str], list[str]]:
    """(the languages the menu shows, those it leaves out): the one for new
    problems first, then those installed here or set in config.toml."""
    current = settings()
    main = current.language or "cpp"
    shown, missing = [main], []
    for key in LISTED:
        if key == main:
            continue
        if key in current.languages or _tools(key):
            shown.append(key)
        else:
            missing.append(key)
    shown += [k for k in current.languages if k not in languages.LANGUAGES and k not in shown]
    return shown, missing


def _language_rows(key: str, offered: dict[str, str]) -> list:
    rows: list = [ui.Heading(f"── {languages.display_name(key)} ──")]
    if key in languages.LANGUAGES:
        rows.append((_compiler_row(key), ("compiler", key)))
    rows.append((_submit_row(key, offered), ("submit", key)))
    if key in languages.LANGUAGES:  # NOTE: config.toml's own languages: edit the file
        rows.append((_commands_row(key), ("commands", key)))
        rows.append((_starter_row(key), ("template", key)))
    return rows


def menu() -> None:
    """cf config: every setting in one list, until Done or Esc."""
    action = "language"
    while True:
        current = settings()
        offered = _offered()
        shown, missing = _shown_languages()
        who = client().handle or "not logged in"
        rows: list = [
            ui.Heading("── General ──"),
            (
                ui.row(
                    "Language for new problems",
                    languages.display_name(current.language or "cpp"),
                    "" if current.language else "not picked yet",
                ),
                "language",
            ),
            (ui.row("Proxy", current.proxy or "none"), "proxy"),
        ]
        for key in shown:
            rows += _language_rows(key, offered)
        if missing:
            names = ", ".join(languages.display_name(k) for k in missing)
            rows.append(ui.Heading(f"── not installed here: {names} ──"))
        rows += [
            ui.Heading(""),
            ("Edit config.toml in your editor", "edit"),
            ("Done", "done"),
        ]
        values = [r[1] for r in rows if not isinstance(r, ui.Heading)]
        try:
            action = ui.select(
                f"cf-tool settings · {who} · {short(current.file)}",
                rows,
                default=action if action in values else "language",
            )
        except ui.Canceled:
            return  # NOTE: Esc on the menu itself: done
        if action == "done":
            return
        try:
            if isinstance(action, tuple):
                _PICKERS[action[0]](action[1])
            elif action == "language":
                pick_language()
            elif action == "proxy":
                pick_proxy()
            elif action == "edit":
                edit_file()
        except ui.Canceled:
            pass  # NOTE: Esc in a list: back to the menu
