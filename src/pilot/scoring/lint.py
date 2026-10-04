"""Ruff lint scoring, run in the sandbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pilot.sandbox import docker_runner


def run_ruff(target: Path, timeout: int = 60, image: str | None = None) -> dict[str, Any]:
    """Run ruff against `target` inside the sandbox.

    Returns a dict with `issues`, `clean` and `available`. `clean` is False when
    ruff could not run, so a broken sandbox never reads as a lint-clean tree.
    """
    cmd = ["sh", "-c", "ruff check --output-format=json --no-cache . || true"]
    try:
        result = docker_runner.run_in_sandbox(
            cmd, workdir=Path(target), timeout=timeout, image=image
        )
    except docker_runner.SandboxUnavailable as exc:
        return {"issues": 0, "clean": False, "available": False, "error": str(exc), "detail": []}

    detail: list[Any] = []
    issues = 0
    try:
        parsed = json.loads(result["stdout"] or "[]")
        if isinstance(parsed, list):
            detail = parsed
            issues = len(parsed)
    except json.JSONDecodeError:
        detail = []
    return {"issues": issues, "clean": issues == 0, "available": True, "detail": detail}


def lint_issue_count(target: Path, **kwargs: Any) -> int:
    """Convenience: just the issue count (docs/metrics.md `lint_issues`)."""
    return int(run_ruff(target, **kwargs)["issues"])
