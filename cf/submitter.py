"""
Solution submission module for Codeforces.
"""

import re
from pathlib import Path
from typing import Dict, Optional

from bs4 import BeautifulSoup

from cf.constants import BASE_URL, LANGUAGE_IDS, SUBMIT_URLS
from cf.session import Session
from cf.utils import AuthenticationError, detect_language, SubmissionError


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

        csrf_token = session.get_csrf_token(submit_url)

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

        response = session.client.post(submit_url, data=submit_data)
        response.raise_for_status()

        # Codeforces redirects to "my" page on successful submission
        if "/my" not in str(response.url):
            soup = BeautifulSoup(response.text, 'lxml')
            error_div = soup.find('div', class_='error')
            error_msg = error_div.get_text().strip() if error_div else "Unknown error"
            raise SubmissionError(f"Submission failed: {error_msg}")

        submission_id = _extract_submission_id(response.text)
        submission_url = f"{BASE_URL}/contest/{contest_id}/submission/{submission_id}"

        return {
            "submission_id": submission_id,
            "url": submission_url,
            "contest_id": contest_id,
            "problem_id": problem_id.upper(),
            "language": language,
        }

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
