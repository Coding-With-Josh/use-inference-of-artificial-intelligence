# metrics

## primary trial metrics

- hidden_pass_rate: fraction of hidden tests passed (0-1).
- task_solved: 1 if all hidden tests pass, else 0.
- defect_count: number of failing hidden tests.
- security_findings: bandit findings split by severity (low, medium, high), plus count of failed security-category hidden tests.
- lint_issues: ruff issue count.
- iterations: number of generate/repair rounds used.
- tokens_in, tokens_out, latency_s: usage/time.
- cost_estimate_usd: only if pricing configured.

## attrition

A trial that produced no measurement is **not** a trial that scored zero. The two
are recorded differently and must never be averaged together.

- n_graded / n_ungraded are reported per condition and per task.
- An ungraded trial always carries an `ungraded_reason_code`:

| code | meaning | retried on resume |
|---|---|---|
| `rate_limited` | the provider returned 429 after the retries were exhausted | yes, first |
| `provider_error` | the provider returned 5xx after the retries were exhausted | yes, first |
| `unreachable` | no HTTP response at all (timeout, refused connection) | yes, first |
| `http_error` | any other 4xx; permanent, e.g. 401 or 400 | no |
| `not_graded` | the model ran but the hidden suite produced no verdict | no |

The distinction between the first three and the last two is not cosmetic. A
rate limit is transient, so re-running it recovers a measurement. A 401 will fail
again, so retrying it just burns the budget.

- **differential attrition.** If the ungraded share differs between conditions by
  more than 5 percentage points, the report prints a warning *above* the results
  table. At that point the conditions are being compared over different subsets of
  the corpus, and the difference in means is partly a difference in what survived.
  Measured on rates, not raw counts, so a large balanced run does not trip it.

## pairing

The headline contrast uses **complete pairs only**. A pair is a
`(task_id, trial_index)` cell that was graded in *both* conditions.

- `trial_index` is the replicate number. Pairing on `task_id` alone would collapse
  replicates and silently keep only one per task.
- A cell graded in only one condition is dropped from the contrast and counted in
  the report: `n_dropped`, split into ungraded-on-one-side and missing-entirely.
  A dropped cell is not a zero and not counter-evidence.
- If a trial is retried and succeeds, only the latest record for that cell counts.

## effect sizes

**Preregistered (primary):** the mean paired difference with a bootstrap 95% CI.

**Secondary, not preregistered:** Cohen's *dz* and Hedges' *g*, computed by
`paired_effect_size()` in `src/pilot/analysis/stats.py`.

*dz* is the mean paired difference over the standard deviation of those
differences — the correct standardization for a within-subject design, where the
variance of the raw scores is not the error term. Hedges' small-sample correction
*J* = 1 − 3/(4(n−1) − 1) is applied because at this study's sample sizes *g* is
biased upward and *dz* alone overstates the effect.

These are reported for context and are labelled as such in the report. They are
**not** in `preregistration_template.md`, so they must not be described as
preregistered, and a conclusion should not rest on one. If a future preregistration
lists them, delete the "secondary, not preregistered" label from
`_effect_size_lines()` in `src/pilot/analysis/report.py`.

`paired_effect_size()` returns `interpretable: False` when the paired differences
have no variance. *dz* divides by an SD of zero there, and the guard is a
magnitude-scaled tolerance rather than `sd == 0.0`: ten values of `0.3` averaged
back together are not bit-identical, so an exact-zero check would report a
*dz* in the 1e15 range as though it were a large effect.

## provenance

Every trial records the four fields that identify what produced it:

- `provider`
- `base_url_host` — the host the request actually went to, which is not always
  the provider's own
- `requested_model_id` — what was asked for
- `returned_model_id` — what the API reported answering

`requested_model_id` and `returned_model_id` can legitimately differ; Anthropic
appends a date suffix, and a gateway or alias can rewrite the model entirely. The
report flags any difference, because results from a silently-routed model describe
a model the study did not name. A provider whose envelope omits the field yields
`null`, reported as "not reported by provider" rather than filled in from the
request.