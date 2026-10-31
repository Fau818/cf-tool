"""Commands for your Codeforces account: login and logout."""

from __future__ import annotations

import click

from cf_tool import ui
from cf_tool.cli.common import ask_login, cf_command, client


@click.command()
@cf_command
def login() -> None:
    """Log in to Codeforces (the password is saved encrypted, so an expired
    login renews itself)."""
    c = client()
    if c.handle:
        ui.plain(f"Logged in as {c.handle} now; logging in again.")
    ask_login(c)


@click.command()
@cf_command
def logout() -> None:
    """Forget your login: the saved password and session."""
    c = client()
    who = c.handle
    c.logout()
    ui.green(f"Logged out{f' {who}' if who else ''}")


COMMANDS = [login, logout]
