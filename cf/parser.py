"""
Problem parsing module - orchestrates downloading and setting up problems.
"""

import json
from pathlib import Path
from typing import Dict

from cf.config import Config
from cf.constants import PROBLEM_METADATA_FILE, SOLUTION_FILE_NAMES, TEST_INPUT_PATTERN, TEST_OUTPUT_PATTERN
from cf.scraper import CodeforceScraper
from cf.template import generate_from_template
from cf.utils import ensure_directory, ParseError


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

    # Check if solution file already exists
    if not solution_file.exists():
        try:
            # Try to generate from template
            config = Config()
            template_path = config.get_template_path(language)

            if template_path and template_path.exists():
                # Copy template to solution file
                with open(template_path, 'r') as f:
                    template_content = f.read()

                # Simple variable substitution
                template_content = template_content.replace("$PROBLEM$", problem_id)
                template_content = template_content.replace("$CONTEST$", contest_id)

                with open(solution_file, 'w') as f:
                    f.write(template_content)
            else:
                # Create empty solution file
                with open(solution_file, 'w') as f:
                    if language == "cpp":
                        f.write("#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    \n    return 0;\n}\n")
                    elif language in ["python", "py"]:
                        f.write("# Solution for problem " + problem_id + "\n\n")

        except Exception as e:
            # If template generation fails, just create empty file
            solution_file.touch()

    return {
        "contest_id": contest_id,
        "problem_id": problem_id,
        "directory": str(problem_dir),
        "test_count": len(test_cases),
        "solution_file": str(solution_file),
        "metadata": metadata,
    }
