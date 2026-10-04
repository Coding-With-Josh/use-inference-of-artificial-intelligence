"""Scoring tests that actually execute inside the sandbox.

These are the graded instrument, so each one asserts that a real pytest run
happened -- `collected > 0`, and an exit class consistent with the claim. A
collection error (exit 4) or an empty run (exit 5) must never be mistaken for a
result, which is exactly how two earlier tests in this repo passed while
running zero tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pilot.sandbox import docker_runner
from pilot.scoring import guardrails, lint, security
from pilot.scoring.hidden_tests import run_hidden_tests, score_against_hidden

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"


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
# hidden test scoring
# ---------------------------------------------------------------------------


@requires_sandbox
def test_reference_scores_a_full_pass_on_a_task():
    result = run_hidden_tests(TASKS_DIR / "t01_merge_intervals", "reference")
    assert result["total"] > 0, "pytest collected nothing -- nothing was graded"
    assert result["exit_class"] != "usage_error"
    assert result["exit_class"] != "no_tests_collected"
    assert result["passed"] == result["total"]
    assert result["failed"] == 0
    assert result["passed_ratio"] == 1.0
    assert result["exit_code"] == 0


@requires_sandbox
def test_starter_scores_a_full_fail_on_a_task():
    result = run_hidden_tests(TASKS_DIR / "t01_merge_intervals", "starter")
    assert result["total"] > 0, "pytest collected nothing -- the starter's failure was never seen"
    assert result["failed"] > 0
    assert result["failed_nodes"], "failing tests must be named, not just counted"
    assert result["exit_code"] == 1
    assert result["passed_ratio"] == 0.0


@requires_sandbox
def test_passed_ratio_is_consistent_with_the_counts():
    for target in ("reference", "starter"):
        result = run_hidden_tests(TASKS_DIR / "t02_slugify", target)
        assert result["passed"] + result["failed"] == result["total"]
        assert result["passed_ratio"] == pytest.approx(result["passed"] / result["total"])


@requires_sandbox
def test_score_against_hidden_exposes_documented_metric_names():
    scored = score_against_hidden(TASKS_DIR / "t01_merge_intervals", "starter")
    assert set(scored) == {"hidden_pass_rate", "task_solved", "defect_count", "total"}
    assert scored["hidden_pass_rate"] == 0.0
    assert scored["task_solved"] == 0
    assert scored["defect_count"] > 0


@requires_sandbox
def test_score_against_hidden_on_reference_is_a_solve():
    scored = score_against_hidden(TASKS_DIR / "t01_merge_intervals", "reference")
    assert scored["task_solved"] == 1
    assert scored["defect_count"] == 0
    assert scored["hidden_pass_rate"] == 1.0


@requires_sandbox
def test_security_task_hidden_suite_runs_and_rejects_the_starter():
    result = run_hidden_tests(TASKS_DIR / "t07_file_serving", "starter")
    assert result["total"] > 0
    assert result["failed"] > 0
    traversal = [n for n in result["failed_nodes"] if "traversal" in n or "absolute" in n]
    assert traversal, f"expected traversal-specific failures, got {result['failed_nodes']}"


# ---------------------------------------------------------------------------
# static analysis scoring
# ---------------------------------------------------------------------------


@requires_sandbox
def test_ruff_reports_issues_in_a_dirty_tree(tmp_path):
    (tmp_path / "dirty.py").write_text("import os\nx=1\n", encoding="utf-8")
    result = lint.run_ruff(tmp_path)
    assert result["available"] is True
    assert result["issues"] > 0
    assert result["clean"] is False


@requires_sandbox
def test_ruff_reports_clean_for_an_empty_tree(tmp_path):
    result = lint.run_ruff(tmp_path)
    assert result["available"] is True
    assert result["issues"] == 0
    assert result["clean"] is True


@requires_sandbox
def test_lint_issue_count_matches_the_dict(tmp_path):
    (tmp_path / "dirty.py").write_text("import os\n", encoding="utf-8")
    assert lint.lint_issue_count(tmp_path) == lint.run_ruff(tmp_path)["issues"]


@requires_sandbox
def test_bandit_finds_a_real_weakness(tmp_path):
    (tmp_path / "weak.py").write_text(
        "import subprocess\nsubprocess.call('ls', shell=True)\n", encoding="utf-8"
    )
    result = security.run_bandit(tmp_path)
    assert result["available"] is True
    assert result["total"] > 0
    assert any(f["test_id"] for f in result["findings"])
    assert sum(result["severities"].values()) == result["total"]


@requires_sandbox
def test_bandit_is_quiet_on_a_clean_tree(tmp_path):
    (tmp_path / "clean.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    result = security.run_bandit(tmp_path)
    assert result["available"] is True
    assert result["total"] == 0
    assert set(result["severities"]) == {"low", "medium", "high"}


@requires_sandbox
def test_security_findings_metric_shape(tmp_path):
    (tmp_path / "weak.py").write_text(
        "import subprocess\nsubprocess.call('ls', shell=True)\n", encoding="utf-8"
    )
    metric = security.security_findings(tmp_path, failed_security_tests=3)
    assert set(metric) == {"bandit", "bandit_total", "failed_security_tests"}
    assert metric["failed_security_tests"] == 3
    assert metric["bandit_total"] == sum(metric["bandit"].values())


@requires_sandbox
def test_empty_severities_helper():
    assert security.empty_severities() == {"low": 0, "medium": 0, "high": 0}


# ---------------------------------------------------------------------------
# guardrails (condition C stage 3)
# ---------------------------------------------------------------------------


@requires_sandbox
def test_guardrails_pass_on_a_correct_solution(tmp_path):
    """Copy a task's reference in as the solution; checks must come back green."""
    task = TASKS_DIR / "t01_merge_intervals"
    (tmp_path / "starter").mkdir()
    (tmp_path / "visible_tests").mkdir()
    for test in (task / "visible_tests").glob("*.py"):
        shutil.copy2(test, tmp_path / "visible_tests" / test.name)
    for src in (task / "reference").glob("*.py"):
        shutil.copy2(src, tmp_path / "starter" / src.name)

    report = guardrails.run_guardrails(tmp_path, run_static=False)
    assert report.available is True
    assert report.tests_ok is True
    assert report.passed is True
    assert report.failures == []


