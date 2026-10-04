"""Bandit security scoring, run in the sandbox.

docs/metrics.md: `security_findings` is bandit findings split by severity plus
the count of failed security-category hidden tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pilot.sandbox import docker_runner

SEVERITIES = ("low", "medium", "high")


def empty_severities() -> dict[str, int]:
    return dict.fromkeys(SEVERITIES, 0)


def run_bandit(target: Path, timeout: int = 60, image: str | None = None) -> dict[str, Any]:
    """Run bandit recursively against `target` inside the sandbox."""
    cmd = ["sh", "-c", "bandit -r -f json -q . || true"]
    try:
        result = docker_runner.run_in_sandbox(
            cmd, workdir=Path(target), timeout=timeout, image=image
        )
    except docker_runner.SandboxUnavailable as exc:
        return {
            "severities": empty_severities(),
            "total": 0,
            "available": False,
            "error": str(exc),
        }

    severities = empty_severities()
    findings: list[dict[str, Any]] = []
    try:
        parsed = json.loads(result["stdout"] or "{}")
        for finding in parsed.get("results", []):
            sev = str(finding.get("issue_severity", "")).lower()
            if sev in severities:
                severities[sev] += 1
            findings.append(
                {
                    "test_id": finding.get("test_id"),
                    "severity": sev,
                    "issue_text": finding.get("issue_text"),
                }
            )
    except json.JSONDecodeError:
        findings = []

    return {
        "severities": severities,
        "total": sum(severities.values()),
        "available": True,
        "findings": findings,
    }


def security_findings(
    target: Path, failed_security_tests: int = 0, **kwargs: Any
) -> dict[str, Any]:
    """The `security_findings` metric from docs/metrics.md."""
    bandit_result = run_bandit(target, **kwargs)
    return {
        "bandit": bandit_result["severities"],
        "bandit_total": bandit_result["total"],
        "failed_security_tests": failed_security_tests,
    }
