"""
Code compilation module for C++ and other compiled languages.
"""

import subprocess
from pathlib import Path
from typing import List, Optional

from cf.config import Config
from cf.constants import DEFAULT_COMPILERS
from cf.utils import CompilationError


def _compile(
    cmd: List[str],
    source_file: Path,
    output_file: Path,
    use_shell: bool = False,
) -> Path:
    """
    Compile source file using the given command.

    Args:
        cmd: Compiler command as list or string (if use_shell=True)
        source_file: Path to source file
        output_file: Path to output executable
        use_shell: Whether to use shell execution

    Returns:
        Path to compiled executable

    Raises:
        CompilationError: If compilation fails
    """
    try:
        if use_shell:
            result = subprocess.run(
                ' '.join(cmd) if isinstance(cmd, list) else cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=source_file.parent,
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=source_file.parent,
            )

        if result.returncode != 0:
            error_msg = result.stderr if result.stderr else result.stdout
            raise CompilationError(f"Compilation failed:\n{error_msg}")

        if output_file.suffix != '.class' and not output_file.exists():
            raise CompilationError("Compilation succeeded but executable not found")

        return output_file

    except subprocess.SubprocessError as e:
        raise CompilationError(f"Compilation error: {e}")


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

    if output_file is None:
        output_file = source_file.with_suffix('')

    config = Config()
    compiler_cmd = config.get_compiler_command("cpp")

    if not compiler_cmd:
        compiler_cmd = DEFAULT_COMPILERS["cpp"]

    # Build command with placeholders
    if "{source}" in compiler_cmd:
        cmd = compiler_cmd.format(source=str(source_file), output=str(output_file))
    else:
        cmd = f"{compiler_cmd} {source_file} -o {output_file}"

    return _compile([cmd], source_file, output_file, use_shell=True)


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
        config = Config()
        compiler_cmd = config.get_compiler_command("c")
        if not compiler_cmd:
            compiler_cmd = DEFAULT_COMPILERS.get("c", "gcc -O2 -Wall")

        output_file = source_file.with_suffix('')
        cmd = f"{compiler_cmd} {source_file} -o {output_file}"
        return _compile([cmd], source_file, output_file, use_shell=True)

    elif language in ["python", "py"]:
        return None

    elif language == "java":
        output_file = source_file.with_suffix('.class')
        return _compile(["javac", str(source_file)], source_file, output_file)

    else:
        raise CompilationError(f"Unsupported language: {language}")
