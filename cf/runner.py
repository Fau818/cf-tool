"""
Code execution module for running solutions.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from cf.config import Config


class ExecutionResult:
    """Result of code execution."""

    def __init__(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
        time: float,
        timeout: bool = False,
        error: Optional[str] = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.time = time
        self.timeout = timeout
        self.error = error


def run_executable(
    executable: Path, input_data: str, timeout: float = 2.0
) -> ExecutionResult:
    """
    Run compiled executable with input.

    Args:
        executable: Path to executable file
        input_data: Input data to pipe to stdin
        timeout: Timeout in seconds

    Returns:
        ExecutionResult object
    """
    import time

    start_time = time.time()

    try:
        process = subprocess.Popen(
            [str(executable)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=executable.parent,
        )

        try:
            stdout, stderr = process.communicate(
                input=input_data.encode('utf-8'), timeout=timeout
            )

            elapsed_time = time.time() - start_time

            return ExecutionResult(
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                returncode=process.returncode,
                time=elapsed_time,
            )

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            elapsed_time = time.time() - start_time

            return ExecutionResult(
                stdout="",
                stderr="",
                returncode=-1,
                time=elapsed_time,
                timeout=True,
                error=f"Time Limit Exceeded ({timeout}s)",
            )

    except Exception as e:
        elapsed_time = time.time() - start_time
        return ExecutionResult(
            stdout="",
            stderr="",
            returncode=-1,
            time=elapsed_time,
            error=f"Runtime error: {e}",
        )


def run_python(source_file: Path, input_data: str, timeout: float = 2.0) -> ExecutionResult:
    """
    Run Python script with input.

    Args:
        source_file: Path to Python source file
        input_data: Input data to pipe to stdin
        timeout: Timeout in seconds

    Returns:
        ExecutionResult object
    """
    import time

    start_time = time.time()

    # Use the same Python interpreter that's running this code
    python_cmd = sys.executable

    try:
        process = subprocess.Popen(
            [python_cmd, str(source_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=source_file.parent,
        )

        try:
            stdout, stderr = process.communicate(
                input=input_data.encode('utf-8'), timeout=timeout
            )

            elapsed_time = time.time() - start_time

            return ExecutionResult(
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                returncode=process.returncode,
                time=elapsed_time,
            )

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            elapsed_time = time.time() - start_time

            return ExecutionResult(
                stdout="",
                stderr="",
                returncode=-1,
                time=elapsed_time,
                timeout=True,
                error=f"Time Limit Exceeded ({timeout}s)",
            )

    except Exception as e:
        elapsed_time = time.time() - start_time
        return ExecutionResult(
            stdout="",
            stderr="",
            returncode=-1,
            time=elapsed_time,
            error=f"Runtime error: {e}",
        )


def run_code(
    source_file: Path,
    language: str,
    input_data: str,
    executable: Optional[Path] = None,
    timeout: Optional[float] = None,
) -> ExecutionResult:
    """
    Run code with input based on language.

    Args:
        source_file: Path to source file
        language: Programming language
        input_data: Input data to pipe to stdin
        executable: Optional path to compiled executable (for compiled languages)
        timeout: Optional timeout in seconds

    Returns:
        ExecutionResult object
    """
    if timeout is None:
        config = Config()
        timeout = config.get("timeout", 2.0)

    if language in ["cpp", "c++", "c"]:
        if executable is None:
            raise ValueError("Executable path required for compiled languages")
        return run_executable(executable, input_data, timeout)

    elif language in ["python", "py"]:
        return run_python(source_file, input_data, timeout)

    elif language == "java":
        # Java execution is more complex, for now just support basic case
        if executable is None:
            raise ValueError("Class file required for Java")

        import time

        start_time = time.time()

        # Extract class name from source file
        classname = source_file.stem

        try:
            process = subprocess.Popen(
                ["java", classname],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=source_file.parent,
            )

            try:
                stdout, stderr = process.communicate(
                    input=input_data.encode('utf-8'), timeout=timeout
                )

                elapsed_time = time.time() - start_time

                return ExecutionResult(
                    stdout=stdout.decode('utf-8', errors='replace'),
                    stderr=stderr.decode('utf-8', errors='replace'),
                    returncode=process.returncode,
                    time=elapsed_time,
                )

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                elapsed_time = time.time() - start_time

                return ExecutionResult(
                    stdout="",
                    stderr="",
                    returncode=-1,
                    time=elapsed_time,
                    timeout=True,
                    error=f"Time Limit Exceeded ({timeout}s)",
                )

        except Exception as e:
            elapsed_time = time.time() - start_time
            return ExecutionResult(
                stdout="",
                stderr="",
                returncode=-1,
                time=elapsed_time,
                error=f"Runtime error: {e}",
            )

    else:
        raise ValueError(f"Unsupported language: {language}")
