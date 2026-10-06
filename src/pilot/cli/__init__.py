from __future__ import annotations

import json
from pathlib import Path

import typer

from pilot.models.http import BaseUrlBlocked, ProviderError
from pilot.models.registry import (
    check_configured_base_url,
    describe_unusual_base_url,
    resolve,
)
from pilot.runner import run as runner
from pilot.tasks import validate as tasks_validate

app = typer.Typer(help="Pilot model experiment harness.")

REPO_ROOT = Path(__file__).resolve().parents[3]


@app.command("study1-plan")
def study1_plan(
    allow_custom_base_url: bool = typer.Option(
        False,
        "--allow-custom-base-url",
        help=(
            "Permit a *_BASE_URL that is not the provider's official host, so the "
            "API key may be sent there. Recorded in every trial's provenance."
        ),
    ),
) -> None:
    """Print the trial plan and cost estimate. Spends nothing.

    Also resolves the configured provider, so an unsupported or misspelled
    PROVIDER is reported here -- before any run -- instead of at the first paid
    API call. Without this, a typo looked like a valid plan.
    """
    cfg = runner.load_config()
    if allow_custom_base_url:
        cfg.model.allow_custom_base_url = True
    try:
        result = runner.plan(cfg)
        # Resolution is pure: it imports the adapter and reads config, it does
        # not construct a client or open a connection.
        resolve(result["provider"])
    except ValueError as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    # A non-official base URL redirects the API key to another host. Refused here
    # (exit 4, before anything runs) unless the operator opted in with
    # --allow-custom-base-url; when they did, it is stated in plain sight.
    try:
        check_configured_base_url(cfg)
    except BaseUrlBlocked as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    note = describe_unusual_base_url(cfg)
    if note:
        typer.echo(f"note: {note}", err=True)

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
    ablate: str = typer.Option(
        "",
        "--ablate",
        help="Comma-separated condition-C ablations: context,decomposition,guardrails.",
    ),
    allow_custom_base_url: bool = typer.Option(
        False,
        "--allow-custom-base-url",
        help=(
            "Permit a *_BASE_URL that is not the provider's official host, so the "
            "API key may be sent there. Recorded in every trial's provenance."
        ),
    ),
    tasks: str = typer.Option(
        "",
        "--tasks",
        help="Comma-separated task ids to run, e.g. --tasks t01,t07. Empty = all.",
    ),
    trials: int = typer.Option(
        0,
        "--trials",
        help="Replicates per (task, condition). 0 = the configured N_TRIALS.",
    ),
    conditions: str = typer.Option(
        "",
        "--conditions",
        help="Comma-separated conditions to run, e.g. --conditions b,c. Empty = all three.",
    ),
) -> None:
    """Execute the study-1 trial matrix.

    `--tasks t01,t07 --trials 3 --conditions b,c --dry-run` is the pilot-mode
    preview: it prints exactly which trials would run, in what order, for which
    provider, and what it would cost, without calling a model or grading
    anything.
    """
    # Parsed and validated before any spend: an unknown ablation name must not
    # be discovered only after the trials it was meant to disable have run.
    try:
        ablations = runner.parse_ablation(ablate)
        task_filter = runner.parse_task_filter(tasks)
        condition_filter = runner.parse_conditions(conditions)
    except ValueError as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    # Loaded through `runner.load_config`, not a direct import, so a caller that
    # patches the runner's config source still controls this command.
    cfg = runner.load_config()
    cfg.experiment.ablation = ",".join(ablations) or None
    if trials:
        if trials < 1:
            typer.echo("configuration error: --trials must be >= 1", err=True)
            raise typer.Exit(code=4)
        cfg.experiment.n_trials = trials

    # The flag is the explicit opt-in for redirecting the credential. It is
    # checked before anything runs, so a stale *_BASE_URL costs nothing.
    if allow_custom_base_url:
        cfg.model.allow_custom_base_url = True
    try:
        check_configured_base_url(cfg)
    except BaseUrlBlocked as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    note = describe_unusual_base_url(cfg)
    if note:
        typer.echo(f"note: {note}", err=True)

    try:
        summary = runner.run(
            cfg,
            run_id=run_id,
            conditions=condition_filter or runner.CONDITIONS,
            task_filter=task_filter,
            dry_run=dry_run,
            resume=not no_resume,
        )
    except runner.BudgetExceeded as exc:
        typer.echo(f"budget guard: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    except ProviderError as exc:
        # Misconfiguration must be one actionable line, not a Rich traceback.
        # The message is already redacted by `pilot.models.http`.
        typer.echo(f"provider error: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    if dry_run:
        typer.echo(
            f"DRY RUN: run_id={summary['run_id']} would execute "
            f"{summary['planned_trials']} trial(s) "
            f"for provider {summary['provider']}"
        )
        for line in summary["planned_order"]:
            typer.echo(f"  would run {line}")
        typer.echo(
            f"DRY RUN: estimated_cost_usd={summary['cost_estimate_usd']} "
            f"within_budget={summary['within_budget']} "
            f"(no model called, nothing graded, nothing written)"
        )
        return

    typer.echo(
        f"run_id={summary['run_id']} executed={summary['executed']} "
        f"skipped={summary['skipped']} ungraded={summary['ungraded']} "
        f"retried_first={summary['retried_first']} "
        f"spent_usd={summary['spent_usd']} dry_run={summary['dry_run']}"
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
def demo_mock(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Exercise control flow without calling a model or grading."
    ),
) -> None:
    """End-to-end pipeline on the mock model, producing a watermarked report.

    Writes under results/demo-mock/ only. Never contacts a real provider.

    The provider is pinned to the mock rather than inherited from the
    environment. This command's contract is that it is offline and synthetic,
    so a `PROVIDER` set in the operator's shell must not be able to turn a
    watermarked pipeline test into a real, billed API run -- nor let the
    `synthetic: true` below describe data that came from a live model.
    """
    from pilot.analysis import report as report_mod
    from pilot.scoring import metrics

    out_dir = REPO_ROOT / "results" / "demo-mock"
    out_dir.mkdir(parents=True, exist_ok=True)

    run_id = "demo-mock"
    cfg = runner.load_config()
    cfg.model.provider = "mock"
    cfg.model.id = "mock"
    # One replicate per (task, condition). The replicate loop is real now, so at
    # the configured N_TRIALS this would be 10 x 2 x 20 = 400 trials and ~50
    # minutes. A pipeline smoke test needs to prove the pipeline works, not to
    # collect a sample, so it takes 20 trials and stays in CI budget.
    cfg.experiment.n_trials = 1
    summary = runner.run(cfg, run_id=run_id, conditions=("b", "c"), dry_run=dry_run)
    analysis = runner.analyze(run_id=run_id, output_dir=out_dir)

    manifest = {
        # Derived from the run that actually happened, not asserted. If the pin
        # above were ever removed, this would report False rather than lying.
        "synthetic": summary["synthetic"],
        "provider": summary["provider"],
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
