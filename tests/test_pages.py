"""Parser tests: hand-written snippets plus pages trimmed from the live site
(tests/fixtures, fetched 2026-10-12)."""

from pathlib import Path

import pytest

from cf_tool.errors import CFError
from cf_tool.codeforces.pages import (
    describe_page,
    find_code,
    find_countdown,
    find_csrf,
    find_error_message,
    find_handle,
    find_message,
    find_samples,
    has_turnstile,
    is_browser_check,
    is_captcha_error,
    is_cloudflare_challenge,
    is_gate,
    is_standard_io,
    is_verification_gate,
    parse_languages,
    parse_problems,
    parse_submissions,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


LOGGED_IN = '<script>var userInfo = { handle = "tourist" };</script>'
CSRF = "<script>window.x = { csrf='deadbeef1234' };</script>"

SAMPLES_BR = """
<div class="sample-test">
  <div class="input"><div class="title">Input</div><pre>1 2<br />3 4</pre></div>
  <div class="output"><div class="title">Output</div><pre>3</pre></div>
  <div class="input"><div class="title">Input</div><pre>5</pre></div>
  <div class="output"><div class="title">Output</div><pre>10</pre></div>
</div>
"""

SAMPLES_DIV_LINES = """
<div class="sample-test">
  <div class="input"><div class="title">Input</div><pre>
    <div class="test-example-line test-example-line-even test-example-line-0">3</div>
    <div class="test-example-line test-example-line-odd test-example-line-1">1 2 3</div>
  </pre></div>
  <div class="output"><div class="title">Output</div><pre>6</pre></div>
</div>
"""

SAMPLES_ESCAPED = """
<div class="input"><pre>a&lt;b &amp;&amp; c&gt;d</pre></div>
<div class="output"><pre>yes</pre></div>
"""


def test_find_handle():
    assert find_handle(LOGGED_IN) == "tourist"
    assert find_handle("<html>logged out</html>") is None


def test_find_csrf():
    assert find_csrf(CSRF) == "deadbeef1234"
    assert find_csrf('<meta data-csrf="abc123def"/>') == "abc123def"
    with pytest.raises(CFError, match="Cannot find csrf"):
        find_csrf("<html></html>")


def test_find_samples_br_format():
    inputs, outputs = find_samples(SAMPLES_BR)
    assert inputs == ["1 2\n3 4\n", "5\n"]
    assert outputs == ["3\n", "10\n"]


def test_find_samples_div_line_format():
    inputs, outputs = find_samples(SAMPLES_DIV_LINES)
    assert inputs == ["3\n1 2 3\n"]
    assert outputs == ["6\n"]


def test_find_samples_unescapes_entities():
    inputs, _ = find_samples(SAMPLES_ESCAPED)
    assert inputs == ["a<b && c>d\n"]


def test_find_samples_mismatch():
    with pytest.raises(CFError, match="Cannot parse sample"):
        find_samples('<div class="input"><pre>1</pre></div>')


def test_is_standard_io():
    modern = (
        '<div class="input-file input-standard"><div class="property-title">input</div>'
        'standard input</div><div class="output-file output-standard">'
        '<div class="property-title">output</div>standard output</div>'
    )
    assert is_standard_io(modern) is True
    # old problems (e.g. 4A) say stdin/stdout and may lack the -standard class
    old = (
        '<div class="input-file"><div class="property-title">input</div>stdin</div>'
        '<div class="output-file"><div class="property-title">output</div>stdout</div>'
    )
    assert is_standard_io(old) is True
    file_io = (
        '<div class="input-file"><div class="property-title">input</div>input.txt</div>'
        '<div class="output-file"><div class="property-title">output</div>output.txt</div>'
    )
    assert is_standard_io(file_io) is False


def test_find_countdown():
    assert find_countdown('<span class="countdown">01:02:03</span>') == 3723
    with pytest.raises(CFError):
        find_countdown("<html></html>")


def test_find_error_message():
    html = '<span class="error for__source">You have submitted exactly the same code before</span>'
    assert find_error_message(html) == "You have submitted exactly the same code before"
    assert find_error_message("<html></html>") is None


def test_find_error_message_skips_empty_placeholders():
    form = (
        '<span class="error for__handleOrEmail"></span>'
        '<span class="error for__password">Invalid handle/email or password</span>'
    )
    assert find_error_message(form) == "Invalid handle/email or password"


def test_find_message():
    html = 'Codeforces.showMessage("Solution submitted successfully");  Codeforces.reformatTimes();'
    assert find_message(html) == "Solution submitted successfully"


def test_find_code():
    html = '<pre id="program-source-text" class="prettyprint">int main() { return a&lt;b; }</pre>'
    assert find_code(html) == "int main() { return a<b; }"


PROBLEMS_TABLE = """
<table class="problems">
  <tr><th>#</th><th>Name</th><th></th><th></th></tr>
  <tr class="accepted-problem">
    <td class="id"><a href="/contest/1136/problem/A">A</a></td>
    <td><div><div><a href="/contest/1136/problem/A">Nastya Is Reading a Book</a></div>
      <div class="notice">standard input/output
      1 s, 256 MB</div></div></td>
    <td></td>
    <td><a href="">x5234</a></td>
  </tr>
  <tr>
    <td class="id"><a href="/contest/1136/problem/B">B</a></td>
    <td><div><div><a href="/contest/1136/problem/B">Nastya Is Playing</a></div>
      <div class="notice">standard input/output
      1 s, 256 MB</div></div></td>
    <td></td>
    <td><a href="">x4521</a></td>
  </tr>
</table>
"""


def test_parse_problems():
    problems = parse_problems(PROBLEMS_TABLE)
    assert len(problems) == 2
    a = problems[0]
    assert (a.id, a.name, a.passed) == ("A", "Nastya Is Reading a Book", "5234")
    assert a.io == "standard input/output"
    assert a.limit == "1 s, 256 MB"
    assert a.state == "accepted-problem"
    assert problems[1].state == ""


def test_parse_problems_missing():
    with pytest.raises(CFError):
        parse_problems("<html></html>")


LANG_SELECT = """
<select name="programTypeId">
  <option value="89">GNU G++23 14.2 (64 bit, msys2)</option>
  <option value="31">Python 3.8.10</option>
  <option value="">choose...</option>
</select>
"""


def test_parse_languages():
    languages = parse_languages(LANG_SELECT)
    assert languages == {"89": "GNU G++23 14.2 (64 bit, msys2)", "31": "Python 3.8.10"}
    assert parse_languages("<html></html>") == {}


SUBMISSIONS = """
<meta name="utc_offset" content="+03:00"/>
<table>
<tr data-submission-id="12345" partymemberids=";67;">
  <td class="id-cell"><a href="/contest/1136/submission/12345">12345</a></td>
  <td class="status-small"><span class="format-time">Jun/11/2026 12:00</span></td>
  <td data-problemid="999" class="status-small"><a href="">A - Nastya</a></td>
  <td>GNU G++23 14.2</td>
  <td class="status-cell">
    <span class="submissionVerdictWrapper" submissionverdict="OK">
      <span class="verdict-accepted">Accepted</span>
    </span>
  </td>
  <td class="time-consumed-cell">15 ms</td>
  <td class="memory-consumed-cell">8 KB</td>
</tr>
<tr data-submission-id="12346">
  <td class="id-cell">12346</td>
  <td class="status-small"><span class="format-time">11.06.2026 12:05</span></td>
  <td data-problemid="998" class="status-small"><a href="">B - Playing</a></td>
  <td>Python 3.8.10</td>
  <td class="status-cell">
    <span class="submissionVerdictWrapper" submissionverdict="TESTING">
      <span class="verdict-waiting">Running on test
        <span class="verdict-format-judged">3</span></span>
    </span>
  </td>
  <td class="time-consumed-cell">-</td>
  <td class="memory-consumed-cell">-</td>
</tr>
</table>
"""


def test_parse_submissions():
    subs = parse_submissions(SUBMISSIONS)
    assert len(subs) == 2

    done = subs[0]
    assert done.id == 12345
    assert done.name == "A - Nastya"
    assert done.lang == "GNU G++23 14.2"
    assert done.end is True
    assert done.time_ms == 15
    assert done.memory_bytes == 8 * 1024
    text, style = done.styled_status()
    assert text == "Accepted"
    assert style == "green"
    assert done.problem_index() == "a"

    running = subs[1]
    assert running.end is False
    text, style = running.styled_status()
    assert "Running on test" in text
    assert style == "white"


def test_parse_submissions_count():
    assert len(parse_submissions(SUBMISSIONS, 1)) == 1


def test_parse_submissions_empty():
    with pytest.raises(CFError, match="Cannot find any submission"):
        parse_submissions("<html></html>")


# ------------------------------------------------- live-site fixtures


def test_cloudflare_interstitial_is_a_gate():
    page = fixture("challenge_enter.html")
    assert is_cloudflare_challenge(page)
    assert is_gate(page)


def test_codeforces_turnstile_page_is_a_gate():
    page = fixture("verification_gate.html")
    assert is_verification_gate(page)
    assert is_gate(page)
    assert has_turnstile(page)


def test_codeforces_browser_check_on_the_login_page():
    page = fixture("browser_check_enter.html")
    assert is_browser_check(page)
    assert is_gate(page)
    assert not has_turnstile(page)


@pytest.mark.parametrize(
    "name,described",
    [
        ("challenge_enter.html", "Cloudflare's check"),
        ("browser_check_enter.html", "Codeforces' browser check"),
        ("verification_gate.html", "Codeforces' Turnstile check"),
    ],
)
def test_a_check_page_is_named_in_errors(name, described):
    assert describe_page(fixture(name)) == described


def test_another_page_is_named_by_its_title():
    assert describe_page("<html><title>  Codeforces &amp; co\n</title></html>") == (
        'the page "Codeforces & co"'
    )
    assert describe_page("") == "a blank page"


@pytest.mark.parametrize(
    "name", ["problem_4a.html", "problem_2171a.html", "contest_2171.html", "submissions.html"]
)
def test_normal_pages_are_not_gates(name):
    page = fixture(name)
    # every normal page embeds Cloudflare's /cdn-cgi/challenge-platform/ bot
    # script; that must not be mistaken for a challenge
    assert "challenge-platform" in page
    assert not is_gate(page)
    assert not has_turnstile(page)
    assert not is_browser_check(page)


def test_live_samples_br_markup():
    page = fixture("problem_4a.html")
    assert find_samples(page) == (["8\n"], ["YES\n"])
    assert is_standard_io(page)


def test_live_samples_line_markup():
    inputs, outputs = find_samples(fixture("problem_2171a.html"))
    assert inputs == ["5\n2\n3\n4\n6\n100\n"]
    assert outputs == ["1\n0\n2\n2\n26\n"]


def test_live_file_io_problem():
    page = fixture("fileio_120a.html")
    assert find_samples(page) == (["front\n1\n"], ["L\n"])
    assert not is_standard_io(page)


def test_line_markup_keeps_leading_spaces():
    page = (
        '<div class="input"><pre>'
        '<div class="test-example-line test-example-line-0">2</div>'
        '<div class="test-example-line test-example-line-1">  #</div>'
        '</pre></div><div class="output"><pre>1</pre></div>'
    )
    assert find_samples(page)[0] == ["2\n  #\n"]


def test_acmsguru_samples():
    # acmsguru 100 "A+B": free-form statement, samples in bare <pre> blocks
    assert find_samples(fixture("acmsguru_100.html")) == (["5 3\n"], ["8\n"])


def test_live_problems_table():
    problems = parse_problems(fixture("contest_2171.html"))
    assert len(problems) == 9
    assert problems[0].id == "A"
    assert problems[0].name == "Shizuku Hoshikawa and Farm Legs"
    assert (problems[0].io, problems[0].limit) == ("standard input/output", "1 s, 256 MB")
    assert problems[0].passed.isdigit()


def test_live_submissions():
    subs = parse_submissions(fixture("submissions.html"))
    assert [(s.id, s.lang, s.problem_index()) for s in subs] == [
        (392264558, "PyPy 3-64", "b"),
        (379163092, "C++20 (GCC 13-64)", "a"),
        (379163040, "C++20 (GCC 13-64)", "a"),
    ]
    assert all(s.end for s in subs)
    assert subs[1].styled_status() == ("Wrong answer on test 1", "blue")
    assert subs[2].styled_status() == ("Accepted", "green")


def test_live_countdown_over_a_day():
    # "5 days" is shown; the exact time sits in the title attribute
    assert find_countdown(fixture("countdown.html")) == 115 * 3600 + 5 * 60 + 5


def test_is_captcha_error():
    assert is_captcha_error("Please confirm you are not a robot")
    assert is_captcha_error("Captcha verification failed")
    assert not is_captcha_error("Invalid handle/email or password")


def test_problem_header():
    from cf_tool.codeforces.pages import ProblemHeader, find_problem_header

    assert find_problem_header(fixture("problem_4a.html")) == ProblemHeader(
        "A. Watermelon", 1.0, 64, False
    )
    interactive = find_problem_header(fixture("interactive_1520f1.html"))
    assert interactive == ProblemHeader("F1. Guess the K-th Zero (Easy version)", 1.0, 256, True)
    assert find_problem_header(fixture("acmsguru_100.html")) == ProblemHeader("", None, None, False)


def test_sample_cases():
    from cf_tool.codeforces.pages import find_sample_cases

    assert find_sample_cases(fixture("problem_2171a.html")) == [
        ([0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5])  # NOTE: line 0 gives the number of cases
    ]
    assert find_sample_cases(fixture("problem_4a.html")) == [None]  # classic markup


def test_sample_cases_follow_the_trimmed_text():
    from cf_tool.codeforces.pages import find_sample_cases, find_samples

    line = '<div class="test-example-line test-example-line-{}">{}</div>'
    body = (
        '<div class="input"><pre>'
        + "".join(line.format(case, text) for case, text in [(1, ""), (1, "3"), (2, "4"), (2, " ")])
        + '</pre></div><div class="output"><pre>'
        + line.format(1, "x")
        + line.format(2, "y")
        + "</pre></div>"
    )
    inputs, _ = find_samples(body)
    assert inputs == ["3\n4\n"]
    assert find_sample_cases(body) == [([1, 2], [1, 2])]


def test_statement_tolerance():
    from cf_tool.codeforces.pages import find_problem_header

    assert (
        find_problem_header(fixture("epsilon_808b.html")).epsilon == 1e-6
    )  # NOTE: 10<sup>-6</sup>
    assert find_problem_header(fixture("anycase_2000a.html")).ignore_case
    for name in ("problem_4a.html", "problem_2171a.html", "interactive_1520f1.html"):
        header = find_problem_header(fixture(name))
        assert (header.epsilon, header.ignore_case) == (None, False), name
    modern = (
        '<div class="problem-statement">Your answer is correct if its absolute or relative '
        'error does not exceed $$$10^{-9}$$$.</div><div class="sample-tests">'
    )
    assert find_problem_header(modern).epsilon == 1e-9


def test_a_statement_that_accepts_any_answer():
    from cf_tool.codeforces.pages import find_problem_header

    assert find_problem_header(fixture("any_answer_2275a.html")).any_answer
    for name in (
        "problem_4a.html",
        "anycase_2000a.html",
        "epsilon_808b.html",
        "interactive_1520f1.html",  # NOTE: "if you don't print anything"
    ):
        assert not find_problem_header(fixture(name)).any_answer, name


@pytest.mark.parametrize(
    "text,accepts",
    [
        ("If there are multiple answers, print any of them.", True),
        ("If there are several solutions, you may output any.", True),
        ("Print any such permutation.", True),
        ("If there are multiple optimal answers, any of them will be accepted.", True),
        ("Do not print any extra spaces.", False),
        ("If you don't print anything, you get Idleness limit exceeded.", False),
        ("You may print any letter in any case (upper or lower).", False),
        ("Print the answer modulo 998244353.", False),
    ],
)
def test_any_answer_wording(text, accepts):
    from cf_tool.codeforces.pages import find_problem_header

    page = f'<div class="problem-statement"><p>{text}</p></div><div class="sample-tests">'
    assert find_problem_header(page).any_answer is accepts


def test_a_note_can_say_other_answers_are_possible():
    from cf_tool.codeforces.pages import find_problem_header

    page = (
        '<div class="problem-statement"><p>Print a permutation.</p></div>'
        '<div class="sample-tests"></div><div class="note"><p>In the first test case, other '
        "answers are also possible.</p></div>"
    )
    assert find_problem_header(page).any_answer
    # NOTE: wording after the samples (notes, the sidebar) doesn't count
    later = '<div class="problem-statement"><div class="sample-tests">in any case</div></div>'
    assert not find_problem_header(later).ignore_case


def test_parse_contests():
    from cf_tool.codeforces.pages import Contest, parse_contests

    result = [
        {
            "id": 2278,
            "name": "Round",
            "phase": "BEFORE",
            "startTimeSeconds": 100,
            "durationSeconds": 60,
        },
        {"id": 9, "name": "No start time yet", "phase": "BEFORE"},
    ]
    assert parse_contests(result) == [Contest(2278, "Round", 100, 60, "BEFORE")]


def test_any_case_means_letter_case_only():
    from cf_tool.codeforces.pages import find_problem_header

    def statement(text: str) -> str:
        return f'<div class="problem-statement">{text}</div><div class="sample-tests">'

    assert find_problem_header(statement("You can output the answer in any case.")).ignore_case
    assert find_problem_header(statement("Each letter can be printed in any case.")).ignore_case
    assert find_problem_header(statement("Comparison is case-insensitive.")).ignore_case
    idiom = "Print the minimum. In any case, the answer doesn't exceed 10."
    assert not find_problem_header(statement(idiom)).ignore_case


def test_split_problems():
    from cf_tool.codeforces.pages import find_problem_header, find_samples, split_problems

    parts = split_problems(fixture("contest_2171_problems.html"))
    assert [index for index, _ in parts] == ["A", "B"]
    names = [find_problem_header(part).name for _, part in parts]
    assert names == ["A. Shizuku Hoshikawa and Farm Legs", "B. Yuu Koito and Minimum Absolute Sum"]
    inputs, outputs = find_samples(parts[0][1])
    assert len(inputs) == len(outputs) == 1
    assert split_problems(fixture("problem_4a.html")) == []


def test_wants_login():
    from cf_tool.codeforces.pages import wants_login

    assert wants_login('<form id="enterForm"><input name="handleOrEmail"></form>')
    assert not wants_login(fixture("problem_4a.html"))


# ┌──────────────────────────────────────────────────────────┐
# │                  Statements as Markdown                  │
# └──────────────────────────────────────────────────────────┘


def test_a_statement_as_markdown():
    from cf_tool.codeforces.pages import statement_markdown

    text = statement_markdown(fixture("problem_4a.html"))
    assert text.startswith("# A. Watermelon\n\ntime limit per test: 1 second · ")
    assert "\n## Input\n" in text and "\n## Output\n" in text and "\n## Note\n" in text
    assert "Print YES, if the boys" in text  # NOTE: plain text, no inline formatting
    assert "### Input\n\n```\n8\n```" in text
    assert "<" not in text


def test_tex_lists_and_images_in_markdown():
    from cf_tool.codeforces.pages import statement_markdown

    text = statement_markdown(fixture("problem_2171a.html"))
    assert "Shizuku counts $n$ legs" in text  # NOTE: $$$n$$$ on the page
    assert "It is known that only chickens" in text  # NOTE: a link's text
    assert "- he can have two chickens and zero cows, or\n\n- he can have zero" in text
    old = statement_markdown(fixture("epsilon_808b.html"))
    assert "2·10^5" in old and "a_i" in old and "](https://espresso.codeforces.com/" in old
    assert "### Input 3" in old  # NOTE: several examples are numbered


def test_an_interactive_statement_keeps_its_sections():
    from cf_tool.codeforces.pages import statement_markdown

    text = statement_markdown(fixture("interactive_1520f1.html"))
    assert "This is an interactive problem." in text and "\n## Interaction\n" in text
    assert "? 4 6" in text
    assert statement_markdown("<html><p>no statement</p></html>") == ""


# ┌──────────────────────────────────────────────────────────┐
# │                   A submission's tests                   │
# └──────────────────────────────────────────────────────────┘


def test_the_failed_test_of_a_submission():
    import json

    from cf_tool.codeforces.pages import has_test_details, parse_submission_details

    details = parse_submission_details(json.loads(fixture("submit_source_2275f.json")))
    assert details.verdict == "Wrong answer on test 27" and details.problem == "(F) Tea Blend"
    failed = details.failed
    assert failed.number == 27 and failed.verdict == "WRONG_ANSWER" and failed.cut
    assert failed.input.startswith("3221\n78498\n2 3 5 7 ") and "\r" not in failed.output
    assert failed.checker == "wrong answer 6th numbers differ - expected: '2', found: '4'"
    assert has_test_details('<a class="click-to-view-tests" href="#">')
    assert not has_test_details(fixture("problem_4a.html"))
