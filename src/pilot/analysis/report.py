"""Markdown report for study 1.

The report states its own provenance: synthetic runs are watermarked, and an
empty run says so plainly instead of rendering a table of nothing. No figure or
table is emitted from data the pipeline did not actually process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WATERMARK = "synthetic data, pipeline test only"


def _fmt(value: float, places: int = 3) -> str:
    if value != value:  # NaN check without importing math
        return "n/a"
    return f"{value:.{places}f}"


def render_report(analysis: dict[str, Any], figures: list[Path] | None = None) -> str:
    """Render the study-1 report body."""
    synthetic = bool(analysis.get("synthetic", True))
    trials = analysis.get("n_trials", 0)

    lines: list[str] = ["# study 1 report", ""]

    if synthetic:
        lines += [
            f"> **{WATERMARK}**",
            "> These numbers come from a mock-model pipeline run. They are not",
            "> measurements of any real model or any real person.",
            "",
        ]

    lines += [
        "## run",
        "",
        f"- trials analyzed: {trials}",
        f"- run_id: `{analysis.get('run_id', 'n/a')}`",
        "",
    ]

    graded = analysis.get("n_graded")
    ungraded = int(analysis.get("n_ungraded", 0) or 0)
    if graded is not None:
        lines += [
            f"- trials graded: {graded}",
            f"- trials not graded: {ungraded}",
            "",
        ]

    # Ungraded trials are the one thing that most easily reads as a result when
    # it is not, so it is stated before any table, with the reason.
    if ungraded:
        lines += [
            f"> **warning: {ungraded} of {trials} trials could not be graded.**",
            "> Their metrics are absent from every table below -- they are not",
            "> zeros. A trial with no measurement contributes nothing to these",
            "> statistics.",
            "",
        ]
        for reason in analysis.get("ungraded_reasons", []) or ["no reason recorded"]:
            lines.append(f"> - {reason}")
        if not analysis.get("by_condition"):
            lines += [
                "",
                "No trial produced a grade, so no outcome statistics follow.",
            ]
        lines.append("")

    if trials == 0:
        lines += [
            "## no data",
            "",
            "No trials were recorded, so no statistics are reported. This is a",
            "deliberate blank, not a zero result: no claim is being made here.",
            "",
        ]
        return "\n".join(lines)

    if not analysis.get("by_condition"):
        lines += [
            "## no graded data",
            "",
            "Trials were recorded but none of them produced a measurable score,",
            "so no outcome statistics are reported. This is a measurement failure,",
            "not a zero result.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## outcome by condition",
        "",
        "| condition | n | mean hidden_pass_rate | sd | mean defects |",
        "|---|---|---|---|---|",
    ]
    for name, stats in sorted(analysis.get("by_condition", {}).items()):
        hp = stats.get("hidden_pass_rate", {})
        dc = stats.get("defect_count", {})
        lines.append(
            f"| {name} | {hp.get('n', 0)} | {_fmt(hp.get('mean', 0.0))} | "
            f"{_fmt(hp.get('sd', 0.0))} | {_fmt(dc.get('mean', 0.0))} |"
        )
    lines.append("")

    contrasts = analysis.get("contrasts", {})
    if contrasts:
        lines += ["## contrasts", ""]
        for label, result in sorted(contrasts.items()):
            effect = result.get("effect", {})
            t = result.get("paired_t", {})
            w = result.get("wilcoxon", {})
            holm = result.get("holm", {})
            lines += [
                f"### {label}",
                "",
                f"- paired t: t={_fmt(t.get('statistic', 0.0))}, "
                f"p={_fmt(t.get('p_value', 1.0))}, n={t.get('n', 0)}",
                f"- wilcoxon: W={_fmt(w.get('statistic', 0.0))}, "
                f"p={_fmt(w.get('p_value', 1.0))}",
                f"- mean difference: {_fmt(effect.get('mean_diff', 0.0))} "
                f"(95% CI {_fmt(effect.get('ci_low', 0.0))} to {_fmt(effect.get('ci_high', 0.0))})",
                f"- holm-adjusted p (family of {holm.get('m', 0)}): "
                f"{[_fmt(p) for p in holm.get('adjusted', [])]}",
                f"- reject at alpha={holm.get('alpha', 0.05)}: {holm.get('reject', [])}",
                "",
            ]
            if t.get("note"):
                lines += [f"> note: {t['note']}", ""]

    mixed = analysis.get("mixed_effects")
    if mixed:
        lines += [
            "## mixed effects",
            "",
            f"- converged: {mixed.get('converged')}",
            f"- n: {mixed.get('n', 0)}",
            "",
        ]
        if mixed.get("coef"):
            for term, value in sorted(mixed["coef"].items()):
                lines.append(f"- `{term}` = {_fmt(value)}")
            lines.append("")
        if mixed.get("note"):
            lines += [f"> note: {mixed['note']}", ""]

    calibration = analysis.get("calibration")
    if calibration:
        lines += [
            "## calibration",
            "",
            f"- brier score: {_fmt(calibration.get('brier', 0.0))}",
            f"- expected calibration error: {_fmt(calibration.get('calibration_error', 0.0))}",
            "",
        ]

    if figures:
        lines += ["## figures", ""]
        for figure in figures:
            rel = Path(figure).name
            caption = f"{WATERMARK}" if synthetic else ""
            lines += [f"![{rel}]({rel})", f"*{caption}*" if caption else "", ""]

    lines += [
        "## provenance",
        "",
        f"- synthetic: {synthetic}",
        f"- seed: {analysis.get('seed', 'n/a')}",
        "",
    ]
    return "\n".join(lines)


def write_report(
    path: Path,
    analysis: dict[str, Any] | None = None,
    figures: list[Path] | None = None,
) -> Path:
    """Write the report to `path`, creating parent directories."""
    analysis = analysis if analysis is not None else {"synthetic": True, "n_trials": 0}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(analysis, figures), encoding="utf-8")
    return path
