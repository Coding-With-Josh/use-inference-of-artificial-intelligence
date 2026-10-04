"""Tests for the scoring metrics in docs/metrics.md.

Empty and partial input must produce a defined value, not an exception or NaN:
a study that collects no data has to report zero trials, not crash.
"""

from __future__ import annotations

import math

import pytest

from pilot.scoring import metrics

# ---------------------------------------------------------------------------
# per-trial outcome metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([True, True, True, True], 1.0),
        ([True, True, False, False], 0.5),
        ([False, False], 0.0),
    ],
)
def test_hidden_pass_rate(results, expected):
    assert metrics.hidden_pass_rate(results) == pytest.approx(expected)


def test_hidden_pass_rate_of_nothing_is_zero():
    assert metrics.hidden_pass_rate([]) == 0.0


def test_task_solved_requires_every_check():
    assert metrics.task_solved([True, True]) == 1
    assert metrics.task_solved([True, False]) == 0
    assert metrics.task_solved([]) == 0


def test_defect_count():
    assert metrics.defect_count([True, False, False]) == 2
    assert metrics.defect_count([]) == 0
    assert metrics.defect_count([True]) == 0


# ---------------------------------------------------------------------------
# descriptive stats
# ---------------------------------------------------------------------------


def test_mean_and_stdev():
    assert metrics.mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert metrics.stdev([1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_mean_and_stdev_of_empty_are_defined():
    assert metrics.mean([]) == 0.0
    assert metrics.stdev([]) == 0.0
    assert metrics.stdev([1.0]) == 0.0


def test_summarize_reports_n_and_extremes():
    summary = metrics.summarize([0.2, 0.4, 0.6])
    assert summary["n"] == 3
    assert summary["mean"] == pytest.approx(0.4)
    assert summary["min"] == pytest.approx(0.2)
    assert summary["max"] == pytest.approx(0.6)


def test_summarize_of_empty_has_no_nan():
    summary = metrics.summarize([])
    assert summary["n"] == 0
    for key in ("mean", "sd", "min", "max"):
        assert not math.isnan(summary[key])


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------


def test_brier_score_perfect_and_worst():
    assert metrics.brier_score([0.0, 1.0], [0, 1]) == pytest.approx(0.0)
    assert metrics.brier_score([1.0, 0.0], [0, 1]) == pytest.approx(1.0)


def test_brier_score_of_mismatched_or_empty_input():
    assert metrics.brier_score([], []) == 0.0
    assert metrics.brier_score([0.5], [0, 1]) == 0.0


def test_calibration_error_is_zero_when_confident_and_correct():
    assert metrics.calibration_error([0.0, 1.0], [0, 1], bins=2) == pytest.approx(0.0)


def test_calibration_error_is_one_when_maximally_wrong():
    value = metrics.calibration_error([1.0, 0.0], [0, 1], bins=2)
    assert value == pytest.approx(1.0)


def test_calibration_error_handles_empty():
    assert metrics.calibration_error([], []) == 0.0


def test_calibration_error_stays_in_range_with_sparse_bins():
    probabilities = [0.02] * 5 + [0.98] * 5
    outcomes = [0] * 5 + [1] * 5
    assert 0.0 <= metrics.calibration_error(probabilities, outcomes, bins=10) <= 1.0


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def test_aggregate_trials_summarizes_records():
    trials = [
        {"hidden_pass_rate": 0.5, "defect_count": 2, "task_solved": 0, "iterations": 1},
        {"hidden_pass_rate": 1.0, "defect_count": 0, "task_solved": 1, "iterations": 3},
    ]
    summary = metrics.aggregate_trials(trials)
    assert summary["n_trials"] == 2
    assert summary["hidden_pass_rate"]["mean"] == pytest.approx(0.75)
    assert summary["task_solved_rate"] == pytest.approx(0.5)
    assert summary["iterations"]["mean"] == pytest.approx(2.0)


def test_aggregate_trials_tolerates_missing_keys():
    summary = metrics.aggregate_trials([{"task_id": "t01"}])
    assert summary["n_trials"] == 1
    assert summary["hidden_pass_rate"]["mean"] == 0.0
    assert summary["task_solved_rate"] == 0.0


def test_aggregate_trials_of_nothing():
    summary = metrics.aggregate_trials([])
    assert summary["n_trials"] == 0
    assert summary["task_solved_rate"] == 0.0


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


def test_cost_estimate_is_zero_without_pricing():
    assert metrics.estimate_cost_usd(1000, 2000, 0.0, 0.0) == 0.0


def test_cost_estimate_combines_both_directions():
    value = metrics.estimate_cost_usd(1_000_000, 1_000_000, 3.0, 15.0)
    assert value == pytest.approx(18.0)


def test_cost_estimate_ignores_unpriced_direction():
    assert metrics.estimate_cost_usd(0, 1_000_000, 0.0, 15.0) == pytest.approx(15.0)
