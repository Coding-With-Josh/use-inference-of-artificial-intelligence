"""Structural guarantee that starters contain no working implementation.

The previous version of this test grepped for the substrings "md5(", "' OR '"
and "../", which passed even though t06 and t07 starters contained complete,
working, vulnerable implementations -- neither substring occurred in them.

This version parses each starter with `ast` and requires that every function
body is exactly {docstring, raise NotImplementedError} and nothing else. A
starter cannot pass while containing executable logic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"

TASK_IDS = sorted(p.name for p in TASKS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))


def _iter_functions(tree: ast.Module):
    """Yield every FunctionDef in the module, including methods."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _function_body_statements(fn: ast.FunctionDef) -> list[ast.stmt]:
    body = list(fn.body)
    # Drop the docstring, which is permitted.
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_starter_has_at_least_one_function(task_id: str) -> None:
    starter_files = list((TASKS_DIR / task_id / "starter").glob("*.py"))
    assert starter_files, f"{task_id} has no starter implementation file"
    for path in starter_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        fns = list(_iter_functions(tree))
        assert fns, f"{path} declares no functions"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_starter_bodies_are_only_docstring_and_notimplemented(task_id: str) -> None:
    """Every starter function body must be a docstring plus NotImplementedError.

    Anything else -- a return, a call, an assignment, a pass -- is working code
    and fails here.
    """
    for path in (TASKS_DIR / task_id / "starter").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in _iter_functions(tree):
            stmts = _function_body_statements(fn)
            assert len(stmts) == 1, (
                f"{path.name}:{fn.name} body has {len(stmts)} statements; "
                "a starter must contain only a docstring and `raise NotImplementedError`"
            )
            only = stmts[0]
            assert isinstance(only, ast.Raise), (
                f"{path.name}:{fn.name} must raise NotImplementedError, got {type(only).__name__}"
            )
            exc = only.exc
            # `raise NotImplementedError` parses to ast.Name; `raise
            # NotImplementedError()` parses to ast.Call. Both are acceptable, but
            # anything else is a different exception and fails here.
            if isinstance(exc, ast.Call):
                assert isinstance(exc.func, ast.Name), f"{path.name}:{fn.name} bad raise target"
                exc_name = exc.func.id
            elif isinstance(exc, ast.Name):
                exc_name = exc.id
            else:
                detail = ast.dump(exc) if exc is not None else "None"
                raise AssertionError(
                    f"{path.name}:{fn.name} raises a non-name expression: {detail}"
                )
            assert exc_name == "NotImplementedError", (
                f"{path.name}:{fn.name} raises {exc_name}, not NotImplementedError"
            )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_starter_has_no_imports(task_id: str) -> None:
    """Imports are how a starter smuggles in a working implementation."""
    for path in (TASKS_DIR / task_id / "starter").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Import), f"{path.name} has an import: {ast.dump(node)}"
            assert not isinstance(node, ast.ImportFrom), (
                f"{path.name} has a from-import: {ast.dump(node)}"
            )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_starter_module_has_docstrings(task_id: str) -> None:
    """Functions carry a docstring so the signature is self-describing."""
    for path in (TASKS_DIR / task_id / "starter").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in _iter_functions(tree):
            assert ast.get_docstring(fn), f"{path.name}:{fn.name} is missing a docstring"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_starters_are_strictly_simpler_than_references(task_id: str) -> None:
    """A starter must never be as large as its reference solution."""
    for start_path in (TASKS_DIR / task_id / "starter").glob("*.py"):
        ref_dir = TASKS_DIR / task_id / "reference"
        refs = list(ref_dir.glob("*.py"))
        assert refs, f"{task_id} has no reference"
        start_loc = sum(1 for _ in ast.walk(ast.parse(start_path.read_text())))
        for ref_path in refs:
            ref_loc = sum(1 for _ in ast.walk(ast.parse(ref_path.read_text())))
            assert start_loc < ref_loc, (
                f"{start_path.name} has {start_loc} AST nodes, "
                f"{ref_path.name} has {ref_loc}; starter is not a stub"
            )
