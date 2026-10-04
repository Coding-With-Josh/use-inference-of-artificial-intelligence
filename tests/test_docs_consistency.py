"""Tests that the documentation does not describe a repo that does not exist.

The README used to tell a reader to run `make study1` and to expect `make test`
to run lint and typecheck. Neither target nor behaviour existed. Documentation
drift is invisible in CI -- nothing breaks, the instructions are just wrong -- so
it gets a test here.

These tests assert only that names referenced in the docs exist. They do not
check that the docs are *good*.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = REPO_ROOT / "Makefile"
README = REPO_ROOT / "README.md"

# `make foo`, `make foo bar`, `uv run foo` in fenced or inline code.
MAKE_REF = re.compile(r"\bmake\s+([a-z0-9][a-z0-9-]*)")
TARGET_LINE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9_.-]*):", re.MULTILINE)


def _targets() -> set[str]:
    return set(TARGET_LINE.findall(MAKEFILE.read_text(encoding="utf-8")))


def _referenced_targets(document: Path) -> set[str]:
    return set(MAKE_REF.findall(document.read_text(encoding="utf-8")))


def test_makefile_has_the_targets_the_workflow_needs():
    targets = _targets()
    for required in ("install", "test", "lint", "typecheck", "sandbox-image"):
        assert required in targets


def test_every_make_target_the_readme_names_exists():
    missing = sorted(_referenced_targets(README) - _targets())
    assert not missing, f"README references nonexistent make targets: {missing}"


def test_readme_documents_the_sandbox_build_step():
    """`make demo-mock` needs the image; the quickstart has to say so."""
    assert "sandbox-image" in _referenced_targets(README)


def test_readme_does_not_claim_make_test_runs_lint_or_typecheck():
    """`make test` runs pytest only -- lint and typecheck are separate targets."""
    readme = README.read_text(encoding="utf-8")
    for line in readme.splitlines():
        if "`make test`" not in line:
            continue
        assert "lint" not in line.lower(), f"README overstates what `make test` does: {line!r}"
        assert "typecheck" not in line.lower(), f"README overstates `make test`: {line!r}"


def test_readme_declares_that_the_study_has_not_been_run():
    """A repo whose only numbers are synthetic must say so at the top."""
    head = "\n".join(README.read_text(encoding="utf-8").splitlines()[:12]).lower()
    assert "status:" in head
    assert "not been run" in head


def test_handoff_does_not_claim_the_study_has_results():
    handoff = (REPO_ROOT / "docs" / "handoff.md").read_text(encoding="utf-8")
    lowered = handoff.lower()
    assert "not done" in lowered or "gaps" in lowered
    # The old handoff asserted completion with a stale test count.
    assert "26 passed" not in handoff, "handoff quotes a stale test count"


@pytest.mark.parametrize("name", ["tasks.md", "metrics.md", "design.md", "threats_to_validity.md"])
def test_documented_files_exist(name):
    assert (REPO_ROOT / "docs" / name).exists(), f"docs/{name} is referenced but missing"
