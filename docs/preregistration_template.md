# preregistration template

title: pilot model experiment

hypotheses:
- h1: condition c < condition b on defects and security findings.
- h2: condition c faster than a at comparable quality.
- h3: condition b worse calibration than c.

design: between/within with tasks x conditions, randomization (balanced latin-square for study 2, run order for study 1). pre-register sample sizes.

measures: see docs/metrics.md.

analysis: mixed effects (random task/participant), bootstrap 95% cis, effect sizes, holm correction for multiple comparisons. report if sample too small.
