"""Condition C: pilot practice.

docs/conditions.md defines four stages, each separately ablatable:

  1. context      -- spec, visible tests, project context template, starter code
  2. decomposition -- plan steps, generate and integrate per step (step cap)
  3. guardrails   -- run visible tests + static checks in the sandbox, feed
                     failures back for repair (max_repair_rounds, stop on pass)
  4. scoped authority -- writes only to designated task files; others rejected
                     and logged

The point of the condition is that every write goes through `WriteAuthority` and
every stage-3 check runs untrusted code in the sandbox. Ablating a stage removes
that control, which is what makes the ablation interpretable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pilot.authority import UnauthorizedWrite, WriteAuthority
from pilot.conditions.base import Condition, TrialResult
from pilot.prompts import (
    TaskContext,
    build_condition_c_context_prompt,
    build_decomposition_prompt,
    build_repair_prompt,
    build_step_prompt,
)
from pilot.scoring.guardrails import GuardrailReport, run_guardrails

ABLATIONS = ("context", "decomposition", "guardrails")


class ConditionC(Condition):
    name = "c"

    def __init__(
        self,
        model: Any,
        workdir: Any = None,
        ablate: list[str] | None = None,
        max_repair_rounds: int = 3,
        max_steps: int = 5,
        target_file: str | None = None,
        run_guardrails: bool = True,
    ) -> None:
        super().__init__(model, workdir)
        unknown = set(ablate or []) - set(ABLATIONS)
        if unknown:
            raise ValueError(f"unknown ablation(s): {sorted(unknown)}; expected {list(ABLATIONS)}")
        self.ablate = list(ablate or [])
        self.max_repair_rounds = max_repair_rounds
        self.max_steps = max_steps
        self.target_file = target_file
        self.run_guardrails_enabled = run_guardrails

    # -- stages -------------------------------------------------------------

    def _stage_context(self, ctx: TaskContext, prompts: list[str], responses: list[str]) -> None:
        if "context" in self.ablate:
            return
        prompt = build_condition_c_context_prompt(ctx)
        prompts.append(prompt)
        responses.append(self.model.generate(prompt))

    def _stage_decomposition(
        self, ctx: TaskContext, prompts: list[str], responses: list[str]
    ) -> list[str]:
        if "decomposition" in self.ablate:
            return []
        plan_prompt = build_decomposition_prompt(ctx)
        prompts.append(plan_prompt)
        plan_response = self.model.generate(plan_prompt)
        responses.append(plan_response)
        steps = self._parse_steps(plan_response)[: self.max_steps]
        for index, step in enumerate(steps, start=1):
            step_prompt = build_step_prompt(step, index, len(steps))
            prompts.append(step_prompt)
            responses.append(self.model.generate(step_prompt))
        return steps

    @staticmethod
    def _parse_steps(plan: str) -> list[str]:
        steps = []
        for line in plan.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            head, sep, rest = stripped.partition(".")
            if sep and head.strip().isdigit() and rest.strip():
                steps.append(rest.strip())
        return steps

    # -- main ---------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TrialResult:
        prompts: list[str] = []
        responses: list[str] = []
        failures: list[str] = []
        rejected: list[dict[str, Any]] = []
        guardrail_rounds = 0
        iterations = 0
        error: str | None = None

        authority = self._authority(ctx)

        self._stage_context(ctx, prompts, responses)
        iterations += 1

        self._stage_decomposition(ctx, prompts, responses)
        iterations += 1

        code = responses[-1] if responses else ""
        # Guardrails need something on disk to check. With no workdir there is
        # nothing to run against, so the loop is skipped rather than tripping an
        # assertion below.
        guardrails_on = (
            self.run_guardrails_enabled
            and "guardrails" not in self.ablate
            and authority is not None
        )

        if guardrails_on:
            # Bounded repair loop: stop as soon as checks pass, never exceed
            # max_repair_rounds. `iterations` therefore reflects actual rounds.
            for round_index in range(self.max_repair_rounds + 1):
                written, write_error = self._write(authority, code)
                if write_error is not None:
                    rejected.append(write_error)
                    continue

                report = self._guardrails(written)
                if report is None:
                    break
                guardrail_rounds += 1
                if report.passed:
                    break
                if round_index == self.max_repair_rounds:
                    failures = report.failures
                    break
                failures = report.failures
                repair_prompt = build_repair_prompt(report.format_failures())
                prompts.append(repair_prompt)
                response = self.model.generate(repair_prompt)
                responses.append(response)
                code = self._strip_code_fence(response)
                iterations += 1
        else:
            self._write(authority, code)

        return TrialResult(
            condition=self.name,
            task_id=ctx.task_id,
            final_code=code,
            iterations=iterations,
            prompts=prompts,
            responses=responses,
            guardrail_failures=failures,
            guardrail_rounds=guardrail_rounds,
            ablated=list(self.ablate),
            rejected_writes=rejected,
            error=error,
        )

    # -- helpers ------------------------------------------------------------

    def _authority(self, ctx: TaskContext) -> WriteAuthority | None:
        if self.workdir is None:
            return None
        target = self.target_file or self._default_target(ctx)
        return WriteAuthority(Path(self.workdir), allowed=(target,))

    @staticmethod
    def _default_target(ctx: TaskContext) -> str:
        # The starter's own module is the only writable target by default.
        return "starter/solution.py"

    def _write(self, authority: WriteAuthority | None, code: str) -> tuple[Any, dict | None]:
        """Write through the authority, recording rejections instead of raising."""
        if authority is None:
            return None, None
        target = authority.allowed[0]
        try:
            return authority.write(target, code), None
        except UnauthorizedWrite as exc:
            return None, {
                "target": target,
                "error": str(exc),
                "decision": authority.decisions[-1].as_record() if authority.decisions else None,
            }

    def _guardrails(self, written: Any) -> GuardrailReport | None:
        if self.workdir is None:
            return None
        return run_guardrails(Path(self.workdir), target_file=self.target_file)
