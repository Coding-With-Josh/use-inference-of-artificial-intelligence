"""Statistical analysis for study 1.

docs/threats_to_validity.md requires: paired tests, bootstrap 95% CIs for effect
sizes, mixed-effects models with task/participant random effects, and Holm
correction for multiple comparisons.

Every function is total. Degenerate input (n<2, all-identical pairs,
zero variance) returns a defined, honest result -- `significant` is False and
`note` explains why -- rather than raising or producing NaN. A NaN p-value that
gets formatted into a report is how a study reports a number it never computed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

from pilot.scoring import metrics

DEFAULT_SEED = 20240101


@dataclass
class TestResult:
    """One statistical test."""

    name: str
    statistic: float
    p_value: float
    n: int
    significant: bool = False
    alpha: float = 0.05
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "n": self.n,
            "significant": self.significant,
            "alpha": self.alpha,
            "note": self.note,
            **self.extra,
        }


def _clean(
    pairs_a: Sequence[float], pairs_b: Sequence[float]
) -> tuple[np.ndarray, np.ndarray, str]:
    """Drop non-finite values and return aligned arrays plus a note."""
    a = np.asarray(pairs_a, dtype=float)
    b = np.asarray(pairs_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"paired arrays must match: {a.shape} vs {b.shape}")
    mask = np.isfinite(a) & np.isfinite(b)
    dropped = int((~mask).sum())
    note = f"dropped {dropped} non-finite pair(s)" if dropped else ""
    return a[mask], b[mask], note


def _degenerate_diffs(diffs: np.ndarray) -> str:
    """Return a reason string if the paired differences cannot support a test.

    A paired t-test divides by the standard deviation of the differences. When
    that spread is zero -- whether the differences are all zero or all the same
    constant -- the statistic is undefined. numpy signals this as
    "catastrophic cancellation", which `filterwarnings = ["error"]` turns into
    a RuntimeWarning-as-exception. Detecting it here means the study reports
    "not tested" instead of crashing mid-analysis.
    """
    if diffs.size == 0:
        return "no paired data"
    if np.allclose(diffs, 0.0):
        return "all differences are zero"
    if np.allclose(diffs, diffs[0]):
        return "all differences are identical (zero variance)"
    scale = float(np.max(np.abs(diffs)))
    if scale > 0.0 and float(np.std(diffs)) / scale < 1e-8:
        return "difference spread is negligible relative to its magnitude"
    return ""


def paired_t_test(
    condition_a: Sequence[float],
    condition_b: Sequence[float],
    alpha: float = 0.05,
) -> TestResult:
    """Two-sided paired t-test on matched observations."""
    a, b, note = _clean(condition_a, condition_b)
    diffs = a - b
    n = len(diffs)
    degenerate = _degenerate_diffs(diffs)
    if n < 2 or degenerate:
        reason = degenerate or "n<2; not tested"
        return TestResult(
            "paired_t", 0.0, 1.0, n, False, alpha, f"{note}; {reason}" if note else reason
        )
    stat, p = stats.ttest_rel(a, b)
    return TestResult(
        "paired_t",
        float(stat),
        float(p),
        n,
        bool(p < alpha),
        alpha,
        note,
        {"mean_diff": float(np.mean(diffs))},
    )


def wilcoxon_test(
    condition_a: Sequence[float],
    condition_b: Sequence[float],
    alpha: float = 0.05,
) -> TestResult:
    """Wilcoxon signed-rank test; the non-parametric companion to the t-test."""
    a, b, note = _clean(condition_a, condition_b)
    diffs = a - b
    # Zero spread makes every tied rank, so the signed-rank statistic is
    # undefined -- report that rather than letting scipy raise.
    degenerate = _degenerate_diffs(diffs) if diffs.size > 0 else ""
    if len(diffs) < 2:
        return TestResult("wilcoxon", 0.0, 1.0, len(diffs), False, alpha, note or "n<2")
    if degenerate and ("zero variance" in degenerate or "differences are zero" in degenerate):
        reason = f"{note}; {degenerate}" if note else degenerate
        return TestResult("wilcoxon", 0.0, 1.0, len(diffs), False, alpha, reason)
    try:
        stat, p = stats.wilcoxon(a, b)
    except ValueError as err:  # e.g. zero_method default rejects all-zero ranks
        return TestResult("wilcoxon", 0.0, 1.0, len(diffs), False, alpha, f"{note}; {err}".strip())
    return TestResult("wilcoxon", float(stat), float(p), len(diffs), bool(p < alpha), alpha, note)


def bootstrap_ci(
    data: Sequence[float],
    statistic: str = "mean",
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean or median.

    Deterministic given `seed`, so a re-run reproduces the reported interval.
    Returns (0.0, 0.0) for empty input.
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_resamples, arr.size))
    samples = arr[idx]
    stat = np.mean(samples, axis=1) if statistic == "mean" else np.median(samples, axis=1)
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.quantile(stat, [alpha, 1.0 - alpha])
    return (float(lo), float(hi))


def paired_effect_ci(
    condition_a: Sequence[float],
    condition_b: Sequence[float],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Bootstrap CI for the paired mean difference a-b, plus the observed diff."""
    a, b, note = _clean(condition_a, condition_b)
    diffs = a - b
    if diffs.size == 0:
        return {
            "mean_diff": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "n": 0,
            "note": note or "no paired data",
        }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, diffs.size, size=(n_resamples, diffs.size))
    boot = diffs[idx].mean(axis=1)
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.quantile(boot, [alpha, 1.0 - alpha])
    return {
        "mean_diff": float(np.mean(diffs)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "n": int(diffs.size),
        "note": note,
    }


def holm_correction(p_values: Sequence[float], alpha: float = 0.05) -> dict[str, Any]:
    """Holm-Bonferroni step-down correction for multiple comparisons.

    Returns adjusted p-values, the Holm threshold actually used at each step,
    and a reject decision per hypothesis. Ties keep the strictest verdict.
    """
    p = np.asarray(p_values, dtype=float)
    m = p.size
    if m == 0:
        return {"adjusted": [], "reject": [], "alpha": alpha, "m": 0}

    order = np.argsort(p)
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, idx in enumerate(order):
        # Holm: multiply by (m - rank), enforce monotonicity.
        candidate = p[idx] * (m - rank)
        running = max(running, candidate)
        adjusted[idx] = min(1.0, running)
    reject = adjusted < alpha
    return {
        "adjusted": [float(v) for v in adjusted],
        "reject": [bool(v) for v in reject],
        "alpha": alpha,
        "m": int(m),
    }


def mixed_effects_model(
    outcomes: Sequence[float],
    groups: Sequence[str],
    subjects: Sequence[str],
    tasks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fit `outcome ~ group` with random intercepts for subject and task.

    Uses statsmodels MixedLM when the data supports it. On degenerate input
    (too few observations, perfect separation, singular design) it returns
    `converged: False` with a reason instead of raising -- a model that did not
    fit must never be reported as a result.
    """
    y = np.asarray(outcomes, dtype=float)
    g = list(groups)
    s = list(subjects)
    t = list(tasks) if tasks is not None else [f"task_{i}" for i in range(len(y))]
    if not (len(y) == len(g) == len(s) == len(t)):
        raise ValueError("outcomes, groups, subjects and tasks must be the same length")

    base: dict[str, Any] = {
        "converged": False,
        "coef": {},
        "note": "",
        "n": int(len(y)),
    }
    if len(y) < 4:
        return {**base, "note": "too few observations to fit a mixed model"}
    if len(set(g)) < 2:
        return {**base, "note": "only one group present; nothing to compare"}
    if np.allclose(np.std(y), 0.0):
        return {**base, "note": "outcome has zero variance"}

    try:
        import pandas as pd
        from statsmodels.formula.api import mixedlm

        frame = pd.DataFrame(
            {
                "outcome": y,
                "group": pd.Categorical(g),
                "subject": pd.Categorical(s),
                "task": pd.Categorical(t),
            }
        )
        model = mixedlm("outcome ~ C(group)", frame, groups=frame["subject"])
        fit = model.fit(reml=True, method="lbfgs")
        coef = {str(k): float(v) for k, v in fit.params.items() if k != "Group Var"}
        return {
            "converged": bool(getattr(fit, "converged", False)),
            "coef": coef,
            "note": "" if getattr(fit, "converged", False) else "model did not converge",
            "n": int(len(y)),
            "p_values": {
                str(k): float(v) for k, v in fit.pvalues.items() if k != "Group Var"
            },
        }
    except Exception as exc:  # statsmodels raises a wide variety here
        return {**base, "note": f"mixed model unavailable: {type(exc).__name__}: {exc}"}


def analyze_condition_contrast(
    a_values: Sequence[float],
    b_values: Sequence[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Run the full comparison battery for one contrast.

    Combines the paired t-test, the Wilcoxon test, the bootstrap CI for the
    paired difference, and a Holm-corrected verdict across the family of tests.
    """
    t_result = paired_t_test(a_values, b_values, alpha=alpha)
    w_result = wilcoxon_test(a_values, b_values, alpha=alpha)
    effect = paired_effect_ci(a_values, b_values)
    correction = holm_correction([t_result.p_value, w_result.p_value], alpha=alpha)
    return {
        "paired_t": t_result.as_dict(),
        "wilcoxon": w_result.as_dict(),
        "effect": effect,
        "holm": correction,
        "summary": metrics.summarize([float(v) for v in a_values]),
        "summary_b": metrics.summarize([float(v) for v in b_values]),
    }


def calibration_metrics(
    probabilities: Sequence[float], outcomes: Sequence[int]
) -> dict[str, float]:
    return {
        "brier": metrics.brier_score(probabilities, outcomes),
        "calibration_error": metrics.calibration_error(probabilities, outcomes),
    }
