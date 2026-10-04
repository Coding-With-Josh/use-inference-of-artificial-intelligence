from __future__ import annotations

from pathlib import Path


def save_figure(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic plot, pipeline test only")
