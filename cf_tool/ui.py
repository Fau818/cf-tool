"""Console output and interactive prompts.

Messages are colored lines; richer views (tables, panels) live in views.py.
Every helper here prints text literally, never as Rich markup, because it
carries foreign text (sample I/O, file names, messages from Codeforces)
where "[a]" or "[/]" must not be eaten or crash.

Prompts use questionary for arrow-key selection / fuzzy filtering / inline
validation when attached to a terminal, and fall back to plain typed input
otherwise (pipes, CI, the test harness) so nothing hangs waiting on a TTY.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from typing import Callable, Iterator, Sequence, TypeVar

from rich.cells import cell_len
from rich.console import Console
from rich.errors import LiveError
from rich.text import Text

console = Console(highlight=False, emoji=False)  # NOTE: ":x:" in a sample is text

# The palette: soft colors that read well on dark and light terminals. Plain
# color names in styles ("green", "bold cyan") are drawn in these, so every
# message, table and menu shares them.
ACCENT = "#7aa2f7"  # blue: what to look at, names, the menu pointer
SUCCESS = "#9ece6a"
WARNING = "#e0af68"
ERROR = "#f7768e"
MUTED = "#8a8fa8"  # secondary text: values, times, hints
INFO = "#7dcfff"  # a lighter blue, for the odd verdict that is neither
_COLORS = {
    "cyan": ACCENT,
    "green": SUCCESS,
    "yellow": WARNING,
    "red": ERROR,
    "blue": INFO,
    "dim": MUTED,
    "white": "default",
}

T = TypeVar("T")

# (label, value) pair for select(); value is returned, label is shown.
Choice = tuple[str, T]
# A validator returns True when ok, or an error message string to show.
Validator = Callable[[str], "bool | str"]


@dataclass(frozen=True)
class Heading:
    """A line between groups of select() choices; it cannot be selected."""

    text: str


class Canceled(Exception):
    """The user canceled a prompt (Esc, Ctrl-C, or no input at all)."""


def styled(style: str) -> str:
    """A style with the palette's colors for the plain color names in it."""
    return " ".join(_COLORS.get(word, word) for word in style.split())


def line(*parts: tuple[str, str]) -> None:
    """One line of differently styled (text, style) parts."""
    console.print(Text.assemble(*((text, styled(style)) for text, style in parts)))


def info(message: str) -> None:
    line(("› ", "cyan bold"), (message, ""))


def success(message: str) -> None:
    line(("✓ ", "green bold"), (message, ""))


def warn(message: str) -> None:
    line(("! ", "yellow bold"), (message, ""))


def error(message: str) -> None:
    line(("✗ ", "red bold"), (message, ""))


def plain(message: str) -> None:
    console.print(message, markup=False)


def dim(message: str) -> None:
    console.print(message, style=MUTED, markup=False)


# the names messages had before the palette
cyan, green, yellow, red = info, success, warn, error


def row(label: str, value: str = "", note: str = "") -> str:
    """A menu item that shows a setting: its label, its current value (in a
    quieter color, lined up with the others) and a note ("recommended")."""
    return f"{label}{_FIELD}{value}{_FIELD}{note}"


_FIELD = "\x1f"  # NOTE: between a row's parts; select() lays them out


@contextlib.contextmanager
def status(message: str) -> Iterator[Callable[[str], None]]:
    """A spinner while something slow runs; yields a function that changes
    its message. A no-op off a terminal, or on an older Rich that cannot nest
    it inside another live display."""
    if not console.is_terminal:
        yield lambda text: None
        return
    spinner = console.status(Text(message, style=ACCENT), spinner_style=ACCENT)
    try:
        spinner.start()
    except LiveError:
        yield lambda text: None
        return
    try:
        yield lambda text: spinner.update(Text(text, style=ACCENT))
    finally:
        spinner.stop()


def scanline() -> str:
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        raise Canceled() from None


# --------------------------------------------------------------- interactive

_QMARK = "◆"
_POINTER = "❯"


