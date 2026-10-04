"""Tests for the statistical layer.

Emphasis on degenerate input: every function must return an honest, defined
result rather than raising or producing NaN, because a NaN formatted into the
report reads as a number the study never computed.
"""

from __future__ import annotations

import math

import pytest

from pilot.analysis import stats
from pilot.scoring import metrics

# --------------------------------------------------------------------------
# paired t-test / wilcoxon
# --------------------------------------------------------------------------


def test_paired_t_detects_consistent_difference():
    # Differences must vary: a constant difference has zero variance and the
    # t statistic is undefined (see the degenerate-input test below).
    a = [10.0, 12.0, 15.0, 13.0, 20.0, 18.0]
    b = [5.0, 6.0, 8.0, 7.0, 12.0, 11.0]
    result = stats.paired_t_test(a, b)
    assert result.n == 6
    assert result.significant is True
    assert result.p_value < 0.05
    assert result.extra["mean_diff"] == pytest.approx(6.5)


def test_paired_t_on_identical_series_is_not_significant():
    values = [1.0, 2.0, 3.0, 4.0]
    result = stats.paired_t_test(values, values)
    assert result.significant is False
    assert result.p_value == 1.0
    assert "zero" in result.note


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ([], []),
        ([1.0], [2.0]),
    ],
)
def test_paired_t_degenerate_input_is_honest(a, b):
    result = stats.paired_t_test(a, b)
    assert result.significant is False
    assert not math.isnan(result.p_value)
    assert result.note


def test_paired_t_on_constant_nonzero_differences_is_honest():
    """Zero spread, but not zero differences: the t statistic is undefined.

    numpy raises this as catastrophic cancellation, which `filterwarnings =
    ["error"]` escalates to an exception. It must come back as "not tested".
    """
    a = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    b = [9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
    result = stats.paired_t_test(a, b)
    assert result.significant is False
    assert result.p_value == 1.0
    assert "identical" in result.note or "zero variance" in result.note


def test_wilcoxon_on_constant_differences_is_honest():
    a = [10.0, 11.0, 12.0, 13.0]
    b = [9.0, 10.0, 11.0, 12.0]
    result = stats.wilcoxon_test(a, b)
    assert result.significant is False
    assert result.note


def test_paired_t_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="must match"):
        stats.paired_t_test([1.0, 2.0], [1.0])


def test_paired_t_drops_non_finite_and_notes_it():
    result = stats.paired_t_test([1.0, float("nan"), 3.0, 4.0], [0.0, 1.0, 2.0, 3.0])
    assert result.n == 3
    assert "dropped 1" in result.note


def test_wilcoxon_detects_consistent_difference():
    # n=8: with 5 pairs all-same-sign, scipy's exact two-sided p is 2/32=0.0625,
    # which is correct but not < 0.05. Sample size, not the test, is the limit.
    a = [20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0, 34.0]
    b = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    result = stats.wilcoxon_test(a, b)
    assert result.significant is True


def test_wilcoxon_on_all_zero_differences():
    values = [3.0, 4.0]
    result = stats.wilcoxon_test(values, values)
    assert result.significant is False
    assert result.note


def test_wilcoxon_degenerate_input():
    result = stats.wilcoxon_test([1.0], [2.0])
    assert result.significant is False
    assert result.note


# --------------------------------------------------------------------------
# bootstrap
# --------------------------------------------------------------------------


def test_bootstrap_ci_brackets_the_mean():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    lo, hi = stats.bootstrap_ci(data, n_resamples=2000, seed=7)
    assert lo < 3.0 < hi


def test_bootstrap_ci_is_deterministic_for_a_seed():
    data = [1.0, 5.0, 3.0, 9.0]
    first = stats.bootstrap_ci(data, seed=99)
    second = stats.bootstrap_ci(data, seed=99)
    assert first == second


def test_bootstrap_ci_reproduces_its_own_result():
    """A preregistered interval must be re-derivable exactly; that is the seed's job.

    Asserting that *different* seeds give *different* endpoints would be flaky:
    on small discrete samples the 2.5th/97.5th percentiles frequently land on
    the same order statistics for any seed. Determinism is the real requirement.
    """
    data = [1.0, 5.0, 3.0, 9.0, 2.0, 7.0, 4.0, 6.0]
    first = stats.bootstrap_ci(data, seed=1)
    second = stats.bootstrap_ci(data, seed=1)
    assert first == second
    assert stats.bootstrap_ci(data, seed=1) != (0.0, 0.0)


def test_bootstrap_ci_scales_with_confidence():
    data = [1.0, 5.0, 3.0, 9.0, 2.0, 7.0, 4.0, 6.0]
    narrow = stats.bootstrap_ci(data, confidence=0.50, seed=2)
    wide = stats.bootstrap_ci(data, confidence=0.99, seed=2)
    assert (wide[1] - wide[0]) >= (narrow[1] - narrow[0])


def test_bootstrap_ci_empty_is_zero():
    assert stats.bootstrap_ci([]) == (0.0, 0.0)


def test_bootstrap_ci_ignores_non_finite():
    lo, hi = stats.bootstrap_ci([1.0, float("nan"), 3.0], seed=1)
    assert math.isfinite(lo) and math.isfinite(hi)


def test_bootstrap_median_variant():
    lo, hi = stats.bootstrap_ci(
        [1.0, 2.0, 3.0, 100.0], statistic="median", n_resamples=1000, seed=3
    )
    assert lo <= hi


