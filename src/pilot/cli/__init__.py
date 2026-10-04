from __future__ import annotations

import json
from pathlib import Path

import typer

from pilot.runner import run as runner
from pilot.tasks import validate as tasks_validate

app = typer.Typer(help="Pilot model experiment harness.")

REPO_ROOT = Path(__file__).resolve().parents[3]


@app.command("study1-plan")
def study1_plan() -> None:
    """Print the trial plan and cost estimate. Spends nothing."""
    result = runner.plan()
    typer.echo(
        f"trials={result['trials']} tasks={result['tasks']} "
        f"cost_estimate_usd={result['cost_estimate_usd']} "
        f"within_budget={result['within_budget']}"
    )


@app.command("study1-run")
def study1_run(
    run_id: str = typer.Option("study1", help="Run identifier."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan without calling a model."),
    no_resume: bool = typer.Option(False, "--no-resume", help="Ignore existing trial log."),
) -> None:
    """Execute the study-1 trial matrix."""
    try:
        summary = runner.run(run_id=run_id, dry_run=dry_run, resume=not no_resume)
    except runner.BudgetExceeded as exc:
        typer.echo(f"budget guard: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    typer.echo(
        f"run_id={summary['run_id']} executed={summary['executed']} "
        f"skipped={summary['skipped']} spent_usd={summary['spent_usd']} "
        f"dry_run={summary['dry_run']}"
    )


@app.command("study1-analyze")
def study1_analyze(
    run_id: str = typer.Option("study1", help="Run identifier to analyze."),
    no_figures: bool = typer.Option(False, "--no-figures", help="Skip figure rendering."),
) -> None:
    """Analyze a run and write the report."""
    analysis = runner.analyze(run_id=run_id, figures=not no_figures)
    typer.echo(f"report={analysis['report']} trials={analysis['n_trials']}")


@app.command("tasks-validate")
def tasks_validate_cmd(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show failing test names."),
) -> None:
    """Run every reference and starter in the sandbox and check the contract."""
    try:
        code = tasks_validate.validate(verbose=verbose)
    except Exception as exc:  # sandbox unavailable -> distinct exit code
        from pilot.sandbox import docker_runner

        if isinstance(exc, docker_runner.SandboxUnavailable):
            typer.echo(f"sandbox unavailable: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        raise
    raise typer.Exit(code=code)


@app.command("demo-mock")
def demo_mock() -> None:
    """End-to-end pipeline on the mock model, producing a watermarked report.

    Writes under results/demo-mock/ only. Never contacts a real provider.
    """
    from pilot.analysis import report as report_mod
    from pilot.scoring import metrics

    out_dir = REPO_ROOT / "results" / "demo-mock"
    out_dir.mkdir(parents=True, exist_ok=True)

    run_id = "demo-mock"
    summary = runner.run(run_id=run_id, conditions=("b", "c"))
    analysis = runner.analyze(run_id=run_id, output_dir=out_dir)

    manifest = {
        "synthetic": True,
        "watermark": report_mod.WATERMARK,
        "run": summary,
        "n_trials": analysis["n_trials"],
        # Measurement status travels with the artefact: a consumer reading only
        # the manifest must be able to tell a measured zero from no measurement.
        "n_graded": analysis["n_graded"],
        "n_ungraded": analysis["n_ungraded"],
        "ungraded_reasons": analysis["ungraded_reasons"],
        "report": analysis["report"],
        "figures": analysis["figures"],
        "metrics_check": {
            "hidden_pass_rate_empty": metrics.hidden_pass_rate([]),
            "task_solved_empty": metrics.task_solved([]),
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    typer.echo(f"report={analysis['report']}")
    typer.echo(f"figures={len(analysis['figures'])}")
    typer.echo(f"manifest={manifest_path}")
    typer.echo(f"NOTE: {report_mod.WATERMARK}")


@app.command("study2-randomize")
def study2_randomize() -> None:
    from study2 import randomize

    randomize.randomize(REPO_ROOT / "synthetic" / "randomization.csv")


@app.command("study2-ingest")
def study2_ingest() -> None:
    from study2 import ingest

    ingest.ingest(
        REPO_ROOT / "synthetic" / "participants.csv",
        REPO_ROOT / "results" / "study2_ingested.csv",
    )


@app.command("study2-analyze")
def study2_analyze() -> None:
    from study2 import analysis

    analysis.analyze(
        REPO_ROOT / "results" / "study2_ingested.csv",
        REPO_ROOT / "results" / "study2",
    )


@app.command("demo")
def demo() -> None:
    """Deprecated alias for demo-mock."""
    typer.echo("`demo` is deprecated; use `demo-mock`.", err=True)
    demo_mock()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
