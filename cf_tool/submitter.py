"""
Solution submission module for Codeforces.
"""

import re
from pathlib import Path
from typing import Dict, Optional

from bs4 import BeautifulSoup

from cf_tool.constants import BASE_URL, LANGUAGE_IDS, SUBMIT_URLS
from cf_tool.session import Session
from cf_tool.utils import AuthenticationError, detect_language, SubmissionError


def submit_solution(
    contest_id: str,
    problem_id: str,
    file_path: str,
    language: Optional[str] = None,
    contest_type: str = "contest",
) -> Dict:
    """
    Submit a solution to Codeforces.

    Args:
        contest_id: Contest ID
        problem_id: Problem ID (letter)
        file_path: Path to solution file
        language: Optional language override
        contest_type: Type of contest (contest, gym)

    Returns:
        Dictionary with submission info (submission_id, url)

    Raises:
        SubmissionError: If submission fails
        AuthenticationError: If not authenticated
    """
    solution_path = Path(file_path)
    if not solution_path.exists():
        raise SubmissionError(f"Solution file not found: {file_path}")

    if language is None:
        language = detect_language(solution_path)
        if language is None:
            raise SubmissionError(f"Cannot detect language from file: {file_path}")

    language_id = LANGUAGE_IDS.get(language)
    if language_id is None:
        raise SubmissionError(f"Unsupported language: {language}")

    try:
        source_code = solution_path.read_text()
    except IOError as e:
        raise SubmissionError(f"Failed to read solution file: {e}")

    submit_url_pattern = SUBMIT_URLS.get(contest_type)
    if not submit_url_pattern:
        raise SubmissionError(f"Unknown contest type: {contest_type}")

    submit_url = submit_url_pattern.format(cid=contest_id)

    session = Session()
    try:
        session.ensure_authenticated()

        # Get the submit page first to extract a fresh CSRF token
        page_response = session.get(submit_url)
        page_response.raise_for_status()

        csrf_token = session.extract_csrf_token(page_response.text)
        if not csrf_token:
            raise SubmissionError(
                "Could not extract CSRF token from submit page. "
                "Session may have expired. Try 'cf config login' to re-login."
            )

        submit_data = {
            "csrf_token": csrf_token,
            "action": "submitSolutionFormSubmitted",
            "contestId": contest_id,
            "submittedProblemIndex": problem_id.upper(),
            "programTypeId": language_id,
            "source": source_code,
            "tabSize": "4",
            "sourceFile": "",
        }

        # Submit using session.post (with retry) and follow redirects
        response = session.post(submit_url, data=submit_data, allow_redirects=True)
        response.raise_for_status()

        final_url = str(response.url)

        # Codeforces redirects to "my" page on successful submission
        if "/my" in final_url:
            submission_id = _extract_submission_id(response.text)
            submission_url = f"{BASE_URL}/contest/{contest_id}/submission/{submission_id}"

            return {
                "submission_id": submission_id,
                "url": submission_url,
                "contest_id": contest_id,
                "problem_id": problem_id.upper(),
                "language": language,
            }

        # Not redirected to /my — check for error messages
        soup = BeautifulSoup(response.text, 'lxml')

        # Collect all error messages from the page
        error_messages = []

        # Check for error spans with text content (e.g. "for__source" errors)
        for err in soup.find_all('span', class_=lambda c: c and 'error' in c):
            text = err.get_text(strip=True)
            if text:
                error_messages.append(text)

        # Check for error divs
        for err in soup.find_all('div', class_='error'):
            text = err.get_text(strip=True)
            if text:
                error_messages.append(text)

        # Check for roundbox error (CF uses this for "You have submitted exactly the same code before")
        for err in soup.find_all('span', class_='error'):
            parent = err.parent
            if parent:
                text = parent.get_text(strip=True)
                if text and text not in error_messages:
                    error_messages.append(text)

        if error_messages:
            raise SubmissionError(
                "Submission rejected: " + "; ".join(error_messages)
            )

        # Check if redirected to login page (session expired)
        if "/enter" in final_url:
            raise SubmissionError(
                "Redirected to login page. Session expired. "
                "Run 'cf config login' to re-login."
            )

        # Unknown state — provide debug info
        title = soup.find('title')
        title_text = title.get_text().strip() if title else "unknown"

        # Also try to grab any visible message on the page
        body_text = soup.get_text(strip=True)[:500] if soup.body else ""

        raise SubmissionError(
            f"Unexpected response (page: '{title_text}', url: {final_url}).\n"
            f"Page content preview: {body_text[:200]}\n"
            f"Try 'cf config login' to refresh your session."
        )

    except (SubmissionError, AuthenticationError):
        raise
    except Exception as e:
        raise SubmissionError(f"Submission failed: {e}")
    finally:
        session.close()


def _extract_submission_id(html: str) -> str:
    """Extract submission ID from response HTML."""
    soup = BeautifulSoup(html, 'lxml')

    # Try data-submission-id attribute
    submission_row = soup.find('tr', {'data-submission-id': True})
    if submission_row:
        return submission_row.get('data-submission-id')

    # Fallback: regex search
    match = re.search(r'submission/(\d+)', html)
    if match:
        return match.group(1)

    return "unknown"
