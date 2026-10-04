"""Tests for the study-1 runner: planning, budget, resume, analysis.

`plan()` must be pure and free of side effects; `run()` must refuse work that
exceeds the budget both before and during the run; `analyze()` must say it has no
data rather than rendering an empty table.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pilot.config.config import Config, load_config
from pilot.runner import run as runner

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tasks(tmp_path):
    """A miniature two-task corpus, so the runner tests stay fast."""
    root = tmp_path / "tasks"
    for name in ("t01_alpha", "t02_beta"):
        task = root / name
        (task / "starter").mkdir(parents=True)
        (task / "reference").mkdir()
        (task / "visible_tests").mkdir()
        (task / "hidden_tests").mkdir()
        (task / "spec.md").write_text(f"# {name}\n\nDo the thing.\n", encoding="utf-8")
        (task / "meta.yaml").write_text("category: core\ndifficulty: 2\n", encoding="utf-8")
        (task / "starter" / "mod.py").write_text("def f():\n    raise NotImplementedError\n")
    return root


# ---------------------------------------------------------------------------
# discovery and planning
# ---------------------------------------------------------------------------


def test_discovery_finds_the_real_corpus():
    ids = runner.discover_task_ids()
    assert len(ids) == 10


def test_discovery_of_a_mini_corpus(tasks):
    assert runner.discover_task_ids(tasks) == ["t01_alpha", "t02_beta"]


def test_plan_is_pure(tasks):
    """Planning must not create files, call a model, or run a sandbox."""
    before = sorted(p.name for p in tasks.iterdir())
    runner.plan(tasks_dir=tasks)
    assert sorted(p.name for p in tasks.iterdir()) == before
    assert not (REPO_ROOT / "results" / "plan-probe").exists()


def test_plan_counts_trials(tasks):
    plan = runner.plan(tasks_dir=tasks)
    assert plan["tasks"] == 2
    assert plan["conditions"] == ["a", "b", "c"]
    assert plan["trials"] == 2 * 3 * max(1, load_config().experiment.n_trials)


def test_plan_reports_a_cost_estimate_and_budget_verdict(tasks):
    plan = runner.plan(tasks_dir=tasks)
    assert plan["cost_estimate_usd"] > 0
    assert plan["within_budget"] is (plan["cost_estimate_usd"] <= plan["max_cost_usd"])
    assert plan["synthetic"] is True


# ---------------------------------------------------------------------------
# budget guard
# ---------------------------------------------------------------------------


def test_run_refuses_a_plan_over_the_cap(tasks):
    cfg = load_config()
    cfg.experiment.max_cost_usd = 0.0
    with pytest.raises(runner.BudgetExceeded) as excinfo:
        runner.run(config=cfg, run_id="budget-probe", tasks_dir=tasks, dry_run=True)
    assert "over the" in str(excinfo.value)
    assert "MAX_COST_USD" in str(excinfo.value)


def test_budget_guard_message_names_the_cap(tasks):
    cfg = load_config()
    cfg.experiment.max_cost_usd = 0.0
    with pytest.raises(runner.BudgetExceeded, match=r"\$0\.00 cap"):
        runner.run(config=cfg, run_id="budget-probe-2", tasks_dir=tasks, dry_run=True)


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------


def test_dry_run_executes_the_control_flow_without_work(tasks):
    summary = runner.run(run_id="dry-probe", tasks_dir=tasks, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["executed"] > 0
    assert summary["synthetic"] is True


def test_dry_run_calls_no_model_and_no_sandbox(tasks, monkeypatch):
    """A dry run that reached the model would be a budget bug, not a convenience."""

    def explode(*args, **kwargs):
        raise AssertionError("dry run touched the model or sandbox")

    monkeypatch.setattr(runner.MockModel, "generate", explode)
    monkeypatch.setattr(runner, "_build_condition", explode)
    runner.run(run_id="dry-probe-2", tasks_dir=tasks, dry_run=True)


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


def test_completed_keys_ignores_a_truncated_trailing_line(tmp_path):
    log = tmp_path / "trials.jsonl"
    log.write_text('{"task_id": "t01", "condition": "b"}\n{"task_id": "t02"')
    keys = runner._completed_keys(log)
    assert keys == {("t01", "b")}


def test_completed_keys_of_a_missing_log(tmp_path):
    assert runner._completed_keys(tmp_path / "nope.jsonl") == set()


def test_completed_keys_ignores_blank_lines(tmp_path):
    log = tmp_path / "trials.jsonl"
    log.write_text('\n\n{"task_id": "t01", "condition": "c"}\n\n')
    assert runner._completed_keys(log) == {("t01", "c")}


def test_resume_skips_already_recorded_trials(tasks):
    """Pre-seed the log; the runner must not re-bill those trials."""
    log_dir = REPO_ROOT / "results" / "resume-probe"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "trials.jsonl"
    log.write_text("", encoding="utf-8")

    try:
        first = runner.run(run_id="resume-probe", tasks_dir=tasks, dry_run=True, resume=False)
        assert first["skipped"] == 0

        # Now write real records for every trial the first run planned, and
        # confirm a second run treats them as complete.
        records = [
            {"task_id": task, "condition": cond}
            for task in runner.discover_task_ids(tasks)
            for cond in runner.CONDITIONS
        ]
        log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

        second = runner.run(run_id="resume-probe", tasks_dir=tasks, dry_run=True, resume=True)
        assert second["skipped"] == len(records)
        assert second["executed"] == 0

        third = runner.run(run_id="resume-probe", tasks_dir=tasks, dry_run=True, resume=False)
        assert third["skipped"] == 0
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


def test_trial_key_tuple():
    assert runner.TrialKey("t01", "b").as_tuple() == ("t01", "b")


# ---------------------------------------------------------------------------
# load and analyze
# ---------------------------------------------------------------------------


def test_load_trials_of_a_missing_run():
    assert runner.load_trials("no-such-run-id") == []


def test_load_trials_skips_malformed_lines(tmp_path, monkeypatch):
    run_id = "malformed-probe"
    log_dir = REPO_ROOT / "results" / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        (log_dir / "trials.jsonl").write_text(
            '{"task_id": "t01", "condition": "b", "hidden_pass_rate": 0.5}\nnot json\n',
            encoding="utf-8",
        )
        records = runner.load_trials(run_id)
        assert len(records) == 1
        assert records[0]["hidden_pass_rate"] == 0.5
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


def test_analyze_with_no_trials_says_so(tmp_path):
    analysis = runner.analyze(run_id="absent-run", output_dir=tmp_path, figures=False)
    assert analysis["n_trials"] == 0
    body = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## no data" in body
    assert "No trials were recorded" in body


def test_analyze_without_figures_writes_no_images(tmp_path):
    runner.analyze(run_id="absent-run-2", output_dir=tmp_path, figures=False)
    assert list(tmp_path.glob("*.png")) == []


def test_analyze_never_reports_non_synthetic(tmp_path):
    analysis = runner.analyze(run_id="absent-run-3", output_dir=tmp_path, figures=False)
    assert analysis["synthetic"] is True


def test_alignment_pairs_by_task_id():
    b = [{"task_id": "t01", "hidden_pass_rate": 0.5}, {"task_id": "t02", "hidden_pass_rate": 0.6}]
    c = [{"task_id": "t02", "hidden_pass_rate": 0.9}, {"task_id": "t01", "hidden_pass_rate": 0.8}]
    aligned = runner._aligned(b, c)
    assert aligned == {"b": [0.5, 0.6], "c": [0.8, 0.9]}


def test_alignment_with_no_shared_tasks_is_none():
    b = [{"task_id": "t01", "hidden_pass_rate": 0.5}]
    c = [{"task_id": "t99", "hidden_pass_rate": 0.9}]
    assert runner._aligned(b, c) is None


def test_alignment_of_nothing_is_none():
    assert runner._aligned([], []) is None


def test_unknown_condition_is_rejected():
    with pytest.raises(ValueError, match="unknown condition"):
        runner._build_condition("z", object(), None, None)


def test_known_conditions_build():
    for name in runner.CONDITIONS:
        assert runner._build_condition(name, object(), None, None) is not None


def test_condition_c_receives_its_ablation():
    built = runner._build_condition("c", object(), None, "context,guardrails")
    assert built.ablate == ["context", "guardrails"]


# ---------------------------------------------------------------------------
# exported surface
# ---------------------------------------------------------------------------


def test_public_names_are_exported():
    for name in ("BudgetExceeded", "analyze", "discover_task_ids", "load_trials", "plan", "run"):
        assert name in runner.__all__


def test_config_loads_defaults():
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.experiment.max_cost_usd > 0
