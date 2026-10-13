"""Console output and interactive prompts.

Messages are the Go tool's coloured lines; richer views (tables, panels)
live in views.py. Every helper here prints text literally — never as Rich
markup — because it carries foreign text (sample I/O, file names, messages
from Codeforces) where "[a]" or "[/]" must not be eaten or crash.

Prompts use questionary for arrow-key selection / fuzzy filtering / inline
validation when attached to a terminal, and fall back to plain typed input
otherwise (pipes, CI, the test harness) so nothing hangs waiting on a TTY.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from typing import Callable, Iterator, Sequence, TypeVar

from rich.console import Console
from rich.errors import LiveError
from rich.text import Text

console = Console(highlight=False)

T = TypeVar("T")

# (label, value) pair for select(); value is returned, label is shown.
Choice = tuple[str, T]
# A validator returns True when ok, or an error message string to show.
Validator = Callable[[str], "bool | str"]


@dataclass(frozen=True)
class Heading:
    """A line between groups of select() choices; it cannot be selected."""

    text: str


def cyan(message: str) -> None:
    console.print(message, style="cyan", markup=False)


def green(message: str) -> None:
    console.print(message, style="green", markup=False)


def red(message: str) -> None:
    console.print(message, style="red", markup=False)


def yellow(message: str) -> None:
    console.print(message, style="yellow", markup=False)


def plain(message: str) -> None:
    console.print(message, markup=False)


def line(*parts: tuple[str, str]) -> None:
    """One line of differently styled (text, style) parts."""
    console.print(Text.assemble(*parts))


@contextlib.contextmanager
def status(message: str) -> Iterator[None]:
    """A spinner while something slow runs; a no-op off a terminal, or on an
    older Rich that cannot nest it inside another live display."""
    if not console.is_terminal:
        yield
        return
    spinner = console.status(Text(message, style="cyan"))
    try:
        spinner.start()
    except LiveError:
        yield
        return
    try:
        yield
    finally:
        spinner.stop()


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


# questionary's shortcut keys: 1-9, 0, a-z
MAX_SHORTCUTS = 36


def _ask(question):
    """The answer to a questionary question; None when the user cancels
    (Ctrl-C, or Esc in a menu). Unlike Question.ask(), prints nothing then."""
    try:
        return question.unsafe_ask()
    except KeyboardInterrupt:
        return None


def _cancelled(answer) -> None:
    """Exit when the user cancelled the prompt (answer None)."""
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


def select(
    message: str,
    choices: Sequence[Choice | Heading],
    *,
    default: T | None = None,
    search: bool = False,
) -> T:
    """Pick one value from (label, value) choices, which Headings may split
    into groups; default is pre-selected.

    Interactive: arrow keys, plus a number/letter key per item (lists of up
    to MAX_SHORTCUTS) or type-to-filter (search=True); Enter confirms.
    Fallback: numbered list + index typing (keeps choose_index patchable).
    """
    options = [c for c in choices if not isinstance(c, Heading)]
    if not interactive():
        cyan(message)
        number = 0
        for c in choices:
            if isinstance(c, Heading):
                plain(f"     {c.text}")  # in line with the labels
            else:
                plain(f"{number:3}: {c[0]}")
                number += 1
        return options[choose_index(len(options))][1]

    import questionary
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.keys import Keys
    from questionary.prompts.common import InquirerControl

    shortcuts = not search and len(options) <= MAX_SHORTCUTS
    q_choices = [
        (
            questionary.Separator(c.text)
            if isinstance(c, Heading)
            else questionary.Choice(title=c[0], value=c[1])
        )
        # a filtered list has no groups left to head
        for c in (options if search else choices)
    ]
    question = questionary.select(
        message,
        choices=q_choices,
        default=default,
        style=_style(),
        qmark=_QMARK,
        use_search_filter=search,
        use_shortcuts=shortcuts,
        # j/k move the pointer, unless typing filters or they are shortcuts
        # themselves (items 20 and 21 get "j" and "k")
        use_jk_keys=not search and not (shortcuts and len(options) > 19),
        show_selected=search,  # long lists: which item the pointer is on
    )
    app = question.application
    # questionary also paints the default as "selected", in reverse video: a
    # solid bar that stays put when the pointer moves. The pointer alone shows
    # where the answer is (Enter takes the item under it).
    for control in app.layout.find_all_controls():
        if isinstance(control, InquirerControl):
            control.selected_options.clear()
    escape = KeyBindings()

    # Esc cancels, like Ctrl-C. Left to prompt_toolkit, Esc then Enter (Meta-Enter)
    # submits the prompt's hidden input line, answering "" instead of an item.
    @escape.add(Keys.Escape, eager=True)
    def _(event) -> None:
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    app.key_bindings = merge_key_bindings([app.key_bindings, escape])
    answer = _ask(question)
    if answer is not None and answer not in [value for _, value in options]:
        answer = None  # some other key ended the prompt without an item: cancelled
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

    answer = _ask(
        questionary.text(message, default=default, validate=_validate, style=_style(), qmark=_QMARK)
    )
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

    answer = _ask(questionary.path(message, validate=validate, style=_style(), qmark=_QMARK))
    _cancelled(answer)
    return answer.strip()


def confirm(message: str, *, default: bool = False) -> bool:
    """Yes/no prompt; an empty answer takes the default."""
    if not interactive():
        cyan(message + (" (Y/n)? " if default else " (y/N)? "))
        while True:
            text_in = scanline().strip().lower()
            if not text_in:
                return default
            if text_in in ("y", "n"):
                return text_in == "y"
            red("Invalid input. Please input again: ")

    import questionary

    answer = _ask(
        questionary.confirm(
            message, default=default, style=_style(), qmark=_QMARK, auto_enter=False
        )
    )
    _cancelled(answer)
    return answer
