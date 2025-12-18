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
            # Match in1.txt, in2.txt, etc.
            match = re.match(r'in(\d+)\.txt', file.name)
            if match:
                test_numbers.add(int(match.group(1)))

    return sorted(test_numbers)


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
        # Auto-detect solution file in current directory
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
            # Return compilation error as a test result
            return [
                {
                    "test_number": 0,
                    "passed": False,
                    "error": f"Compilation failed: {e}",
                    "time": 0.0,
                }
            ]

    # Run tests
    results = []

    for test_num in test_numbers:
        input_file = problem_dir / TEST_INPUT_PATTERN.format(test_num)
        output_file = problem_dir / TEST_OUTPUT_PATTERN.format(test_num)

        if not input_file.exists() or not output_file.exists():
            results.append(
                {
                    "test_number": test_num,
                    "passed": False,
                    "error": "Test case files not found",
                    "time": 0.0,
                }
            )
            continue

        # Read input and expected output
        with open(input_file, 'r') as f:
            input_data = f.read()

        with open(output_file, 'r') as f:
            expected_output = f.read()

        # Run code
        try:
            exec_result = run_code(solution_path, language, input_data, executable)

            if exec_result.timeout:
                results.append(
                    {
                        "test_number": test_num,
                        "passed": False,
                        "error": exec_result.error,
                        "time": exec_result.time,
                    }
                )
                continue

            if exec_result.error:
                results.append(
                    {
                        "test_number": test_num,
                        "passed": False,
                        "error": exec_result.error,
                        "time": exec_result.time,
                    }
                )
                continue

            if exec_result.returncode != 0:
                error_msg = "Runtime Error"
                if exec_result.stderr:
                    error_msg += f": {exec_result.stderr[:200]}"
                results.append(
                    {
                        "test_number": test_num,
                        "passed": False,
                        "error": error_msg,
                        "time": exec_result.time,
                    }
                )
                continue

            # Compare outputs
            actual_output = exec_result.stdout
            actual_normalized = normalize_whitespace(actual_output)
            expected_normalized = normalize_whitespace(expected_output)

            if actual_normalized == expected_normalized:
                results.append(
                    {
                        "test_number": test_num,
                        "passed": True,
                        "time": exec_result.time,
                    }
                )
            else:
                results.append(
                    {
                        "test_number": test_num,
                        "passed": False,
                        "expected": expected_output,
                        "actual": actual_output,
                        "time": exec_result.time,
                    }
                )

        except Exception as e:
            results.append(
                {
                    "test_number": test_num,
                    "passed": False,
                    "error": str(e),
                    "time": 0.0,
                }
            )

    return results
