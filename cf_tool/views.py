"""Rich renderables: submission table/panel, problem list, failed-sample diff.

Pure functions from data to renderables — printing (and live refresh) is
the caller's business. Every foreign string goes in as Text, never markup.
"""

from __future__ import annotations

import operator
from typing import Callable

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cf_tool.pages import StatisInfo, Submission
from cf_tool.problem import Cases

LinesAlike = Callable[[str, str], bool]  # (output line, answer line): counts as it?

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


def program_output(text: str) -> Group:
    """What a program printed, its first lines only."""
    if not text.strip():
        return Group(Text("-----Output-----", style="cyan"), Text("(no output)", style="dim"))
    return Group(
        Text("-----Output-----", style="cyan"),
        _clip(text.rstrip("\n").split("\n"), INPUT_LINES),
    )


def _diff_rows(
    rows: list[int], out_lines: list[str], ans_lines: list[str], same: LinesAlike = operator.eq
) -> Table:
    """Output and answer side by side for these line indexes, differences marked."""
    diff = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", pad_edge=False)
    diff.add_column("#", justify="right", style="dim")
    diff.add_column("output")
    diff.add_column("answer")
    for i in rows:
        out = out_lines[i] if i < len(out_lines) else None
        ans = ans_lines[i] if i < len(ans_lines) else None
        alike = out is not None and ans is not None and same(out, ans)
        diff.add_row(
            str(i + 1),
            (
                Text("(missing)", style="dim")
                if out is None
                else Text(out, style="" if alike else "red")
            ),
            (
                Text("(missing)", style="dim")
                if ans is None
                else Text(ans, style="" if alike else "green")
            ),
        )
    return diff


def _failing_case(
    input_lines: list[str],
    out_lines: list[str],
    ans_lines: list[str],
    cases: Cases,
    same: LinesAlike,
) -> Group | None:
    """The first test case of a multi-test sample that differs: its input and
    lines only; None when the saved layout doesn't fit these files."""
    input_cases, answer_cases = cases
    if len(input_cases) != len(input_lines) or len(answer_cases) != len(ans_lines):
        return None  # NOTE: the sample was edited after cf parse
    bad = sorted(
        {
            answer_cases[i]
            for i in range(len(ans_lines))
            if i >= len(out_lines) or not same(out_lines[i], ans_lines[i])
        }
    )
    total = max(input_cases, default=0)
    if not bad:  # NOTE: every case matches, so the output only runs longer
        extra = list(range(len(ans_lines), len(out_lines)))[:DIFF_LINES]
        return Group(
            Text("Extra output after the last test case", style="red"),
            _diff_rows(extra, out_lines, ans_lines, same),
        )
    case = bad[0]
    others = f" (also {', '.join(map(str, bad[1:]))})" if len(bad) > 1 else ""
    rows = [i for i, c in enumerate(answer_cases) if c == case][:DIFF_LINES]
    case_input = [line for line, c in zip(input_lines, input_cases) if c == case]
    return Group(
        Text(f"Test case {case} of {total} differs{others}", style="red"),
        Text(f"-----Input of test case {case}-----", style="cyan"),
        _clip(case_input, INPUT_LINES),
        _diff_rows(rows, out_lines, ans_lines, same),
    )


def failed_sample(
    input_text: str,
    out_lines: list[str],
    ans_lines: list[str],
    cases: Cases | None = None,
    same: LinesAlike = operator.eq,
) -> Group:
    """What went wrong in a sample (same: whether an output line counts as
    its answer line):
    - multi-test, with cases known: the first differing test case only
    - otherwise: the input, then output and answer side by side"""
    input_lines = input_text.rstrip("\n").split("\n")
    if cases is not None:
        view = _failing_case(input_lines, out_lines, ans_lines, cases, same)
        if view is not None:
            return view
    total = max(len(out_lines), len(ans_lines))
    first_bad = next(
        (
            i
            for i in range(total)
            if i >= len(out_lines) or i >= len(ans_lines) or not same(out_lines[i], ans_lines[i])
        ),
        0,
    )
    # long outputs: show a window starting a little before the first difference
    start = max(0, first_bad - 5) if total > DIFF_LINES else 0
    stop = min(total, start + DIFF_LINES)
    parts: list[RenderableType] = [
        Text("-----Input-----", style="cyan"),
        _clip(input_lines, INPUT_LINES),
        _diff_rows(list(range(start, stop)), out_lines, ans_lines, same),
    ]
    if start or stop < total:
        parts.append(Text(f"lines {start + 1}–{stop} of {total}", style="dim"))
    return Group(*parts)