@requires_sandbox
def test_guardrails_fail_on_an_empty_stub(tmp_path):
    (tmp_path / "starter").mkdir()
    (tmp_path / "visible_tests").mkdir()
    for test in (TASKS_DIR / "t01_merge_intervals" / "visible_tests").glob("*.py"):
        shutil.copy2(test, tmp_path / "visible_tests" / test.name)
    (tmp_path / "starter" / "merge_intervals.py").write_text(
        "def merge_intervals(intervals):\n    raise NotImplementedError\n"
    )

    report = guardrails.run_guardrails(tmp_path, run_static=False)
    assert report.passed is False
    assert report.failures
    assert "visible tests failed" in report.failures[0]


@requires_sandbox
def test_guardrail_failures_are_formatted_for_the_repair_prompt(tmp_path):
    (tmp_path / "starter").mkdir()
    (tmp_path / "visible_tests").mkdir()
    for test in (TASKS_DIR / "t01_merge_intervals" / "visible_tests").glob("*.py"):
        shutil.copy2(test, tmp_path / "visible_tests" / test.name)
    (tmp_path / "starter" / "merge_intervals.py").write_text(
        "def merge_intervals(i):\n    return []\n"
    )

    report = guardrails.run_guardrails(tmp_path, run_static=False)
    text = report.format_failures()
    assert text.startswith("- ")
    assert "test_hidden" not in text, "guardrail output must not echo hidden test names"


@requires_sandbox
def test_guardrails_with_no_visible_tests_are_not_reported_as_passing(tmp_path):
    """Fail closed: nothing to verify must not read as success."""
    (tmp_path / "starter").mkdir()
    (tmp_path / "visible_tests").mkdir()
    (tmp_path / "starter" / "merge_intervals.py").write_text(
        "def merge_intervals(i):\n    return []\n"
    )

    report = guardrails.run_guardrails(tmp_path, run_static=False)
    assert report.passed is False
    assert report.failures


@requires_sandbox
def test_guardrails_include_static_checks(tmp_path):
    (tmp_path / "starter").mkdir()
    (tmp_path / "visible_tests").mkdir()
    (tmp_path / "starter" / "merge_intervals.py").write_text(
        "import subprocess\nsubprocess.call('ls', shell=True)\n"
    )
    report = guardrails.run_guardrails(tmp_path, run_static=True)
    # B602 (shell=True) is a LOW-severity finding, so assert on the total
    # across severities rather than assuming a high/medium hit.
    assert sum(report.bandit_findings.values()) > 0
    assert report.passed is False


def test_shell_join_quotes_arguments():
    assert guardrails.shell_join(["a b", "c"]) == "'a b' c"


# ---------------------------------------------------------------------------
# sandbox runner behaviour used by every scoring path
# ---------------------------------------------------------------------------


def test_run_in_sandbox_refuses_unknown_image(tmp_path):
    with pytest.raises(docker_runner.SandboxUnavailable) as excinfo:
        docker_runner.run_in_sandbox(["echo", "hi"], workdir=tmp_path, image="no-such-image:0")
    assert "make sandbox-image" in str(excinfo.value)


@requires_sandbox
def test_command_exit_codes_are_classified(tmp_path):
    """`classify_exit` is deliberately pytest-oriented (see its docstring).

    Exit 1 therefore means "tests failed" even for a generic command like
    `false`. Callers that need "some non-zero status" must compare exit_code.
    """
    assert docker_runner.run_in_sandbox(["true"], workdir=tmp_path)["exit_class"] == "passed"
    failed = docker_runner.run_in_sandbox(["false"], workdir=tmp_path)
    assert failed["exit_class"] == "tests_failed"
    assert failed["exit_code"] == 1


@requires_sandbox
def test_command_not_found_is_distinguished_from_failure(tmp_path):
    missing = docker_runner.run_in_sandbox(["definitely-not-a-real-binary"], workdir=tmp_path)
    assert missing["exit_class"] == "command_not_found"
    assert missing["exit_code"] == 127


@requires_sandbox
def test_empty_test_directory_collects_nothing(tmp_path):
    """The property the whole scoring layer relies on: 0 collected is detectable."""
    (tmp_path / "nothing").mkdir()
    result = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path("nothing")], workdir=tmp_path, timeout=120
    )
    assert result["collected"] == 0
    assert result["exit_class"] == "no_tests_collected"


@requires_sandbox
def test_missing_test_path_is_a_usage_error_not_a_failure(tmp_path):
    """A bad path must surface as exit 4, never as 'tests failed'."""
    result = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path("does_not_exist")], workdir=tmp_path, timeout=120
    )
    assert result["collected"] == 0
    assert result["exit_class"] == "usage_error"
    assert result["exit_code"] == 4
