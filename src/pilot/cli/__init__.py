from __future__ import annotations

import sys
from pathlib import Path

import typer

from pilot.runner import run as runner
from pilot.tasks import validate as tasks_validate

app = typer.Typer()


@app.command()
def study1_plan() -> None:
    result = runner.plan()
    typer.echo(f"trials={result['trials']} cost_estimate_usd={result['cost_estimate_usd']}")


@app.command()
def study1_run() -> None:
    runner.run()


@app.command()
def study1_analyze() -> None:
    runner.analyze()


@app.command(name="tasks-validate")
def tasks_validate_cmd() -> None:
    sys.exit(tasks_validate.validate())


@app.command()
def study2_randomize() -> None:
    from study2 import randomize

    randomize.randomize(Path("synthetic/randomization.csv"))


@app.command()
def study2_ingest() -> None:
    from study2 import ingest

    ingest.ingest(Path("synthetic/participants.csv"), Path("results/study2_ingested.csv"))


@app.command()
def study2_analyze() -> None:
    from study2 import analysis

    analysis.analyze(Path("results/study2_ingested.csv"), Path("results/study2"))


@app.command()
def demo() -> None:
    Path("results/demo").mkdir(parents=True, exist_ok=True)
    (Path("results/demo/report.md")).write_text("# demo report\n\nsynthetic data, pipeline test only\n")


def main() -> None:
    app()
