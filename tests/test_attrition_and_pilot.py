"""Item 3 and item 5: attrition reporting, (task, trial) pairing, and pilot mode.

The property under test is that a missing measurement can never be read as a
result. A rate-limited trial is not a zero, a dropped pair is not a non-effect,
and a condition that lost more trials than another is a different warning from
one that lost the same share.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pilot.config.config import Config
from pilot.models.http import ProviderError
from pilot.runner import run as runner

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def trial(
    task_id: str,
    condition: str,
    index: int = 0,
    *,
    graded: bool = True,
    rate: float = 0.5,
    reason: str | None = None,
    code: str | None = None,
    synthetic: bool = True,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "task_id": task_id,
        "condition": condition,
        "trial_index": index,
        "graded": graded,
        "hidden_pass_rate": rate,
        "defect_count": 2,
        "task_solved": 0,
        "iterations": 1,
        "synthetic": synthetic,
    }
    if graded:
        record["grade_exit_class"] = "tests_failed"
    else:
        record["grade_exit_class"] = "not_graded"
        record["ungraded_reason"] = reason or "HTTP 429: rate limited"
        record["ungraded_reason_code"] = code or "rate_limited"
        record["hidden_pass_rate"] = 0.0
    return record


def write_log(run_id: str, records: list[dict[str, Any]]) -> None:
    path = Path("results") / run_id / "trials.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")



def make_task(root: Path, name: str) -> Path:
    """A minimal but structurally real task directory."""
    task = root / name
    (task / "starter").mkdir(parents=True)
    (task / "starter" / "__init__.py").write_text("")
    (task / "spec.md").write_text("do a thing\n")
    (task / "meta.yaml").write_text(f"id: {name}\n")
    return task


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    make_task(tasks, "t01_x")
    make_task(tasks, "t02_y")
    return tasks

@pytest.fixture
def clean_run(request: pytest.FixtureRequest) -> Any:
    run_id = request.node.name
    yield run_id
    shutil.rmtree(Path("results") / run_id, ignore_errors=True)


# --------------------------------------------------------------------------
# attrition accounting
# --------------------------------------------------------------------------


def test_n_graded_and_n_ungraded_are_reported_per_condition(clean_run: str) -> None:
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5),
        trial("t01", "b", 1, rate=0.6),
        trial("t01", "b", 2, graded=False),
        trial("t01", "c", 0, rate=0.8),
        trial("t01", "c", 1, graded=False),
        trial("t01", "c", 2, rate=0.9),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    by = a["attrition"]["by_condition"]
    assert by["b"] == {"n_total": 3, "n_graded": 2, "n_ungraded": 1, "reasons": {"rate_limited": 1}}
    assert by["c"] == {"n_total": 3, "n_graded": 2, "n_ungraded": 1, "reasons": {"rate_limited": 1}}


def test_attrition_is_reported_per_task_too(clean_run: str) -> None:
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5),
        trial("t02", "b", 0, graded=False),
        trial("t02", "c", 0, rate=0.7),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    by_task = a["attrition"]["by_task"]
    assert by_task["t01"] == {"n_total": 1, "n_graded": 1, "n_ungraded": 0, "reasons": {}}
    # t02 lost its b trial but its c trial graded, so it counts one of each.
    assert by_task["t02"] == {
        "n_total": 2, "n_graded": 1, "n_ungraded": 1,
        "reasons": {"rate_limited": 1},
    }


def test_every_ungraded_reason_is_kept_separate(clean_run: str) -> None:
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5),
        trial("t02", "b", 0, graded=False, reason="suite never ran",
              code="not_graded", ),
        trial("t03", "b", 0, graded=False, reason="429", code="rate_limited"),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    reasons = a["attrition"]["by_condition"]["b"]["reasons"]
    assert reasons == {"not_graded": 1, "rate_limited": 1}
    assert len(a["ungraded_reasons"]) == 2


def test_attrition_imbalance_above_five_points_is_flagged(clean_run: str) -> None:
    """C loses every trial it had, B loses none: 100 points apart."""
    records = [trial("t01", "b", 0, rate=0.5), trial("t02", "b", 0, rate=0.6)]
    records += [trial(f"t0{i}", "c", 0, graded=False) for i in range(1, 5)]
    write_log(clean_run, records)
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["attrition"]["imbalanced"] is True
    assert a["attrition"]["imbalance_points"] == 100.0
    assert a["attrition"]["worst_condition"] == "c"


def test_equal_attrition_is_not_flagged(clean_run: str) -> None:
    """25% in both conditions is noise, not a confound. It must stay quiet."""
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5),
        trial("t02", "b", 0, graded=False),
        trial("t01", "c", 0, rate=0.7),
        trial("t02", "c", 0, graded=False),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["attrition"]["imbalanced"] is False
    assert a["attrition"]["imbalance_points"] == 0.0


def test_exactly_at_the_threshold_is_not_flagged(clean_run: str) -> None:
    """b loses 1 of 20 (5.0 points), c loses none: exactly at, not above."""
    records = [trial(f"t{i:02d}", "b", 0, rate=0.5) for i in range(19)]
    records.append(trial("t99", "b", 0, graded=False))
    records += [trial(f"u{i:02d}", "c", 0, rate=0.7) for i in range(20)]
    write_log(clean_run, records)
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["attrition"]["imbalance_points"] == 5.0
    assert a["attrition"]["imbalanced"] is False, "the threshold is strictly greater-than"


def test_just_above_the_threshold_is_flagged(clean_run: str) -> None:
    """b loses 2 of 20 (10 points) against c's 0: 5 points over the line."""
    records = [trial(f"t{i:02d}", "b", 0, rate=0.5) for i in range(18)]
    records += [trial("t98", "b", 0, graded=False), trial("t99", "b", 0, graded=False)]
    records += [trial(f"u{i:02d}", "c", 0, rate=0.7) for i in range(20)]
    write_log(clean_run, records)
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["attrition"]["imbalance_points"] == 10.0
    assert a["attrition"]["imbalanced"] is True


