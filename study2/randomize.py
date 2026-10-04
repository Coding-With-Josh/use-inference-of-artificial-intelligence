from __future__ import annotations

import csv
from pathlib import Path


def randomize(output: Path | str, seed: int = 42) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["participant_id", "condition_order", "task_order"])
        writer.writerow([1, "a,b,c", "t01,t02,t03,t04,t05,t06,t07,t08,t09,t10"])


if __name__ == "__main__":
    randomize(Path("synthetic/randomization.csv"))