def interactive() -> bool:
    """True when both ends are a real terminal, so questionary can run."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _style():
    import questionary

    return questionary.Style(
        [
            ("qmark", f"fg:{ACCENT} bold"),
            ("question", "bold"),
            ("answer", f"fg:{SUCCESS} bold"),
            ("pointer", f"fg:{ACCENT} bold"),
            ("highlighted", f"fg:{ACCENT} bold"),
            ("selected", f"fg:{SUCCESS}"),
            ("separator", f"fg:{MUTED}"),
            ("instruction", f"fg:{MUTED}"),
            ("value", f"fg:{MUTED}"),
            ("value-on", f"fg:{ACCENT}"),
            ("note", f"fg:{SUCCESS}"),
            ("text", ""),
        ]
    )


# questionary's shortcut keys: 1-9, 0, a-z
MAX_SHORTCUTS = 36


def _ask(question):
    """The answer to a questionary question; None when the user cancels
    (Ctrl-C, or Esc). Unlike Question.ask(), prints nothing then."""
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.keys import Keys

    escape = KeyBindings()

    # NOTE: Esc cancels, like Ctrl-C. Left to prompt_toolkit, Esc then Enter
    # \     (Meta-Enter) submits the prompt's input line as it is
    @escape.add(Keys.Escape, eager=True)
    def _(event) -> None:
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    app = question.application
    app.key_bindings = merge_key_bindings([app.key_bindings, escape])
    try:
        return question.unsafe_ask()
    except KeyboardInterrupt:
        return None


def _canceled(answer) -> None:
    """Raise Canceled when the user canceled the prompt (answer None)."""
    if answer is None:
        raise Canceled()


def choose_index(count: int, default: int = 0) -> int:
    """Ask until the user types a number from 1 to count (Enter: the
    default); returns the index of the choice."""
    cyan(f"Your choice (1-{count}, Enter for {default + 1}): ")
    while True:
        text_in = scanline().strip()
        if not text_in:
            return default
        if text_in.isdigit() and 1 <= int(text_in) <= count:
            return int(text_in) - 1
        red(f"A number from 1 to {count}, please: ")


def _laid_out(labels: Sequence[str]) -> list[str]:
    """Menu labels with their row() parts lined up: each label padded to the
    longest, then its value, then its note."""
    width = max(
        (cell_len(label.split(_FIELD)[0]) for label in labels if _FIELD in label), default=0
    )
    laid = []
    for label in labels:
        if _FIELD in label:
            name, value, note = label.split(_FIELD)
            label = name + " " * (width - cell_len(name)) + _FIELD + value + _FIELD + note
        laid.append(label)
    return laid


def _plain_row(label: str) -> str:
    """A laid-out row as plain text (off a terminal)."""
    if _FIELD not in label:
        return label
    name, value, note = label.split(_FIELD)
    return f"{name}   {value}" + (f"  ({note})" if note else "")


def _styled_rows(control) -> None:
    """Draw row() parts in their colors: the value quiet (bright under the
    pointer), the note green."""
    original = control.text  # NOTE: the bound _get_choice_tokens, taken at construction

    def tokens():
        drawn = []
        for style, text in original():
            if _FIELD not in text:
                drawn.append((style, text))
                continue
            name, value, note = text.split(_FIELD)
            on = "highlighted" in style
            drawn.append((style, name + "   "))
            drawn.append(("class:value-on" if on else "class:value", value))
            if note:
                drawn.append(("class:note", f"  {note}"))
        return drawn

    control.text = tokens


def _enter_picks(control):
    """Enter takes the item under the pointer, as in questionary, but the
    answer line then shows a row() by its label alone."""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    bindings = KeyBindings()

    @bindings.add(Keys.ControlM, eager=True)
    def _(event) -> None:
        choice = control.get_pointed_at()
        if isinstance(choice.title, str) and _FIELD in choice.title:
            choice.title = choice.title.split(_FIELD)[0].rstrip()
        control.is_answered = True
        event.app.exit(result=choice.value)

    return bindings


def select(
    message: str,
    choices: Sequence[Choice | Heading],
    *,
    default: T | None = None,
    search: bool = False,
) -> T:
    """Pick one value from (label, value) choices, which Headings may split
    into groups; default is pre-selected. Raises Canceled on Esc or Ctrl-C.

    Interactive: arrow keys, plus a number/letter key per item (lists of up
    to MAX_SHORTCUTS) or type-to-filter (search=True); Enter confirms.
    Fallback: numbered list + index typing (keeps choose_index patchable).
    """
    options = [c for c in choices if not isinstance(c, Heading)]
    labels = iter(_laid_out([c[0] for c in options]))
    laid = [c if isinstance(c, Heading) else (next(labels), c[1]) for c in choices]
    options = [c for c in laid if not isinstance(c, Heading)]
    if not interactive():
        info(message)
        number = 0
        for c in laid:
            if isinstance(c, Heading):
                plain(f"     {c.text}")  # NOTE: in line with the labels
            else:
                number += 1
                plain(f"{number:3}) {_plain_row(c[0])}")
        values = [value for _, value in options]
        first = values.index(default) if default in values else 0
        return options[choose_index(len(options), first)][1]

    import questionary
    from prompt_toolkit.key_binding import merge_key_bindings
    from questionary.prompts.common import InquirerControl

    shortcuts = not search and len(options) <= MAX_SHORTCUTS
    q_choices = [
        (
            questionary.Separator(c.text)
            if isinstance(c, Heading)
            else questionary.Choice(title=c[0], value=c[1])
        )
        # a filtered list has no groups left to head
        for c in (options if search else laid)
    ]
    question = questionary.select(
        message,
        choices=q_choices,
        default=default,
        style=_style(),
        qmark=_QMARK,
        pointer=_POINTER,
        use_search_filter=search,
        use_shortcuts=shortcuts,
        # j/k move the pointer, unless typing filters or they are shortcuts
        # themselves (items 20 and 21 get "j" and "k")
        use_jk_keys=not search and not (shortcuts and len(options) > 19),
        show_selected=search,  # long lists: which item the pointer is on
    )
    # questionary also paints the default as "selected", in reverse video: a
    # solid bar that stays put when the pointer moves. The pointer alone shows
    # where the answer is (Enter takes the item under it).
    app = question.application
    for control in app.layout.find_all_controls():
        if isinstance(control, InquirerControl):
            control.selected_options.clear()
            _styled_rows(control)
            app.key_bindings = merge_key_bindings([app.key_bindings, _enter_picks(control)])
    answer = _ask(question)
    if answer is not None and answer not in [value for _, value in options]:
        answer = None  # some other key ended the prompt without an item: canceled
    _canceled(answer)
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
    _canceled(answer)
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
    _canceled(answer)
    return answer.strip()


def confirm(message: str, *, default: bool = False) -> bool:
    """Yes/no prompt; an empty answer, or no input at all, takes the default."""
    if not interactive():
        cyan(message + (" (Y/n)? " if default else " (y/N)? "))
        while True:
            try:
                text_in = input().strip().lower()
            except EOFError:
                return default  # NOTE: nobody to ask (input from a pipe, or none)
            except KeyboardInterrupt:
                raise Canceled() from None
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
    _canceled(answer)
    return answer
