from __future__ import annotations

from pathlib import Path


def analyze(input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_study2.md").write_text("# study 2 report\n\nsynthetic data, pipeline test only\n")


if __name__ == "__main__":
    analyze(Path("results/study2_ingested.csv"), Path("results/study2"))
