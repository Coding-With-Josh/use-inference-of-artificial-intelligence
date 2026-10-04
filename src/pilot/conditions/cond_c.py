from __future__ import annotations

from typing import Any


def run_cond_c(task_id: str, model: Any, prompt: str, ablate: list[str] | None = None) -> dict[str, Any]:
    ablate = ablate or []
    iterations = 1
    if "decomposition" not in ablate:
        iterations += 1
    if "guardrails" not in ablate:
        iterations += 1
    if "context" not in ablate:
        pass
    response = model.generate(prompt)
    return {"condition": "c", "task_id": task_id, "response": response, "iterations": iterations, "ablated": ablate}
