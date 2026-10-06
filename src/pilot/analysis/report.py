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


def _effect_size_lines(effect_size: dict[str, Any]) -> list[str]:
    """Report the standardized effect size, or say why it is undefined.

    Printing `inf` or `nan` here would present a division-by-zero artefact of
    degenerate data as though it were a measured effect, so an uninterpretable
    result is stated as such.
    """
    if not effect_size:
        return []
    if not effect_size.get("interpretable", False):
        return [
            f"- effect size: not defined "
            f"({effect_size.get('note', 'insufficient paired data')})"
        ]
    # Labelled secondary on purpose. dz and g are *not* in the preregistration
    # template, so reporting them as if they were preregistered would misrepresent
    # what was decided in advance. See docs/metrics.md.
    return [
        f"- effect size (**secondary, not preregistered**): "
        f"Cohen's dz={_fmt(effect_size['cohens_dz'])}, "
        f"Hedges' g={_fmt(effect_size['hedges_g'])} "
        f"(sd of paired differences={_fmt(effect_size['sd_diff'])})",
        "> dz and g are reported for context. The preregistered effects are the",
        "> mean difference with its bootstrap CI. See docs/metrics.md.",
    ]


def _attrition_lines(analysis: dict[str, Any]) -> list[str]:
    """Per-condition and per-task attrition, plus the imbalance warning.

    The imbalance warning goes above the results table, not in a footnote. If the
    conditions lost measurably different shares of their trials, the comparison
    below is between two different subsets of the corpus, and a reader who reaches
    the table without seeing that has been told something misleading by omission.
    """
    attrition = analysis.get("attrition") or {}
    by_condition = attrition.get("by_condition") or {}
    if not by_condition:
        return []

    lines = ["## attrition", ""]
    lines += [
        "| condition | planned | graded | ungraded | ungraded % | reasons |",
        "|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(by_condition.items()):
        total = entry.get("n_total", 0)
        ungraded = entry.get("n_ungraded", 0)
        pct = (100.0 * ungraded / total) if total else 0.0
        reasons = ", ".join(
            f"{reason}={count}" for reason, count in sorted(entry.get("reasons", {}).items())
        )
        lines.append(
            f"| {name} | {total} | {entry.get('n_graded', 0)} | {ungraded} | "
            f"{pct:.1f} | {reasons or 'n/a'} |"
        )
    lines.append("")

    by_task = attrition.get("by_task") or {}
    if by_task:
        lines += ["<details><summary>per task</summary>", ""]
        lines += ["| task | graded | ungraded |", "|---|---|---|"]
        for name, entry in sorted(by_task.items()):
            lines.append(
                f"| {name} | {entry.get('n_graded', 0)} | {entry.get('n_ungraded', 0)} |"
            )
        lines += ["", "</details>", ""]

    if attrition.get("imbalanced"):
        lines += [
            f"> **warning: differential attrition of "
            f"{_fmt(attrition.get('imbalance_points', 0.0), 1)} points.**",
            f"> Condition `{attrition.get('worst_condition')}` lost more trials than the",
            f"> others, above the {attrition.get('threshold_points')}-point threshold.",
            "> The conditions are therefore compared over different subsets of the",
            "> corpus, and the difference below is partly a difference in what",
            "> survived. Read the effect sizes with that in mind.",
            "",
        ]
    return lines


def _pairing_lines(label: str, pairing: dict[str, Any]) -> list[str]:
    """State how many (task, trial) pairs the headline contrast actually used."""
    if not pairing:
        return []
    dropped = pairing.get("n_dropped", 0)
    lines = [
        f"- pairing: {pairing.get('n_pairs', 0)} {pairing.get('key', 'pairs')} "
        f"graded in both conditions",
    ]
    if dropped:
        reasons = []
        if pairing.get("n_b_ungraded"):
            reasons.append(f"{pairing['n_b_ungraded']} ungraded in the first condition")
        if pairing.get("n_c_ungraded"):
            reasons.append(f"{pairing['n_c_ungraded']} ungraded in the second")
        if pairing.get("n_b_missing"):
            reasons.append(f"{pairing['n_b_missing']} missing from the first condition")
        if pairing.get("n_c_missing"):
            reasons.append(f"{pairing['n_c_missing']} missing from the second")
        lines.append(f"- **{dropped} pair(s) dropped:** " + "; ".join(reasons))
        lines.append(
            "> These cells contribute to no number in this section. They are not"
            " zeros and they are not counter-evidence."
        )
    else:
        lines.append("- dropped pairs: 0")
    lines.append(f"> note: {pairing.get('note', '')}")
    return lines


def _provenance_lines(provenance: dict[str, Any]) -> list[str]:
    """What actually answered: provider, host, requested and returned model."""
    if not provenance:
        return []
    lines = [
        f"- provider: {', '.join(provenance.get('providers') or ['unknown'])}",
        f"- base_url host: "
        f"{', '.join(provenance.get('base_url_hosts') or ['n/a (mock, offline)'])}",
        f"- requested model id: "
        f"{', '.join(provenance.get('requested_model_ids') or ['n/a'])}",
        f"- returned model id: "
        f"{', '.join(provenance.get('returned_model_ids') or ['not reported by provider'])}",
    ]
    mismatch = provenance.get("model_id_mismatch") or []
    if mismatch:
        lines += [
            f"- **the API reported a different model than was requested: "
            f"{', '.join(mismatch)}**",
            "> These results describe a model the study did not name. Treat them as",
            "> evidence about the returned id, not the requested one.",
        ]
    if provenance.get("custom_base_url"):
        lines.append(
            "- **a non-official base URL was in effect** (--allow-custom-base-url): "
            "the API key was sent to a host other than the provider's own"
        )
    retries = provenance.get("total_retries", 0)
    if retries:
        lines.append(f"- provider retries across the run: {retries}")
    missing = provenance.get("trials_without_returned_model_id", 0)
    if missing:
        lines.append(
            f"- trials with no returned model id reported: {missing} "
            "(the provider's envelope did not carry one)"
        )
    return lines


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

    lines += _attrition_lines(analysis)

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
                *_effect_size_lines(result.get("effect_size", {})),
                *_pairing_lines(label, result.get("pairing", {})),
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
        *_provenance_lines(analysis.get("provenance") or {}),
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
