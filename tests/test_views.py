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
