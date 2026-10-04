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
from pilot.models.mock import MockModel
from pilot.prompts import load_task_context
from pilot.scoring import metrics

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / "tasks"

CONDITIONS = ("a", "b", "c")

# Illustrative mock pricing, only used to produce a *plan* estimate. The mock
# model costs nothing to serve; these figures exist so the budget guard has
# something to check before a real provider is wired in.
MOCK_PRICE_IN_PER_MTOK = 3.0
MOCK_PRICE_OUT_PER_MTOK = 15.0
ESTIMATED_TOKENS_IN = 1200
ESTIMATED_TOKENS_OUT = 800


class BudgetExceeded(RuntimeError):
    """Raised when projected or actual spend exceeds the configured cap."""


def discover_task_ids(tasks_dir: Path | None = None) -> list[str]:
    base = Path(tasks_dir or TASKS_DIR)
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("_"))


def plan(config: Config | None = None, tasks_dir: Path | None = None) -> dict[str, Any]:
    """Compute the trial plan. Pure: no model, no sandbox, no writes."""
    cfg = config or load_config()
    task_ids = discover_task_ids(tasks_dir)
    n_tasks = len(task_ids)
    trials = n_tasks * len(CONDITIONS) * max(1, cfg.experiment.n_trials)

    per_trial = metrics.estimate_cost_usd(
        ESTIMATED_TOKENS_IN, ESTIMATED_TOKENS_OUT, MOCK_PRICE_IN_PER_MTOK, MOCK_PRICE_OUT_PER_MTOK
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
        "synthetic": cfg.model.provider == "mock",
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
) -> dict[str, Any]:
    """Execute the study-1 trial matrix.

    Returns a summary dict. In dry_run mode nothing is executed and no model is
    called; the planned trial list is still returned so the control flow is
    exercised.
    """
    cfg = config or load_config()
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

    model = MockModel(seed=cfg.model.seed or 42)
    logger = JsonlLogger(run_id, base)

    executed = 0
    skipped = 0
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
                MOCK_PRICE_IN_PER_MTOK,
                MOCK_PRICE_OUT_PER_MTOK,
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

            ctx = load_task_context(task_path)
            trial = _build_condition(condition, model, task_path, cfg.experiment.ablation)
            result = trial.run(ctx)

            logger.log_trial(
                {
                    "task_id": result.task_id,
                    "condition": result.condition,
                    "iterations": result.iterations,
                    "guardrail_rounds": result.guardrail_rounds,
                    "ablated": result.ablated,
                    "rejected_writes": result.rejected_writes,
                    "hidden_pass_rate": 0.0,
                    "task_solved": 0,
                    "defect_count": 0,
                    "synthetic": True,
                }
            )
            executed += 1
            spent += trial_cost

    return {
        "run_id": run_id,
        "executed": executed,
        "skipped": skipped,
        "planned": planned["trials"],
        "spent_usd": round(spent, 4),
        "max_cost_usd": cfg.experiment.max_cost_usd,
        "dry_run": dry_run,
        "synthetic": True,
        "log": str(log_path),
    }


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

    by_condition: dict[str, list[dict[str, Any]]] = {}
    for record in trials:
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
        outcomes=[float(t.get("hidden_pass_rate", 0.0)) for t in trials],
        groups=[t.get("condition", "unknown") for t in trials],
        subjects=[t.get("participant_id", t.get("task_id", "unknown")) for t in trials],
        tasks=[t.get("task_id", "unknown") for t in trials],
    ) if trials else {"converged": False, "note": "no trials recorded", "n": 0, "coef": {}}

    analysis = {
        "run_id": run_id,
        "n_trials": len(trials),
        "synthetic": True,
        "by_condition": condition_stats,
        "contrasts": contrasts,
        "mixed_effects": mixed,
        "seed": 42,
    }

    figure_paths: list[Path] = []
    if figures and trials:
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
