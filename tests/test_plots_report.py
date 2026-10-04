"""Tests for figures and the markdown report.

Both are held to the same rule docs/reproducing.md imposes: anything derived
from synthetic data must say so, and a report over zero trials must say that
rather than rendering an empty results table.
"""

from __future__ import annotations

import pytest

from pilot.analysis import plots, report

WATERMARK = "synthetic data, pipeline test only"


@pytest.fixture
def populated_analysis():
    return {
        "run_id": "demo-mock",
        "n_trials": 4,
        "synthetic": True,
        "seed": 42,
        "by_condition": {
            "b": {
                "n_trials": 2,
                "hidden_pass_rate": {"n": 2, "mean": 0.4, "sd": 0.1, "min": 0.3, "max": 0.5},
            },
            "c": {
                "n_trials": 2,
                "hidden_pass_rate": {"n": 2, "mean": 0.8, "sd": 0.1, "min": 0.7, "max": 0.9},
            },
        },
        "contrasts": {
            "c_minus_b_hidden_pass_rate": {
                "paired_t": {
                    "statistic": 4.0,
                    "p_value": 0.02,
                    "n": 2,
                    "significant": True,
                    "note": "",
                },
                "wilcoxon": {"statistic": 2.0, "p_value": 0.05, "n": 2},
                "effect": {
                    "mean_diff": 0.4,
                    "ci_low": 0.3,
                    "ci_high": 0.5,
                    "n": 2,
                    "note": "",
                },
                "holm": {"adjusted": [0.02, 0.05], "reject": [True, False], "alpha": 0.05, "m": 2},
            }
        },
        "mixed_effects": {"converged": True, "n": 4, "coef": {"Intercept": 0.6}, "note": ""},
        "calibration": {"brier": 0.08, "calibration_error": 0.12},
    }


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------


def test_outcomes_figure_is_written(tmp_path):
    path = plots.plot_outcomes_by_condition({"b": [0.3, 0.5], "c": [0.7, 0.9]}, tmp_path / "o.png")
    assert path.exists()
    assert path.stat().st_size > 0


def test_effect_figure_is_written(tmp_path):
    effect = {"mean_diff": 0.4, "ci_low": 0.3, "ci_high": 0.5}
    assert plots.plot_effect_size_ci(effect, tmp_path / "e.png").exists()


def test_defect_histogram_is_written(tmp_path):
    assert plots.plot_defect_histogram({"b": [1, 2, 3], "c": [0, 1]}, tmp_path / "d.png").exists()


def test_figures_create_missing_parents(tmp_path):
    path = plots.plot_outcomes_by_condition({"b": [1.0]}, tmp_path / "deep" / "nested" / "o.png")
    assert path.exists()


def test_figure_with_empty_condition_does_not_crash(tmp_path):
    assert plots.plot_outcomes_by_condition({"b": [], "c": [1.0]}, tmp_path / "o.png").exists()


def test_defect_histogram_with_all_zero(tmp_path):
    assert plots.plot_defect_histogram({"b": [0, 0, 0]}, tmp_path / "d.png").exists()


def test_stamp_adds_the_watermark_for_synthetic_data():
    from matplotlib import pyplot as plt

    fig, _ = plt.subplots()
    plots._stamp(fig, synthetic=True)
    assert [t.get_text() for t in fig.texts] == [WATERMARK]
    plt.close(fig)


def test_stamp_omits_the_watermark_for_real_data():
    from matplotlib import pyplot as plt

    fig, _ = plt.subplots()
    plots._stamp(fig, synthetic=False)
    assert fig.texts == []
    plt.close(fig)


def test_synthetic_figure_bytes_differ_from_real_figure_bytes(tmp_path):
    """End-to-end: the stamp actually reaches the rendered image."""
    data = {"b": [0.3, 0.5], "c": [0.7, 0.9]}
    synthetic = plots.plot_outcomes_by_condition(data, tmp_path / "syn.png", synthetic=True)
    real = plots.plot_outcomes_by_condition(data, tmp_path / "real.png", synthetic=False)
    assert synthetic.read_bytes() != real.read_bytes()


def test_watermark_constant_matches_report():
    assert plots.WATERMARK == report.WATERMARK == WATERMARK


def test_metrics_sd_handles_short_input():
    assert plots.metrics_sd([]) == 0.0
    assert plots.metrics_sd([1.0]) == 0.0
    assert plots.metrics_sd([1.0, 3.0]) == pytest.approx(2.0**0.5)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_report_states_synthetic_provenance(populated_analysis):
    body = report.render_report(populated_analysis)
    assert WATERMARK in body
    # The sentence is hard-wrapped, so assert on a phrase within one line.
    assert "measurements of any real model" in body


def test_report_omits_watermark_when_not_synthetic(populated_analysis):
    populated_analysis["synthetic"] = False
    body = report.render_report(populated_analysis)
    assert WATERMARK not in body
    assert "- synthetic: False" in body


