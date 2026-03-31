"""
Utility functions for cf-tool.
"""

import json
import re
from pathlib import Path


class CFError(Exception):
    """Base exception for cf-tool."""
    pass


class NetworkError(CFError):
    """Network-related errors."""
    pass


class AuthenticationError(CFError):
    """Authentication failures."""
    pass


class CompilationError(CFError):
    """Compilation failures."""
    pass


class SubmissionError(CFError):
    """Submission failures."""
    pass


class ParseError(CFError):
    """Parsing failures."""
    pass


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text for comparison.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace
    """
    # Split into lines, strip each line, filter empty lines
    lines = [line.rstrip() for line in text.split('\n')]
    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def find_solution_file(directory: Path, language: str | None = None) -> Path | None:
    """
    Find solution file in directory.

    Args:
        directory: Directory to search in
        language: Optional language hint

    Returns:
        Path to solution file if found, None otherwise
    """
    from cf_tool.constants import SOLUTION_FILE_NAMES, EXTENSION_TO_LANGUAGE

    # If language specified, look for that specific file
    if language:
        solution_name = SOLUTION_FILE_NAMES.get(language)
        if solution_name:
            solution_path = directory / solution_name
            if solution_path.exists():
                return solution_path

    # Otherwise, search for any solution file
    for lang, filename in SOLUTION_FILE_NAMES.items():
        solution_path = directory / filename
        if solution_path.exists():
            return solution_path

    # Search for common patterns like main.cpp, a.cpp, etc.
    common_names = ["main", "a", "code", "sol"]
    for ext, _ in EXTENSION_TO_LANGUAGE.items():
        for name in common_names:
            filepath = directory / f"{name}{ext}"
            if filepath.exists():
                return filepath

    return None


def detect_language(filepath: Path) -> str | None:
    """
    Detect programming language from file extension.

    Args:
        filepath: Path to source file

    Returns:
        Language name or None if not recognized
    """
    from cf_tool.constants import EXTENSION_TO_LANGUAGE

    ext = filepath.suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def get_config_dir() -> Path:
    """
    Get the configuration directory for cf-tool.

    Returns:
        Path to config directory (~/.cf/)
    """
    # Use ~/.cf/ for compatibility with original cf-tool
    config_dir = Path.home() / ".cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def parse_problem_url(url: str) -> tuple[str, str, str] | None:
    """
    Parse Codeforces problem URL.

    Args:
        url: Problem URL

    Returns:
        Tuple of (contest_type, contest_id, problem_id) or None if invalid
    """
    # Contest: https://codeforces.com/contest/1900/problem/A
    contest_pattern = r'codeforces\.com/contest/(\d+)/problem/([A-Za-z]\d?)'
    match = re.search(contest_pattern, url)
    if match:
        return ('contest', match.group(1), match.group(2))

    # Gym: https://codeforces.com/gym/100001/problem/A
    gym_pattern = r'codeforces\.com/gym/(\d+)/problem/([A-Za-z]\d?)'
    match = re.search(gym_pattern, url)
    if match:
        return ('gym', match.group(1), match.group(2))

    # Problemset: https://codeforces.com/problemset/problem/1900/A
    problemset_pattern = r'codeforces\.com/problemset/problem/(\d+)/([A-Za-z]\d?)'
    match = re.search(problemset_pattern, url)
    if match:
        return ('problemset', match.group(1), match.group(2))

    return None


def detect_context_from_dir(directory: Path | None = None) -> tuple[str, str | None] | None:
    """
    Detect contest_id and problem_id from directory structure.

    Looks for problem.json in the current or parent directories to determine
    the contest/problem context. Supports these directory layouts:
      - Inside problem dir: {contest_id}/{problem_id}/ -> (contest_id, problem_id)
      - Inside contest dir: {contest_id}/ -> (contest_id, None)

    Args:
        directory: Directory to check (defaults to CWD)

    Returns:
        Tuple of (contest_id, problem_id) or (contest_id, None) or None
    """
    if directory is None:
        directory = Path.cwd()

    # Check if we're in a problem directory (has problem.json)
    metadata_file = directory / "problem.json"
    if metadata_file.exists():
        try:
            data = json.loads(metadata_file.read_text())
            cid = data.get("contest_id")
            pid = data.get("problem_id")
            if cid:
                return (str(cid), pid)
        except (json.JSONDecodeError, IOError):
            pass

    # Check directory name pattern: parent is contest_id (digits), current is problem_id (letter)
    dir_name = directory.name
    parent_name = directory.parent.name

    if parent_name.isdigit() and re.match(r'^[A-Za-z]\d*$', dir_name):
        return (parent_name, dir_name.upper())

    # Check if we're in a contest directory (has subdirs that look like problems)
    if dir_name.isdigit():
        has_problems = any(
            d.is_dir() and re.match(r'^[A-Za-z]\d*$', d.name)
            for d in directory.iterdir()
        )
        if has_problems:
            return (dir_name, None)

    return None


def ensure_directory(path: Path) -> Path:
    """
    Ensure directory exists, create if not.

    Args:
        path: Directory path

    Returns:
        Path object
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """
    Convert string to safe filename.

    Args:
        name: Original name

    Returns:
        Safe filename
    """
    # Remove or replace unsafe characters
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    return safe.strip()
