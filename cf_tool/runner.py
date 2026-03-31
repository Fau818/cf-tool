"""
Code execution module for running solutions.
"""

import subprocess
import sys
import time as time_module
from pathlib import Path
from typing import List, Optional

from cf_tool.config import Config


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


def _run_process(
    cmd: List[str], input_data: str, timeout: float, cwd: Path
) -> ExecutionResult:
    """
    Run a process with the given command and input.

    Args:
        cmd: Command and arguments as a list
        input_data: Input data to pipe to stdin
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        ExecutionResult object
    """
    start_time = time_module.time()

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = process.communicate(
                input=input_data.encode('utf-8'), timeout=timeout
            )

            elapsed_time = time_module.time() - start_time

            return ExecutionResult(
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                returncode=process.returncode,
                time=elapsed_time,
            )

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            elapsed_time = time_module.time() - start_time

            return ExecutionResult(
                stdout="",
                stderr="",
                returncode=-1,
                time=elapsed_time,
                timeout=True,
                error=f"Time Limit Exceeded ({timeout}s)",
            )

    except Exception as e:
        elapsed_time = time_module.time() - start_time
        return ExecutionResult(
            stdout="",
            stderr="",
            returncode=-1,
            time=elapsed_time,
            error=f"Runtime error: {e}",
        )


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
    return _run_process([str(executable)], input_data, timeout, executable.parent)


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
    return _run_process([sys.executable, str(source_file)], input_data, timeout, source_file.parent)


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
        if executable is None:
            raise ValueError("Class file required for Java")
        classname = source_file.stem
        return _run_process(["java", classname], input_data, timeout, source_file.parent)

    else:
        raise ValueError(f"Unsupported language: {language}")
