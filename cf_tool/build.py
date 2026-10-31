"""Building a code file before it runs, with a cache: a source that hasn't
changed is not compiled again.

Builds live in $XDG_CACHE_HOME/cf/build/<key>/, never next to the code. The
key covers the source, the build and run commands, the compiler's version
text and the files in the build's include folders (-I), so a change to any of
them builds afresh; a C/C++ source with a local `#include "..."` is rebuilt
every time (the header may have changed). Builds unused for a week are
removed.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cf_tool import paths, process
from cf_tool.errors import CFError
from cf_tool.languages import Setup

BUILD_TIMEOUT = 300.0  # seconds a compiler may take
MAX_AGE = 7 * 24 * 3600  # seconds an unused build is kept
_MARK = ".built"  # in a finished build's folder
_LOCAL_INCLUDE_RE = re.compile(rb'^\s*#\s*include\s*"', re.MULTILINE)
_pruned = False


class BuildFailed(CFError):
    """The compiler refused the code; its message is in output."""

    def __init__(self, message: str, output: str) -> None:
        super().__init__(message)
        self.output = output


@dataclass(frozen=True)
class Built:
    cached: bool  # nothing was compiled
    seconds: float
    messages: str  # what the compiler printed (warnings)


class Program:
    """A code file and how its language builds and runs it."""

    def __init__(self, source: Path | str, setup: Setup) -> None:
        self.source = Path(os.path.abspath(source))
        self.setup = setup
        self._folder: Path | None = None

    @property
    def name(self) -> str:
        return self.source.name

    def _key(self, code: bytes, headers: str) -> str:
        digest = hashlib.sha256()
        for part in (
            self.setup.fingerprint,
            "\0".join(self.setup.build or ()),
            "\0".join(self.setup.run),
            sys.platform,
            str(self.source),
            headers,
        ):
            digest.update(part.encode() + b"\1")
        digest.update(code)
        return digest.hexdigest()[:32]

    def _values(self, folder: Path | None) -> dict[str, str]:
        exe = self.source.stem + (".exe" if sys.platform == "win32" else "")
        values = {"src": str(self.source), "name": self.source.stem, "class": self.source.stem}
        if folder is not None:
            copy = folder / (self.setup.copy_as or self.source.name)
            values.update(dir=str(folder), exe=str(folder / exe), copy=str(copy))
        return values

    def build(self) -> Built:
        """Build the program, unless an identical build is cached; returns how
        it went. Raises BuildFailed with the compiler's output when it fails."""
        if self.setup.build is None:
            return Built(cached=True, seconds=0.0, messages="")
        try:
            code = self.source.read_bytes()
        except OSError as e:
            raise CFError(f"Cannot read {self.source}: {e.strerror or e}") from e
        headers = _headers_stamp(self.setup.build, self.source.parent)
        always = headers is None or bool(_LOCAL_INCLUDE_RE.search(code))
        folder = paths.CACHE_DIR / "build" / self._key(code, headers or "")
        self._folder = folder
        if (folder / _MARK).is_file() and not always:
            with contextlib.suppress(OSError):
                os.utime(folder / _MARK)  # NOTE: still in use, so not pruned
            return Built(cached=True, seconds=0.0, messages="")
        _prune()
        work = folder.with_name(f"{folder.name}.{os.getpid()}.tmp")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        values = self._values(work)
        if any("{copy}" in word for word in self.setup.build):
            shutil.copyfile(self.source, values["copy"])
        argv = fill(self.setup.build, values)
        started = time.perf_counter()
        result = process.run(argv, cwd=self.source.parent, timeout=BUILD_TIMEOUT)
        seconds = time.perf_counter() - started
        messages = (result.stdout + result.stderr).decode(errors="replace").strip()
        if not result.ok:
            shutil.rmtree(work, ignore_errors=True)
            if result.status == process.TIMEOUT:
                raise BuildFailed(f"Building {self.name} took over {BUILD_TIMEOUT:g}s", messages)
            raise BuildFailed(f"{self.name} doesn't compile ({result.reason()})", messages)
        (work / _MARK).write_text("", encoding="utf-8")
        if (folder / _MARK).is_file() and not always:
            shutil.rmtree(work, ignore_errors=True)  # NOTE: another cf built the same meanwhile
        else:
            shutil.rmtree(folder, ignore_errors=True)  # NOTE: a half-built or outdated one
            try:
                os.replace(work, folder)
            except OSError:  # NOTE: another cf put its build there just now
                shutil.rmtree(work, ignore_errors=True)
        return Built(cached=False, seconds=seconds, messages=messages)

    def argv(self) -> list[str]:
        """The command that runs the program (after build())."""
        if self.setup.build is not None and self._folder is None:
            raise CFError(f"{self.name} isn't built yet")
        return fill(self.setup.run, self._values(self._folder))

    def run(self, **options) -> process.Result:
        """Run the built program in its own folder (see process.run for options)."""
        return process.run(
            self.argv(), cwd=self.source.parent, big_stack=self.setup.big_stack, **options
        )


_INCLUDE_FLAGS = ("-isystem", "-iquote", "-idirafter", "-I")
MAX_HEADERS = 5000  # files under -I folders looked at; more: built every time


def _headers_stamp(build: tuple[str, ...], base: Path) -> str | None:
    """What the build's include folders (-I and the like, other than cf-tool's
    own) hold, as one text that changes whenever a file there does; None when
    they hold too many files to look at."""
    from cf_tool.languages import shim_folder

    folders = []
    for i, word in enumerate(build):
        for flag in _INCLUDE_FLAGS:
            if word == flag and i + 1 < len(build):
                folders.append(build[i + 1])
            elif word.startswith(flag) and len(word) > len(flag):
                folders.append(word[len(flag) :])
            else:
                continue
            break
    own = shim_folder()
    stamp = []
    for name in folders:
        folder = (base / Path(name).expanduser()).resolve()
        if "{" in name or folder == own.resolve() or not folder.is_dir():
            continue
        for root, _, files in os.walk(folder):
            for file in files:
                try:
                    info = os.stat(os.path.join(root, file))
                except OSError:
                    continue
                stamp.append(f"{root}/{file}:{info.st_mtime_ns}:{info.st_size}")
                if len(stamp) > MAX_HEADERS:
                    return None
    return "\n".join(sorted(stamp))


def fill(words: tuple[str, ...] | list[str], values: dict[str, str]) -> list[str]:
    """The words of a command with its placeholders filled in: {src} {exe}
    {dir} {name} {class} {copy} (the code, copied into {dir} before the
    build); one left unknown stays as written."""
    filled = []
    for word in words:
        for key, value in values.items():
            word = word.replace("{" + key + "}", value)
        filled.append(word)
    return filled


def _prune() -> None:
    """Remove builds unused for MAX_AGE (once per run)."""
    global _pruned
    if _pruned:
        return
    _pruned = True
    now = time.time()
    for entry in (paths.CACHE_DIR / "build").glob("*"):
        try:
            stamp = entry / _MARK
            age = now - (stamp.stat().st_mtime if stamp.exists() else entry.stat().st_mtime)
        except OSError:
            continue
        if age > MAX_AGE:
            shutil.rmtree(entry, ignore_errors=True)
