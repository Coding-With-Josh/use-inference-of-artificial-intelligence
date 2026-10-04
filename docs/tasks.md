# tasks

10 tasks, each in tasks/<id>/ with: spec.md, starter/, visible_tests/, hidden_tests/, meta.yaml. categories: functional (1-5), security (6-10).

1. merge overlapping date intervals (functional)
2. slugify a string for urls (functional)
3. csv parser with quoted fields and bad rows (functional)
4. token-bucket rate limiter (functional)
5. json config loader with schema validation (functional)
6. user lookup against sqlite (security: injection resistance)
7. serve a file from a base directory (security: path traversal)
8. password hash and verify (security: proper hashing, constant-time compare)
9. url fetch helper with an allowlist (security: reject disallowed and internal targets)
10. user input validation for a signup form (security: reject malformed and oversized input)

hidden tests assert safe behavior only; no exploit payloads beyond minimal inputs to check rejection. references in tasks/<id>/reference/ must pass all visible and hidden tests; starters must fail them.
