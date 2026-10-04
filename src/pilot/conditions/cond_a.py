"""Condition A: no-AI baseline.

No model is called. The trial records that the task was attempted unaided, which
is the baseline the other conditions are compared against (docs/design.md h2:
condition c finishes faster than condition a at comparable quality).
"""

from __future__ import annotations

from typing import Any

from pilot.conditions.base import Condition, TrialResult
from pilot.prompts import TaskContext, build_condition_a_prompt


class ConditionA(Condition):
    name = "a"

    def run(self, ctx: TaskContext) -> TrialResult:
        # The instruction text is still built and logged, so the trial record has
        # the same shape across conditions -- but no model is ever invoked.
        instructions = build_condition_a_prompt(ctx)
        return TrialResult(
            condition=self.name,
            task_id=ctx.task_id,
            final_code="",
            iterations=0,
            prompts=[instructions],
            responses=[],
        )


def run_cond_a(task_id: str, human_code: str = "", elapsed_s: float = 0.0) -> dict[str, Any]:
    """Record an unaided human attempt supplied by the study harness."""
    return {
        "condition": "a",
        "task_id": task_id,
        "code": human_code,
        "elapsed_s": elapsed_s,
    }
