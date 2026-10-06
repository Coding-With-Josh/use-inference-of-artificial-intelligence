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

#: Attrition spread, in percentage points of ungraded trials, above which the
#: conditions are measuring different subsets badly enough to say so loudly.
#: 5 points is the threshold from the reporting guidance for differential
#: attrition: beyond it the contrast is confounded with what was lost, not merely
#: noisier. Configurable because it is a judgement call, but a constant so the
#: report and the test agree on one number.
ATTRITION_IMBALANCE_POINTS = 5.0

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
    """Task directory names in the corpus.

    A missing directory yields an empty list rather than raising: `plan()` is a
    pure query and is used for previews, so pointing it at a path that is not there
    yet should report zero trials, not a traceback.
    """
    base = Path(tasks_dir or TASKS_DIR)
    if not base.is_dir():
        return []
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


def _resolve_task_id(token: str, known: list[str]) -> str:
    """Resolve one `--tasks` token to a corpus directory name.

    Accepts the full id or any unambiguous prefix, so `--tasks t01,t07` works
    without the operator copying long names like `t07_file_serving`.

    A prefix matching more than one task is an error rather than a guess: the
    alternative is collecting trials for the wrong task and reporting the run as
    complete.
    """
    if token in known:
        return token
    matches = [t for t in known if t.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"task id {token!r} is ambiguous: it matches {', '.join(matches)}; "
            "use more of the id"
        )
    raise ValueError(
        f"unknown task id {token!r}; available: {', '.join(known)}"
    )


def parse_task_filter(value: str | None, tasks_dir: Path | None = None) -> tuple[str, ...]:
    """Validate `--tasks` against the corpus before any spend.

    A typo'd task id must be a configuration error here, not a run that silently
    collects fewer trials than the operator asked for and reports it as complete.
    """
    requested = [part.strip() for part in (value or "").split(",") if part.strip()]
    if not requested:
        return ()
    known = discover_task_ids(tasks_dir)
    resolved: list[str] = []
    for token in requested:
        task_id = _resolve_task_id(token, known)
        if task_id not in resolved:
            resolved.append(task_id)
    # Corpus order rather than the order typed, so two invocations naming the same
    # tasks produce the same plan and therefore the same run order.
    return tuple(t for t in known if t in set(resolved))


def parse_conditions(value: str | None) -> tuple[str, ...]:
    """Validate `--conditions` against the three defined conditions."""
    requested = [part.strip() for part in (value or "").split(",") if part.strip()]
    if not requested:
        return ()
    unknown = [c for c in requested if c not in CONDITIONS]
    if unknown:
        raise ValueError(
            f"unknown condition(s) {', '.join(sorted(set(unknown)))}; "
            f"supported: {', '.join(CONDITIONS)}"
        )
    # Normalise to CONDITIONS order so the run order is fixed by the design.
    return tuple(c for c in CONDITIONS if c in set(requested))


