"""All Codeforces HTML/JSON parsing in one place (regexes + BeautifulSoup).

Function names and regexes follow the Go client (findHandle, findCsrf, ...)
so behavior can be diffed against the original. Sample extraction also
handles the newer markup where each line sits in a
<div class="test-example-line"> instead of being <br>-separated, and the
free-form "Sample Input" statements of acmsguru.

Also here: recognizing the pages that stand *between* us and Codeforces
(Cloudflare's interstitial, Codeforces' own Turnstile gate).
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from cf_tool.errors import CFError, NotLoggedInError

_HANDLE_RE = re.compile(r'handle = "([\s\S]+?)"')
_CSRF_RE = re.compile(r"csrf='(.+?)'")
_CSRF_DATA_RE = re.compile(r'data-csrf=[\'"]([a-f0-9]+)[\'"]')
_INPUT_RE = re.compile(r'class="input"[\s\S]*?<pre[^>]*>([\s\S]*?)</pre>')
_OUTPUT_RE = re.compile(r'class="output"[\s\S]*?<pre[^>]*>([\s\S]*?)</pre>')
# acmsguru statements are free-form: "Sample Input" <p>, then a <pre>
_SGU_INPUT_RE = re.compile(r"Sample\s+Input[\s\S]*?<pre[^>]*>([\s\S]*?)</pre>", re.IGNORECASE)
_SGU_OUTPUT_RE = re.compile(r"Sample\s+Output[\s\S]*?<pre[^>]*>([\s\S]*?)</pre>", re.IGNORECASE)
_COUNTDOWN_RE = re.compile(r'class=["\']countdown["\'][\s\S]*?(\d+):(\d+):(\d+)')
_ERROR_MSG_RE = re.compile(r'error[a-zA-Z_\- ]*">(.*?)</span>')
_SHOW_MSG_RE = re.compile(
    r'Codeforces\.showMessage\("([^"]*)"\);\s*?Codeforces\.reformatTimes\(\);'
)
_CODE_RE = re.compile(r"<pre[\s\S]*?>([\s\S]*?)</pre>")
_UTC_OFFSET_RE = re.compile(r'name="utc_offset" content="([\s\S]+?)"')
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d+")

# the Go tool matched one exact <div> string; Codeforces has since added
# extra classes and the wording varies by problem age ("standard input" on
# newer pages, "stdin" on older ones), so match loosely
_STANDARD_INPUT_RE = re.compile(
    r'class="input-file input-standard"|'
    r'class="input-file[^"]*"><div class="property-title">input</div>\s*(standard input|stdin)<'
)
_STANDARD_OUTPUT_RE = re.compile(
    r'class="output-file output-standard"|'
    r'class="output-file[^"]*"><div class="property-title">output</div>\s*(standard output|stdout)<'
)

# Cloudflare's managed-challenge interstitial. Never use "challenge-platform"
# as a marker: every normal page embeds Cloudflare's bot-detection script
# from /cdn-cgi/challenge-platform/scripts/jsd/.
_CLOUDFLARE_MARKERS = ("<title>Just a moment", "_cf_chl_opt")
# Codeforces' own Turnstile gate posts the solved token here, then reloads
_VERIFICATION_MARKER = "/data/turnstile"
_CAPTCHA_WORDS_RE = re.compile(r"captcha|robot|human|turnstile|verif", re.IGNORECASE)


def is_cloudflare_challenge(body: str) -> bool:
    return any(marker in body for marker in _CLOUDFLARE_MARKERS)


def is_verification_gate(body: str) -> bool:
    return _VERIFICATION_MARKER in body


def is_gate(body: str) -> bool:
    """True for a page that stands in front of the content: Cloudflare's
    interstitial or Codeforces' own Turnstile verification page."""
    return is_cloudflare_challenge(body) or is_verification_gate(body)


def has_turnstile(body: str) -> bool:
    """True when the page carries a Turnstile widget (only a browser can solve it)."""
    return "cf-turnstile" in body


def is_captcha_error(message: str) -> bool:
    """True when a form error is about the human check, not the credentials."""
    return bool(_CAPTCHA_WORDS_RE.search(message))


def find_handle(body: str) -> str | None:
    match = _HANDLE_RE.search(body)
    return match.group(1) if match else None


def require_handle(body: str) -> str:
    handle = find_handle(body)
    if handle is None:
        raise NotLoggedInError()
    return handle


def find_csrf(body: str) -> str:
    match = _CSRF_RE.search(body) or _CSRF_DATA_RE.search(body)
    if not match:
        raise CFError("Cannot find csrf")
    return match.group(1)


