"""Rich renderables: submission table/panel, problem list, failed-sample diff.

Pure functions from data to renderables — printing (and live refresh) is
the caller's business. Every foreign string goes in as Text, never markup.
"""

from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cf_tool.pages import StatisInfo, Submission

# a failed sample shows at most this many lines of input / of the diff
INPUT_LINES = 30
DIFF_LINES = 40


def submission_table(submissions: list[Submission], problem_id: str = "") -> Table:
    """Recent submissions (the Go tool's `cf watch` table), optionally one problem's."""
    table = Table(box=box.ROUNDED, border_style="dim", header_style="bold cyan")
    # long columns may wrap on narrow terminals; the short ones never do
    for column in ("#", "when", "problem", "lang", "status", "time", "memory"):
        table.add_column(column, justify="center", no_wrap=column in ("#", "time", "memory"))
    for sub in submissions:
        if problem_id and sub.problem_index() != problem_id.lower():
            continue
        status, style = sub.styled_status()
        table.add_row(
            str(sub.id),
            Text(sub.when),
            Text(sub.name),
            Text(sub.lang),
            Text(status, style=style),
            sub.parse_time(),
            sub.parse_memory(),
        )
    return table


def submission_panel(sub: Submission) -> Panel:
    """Single-submission detail view (the Go tool's display after submit)."""
    status, style = sub.styled_status()
    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="right", style="bold cyan")
    grid.add_column()
    grid.add_row("#:", str(sub.id))
    grid.add_row("when:", Text(sub.when))
    grid.add_row("prob:", Text(sub.name))
    grid.add_row("lang:", Text(sub.lang))
    grid.add_row("status:", Text(status, style=style or "white"))
    grid.add_row("time:", sub.parse_time() if sub.end else "-")
    grid.add_row("memory:", sub.parse_memory() if sub.end else "-")
    border = style if sub.end and style else "dim"
    return Panel(grid, box=box.ROUNDED, border_style=border, expand=False)


def problems_table(problems: list[StatisInfo]) -> Table:
    """A contest's problems (`cf list`): solved rows green, failed ones red."""
    table = Table(box=box.ROUNDED, border_style="dim", header_style="bold cyan")
    for column in ("#", "problem", "passed", "limit", "IO"):
        table.add_column(column, justify="center")
    for prob in problems:
        style = ""
        if "accepted" in prob.state:
            style = "black on green"
        elif "rejected" in prob.state:
            style = "black on red"
        table.add_row(
            *(Text(v) for v in (prob.id, prob.name, prob.passed, prob.limit, prob.io)),
            style=style,
        )
    return table


def _clip(lines: list[str], limit: int) -> Text:
    text = Text("\n".join(lines[:limit]))
    if len(lines) > limit:
        text.append(f"\n… {len(lines) - limit} more lines", style="dim")
    return text


def failed_sample(input_text: str, out_lines: list[str], ans_lines: list[str]) -> Group:
    """Input, then output and answer side by side with differing lines marked."""
    total = max(len(out_lines), len(ans_lines))
    first_bad = next(
        (
            i
            for i in range(total)
            if i >= len(out_lines) or i >= len(ans_lines) or out_lines[i] != ans_lines[i]
        ),
        0,
    )
    # long outputs: show a window starting a little before the first difference
    start = max(0, first_bad - 5) if total > DIFF_LINES else 0
    stop = min(total, start + DIFF_LINES)

    diff = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", pad_edge=False)
    diff.add_column("#", justify="right", style="dim")
    diff.add_column("output")
    diff.add_column("answer")
    for i in range(start, stop):
        out = out_lines[i] if i < len(out_lines) else None
        ans = ans_lines[i] if i < len(ans_lines) else None
        same = out == ans
        diff.add_row(
            str(i + 1),
            (
                Text("(missing)", style="dim")
                if out is None
                else Text(out, style="" if same else "red")
            ),
            (
                Text("(missing)", style="dim")
                if ans is None
                else Text(ans, style="" if same else "green")
            ),
        )
    parts: list[RenderableType] = [
        Text("-----Input-----", style="cyan"),
        _clip(input_text.rstrip("\n").split("\n"), INPUT_LINES),
        diff,
    ]
    if start or stop < total:
        parts.append(Text(f"lines {start + 1}–{stop} of {total}", style="dim"))
    return Group(*parts)
