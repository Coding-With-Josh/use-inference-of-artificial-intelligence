"""Run a task's hidden suite in the sandbox and report pass/fail counts.

Hidden tests are the graded instrument. They only ever execute inside the
sandbox; the harness never runs them on the host.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pilot.sandbox import docker_runner


def run_hidden_tests(
    task_dir: Path,
    implementation: str = "reference",
    timeout: int | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Run the hidden suite for `task_dir` against `implementation`.

    Args:
        task_dir: the task directory (mounted read-only into the sandbox).
        implementation: subdirectory of the task holding the code under test,
            e.g. "reference" or "starter".

    Returns:
        A dict with `passed`, `total` (collected), `failed`, `passed_ratio`,
        `failed_nodes` and `exit_class`. `total` is 0 when pytest collected
        nothing, which callers must treat as "not graded", not as a pass.
    """
    task_dir = Path(task_dir)
    result = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path("/app/hidden_tests")],
        workdir=task_dir,
        pythonpath=f"/app/{implementation}",
        timeout=timeout,
        image=image,
    )
    total = result["collected"]
    failed = result["failed"]
    passed = result["passed"]
    return {
        "passed": passed,
        "total": total,
        "failed": failed,
        # Collection/fixture errors are counted separately from tests: pytest
        # reports "Interrupted: 1 error during collection", and the summary
        # parser records that as one item. A caller that gates only on `total`
        # would score a suite that never ran.
        "errors": result["errors"],
        "passed_ratio": (passed / total) if total else 0.0,
        "failed_nodes": result["failed_nodes"],
        "exit_code": result["exit_code"],
        "exit_class": result["exit_class"],
        "implementation": implementation,
    }


def score_against_hidden(task_dir: Path, implementation: str = "reference") -> dict[str, Any]:
    """Convenience wrapper exposing exactly the metrics in docs/metrics.md."""
    from pilot.scoring import metrics

    result = run_hidden_tests(task_dir, implementation=implementation)
    outcomes = [True] * result["passed"] + [False] * result["failed"]
    return {
        "hidden_pass_rate": metrics.hidden_pass_rate(outcomes),
        "task_solved": metrics.task_solved(outcomes) if outcomes else 0,
        "defect_count": metrics.defect_count(outcomes),
        "total": result["total"],
    }
