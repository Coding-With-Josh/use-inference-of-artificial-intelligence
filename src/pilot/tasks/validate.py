"""Validate the task corpus by running every solution inside the sandbox.

Contract enforced here, for every task:

  * the reference implementation passes ALL visible and hidden tests
  * the starter implementation FAILS them (it is an empty stub)
  * a suite that collected nothing, or that pytest could not even collect, is a
    hard error -- never a pass

Nothing runs on the host. If Docker or the sandbox image is unavailable this
raises rather than falling back to local execution of untrusted code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from pilot.config.config import SandboxConfig
from pilot.sandbox import docker_runner

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / "tasks"


@dataclass
class TaskResult:
    """Outcome of running one implementation's test suite in the sandbox."""

    task_id: str
    target: str
    expected_pass: bool
    exit_code: int
    exit_class: str
    collected: int
    failed: int
    passed: int
    failed_nodes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        verdict = "OK  " if self.ok else "FAIL"
        return (
            f"{verdict} {self.task_id:<24} {self.target:<9} "
            f"exit={self.exit_code:<4} class={self.exit_class:<14} "
            f"collected={self.collected:<4} failed={self.failed}"
        )


def discover_tasks(tasks_dir: Path | None = None) -> list[Path]:
    base = tasks_dir or TASKS_DIR
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_"))


def _run_one(task_dir: Path, target: str, timeout: int, image: str | None) -> TaskResult:
    """Run `target`'s tests against both suites inside the sandbox."""
    impl_dir = task_dir / target
    expected_pass = target == "reference"

    if not impl_dir.is_dir():
        return TaskResult(
            task_id=task_dir.name,
            target=target,
            expected_pass=expected_pass,
            exit_code=-1,
            exit_class="missing_dir",
            collected=0,
            failed=0,
            passed=0,
            problems=[f"{target}/ directory is missing"],
        )

    result = docker_runner.run_pytest_in_sandbox(
        test_paths=[Path("/app/visible_tests"), Path("/app/hidden_tests")],
        workdir=task_dir,
        pythonpath=f"/app/{target}",
        timeout=timeout,
        image=image,
    )

    collected = result["collected"]
    failed = result["failed"]
    exit_code = result["exit_code"]
    exit_class = result["exit_class"]

    problems: list[str] = []

    # A run that executed nothing proves nothing. This is the check whose
    # absence previously let a collection error masquerade as a result.
    if exit_class == "no_tests_collected":
        detail = result["stderr"].strip()[:200]
        problems.append(f"pytest collected no tests (exit 5) -- {detail}")
    elif exit_class == "usage_error":
        detail = result["stderr"].strip()[:200]
        problems.append(f"pytest collection/usage error (exit 4) -- {detail}")
    elif collected == 0:
        problems.append("pytest collected 0 tests -- nothing was verified")
    elif exit_class == "timeout":
        problems.append(f"sandbox run timed out after {timeout}s")
    elif exit_class in ("launch_error", "docker_daemon_error"):
        problems.append(f"sandbox could not run the suite: {exit_class}")
    elif expected_pass:
        if exit_code != 0:
            problems.append(f"reference must pass but exited {exit_code} ({exit_class})")
        elif failed:
            problems.append(f"reference had {failed} failing test(s): {result['failed_nodes']}")
    else:
        if exit_code == 0:
            problems.append("starter passed every test -- it must fail them")
        elif exit_code != 1:
            problems.append(f"starter exited {exit_code} ({exit_class}); expected 1 (tests failed)")
        elif failed == 0:
            problems.append("starter exited 1 but no tests were reported failing")

    return TaskResult(
        task_id=task_dir.name,
        target=target,
        expected_pass=expected_pass,
        exit_code=exit_code,
        exit_class=exit_class,
        collected=collected,
        failed=failed,
        passed=result["passed"],
        failed_nodes=result["failed_nodes"],
        problems=problems,
    )


def validate(
    tasks_dir: Path | None = None,
    timeout: int | None = None,
    image: str | None = None,
    verbose: bool = False,
) -> int:
    """Validate every task. Returns 0 on success, 1 on any failure.

    Raises docker_runner.SandboxUnavailable if the sandbox is unusable, so a
    misconfigured environment is never reported as a corpus problem.
    """
    cfg = SandboxConfig()
    timeout = timeout or max(cfg.timeout_s, 120)
    tasks = discover_tasks(tasks_dir)
    if not tasks:
        print("no tasks found", file=sys.stderr)
        return 1

    results: list[TaskResult] = []
    for task_dir in tasks:
        for target in ("reference", "starter"):
            results.append(_run_one(task_dir, target, timeout, image))

    failures = [r for r in results if not r.ok]
    for result in results:
        print(result.summary())
        if verbose or not result.ok:
            for problem in result.problems:
                print(f"       - {problem}")
            if result.target == "starter" and result.failed_nodes:
                print("       starter fails: " + ", ".join(result.failed_nodes))

    total_hidden = sum(r.collected for r in results if r.target == "reference")
    print()
    print(
        f"{len(tasks)} tasks, {len(results)} sandbox runs, "
        f"{total_hidden} tests across reference suites"
    )
    if failures:
        print(f"FAILED: {len(failures)} of {len(results)} runs did not meet the contract")
        return 1
    print("OK: every reference passed; every starter failed")
    return 0


def main() -> None:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    try:
        sys.exit(validate(verbose=verbose))
    except docker_runner.SandboxUnavailable as exc:
        print(f"sandbox unavailable: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
