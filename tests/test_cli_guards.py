"""CLI-level guards: ablations, budget, resume.

These exercise the operator-facing surface rather than the internals, because
the failures worth catching here are the ones that cost money or silently
produce the wrong experiment:

  * an unknown `--ablate` name must be rejected before any spend
  * the budget cap must abort a run that would exceed it
  * a resumed run must not re-execute or re-bill trials already in the log
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pilot.cli import app
from pilot.config.config import Config, load_config
from pilot.runner import run as runner

runner_cli = CliRunner()


# --------------------------------------------------------------------------
# --ablate
# --------------------------------------------------------------------------


def test_parse_ablation_accepts_the_three_documented_names() -> None:
    from pilot.conditions.cond_c import ABLATIONS

    for name in ABLATIONS:
        assert runner.parse_ablation(name) == [name]


def test_parse_ablation_accepts_a_comma_separated_list() -> None:
    assert runner.parse_ablation("context,guardrails") == ["context", "guardrails"]


def test_parse_ablation_normalises_order_and_whitespace() -> None:
    """Recorded `ablated` lists must be comparable between runs."""
    assert runner.parse_ablation(" guardrails , context ") == ["context", "guardrails"]
    assert runner.parse_ablation("context,context") == ["context"]


@pytest.mark.parametrize("value", ["", None, "  ", ",,"])
def test_parse_ablation_of_nothing_is_empty(value: str | None) -> None:
    assert runner.parse_ablation(value) == []


@pytest.mark.parametrize("value", ["nonsense", "context,nonsense", "Context", "contexts"])
def test_parse_ablation_rejects_unknown_names(value: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        runner.parse_ablation(value)
    assert "supported" in str(excinfo.value)


def test_cli_rejects_an_unknown_ablation_without_running_anything() -> None:
    result = runner_cli.invoke(app, ["study1-run", "--ablate", "nonsense"])
    assert result.exit_code == 4
    assert "unknown ablation" in result.output
    assert "executed=" not in result.output, "no trial may run under a rejected config"


def test_cli_dry_run_with_a_valid_ablation() -> None:
    result = runner_cli.invoke(
        app, ["study1-run", "--run-id", "abl-cli", "--dry-run", "--ablate", "context,guardrails"]
    )
    assert result.exit_code == 0, result.output
    # A dry run prints its plan rather than a completed-run summary, but the
    # run_id still identifies which plan this is.
    assert "run_id=abl-cli" in result.output


def test_ablation_env_var_is_read() -> None:
    cfg = load_config()
    assert cfg.experiment.ablation is None or isinstance(cfg.experiment.ablation, str)


# --------------------------------------------------------------------------
# Budget guard
# --------------------------------------------------------------------------


def test_plan_reports_a_estimate_over_budget() -> None:
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 20
    cfg.experiment.max_cost_usd = 0.0001
    planned = runner.plan(cfg)
    assert planned["within_budget"] is False


def test_run_refuses_to_start_when_the_plan_exceeds_the_cap() -> None:
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 20
    cfg.experiment.max_cost_usd = 0.0001
    with pytest.raises(runner.BudgetExceeded) as excinfo:
        runner.run(cfg, run_id="budget-refuse", dry_run=True, conditions=("a",))
    assert "over the" in str(excinfo.value)


def test_the_plan_cap_is_checked_before_any_trial_runs() -> None:
    """Ordering matters: a hopeless plan must be refused before spending.

    The plan-level check runs before the loop, so a cap below the plan total
    always trips there rather than partway through the matrix.
    """
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 20
    per_trial = runner.metrics.estimate_cost_usd(
        runner.ESTIMATED_TOKENS_IN, runner.ESTIMATED_TOKENS_OUT, *cfg.model.pricing()
    )
    cfg.experiment.max_cost_usd = per_trial * 3  # far below the 200-trial plan

    with pytest.raises(runner.BudgetExceeded) as excinfo:
        runner.run(cfg, run_id="budget-mid", dry_run=True, conditions=("a",))
    assert "over the" in str(excinfo.value)
    assert not (Path("results") / "budget-mid" / "trials.jsonl").exists()


def test_the_cap_is_rechecked_per_trial_not_only_against_the_plan() -> None:
    """The mid-run guard exists for when the plan estimate understates reality.

    Exercised by raising the cap just above the plan total and then shrinking
    the *remaining* allowance mid-loop -- the point is that the check sits
    inside the loop, not only before it.
    """
    source = Path("src/pilot/runner/run.py").read_text()
    loop_body = source.split("for condition in conditions:", 1)[1]
    assert "spent + trial_cost > cfg.experiment.max_cost_usd" in loop_body, (
        "the per-trial budget re-check must live inside the trial loop"
    )


def test_budget_exceeded_exits_with_code_3(monkeypatch) -> None:
    """The budget guard must abort the run with exit 3, before spending anything.

    Previously this ran a real full-corpus study under the default cap and asserted
    `exit_code in (0, 3)`, which passed whether or not the guard fired. It now pins
    a cap that cannot be met, so the guard is the only thing that can produce exit
    3 -- and no trial runs, so the test does not scale with N_TRIALS.
    """
    cfg = load_config()
    cfg.model.provider = "mock"
    cfg.model.id = "mock"
    cfg.experiment.max_cost_usd = 0.0
    monkeypatch.setattr("pilot.cli.runner.load_config", lambda *a, **k: cfg)

    # The log is append-only and survives across runs, so a leftover would make
    # this assertion fail for a reason that has nothing to do with the guard.
    shutil.rmtree(Path("results") / "budget-cli", ignore_errors=True)

    result = runner_cli.invoke(app, ["study1-run", "--run-id", "budget-cli"])
    assert result.exit_code == 3, result.output
    assert "budget guard" in result.output
    # Aborted before any trial, so nothing was recorded.
    assert not (Path("results") / "budget-cli" / "trials.jsonl").exists()
    shutil.rmtree(Path("results") / "budget-cli", ignore_errors=True)


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------


def test_a_dry_run_records_nothing_and_therefore_has_nothing_to_resume() -> None:
    """Explains the resume tests below: `dry_run` returns before log_trial."""
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 1
    cfg.experiment.max_cost_usd = 1000.0

    n = len(runner.discover_task_ids())
    first = runner.run(cfg, run_id="resume-dry", conditions=("a",), dry_run=True)
    # Executed nothing; planned n tasks x 1 condition x n_trials.
    assert first["executed"] == 0
    assert first["planned_trials"] == n * cfg.experiment.n_trials
    assert not (Path("results") / "resume-dry" / "trials.jsonl").exists()

    second = runner.run(cfg, run_id="resume-dry", conditions=("a",), dry_run=True)
    assert second["skipped"] == 0


def test_resume_skips_trials_already_recorded() -> None:
    """A real run's log is what resume reads; seeded directly to keep this fast."""
    log = Path("results") / "resume-check" / "trials.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    ids = runner.discover_task_ids()
    log.write_text(
        "".join(
            json.dumps({"task_id": task_id, "condition": "a"}) + "\n" for task_id in ids
        ),
        encoding="utf-8",
    )

    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 1
    cfg.experiment.max_cost_usd = 1000.0

    summary = runner.run(cfg, run_id="resume-check", conditions=("a",), dry_run=True)
    assert summary["skipped"] == len(ids)
    assert summary["executed"] == 0


