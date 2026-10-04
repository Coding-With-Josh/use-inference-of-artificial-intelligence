"""Metrics for study 1, per docs/metrics.md.

Every function here is total: empty input yields a defined value rather than
raising or returning NaN, so an empty or partial run produces a report instead
of a crash.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np


def defect_count(results: Iterable[bool]) -> int:
    """Number of failing checks."""
    return sum(1 for r in results if not r)


def task_solved(results: Iterable[bool]) -> int:
    """1 if every check passed, else 0. Empty input is 0 (nothing was solved)."""
    results_list = list(results)
    if not results_list:
        return 0
    return 1 if all(results_list) else 0


def hidden_pass_rate(results: Iterable[bool]) -> float:
    """Fraction of checks passed, 0.0 for empty input."""
    results_list = list(results)
    if not results_list:
        return 0.0
    return sum(1 for r in results_list if r) / float(len(results_list))


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; 0.0 for empty input."""
    return float(np.mean(values)) if len(values) else 0.0


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation; 0.0 for fewer than 2 values."""
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0


def summarize(values: Sequence[float]) -> dict[str, float]:
    """Mean/std/n with counts, safe on empty input."""
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "mean": mean(values),
        "sd": stdev(values),
        "min": float(arr.min()) if arr.size else 0.0,
        "max": float(arr.max()) if arr.size else 0.0,
    }


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    """Brier score for confidence calibration (docs/threats_to_validity.md)."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    return float(np.mean((p - y) ** 2))


def calibration_error(
    probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10
) -> float:
    """Expected calibration error over `bins` equal-width bins."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    n = len(p)
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        mask = (p > lo) & (p <= hi) if lo > 0 else (p >= lo) & (p <= hi)
        if not mask.any():
            continue
        total += (mask.sum() / n) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(total)


def aggregate_trials(trials: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-trial records into the summary stats the report needs.

    Expects each trial dict to carry at least `hidden_pass_rate` and
    `defect_count`; missing keys default to 0.0 so a partial run still reports.
    """
    trials = list(trials)
    pass_rates = [float(t.get("hidden_pass_rate", 0.0)) for t in trials]
    defects = [float(t.get("defect_count", 0.0)) for t in trials]
    solved = [int(bool(t.get("task_solved", 0))) for t in trials]
    iterations = [float(t.get("iterations", 0.0)) for t in trials]

    return {
        "n_trials": len(trials),
        "hidden_pass_rate": summarize(pass_rates),
        "defect_count": summarize(defects),
        "task_solved_rate": (sum(solved) / len(solved)) if solved else 0.0,
        "iterations": summarize(iterations),
    }


def estimate_cost_usd(
    tokens_in: int, tokens_out: int, price_in_per_mtok: float, price_out_per_mtok: float
) -> float:
    """Cost estimate. Returns 0.0 when no pricing is configured."""
    if price_in_per_mtok <= 0 and price_out_per_mtok <= 0:
        return 0.0
    return (tokens_in / 1_000_000) * price_in_per_mtok + (
        tokens_out / 1_000_000
    ) * price_out_per_mtok
