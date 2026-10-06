# pilot model experiment

**status: the pipeline is built and verified; the study has not been run.**
`make test`, `make tasks-validate` and `make demo-mock` all pass, but every
number this repo can currently produce comes from a mock model and is
watermarked as such. There are no results from a real model, and no results
from participants. See `docs/handoff.md` for what is built, what is verified,
and what is still missing.

this repo is the experiment code and materials for the preprint *Use Inference of Artificial Intelligence: The Pilot Model*. it implements a testable version of the pilot model: ai output is inference (a probability-weighted guess), not a fact; the user is the pilot, and the ai is the instrument. the repo is designed to be reproducible by a stranger in one afternoon.

the core idea is simple: safety comes from three levers controlled by the pilot. context lowers e (chance the output is wrong in a way that matters). checking raises d (chance the error is caught before it takes effect). limits bound i (impact if an error lands). e[harm] = e*(1-d)*i.

this repo tests the paper's hypotheses, not to "prove" them, but to see what the data supports. the work could show the hypotheses are wrong. that possibility is treated as part of the experiment.

all numbers must come from code that actually ran. synthetic data lives only in `synthetic/` and is used only to test the pipeline; any figure or table generated from it must be clearly labeled "synthetic data, pipeline test only". see below for the explicit warning.

## quickstart

1. install python 3.11+ and uv: see https://docs.astral.sh/uv/.
2. `make install`
3. `make sandbox-image`  # build the pinned, non-root, no-network sandbox image
4. copy `.env.example` to `.env` and fill only what you need (api keys are never logged).
   `make test`, `make tasks-validate` and `make demo-mock` need **no** api key: they
   pin the mock provider internally, so they stay offline even if your shell has
   `PROVIDER` and a key exported.
5. `make test`  # unit and integration tests, 85% coverage gate
6. `make lint`  # ruff
7. `make typecheck`  # mypy
8. `make tasks-validate`  # every reference passes, every starter fails (needs docker)
9. `make demo-mock`  # full pipeline with mock model (needs docker)
10. `make study1-plan`  # dry run with cost estimate
11. `make study1-run`  # run study 1 (needs an api key for the chosen provider)
12. `make study1-analyze`  # stats and report

## providers

`PROVIDER` selects the model backend. Keys come from the environment only —
there is deliberately no command-line flag for a key, because argv is visible in
`ps` output to every process on the machine.

| `PROVIDER` | key | default model | notes |
|---|---|---|---|
| `groq` (default) | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | has a usable free tier; rate-limited |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5` | |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1` | |
| `mock` | — | — | offline, deterministic, watermarked; used by every test |

```bash
PROVIDER=groq GROQ_API_KEY=... make study1-run
PROVIDER=mock make demo-mock          # offline pipeline check
MODEL_ID=llama-3.1-8b-instant make study1-plan   # override the model
```

Three things worth knowing:

- **the default applies to study runs only.** `demo-mock` and the test suite pin
  `PROVIDER=mock` themselves, because their contract is "offline and
  watermarked". a key in your shell cannot turn them into a real billed run.
- **a `*_BASE_URL` override redirects the key, and is refused unless you say so.**
  `study1-plan` and `study1-run` exit 4 when a base URL points somewhere other
  than the provider's official host. proxies and gateways are legitimate, so
  `--allow-custom-base-url` permits one — and the override is then recorded in
  every trial's provenance, so a proxied run is identifiable after the fact.
- **429 and 5xx are retried, with backoff, honouring `Retry-After`** (capped at
  60 s, since that header is untrusted remote input). Each retry reuses the same
  `Idempotency-Key`, so a conforming provider dedupes it. When retries run out,
  the trial is recorded as **ungraded with reason `rate_limited`** — never as a
  failure or a zero — and a resume retries it first.
  Timeouts and refused connections are **not** retried: there is no status, so no
  way to tell whether the request was served.

## pilot mode

Preview a small run before committing to a real one. `--dry-run` needs no API key,
makes no network call, grades nothing, and writes nothing:

```bash
pilot study1-run --tasks t01,t07 --trials 3 --conditions b,c --dry-run
```

```
DRY RUN: would execute 12 trial(s) for provider mock
  would run b/t01_merge_intervals
  would run b/t01_merge_intervals#1
  ...
DRY RUN: estimated_cost_usd=0.1872 within_budget=True (no model called, nothing graded, nothing written)
```

Drop `--dry-run` to actually run it. Task ids may be full (`t07_file_serving`) or
an unambiguous prefix (`t07`); an unknown or ambiguous id is a configuration
error, not a silently shorter run.

## attrition and pairing

The report shows `n_graded`/`n_ungraded` per condition and per task, with reasons,
and warns **above the results table** when the ungraded share differs between
conditions by more than 5 percentage points — at that point the conditions are
being compared over different subsets of the corpus.

The headline contrast uses `(task, replicate)` pairs graded in **both**
conditions. Dropped pairs are counted and named in the report; they are not zeros.
See `docs/metrics.md`.

## cost and safety notes

- docker desktop is required to run sandboxed code (sandbox, mock demo, task validation). if docker is not available, the sandbox refuses to run and explains why. no unsafe local mode.
- sandbox runs with no network, resource limits, hard timeout, non-root user where possible, and read-only root where possible.
- provider agnostic; model id, temperature, seed, tokens from config; secrets only via environment variables.
- budget guard: `--max-cost-usd` aborts before overspending. `--dry-run` prints plan without calling apis.
- everything logged (append-only jsonl) with provenance; no secrets logged.

## repo map

- `docs/` - design, conditions, tasks, metrics, threats, reproducing, preregistration template, handoff
- `tasks/` - 10 tasks (5 functional, 5 security) with spec, starter, visible/hidden tests, meta
- `src/pilot/` - config, models, sandbox, conditions, scoring, logging, runner, analysis, cli
- `study2/` - protocol, consent, instructions, surveys, randomize, ingest, analysis
- `synthetic/` - pipeline test data only
- `results/` - run outputs (gitignored except .gitkeep)
- `tests/` - unit and integration tests

## how to cite

see `CITATION.cff`. full title: *Use Inference of Artificial Intelligence: The Pilot Model*. paper link placeholder: TODO(joshua). doi placeholder: TODO(joshua).

## how to reproduce the paper's results

see `docs/reproducing.md`. the pipeline is deterministic where possible and records full provenance.

## limitations, honestly

the expected-harm decomposition is illustrative (e,d,i not fully independent in practice). verification is cheaper in software than many domains. the proposed evaluation has not yet been run; model progress may shift failure modes. the pilot metaphor weakens as autonomy grows. some harms affect third parties who cannot verify. these limits are documented in `docs/threats_to_validity.md`.

## synthetic data warning (explicit)

synthetic data is for pipeline testing only. it is not evidence of the paper's hypotheses. outputs generated from synthetic data must be clearly watermarked/ labeled as "synthetic data, pipeline test only". no fabricated results are ever committed as real experimental findings.
