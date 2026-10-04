"""Tests for the model layer.

The mock's contract has one job beyond determinism: its output must be valid,
importable Python. The harness grades a trial by writing the response to the
task's entrypoint module and importing it, so un-importable output makes every
trial ungradeable -- which silently turns the whole scoring path into dead code.
"""

from __future__ import annotations

import ast

import pytest

from pilot.models import mock
from pilot.models.base import Model

SPEC_PROMPT = """Implement this.

```python
def merge_intervals(intervals):
    raise NotImplementedError
```
"""


def test_mock_is_a_model():
    assert isinstance(mock.MockModel(seed=1), Model)


def test_mock_generates():
    m = mock.MockModel(seed=42)
    assert m.generate("test")


def test_mock_is_deterministic_for_a_fixed_seed():
    a = mock.MockModel(seed=7).generate(SPEC_PROMPT)
    b = mock.MockModel(seed=7).generate(SPEC_PROMPT)
    assert a == b


def test_mock_seed_changes_the_outcome_label():
    labels = {mock.MockModel(seed=s).label(SPEC_PROMPT) for s in range(40)}
    assert len(labels) > 1, "the seed does not affect the label at all"


def test_output_is_valid_python():
    """The property the grader depends on."""
    for seed in range(30):
        source = mock.MockModel(seed=seed).generate(SPEC_PROMPT)
        ast.parse(source)  # raises if not syntactically valid


def test_output_defines_the_functions_the_prompt_shows():
    source = mock.MockModel(seed=3).generate(SPEC_PROMPT)
    tree = ast.parse(source)
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "merge_intervals" in defined


def test_duplicate_signatures_are_emitted_once():
    prompt = "def f(a):\n    pass\n\ndef f(b):\n    pass\n"
    source = mock.MockModel(seed=1).generate(prompt)
    tree = ast.parse(source)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    # __getattr__ is always present, so assert on the prompt-derived names.
    assert [n for n in names if n != "__getattr__"] == ["f"]


def test_prompt_with_no_signature_still_yields_valid_python():
    source = mock.MockModel(seed=2).generate("Just describe the task in prose.")
    ast.parse(source)


def test_security_flavored_prompts_map_to_the_insecure_label():
    model = mock.MockModel(seed=1)
    assert model.label("Write a safe path joiner") == "insecure"


@pytest.mark.parametrize("label", sorted(mock._EXPRESSIONS))
def test_every_label_expression_composes_into_valid_python(label):
    """An expression that does not compose breaks grading for that whole label."""
    expression = mock._EXPRESSIONS[label]
    ast.parse(f"def f(*args, **kwargs):\n    return {expression}\n")
    ast.parse(f"def g(name):\n    return lambda *a, **k: ({expression})\n")


def test_names_come_from_import_statements_too():
    """The hidden tests reach the entrypoint by import, not by `def`."""
    prompt = "from merge_intervals import merge_intervals, Interval\n"
    assert mock.MockModel(seed=1).names(prompt) == ["merge_intervals", "Interval"]


def test_names_drops_star_imports_and_dunder():
    prompt = "from mod import *\nfrom other import _private\n"
    assert mock.MockModel(seed=1).names(prompt) == []


@pytest.mark.parametrize("seed", range(12))
def test_unmentioned_names_still_resolve(seed):
    """PEP 562 fallback: this is what keeps grading reachable at all.

    Without it a hidden test dies at `from mod import whatever`, pytest reports a
    collection error, and the trial is recorded as ungraded -- the scoring path
    would never execute even once.
    """
    import types

    model = mock.MockModel(seed=seed)
    source = model.generate("no signatures here")
    module = types.ModuleType("candidate")
    exec(compile(source, "candidate.py", "exec"), module.__dict__)  # noqa: S102

    resolved = module.anything_at_all
    assert callable(resolved), f"seed {seed} ({model.label('x')}) did not resolve"
    resolved()  # must not raise


def test_prompt_free_output_is_still_importable():
    import types

    source = mock.MockModel(seed=9).generate("just prose, no code")
    module = types.ModuleType("candidate")
    exec(compile(source, "candidate.py", "exec"), module.__dict__)  # noqa: S102
    assert callable(module.whatever)
