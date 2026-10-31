"""What `cf parse` learns about a problem besides its samples, kept in the
problem's folder for `cf test`: its limits, whether it is interactive, and
which test case each sample line belongs to."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FILE_NAME = ".cf-problem.json"

# per sample: the test case of each input line and of each answer line
Cases = tuple[list[int], list[int]]


@dataclass
class ProblemInfo:
    name: str = ""
    url: str = ""
    time_limit: float | None = None  # seconds
    memory_limit: int | None = None  # megabytes
    interactive: bool = False
    cases: list[Cases | None] = field(default_factory=list)  # one per in{i}/ans{i}

    def save(self, folder: Path) -> None:
        (folder / FILE_NAME).write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, folder: Path) -> ProblemInfo | None:
        """The info `cf parse` saved in folder; None if there is none or it is unreadable."""
        try:
            data = json.loads((folder / FILE_NAME).read_text(encoding="utf-8"))
            return cls(
                name=str(data.get("name", "")),
                url=str(data.get("url", "")),
                time_limit=_number(data.get("time_limit")),
                memory_limit=_number(data.get("memory_limit")),
                interactive=bool(data.get("interactive", False)),
                cases=[(list(c[0]), list(c[1])) if c else None for c in data.get("cases", [])],
            )
        except (OSError, ValueError, TypeError, IndexError, AttributeError):
            return None

    def sample_cases(self, sample_id: str) -> Cases | None:
        """The cases of sample in{sample_id}.txt, if the page marked them."""
        index = int(sample_id) - 1
        return self.cases[index] if 0 <= index < len(self.cases) else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