def test_attrition_imbalance_is_measured_in_points_not_raw_counts(clean_run: str) -> None:
    """Raw counts would flag a large balanced run. Rates must not."""
    records: list[dict[str, Any]] = []
    for i in range(60):
        records.append(trial(f"b{i:03d}", "b", 0, rate=0.5))
        records.append(trial(f"c{i:03d}", "c", 0, graded=False))
    write_log(clean_run, records)
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["attrition"]["by_condition"]["b"]["n_ungraded"] == 0
    assert a["attrition"]["by_condition"]["c"]["n_ungraded"] == 60
    assert a["attrition"]["imbalanced"] is True, "100% attrition in one condition is real"


def test_the_imbalance_warning_appears_above_the_results_table(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    records = [trial("t01", "b", 0, rate=0.5)]
    records += [trial(f"t0{i}", "c", 0, graded=False) for i in range(1, 5)]
    write_log(clean_run, records)
    text = render_report(runner.analyze(run_id=clean_run, figures=False))
    warning_at = text.index("differential attrition")
    table_at = text.index("## outcome by condition")
    assert warning_at < table_at, "the warning must come before the numbers it qualifies"


def test_no_warning_when_attrition_is_balanced(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5), trial("t02", "b", 0, graded=False),
        trial("t01", "c", 0, rate=0.7), trial("t02", "c", 0, graded=False),
    ])
    assert "differential attrition" not in render_report(
        runner.analyze(run_id=clean_run, figures=False)
    )


# --------------------------------------------------------------------------
# pairing on (task_id, trial_index)
# --------------------------------------------------------------------------


