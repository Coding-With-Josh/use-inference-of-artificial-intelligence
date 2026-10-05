"""Deterministic stand-in for a real model.

The mock exists so the whole pipeline -- plan, generate, guardrails, write,
grade, analyze -- can be exercised without a provider key. That only works if its
output is *consumable*: the harness grades each trial by writing the model's
response to the task's entrypoint module, importing it, and running the task's
hidden suite against it.

So the mock emits syntactically valid Python that exposes whatever identifiers
the prompt implies, plus a module-level ``__getattr__`` (PEP 562) so names the
prompt never mentioned still resolve. Without that fallback the mock is unusable
in practice: condition C's final prompt is a single decomposition step and names
nothing at all, so every trial came back uncollectable and the whole scoring path
was dead code.

An earlier version returned bare tokens ('correct', 'insecure', 'subtly_wrong'),
which do not even import, so nothing was ever graded.

It still has no access to the hidden tests, so it cannot game them: a graded mock
trial is a real measurement of a deliberately inert program, and the resulting
score is genuinely zero rather than unmeasured.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pilot.models.base import Model

# `def name(` at any indentation, i.e. a function the prompt shows.
_SIGNATURE = re.compile(r"^[ \t]*def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)

# `from mod import a, b` -- the shape a test uses to reach the entrypoint.
_FROM_IMPORT = re.compile(r"^[ \t]*from\s+[\w.]+\s+import\s+([^\n#]+)", re.MULTILINE)

# One *expression* per outcome label: expressions compose into both a function
# body (`return <expr>`) and a lambda, which statements would not. All are valid
# Python, all are wrong in different ways, and none is tuned to any task.
_EXPRESSIONS = {
    "correct": "args[0] if args else None",
    "subtly_wrong": "None",
    "insecure": "eval('1')",
}


class MockModel(Model):
    """A seeded, offline model that returns importable, inert code."""

    provider = "mock"

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, "model_id": "mock", "seed": self.seed}

    def label(self, prompt: str) -> str:
        """The outcome this prompt deterministically maps to."""
        digest = hashlib.md5((prompt + str(self.seed)).encode()).hexdigest()
        lowered = prompt.lower()
        if "security" in lowered or "sql" in lowered or "path" in lowered:
            return "insecure"
        return "correct" if int(digest[0], 16) < 8 else "subtly_wrong"

    def names(self, prompt: str) -> list[str]:
        """Identifiers the prompt implies the solution module must expose."""
        found = list(_SIGNATURE.findall(prompt))
        for group in _FROM_IMPORT.findall(prompt):
            found += [part.strip() for part in group.split(",")]
        ordered: list[str] = []
        for name in found:
            # Only plain identifiers: `*`, dotted paths and `as` aliases are not
            # valid function definitions.
            if name.isidentifier() and name not in ordered and not name.startswith("_"):
                ordered.append(name)
        return ordered

    def generate(self, prompt: str, **kwargs: Any) -> str:
        label = self.label(prompt)
        expression = _EXPRESSIONS[label]

        lines = [f"# mock output ({label}) -- inert by construction"]
        for name in self.names(prompt):
            lines += [f"def {name}(*args, **kwargs):", f"    return {expression}"]

        # Module-level __getattr__ (PEP 562): resolve any name the prompt did not
        # mention, so the hidden tests reach their assertions instead of dying at
        # import. Everything it hands back is still wrong.
        lines += [
            "def __getattr__(name):",
            f"    return lambda *args, **kwargs: ({expression})",
        ]
        return "\n".join(lines) + "\n"
