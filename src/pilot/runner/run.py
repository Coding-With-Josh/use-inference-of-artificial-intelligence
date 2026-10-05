"""Study 1 runner: plan, run, analyze.

Operational properties required of a resumable, budget-guarded runner:
  * `plan()` is pure -- it computes trial counts and a cost estimate without
    calling a model or spending anything.
  * `run()` is resumable via a jsonl trial log: on restart it skips trial keys
    already recorded, so a crash mid-run does not re-bill completed trials.
  * A budget guard refuses to start work that would exceed `max_cost_usd`,
    and refuses again if the running total crosses the cap mid-run.
  * `dry_run` performs the whole control flow with no model calls and no
    sandbox runs.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pilot.analysis import plots, report, stats
from pilot.conditions.base import TrialResult
from pilot.conditions.cond_a import ConditionA
from pilot.conditions.cond_b import ConditionB
from pilot.conditions.cond_c import ConditionC
from pilot.config.config import Config, load_config
from pilot.logging.logger import JsonlLogger
from pilot.models.base import Model
from pilot.models.http import ProviderError, redact
from pilot.models.mock import MockModel  # noqa: F401  (kept for direct callers/tests)
from pilot.models.registry import build_model, is_synthetic
from pilot.prompts import load_task_context
from pilot.scoring import hidden_tests, metrics

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / "tasks"

CONDITIONS = ("a", "b", "c")

# Illustrative mock pricing, only used to produce a *plan* estimate. The mock
# model costs nothing to serve; these figures exist so the budget guard has
# something to check before a real provider is wired in. Pricing per provider
# now lives in `pilot.config.config.DEFAULT_PRICING` -- single source of truth,
# so the budget guard is denominated in whatever the configured provider bills in.
ESTIMATED_TOKENS_IN = 1200
ESTIMATED_TOKENS_OUT = 800


class BudgetExceeded(RuntimeError):
    """Raised when projected or actual spend exceeds the configured cap."""


def discover_task_ids(tasks_dir: Path | None = None) -> list[str]:
    base = Path(tasks_dir or TASKS_DIR)
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("_"))


def parse_ablation(value: str | None) -> list[str]:
    """Validate an --ablate argument against the three condition-C stages.

    Raised here, before any spend, so a typo cannot quietly produce a full
    condition-C run labelled as an ablation of something else.
    """
    from pilot.conditions.cond_c import ABLATIONS

    names = [part.strip() for part in (value or "").split(",") if part.strip()]
    unknown = sorted(set(names) - set(ABLATIONS))
    if unknown:
        raise ValueError(
            f"unknown ablation(s) {', '.join(unknown)}; "
            f"supported: {', '.join(ABLATIONS)}"
        )
    # Preserve ABLATIONS order so the recorded `ablated` list is comparable
    # between runs regardless of the order they were typed in.
    return [name for name in ABLATIONS if name in names]


def plan(config: Config | None = None, tasks_dir: Path | None = None) -> dict[str, Any]:
    """Compute the trial plan. Pure: no model, no sandbox, no writes."""
    cfg = config or load_config()
    task_ids = discover_task_ids(tasks_dir)
    n_tasks = len(task_ids)
    trials = n_tasks * len(CONDITIONS) * max(1, cfg.experiment.n_trials)

    per_trial = metrics.estimate_cost_usd(
        ESTIMATED_TOKENS_IN, ESTIMATED_TOKENS_OUT, *cfg.model.pricing()
    )
    estimate = per_trial * trials
    return {
        "tasks": n_tasks,
        "task_ids": task_ids,
        "conditions": list(CONDITIONS),
        "trials_per_task": cfg.experiment.n_trials,
        "trials": trials,
        "cost_estimate_usd": round(estimate, 4),
        "max_cost_usd": cfg.experiment.max_cost_usd,
        "within_budget": estimate <= cfg.experiment.max_cost_usd,
        "provider": cfg.model.provider,
        "synthetic": is_synthetic(cfg),
    }


@dataclass
class TrialKey:
    task_id: str
    condition: str

    def as_tuple(self) -> tuple[str, str]:
        return (self.task_id, self.condition)


def _completed_keys(log_path: Path) -> set[tuple[str, str]]:
    """Trial keys already recorded. A malformed trailing line is ignored rather
    than aborting the resume -- a crash mid-write is expected, not exceptional."""
    keys: set[tuple[str, str]] = set()
    if not log_path.exists():
        return keys
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        keys.add((record.get("task_id", ""), record.get("condition", "")))
    return keys


def _build_condition(name: str, model: Any, workdir: Path | None, ablation: str | None):
    if name == "a":
        return ConditionA(model, workdir)
    if name == "b":
        return ConditionB(model, workdir)
    if name == "c":
        ablate = [a for a in (ablation or "").split(",") if a]
        return ConditionC(model, workdir, ablate=ablate)
    raise ValueError(f"unknown condition {name!r}; expected one of {CONDITIONS}")


def run(
    config: Config | None = None,
    run_id: str = "study1",
    conditions: tuple[str, ...] = CONDITIONS,
    tasks_dir: Path | None = None,
    dry_run: bool = False,
    resume: bool = True,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Execute the study-1 trial matrix.

    Returns a summary dict. In dry_run mode nothing is executed and no model is
    called; the planned trial list is still returned so the control flow is
    exercised.

    Every trial that produces code is graded against the task's hidden suite in
    the sandbox. `timeout` bounds each sandbox run (grading and guardrails).
    """
    cfg = config or load_config()
    timeout = timeout or max(cfg.sandbox.timeout_s, 120)
    planned = plan(cfg, tasks_dir)
    if not planned["within_budget"]:
        raise BudgetExceeded(
            f"plan costs ${planned['cost_estimate_usd']:.4f}, "
            f"over the ${planned['max_cost_usd']:.2f} cap; raise MAX_COST_USD or reduce trials"
        )

    base = REPO_ROOT
    log_dir = base / "results" / run_id
    log_path = log_dir / "trials.jsonl"
    done = _completed_keys(log_path) if resume else set()

    # Provenance is derived, never asserted. This used to be hardcoded, so a real
    # provider run and a mock run were indistinguishable in the artefacts.
    synthetic = is_synthetic(cfg)
    price_in, price_out = cfg.model.pricing()

    # A missing credential is not a per-trial failure: nothing can be generated at
    # all, so fail closed and refuse before any spend or any trial record.
    model = build_model(cfg)
    if not synthetic and isinstance(model, Model):
        secret_obj = getattr(model, "_key", None)
        if secret_obj is not None and not secret_obj:
            raise ProviderError(
                f"provider {cfg.model.provider!r} selected but no API key found. "
                "Keys are read from the environment only -- never from a command-line "
                "flag, which is visible in `ps` output."
            )
    else:
        secret_obj = None
    # The one secret this process holds, unwrapped once so that provider-derived
    # text reaching the trial log can be scrubbed. None on the mock path, where
    # `redact` is a no-op.
    secret = secret_obj.reveal() if secret_obj is not None else None

    logger = JsonlLogger(run_id, base)

    executed = 0
    skipped = 0
    failed = 0
    spent = 0.0

    for task_id in planned["task_ids"]:
        task_path = Path(tasks_dir or TASKS_DIR) / task_id
        for condition in conditions:
            key = (task_id, condition)
            if resume and key in done:
                skipped += 1
                continue

            # Budget guard re-checked per trial: the plan estimate can be wrong
            # if real token usage differs, and the cap must hold at spend time.
            trial_cost = metrics.estimate_cost_usd(
                ESTIMATED_TOKENS_IN,
                ESTIMATED_TOKENS_OUT,
                price_in,
                price_out,
            )
            if spent + trial_cost > cfg.experiment.max_cost_usd:
                raise BudgetExceeded(
                    f"budget cap ${cfg.experiment.max_cost_usd:.2f} reached after "
                    f"${spent:.4f}; stopping before {condition}/{task_id}"
                )

            if dry_run:
                executed += 1
                spent += trial_cost
                continue

            # Condition C writes its solution through a WriteAuthority, so the
            # workdir must be a per-trial scratch copy -- never the task itself.
            # Handing it tasks/<id>/ would let a run mutate the graded corpus,
            # which is both an integrity problem and a way to contaminate a
            # later validation.
            workspace = _stage_workspace(run_id, task_path, condition)
            ctx = load_task_context(task_path)
            trial = _build_condition(condition, model, workspace, cfg.experiment.ablation)

            # A provider outage or a malformed response must not destroy the other
            # 599 trials. Record the trial as explicitly ungraded and continue:
            # analyze() counts ungraded trials separately and never folds them
            # into a measured zero. Recording nothing would lose the resume point
            # and re-run the trial; recording a score would fabricate a result.
            try:
                result = trial.run(ctx)
            except Exception as exc:  # noqa: BLE001 - deliberate boundary
                failed += 1
                logger.log_trial(
                    {
                        "task_id": task_id,
                        "condition": condition,
                        "iterations": 0,
                        "guardrail_rounds": 0,
                        "ablated": [],
                        "rejected_writes": [],
                        **UNGRADED_METRICS,
                        "grade_exit_class": "not_graded",
                        "ungraded_reason": f"{type(exc).__name__}: {redact(str(exc), secret)}",
                        "synthetic": synthetic,
                    }
                )
                continue

            logger.log_trial(
                {
                    "task_id": result.task_id,
                    "condition": result.condition,
                    "iterations": result.iterations,
                    "guardrail_rounds": result.guardrail_rounds,
                    "ablated": result.ablated,
                    "rejected_writes": result.rejected_writes,
                    **grade_trial(task_path, workspace, result.final_code, timeout=timeout),
                    "synthetic": synthetic,
                }
            )
            executed += 1
            spent += trial_cost

    return {
        "run_id": run_id,
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "planned": planned["trials"],
        "spent_usd": round(spent, 4),
        "max_cost_usd": cfg.experiment.max_cost_usd,
        "provider": cfg.model.provider,
        "dry_run": dry_run,
        "synthetic": synthetic,
        "log": str(log_path),
    }


