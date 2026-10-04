"""Prove each security task's hidden suite actually rejects its unsafe fixture.

This replaces two earlier tests that could pass without running anything:

  * `test_hidden_against_unsafe.py` ended in a bare `pass`.
  * `test_hidden_against_unsafe2.py` invoked pytest with the relative path
    `../hidden_tests/test_hidden.py` from the task directory, where no such file
    exists. pytest exited 4 ("file or directory not found"), and the assertion
    `returncode != 0` was satisfied by that usage error -- zero tests ran.

General rule enforced here, and in `_assert_real_pytest_run` below: a test that
shells out to pytest must assert the collected count, so "nothing ran" can never
be mistaken for "the implementation failed". Exit 1 (tests failed) is required
specifically -- exit 4 (usage/collection error) and exit 5 (no tests collected)
are rejected.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from pilot.sandbox import docker_runner

REPO_ROOT = Path(__file__).resolve().parent.parent
UNSAFE_DIR = REPO_ROOT / "tests" / "fixtures" / "unsafe"

# Security tasks per docs/tasks.md (items 6-10): task id -> entrypoint module.
SECURITY_TASKS = {
    "t06_user_lookup": "user_lookup",
    "t07_file_serving": "file_server",
    "t08_password_hash": "password",
    "t09_url_fetch": "url_fetch",
    "t10_signup_validation": "signup",
}


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


def _assert_real_pytest_run(res: dict) -> None:
    """Reject any run that did not actually execute tests.

    This is the check whose absence made the old tests meaningless.
    """
    assert res["collected"] > 0, (
        f"pytest collected 0 tests -- nothing was verified.\n"
        f"exit_class={res['exit_class']} exit_code={res['exit_code']}\n"
        f"stdout:\n{res['stdout']}\nstderr:\n{res['stderr']}"
    )
    assert res["exit_class"] != "no_tests_collected", "pytest collected no tests (exit 5)"
    assert res["exit_class"] != "usage_error", (
        f"pytest hit a usage/collection error (exit 4), which is not a test failure:\n"
        f"{res['stdout']}\n{res['stderr']}"
    )


def _stage(task_id: str, entrypoint: str, impl: Path, staging: Path) -> None:
    """Build a container-visible dir holding the tests plus `impl`."""
    staging.mkdir(parents=True, exist_ok=True)
    for suite in ("visible_tests", "hidden_tests"):
        for test_file in sorted((REPO_ROOT / "tasks" / task_id / suite).glob("*.py")):
            shutil.copy2(test_file, staging / test_file.name)
    # The hidden tests import the entrypoint by name, so the fixture must carry
    # that exact filename -- that is what made the old PYTHONPATH approach
    # import nothing and collection-error out.
    shutil.copy2(impl, staging / f"{entrypoint}.py")
    # The container runs as uid 1000; pytest's tmp_path dirs are 0700 on the
    # host, which would make the bind mount untraversable from inside.
    os.chmod(staging, 0o755)
    for child in staging.iterdir():
        os.chmod(child, 0o644)


@pytest.mark.parametrize("task_id", sorted(SECURITY_TASKS))
@requires_sandbox
def test_unsafe_fixture_fails_hidden_tests(task_id: str, tmp_path: Path) -> None:
    """The unsafe implementation must fail, with tests genuinely executed."""
    entrypoint = SECURITY_TASKS[task_id]
    fixture = UNSAFE_DIR / f"{task_id}.py"
    assert fixture.exists(), f"missing unsafe fixture {fixture}"

    staging = tmp_path / task_id
    _stage(task_id, entrypoint, fixture, staging)

    res = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path(".")],
        workdir=staging,
        pythonpath="/app",
        timeout=180,
    )

    _assert_real_pytest_run(res)

    # Required outcome: pytest ran the suite and tests actually failed.
    assert res["exit_code"] == 1, (
        f"{task_id}: expected exit 1 (tests failed), got {res['exit_code']} "
        f"({res['exit_class']})\n{res['stdout']}\n{res['stderr']}"
    )
    assert res["failed"] > 0, f"{task_id}: unsafe fixture passed every hidden test"

    print(
        f"\n{task_id}: {res['failed']}/{res['collected']} hidden tests reject the "
        f"unsafe fixture:\n  " + "\n  ".join(res["failed_nodes"])
    )


@pytest.mark.parametrize("task_id", sorted(SECURITY_TASKS))
@requires_sandbox
def test_reference_passes_the_same_suite(task_id: str, tmp_path: Path) -> None:
    """Control: the identical harness run against the reference must pass.

    Without this, a suite that fails for every implementation (a typo, a bad
    import) would look like a working detector.
    """
    entrypoint = SECURITY_TASKS[task_id]
    reference = next((REPO_ROOT / "tasks" / task_id / "reference").glob("*.py"))

    staging = tmp_path / f"{task_id}_ref"
    _stage(task_id, entrypoint, reference, staging)

    res = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path(".")],
        workdir=staging,
        pythonpath="/app",
        timeout=180,
    )

    _assert_real_pytest_run(res)
    assert res["exit_code"] == 0, (
        f"{task_id}: reference must pass, got exit {res['exit_code']} "
        f"({res['exit_class']})\n{res['stdout']}\n{res['stderr']}"
    )
    assert res["failed"] == 0, f"{task_id}: reference had failing tests: {res['failed_nodes']}"


def test_parse_pytest_summary_rejects_empty_output() -> None:
    """A parser that returns collected=0 for empty output is what we rely on."""
    assert docker_runner.parse_pytest_summary("")["collected"] == 0


def test_parse_pytest_summary_counts_failures_and_nodes() -> None:
    out = (
        "FAILED test_hidden.py::test_a - AssertionError\n"
        "FAILED test_hidden.py::test_b - AssertionError\n"
        "2 failed, 10 passed in 0.05s\n"
    )
    parsed = docker_runner.parse_pytest_summary(out)
    assert parsed["failed"] == 2
    assert parsed["passed"] == 10
    assert parsed["collected"] == 12
    assert parsed["failed_nodes"] == ["test_hidden.py::test_a", "test_hidden.py::test_b"]


def test_every_security_task_has_an_unsafe_fixture() -> None:
    for task_id in SECURITY_TASKS:
        assert (UNSAFE_DIR / f"{task_id}.py").exists(), f"missing fixture for {task_id}"