def _pre_to_text(inner: str) -> str:
    """Sample <pre> content -> text. Handles both the classic <br>-separated
    markup and the newer one-<div>-per-line markup."""
    if "test-example-line" in inner:
        lines = re.findall(r"<div[^>]*>([\s\S]*?)</div>", inner)
        # only the whole text is trimmed (as Go does): leading spaces inside
        # a line can be part of the input, e.g. ASCII-art grids
        text = "\n".join(html_lib.unescape(_TAG_RE.sub("", line)) for line in lines)
        return text.strip() + "\n"
    text = re.sub(r"<[\s/br]+?>", "\n", inner)  # the Go tool's <br> normalizer
    text = _TAG_RE.sub("", text)
    return html_lib.unescape(text).strip() + "\n"


def find_samples(body: str) -> tuple[list[str], list[str]]:
    """Sample (inputs, outputs) as text, each ending with a newline."""
    inputs = _INPUT_RE.findall(body)
    outputs = _OUTPUT_RE.findall(body)
    if not inputs and not outputs:
        inputs = _SGU_INPUT_RE.findall(body)
        outputs = _SGU_OUTPUT_RE.findall(body)
    if not inputs or not outputs or len(inputs) != len(outputs):
        raise CFError(f"Cannot parse sample with input {len(inputs)} and output {len(outputs)}")
    return [_pre_to_text(s) for s in inputs], [_pre_to_text(s) for s in outputs]


def is_standard_io(body: str) -> bool:
    return bool(_STANDARD_INPUT_RE.search(body) and _STANDARD_OUTPUT_RE.search(body))


def find_countdown(body: str) -> int:
    match = _COUNTDOWN_RE.search(body)
    if not match:
        raise CFError("Cannot find any countdown")
    h, m, s = (int(g) for g in match.groups())
    return h * 3600 + m * 60 + s


def find_error_message(body: str) -> str | None:
    """First non-empty form error (forms also carry empty error placeholders)."""
    for match in _ERROR_MSG_RE.finditer(body):
        message = html_lib.unescape(_TAG_RE.sub("", match.group(1))).strip()
        if message:
            return message
    return None


def find_message(body: str) -> str | None:
    """The Codeforces.showMessage flash text, if present."""
    match = _SHOW_MSG_RE.search(body)
    return match.group(1) if match else None


def find_code(body: str) -> str:
    match = _CODE_RE.search(body)
    if not match:
        raise CFError("Cannot find any code")
    return html_lib.unescape(match.group(1))


def find_cf_offset(body: str) -> str:
    match = _UTC_OFFSET_RE.search(body)
    if not match:
        raise CFError("Cannot find cf utc offset")
    return match.group(1)


# ------------------------------------------------------------- problem list


@dataclass
class StatisInfo:
    id: str
    name: str
    io: str
    limit: str
    passed: str
    state: str  # tr class, e.g. "accepted-problem" / "rejected-problem" / ""


def parse_problems(body: str) -> list[StatisInfo]:
    soup = BeautifulSoup(body, "lxml")
    table = soup.find("table", class_="problems")
    if table is None:
        raise CFError("Cannot find any problem statis")
    problems = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        problem_id = cells[0].get_text(strip=True)
        name_link = cells[1].find("a")
        name = name_link.get_text(strip=True) if name_link else ""
        notice = cells[1].find("div", class_="notice")
        io_text, limit = "", ""
        if notice:
            parts = [p.strip() for p in notice.get_text("\n").splitlines() if p.strip()]
            if parts:
                io_text = parts[0]
            if len(parts) > 1:
                limit = ", ".join(parts[1:])
        passed = "0"
        if len(cells) > 3:
            digits = _NUM_RE.search(cells[3].get_text())
            if digits:
                passed = digits.group(0)
        problems.append(
            StatisInfo(
                id=problem_id,
                name=name,
                io=io_text,
                limit=limit,
                passed=passed,
                state=" ".join(row.get("class", [])),
            )
        )
    if not problems:
        raise CFError("Cannot find any problem")
    return problems


# --------------------------------------------------------------- languages


def parse_languages(body: str) -> dict[str, str]:
    """id -> display name from the submit page's programTypeId <select>."""
    soup = BeautifulSoup(body, "lxml")
    select = soup.find("select", attrs={"name": "programTypeId"})
    if select is None:
        return {}
    return {
        opt["value"]: opt.get_text(strip=True)
        for opt in select.find_all("option")
        if opt.get("value")
    }


# -------------------------------------------------------------- submissions