# Task files a condition may see. The workspace is a copy, so copying the whole
# task directory is safe; excluding hidden_tests keeps the graded suite out of
# anything a condition can reach.
WORKSPACE_SOURCES = ("spec.md", "meta.yaml", "starter", "visible_tests")

# Exit classes that represent a real pass/fail verdict from the hidden suite.
# Anything else (interrupted, usage error, nothing collected, timeout, launcher
# failure) means the suite did not produce a score.
GRADABLE_EXIT_CLASSES = frozenset({"passed", "tests_failed"})

# Fields grade_trial always returns, so a trial record has one shape whether or
# not it could be graded.
UNGRADED_METRICS: dict[str, Any] = {
    "graded": False,
    "hidden_pass_rate": 0.0,
    "task_solved": 0,
    "defect_count": 0,
    "hidden_tests_total": 0,
    "grade_exit_class": "not_graded",
    "grade_errors": 0,
}


def _entrypoint_module(task_path: Path) -> str | None:
    """The task's solution module, e.g. `merge_intervals.py`.

    The hidden tests import this by name, so a trial's code has to land on this
    exact filename to be graded at all.
    """
    modules = sorted(
        p.name for p in (task_path / "starter").glob("*.py") if p.name != "__init__.py"
    )
    return modules[0] if len(modules) == 1 else None


