"""Prompt assembly, and the guarantee that hidden tests never reach a prompt.

This is the permanent leak test required by the audit. It replaces two earlier
tests that could not fail:

  * `test_hidden_leak_in_prompts.py` globbed `rglob("prompt*")`, which matched
    **zero** files in the repo, so it asserted nothing.
  * `test_no_hidden_leak.py` only checked whether one hidden test file appeared
    *verbatim* inside another file -- an assertion no realistic leak satisfies.

What is asserted here instead:
  * the template set and the generated prompt set are both non-empty
  * no hidden-test function name appears in any spec, starter, visible test,
    template, or generated prompt
  * no distinctive hidden-test string literal appears in any of those either
  * the structural guard in prompts.py refuses to read hidden_tests at all
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pilot.conditions.cond_b import ConditionB
from pilot.conditions.cond_c import ConditionC
from pilot.models.mock import MockModel
from pilot.prompts import (
    ALLOWED_SOURCES,
    HiddenTestLeak,
    _read_allowed,
    build_condition_a_prompt,
    build_condition_b_prompt,
    build_condition_c_context_prompt,
    build_decomposition_prompt,
    build_repair_prompt,
    build_scoped_authority_notice,
    build_step_prompt,
    iter_templates,
    load_task_context,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
TASK_IDS = sorted(p.name for p in TASKS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))

# Test-scaffolding strings that are not "distinctive" and would make the
# literal scan meaningless if treated as leaks.
GENERIC_LITERALS = {
    "utf-8",
    "tmp_path",
    "/app",
    "/etc/passwd",
    "secret",
    "alice",
    "bob",
    "password123",
    "alice@example.com",
    "correct horse battery staple",
    "localhost",
    "evil.com",
    "example.com",
    "api.example.com",
    "http://localhost:8080/data",
    "http://127.0.0.1/data",
    "http://10.0.0.5/data",
    "http://192.168.1.1/data",
    "http://172.16.0.1/data",
    "https://example.com/data",
    "https://api.example.com/v1",
    "https://evil.com/data",
    "https://example.com.evil.com/data",
    "https:///data",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "say \"hi\"",
    "line1\nline2",
    "1,2",
    "1",
    "2",
    "3",
    "4",
    "a,b",
    "a\n",
    "a,b\n",
    'a\n"1,2","3"',
    'a,b\n"1,2","3"',
    "a\n1\n2\n3",
    "a,b\n1\n",
    'a\n"say ""hi"""',
    "name\ncafé",
    "a,b\n1,2\n\n3,4",
    "a,b\n1,2,3,4",
    "h",
    "port",
    "host",
    "80",
    "{not json",
    "0",
    "65535",
    "70000",
    "-1",
    "1234",
    "a" * 250 + "@example.com",
    "x" * 200,
    "u" * 100,
    "",
}