def test_report_renders_conditions_and_contrasts(populated_analysis):
    body = report.render_report(populated_analysis)
    assert "| b |" in body
    assert "| c |" in body
    assert "c_minus_b_hidden_pass_rate" in body
    assert "paired t" in body
    assert "wilcoxon" in body
    assert "holm-adjusted p" in body


def test_report_says_no_data_rather_than_rendering_zeros():
    body = report.render_report({"synthetic": True, "n_trials": 0})
    assert "## no data" in body
    assert "No trials were recorded" in body
    assert "| condition |" not in body, "an empty table must not look like a result"


def test_report_notes_non_convergence(populated_analysis):
    populated_analysis["mixed_effects"] = {
        "converged": False,
        "n": 4,
        "coef": {},
        "note": "singular random effects",
    }
    body = report.render_report(populated_analysis)
    assert "singular random effects" in body
    assert "converged: False" in body


def test_report_shows_test_note_when_present(populated_analysis):
    contrast = populated_analysis["contrasts"]["c_minus_b_hidden_pass_rate"]
    contrast["paired_t"]["note"] = "dropped 2 pairs"
    assert "dropped 2 pairs" in report.render_report(populated_analysis)


def test_report_renders_nan_as_na():
    body = report.render_report(
        {
            "synthetic": False,
            "n_trials": 1,
            "by_condition": {
                "b": {"hidden_pass_rate": {"n": 1, "mean": float("nan"), "sd": 0.0}}
            },
        }
    )
    row = next(line for line in body.splitlines() if line.startswith("| b |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    # The NaN mean must render as n/a, never as a bare "nan" that reads as a number.
    assert cells[2] == "n/a"
    assert "nan" not in cells


def test_report_lists_figures_with_captions(tmp_path, populated_analysis):
    figure = tmp_path / "fig.png"
    figure.write_bytes(b"\x89PNG\r\n\x1a\n")
    body = report.render_report(populated_analysis, [figure])
    assert "![fig.png](fig.png)" in body
    assert f"*{WATERMARK}*" in body


def test_report_omits_figure_caption_when_real(tmp_path, populated_analysis):
    populated_analysis["synthetic"] = False
    figure = tmp_path / "fig.png"
    figure.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert f"*{WATERMARK}*" not in report.render_report(populated_analysis, [figure])


def test_write_report_creates_parents(tmp_path, populated_analysis):
    path = report.write_report(tmp_path / "a" / "b" / "report.md", populated_analysis)
    assert path.exists()
    assert path.read_text().startswith("# study 1 report")


def test_write_report_defaults_to_empty_honest_report(tmp_path):
    path = report.write_report(tmp_path / "report.md")
    assert "## no data" in path.read_text()


def test_report_records_the_seed(populated_analysis):
    assert "- seed: 42" in report.render_report(populated_analysis)


# ---------------------------------------------------------------------------
# measurement status: the report must never let "unmeasured" look like "zero"
# ---------------------------------------------------------------------------


def test_report_states_how_many_trials_were_graded(populated_analysis):
    populated_analysis["n_graded"] = 4
    populated_analysis["n_ungraded"] = 0
    body = report.render_report(populated_analysis)
    assert "- trials graded: 4" in body
    assert "- trials not graded: 0" in body
    assert "could not be graded" not in body


def test_report_warns_before_any_table_when_trials_are_ungraded(populated_analysis):
    populated_analysis["n_trials"] = 5
    populated_analysis["n_graded"] = 2
    populated_analysis["n_ungraded"] = 3
    populated_analysis["ungraded_reasons"] = ["hidden suite collected nothing"]
    body = report.render_report(populated_analysis)
    assert "**warning: 3 of 5 trials could not be graded.**" in body
    assert "hidden suite collected nothing" in body
    # The warning has to precede the table, or it reads as a footnote.
    assert body.index("could not be graded") < body.index("| condition |")


def test_report_says_ungraded_metrics_are_not_zeroes(populated_analysis):
    populated_analysis["n_ungraded"] = 1
    body = report.render_report(populated_analysis)
    assert "they are not" in body
    assert "zeros" in body


def test_report_with_only_ungraded_trials_renders_no_outcome_table(populated_analysis):
    populated_analysis["n_trials"] = 5
    populated_analysis["n_graded"] = 0
    populated_analysis["n_ungraded"] = 5
    populated_analysis["by_condition"] = {}
    populated_analysis["contrasts"] = {}
    body = report.render_report(populated_analysis)
    assert "## no graded data" in body
    assert "| condition |" not in body
    assert "measurement failure" in body


def test_report_falls_back_to_a_reason_when_none_is_recorded(populated_analysis):
    populated_analysis["n_ungraded"] = 2
    populated_analysis["ungraded_reasons"] = []
    assert "no reason recorded" in report.render_report(populated_analysis)


def test_report_makes_no_grading_claim_when_the_status_is_unknown():
    """No `n_graded` in the analysis means the report must not assert one."""
    body = report.render_report({"synthetic": True, "n_trials": 1, "by_condition": {}})
    assert "trials graded" not in body
    assert "trials not graded" not in body
