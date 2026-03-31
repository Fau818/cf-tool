"""
Submission status watcher for Codeforces.

Polls submission status and displays real-time updates.
"""

import time

import cloudscraper
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from cf_tool.constants import BASE_URL

console = Console()

# Verdicts that indicate the submission is still being judged
PENDING_VERDICTS = {
    "TESTING",
    "SUBMITTED",
    None,
    "",
}

# Final verdicts
FINAL_VERDICTS = {
    "OK",
    "ACCEPTED",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "COMPILATION_ERROR",
    "IDLENESS_LIMIT_EXCEEDED",
    "SECURITY_VIOLATED",
    "CRASHED",
    "SKIPPED",
    "CHALLENGED",
    "PARTIAL",
    "PRESENTATION_ERROR",
}

# Verdict display names and colors
VERDICT_DISPLAY = {
    "OK": ("Accepted", "green"),
    "ACCEPTED": ("Accepted", "green"),
    "WRONG_ANSWER": ("Wrong Answer", "red"),
    "TIME_LIMIT_EXCEEDED": ("Time Limit Exceeded", "red"),
    "MEMORY_LIMIT_EXCEEDED": ("Memory Limit Exceeded", "red"),
    "RUNTIME_ERROR": ("Runtime Error", "red"),
    "COMPILATION_ERROR": ("Compilation Error", "yellow"),
    "IDLENESS_LIMIT_EXCEEDED": ("Idleness Limit Exceeded", "red"),
    "TESTING": ("Testing", "cyan"),
    "SUBMITTED": ("Submitted", "cyan"),
    "PARTIAL": ("Partial", "yellow"),
    "SKIPPED": ("Skipped", "yellow"),
    "CHALLENGED": ("Challenged", "red"),
    "PRESENTATION_ERROR": ("Presentation Error", "red"),
}


_api_client: cloudscraper.CloudScraper | None = None


def _get_api_client() -> cloudscraper.CloudScraper:
    """Get a shared cloudscraper client for API calls."""
    global _api_client
    if _api_client is None:
        _api_client = cloudscraper.create_scraper()
    return _api_client


def get_submission_status(contest_id: str, submission_id: str) -> dict | None:
    """
    Fetch submission status from Codeforces API.

    Args:
        contest_id: Contest ID
        submission_id: Submission ID

    Returns:
        Submission data dict or None if not found
    """
    try:
        client = _get_api_client()

        api_url = f"{BASE_URL}/api/contest.status"
        params = {
            "contestId": contest_id,
            "from": 1,
            "count": 50,
        }

        response = client.get(api_url, params=params)
        data = response.json()

        if data.get("status") != "OK":
            return None

        for submission in data.get("result", []):
            if str(submission.get("id")) == str(submission_id):
                return submission

        return None

    except Exception:
        return None


def get_submission_by_handle(contest_id: str, handle: str, count: int = 10) -> dict | None:
    """
    Get the most recent submission for a user in a contest.

    Args:
        contest_id: Contest ID
        handle: Codeforces handle
        count: Number of submissions to return

    Returns:
        Most recent submission or None
    """
    try:
        client = _get_api_client()

        api_url = f"{BASE_URL}/api/contest.status"
        params = {
            "contestId": contest_id,
            "handle": handle,
            "from": 1,
            "count": count,
        }

        response = client.get(api_url, params=params)
        data = response.json()

        if data.get("status") != "OK":
            return None

        results = data.get("result", [])
        return results[0] if results else None

    except Exception:
        return None


def format_submission_status(submission: dict, contest_id: str, problem_id: str) -> Text:
    """
    Format submission status for display.

    Args:
        submission: Submission data from API
        contest_id: Contest ID
        problem_id: Problem ID

    Returns:
        Rich Text object with formatted status
    """
    text = Text()

    # Header
    verdict = submission.get("verdict", "TESTING")
    lang = submission.get("programmingLanguage", "Unknown")

    text.append(f"Submit {contest_id} {problem_id} ", style="bold")
    text.append(f"{lang}\n", style="cyan")

    # Author
    author = submission.get("author", {})
    members = author.get("members", [{}])
    handle = members[0].get("handle", "Unknown") if members else "Unknown"
    text.append(f"Current user: {handle}\n", style="white")

    # Status line
    display_name, color = VERDICT_DISPLAY.get(verdict, (verdict, "white"))

    if verdict == "TESTING":
        # Show which test is being processed
        passed_count = submission.get("passedTestCount", 0)
        text.append("Running on test ", style="white")
        text.append(f"{passed_count + 1}\n", style="cyan")
    else:
        text.append(f"{display_name}\n", style=color)

    # Details
    sub_id = submission.get("id", "Unknown")
    creation_time = submission.get("creationTimeSeconds", 0)
    time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(creation_time))

    problem = submission.get("problem", {})
    prob_name = problem.get("name", "Unknown")
    prob_index = problem.get("index", problem_id)

    text.append(f"      #: {sub_id}\n", style="white")
    text.append(f"   when: {time_str}\n", style="white")
    text.append(f"   prob: {prob_index} - {prob_name}\n", style="white")
    text.append(f"   lang: {lang}\n", style="white")

    # Final verdict line with color
    text.append(" status: ", style="white")

    if verdict == "TESTING":
        passed_count = submission.get("passedTestCount", 0)
        text.append(f"Running on test {passed_count + 1}", style="cyan")
    else:
        text.append(display_name, style=color)

    text.append("\n", style="white")

    # Time and memory (only show for final verdicts)
    if verdict not in PENDING_VERDICTS:
        time_ms = submission.get("timeConsumedMillis", 0)
        memory_bytes = submission.get("memoryConsumedBytes", 0)

        # Format memory
        if memory_bytes >= 1024 * 1024:
            memory_str = f"{memory_bytes / (1024 * 1024):.2f} MB"
        elif memory_bytes >= 1024:
            memory_str = f"{memory_bytes / 1024:.2f} KB"
        else:
            memory_str = f"{memory_bytes} B"

        text.append(f"   time: {time_ms} ms\n", style="white")
        text.append(f" memory: {memory_str}", style="white")

    return text


def watch_submission(
    contest_id: str,
    problem_id: str,
    submission_id: str,
    timeout: float = 120.0,
    interval: float = 1.0,
) -> dict:
    """
    Watch submission status until final verdict.

    Args:
        contest_id: Contest ID
        problem_id: Problem ID
        submission_id: Submission ID
        timeout: Maximum time to wait in seconds
        interval: Polling interval in seconds

    Returns:
        Final submission data
    """
    start_time = time.time()
    last_status = None

    with Live(console=console, refresh_per_second=4) as live:
        while time.time() - start_time < timeout:
            submission = get_submission_status(contest_id, submission_id)

            if submission:
                verdict = submission.get("verdict", "TESTING")

                # Update display
                status_text = format_submission_status(submission, contest_id, problem_id)
                live.update(status_text)

                # Check if final verdict
                if verdict in FINAL_VERDICTS:
                    # Wait a moment to show final status
                    time.sleep(0.5)
                    return submission

                last_status = submission

            time.sleep(interval)

    # Timeout - return last known status
    return last_status or {}


def print_final_status(submission: dict, contest_id: str, problem_id: str) -> None:
    """
    Print final submission status (non-live version).

    Args:
        submission: Submission data from API
        contest_id: Contest ID
        problem_id: Problem ID
    """
    if not submission:
        console.print("[red]Could not fetch submission status[/red]")
        return

    status_text = format_submission_status(submission, contest_id, problem_id)
    console.print(status_text)