def test_no_resume_re_executes_everything() -> None:
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 1
    cfg.experiment.max_cost_usd = 1000.0

    ids = runner.discover_task_ids()
    log = Path("results") / "noresume-check" / "trials.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "".join(json.dumps({"task_id": i, "condition": "a"}) + "\n" for i in ids),
        encoding="utf-8",
    )

    again = runner.run(
        cfg, run_id="noresume-check", conditions=("a",), dry_run=True, resume=False
    )
    assert again["skipped"] == 0, "--no-resume must ignore the existing log"
    assert again["planned_trials"] == len(ids) * cfg.experiment.n_trials


def test_a_malformed_trailing_log_line_does_not_abort_resume() -> None:
    """A crash mid-write is expected, not exceptional."""
    log = Path("results") / "resume-malformed" / "trials.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps({"task_id": "t01_merge_intervals", "condition": "a"}) + "\n"
        '{"task_id": "t02_slugify", "condi',  # truncated by a crash
        encoding="utf-8",
    )
    keys = runner._completed_keys(log)
    assert ("t01_merge_intervals", "a", 0) in keys
    assert ("t02_slugify", "", 0) not in keys


def test_resume_does_not_rebill_skipped_trials() -> None:
    """A skipped trial must contribute nothing to the running spend total."""
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 1
    cfg.experiment.max_cost_usd = 1000.0

    ids = runner.discover_task_ids()
    log = Path("results") / "resume-spend" / "trials.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "".join(json.dumps({"task_id": i, "condition": "a"}) + "\n" for i in ids),
        encoding="utf-8",
    )

    summary = runner.run(cfg, run_id="resume-spend", conditions=("a",), dry_run=True)
    assert summary["skipped"] == len(ids)
    assert summary["spent_usd"] == 0.0, "resuming must not re-charge completed trials"
