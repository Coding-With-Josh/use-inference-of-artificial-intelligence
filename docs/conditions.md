# conditions

## condition b (naive use)
- prompt is task spec plus visible tests as plain text only.
- one generation, no retries, no feedback.
- output accepted as is.

## condition c (pilot practice)
stages:
1. context: spec, visible tests, project context template, starter code.
2. decomposition: plan steps, generate and integrate per step (step cap).
3. guardrails: run visible tests, ruff, bandit, mypy in sandbox; feed failures back for repair (max_repair_rounds=3, stop early on pass).
4. scoped authority: writes only to designated task files; other writes rejected and logged.

ablations: `--ablate context|decomposition|guardrails` (each separately toggleable).
