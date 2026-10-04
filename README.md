# pilot model experiment

this repo is the experiment code and materials for the preprint *Use Inference of Artificial Intelligence: The Pilot Model*. it implements a testable version of the pilot model: ai output is inference (a probability-weighted guess), not a fact; the user is the pilot, and the ai is the instrument. the repo is designed to be reproducible by a stranger in one afternoon.

the core idea is simple: safety comes from three levers controlled by the pilot. context lowers e (chance the output is wrong in a way that matters). checking raises d (chance the error is caught before it takes effect). limits bound i (impact if an error lands). e[harm] = e*(1-d)*i.

this repo tests the paper's hypotheses, not to "prove" them, but to see what the data supports. the work could show the hypotheses are wrong. that possibility is treated as part of the experiment.

all numbers must come from code that actually ran. synthetic data lives only in `synthetic/` and is used only to test the pipeline; any figure or table generated from it must be clearly labeled "synthetic data, pipeline test only". see below for the explicit warning.

## quickstart

1. install python 3.11+ and uv: see https://docs.astral.sh/uv/.
2. `make install`
3. copy `.env.example` to `.env` and fill only what you need (api keys are never logged).
4. `make test`  # runs lint, typecheck, unit tests
5. `make demo-mock`  # full pipeline with mock model (requires docker)
6. `make study1-plan`  # dry run with cost estimate
7. `make study1`  # run study 1
8. `make study1-analyze`  # stats and report

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
