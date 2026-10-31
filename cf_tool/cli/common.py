"""What the commands share: error handling, the settings and the client
(loaded once per run), finding the problem a command means, logging in on
the spot, the language for starter code, and building a program."""

from __future__ import annotations

import functools
import getpass
import os
import sys
import traceback
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from cf_tool import languages, ui, workspace
from cf_tool.build import BuildFailed, Program
from cf_tool.errors import CFError
from cf_tool.settings import Settings
from cf_tool.workspace import ProblemInfo, Target

if TYPE_CHECKING:
    from cf_tool.codeforces.client import Client


def fail(message: str) -> None:
    if os.environ.get("CF_DEBUG"):
        traceback.print_exc()
    ui.red(message)
    sys.exit(1)


def cf_command(f):
    """A command whose errors end in a red line, not a traceback."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except CFError as e:
            fail(str(e))
        except OSError as e:  # NOTE: unreadable or unwritable files and the like
            fail(str(e))
        except ui.Canceled:
            ui.dim("Canceled.")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(1)

    return wrapper


# ┌──────────────────────────────────────────────────────────┐
# │                  Settings and the client                 │
# └──────────────────────────────────────────────────────────┘

_settings: Settings | None = None
_client: "Client | None" = None


def settings() -> Settings:
    """The settings, read once per run; their warnings are shown then."""
    global _settings
    if _settings is None:
        _settings = Settings.load()
        for warning in _settings.warnings:
            ui.yellow(warning)
    return _settings


def client() -> "Client":
    global _client
    if _client is None:
        from cf_tool.codeforces.client import Client

        _client = Client(settings())
    return _client


def reset() -> None:
    """Forget the settings and client read so far (tests run many commands)."""
    global _settings, _client
    _settings = _client = None


def open_url(url: str) -> None:
    ui.line(("Opening ", "cyan"), (url, ""))
    webbrowser.open(url)


def short(path: Path | str) -> str:
    """A path for messages: relative to the current folder when inside it,
    else with the home folder as ~."""
    path = Path(path)
    try:
        relative = path.resolve().relative_to(Path.cwd().resolve())
        return str(relative) if str(relative) != "." else "."
    except ValueError:
        pass
    text, home = str(path), str(Path.home())
    return "~" + text[len(home) :] if text == home or text.startswith(home + os.sep) else text


# ┌──────────────────────────────────────────────────────────┐
# │                   The problem meant                      │
# └──────────────────────────────────────────────────────────┘


def target_of(specs: tuple[str, ...] | list[str], cwd: Path | None = None) -> Target:
    """The target the arguments name, with the folder filling in the rest."""
    cwd = cwd or Path.cwd()
    return workspace.parse_target(list(specs), workspace.here(cwd))


def problem_folder_of(target: Target, cwd: Path | None = None) -> Path | None:
    """The folder of target's problem, wherever it is from here."""
    return workspace.locate(target, cwd or Path.cwd(), settings().root_folder())


