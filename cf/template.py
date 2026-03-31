"""
Template management for generating code files.
"""

from pathlib import Path
from typing import Optional

from cf.config import Config
from cf.constants import SOLUTION_FILE_NAMES
from cf.utils import ensure_directory


def generate_from_template(
    contest_id: str, problem_id: str, language: str = "cpp",
    alias: Optional[str] = None,
) -> Path:
    """
    Generate a code file from template.

    Args:
        contest_id: Contest ID
        problem_id: Problem ID
        language: Programming language
        alias: Optional template alias to use

    Returns:
        Path to generated file

    Raises:
        FileNotFoundError: If template not found
    """
    config = Config()
    template_path = None

    if alias:
        # Use specific named template
        tmpl = config.get_template_by_alias(alias)
        if tmpl:
            path = Path(tmpl["path"]).expanduser()
            if path.exists():
                template_path = path
            else:
                raise FileNotFoundError(f"Template file not found: {tmpl['path']}")
    else:
        # Try named template system first (default for language)
        tmpl = config.get_default_template(language)
        if tmpl:
            path = Path(tmpl["path"]).expanduser()
            if path.exists():
                template_path = path

        # Fall back to legacy template path
        if not template_path:
            template_path = config.get_template_path(language)

    if not template_path or not template_path.exists():
        raise FileNotFoundError(f"Template for {language} not found")

    template_content = template_path.read_text()

    # Variable substitution
    template_content = template_content.replace("$PROBLEM$", problem_id.upper())
    template_content = template_content.replace("$CONTEST$", contest_id)

    # Create output directory and file
    current_dir = Path.cwd()
    problem_dir = current_dir / contest_id / problem_id.upper()
    ensure_directory(problem_dir)

    solution_filename = SOLUTION_FILE_NAMES.get(language, f"solution.{language}")
    solution_file = problem_dir / solution_filename

    # Handle filename collision with numeric suffix
    if solution_file.exists():
        base = solution_file.stem
        ext = solution_file.suffix
        counter = 1
        while solution_file.exists():
            solution_file = problem_dir / f"{base}{counter}{ext}"
            counter += 1

    solution_file.write_text(template_content)
    return solution_file
