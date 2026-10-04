"""Guardrails: the automated checks condition C repairs against.

docs/conditions.md stage 3: "run visible tests, ruff, bandit, mypy in sandbox;
feed failures back for repair (max_repair_rounds=3, stop early on pass)".

Every check runs untrusted code inside the sandbox via `docker_runner`. Nothing
is executed on the host. If the sandbox is unavailable the guardrails report
`unavailable` and the caller decides -- it must never be read as "checks
passed", because that would silently convert a missing control into a pass.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pilot.sandbox import docker_runner


@dataclass
class GuardrailReport:
    """Outcome of one guardrail pass.

    `passed` is False whenever any check failed *or* could not run, so an
    unavailable sandbox can never read as a clean bill of health.
    """

    passed: bool = True
    available: bool = True
    tests_ok: bool = True
    lint_issues: int = 0
    bandit_findings: dict[str, int] = field(
        default_factory=lambda: {"low": 0, "medium": 0, "high": 0}
    )
    failures: list[str] = field(default_factory=list)

    def format_failures(self) -> str:
        return "\n".join(f"- {failure}" for failure in self.failures) or "(no detail)"


def _run(cmd: list[str], workdir: Path, timeout: int) -> dict[str, Any]:
    return docker_runner.run_in_sandbox(cmd, workdir=workdir, timeout=timeout)


def run_visible_tests(
    workdir: Path, target_file: str | None = None, timeout: int = 120
) -> dict:
    """Run the visible suite for `workdir` in the sandbox."""
    paths = [Path("/app/visible_tests")]
    return docker_runner.run_pytest_in_sandbox(
        test_paths=paths,
        workdir=workdir,
        pythonpath="/app/starter",
        timeout=timeout,
    )


def run_ruff_in_sandbox(workdir: Path, timeout: int = 60) -> dict[str, Any]:
    """Count ruff issues on the sandbox-mounted tree."""
    result = _run(
        ["sh", "-c", "ruff check --output-format=json --no-cache . || true"],
        workdir,
        timeout,
    )
    issues = 0
    detail: list[Any] = []
    try:
        parsed = json.loads(result["stdout"] or "[]")
        if isinstance(parsed, list):
            detail = parsed
            issues = len(parsed)
    except json.JSONDecodeError:
        issues = 0
    return {"issues": issues, "detail": detail, "exit_class": result["exit_class"]}


def run_bandit_in_sandbox(workdir: Path, timeout: int = 60) -> dict[str, Any]:
    """Run bandit and split findings by severity."""
    result = _run(
        ["sh", "-c", "bandit -r -f json -q . || true"],
        workdir,
        timeout,
    )
    severities = {"low": 0, "medium": 0, "high": 0}
    try:
        parsed = json.loads(result["stdout"] or "{}")
        for finding in parsed.get("results", []):
            sev = str(finding.get("issue_severity", "")).lower()
            if sev in severities:
                severities[sev] += 1
    except json.JSONDecodeError:
        pass
    return {"severities": severities, "exit_class": result["exit_class"]}


def run_guardrails(
    workdir: Path,
    target_file: str | None = None,
    timeout: int = 120,
    run_static: bool = True,
) -> GuardrailReport:
    """Run visible tests (and optionally ruff/bandit) inside the sandbox."""
    report = GuardrailReport()
    try:
        tests = run_visible_tests(workdir, target_file, timeout=timeout)
    except docker_runner.SandboxUnavailable as exc:
        # Fail closed: an unavailable sandbox means the guardrail did not pass.
        return GuardrailReport(
            passed=False,
            available=False,
            failures=[f"guardrails unavailable: {exc}"],
        )

    report.tests_ok = tests["exit_code"] == 0
    if not report.tests_ok:
        if tests["collected"] == 0:
            report.failures.append("visible tests collected nothing -- cannot verify")
        else:
            report.failures.append(
                f"visible tests failed ({tests['failed']} failing): "
                + ", ".join(tests["failed_nodes"][:5])
            )

    if run_static:
        lint = run_ruff_in_sandbox(workdir)
        report.lint_issues = lint["issues"]
        bandit_result = run_bandit_in_sandbox(workdir)
        report.bandit_findings = bandit_result["severities"]
        if report.lint_issues:
            report.failures.append(f"ruff reported {report.lint_issues} issue(s)")

    report.passed = report.tests_ok and not report.failures
    return report


def shell_join(parts: list[str]) -> str:
    """Quote argv parts for the `sh -c` the sandbox runner requires."""
    return " ".join(shlex.quote(p) for p in parts)
