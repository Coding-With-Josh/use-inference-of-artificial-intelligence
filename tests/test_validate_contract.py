"""The task-corpus validation contract.

Two kinds of test here:

  * contract tests, run in-process, that pin the acceptance rules using synthetic
    TaskResults -- these always run, even with no Docker
  * one end-to-end test that runs the real corpus through the sandbox

The contract matters because the failure mode it guards against is invisible: a
validator that accepts "pytest exited 0" without checking that tests actually ran
would happily report a healthy corpus over an empty one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pilot.sandbox import docker_runner
from pilot.tasks import validate as validator

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
TASK_IDS = sorted(p.name for p in TASKS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))


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


# ---------------------------------------------------------------------------
# corpus shape (no sandbox needed)
# ---------------------------------------------------------------------------


def test_corpus_has_ten_tasks():
    assert len(TASK_IDS) == 10


def test_every_task_has_the_required_parts():
    for task_id in TASK_IDS:
        task = TASKS_DIR / task_id
        assert (task / "spec.md").exists(), f"{task_id} has no spec.md"
        assert list((task / "starter").glob("*.py")), f"{task_id} has no starter module"
        assert list((task / "reference").glob("*.py")), f"{task_id} has no reference module"
        assert list((task / "visible_tests").glob("*.py")), f"{task_id} has no visible tests"
        assert list((task / "hidden_tests").glob("*.py")), f"{task_id} has no hidden tests"


def test_every_task_has_at_least_six_hidden_tests():
    """docs/tasks.md expects meaningful hidden coverage per task."""
    for task_id in TASK_IDS:
        tests = (TASKS_DIR / task_id / "hidden_tests" / "test_hidden.py").read_text("utf-8")
        count = tests.count("\ndef test_")
        assert count >= 6, f"{task_id} has only {count} hidden tests"


def test_discovery_finds_the_whole_corpus():
    discovered = [p.name for p in validator.discover_tasks(TASKS_DIR)]
    assert discovered == TASK_IDS


def test_discovery_ignores_underscore_dirs(tmp_path):
    (tmp_path / "t01_ok").mkdir()
    (tmp_path / "_scratch").mkdir()
    assert [p.name for p in validator.discover_tasks(tmp_path)] == ["t01_ok"]


# ---------------------------------------------------------------------------
# the acceptance contract, exercised with synthetic results
# ---------------------------------------------------------------------------


def _run(**kwargs):
    """A synthetic sandbox result, in the shape run_pytest_in_sandbox returns."""
    defaults = {
        "exit_code": 0,
        "exit_class": "passed",
        "collected": 10,
        "failed": 0,
        "passed": 10,
        "failed_nodes": [],
        "stderr": "",
    }
    defaults.update(kwargs)
    return defaults


def _result(target="reference", **kwargs):
    """Evaluate a synthetic run and return the resulting TaskResult."""
    run = _run(**kwargs)
    return validator.TaskResult(
        task_id="t01",
        target=target,
        expected_pass=target == "reference",
        exit_code=run["exit_code"],
        exit_class=run["exit_class"],
        collected=run["collected"],
        failed=run["failed"],
        passed=run["passed"],
        failed_nodes=run["failed_nodes"],
        problems=validator.evaluate_run(target, run, 180),
    )


def test_a_clean_reference_run_has_no_problems():
    assert _result().ok is True


def test_a_reference_that_collected_nothing_is_rejected():
    """The exact hole that let an empty suite look healthy."""
    result = _result(collected=0, passed=0)
    assert result.ok is False
    assert "collected 0 tests" in result.problems[0]


def test_a_reference_with_failures_is_rejected():
    result = _result(exit_code=1, exit_class="tests_failed", failed=2, passed=8,
                     failed_nodes=["t.py::a", "t.py::b"])
    assert result.ok is False
    assert "must pass" in result.problems[0]


def test_a_usage_error_is_not_accepted_as_a_passing_reference():
    result = _result(exit_code=4, exit_class="usage_error", collected=0, passed=0,
                     stderr="file or directory not found")
    assert result.ok is False
    assert "exit 4" in result.problems[0]
    assert "file or directory not found" in result.problems[0]


def test_no_tests_collected_is_rejected_outright():
    result = _result(exit_code=5, exit_class="no_tests_collected", collected=0, passed=0)
    assert result.ok is False
    assert "collected no tests" in result.problems[0]


def test_a_timeout_is_rejected():
    result = _result(exit_class="timeout", exit_code=124)
    assert result.ok is False
    assert "timed out" in result.problems[0]


def test_a_sandbox_launch_error_is_not_a_corpus_problem():
    result = _result(exit_class="launch_error", exit_code=-1)
    assert result.ok is False
    assert "could not run" in result.problems[0]


def test_a_starter_that_passes_is_rejected():
    result = _result(target="starter", exit_code=0)
    assert result.ok is False
    assert "must fail" in result.problems[0]


def test_a_starter_exiting_four_is_rejected():
    """A collection error is not a failing starter."""
    result = _result(target="starter", exit_code=4, exit_class="usage_error", collected=0)
    assert result.ok is False
    assert "exit 4" in result.problems[0]


def test_a_starter_that_exits_one_with_no_failures_is_rejected():
    result = _result(target="starter", exit_code=1, exit_class="tests_failed")
    assert result.ok is False
    assert "no tests were reported failing" in result.problems[0]


def test_a_starter_exiting_some_other_code_is_rejected():
    result = _result(target="starter", exit_code=3, exit_class="internal_error")
    assert result.ok is False
    assert "expected 1" in result.problems[0]


def test_a_good_starter_run_is_accepted():
    result = _result(target="starter", exit_code=1, exit_class="tests_failed",
                     collected=10, failed=10, passed=0)
    assert result.ok is True


def test_evaluate_run_is_pure_and_needs_no_task_directory():
    """The verdict must be derivable from a result dict alone."""
    problems = validator.evaluate_run("reference", _run())
    assert problems == []


def test_timeout_message_works_without_a_timeout_value():
    problems = validator.evaluate_run("reference", _run(exit_class="timeout", exit_code=124))
    assert "timed out" in problems[0]


def test_unusable_classes_are_a_named_constant():
    assert "usage_error" not in validator.UNUSABLE_EXIT_CLASSES
    assert "launch_error" in validator.UNUSABLE_EXIT_CLASSES


def test_missing_implementation_directory_is_reported(tmp_path):
    (tmp_path / "t99_missing").mkdir()
    result = validator._run_one(tmp_path / "t99_missing", "reference", 60, None)
    assert result.ok is False
    assert "missing" in result.problems[0]
    assert result.exit_class == "missing_dir"


def test_summary_line_shows_the_verdict():
    assert "OK" in _result().summary()
    bad = _result(collected=0)
    assert "FAIL" in bad.summary()
    assert "collected=0" in bad.summary()


def test_validate_rejects_an_empty_corpus(tmp_path, capsys):
    assert validator.validate(tasks_dir=tmp_path) == 1
    assert "no tasks found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


@requires_sandbox
def test_real_corpus_validates():
    """Every reference passes; every starter fails. Nothing weaker."""
    assert validator.validate(verbose=False) == 0


@requires_sandbox
def test_validate_reports_every_run():
    results = [validator._run_one(TASKS_DIR / t, target, 180, None) for t in TASK_IDS
               for target in ("reference", "starter")]
    assert len(results) == 20
    assert all(r.ok for r in results), [r.summary() for r in results if not r.ok]
    # Each starter must name the tests it fails, or the report is uninformative.
    assert all(r.failed_nodes for r in results if r.target == "starter")
