"""The cf command. Each command's body stays thin: work out the problem and
the file meant, then call one function; errors end in a red line, not a
traceback (CF_DEBUG=1 shows the traceback too)."""

from __future__ import annotations

import click

from cf_tool import __version__, settings as settings_module, ui
from cf_tool.cli import account, problems, setup, submitting, testing
from cf_tool.cli.completion import completion

# cf-tool 0.3's command names, still understood
ALIASES = {"parse": "get", "gen": "new", "watch": "status", "list": "problems"}

# the commands in the order the help lists them
ORDER = [
    "get",
    "test",
    "submit",
    "status",
    "race",
    "open",
    "problems",
    "contests",
    "pick",
    "stress",
    "listen",
    "new",
    "pull",
    "clone",
    "login",
    "logout",
    "langs",
    "config",
    "doctor",
    "upgrade",
    "completion",
]


class Group(click.Group):
    """Commands listed in a useful order, and the old names as aliases."""

    def get_command(self, ctx, cmd_name):
        return super().get_command(ctx, ALIASES.get(cmd_name, cmd_name))

    def list_commands(self, ctx):
        names = super().list_commands(ctx)
        return sorted(names, key=lambda name: ORDER.index(name) if name in ORDER else len(ORDER))


@click.group(cls=Group, context_settings={"help_option_names": ["-h", "--help"]})
# NOTE: CP Editor reads the version as the digits after a v
@click.version_option(__version__, prog_name="cf", message="cf-tool v%(version)s")
@click.pass_context
def main(ctx: click.Context) -> None:
    """cf-tool: Codeforces from your terminal.

    \b
    cf get 2050       folders, samples and starter code for contest 2050
    cd 2050/a
    cf test           build and run your code on the samples
    cf submit         submit it, and watch the verdict
    """
    if ctx.invoked_subcommand == "completion":
        return  # NOTE: its output is a script the shell evaluates; notes would break it
    try:
        notes = settings_module.migrate()
    except OSError as e:
        notes = [f"Could not move your old settings ({e})"]
    for note in notes:
        ui.yellow(note)


# one line each in cf --help
SHORT_HELP = {
    "get": "Set up problems: folders, samples, starter code",
    "test": "Run your code on the problem's tests",
    "submit": "Submit your code and watch the verdict",
    "status": "Your submissions, refreshed until judged",
    "race": "Count down to a contest, then get its problems",
    "open": "Open a problem, the standings, or a submission",
    "problems": "A contest's problems and how many solved them",
    "contests": "Upcoming contests",
    "pick": "A random unsolved problem to practice on",
    "stress": "Random tests until your code and a brute force differ",
    "listen": "Receive problems from Competitive Companion",
    "new": "A code file from your starter code",
    "pull": "Download the code of your submissions",
    "clone": "Download the code of all of a user's submissions",
    "login": "Log in to Codeforces",
    "logout": "Forget your login",
    "langs": "How each language is built, run and submitted",
    "config": "Open the settings in your editor",
    "doctor": "Check the setup and say how to fix it",
    "upgrade": "Check GitHub for a newer cf-tool",
    "completion": "The Tab-completion script for your shell",
}

for module in (problems, testing, submitting, account, setup):
    for command in module.COMMANDS:
        main.add_command(command)
main.add_command(completion)
for name, text in SHORT_HELP.items():
    main.commands[name].short_help = text
