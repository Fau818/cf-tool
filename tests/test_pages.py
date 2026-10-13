"""Parser tests: hand-written snippets plus pages trimmed from the live site
(tests/fixtures, fetched 2026-10-12)."""

from pathlib import Path

import pytest

from cf_tool.errors import CFError
from cf_tool.pages import (
    find_code,
    find_countdown,
    find_csrf,
    find_error_message,
    find_handle,
    find_message,
    find_samples,
    has_turnstile,
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