def _hidden_test_names(task_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in (task_dir / "hidden_tests").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test_"):
                    names.add(node.name)
    return names


def _visible_tests_text(task_id: Path) -> str:
    """The published example tests -- the only genuinely public source.

    This deliberately does *not* include spec.md or the starter. If it did, the
    leak assertions below would be circular: pasting a hidden assertion into the
    spec would redefine it as "public" and the check could never fire. The spec
    and starter are assertion *targets*, not the reference set.
    """
    chunks = []
    for path in (TASKS_DIR / task_id / "visible_tests").glob("*.py"):
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _hidden_test_literals(task_id: Path) -> set[str]:
    """Distinctive string literals that exist *only* in the hidden suite.

    A literal already shown in a visible test is a public example by
    construction, so its presence in a prompt is not a leak. What remains are the
    graded assertions -- if one of those reaches a spec, a starter, a template
    or a generated prompt, the model has been handed its own grading key.
    """
    literals: set[str] = set()
    for path in (TASKS_DIR / task_id / "hidden_tests").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if len(value) >= 12 and value not in GENERIC_LITERALS:
                    literals.add(value)

    visible = _visible_tests_text(task_id)
    return {lit for lit in literals if lit not in visible}


def _corpus_texts() -> dict[str, str]:
    """specs, starters and visible tests -- everything a prompt may draw on."""
    texts: dict[str, str] = {}
    for task_id in TASK_IDS:
        task_dir = TASKS_DIR / task_id
        spec = task_dir / "spec.md"
        if spec.exists():
            texts[f"{task_id}/spec.md"] = spec.read_text(encoding="utf-8")
        for sub in ("starter", "visible_tests"):
            for path in (task_dir / sub).glob("*.py"):
                texts[f"{task_id}/{sub}/{path.name}"] = path.read_text(encoding="utf-8")
    return texts


def _generated_prompts() -> list[str]:
    """Every prompt produced by a full mock run across all tasks.

    Collected by actually running the conditions, so a new prompt-building code
    path cannot slip past the scan by not being referenced here.
    """
    model = MockModel(seed=42)
    prompts: list[str] = []
    for task_id in TASK_IDS:
        ctx = load_task_context(TASKS_DIR / task_id)
        prompts.append(build_condition_a_prompt(ctx))
        prompts.append(build_condition_b_prompt(ctx))
        prompts.append(build_condition_c_context_prompt(ctx))
        prompts.append(build_decomposition_prompt(ctx))
        prompts.append(build_step_prompt("do a thing", 1, 3))
        prompts.append(build_repair_prompt("visible tests failed"))
        prompts.append(build_scoped_authority_notice(ctx.allowed_files))

        b_result = ConditionB(model).run(ctx)
        prompts.extend(b_result.prompts)

        c_result = ConditionC(model, workdir=None).run(ctx)
        prompts.extend(c_result.prompts)
    return prompts


# ---------------------------------------------------------------------------
# Non-vacuity: the scans below must actually have something to scan.
# ---------------------------------------------------------------------------


def test_template_set_is_non_empty() -> None:
    templates = iter_templates()
    assert len(templates) > 0, "no prompt templates found -- the leak scan would prove nothing"
    assert all(text.strip() for text in templates.values())


def test_corpus_text_set_is_non_empty() -> None:
    texts = _corpus_texts()
    assert len(texts) > 0
    assert len(TASK_IDS) > 0


def test_generated_prompt_set_is_non_empty() -> None:
    prompts = _generated_prompts()
    assert len(prompts) > 0, "no prompts generated -- the leak scan would prove nothing"
    assert any(p.strip() for p in prompts)


def test_every_task_has_hidden_test_names() -> None:
    for task_id in TASK_IDS:
        assert _hidden_test_names(TASKS_DIR / task_id), f"{task_id} yielded no hidden test names"


def test_exclusive_hidden_literals_exist() -> None:
    """Non-vacuity: there must be strings that exist *only* in hidden tests.

    Without this, a bug that emptied `_hidden_test_literals` would turn every
    leak assertion below into a no-op that passes for the wrong reason.
    """
    total = sum(len(_hidden_test_literals(task_id)) for task_id in TASK_IDS)
    assert total > 0, "no hidden-test-exclusive strings found; the scan would prove nothing"


# ---------------------------------------------------------------------------
# The leak assertions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_hidden_test_name_appears_in_model_visible_files(task_id: str) -> None:
    names = _hidden_test_names(TASKS_DIR / task_id)
    assert names, "precondition: hidden test names found"
    for label, text in _corpus_texts().items():
        for name in names:
            assert name not in text, f"{task_id}: hidden test name {name!r} leaked into {label}"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_hidden_test_literal_appears_in_model_visible_files(task_id: str) -> None:
    """Spec and starter are assertion targets, not the public reference set.

    Pasting a graded assertion into either is exactly the leak this catches.
    """
    literals = _hidden_test_literals(task_id)
    for label, text in _corpus_texts().items():
        for literal in literals:
            assert literal not in text, (
                f"{task_id}: hidden-test string {literal!r} leaked into {label}"
            )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_hidden_test_name_appears_in_any_template(task_id: str) -> None:
    names = _hidden_test_names(TASKS_DIR / task_id)
    for template_name, template in iter_templates().items():
        for name in names:
            assert name not in template, (
                f"{task_id}: hidden test name {name!r} leaked into template {template_name}"
            )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_hidden_test_literal_appears_in_any_template(task_id: str) -> None:
    literals = _hidden_test_literals(task_id)
    for template_name, template in iter_templates().items():
        for literal in literals:
            assert literal not in template, (
                f"{task_id}: hidden-test string {literal!r} leaked into template {template_name}"
            )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_hidden_test_content_appears_in_generated_prompts(task_id: str) -> None:
    """The real check: scan every prompt a mock run actually produces."""
    names = _hidden_test_names(TASKS_DIR / task_id)
    literals = _hidden_test_literals(task_id)
    prompts = _generated_prompts()
    assert prompts, "precondition: prompts generated"

    for prompt in prompts:
        for name in names:
            assert name not in prompt, (
                f"{task_id}: hidden test name {name!r} appeared in a generated prompt"
            )
        for literal in literals:
            assert literal not in prompt, (
                f"{task_id}: hidden-test string {literal!r} appeared in a generated prompt"
            )


def test_generated_prompts_are_not_empty() -> None:
    for prompt in _generated_prompts():
        assert prompt.strip(), "a generated prompt was blank"


# ---------------------------------------------------------------------------
# The structural guard.
# ---------------------------------------------------------------------------


def test_read_allowed_refuses_hidden_tests(tmp_path) -> None:
    (tmp_path / "hidden_tests").mkdir()
    (tmp_path / "hidden_tests" / "test_hidden.py").write_text("def test_x(): pass")
    with pytest.raises(HiddenTestLeak):
        _read_allowed(tmp_path, "hidden_tests")
    with pytest.raises(HiddenTestLeak):
        _read_allowed(tmp_path, "hidden_tests/test_hidden.py")


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_load_task_context_never_reads_hidden_tests(task_id: str) -> None:
    ctx = load_task_context(TASKS_DIR / task_id)
    hidden_source = "\n".join(
        p.read_text(encoding="utf-8") for p in (TASKS_DIR / task_id / "hidden_tests").glob("*.py")
    )
    for value in ctx.prompt_sources.values():
        # No hidden-test function name may appear in any prompt source.
        for name in _hidden_test_names(TASKS_DIR / task_id):
            assert name not in value


def test_task_context_has_no_hidden_test_field() -> None:
    """A new field carrying hidden tests would be the only way to leak them."""
    fields = set(load_task_context(TASKS_DIR / TASK_IDS[0]).__dict__)
    for banned in ("hidden", "hidden_tests", "hidden_source", "answers"):
        assert not any(banned in field for field in fields)


def test_allowed_sources_excludes_hidden_tests() -> None:
    assert "hidden_tests" not in ALLOWED_SOURCES


def test_read_allowed_rejects_arbitrary_paths(tmp_path) -> None:
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "x.py").write_text("x")
    with pytest.raises(HiddenTestLeak):
        _read_allowed(tmp_path, "evil")


def test_context_loads_spec_category_and_starter() -> None:
    ctx = load_task_context(TASKS_DIR / "t07_file_serving")
    assert ctx.task_id == "t07_file_serving"
    assert ctx.category == "security"
    assert ctx.spec.strip()
    assert "serve_file" in ctx.starter
    assert "def test_" in ctx.visible_tests