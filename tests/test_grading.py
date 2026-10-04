"""Tests for trial grading.

The central property: a trial that could not be graded must never render as a
trial that scored zero. Both cases produce `hidden_pass_rate == 0.0`, so the
`graded` flag is the only thing standing between a measurement failure and a
confidently wrong result -- it is asserted on every case here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pilot.runner import run as runner
from pilot.sandbox import docker_runner

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
T01 = TASKS_DIR / "t01_merge_intervals"


def _sandbox_ready() -> bool:
    return (
        shutil.which("docker") is not None
        and docker_runner.is_docker_available()
        and docker_runner.image_exists(docker_runner.SandboxConfig().docker_image)
    )


requires_sandbox = pytest.mark.skipif(
    not _sandbox_ready(),
    reason="sandbox not ready; run `make sandbox-image` and start Docker Desktop",
)


@pytest.fixture
def workspace(tmp_path):
    """A staged workspace exactly as the runner builds one."""
    ws = tmp_path / "tasks" / "t01__b"
    shutil.copytree(T01 / "starter", ws / "starter")
    (ws / "spec.md").write_text("# spec\n", encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# entrypoint identification
# ---------------------------------------------------------------------------


def test_entrypoint_is_the_single_starter_module():
    assert runner._entrypoint_module(T01) == "merge_intervals.py"


def test_entrypoint_is_none_when_ambiguous(tmp_path):
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "a.py").write_text("")
    (starter / "b.py").write_text("")
    assert runner._entrypoint_module(tmp_path) is None


def test_entrypoint_is_none_when_absent(tmp_path):
    (tmp_path / "starter").mkdir()
    assert runner._entrypoint_module(tmp_path) is None


def test_entrypoint_ignores_dunder_init(tmp_path):
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "__init__.py").write_text("")
    (starter / "real.py").write_text("")
    assert runner._entrypoint_module(tmp_path) == "real.py"


# ---------------------------------------------------------------------------
# ungraded cases: must be flagged, never scored as zero
# ---------------------------------------------------------------------------


def test_no_code_is_ungraded_not_a_zero_score(workspace):
    graded = runner.grade_trial(T01, workspace, "", timeout=60)
    assert graded["graded"] is False
    assert graded["hidden_pass_rate"] == 0.0
    assert "no code" in graded["grade_reason"]
    assert graded["grade_exit_class"] == "not_graded"


def test_whitespace_only_code_is_ungraded(workspace):
    graded = runner.grade_trial(T01, workspace, "   \n\t\n", timeout=60)
    assert graded["graded"] is False


def test_ambiguous_task_is_ungraded(tmp_path, workspace):
    (T01 / "starter" / "extra_module.py").exists() or None
    # Build an ambiguous task locally rather than touching the corpus.
    task = tmp_path / "ambiguous"
    shutil.copytree(T01, task)
    (task / "starter" / "second.py").write_text("x = 1\n")
    graded = runner.grade_trial(task, workspace, "x = 1\n", timeout=60)
    assert graded["graded"] is False
    assert "entrypoint" in graded["grade_reason"]


def test_ungraded_metrics_always_have_the_standard_shape():
    assert set(runner.UNGRADED_METRICS) == {
        "graded",
        "hidden_pass_rate",
        "task_solved",
        "defect_count",
        "hidden_tests_total",
        "grade_exit_class",
        "grade_errors",
    }


# ---------------------------------------------------------------------------
# real grading
# ---------------------------------------------------------------------------


@requires_sandbox
def test_reference_code_scores_a_full_pass(workspace):
    code = (T01 / "reference" / "merge_intervals.py").read_text(encoding="utf-8")
    graded = runner.grade_trial(T01, workspace, code, timeout=180)
    assert graded["graded"] is True
    assert graded["hidden_pass_rate"] == 1.0
    assert graded["task_solved"] == 1
    assert graded["defect_count"] == 0
    assert graded["hidden_tests_total"] > 0, "the hidden suite collected nothing"


@requires_sandbox
def test_stub_code_scores_a_full_fail_and_names_the_tests(workspace):
    stub = "def merge_intervals(intervals):\n    raise NotImplementedError\n"
    graded = runner.grade_trial(T01, workspace, stub, timeout=180)
    assert graded["graded"] is True
    assert graded["hidden_pass_rate"] == 0.0
    assert graded["task_solved"] == 0
    assert graded["defect_count"] == graded["hidden_tests_total"] > 0
    assert graded["failed_nodes"], "a failing grade must name the failing tests"


@requires_sandbox
def test_partially_correct_code_scores_between_zero_and_one(workspace):
    """Always-empty is right for every input, so most tests still fail."""
    code = "def merge_intervals(intervals):\n    return []\n"
    graded = runner.grade_trial(T01, workspace, code, timeout=180)
    assert graded["graded"] is True
    assert 0.0 <= graded["hidden_pass_rate"] <= 1.0
    assert graded["hidden_tests_total"] > 0


@requires_sandbox
def test_grading_never_mutates_the_task_corpus(workspace):
    before = sorted(
        (p.relative_to(T01).as_posix(), p.read_bytes()) for p in T01.rglob("*.py")
    )
    runner.grade_trial(T01, workspace, "def merge_intervals(i):\n    return []\n", timeout=180)
    after = sorted((p.relative_to(T01).as_posix(), p.read_bytes()) for p in T01.rglob("*.py"))
    assert before == after


@requires_sandbox
def test_grading_workspace_holds_hidden_tests_and_the_workspace_does_not(workspace):
    runner.grade_trial(T01, workspace, "def merge_intervals(i):\n    return []\n", timeout=180)
    grading_dir = workspace.parent / f"{workspace.name}__grading"
    assert (grading_dir / "hidden_tests").is_dir()
    assert not (workspace / "hidden_tests").exists(), (
        "the condition's workspace must never contain the graded suite"
    )


@requires_sandbox
def test_staging_workspace_omits_hidden_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    staged = runner._stage_workspace("probe", T01, "c")
    assert (staged / "spec.md").exists()
    assert (staged / "starter").is_dir()
    assert not (staged / "hidden_tests").exists()


@requires_sandbox
def test_staging_workspace_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    first = runner._stage_workspace("probe", T01, "c")
    (first / "starter" / "leftover.py").write_text("stale")
    second = runner._stage_workspace("probe", T01, "c")
    assert not (second / "starter" / "leftover.py").exists()


@requires_sandbox
def test_run_records_measured_metrics_not_hard_coded_ones(tmp_path, monkeypatch):
    """A trial record must carry a measured score, not a literal 0.0."""
    tasks = tmp_path / "tasks"
    task = tasks / "t01_alpha"
    for sub in ("starter", "reference", "visible_tests", "hidden_tests"):
        (task / sub).mkdir(parents=True)
    (task / "spec.md").write_text("# t\n", encoding="utf-8")
    (task / "meta.yaml").write_text("category: core\ndifficulty: 1\n", encoding="utf-8")
    # A real hidden suite plus a reference that solves it.
    (task / "hidden_tests" / "test_hidden.py").write_text(
        "def test_solved():\n    assert solution_ok() is True\n", encoding="utf-8"
    )
    (task / "starter" / "mod.py").write_text("def solution_ok():\n    return False\n")
    (task / "reference" / "mod.py").write_text("def solution_ok():\n    return True\n")

    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "TASKS_DIR", tasks)
    summary = runner.run(run_id="grade-probe", conditions=("b",), timeout=180)
    assert summary["executed"] == 1

    records = runner.load_trials("grade-probe")
    assert len(records) == 1
    record = records[0]
    assert "graded" in record, "a trial record must state whether it was graded"
    assert record["hidden_tests_total"] > 0


@requires_sandbox
def test_trial_record_is_valid_jsonl(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks"
    task = tasks / "t01_alpha"
    for sub in ("starter", "reference", "visible_tests", "hidden_tests"):
        (task / sub).mkdir(parents=True)
    (task / "spec.md").write_text("# t\n", encoding="utf-8")
    (task / "meta.yaml").write_text("category: core\ndifficulty: 1\n", encoding="utf-8")
    (task / "hidden_tests" / "test_hidden.py").write_text(
        "def test_solved():\n    assert solution_ok() is True\n", encoding="utf-8"
    )
    (task / "starter" / "mod.py").write_text("def solution_ok():\n    return True\n")

    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "TASKS_DIR", tasks)
    runner.run(run_id="jsonl-probe", conditions=("b",), timeout=180)

    log = tmp_path / "results" / "jsonl-probe" / "trials.jsonl"
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)


# ---------------------------------------------------------------------------
# a suite that never ran must not score zero
# ---------------------------------------------------------------------------


@requires_sandbox
def test_unimportable_code_is_ungraded_not_a_zero_score(workspace):
    """The regression this gate exists for.

    The mock model emits bare tokens, which do not import. pytest then reports
    "Interrupted: 1 error during collection"; the summary parser counts that
    error as one collected item, so a `total > 0` check alone would report a
    measured score of 0.0 for a suite that never executed a single test.
    """
    graded = runner.grade_trial(T01, workspace, "correct", timeout=180)
    assert graded["graded"] is False
    assert graded["hidden_pass_rate"] == 0.0
    assert graded["grade_exit_class"] != "passed"
    assert "did not run" in graded["grade_reason"]
    assert graded["hidden_tests_total"] == 0


@requires_sandbox
def test_ungraded_reason_names_the_exit_class(workspace):
    graded = runner.grade_trial(T01, workspace, "correct", timeout=180)
    assert graded["grade_exit_class"] in graded["grade_reason"]


def test_gradable_exit_classes_are_only_real_verdicts():
    assert runner.GRADABLE_EXIT_CLASSES == {"passed", "tests_failed"}
    for bad in ("interrupted", "usage_error", "no_tests_collected", "timeout", "launch_error"):
        assert bad not in runner.GRADABLE_EXIT_CLASSES


def test_ungraded_metrics_include_the_error_count():
    assert "grade_errors" in runner.UNGRADED_METRICS
