from __future__ import annotations

from pathlib import Path


def ingest(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("participant_id,task,correct,secure,confidence_correct,confidence_secure,time_s\n")
    output_path.write_text(output_path.read_text() + "1,t01,1,1,7,7,60\n")  # synthetic
    output_path.write_text("# synthetic data, pipeline test only\n")


if __name__ == "__main__":
    ingest(Path("synthetic/participants.csv"), Path("results/study2_ingested.csv"))
