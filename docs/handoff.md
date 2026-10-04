# handoff

## what is done (this commit)
- docs + skeleton in current repo root (no extra subdir).
- design, conditions, tasks, metrics, threats, reproducing, preregistration, handoff written.
- README, LICENSE, CITATION.cff, CONTRIBUTING, SECURITY, Makefile, pyproject (requires-python >=3.11, uv, src layout), .env.example, .gitignore, ci.yml.
- src/pilot package stubs with __init__.py in all subdirs.
- tests/test_smoke.py (import pilot) so ci is green.
- sandbox tests: designed to skip locally when docker is absent, always run in ci; no unsafe local mode.
- CITATION.cff has full title and preferred-citation with TODO(joshua) doi/url placeholder.

## what still needs to be done
- build tasks/ with 10 tasks, starter/visible/hidden/meta, reference solutions.
- sandbox (docker runner) with no network, limits, timeout, non-root, graceful refusal if docker missing.
- mock model provider.
- conditions b and c (with ablations).
- logging (jsonl, provenance, hashes, raw/, no secrets).
- scoring (hidden tests, bandit, ruff aggregation).
- analysis (study 1: paired tests, bootstrap cis, mixed effects, figures, report.md with honesty rules).
- cli commands as specified.
- study 2 materials and tooling (protocol, consent, instructions, surveys, randomize, ingest, analysis) + demo with synthetic data.
- full tests (sandbox skip logic, hidden tests not leaked, no secrets in logs, resume, calibration, etc.), coverage >=85%.
- integrate into ci (keep smoke; add sandbox tests gated by ci env).

## docker requirement (critical)
docker desktop must be installed before the sandbox, mock demo, or task validation can run. if docker is not available, the sandbox will refuse to run and explain why; no unsafe local mode is provided.

## gaps / todos (author-supplied)
- paper link placeholder: TODO(joshua) in README and CITATION.cff url.
- ethics contact/approval placeholders: TODO(joshua) in study2 consent/protocol.
- doi placeholder: TODO(joshua) in CITATION.cff preferred-citation.
- api keys, run study 1, recruit participants, check ethics requirements, fill results placeholders as needed.
