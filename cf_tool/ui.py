"""Console output and interactive prompts.

Output stays as the Go tool's simple coloured lines (no panels). Prompts use
questionary for arrow-key selection / fuzzy filtering / inline validation when
attached to a terminal, and fall back to plain typed input otherwise (pipes,
CI, the test harness) so nothing hangs waiting on a TTY that isn't there.
"""

from __future__ import annotations

import sys
from typing import Callable, Sequence, TypeVar

from rich.console import Console

console = Console(highlight=False)

T = TypeVar("T")

# (label, value) pair for select(); value is returned, label is shown.
Choice = tuple[str, T]
# A validator returns True when ok, or an error message string to show.
Validator = Callable[[str], "bool | str"]


def cyan(message: str) -> None:
    console.print(message, style="cyan")


def green(message: str) -> None:
    console.print(message, style="green")


def red(message: str) -> None:
    console.print(message, style="red")


def yellow(message: str) -> None:
    console.print(message, style="yellow")


def plain(message: str) -> None:
    console.print(message)


def scanline() -> str:
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        print("\nInterrupted.")
        sys.exit(1)


# --------------------------------------------------------------- interactive

_QMARK = "?"


def interactive() -> bool:
    """True when both ends are a real terminal, so questionary can run."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _style():
    import questionary

    return questionary.Style(
        [
            ("qmark", "fg:cyan bold"),
            ("question", "bold"),
            ("answer", "fg:green bold"),
            ("pointer", "fg:cyan bold"),
            ("highlighted", "fg:cyan bold"),
            ("selected", "fg:green"),
            ("instruction", "fg:#888888"),
            ("text", ""),
        ]
    )


def _cancelled(answer) -> None:
    """questionary returns None when the user hits Ctrl-C/Esc."""
    if answer is None:
        print("\nInterrupted.")
        sys.exit(1)


def choose_index(max_len: int) -> int:
    """Prompt until the user enters a valid index in [0, max_len)."""
    cyan("Please choose one (index): ")
    while True:
        text_in = scanline().strip()
        if text_in.isdigit() and 0 <= int(text_in) < max_len:
            return int(text_in)
        red("Invalid index! Please try again: ")


def yes_or_no(note: str) -> bool:
    cyan(note)
    while True:
        text_in = scanline().strip()
        if text_in in ("y", "Y"):
            return True
        if text_in in ("n", "N"):
            return False
        red("Invalid input. Please input again: ")


def select(
    message: str,
    choices: Sequence[Choice],
    *,
    default: T | None = None,
    search: bool = False,
) -> T:
    """Pick one value from (label, value) choices.

    Interactive: arrow-key list, optionally type-to-filter (search=True).
    Fallback: numbered list + index typing (keeps choose_index patchable).
    """
    if not interactive():
        cyan(message)
        for i, (label, _) in enumerate(choices):
            plain(f"{i:3}: {label}")
        return choices[choose_index(len(choices))][1]

    import questionary

    q_choices = [questionary.Choice(title=label, value=value) for label, value in choices]
    answer = questionary.select(
        message,
        choices=q_choices,
        default=default,
        style=_style(),
        qmark=_QMARK,
        use_search_filter=search,
        use_jk_keys=not search,
        show_selected=True,
    ).ask()
    _cancelled(answer)
    return answer


def text(
    message: str,
    *,
    default: str = "",
    validate: Validator | None = None,
    allow_empty: bool = True,
) -> str:
    """Free-text input with optional inline validation."""
    if not interactive():
        while True:
            cyan(message)
            value = scanline().strip()
            if not value and default:
                return default
            ok = True if validate is None else validate(value)
            if ok is True and (value or allow_empty):
                return value
            red(ok if isinstance(ok, str) else "Invalid input. Please input again: ")

    import questionary

    def _validate(raw: str):
        raw = raw.strip()
        if not raw and not allow_empty and not default:
            return "This field can not be empty"
        if validate is None or not raw:
            return True
        return validate(raw)

    answer = questionary.text(
        message, default=default, validate=_validate, style=_style(), qmark=_QMARK
    ).ask()
    _cancelled(answer)
    return answer.strip()


def path(message: str, *, validate: Validator | None = None) -> str:
    """Filesystem path input with tab/auto completion."""
    if not interactive():
        while True:
            cyan(message)
            value = scanline().strip()
            ok = True if validate is None else validate(value)
            if ok is True:
                return value
            red(ok if isinstance(ok, str) else "Invalid path. Please input again: ")

    import questionary

    answer = questionary.path(message, validate=validate, style=_style(), qmark=_QMARK).ask()
    _cancelled(answer)
    return answer.strip()


def confirm(message: str, *, default: bool = False) -> bool:
    """Yes/no prompt."""
    if not interactive():
        suffix = " (Y/n)? " if default else " (y/N)? "
        return yes_or_no(message + suffix)

    import questionary

    answer = questionary.confirm(
        message, default=default, style=_style(), qmark=_QMARK, auto_enter=False
    ).ask()
    _cancelled(answer)
    return answer
