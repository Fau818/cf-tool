"""The failed-sample view: plain diff, and per test case for multi-test samples."""

from rich.console import Console

from cf_tool import views

INPUT = "5\n2\n3\n4\n6\n100\n"  # 2171A: 5 test cases, one line each
ANSWER = ["1", "0", "2", "2", "26"]
CASES = ([0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5])


def render(view) -> str:
    console = Console(width=80, record=True)
    console.print(view)
    return console.export_text()


def test_first_differing_case_only():
    text = render(views.failed_sample(INPUT, ["1", "0", "9", "2", "27"], ANSWER, CASES))
    assert text.startswith("Test case 3 of 5 differs (also 5)\n-----Input of test case 3-----\n4\n")
    assert "9" in text and "26" not in text  # NOTE: case 5's lines aren't shown


def test_a_missing_line_in_a_case():
    text = render(views.failed_sample(INPUT, ["1", "0"], ANSWER, CASES))
    assert "Test case 3 of 5 differs (also 4, 5)" in text and "(missing)" in text


def test_extra_output_after_the_last_case():
    text = render(views.failed_sample(INPUT, ANSWER + ["7"], ANSWER, CASES))
    assert text.startswith("Extra output after the last test case")


def test_an_edited_sample_gets_the_plain_diff():
    text = render(views.failed_sample(INPUT, ["1", "0", "9", "2", "27"], ANSWER + ["x"], CASES))
    assert text.startswith("-----Input-----")


def test_without_cases_the_plain_diff():
    text = render(views.failed_sample("8\n", ["NO"], ["YES"]))
    assert text.startswith("-----Input-----\n8\n") and "NO" in text and "YES" in text


def test_no_output():
    assert "(no output)" in render(views.program_output(""))


def test_contest_times():
    assert views._until(35 * 60) == "35 min"
    assert views._until(5 * 3600 + 12 * 60 + 30) == "5 h 12 min"
    assert views._until(3 * 86400 + 4 * 3600) == "3 days 4 h"
    assert views._until(-5) == "0 min"
    assert views._length(2 * 3600 + 15 * 60) == "2:15"
    assert views._length(14 * 86400) == "14 days"


def test_calendar_file():
    from cf_tool.pages import Contest

    contests = [Contest(2278, "Round 1131 (Div. 3); rated, sure", 1793457300, 8100, "BEFORE")]
    ics = views.to_ics(contests, "https://codeforces.com", now=1793400000)
    lines = ics.split("\r\n")
    assert lines[:3] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//cf-tool//Codeforces contests//EN",
    ]
    assert "DTSTART:20261031T143500Z" in lines and "DTEND:20261031T165000Z" in lines
    assert r"SUMMARY:Round 1131 (Div. 3)\; rated\, sure" in lines  # NOTE: RFC 5545 escapes
    assert lines[-2:] == ["END:VCALENDAR", ""] and "\n" not in ics.replace("\r\n", "")


def test_calendar_lines_are_folded():
    from cf_tool.pages import Contest

    ics = views.to_ics([Contest(1, "x" * 200, 0, 60, "BEFORE")], "https://codeforces.com", 0)
    assert all(len(line) <= 75 for line in ics.split("\r\n"))
    assert ics.replace("\r\n ", "").count("x" * 200) == 1  # NOTE: unfolding restores it


def test_submission_lines_for_a_pipe():
    from cf_tool.pages import Submission

    sub = Submission(
        id=42, name="D - Soldier", lang="GNU G++23", status="${c-accepted}Accepted", end=True
    )
    text = render(views.submission_panel(sub, boxed=False))
    assert "status: Accepted" in text and "│" not in text  # NOTE: what CP Editor looks for
    assert "│" in render(views.submission_panel(sub))