def test_paired_effect_ci_reports_difference_and_width():
    effect = stats.paired_effect_ci([5.0, 6.0, 7.0], [1.0, 2.0, 3.0], n_resamples=1000, seed=5)
    assert effect["mean_diff"] == pytest.approx(4.0)
    assert effect["ci_low"] <= 4.0 <= effect["ci_high"]
    assert effect["n"] == 3


def test_paired_effect_ci_empty_is_honest():
    effect = stats.paired_effect_ci([], [])
    assert effect["n"] == 0
    assert effect["mean_diff"] == 0.0
    assert effect["note"]


# --------------------------------------------------------------------------
# holm correction
# --------------------------------------------------------------------------


def test_holm_matches_hand_computation():
    # p = [.01, .04, .03] -> sorted .01,.03,.04
    # adjusted: .01*3=.03, .03*2=.06, .04*1=.04 -> monotonic: .03,.06,.06
    result = stats.holm_correction([0.01, 0.04, 0.03], alpha=0.05)
    by_p = dict(zip([0.01, 0.04, 0.03], result["adjusted"], strict=True))
    assert by_p[0.01] == pytest.approx(0.03)
    assert by_p[0.03] == pytest.approx(0.06)
    assert by_p[0.04] == pytest.approx(0.06)


def test_holm_is_monotonic_and_never_below_raw():
    p_values = [0.001, 0.008, 0.039, 0.041, 0.9]
    result = stats.holm_correction(p_values)
    ordered = sorted(zip(p_values, result["adjusted"], strict=True))
    for (_, adj_prev), (_, adj_next) in zip(ordered, ordered[1:], strict=False):
        assert adj_next >= adj_prev - 1e-12
    for raw, adj in zip(p_values, result["adjusted"], strict=True):
        assert adj >= raw - 1e-12
        assert adj <= 1.0


def test_holm_rejects_only_what_survives():
    result = stats.holm_correction([0.001, 0.5], alpha=0.05)
    assert result["reject"] == [True, False]


def test_holm_no_comparisons():
    result = stats.holm_correction([])
    assert result == {"adjusted": [], "reject": [], "alpha": 0.05, "m": 0}


def test_holm_single_comparison_unchanged():
    result = stats.holm_correction([0.02], alpha=0.05)
    assert result["adjusted"] == pytest.approx([0.02])
    assert result["reject"] == [True]


# --------------------------------------------------------------------------
# mixed effects
# --------------------------------------------------------------------------


def test_mixed_effects_fits_on_adequate_data():
    outcomes = [0.9, 0.8, 0.7, 0.6, 0.2, 0.1, 0.3, 0.2]
    groups = ["b", "b", "b", "b", "c", "c", "c", "c"]
    subjects = ["p1", "p1", "p2", "p2", "p1", "p1", "p2", "p2"]
    tasks = ["t01", "t02", "t01", "t02", "t01", "t02", "t01", "t02"]
    result = stats.mixed_effects_model(outcomes, groups, subjects, tasks)
    assert result["n"] == 8
    assert "coef" in result
    # Either it converged with coefficients, or it honestly said why not.
    if not result["converged"]:
        assert result["note"]


def test_mixed_effects_too_few_observations():
    result = stats.mixed_effects_model([1.0, 2.0], ["b", "c"], ["p1", "p1"])
    assert result["converged"] is False
    assert "too few" in result["note"]


def test_mixed_effects_single_group():
    result = stats.mixed_effects_model([1.0, 2.0, 3.0, 4.0], ["b"] * 4, ["p1"] * 4)
    assert result["converged"] is False
    assert "one group" in result["note"]


def test_mixed_effects_zero_variance():
    result = stats.mixed_effects_model([1.0] * 6, ["b", "c"] * 3, ["p1", "p2", "p3"] * 2)
    assert result["converged"] is False
    assert "zero variance" in result["note"]


def test_mixed_effects_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        stats.mixed_effects_model([1.0, 2.0], ["b"], ["p1", "p2"])


# --------------------------------------------------------------------------
# composite + calibration
# --------------------------------------------------------------------------


def test_analyze_condition_contrast_shape():
    result = stats.analyze_condition_contrast([5.0, 6.0, 7.0, 8.0], [1.0, 2.0, 3.0, 4.0])
    assert set(result) >= {"paired_t", "wilcoxon", "effect", "holm", "summary"}
    assert result["holm"]["m"] == 2
    assert result["summary"]["n"] == 4


def test_analyze_condition_contrast_on_empty():
    result = stats.analyze_condition_contrast([], [])
    assert result["paired_t"]["significant"] is False
    assert result["effect"]["n"] == 0


def test_calibration_metrics_perfect_and_worst():
    perfect = stats.calibration_metrics([0.0, 1.0], [0, 1])
    assert perfect["brier"] == pytest.approx(0.0)
    worst = stats.calibration_metrics([1.0, 0.0], [0, 1])
    assert worst["brier"] == pytest.approx(1.0)


def test_calibration_metrics_mismatched_lengths():
    assert stats.calibration_metrics([0.5], [0, 1])["brier"] == 0.0


def test_metrics_calibration_error_bounds():
    value = metrics.calibration_error([0.5, 0.5], [0, 1], bins=2)
    assert 0.0 <= value <= 1.0