def test_pairs_use_task_and_trial_index_not_task_alone(clean_run: str) -> None:
    """Replicates must each form their own pair, not collapse to one per task."""
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.2), trial("t01", "b", 1, rate=0.4),
        trial("t01", "b", 2, rate=0.6),
        trial("t01", "c", 0, rate=0.5), trial("t01", "c", 1, rate=0.7),
        trial("t01", "c", 2, rate=0.9),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    pairing = a["contrasts"]["c_minus_b_hidden_pass_rate"]["pairing"]
    assert pairing["n_pairs"] == 3
    assert pairing["key"] == "(task_id, trial_index)"
    assert pairing["n_dropped"] == 0


def test_a_cell_graded_in_only_one_condition_is_dropped_and_counted(clean_run: str) -> None:
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.2), trial("t01", "b", 1, rate=0.4),
        trial("t01", "b", 2, graded=False),
        trial("t01", "c", 0, rate=0.5), trial("t01", "c", 1, rate=0.7),
        trial("t01", "c", 2, rate=0.9),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    pairing = a["contrasts"]["c_minus_b_hidden_pass_rate"]["pairing"]
    assert pairing["n_pairs"] == 2
    # The cell exists in both conditions but b's copy is ungraded, so it is
    # "ungraded in b", not "missing from b". Conflating them would misattribute
    # attrition to a non-existent trial.
    assert pairing["n_b_ungraded"] == 1
    assert pairing["n_c_ungraded"] == 0
    assert pairing["n_b_missing"] == 0
    assert pairing["n_dropped"] == 1
    assert pairing["dropped_b_ungraded"] == [["t01", 2]]


def test_the_headline_contrast_uses_only_complete_pairs(clean_run: str) -> None:
    """The statistics must be computed on the surviving pairs, not all of b."""
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.0),
        trial("t02", "b", 0, rate=0.0),
        trial("t01", "c", 0, rate=1.0),
        trial("t02", "c", 0, graded=False),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    result = a["contrasts"]["c_minus_b_hidden_pass_rate"]
    assert result["pairing"]["n_pairs"] == 1
    assert result["paired_t"]["n"] == 1
    # The unpaired b cell (0.0) must not drag the difference toward zero.
    assert result["effect"]["mean_diff"] == 1.0


def test_the_report_states_how_many_pairs_were_dropped(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.2), trial("t02", "b", 0, rate=0.3),
        trial("t01", "c", 0, rate=0.5),
    ])
    text = render_report(runner.analyze(run_id=clean_run, figures=False))
    assert "1 pair(s) dropped" in text
    assert "graded in both conditions" in text
    # t02 ran in b but never in c, so it is the b side that lacks a partner.
    assert "1 missing from the first condition" in text


