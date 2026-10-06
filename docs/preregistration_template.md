# preregistration template

title: pilot model experiment

hypotheses:
- h1: condition c < condition b on defects and security findings.
- h2: condition c faster than a at comparable quality.
- h3: condition b worse calibration than c.

design: between/within with tasks x conditions, randomization (balanced latin-square for study 2, run order for study 1). pre-register sample sizes.

measures: see docs/metrics.md.

analysis: mixed effects (random task/participant), bootstrap 95% cis, effect sizes, holm correction for multiple comparisons. report if sample too small.

## primary effect sizes (preregistered)

- the mean paired difference in `hidden_pass_rate` between conditions, with a
  bootstrap 95% confidence interval.
- the same for `defect_count` and `security_findings`.

## secondary effect sizes (NOT preregistered)

Cohen's *dz* and Hedges' *g* for the paired contrast, reported by the harness for
context. These are **not** listed as primary above, so:

- they must be described as secondary and exploratory wherever they appear;
- no confirmatory claim may rest on one;
- they do not enter the Holm correction as a separate hypothesis.

If this study *should* pre-register them, add them to the primary list above and
delete the "secondary, not preregistered" label from `_effect_size_lines()` in
`src/pilot/analysis/report.py`. That label exists so the report cannot imply these
were decided in advance when they were not.

## multiplicity

The Holm correction is applied across the family of tests within each contrast
(paired t and Wilcoxon), not across contrasts. Pre-register which contrasts are
confirmatory.

## attrition

- a trial with no measurement is ungraded, never a zero.
- pre-register an attrition threshold. The harness warns when the ungraded share
  differs between conditions by more than 5 percentage points.
- pre-register what to do if it is exceeded: the default is to report the contrast
  as descriptive rather than confirmatory, and to say so in the report.

## missing data

The headline contrast uses `(task_id, trial_index)` cells graded in **both**
conditions. Cells graded in only one are dropped and counted in the report.
Pre-register the expected drop rate and the analysis if attrition is worse than
that; the default is no imputation, because inventing a value for a missing
measurement is worse than reporting a smaller n.

## provider and model provenance

Pre-register the provider, the model id, and the expected `returned_model_id`.
The harness records all of these per trial and flags any difference between the
requested and returned model id, so a silently-routed model cannot pass as the
pre-registered one.