"""Figures for study 1.

Every figure carries the "synthetic data, pipeline test only" watermark when
the data is synthetic. docs/reproducing.md requires that any figure or table
generated from synthetic data be clearly labelled; the watermark is drawn on
the canvas so it cannot be cropped out unnoticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless; no display required in CI
import matplotlib.pyplot as plt  # noqa: E402

WATERMARK = "synthetic data, pipeline test only"


def _is_synthetic(analysis: dict[str, Any]) -> bool:
    return bool(analysis.get("synthetic", True))


def _stamp(fig: plt.Figure, synthetic: bool) -> None:
    if not synthetic:
        return
    fig.text(
        0.5,
        0.5,
        WATERMARK,
        ha="center",
        va="center",
        fontsize=28,
        color="red",
        alpha=0.25,
        rotation=30,
        zorder=100,
    )


def _finish(fig: plt.Figure, path: Path, synthetic: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _stamp(fig, synthetic)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_outcomes_by_condition(
    values_by_condition: dict[str, list[float]],
    path: Path,
    synthetic: bool = True,
    ylabel: str = "hidden_pass_rate",
) -> Path:
    """Bar chart of the mean outcome per condition, with error bars."""
    names = list(values_by_condition)
    means = [sum(v) / len(v) if v else 0.0 for v in values_by_condition.values()]
    errors = [
        (metrics_sd(values_by_condition[n]) if values_by_condition[n] else 0.0) for n in names
    ]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(names, means, yerr=errors, capsize=5, color="#4C72B0", alpha=0.85)
    ax.set_ylabel(ylabel)
    ax.set_title("Outcome by condition")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, Path(path), synthetic)


def plot_effect_size_ci(
    effect: dict[str, Any],
    path: Path,
    synthetic: bool = True,
) -> Path:
    """Effect size with its bootstrap CI as a horizontal error bar."""
    mean_diff = effect.get("mean_diff", 0.0)
    lo = effect.get("ci_low", 0.0)
    hi = effect.get("ci_high", 0.0)

    fig, ax = plt.subplots(figsize=(7, 2.6))
    ax.errorbar(
        mean_diff,
        0,
        xerr=[[mean_diff - lo], [hi - mean_diff]],
        fmt="o",
        capsize=6,
        color="#C44E52",
    )
    ax.axvline(0.0, linestyle="--", color="grey", linewidth=1)
    ax.set_yticks([])
    ax.set_xlabel("paired mean difference (95% bootstrap CI)")
    ax.set_title("Effect size")
    return _finish(fig, Path(path), synthetic)


def plot_defect_histogram(
    defects_by_condition: dict[str, list[int]],
    path: Path,
    synthetic: bool = True,
) -> Path:
    """Overlaid defect-count histograms per condition."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for name, values in defects_by_condition.items():
        ax.hist(values, bins=range(0, max(values + [1]) + 2), alpha=0.5, label=name)
    ax.set_xlabel("defect_count")
    ax.set_ylabel("trials")
    ax.set_title("Defects per trial")
    ax.legend()
    return _finish(fig, Path(path), synthetic)


def metrics_sd(values: list[float]) -> float:
    """Sample standard deviation; 0.0 for <2 values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return float(variance**0.5)
