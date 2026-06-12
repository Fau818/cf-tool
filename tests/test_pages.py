"""Parser tests against representative Codeforces HTML snippets."""

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
    parse_languages,
    parse_problems,
    parse_submissions,
)

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
    from cf_tool.pages import is_standard_io

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
      <span class="verdict-waiting">Running on test <span class="verdict-format-judged">3</span></span>
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
