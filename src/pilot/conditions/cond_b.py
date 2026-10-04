"""Condition B: naive use.

docs/conditions.md: "prompt is task spec plus visible tests as plain text only.
One generation, no retries, no feedback. Output accepted as is."

The defining property is that there is no checking stage. Whatever the model
returns is written and graded. That is the whole point of the condition, so
there is deliberately no repair loop here.
"""

from __future__ import annotations

from pilot.conditions.base import Condition, TrialResult
from pilot.prompts import TaskContext, build_condition_b_prompt


class ConditionB(Condition):
    name = "b"

    def run(self, ctx: TaskContext) -> TrialResult:
        prompt = build_condition_b_prompt(ctx)
        response = self.model.generate(prompt)
        return TrialResult(
            condition=self.name,
            task_id=ctx.task_id,
            final_code=self._strip_code_fence(response),
            iterations=1,
            prompts=[prompt],
            responses=[response],
        )


def run_cond_b(task_id: str, model, prompt: str) -> dict:
    """Backwards-compatible functional entrypoint retained from the skeleton.

    New code should use `ConditionB(...).run(ctx)`, which also builds the prompt
    and captures it for provenance.
    """
    response = model.generate(prompt)
    return {
        "condition": "b",
        "task_id": task_id,
        "response": response,
        "iterations": 1,
    }
