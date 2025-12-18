"""
Code compilation module for C++ and other compiled languages.
"""

import subprocess
from pathlib import Path
from typing import Optional

from cf.config import Config
from cf.constants import DEFAULT_COMPILERS
from cf.utils import CompilationError


def compile_cpp(source_file: Path, output_file: Optional[Path] = None) -> Path:
    """
    Compile C++ source file.

    Args:
        source_file: Path to C++ source file
        output_file: Optional path to output executable

    Returns:
        Path to compiled executable

    Raises:
        CompilationError: If compilation fails
    """
    if not source_file.exists():
        raise CompilationError(f"Source file not found: {source_file}")

    # Default output file is same name without extension
    if output_file is None:
        output_file = source_file.with_suffix('')

    # Get compiler command from config
    config = Config()
    compiler_cmd = config.get_compiler_command("cpp")

    if not compiler_cmd:
        # Use default compiler command
        compiler_cmd = DEFAULT_COMPILERS["cpp"]

    # Build command
    # Replace placeholders
    cmd = compiler_cmd.format(source=str(source_file), output=str(output_file))

    # If format string didn't have placeholders, build manually
    if "{source}" not in compiler_cmd:
        cmd = f"{compiler_cmd} {source_file} -o {output_file}"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=source_file.parent,
        )

        if result.returncode != 0:
            error_msg = result.stderr if result.stderr else result.stdout
            raise CompilationError(f"Compilation failed:\n{error_msg}")

        if not output_file.exists():
            raise CompilationError("Compilation succeeded but executable not found")

        return output_file

    except subprocess.SubprocessError as e:
        raise CompilationError(f"Compilation error: {e}")


def compile_source(source_file: Path, language: str) -> Optional[Path]:
    """
    Compile source file based on language.

    Args:
        source_file: Path to source file
        language: Programming language

    Returns:
        Path to executable if compiled language, None if interpreted

    Raises:
        CompilationError: If compilation fails
    """
    if language in ["cpp", "c++"]:
        return compile_cpp(source_file)
    elif language == "c":
        # Similar to C++ but with different compiler
        config = Config()
        compiler_cmd = config.get_compiler_command("c")
        if not compiler_cmd:
            compiler_cmd = DEFAULT_COMPILERS.get("c", "gcc -O2 -Wall")

        output_file = source_file.with_suffix('')
        cmd = f"{compiler_cmd} {source_file} -o {output_file}"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=source_file.parent,
            )

            if result.returncode != 0:
                raise CompilationError(f"Compilation failed:\n{result.stderr}")

            return output_file

        except subprocess.SubprocessError as e:
            raise CompilationError(f"Compilation error: {e}")

    elif language in ["python", "py"]:
        # Python is interpreted, no compilation needed
        return None
    elif language == "java":
        # Java compilation
        try:
            result = subprocess.run(
                ["javac", str(source_file)],
                capture_output=True,
                text=True,
                cwd=source_file.parent,
            )

            if result.returncode != 0:
                raise CompilationError(f"Compilation failed:\n{result.stderr}")

            # Return the class file path (same name but .class)
            return source_file.with_suffix('.class')

        except subprocess.SubprocessError as e:
            raise CompilationError(f"Compilation error: {e}")
    else:
        raise CompilationError(f"Unsupported language: {language}")
