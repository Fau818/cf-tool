"""Console output and interactive prompts, styled after the Go tool's
simple colored lines (no panels/decoration)."""

from __future__ import annotations

import sys

from rich.console import Console

console = Console(highlight=False)


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


def choose_index(max_len: int) -> int:
    """Prompt until the user enters a valid index in [0, max_len)."""
    cyan("Please choose one (index): ")
    while True:
        text = scanline().strip()
        if text.isdigit() and 0 <= int(text) < max_len:
            return int(text)
        red("Invalid index! Please try again: ")


def yes_or_no(note: str) -> bool:
    cyan(note)
    while True:
        text = scanline().strip()
        if text in ("y", "Y"):
            return True
        if text in ("n", "N"):
            return False
        red("Invalid input. Please input again: ")
