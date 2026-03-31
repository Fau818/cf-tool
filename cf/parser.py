"""
Problem parsing module - orchestrates downloading and setting up problems.
"""

import json
from pathlib import Path
from typing import Dict, List

from cf.config import Config
from cf.constants import PROBLEM_METADATA_FILE, SOLUTION_FILE_NAMES, TEST_INPUT_PATTERN, TEST_OUTPUT_PATTERN
from cf.scraper import CodeforceScraper
from cf.utils import ensure_directory


def parse_problem(
    contest_id: str, problem_id: str, language: str = "cpp", contest_type: str = "contest"
) -> Dict:
    """
    Parse a problem: download test cases and create directory structure.

    Args:
        contest_id: Contest ID
        problem_id: Problem ID (letter)
        language: Programming language for solution file
        contest_type: Type of contest (contest, gym, problemset)

    Returns:
        Dictionary with parse result information

    Raises:
        ParseError: If parsing fails
    """
    # Normalize problem ID to uppercase
    problem_id = problem_id.upper()

    # Create scraper and fetch problem data
    scraper = CodeforceScraper()
    problem_data = scraper.get_problem_data(contest_id, problem_id, contest_type)

    # Create directory structure: contest_id/problem_id/
    current_dir = Path.cwd()
    contest_dir = current_dir / contest_id
    problem_dir = contest_dir / problem_id

    ensure_directory(problem_dir)

    # Save test cases
    test_cases = problem_data["test_cases"]
    for i, (input_text, output_text) in enumerate(test_cases, 1):
        input_file = problem_dir / TEST_INPUT_PATTERN.format(i)
        output_file = problem_dir / TEST_OUTPUT_PATTERN.format(i)

        with open(input_file, 'w') as f:
            f.write(input_text)
            if not input_text.endswith('\n'):
                f.write('\n')

        with open(output_file, 'w') as f:
            f.write(output_text)
            if not output_text.endswith('\n'):
                f.write('\n')

    # Save problem metadata
    metadata_file = problem_dir / PROBLEM_METADATA_FILE
    metadata = {
        "contest_id": contest_id,
        "problem_id": problem_id,
        "contest_type": contest_type,
        **problem_data["metadata"],
    }

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Generate solution file from template
    solution_filename = SOLUTION_FILE_NAMES.get(language, f"solution.{language}")
    solution_file = problem_dir / solution_filename

    if not solution_file.exists():
        _create_solution_file(solution_file, language, contest_id, problem_id)

    return {
        "contest_id": contest_id,
        "problem_id": problem_id,
        "directory": str(problem_dir),
        "test_count": len(test_cases),
        "solution_file": str(solution_file),
        "metadata": metadata,
    }


def parse_contest(
    contest_id: str, language: str = "cpp", contest_type: str = "contest"
) -> List[Dict]:
    """
    Parse all problems in a contest.

    Args:
        contest_id: Contest ID
        language: Programming language for solution files
        contest_type: Type of contest (contest, gym)

    Returns:
        List of parse result dicts for each problem
    """
    scraper = CodeforceScraper()
    problems = scraper.fetch_contest_problems(contest_id, contest_type)

    results = []
    for prob in problems:
        result = parse_problem(contest_id, prob["id"], language, contest_type)
        results.append(result)

    return results


# Default solution templates for when no custom template exists
DEFAULT_TEMPLATES = {
    "cpp": "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    \n    return 0;\n}\n",
    "python": "# Solution for problem {problem_id}\n\n",
    "py": "# Solution for problem {problem_id}\n\n",
}


def _create_solution_file(solution_file: Path, language: str, contest_id: str, problem_id: str) -> None:
    """Create a solution file from template or default content."""
    try:
        config = Config()
        template_path = config.get_template_path(language)

        if template_path and template_path.exists():
            content = template_path.read_text()
            content = content.replace("$PROBLEM$", problem_id)
            content = content.replace("$CONTEST$", contest_id)
        else:
            content = DEFAULT_TEMPLATES.get(language, "").format(problem_id=problem_id)

        solution_file.write_text(content)
    except Exception:
        solution_file.touch()
