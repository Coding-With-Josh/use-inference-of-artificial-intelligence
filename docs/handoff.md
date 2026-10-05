# handoff

State as of this commit. Everything below was verified by running the command
named; nothing is asserted from memory.

## verified green

| command | result |
|---|---|
| `make test` | 536 passed, coverage 93.06% (gate 85%, unchanged) |
| `make tasks-validate` | 10 tasks, 20 sandbox runs, 120 hidden tests; every reference passed, every starter failed |
| `make demo-mock` | 20 trials, **20 graded**, 206 hidden tests executed, 3 figures, watermarked report + manifest |
| `uv run ruff check .` | All checks passed |
| `uv run mypy src tests` | no issues in 74 source files |

## built and tested

- **sandbox** — `sandbox/Dockerfile` pins `python:3.11-slim` by manifest-list
  digest (works on arm64 and amd64), runs as non-root uid 1000, installs
  pytest/ruff/bandit at the same versions as `.venv`, and has no network.
  `docker_runner.py` checks daemon reachability and image presence and refuses
  with a message naming `make sandbox-image`. There is no local fallback mode.
  Exit codes are classified by `classify_exit()` (0 passed / 1 tests failed /
  4 usage / 5 no tests collected / 124 timeout / 127 not found).
- **task corpus** — 10 tasks. Every starter is docstring + `raise
  NotImplementedError` and nothing else (asserted by an AST-based suite, not by
  reading text). Hidden suites run 8–17 tests per task, all tied to
  `docs/tasks.md`. One unsafe fixture per security task lives in
  `tests/fixtures/unsafe/`, and `tests/test_unsafe_fixtures_fail_hidden.py`
  runs each one in the sandbox and asserts `collected > 0`, `failed > 0`,
  `exit_code == 1` — plus a reference-passing control so a broken harness cannot
  make them pass by accident.
- **prompt leak test** — `tests/test_no_hidden_leak.py` scans every prompt
  template and every mock-run prompt string, asserts it scanned more than zero
  strings, and asserts no hidden test function name or distinctive assertion
  literal appears in any spec, starter, or visible test. 28 hidden-exclusive
  literals are currently detected across the corpus (asserted non-zero).
  `prompts._read_allowed` refuses to read `hidden_tests` at all.
- **scoring** — hidden tests, ruff, bandit, guardrails, metrics. `metrics.py`
  and `report.py` are at 100% statement coverage.
- **conditions** — A/B/C with the `context|decomposition|guardrails` ablations
  and a bounded repair loop. Condition C writes through `authority.py`, a
  deny-by-default scoped write guard (rejects NUL, absolute paths, `..`, and
  symlink escapes; re-checks containment after resolution; audits every attempt
  to a JSONL file).
- **runner** — plan / run / analyze, with a budget guard, `--dry-run`, and
  resume that skips trials already in the log.
- **provider adapters** — `anthropic`, `openai` and `groq` behind the common
  `Model` interface, selected by `PROVIDER` (default `groq`, which has a usable
  free tier). Keys come from the environment only, wrapped in `RedactedSecret`,
  and travel in the `Authorization` header — never a URL parameter, never a log
  line. Adapters speak HTTP through an **injectable transport**, so the whole
  suite runs offline and any unexpected outbound call is visible in a test.
  `build_model` is an allow-list that raises on an unknown provider and never
  falls back to the mock; a silent fallback would turn a real study into
  synthetic data. `demo-mock` and `tests/conftest.py` each pin `PROVIDER=mock`
  themselves, so an exported key cannot turn a watermarked pipeline test into a
  billed API run.
- **analysis** — paired t, Wilcoxon, bootstrap CI, Holm correction, mixed
  effects, figures, markdown report.
- **cli** — `study1-plan`, `study1-run`, `study1-analyze`, `tasks-validate`,
  `demo-mock`.

## measurement honesty

These are the rules the code enforces, each with a test:

- A trial that could not be graded is **never** recorded as a measured zero.
  `grade_trial` returns `graded: False` whenever the hidden suite produced no
  pass/fail verdict — including the case where pytest reports a *collection*
  error, which the summary parser counts as one collected item.
- `analyze()` builds every statistic from graded trials only. Ungraded trials are
  counted and their reasons listed.
- The report prints the grading counts and a warning **above** the results
  table, and renders `## no graded data` (no table, no figures) when nothing was
  measured.
- The manifest carries `n_graded` / `n_ungraded` / `ungraded_reasons`, so a
  consumer reading only the manifest can still tell the two apart.
- The mock model emits *importable, inert* Python (plus a PEP 562
  `__getattr__`). An earlier version returned bare tokens, which do not import,
  so every trial was uncollectable and the grading path was dead code. The mock
  still never sees the hidden tests, so a mock score is genuinely zero rather
  than unmeasured.

## bugs found and fixed while testing

- `runner.run` passed the real task directory to condition C as its workdir, so
  a run wrote the model's output into the graded corpus
  (`tasks/*/starter/solution.py`). Fixed by staging a per-trial workspace; a
  checksum over `tasks/**/*.py` is now identical before and after `make
  demo-mock`.
- `validate.py` buried its acceptance rules inside the function that shells out
  to Docker, so they could only be tested by running Docker. Extracted
  `evaluate_run()`, a pure function; the contract is now tested with synthetic
  results and does not need a container.
- `stats.paired_t_test` crashed under `filterwarnings = ["error"]` on
  constant-but-nonzero differences: `allclose(diffs, 0)` missed them and
  `ttest_rel` then hit numpy's catastrophic-cancellation warning as an
  exception. Fixed with `_degenerate_diffs()`, which reports "not tested"
  instead.
- With guardrails off, `cond_c` discarded the write authority's rejection, so
  scoped-authority violations were silently swallowed. Rejections are now
  recorded.
- `parse_pytest_summary` read the summary keyword one position too early when
  the preceding token was a digit.
- `stats.py` called an undefined `summarize`; `prompts.py` had a dead variable.
  Both caught by ruff.

## known gaps

- `study2/` is not importable as a package from the test suite, so
  `study2/analysis.py` is exercised only by hand, not by `make test`.
- `src/pilot/sandbox/docker_runner.py` is at 80% statement coverage; the
  uncovered lines are launcher-failure branches that need Docker to be *absent*.
- `demo-mock` reports `planned=600` (the full three-condition plan) while
  executing 20 (conditions b and c). Honest, but the two numbers describe
  different scopes.
- The unsafe fixtures for t10 are covered by the shared unsafe-fixture test; the
  per-fixture failure counts are not separately pinned.

## not done — needs a person

- `TODO(joshua)` paper link in README, and the DOI/URL in `CITATION.cff`.
- Ethics contact/approval placeholders in `study2/` consent and protocol.
- **A real study 1 run.** The adapters exist and are tested, but every real
  outbound call is still untested against a live endpoint: no key has ever been
  used here, so Groq's actual response envelope, its rate-limit behaviour and its
  free-tier quotas are unverified. Every number currently in the repo still comes
  from the mock model and is watermarked as such.
- **`GEMINI_API_KEY` was removed from `.env.example`.** It was listed but no
  Gemini adapter exists; listing a key for an unsupported provider invites
  setting it and wondering why nothing changes.
- Participants, ethics review, and any use of the results.