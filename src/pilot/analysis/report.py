from __future__ import annotations

from pathlib import Path


def write_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# report\n\nsynthetic data, pipeline test only\n")
