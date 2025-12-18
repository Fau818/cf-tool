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
    # Validate file exists
    solution_path = Path(file_path)
    if not solution_path.exists():
        raise SubmissionError(f"Solution file not found: {file_path}")

    # Detect language if not provided
    if language is None:
        language = detect_language(solution_path)
        if language is None:
            raise SubmissionError(f"Cannot detect language from file: {file_path}")

    # Get language ID
    language_id = LANGUAGE_IDS.get(language)
    if language_id is None:
        raise SubmissionError(f"Unsupported language: {language}")

    # Read source code
    try:
        with open(solution_path, 'r') as f:
            source_code = f.read()
    except IOError as e:
        raise SubmissionError(f"Failed to read solution file: {e}")

    # Create session
    session = Session()

    # Check if authenticated
    if not session.is_authenticated():
        raise AuthenticationError("Not authenticated. Please run 'cf config login' first.")

    # Get submit URL
    submit_url_pattern = SUBMIT_URLS.get(contest_type)
    if not submit_url_pattern:
        raise SubmissionError(f"Unknown contest type: {contest_type}")

    submit_url = submit_url_pattern.format(cid=contest_id)

    try:
        # Get CSRF token from submit page
        csrf_token = session.get_csrf_token(submit_url)

        # Prepare submission data
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

        # Submit
        response = session.client.post(submit_url, data=submit_data)
        response.raise_for_status()

        # Check if submission was successful
        # Codeforces redirects to "my" page on successful submission
        if "/my" not in str(response.url):
            # Try to parse error message
            soup = BeautifulSoup(response.text, 'lxml')
            error_div = soup.find('div', class_='error')

            if error_div:
                error_msg = error_div.get_text().strip()
                raise SubmissionError(f"Submission failed: {error_msg}")
            else:
                raise SubmissionError("Submission failed: Unknown error")

        # Extract submission ID from the response
        # Look for the submission in the "my submissions" page
        soup = BeautifulSoup(response.text, 'lxml')

        # Find the most recent submission (first row in the table)
        submission_row = soup.find('tr', {'data-submission-id': True})

        if submission_row:
            submission_id = submission_row.get('data-submission-id')
        else:
            # Fallback: try to extract from URL or page content
            match = re.search(r'submission/(\d+)', response.text)
            if match:
                submission_id = match.group(1)
            else:
                # If we can't find submission ID, just use a placeholder
                submission_id = "unknown"

        # Build submission URL
        submission_url = f"{BASE_URL}/contest/{contest_id}/submission/{submission_id}"

        session.close()

        return {
            "submission_id": submission_id,
            "url": submission_url,
            "contest_id": contest_id,
            "problem_id": problem_id.upper(),
            "language": language,
        }

    except Exception as e:
        session.close()
        if isinstance(e, (SubmissionError, AuthenticationError)):
            raise
        raise SubmissionError(f"Submission failed: {e}")
