"""
Utility functions for cf-tool.
"""

import re
from pathlib import Path
from typing import Optional, Tuple


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


def find_solution_file(directory: Path, language: Optional[str] = None) -> Optional[Path]:
    """
    Find solution file in directory.

    Args:
        directory: Directory to search in
        language: Optional language hint

    Returns:
        Path to solution file if found, None otherwise
    """
    from cf.constants import SOLUTION_FILE_NAMES, EXTENSION_TO_LANGUAGE

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


def detect_language(filepath: Path) -> Optional[str]:
    """
    Detect programming language from file extension.

    Args:
        filepath: Path to source file

    Returns:
        Language name or None if not recognized
    """
    from cf.constants import EXTENSION_TO_LANGUAGE

    ext = filepath.suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def get_config_dir() -> Path:
    """
    Get the configuration directory for cf-tool.

    Returns:
        Path to config directory (~/.cf/)
    """
    import platformdirs

    # Use ~/.cf/ for simplicity (cf-tool original location)
    config_dir = Path.home() / ".cf"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def parse_problem_url(url: str) -> Optional[Tuple[str, str, str]]:
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
