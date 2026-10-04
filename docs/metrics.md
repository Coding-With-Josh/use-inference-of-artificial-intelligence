# metrics

- hidden_pass_rate: fraction of hidden tests passed (0-1).
- task_solved: 1 if all hidden tests pass, else 0.
- defect_count: number of failing hidden tests.
- security_findings: bandit findings split by severity (low, medium, high), plus count of failed security-category hidden tests.
- lint_issues: ruff issue count.
- iterations: number of generate/repair rounds used.
- tokens_in, tokens_out, latency_s: usage/time.
- cost_estimate_usd: only if pricing configured.
