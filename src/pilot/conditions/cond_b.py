from __future__ import annotations

from typing import Any


def run_cond_b(task_id: str, model: Any, prompt: str) -> dict[str, Any]:
    response = model.generate(prompt)
    return {"condition": "b", "task_id": task_id, "response": response, "iterations": 1}
