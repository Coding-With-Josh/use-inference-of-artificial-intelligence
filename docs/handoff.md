# handoff

## what is done (this commit)
- docs + skeleton in current repo root (no extra subdir).
- design, conditions, tasks, metrics, threats, reproducing, preregistration, handoff written.
- README, LICENSE, CITATION.cff, CONTRIBUTING, SECURITY, Makefile, pyproject (requires-python >=3.11, uv, src layout), .env.example, .gitignore, ci.yml.
- src/pilot package stubs with __init__.py in all subdirs.
- tests/test_smoke.py (import pilot) so ci is green.
- sandbox tests: designed to skip locally when docker is absent, always run in ci; no unsafe local mode.
- CITATION.cff has full title and preferred-citation with TODO(joshua) doi/url placeholder.
- smoke tests pass; lint/typecheck pass.

## docker status (current)
docker is not installed/running in this environment (no docker binary found). the sandbox runner will be implemented to detect this and refuse gracefully with a clear message; no unsafe local mode. sandbox tests will skip locally when docker is absent and always run in ci.

## what still needs to be done (next: build all tasks)
- build tasks/ with 10 tasks, starter/visible/hidden/meta, reference solutions (batch approach specified in original request was overridden by updated instruction to build all in one run).
- sandbox (docker runner) with no network, limits, timeout, non-root, graceful refusal if docker missing.
- mock model provider.
- conditions b and c (with ablations).
- logging (jsonl, provenance, hashes, raw/, no secrets).
- scoring (hidden tests, bandit, ruff aggregation).
- study 1 runner: resumable, budget guard, dry-run.
- analysis: paired tests, bootstrap cis, mixed-effects, holm correction, figures, report.
- `pilot tasks validate`, run inside the sandbox.
- cli.
- study 2: protocol, consent form, surveys, randomize.py, ingest.py, analysis.py, all runnable on synthetic data.
- finish docs, ci green, final docs/handoff.md.

## docker requirement (critical)
docker desktop must be installed before the sandbox, mock demo, or task validation can run. if docker is not available, the sandbox will refuse to run and explain why; no unsafe local mode is provided.

## gaps / todos (author-supplied)
- paper link placeholder: TODO(joshua) in README and CITATION.cff url.
- ethics contact/approval placeholders: TODO(joshua) in study2 consent/protocol.
- doi placeholder: TODO(joshua) in CITATION.cff preferred-citation.
- api keys, run study 1, recruit participants, check ethics requirements, fill results placeholders as needed.
- all 10 tasks to be implemented (reference solutions must pass bandit/ruff). hidden tests never appear in prompts/specs/visible tests.
- test to prove hidden tests never appear in prompts.
- ensure synthetic outputs are watermarked everywhere they appear.
