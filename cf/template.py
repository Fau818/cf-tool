"""
Template management for generating code files.
"""

from pathlib import Path
from typing import Optional

from cf.config import Config
from cf.constants import SOLUTION_FILE_NAMES
from cf.utils import ensure_directory


def generate_from_template(
    contest_id: str, problem_id: str, language: str = "cpp"
) -> Path:
    """
    Generate a code file from template.

    Args:
        contest_id: Contest ID
        problem_id: Problem ID
        language: Programming language

    Returns:
        Path to generated file

    Raises:
        FileNotFoundError: If template not found
    """
    config = Config()
    template_path = config.get_template_path(language)

    if not template_path or not template_path.exists():
        raise FileNotFoundError(f"Template for {language} not found")

    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()

    # Simple variable substitution
    template_content = template_content.replace("$PROBLEM$", problem_id.upper())
    template_content = template_content.replace("$CONTEST$", contest_id)

    # Create output directory and file
    current_dir = Path.cwd()
    problem_dir = current_dir / contest_id / problem_id.upper()
    ensure_directory(problem_dir)

    solution_filename = SOLUTION_FILE_NAMES.get(language, f"solution.{language}")
    solution_file = problem_dir / solution_filename

    # Write solution file
    with open(solution_file, 'w') as f:
        f.write(template_content)

    return solution_file