_WAIT_VERDICTS = ("null", "TESTING", "SUBMITTED")
_VERDICT_FORMAT_RE = re.compile(r"<span\sclass=[\"']?verdict-format-[^\"'>]+[\"']?>")
_VERDICT_COLOR_RE = re.compile(r"<span\sclass=[\"']?verdict-([^\"'>]+?)[\"']?>")

# ${c-...} marker -> rich style (the Go tool's colorMap)
STATUS_STYLE = {
    "${c-waiting}": "white",
    "${c-failed}": "red",
    "${c-accepted}": "green",
    "${c-rejected}": "blue",
}


@dataclass
class Submission:
    id: int = 0
    name: str = ""
    lang: str = ""
    status: str = ""  # contains ${c-...}/${f-...} markers like the Go tool
    time_ms: int = 0
    memory_bytes: int = 0
    when: str = ""
    passed: int = 0
    end: bool = False

    def styled_status(self) -> tuple[str, str]:
        """(plain text, rich style) for display."""
        status = self.status
        for marker in ("${f-points}", "${f-passed}", "${f-judged}"):
            status = status.replace(marker, str(self.passed))
        style = ""
        for marker, marker_style in STATUS_STYLE.items():
            if marker in status:
                status = status.replace(marker, "")
                style = marker_style
        return status, style

    def parse_memory(self) -> str:
        if self.memory_bytes > 1024 * 1024:
            return f"{self.memory_bytes / 1024 / 1024:.2f} MB"
        if self.memory_bytes > 1024:
            return f"{self.memory_bytes / 1024:.2f} KB"
        return f"{self.memory_bytes} B"

    def parse_time(self) -> str:
        return f"{self.time_ms} ms"

    def problem_index(self) -> str:
        head, _, _ = self.name.partition(" ")
        return head.lower().rstrip("-")


def _parse_when(raw: str, cf_offset: str) -> str:
    for fmt in ("%d.%m.%Y %H:%M", "%b/%d/%Y %H:%M"):
        try:
            naive = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        return raw
    match = re.match(r"([+-])(\d{2}):(\d{2})", cf_offset)
    if not match:
        return naive.strftime("%Y-%m-%d %H:%M")
    sign = 1 if match.group(1) == "+" else -1
    offset = timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))
    return naive.replace(tzinfo=offset).astimezone().strftime("%Y-%m-%d %H:%M")


def _parse_submission_row(row, cf_offset: str) -> Submission:
    def text_of(node) -> str:
        return node.get_text(strip=True) if node else ""

    def int_of(node) -> int:
        digits = _NUM_RE.search(node.get_text()) if node else None
        return int(digits.group(0)) if digits else 0

    verdict_wrapper = row.find(class_="submissionVerdictWrapper")
    end = False
    status = "Unknown"
    if verdict_wrapper:
        verdict = verdict_wrapper.get("submissionverdict", "null")
        end = verdict not in _WAIT_VERDICTS
        inner = verdict_wrapper.decode_contents()
        inner = _VERDICT_FORMAT_RE.sub("", inner)
        inner = _VERDICT_COLOR_RE.sub(r"${c-\1}", inner)
        inner = _TAG_RE.sub("", inner)
        status = html_lib.unescape(inner).strip() or "Unknown"

    when_node = row.find(class_="format-time")
    if when_node:
        when = _parse_when(text_of(when_node), cf_offset)
    else:
        cells = row.find_all("td")
        when = text_of(cells[1]) if len(cells) > 1 else ""

    digits = _NUM_RE.search(status)
    passed = int(digits.group(0)) if digits else 0

    lang_cell = row.find(lambda tag: tag.name == "td" and not tag.has_attr("class"))
    return Submission(
        id=int_of(row.find(class_="id-cell")),
        name=text_of(row.find("td", attrs={"data-problemid": True})),
        lang=text_of(lang_cell),
        status=status,
        time_ms=int_of(row.find(class_="time-consumed-cell")),
        memory_bytes=int_of(row.find(class_="memory-consumed-cell")) * 1024,
        when=when,
        passed=passed,
        end=end,
    )


def parse_submissions(body: str, count: int = -1) -> list[Submission]:
    """Submissions from a /my (or status) page, newest first."""
    cf_offset = ""
    try:
        cf_offset = find_cf_offset(body)
    except CFError:
        pass
    soup = BeautifulSoup(body, "lxml")
    rows = soup.find_all("tr", attrs={"data-submission-id": True})
    if count >= 0:
        rows = rows[:count]
    submissions = [_parse_submission_row(row, cf_offset) for row in rows]
    if not submissions:
        raise CFError("Cannot find any submission")
    return submissions