def plan(
    config: Config | None = None,
    tasks_dir: Path | None = None,
    conditions: tuple[str, ...] = CONDITIONS,
    task_filter: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Compute the trial plan. Pure: no model, no sandbox, no writes."""
    cfg = config or load_config()
    task_ids = discover_task_ids(tasks_dir)
    if task_filter:
        task_ids = [t for t in task_ids if t in set(task_filter)]
    conditions = tuple(c for c in CONDITIONS if c in set(conditions)) or CONDITIONS
    n_tasks = len(task_ids)
    replicates = max(1, cfg.experiment.n_trials)
    trials = n_tasks * len(conditions) * replicates

    per_trial = metrics.estimate_cost_usd(
        ESTIMATED_TOKENS_IN, ESTIMATED_TOKENS_OUT, *cfg.model.pricing()
    )
    estimate = per_trial * trials
    return {
        "tasks": n_tasks,
        "task_ids": task_ids,
        "conditions": list(conditions),
        "trials_per_task": replicates,
        "trials": trials,
        "cost_estimate_usd": round(estimate, 4),
        "max_cost_usd": cfg.experiment.max_cost_usd,
        "within_budget": estimate <= cfg.experiment.max_cost_usd,
        "provider": cfg.model.provider,
        "synthetic": is_synthetic(cfg),
    }


@dataclass(frozen=True)
class TrialKey:
    """One cell of the design matrix: a task, a condition, and a replicate index.

    `trial_index` is part of the identity, not a detail. Without it, replicates of
    the same (task, condition) collide: resume would consider the second replicate
    already done, and the paired contrast would keep only the last replicate per
    task. Both are silent data loss.
    """

    task_id: str
    condition: str
    trial_index: int = 0

    def as_tuple(self) -> tuple[str, str, int]:
        return (self.task_id, self.condition, self.trial_index)

    def as_label(self) -> str:
        suffix = "" if self.trial_index == 0 else f"#{self.trial_index}"
        return f"{self.condition}/{self.task_id}{suffix}"


def _completed_keys(log_path: Path) -> set[tuple[str, str, int]]:
    """Trial keys whose work is genuinely finished, i.e. that were *graded*.

    An ungraded trial -- a rate limit, a provider outage, a suite that never ran --
    is deliberately excluded, so resume retries it. Only a measured trial counts as
    done.

    A malformed trailing line is ignored rather than aborting the resume: a crash
    mid-write is expected, not exceptional.
    """
    keys: set[tuple[str, str, int]] = set()
    if not log_path.exists():
        return keys
    for record in read_trial_records(log_path):
        # `graded` absent means this log predates the field; a record that says
        # nothing about grading is treated as done rather than re-run forever.
        if record.get("graded", True) is False:
            continue
        keys.add(_key_of(record).as_tuple())
    return keys


def _key_of(record: dict[str, Any]) -> TrialKey:
    return TrialKey(
        task_id=str(record.get("task_id", "")),
        condition=str(record.get("condition", "")),
        trial_index=int(record.get("trial_index", 0) or 0),
    )


def read_trial_records(log_path: Path) -> list[dict[str, Any]]:
    """Parse a trial log, skipping unreadable lines."""
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _work_order(
    plan_result: dict[str, Any],
    conditions: tuple[str, ...],
    replicates: int,
    done: set[tuple[str, str, int]],
) -> list[TrialKey]:
    """Every cell to run, ungraded-and-retryable ones first.

    A trial that failed for a transient reason (a rate limit, a provider blip) is
    the most valuable one to re-run: it is the cheapest missing measurement to
    recover. Graded trials are skipped entirely. Ordering is otherwise the design
    order, so a fresh run is reproducible.

    The result is what makes the dry run honest: it is the same list that the
    non-dry run iterates, so `--dry-run` cannot describe a different run.
    """
    order: list[TrialKey] = []
    for task_id in plan_result["task_ids"]:
        for condition in conditions:
            for index in range(replicates):
                key = TrialKey(task_id, condition, index)
                if key.as_tuple() not in done:
                    order.append(key)
    return order


def _build_condition(name: str, model: Any, workdir: Path | None, ablation: str | None):
    if name == "a":
        return ConditionA(model, workdir)
    if name == "b":
        return ConditionB(model, workdir)
    if name == "c":
        ablate = [a for a in (ablation or "").split(",") if a]
        return ConditionC(model, workdir, ablate=ablate)
    raise ValueError(f"unknown condition {name!r}; expected one of {CONDITIONS}")


#: Ungraded reasons that are worth re-running immediately on resume: the
#: measurement is missing because of a transient condition, not because the trial
#: was bad. A grade that failed because the suite never ran is in this class too.
RETRYABLE_UNGRADED_REASONS = ("rate_limited", "provider_error", "unreachable")


def _retry_first(log_path: Path) -> list[TrialKey]:
    """Keys from previous runs that failed transiently and should be retried.

    Ordered before everything else so a resume spends its budget recovering the
    measurements that are missing rather than collecting new ones.
    """
    if not log_path.exists():
        return []
    retriable: list[TrialKey] = []
    for record in read_trial_records(log_path):
        if record.get("graded", True) is not False:
            continue
        reason = str(record.get("ungraded_reason_code", ""))
        if reason in RETRYABLE_UNGRADED_REASONS:
            key = _key_of(record)
            if key not in retriable:
                retriable.append(key)
    return retriable


def run(
    config: Config | None = None,
    run_id: str = "study1",
    conditions: tuple[str, ...] = CONDITIONS,
    tasks_dir: Path | None = None,
    dry_run: bool = False,
    resume: bool = True,
    timeout: int | None = None,
    task_filter: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute the study-1 trial matrix.

    Returns a summary dict. In dry_run mode nothing is executed, no model is
    called and no log is written; the exact list of trials that *would* run is
    returned instead, so the dry run describes the real run rather than a
    plausible-looking substitute.

    Every trial that produces code is graded against the task's hidden suite in
    the sandbox. `timeout` bounds each sandbox run (grading and guardrails).
    """
    cfg = config or load_config()
    timeout = timeout or max(cfg.sandbox.timeout_s, 120)
    planned = plan(cfg, tasks_dir, conditions=conditions, task_filter=task_filter)
    if not planned["within_budget"]:
        raise BudgetExceeded(
            f"plan costs ${planned['cost_estimate_usd']:.4f}, "
            f"over the ${planned['max_cost_usd']:.2f} cap; raise MAX_COST_USD or reduce trials"
        )

    base = REPO_ROOT
    log_dir = base / "results" / run_id
    log_path = log_dir / "trials.jsonl"
    done = _completed_keys(log_path) if resume else set()
    replicates = max(1, cfg.experiment.n_trials)

    # Cells to run, retryable failures first. Computed before the credential check
    # so the dry run works with no key set at all.
    order = _work_order(planned, tuple(planned["conditions"]), replicates, done)
    retried_first = _retry_first(log_path) if (resume and not dry_run) else []
    if retried_first:
        still_pending = {k.as_tuple() for k in order}
        lead_in = [k for k in retried_first if k.as_tuple() in still_pending]
        order = lead_in + [k for k in order if k.as_tuple() not in {x.as_tuple() for x in lead_in}]

    if dry_run:
        return {
            "run_id": run_id,
            "dry_run": True,
            "executed": 0,
            "skipped": len(done),
            "failed": 0,
            "ungraded": 0,
            "retried_first": 0,
            "planned_trials": len(order),
            "planned_order": [k.as_label() for k in order],
            "planned": planned["trials"],
            "cost_estimate_usd": planned["cost_estimate_usd"],
            "within_budget": planned["within_budget"],
            "max_cost_usd": cfg.experiment.max_cost_usd,
            "provider": planned["provider"],
            "spent_usd": 0.0,
            "synthetic": planned["synthetic"],
            "log": str(log_path),
        }

    # Provenance is derived, never asserted. This used to be hardcoded, so a real
    # provider run and a mock run were indistinguishable in the artefacts.
    synthetic = is_synthetic(cfg)
    price_in, price_out = cfg.model.pricing()

    # A missing credential is not a per-trial failure: nothing can be generated at
    # all, so fail closed and refuse before any spend or any trial record.
    # Construction refuses a non-official base URL here, before any trial and at
    # zero cost, unless the operator passed --allow-custom-base-url.
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
    skipped = len(done)
    failed = 0
    ungraded = 0
    spent = 0.0

    # Provenance is snapshotted per trial, not once per run: `returned_model_id`
    # only exists after a call has happened, and condition C makes several. Reset
    # before each trial so a trial's record describes that trial, not every
    # earlier one in the run.
    for key in order:
        task_id, condition, trial_index = key.as_tuple()
        task_path = Path(tasks_dir or TASKS_DIR) / task_id

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
                f"${spent:.4f}; stopping before {key.as_label()}"
            )

        if hasattr(model, "reset_provenance"):
            model.reset_provenance()  # type: ignore[attr-defined]

        # Condition C writes its solution through a WriteAuthority, so the
        # workdir must be a per-trial scratch copy -- never the task itself.
        # Handing it tasks/<id>/ would let a run mutate the graded corpus,
        # which is both an integrity problem and a way to contaminate a
        # later validation. The replicate index keeps replicates apart.
        workspace = _stage_workspace(run_id, task_path, condition, trial_index)
        ctx = load_task_context(task_path)
        trial = _build_condition(condition, model, workspace, cfg.experiment.ablation)

        # A provider outage or a malformed response must not destroy the other
        # trials. Record the trial as explicitly ungraded and continue:
        # analyze() counts ungraded trials separately and never folds them
        # into a measured zero. Recording nothing would lose the resume point
        # and re-run the trial; recording a score would fabricate a result.
        #
        # A rate-limited trial carries `ungraded_reason_code: rate_limited` so a
        # resume can find it and retry it first. It is emphatically NOT recorded
        # as a failure or a zero score.
        try:
            result = trial.run(ctx)
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            failed += 1
            ungraded += 1
            code = getattr(exc, "reason", "condition_error")
            logger.log_trial(
                {
                    "task_id": task_id,
                    "condition": condition,
                    "trial_index": trial_index,
                    "iterations": 0,
                    "guardrail_rounds": 0,
                    "ablated": [],
                    "rejected_writes": [],
                    **UNGRADED_METRICS,
                    "grade_exit_class": "not_graded",
                    "ungraded_reason": f"{type(exc).__name__}: {redact(str(exc), secret)}",
                    "ungraded_reason_code": code,
                    "retryable": code in RETRYABLE_UNGRADED_REASONS,
                    "provenance": _provenance_of(model),
                    "synthetic": synthetic,
                }
            )
            continue

        logger.log_trial(
            {
                "task_id": result.task_id,
                "condition": result.condition,
                "trial_index": trial_index,
                "iterations": result.iterations,
                "guardrail_rounds": result.guardrail_rounds,
                "ablated": result.ablated,
                "rejected_writes": result.rejected_writes,
                **grade_trial(task_path, workspace, result.final_code, timeout=timeout),
                "provenance": _provenance_of(model),
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
        "ungraded": ungraded,
        "retried_first": len(retried_first),
        "planned": planned["trials"],
        "planned_trials": len(order),
        "planned_order": [k.as_label() for k in order],
        "cost_estimate_usd": planned["cost_estimate_usd"],
        "within_budget": planned["within_budget"],
        "spent_usd": round(spent, 4),
        "max_cost_usd": cfg.experiment.max_cost_usd,
        "provider": cfg.model.provider,
        "dry_run": dry_run,
        "synthetic": synthetic,
        "log": str(log_path),
    }


def _provenance_of(model: Any) -> dict[str, Any]:
    """The per-trial provenance record, or an explicit 'unavailable'.

    Never fabricated: if the model cannot report it, the trial says so rather than
    inheriting the requested model id as though it were confirmed.
    """
    provenance = getattr(model, "provenance", None)
    if callable(provenance):
        try:
            return dict(provenance())
        except Exception:  # noqa: BLE001 - provenance must never lose a trial
            return {"error": "provenance unavailable"}
    return {
        "provider": getattr(model, "provider", "unknown"),
        "base_url_host": None,
        "requested_model_id": None,
        "returned_model_id": None,
        "note": "model does not report provenance",
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


def _stage_workspace(
    run_id: str, task_path: Path, condition: str, trial_index: int = 0
) -> Path:
    """Copy a task into a scratch workspace for one trial.

    The copy is what the condition writes into. `hidden_tests` is deliberately
    not copied: no condition needs it, and leaving it out means a workspace
    cannot leak the graded suite into a prompt or a repair loop.

    The replicate index is in the directory name. Without it, replicate 2 of a
    (task, condition) reuses replicate 1's workspace, and any file the first
    replicate left behind is visible to the second -- so replicates stop being
    independent.
    """
    suffix = "" if trial_index == 0 else f"__{trial_index}"
    workspace = REPO_ROOT / "results" / run_id / "work" / f"{task_path.name}__{condition}{suffix}"
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
    records = load_trials(run_id)
    out_dir = Path(output_dir or (REPO_ROOT / "results" / run_id / "analysis"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # A retried trial appears twice in the log: the ungraded attempt and the
    # graded one. Only the latest record per (task, condition, trial_index)
    # counts, so a recovery does not inflate n and a later attempt is not
    # shadowed by the failure that preceded it.
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for record in records:
        latest[_key_of(record).as_tuple()] = record
    trials = list(latest.values())

    # A trial that could not be graded carries hidden_pass_rate 0.0, which is
    # indistinguishable from a trial that genuinely scored zero. Averaging it in
    # would turn a measurement failure into a result, so statistics are built
    # from graded trials only and the ungraded ones are counted and reported.
    graded = [t for t in trials if t.get("graded", True)]
    ungraded = [t for t in trials if not t.get("graded", True)]
    # The same vocabulary as `attrition_by_condition`: the stable reason *code*
    # first, free text only as a fallback. Using exception text here and codes in
    # the attrition table below would print two names for one cause in one report.
    ungraded_reasons = sorted(
        str(t.get("ungraded_reason_code") or t.get("grade_reason") or "no reason recorded")
        for t in ungraded
    )

    by_condition: dict[str, list[dict[str, Any]]] = {}
    for record in graded:
        by_condition.setdefault(record.get("condition", "unknown"), []).append(record)

    condition_stats = {
        name: metrics.aggregate_trials(records) for name, records in by_condition.items()
    }

    attrition = attrition_by_condition(trials)
    contrasts: dict[str, Any] = {}
    if "b" in by_condition and "c" in by_condition:
        # Fed *every* trial for b and c, not just the graded ones. Pairing has to
        # see the missing cells to count them: passed only graded records, a cell
        # ungraded in b looks identical to a cell that was never run, and the
        # report would state "0 pairs dropped" while silently dropping one.
        b_records = [t for t in trials if t.get("condition") == "b"]
        c_records = [t for t in trials if t.get("condition") == "c"]
        pairs = _aligned(b_records, c_records)
        if pairs:
            contrasts["c_minus_b_hidden_pass_rate"] = {
                **stats.analyze_condition_contrast(pairs["c"], pairs["b"]),
                "pairing": pairs["pairing"],
            }

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
        # Derived from the trial records, not asserted. A run log with no
        # `synthetic` field at all predates the field; treat that as unverified
        # rather than silently reporting the mock provenance for real data.
        "synthetic": _is_synthetic_records(trials),
        "attrition": attrition,
        "by_condition": condition_stats,
        "contrasts": contrasts,
        "mixed_effects": mixed,
        "provenance": summarise_provenance(trials),
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


def _is_synthetic_records(trials: list[dict[str, Any]]) -> bool:
    """Whether these records came from a synthetic (mock) model.

    `any` over the recorded flags, so a single real-provider trial in an otherwise
    mock run reports False. Defaulting to True when no trial recorded the flag
    would stamp "synthetic" onto data of unknown origin.
    """
    if not trials:
        return True
    return all(t.get("synthetic", False) for t in trials)


def attrition_by_condition(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """n_graded and n_ungraded per condition and per task, with reasons.

    Attrition is a threat to validity, not a footnote: if condition C loses
    30% of its trials to rate limits and condition B loses 2%, the contrast is
    between two different subsets of the corpus and the difference in means is
    partly a difference in what survived. So the counts are reported per
    condition and per task, and an imbalance above the threshold is raised above
    the results table rather than in a footnote.
    """
    by_condition: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    by_condition_task: dict[str, dict[str, dict[str, int]]] = {}

    for record in trials:
        is_graded = bool(record.get("graded", True))
        condition = str(record.get("condition", "unknown"))
        task_id = str(record.get("task_id", "unknown"))
        reason = (
            "graded"
            if is_graded
            else str(
                record.get("ungraded_reason_code")
                or record.get("grade_reason")
                or "ungraded"
            )
        )

        for bucket, key in ((by_condition, condition), (by_task, task_id)):
            entry = bucket.setdefault(key, {"n_total": 0, "n_graded": 0, "n_ungraded": 0,
                                            "reasons": {}})
            entry["n_total"] += 1
            entry["n_graded" if is_graded else "n_ungraded"] += 1
            # `reasons` records why trials were *lost*. A graded trial is not a
            # reason, so it is counted in n_graded and left out here -- mixing the
            # two would make the column unreadable.
            if not is_graded:
                entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1

        cell = by_condition_task.setdefault(condition, {}).setdefault(
            task_id, {"n_total": 0, "n_graded": 0, "n_ungraded": 0}
        )
        cell["n_total"] += 1
        cell["n_graded" if is_graded else "n_ungraded"] += 1

    # Imbalance is measured in attrition *points*: the spread of the ungraded
    # share across conditions. Compared on the raw count it would flag a big run
    # with equal rates and miss a small run with a badly skewed one.
    rates = {
        name: (entry["n_ungraded"] / entry["n_total"]) if entry["n_total"] else 0.0
        for name, entry in by_condition.items()
    }
    spread = (max(rates.values()) - min(rates.values())) if len(rates) > 1 else 0.0
    worst = max(rates, key=lambda k: rates[k]) if rates else None

    return {
        "by_condition": by_condition,
        "by_task": by_task,
        "by_condition_task": by_condition_task,
        "attrition_rate_by_condition": {k: round(v, 4) for k, v in sorted(rates.items())},
        "imbalance_points": round(spread * 100.0, 2),
        "imbalanced": bool(
            len(rates) > 1
            and spread * 100.0 > ATTRITION_IMBALANCE_POINTS
        ),
        "worst_condition": worst if spread * 100.0 > ATTRITION_IMBALANCE_POINTS else None,
        "threshold_points": ATTRITION_IMBALANCE_POINTS,
    }


def summarise_provenance(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """What actually answered: provider, host, requested and returned model ids.

    Collapsed across trials because a run normally uses one of each, and a run
    that does not is exactly the thing a reader needs to see. Any disagreement
    between requested and returned ids is surfaced as a list rather than hidden,
    since a silent alias means the results describe a different model than the one
    the study names.
    """
    providers: set[str] = set()
    hosts: set[str] = set()
    requested: set[str] = set()
    returned: set[str] = set()
    custom_base_url = False
    total_retries = 0
    missing_returned = 0

    for record in trials:
        prov = record.get("provenance") or {}
        if not isinstance(prov, dict):
            continue
        if prov.get("provider"):
            providers.add(str(prov["provider"]))
        if prov.get("base_url_host"):
            hosts.add(str(prov["base_url_host"]))
        if prov.get("requested_model_id"):
            requested.add(str(prov["requested_model_id"]))
        if prov.get("returned_model_id"):
            returned.add(str(prov["returned_model_id"]))
        else:
            missing_returned += 1
        if prov.get("allow_custom_base_url"):
            custom_base_url = True
        total_retries += int(prov.get("retries", 0) or 0)

    mismatch = sorted(returned - requested)
    return {
        "providers": sorted(providers),
        "base_url_hosts": sorted(hosts),
        "requested_model_ids": sorted(requested),
        "returned_model_ids": sorted(returned),
        "model_id_mismatch": mismatch,
        "custom_base_url": custom_base_url,
        "total_retries": total_retries,
        "trials_without_returned_model_id": missing_returned,
    }


def _aligned(b_records: list[dict], c_records: list[dict]) -> dict[str, Any] | None:
    """Pair b and c results by (task_id, trial_index) so the contrast is paired.

    Only cells graded in *both* conditions form a pair. A pair dropped because one
    side is missing is counted and named, never quietly discarded: the headline
    comparison is over the surviving pairs, and the report says how many that was.

    Keying on task_id alone (as this once did) would keep only the last replicate
    per task, because a dict comprehension overwrites on duplicate keys. The
    replicate index is what makes the pairing correct.
    """
    # Only graded cells can supply a value. Ungraded ones are kept aside so the
    # dropped counts below can distinguish "missing measurement" from "never run".
    def _graded(records: list[dict[str, Any]]) -> dict[tuple[str, int], float]:
        return {
            _pair_key(r): float(r.get("hidden_pass_rate", 0.0))
            for r in records
            if r.get("graded", True)
        }

    b_all = {_pair_key(r) for r in b_records}
    c_all = {_pair_key(r) for r in c_records}
    b_by_cell = _graded(b_records)
    c_by_cell = _graded(c_records)
    shared = sorted(set(b_by_cell) & set(c_by_cell))
    if not shared:
        return None
    # A cell absent from one condition's graded set was either ungraded there or
    # never run there. Both drop the pair; reporting them separately is what makes
    # the attrition visible instead of looking like a smaller study.
    b_only = sorted(set(b_all) - set(c_all) - set(c_by_cell))
    c_only = sorted(set(c_all) - set(b_all) - set(b_by_cell))
    b_ungraded = sorted((set(b_all) - set(b_by_cell)) & set(c_all))
    c_ungraded = sorted((set(c_all) - set(c_by_cell)) & set(b_all))
    return {
        "b": [b_by_cell[cell] for cell in shared],
        "c": [c_by_cell[cell] for cell in shared],
        "pairing": {
            "key": "(task_id, trial_index)",
            "n_pairs": len(shared),
            "n_dropped": len(b_only) + len(c_only) + len(b_ungraded) + len(c_ungraded),
            "n_b_ungraded": len(b_ungraded),
            "n_c_ungraded": len(c_ungraded),
            "n_b_missing": len(b_only),
            "n_c_missing": len(c_only),
            "dropped_b_ungraded": [list(c) for c in b_ungraded],
            "dropped_c_ungraded": [list(c) for c in c_ungraded],
            "dropped_b_missing": [list(c) for c in b_only],
            "dropped_c_missing": [list(c) for c in c_only],
            "note": (
                "pairs are (task_id, trial_index) cells graded in BOTH conditions; "
                f"{len(b_ungraded)} ungraded in b and {len(c_ungraded)} ungraded in c were "
                "dropped because one side has no measurement"
            ),
        },
    }


def _pair_key(record: dict[str, Any]) -> tuple[str, int]:
    return (
        str(record.get("task_id", "")),
        int(record.get("trial_index", 0) or 0),
    )


__all__ = [
    "BudgetExceeded",
    "TrialResult",
    "analyze",
    "discover_task_ids",
    "load_trials",
    "plan",
    "run",
]