def code_file_among(args: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    """(the code file among the arguments, the other arguments): an existing
    file in a known language is the file, not a problem."""
    known = languages.code_extensions(settings())
    files = [a for a in args if Path(a).suffix.lower() in known and Path(a).is_file()]
    if len(files) > 1:
        raise CFError(f"One code file at a time, not {' and '.join(files)}")
    return (files[0] if files else None), tuple(a for a in args if a not in files)


# ┌──────────────────────────────────────────────────────────┐
# │                  Languages and programs                  │
# └──────────────────────────────────────────────────────────┘


def starter_language(asked: str | None = None) -> str:
    """The language for starter code: the one asked for (-l), else the
    setting; the first time, the user picks one and it is saved."""
    current = settings()
    if asked:
        key = languages.language_key(asked, current) or asked.lower().lstrip(".")
        if key not in languages.LANGUAGES and key not in current.languages:
            raise CFError(f"cf-tool doesn't know the language {asked!r} (cf langs lists them)")
        return key
    if current.language:
        return current.language
    if not ui.interactive():  # NOTE: nobody to ask: C++, this once
        ui.yellow("No language picked yet: writing C++ (set language in cf config, or give -l)")
        return "cpp"
    keys = [
        *(
            key for key in languages.LANGUAGES if key != "c"
        ),  # NOTE: C++ covers it; .c files still work
        *(key for key in current.languages if key not in languages.LANGUAGES),
    ]
    key = ui.select(
        "Which language do you write in?",
        [(languages.display_name(key), key) for key in keys],
        default="cpp",
    )
    current.update("language", key)
    ui.green(
        f"Starter code in {languages.display_name(key)} from now on "
        f"(the language in {short(current.file)}; -l picks another once)"
    )
    return key


def program(path: Path, key: str | None = None) -> Program:
    """The code file and how its language builds and runs it here."""
    key = key or languages.language_key(path, settings())
    if key is None:
        raise CFError(f"cf-tool doesn't know what language {path.name} is in")
    return Program(path, languages.setup(key, settings(), source=path))


def build(target: Program) -> None:
    """Build a program (unless its build is cached), saying so; a compiler
    error is shown in full, then raised as CFError."""
    if target.setup.build is None:
        return
    try:
        with ui.status(f"Building {target.name} with {target.setup.tool}..."):
            built = target.build()
    except BuildFailed as e:
        if e.output:
            ui.plain(e.output)
        raise CFError(str(e)) from None
    if not built.cached:
        ui.line((f"Built {target.name} with {target.setup.tool} in {built.seconds:.1f}s", "dim"))
    if built.messages:
        ui.plain(built.messages)


def write_starter(folder: Path, target: Target, info: ProblemInfo | None, key: str) -> Path | None:
    """Write the starter code into a problem's folder as <problem>.<ext>,
    unless the folder has code in that language already; returns the file
    written, if any."""
    language = languages.LANGUAGES.get(key)
    extensions = language.extensions if language else (key,)
    has_code = any(
        entry.suffix.lower().lstrip(".") in extensions and not workspace.is_helper(entry.name)
        for entry in (folder.iterdir() if folder.is_dir() else [])
    )
    path = folder / f"{target.problem.lower()}.{key}"
    if has_code or path.exists():
        return None
    text, _ = languages.starter(key, settings())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        languages.render(text, starter_values(target, info)), encoding="utf-8", newline=""
    )
    return path


def starter_values(target: Target | None, info: ProblemInfo | None) -> dict[str, str]:
    """What starter code's placeholders are filled with."""
    from cf_tool.codeforces.session import Session

    return {
        "handle": _client.handle if _client is not None else Session.load().handle,
        "problem": target.label if target and target.problem else "",
        "name": info.name if info else "",
        "url": info.url if info else "",
    }


# ┌──────────────────────────────────────────────────────────┐
# │                        Logging in                        │
# └──────────────────────────────────────────────────────────┘


def ask_login(c: "Client") -> None:
    """Ask for the handle and password, and log in."""
    current = c.session.handle_or_email
    who = ui.text(
        "Handle or email:",
        default=current,
        validate=lambda s: bool(s.strip()) or "Your Codeforces handle or email",
        allow_empty=False,
    )
    if sys.stdin.isatty():
        ui.dim("The password stays hidden as you type it.")
        password = getpass.getpass("Password: ")
    else:
        # NOTE: piped in (printf ... | cf login): nothing to hide, and getpass
        # \     would only warn that it cannot hide it
        ui.cyan("Password:")
        password = ui.scanline()
    if not password:
        raise CFError("No password: not logged in")
    c.login(who, password)


def ensure_login(c: "Client") -> None:
    """Log in first when no login is saved (a terminal asks for one)."""
    if c.can_log_in:
        return
    if not ui.interactive():
        raise CFError("Not logged in: run cf login")
    ui.yellow("You're not logged in to Codeforces yet.")
    ask_login(c)
