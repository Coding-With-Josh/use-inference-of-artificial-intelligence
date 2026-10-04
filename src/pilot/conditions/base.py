"""Shared types for the three experimental conditions.

docs/design.md defines them as:
  a -- no ai (human baseline)
  b -- naive ai: spec + visible tests, one generation, no retries
  c -- pilot practice: context, decomposition, guardrails, scoped authority
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pilot.models.base import Model
from pilot.prompts import TaskContext


@dataclass
class TrialResult:
    """One trial: one task, one condition, one model.

    `final_code` is the code the harness actually wrote to disk and graded.
    `iterations` counts generate/repair rounds, per docs/metrics.md.
    """

    condition: str
    task_id: str
    final_code: str
    iterations: int = 1
    prompts: list[str] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)
    guardrail_failures: list[str] = field(default_factory=list)
    guardrail_rounds: int = 0
    ablated: list[str] = field(default_factory=list)
    rejected_writes: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def as_record(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "task_id": self.task_id,
            "iterations": self.iterations,
            "guardrail_rounds": self.guardrail_rounds,
            "guardrail_failures": self.guardrail_failures,
            "ablated": self.ablated,
            "rejected_writes": self.rejected_writes,
            "error": self.error,
        }


class Condition(ABC):
    """A condition turns a model plus a task context into a graded solution."""

    name: str = ""

    def __init__(self, model: Model, workdir: Any = None) -> None:
        self.model = model
        self.workdir = workdir

    @abstractmethod
    def run(self, ctx: TaskContext) -> TrialResult:
        """Produce a solution for `ctx`."""

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Models wrap code in fences often enough to be worth handling."""
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
