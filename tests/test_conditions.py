"""Tests for the three conditions and their ablations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pilot.conditions.base import Condition, TrialResult
from pilot.conditions.cond_a import ConditionA, run_cond_a
from pilot.conditions.cond_b import ConditionB, run_cond_b
from pilot.conditions.cond_c import ConditionC
from pilot.models.base import Model
from pilot.prompts import load_task_context

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"


class ScriptedModel(Model):
    """Model returning canned responses in order, recording every prompt."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []
        self._index = 0

    def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        if self._index < len(self.responses):
            response = self.responses[self._index]
            self._index += 1
            return response
        return self.responses[-1] if self.responses else ""


@pytest.fixture
def ctx():
    return load_task_context(TASKS_DIR / "t01_merge_intervals")


# --------------------------------------------------------------------------
# Condition A
# --------------------------------------------------------------------------


def test_cond_a_calls_no_model(ctx):
    model = ScriptedModel(["should not be used"])
    result = ConditionA(model).run(ctx)
    assert result.condition == "a"
    assert model.prompts == [], "condition A must not call a model"
    assert result.responses == []
    assert result.iterations == 0


def test_cond_a_records_instructions(ctx):
    result = ConditionA(ScriptedModel([])).run(ctx)
    assert result.prompts
    assert ctx.task_id in result.prompts[0]


def test_run_cond_a_functional():
    record = run_cond_a("t01", human_code="x", elapsed_s=12.5)
    assert record["condition"] == "a"
    assert record["elapsed_s"] == 12.5


# --------------------------------------------------------------------------
# Condition B
# --------------------------------------------------------------------------


def test_cond_b_single_generation_no_retries(ctx):
    model = ScriptedModel(["```python\ndef merge_intervals(i):\n    return []\n```"])
    result = ConditionB(model).run(ctx)
    assert result.condition == "b"
    assert result.iterations == 1
    assert len(model.prompts) == 1
    assert result.guardrail_rounds == 0


def test_cond_b_strips_code_fence(ctx):
    model = ScriptedModel(["```python\nCODE_HERE\n```"])
    result = ConditionB(model).run(ctx)
    assert result.final_code == "CODE_HERE"


def test_cond_b_prompt_contains_spec_and_visible_tests(ctx):
    model = ScriptedModel(["x"])
    ConditionB(model).run(ctx)
    prompt = model.prompts[0]
    assert "merge" in prompt.lower()
    assert "test_" in prompt


def test_run_cond_b_functional():
    model = ScriptedModel(["resp"])
    record = run_cond_b("t01", model, "prompt text")
    assert record == {
        "condition": "b",
        "task_id": "t01",
        "response": "resp",
        "iterations": 1,
    }


# --------------------------------------------------------------------------
# Condition C
# --------------------------------------------------------------------------


def test_cond_c_rejects_unknown_ablation():
    with pytest.raises(ValueError, match="unknown ablation"):
        ConditionC(ScriptedModel(["x"]), ablate=["not_a_stage"])


@pytest.mark.parametrize("stage", ["context", "decomposition", "guardrails"])
def test_cond_c_accepts_each_documented_ablation(stage):
    condition = ConditionC(ScriptedModel(["x"]), ablate=[stage])
    assert stage in condition.ablate


def test_cond_c_runs_stages_without_workdir(ctx):
    """No workdir means nothing to grade, so it must not crash or loop."""
    model = ScriptedModel(["plan\n1. step one\n2. step two", "CODE"])
    result = ConditionC(model).run(ctx)
    assert result.condition == "c"
    assert result.guardrail_rounds == 0
    assert result.prompts


def test_cond_c_decomposition_parses_numbered_steps(ctx):
    # Order matters: the context stage consumes the first response, then the
    # decomposition stage gets the plan, then one response per parsed step.
    model = ScriptedModel(["CONTEXT", "1. first\n2. second\n3. third", "S1", "S2", "S3"])
    ConditionC(model).run(ctx)
    assert len(model.prompts) >= 4
    assert any("first" in p for p in model.prompts)
    assert any("second" in p for p in model.prompts)
    assert any("third" in p for p in model.prompts)


def test_cond_c_step_cap_is_enforced(ctx):
    plan = "\n".join(f"{i}. step {i}" for i in range(1, 20))
    model = ScriptedModel(["CONTEXT", plan] + [f"S{i}" for i in range(19)])
    condition = ConditionC(model, max_steps=3)
    condition.run(ctx)
    step_prompts = [p for p in model.prompts if "Implement step" in p]
    assert len(step_prompts) == 3


def test_cond_c_context_ablation_skips_context_stage(ctx):
    with_ctx = ScriptedModel(["x"])
    ConditionC(with_ctx, ablate=[]).run(ctx)
    without = ScriptedModel(["x"])
    ConditionC(without, ablate=["context"]).run(ctx)
    assert any("Project context:" in p for p in with_ctx.prompts)
    assert any("pilot-practice workflow" in p for p in with_ctx.prompts)
    assert not any("pilot-practice workflow" in p for p in without.prompts)


def test_cond_c_decomposition_ablation_skips_plan_stage(ctx):
    model = ScriptedModel(["1. a step", "CODE"])
    ConditionC(model, ablate=["decomposition"]).run(ctx)
    assert not any("decompose the task" in p for p in model.prompts)


def test_cond_c_records_ablations(ctx):
    result = ConditionC(ScriptedModel(["x"]), ablate=["guardrails"]).run(ctx)
    assert result.ablated == ["guardrails"]


# --------------------------------------------------------------------------
# Scoped authority integration
# --------------------------------------------------------------------------


def test_cond_c_writes_only_to_granted_file(tmp_path, ctx):
    target = tmp_path / "starter" / "solution.py"
    condition = ConditionC(
        ScriptedModel(["x"]), workdir=tmp_path, target_file="starter/solution.py"
    )
    result = condition.run(ctx)
    assert target.exists(), "granted write did not happen"
    assert result.rejected_writes == []


def test_cond_c_refuses_ungranted_file(tmp_path, ctx):
    """A target outside the grant must be refused and recorded, not written."""
    condition = ConditionC(
        ScriptedModel(["x"]),
        workdir=tmp_path,
        target_file="../escape.py",
        run_guardrails=False,
    )
    result = condition.run(ctx)
    assert not (tmp_path.parent / "escape.py").exists()
    assert result.rejected_writes
    assert "refused" in result.rejected_writes[0]["error"]


def test_cond_c_audit_log_records_rejection(tmp_path, ctx):
    audit = tmp_path / "audit.jsonl"
    condition = ConditionC(
        ScriptedModel(["x"]),
        workdir=tmp_path,
        target_file="../escape.py",
        run_guardrails=False,
    )
    condition.run(ctx)
    # The authority in this path writes its audit next to the run root.
    assert audit.parent.exists()


# --------------------------------------------------------------------------
# Base helpers
# --------------------------------------------------------------------------


def test_trial_result_reports_success():
    assert TrialResult("b", "t01", "code").succeeded is True
    assert TrialResult("b", "t01", "code", error="boom").succeeded is False


def test_trial_result_record_shape():
    record = TrialResult("c", "t01", "code", iterations=3).as_record()
    assert record["condition"] == "c"
    assert record["iterations"] == 3
    assert "guardrail_failures" in record
    assert json.dumps(record)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```python\nx = 1\n```", "x = 1"),
        ("```\nplain\n```", "plain"),
        ("no fence", "no fence"),
        ("```py\ntrailing fence\n```", "trailing fence"),
    ],
)
def test_strip_code_fence(raw, expected):
    assert Condition._strip_code_fence(raw) == expected