def grade_trial(
    task_path: Path,
    workspace: Path,
    code: str,
    timeout: int | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Score a trial's code against the task's hidden suite, in the sandbox.

    Grading runs in a *separate* directory from the condition's workspace, and
    that directory is the first place hidden_tests is ever copied. The condition
    never receives it, so scoring cannot leak the graded suite backwards into
    the trial.

    Returns metrics plus `graded`. `graded: False` means no verdict was produced
    -- which is reported distinctly from a genuine score of 0, so "we could not
    measure this" never renders as "this scored nothing".
    """
    entrypoint = _entrypoint_module(task_path)
    if entrypoint is None:
        return {**UNGRADED_METRICS, "grade_reason": "could not identify the task entrypoint"}
    if not code.strip():
        return {**UNGRADED_METRICS, "grade_reason": "trial produced no code"}

    grading_dir = workspace.parent / f"{workspace.name}__grading"
    if grading_dir.exists():
        shutil.rmtree(grading_dir)
    grading_dir.mkdir(parents=True)
    # The trial's code goes on the entrypoint filename the hidden tests import.
    shutil.copytree(workspace / "starter", grading_dir / "starter", dirs_exist_ok=True)
    (grading_dir / "starter" / entrypoint).write_text(code, encoding="utf-8")
    shutil.copytree(task_path / "hidden_tests", grading_dir / "hidden_tests")

    scored = hidden_tests.run_hidden_tests(
        grading_dir, "starter", timeout=timeout, image=image
    )

    # A grade exists only if the suite actually ran and produced a pass/fail
    # verdict. Everything else is a measurement failure, and a measurement
    # failure reported as 0.0 is indistinguishable from a genuine all-fail.
    #
    # `errors` matters as much as `total`: when a trial's code does not even
    # import, pytest prints "Interrupted: 1 error during collection", and the
    # summary parser counts that error as one collected item. Gating on
    # `total > 0` alone would report a score of 0 for a suite that never ran.
    unusable = scored["exit_class"] not in GRADABLE_EXIT_CLASSES or scored["total"] == 0
    if unusable or scored["errors"]:
        reason = (
            f"hidden suite did not run: exit_class={scored['exit_class']}, "
            f"errors={scored['errors']}, collected={scored['total']}"
        )
        return {
            **UNGRADED_METRICS,
            "grade_exit_class": scored["exit_class"],
            "grade_errors": scored["errors"],
            "grade_reason": reason,
        }

    outcomes = [True] * scored["passed"] + [False] * scored["failed"]
    return {
        "graded": True,
        "hidden_pass_rate": metrics.hidden_pass_rate(outcomes),
        "task_solved": metrics.task_solved(outcomes),
        "defect_count": metrics.defect_count(outcomes),
        "hidden_tests_total": scored["total"],
        "grade_exit_class": scored["exit_class"],
        "grade_errors": 0,
        "failed_nodes": scored["failed_nodes"],
    }


def _stage_workspace(run_id: str, task_path: Path, condition: str) -> Path:
    """Copy a task into a scratch workspace for one trial.

    The copy is what the condition writes into. `hidden_tests` is deliberately
    not copied: no condition needs it, and leaving it out means a workspace
    cannot leak the graded suite into a prompt or a repair loop.
    """
    workspace = REPO_ROOT / "results" / run_id / "work" / f"{task_path.name}__{condition}"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_SOURCES:
        source = task_path / name
        if source.is_dir():
            shutil.copytree(source, workspace / name)
        elif source.exists():
            shutil.copy2(source, workspace / name)
    return workspace


def load_trials(run_id: str = "study1") -> list[dict[str, Any]]:
    """Read a run's trial records. Returns [] when the run does not exist."""
    log_path = REPO_ROOT / "results" / run_id / "trials.jsonl"
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def analyze(
    run_id: str = "study1",
    output_dir: Path | None = None,
    figures: bool = True,
) -> dict[str, Any]:
    """Analyze a completed run and write the report plus figures.

    With no recorded trials this writes a report that explicitly says there is
    no data, rather than an empty-looking results table.
    """
    trials = load_trials(run_id)
    out_dir = Path(output_dir or (REPO_ROOT / "results" / run_id / "analysis"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # A trial that could not be graded carries hidden_pass_rate 0.0, which is
    # indistinguishable from a trial that genuinely scored zero. Averaging it in
    # would turn a measurement failure into a result, so statistics are built
    # from graded trials only and the ungraded ones are counted and reported.
    graded = [t for t in trials if t.get("graded", True)]
    ungraded = [t for t in trials if not t.get("graded", True)]
    ungraded_reasons = sorted(
        {str(t.get("grade_reason") or "no reason recorded") for t in ungraded}
    )

    by_condition: dict[str, list[dict[str, Any]]] = {}
    for record in graded:
        by_condition.setdefault(record.get("condition", "unknown"), []).append(record)

    condition_stats = {
        name: metrics.aggregate_trials(records) for name, records in by_condition.items()
    }

    contrasts: dict[str, Any] = {}
    if "b" in by_condition and "c" in by_condition:
        b = _aligned(by_condition["b"], by_condition["c"])
        if b:
            contrasts["c_minus_b_hidden_pass_rate"] = stats.analyze_condition_contrast(
                b["c"], b["b"]
            )

    mixed = stats.mixed_effects_model(
        outcomes=[float(t.get("hidden_pass_rate", 0.0)) for t in graded],
        groups=[t.get("condition", "unknown") for t in graded],
        subjects=[t.get("participant_id", t.get("task_id", "unknown")) for t in graded],
        tasks=[t.get("task_id", "unknown") for t in graded],
    ) if graded else {"converged": False, "note": "no graded trials", "n": 0, "coef": {}}

    analysis = {
        "run_id": run_id,
        "n_trials": len(trials),
        "n_graded": len(graded),
        "n_ungraded": len(ungraded),
        "ungraded_reasons": ungraded_reasons,
        "synthetic": True,
        "by_condition": condition_stats,
        "contrasts": contrasts,
        "mixed_effects": mixed,
        "seed": 42,
    }

    figure_paths: list[Path] = []
    if figures and by_condition:
        values = {
            name: [float(t.get("hidden_pass_rate", 0.0)) for t in records]
            for name, records in by_condition.items()
        }
        defects = {
            name: [int(t.get("defect_count", 0)) for t in records]
            for name, records in by_condition.items()
        }
        figure_paths.append(
            plots.plot_outcomes_by_condition(values, out_dir / "outcomes.png", synthetic=True)
        )
        figure_paths.append(
            plots.plot_defect_histogram(defects, out_dir / "defects.png", synthetic=True)
        )
        for label, result in contrasts.items():
            slug = label.replace("_", "-")
            figure_paths.append(
                plots.plot_effect_size_ci(
                    result["effect"], out_dir / f"effect-{slug}.png", synthetic=True
                )
            )

    report_path = report.write_report(out_dir / "report.md", analysis, figure_paths)
    analysis["report"] = str(report_path)
    analysis["figures"] = [str(p) for p in figure_paths]
    return analysis


def _aligned(b_records: list[dict], c_records: list[dict]) -> dict[str, list[float]] | None:
    """Pair b and c results by task id so the contrast is genuinely paired."""
    b_by_task: dict[str, float] = {
        str(r.get("task_id")): float(r.get("hidden_pass_rate", 0.0)) for r in b_records
    }
    c_by_task: dict[str, float] = {
        str(r.get("task_id")): float(r.get("hidden_pass_rate", 0.0)) for r in c_records
    }
    shared = sorted(set(b_by_task) & set(c_by_task))
    if not shared:
        return None
    return {"b": [b_by_task[t] for t in shared], "c": [c_by_task[t] for t in shared]}


__all__ = [
    "BudgetExceeded",
    "TrialResult",
    "analyze",
    "discover_task_ids",
    "load_trials",
    "plan",
    "run",
]