def test_a_retried_trial_is_counted_once_not_twice(clean_run: str) -> None:
    """The ungraded attempt and its successful retry are one trial."""
    write_log(clean_run, [
        trial("t01", "b", 0, graded=False),
        trial("t01", "b", 0, rate=0.8),
        trial("t01", "c", 0, rate=0.9),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["n_trials"] == 2, "two cells, not three log lines"
    assert a["n_graded"] == 2
    assert a["n_ungraded"] == 0
    assert a["contrasts"]["c_minus_b_hidden_pass_rate"]["pairing"]["n_pairs"] == 1


def test_the_later_attempt_wins_not_the_earlier_failure(clean_run: str) -> None:
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.1),
        trial("t01", "b", 0, graded=False),
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["n_ungraded"] == 1
    assert a["attrition"]["by_condition"]["b"]["n_graded"] == 0


# --------------------------------------------------------------------------
# resume retries transient failures first
# --------------------------------------------------------------------------


def test_resume_retries_rate_limited_trials_before_new_ones(corpus: Path) -> None:
    run_id = "retry-order"
    try:
        write_log(run_id, [
            {"task_id": "t01_x", "condition": "b", "trial_index": 0, "graded": False,
             "ungraded_reason_code": "rate_limited"},
            {"task_id": "t02_y", "condition": "b", "trial_index": 0, "graded": True,
             "hidden_pass_rate": 0.5},
        ])
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        summary = runner.run(cfg, run_id=run_id, conditions=("b",), tasks_dir=corpus)
        assert summary["retried_first"] == 1
        assert summary["planned_order"][0] == "b/t01_x", (
            "the missing measurement must be recovered before new ones are collected"
        )
        assert "b/t02_y" not in summary["planned_order"], "graded trials must not re-run"
    finally:
        shutil.rmtree(Path("results") / run_id, ignore_errors=True)


def test_a_graded_trial_is_not_retried_on_resume(corpus: Path) -> None:
    run_id = "resume-graded"
    try:
        write_log(run_id, [
            {"task_id": "t01_x", "condition": "b", "trial_index": 0, "graded": True,
             "hidden_pass_rate": 0.5},
        ])
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        summary = runner.run(cfg, run_id=run_id, conditions=("b",), tasks_dir=corpus)
        assert summary["skipped"] == 1
        assert "b/t01_x" not in summary["planned_order"], "a graded trial must not re-run"
        assert summary["planned_order"] == ["b/t02_y"], "only the untouched task remains"
    finally:
        shutil.rmtree(Path("results") / run_id, ignore_errors=True)


def test_an_ungraded_trial_is_retried_on_resume(corpus: Path) -> None:
    run_id = "resume-ungraded"
    try:
        write_log(run_id, [
            {"task_id": "t01_x", "condition": "b", "trial_index": 0, "graded": False,
             "ungraded_reason_code": "rate_limited"},
        ])
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        summary = runner.run(cfg, run_id=run_id, conditions=("b",), tasks_dir=corpus)
        assert summary["skipped"] == 0, "an ungraded trial is not done"
        assert "b/t01_x" in summary["planned_order"], "the missing measurement is re-queued"
    finally:
        shutil.rmtree(Path("results") / run_id, ignore_errors=True)


def test_a_permanent_failure_is_not_retried_first(corpus: Path) -> None:
    """A 401 will fail again. Retrying it first just wastes the budget."""
    run_id = "retry-permanent"
    try:
        write_log(run_id, [
            {"task_id": "t01_x", "condition": "b", "trial_index": 0, "graded": False,
             "ungraded_reason_code": "http_error"},
        ])
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        summary = runner.run(cfg, run_id=run_id, conditions=("b",), tasks_dir=corpus)
        assert summary["retried_first"] == 0
    finally:
        shutil.rmtree(Path("results") / run_id, ignore_errors=True)


# --------------------------------------------------------------------------
# provenance reaches the report
# --------------------------------------------------------------------------


def test_a_model_id_mismatch_is_surfaced_in_the_report(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    records = [trial("t01", "b", 0, rate=0.5), trial("t01", "c", 0, rate=0.7)]
    for record in records:
        record["provenance"] = {
            "provider": "groq",
            "base_url_host": "api.groq.com",
            "requested_model_id": "llama-3.3-70b-versatile",
            "returned_model_id": "llama-3.1-8b-instant",
            "allow_custom_base_url": False,
            "retries": 0,
        }
    write_log(clean_run, records)
    text = render_report(runner.analyze(run_id=clean_run, figures=False))
    assert "different model than was requested" in text
    assert "llama-3.1-8b-instant" in text


def test_the_host_is_printed_in_provenance(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    records = [trial("t01", "b", 0, rate=0.5), trial("t01", "c", 0, rate=0.7)]
    for record in records:
        record["provenance"] = {
            "provider": "anthropic",
            "base_url_host": "api.anthropic.com",
            "requested_model_id": "claude-sonnet-4-5",
            "returned_model_id": "claude-sonnet-4-5-20250929",
            "allow_custom_base_url": False,
            "retries": 0,
        }
    write_log(clean_run, records)
    text = render_report(runner.analyze(run_id=clean_run, figures=False))
    assert "api.anthropic.com" in text
    assert "claude-sonnet-4-5-20250929" in text


def test_a_custom_base_url_run_says_so_in_the_report(clean_run: str) -> None:
    from pilot.analysis.report import render_report

    records = [trial("t01", "b", 0, rate=0.5), trial("t01", "c", 0, rate=0.7)]
    for record in records:
        record["provenance"] = {
            "provider": "anthropic",
            "base_url_host": "gateway.internal.example",
            "requested_model_id": "claude-sonnet-4-5",
            "returned_model_id": "claude-sonnet-4-5",
            "allow_custom_base_url": True,
            "retries": 2,
        }
    write_log(clean_run, records)
    text = render_report(runner.analyze(run_id=clean_run, figures=False))
    assert "non-official base URL was in effect" in text
    assert "gateway.internal.example" in text


def test_synthetic_provenance_is_derived_not_asserted(clean_run: str) -> None:
    """A single real-provider trial means the run is not synthetic."""
    write_log(clean_run, [
        trial("t01", "b", 0, rate=0.5, synthetic=False),
        trial("t01", "c", 0, rate=0.7, synthetic=True),
    ])
    assert runner.analyze(run_id=clean_run, figures=False)["synthetic"] is False


def test_a_log_with_no_synthetic_field_is_not_called_synthetic(clean_run: str) -> None:
    write_log(clean_run, [
        {"task_id": "t01", "condition": "b", "trial_index": 0, "graded": True,
         "hidden_pass_rate": 0.5, "defect_count": 1},
    ])
    a = runner.analyze(run_id=clean_run, figures=False)
    assert a["synthetic"] is False, "unknown provenance must not be stamped synthetic"


# --------------------------------------------------------------------------
# Item 5: pilot mode
# --------------------------------------------------------------------------


def test_task_filter_accepts_full_ids_and_prefixes() -> None:
    parsed = runner.parse_task_filter("t01_merge_intervals,t07")
    assert parsed == ("t01_merge_intervals", "t07_file_serving")


def test_task_filter_rejects_an_unknown_id() -> None:
    with pytest.raises(ValueError) as excinfo:
        runner.parse_task_filter("t99")
    assert "unknown task id" in str(excinfo.value)


def test_task_filter_rejects_an_ambiguous_prefix() -> None:
    with pytest.raises(ValueError) as excinfo:
        runner.parse_task_filter("t0")
    assert "ambiguous" in str(excinfo.value)


def test_task_filter_deduplicates() -> None:
    assert runner.parse_task_filter("t01,t01_merge_intervals") == ("t01_merge_intervals",)


def test_empty_task_filter_means_all() -> None:
    assert runner.parse_task_filter("") == ()
    assert runner.parse_task_filter(None) == ()


def test_conditions_are_validated_and_normalised() -> None:
    assert runner.parse_conditions("c,b") == ("b", "c"), "design order, not typed order"
    assert runner.parse_conditions("") == ()


def test_an_unknown_condition_is_rejected() -> None:
    with pytest.raises(ValueError) as excinfo:
        runner.parse_conditions("b,z")
    assert "unknown condition" in str(excinfo.value)


def test_the_plan_counts_replicates() -> None:
    cfg = Config()
    cfg.experiment.n_trials = 3
    planned = runner.plan(cfg, conditions=("b", "c"), task_filter=("t01_merge_intervals",))
    assert planned["trials"] == 6
    assert planned["tasks"] == 1
    assert planned["trials_per_task"] == 3


def test_the_dry_run_lists_the_exact_trials_it_would_run() -> None:
    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 2
    summary = runner.run(
        cfg, run_id="dry", conditions=("b",),
        task_filter=("t01_merge_intervals",), dry_run=True,
    )
    assert summary["dry_run"] is True
    assert summary["planned_order"] == ["b/t01_merge_intervals", "b/t01_merge_intervals#1"]
    assert summary["planned_trials"] == 2


def test_the_dry_run_writes_nothing() -> None:
    try:
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        runner.run(cfg, run_id="dry-nowrite", conditions=("b",), dry_run=True)
        assert not (Path("results") / "dry-nowrite").exists(), "a dry run must not create files"
    finally:
        shutil.rmtree(Path("results") / "dry-nowrite", ignore_errors=True)


def test_the_dry_run_needs_no_api_key() -> None:
    """Pilot mode must be previewable on a machine with no key at all."""
    import os

    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        cfg = Config()
        cfg.model.provider = "groq"
        cfg.experiment.n_trials = 1
        # task_filter is deliberately empty: the point is that no key is needed to
        # compute a plan, not which tasks it names.
        summary = runner.run(cfg, run_id="dry-nokey", conditions=("b",), dry_run=True)
        assert summary["dry_run"] is True
        assert summary["provider"] == "groq"
    finally:
        shutil.rmtree(Path("results") / "dry-nokey", ignore_errors=True)
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


def test_cli_dry_run_prints_what_it_would_do(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "mock")
    monkeypatch.setenv("N_TRIALS", "3")
    result = CliRunner().invoke(app, [
        "study1-run", "--run-id", "cli-dry",
        "--tasks", "t01,t07", "--trials", "3", "--conditions", "b,c", "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "DRY RUN: run_id=cli-dry would execute 12 trial(s)" in result.output
    assert "b/t01_merge_intervals#1" in result.output
    assert "no model called" in result.output


def test_cli_rejects_an_unknown_task_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "mock")
    result = CliRunner().invoke(app, ["study1-run", "--tasks", "t99"])
    assert result.exit_code == 4
    assert "unknown task id" in result.output


def test_cli_rejects_an_unknown_condition_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "mock")
    result = CliRunner().invoke(app, ["study1-run", "--conditions", "z"])
    assert result.exit_code == 4
    assert "unknown condition" in result.output


def test_cli_refuses_a_non_official_base_url_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://agentrouter.org/")
    result = CliRunner().invoke(app, ["study1-run", "--dry-run"])
    assert result.exit_code == 4
    assert "--allow-custom-base-url" in result.output
    assert "agentrouter.org" in result.output


def test_cli_accepts_a_non_official_base_url_with_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://agentrouter.org/")
    result = CliRunner().invoke(app, ["study1-run", "--dry-run", "--allow-custom-base-url"])
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output


def test_a_rate_limited_run_continues_and_counts_ungraded(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One trial failing must not destroy the rest of the matrix."""
    from pilot.conditions import cond_b

    run_id = "rl-continue"
    calls = {"n": 0}
    real_run = cond_b.ConditionB.run

    def flaky(self: Any, ctx: Any) -> Any:
        calls["n"] += 1
        # Only the first trial is rate limited. If the run aborted on it, `calls`
        # would stay at 1 and the second trial would never happen.
        if calls["n"] == 1:
            raise ProviderError("HTTP 429: rate limited", status=429)
        return real_run(self, ctx)

    monkeypatch.setattr(cond_b.ConditionB, "run", flaky)
    try:
        cfg = Config()
        cfg.model.provider = "mock"
        cfg.experiment.n_trials = 1
        summary = runner.run(cfg, run_id=run_id, conditions=("b",), tasks_dir=corpus)
        assert calls["n"] == 2, "the run must continue past a rate-limited trial"
        records = [
            json.loads(line)
            for line in (Path("results") / run_id / "trials.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(records) == 2, "the second trial must still be recorded"
        assert records[0]["ungraded_reason_code"] == "rate_limited"
        assert records[0]["retryable"] is True
        # The later trial must not inherit the earlier failure. (Its own grade is
        # absent rather than True because this fixture corpus has no hidden suite,
        # so grading cannot run here; what matters is that its reason differs.)
        assert records[1].get("ungraded_reason_code") != "rate_limited"
        assert summary["executed"] == 1, "the surviving trial counts as executed"
    finally:
        monkeypatch.setattr(cond_b.ConditionB, "run", real_run)
        shutil.rmtree(Path("results") / run_id, ignore_errors=True)
