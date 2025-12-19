"""
Testing module for running solutions against test cases.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from cf.compiler import compile_source
from cf.constants import TEST_INPUT_PATTERN, TEST_OUTPUT_PATTERN
from cf.runner import run_code
from cf.utils import detect_language, find_solution_file, normalize_whitespace


def find_test_cases(directory: Path) -> List[int]:
    """
    Find all test case numbers in a directory.

    Args:
        directory: Directory to search

    Returns:
        Sorted list of test case numbers
    """
    test_numbers = set()

    for file in directory.iterdir():
        if file.is_file():
            match = re.match(r'in(\d+)\.txt', file.name)
            if match:
                test_numbers.add(int(match.group(1)))

    return sorted(test_numbers)


def _make_result(
    test_num: int,
    passed: bool,
    time: float,
    error: Optional[str] = None,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
) -> Dict:
    """Create a test result dictionary."""
    result = {"test_number": test_num, "passed": passed, "time": time}
    if error:
        result["error"] = error
    if expected is not None:
        result["expected"] = expected
        result["actual"] = actual
    return result


def run_tests(solution_file: Optional[str] = None) -> List[Dict]:
    """
    Run solution against all test cases.

    Args:
        solution_file: Optional path to solution file. If not provided, auto-detect.

    Returns:
        List of test result dictionaries

    Raises:
        FileNotFoundError: If solution file or test cases not found
        ValueError: If language cannot be detected
    """
    # Determine solution file
    if solution_file:
        solution_path = Path(solution_file)
        if not solution_path.exists():
            raise FileNotFoundError(f"Solution file not found: {solution_file}")
        problem_dir = solution_path.parent
    else:
        problem_dir = Path.cwd()
        solution_path = find_solution_file(problem_dir)

        if not solution_path:
            raise FileNotFoundError(
                "No solution file found. Please specify a file with --file option."
            )

    # Detect language
    language = detect_language(solution_path)
    if not language:
        raise ValueError(f"Cannot detect language from file: {solution_path}")

    # Find test cases
    test_numbers = find_test_cases(problem_dir)
    if not test_numbers:
        raise FileNotFoundError(f"No test cases found in {problem_dir}")

    # Compile if needed
    executable = None
    if language in ["cpp", "c++", "c", "java"]:
        try:
            executable = compile_source(solution_path, language)
        except Exception as e:
            return [_make_result(0, False, 0.0, error=f"Compilation failed: {e}")]

    # Run tests
    results = []

    for test_num in test_numbers:
        input_file = problem_dir / TEST_INPUT_PATTERN.format(test_num)
        output_file = problem_dir / TEST_OUTPUT_PATTERN.format(test_num)

        if not input_file.exists() or not output_file.exists():
            results.append(_make_result(test_num, False, 0.0, error="Test case files not found"))
            continue

        input_data = input_file.read_text()
        expected_output = output_file.read_text()

        try:
            exec_result = run_code(solution_path, language, input_data, executable)

            if exec_result.timeout or exec_result.error:
                results.append(_make_result(test_num, False, exec_result.time, error=exec_result.error))
                continue

            if exec_result.returncode != 0:
                error_msg = "Runtime Error"
                if exec_result.stderr:
                    error_msg += f": {exec_result.stderr[:200]}"
                results.append(_make_result(test_num, False, exec_result.time, error=error_msg))
                continue

            # Compare outputs
            actual_output = exec_result.stdout
            if normalize_whitespace(actual_output) == normalize_whitespace(expected_output):
                results.append(_make_result(test_num, True, exec_result.time))
            else:
                results.append(_make_result(
                    test_num, False, exec_result.time,
                    expected=expected_output, actual=actual_output
                ))

        except Exception as e:
            results.append(_make_result(test_num, False, 0.0, error=str(e)))

    return results
