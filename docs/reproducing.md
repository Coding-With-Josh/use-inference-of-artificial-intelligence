# reproducing

requirements: python 3.11+, uv. docker desktop required for sandbox/mock demo/task validation that runs sandboxed code; if docker unavailable, sandbox refuses with clear message.

quickstart:
1. install uv and python 3.11+.
2. `make install`
3. copy .env.example to .env and set keys if using real providers (never commit).
4. `make test`
5. `make demo-mock` (requires docker)
6. `make study1-plan`
7. `make study1` (real providers or mock as configured)
8. `make study1-analyze`
9. `make tasks-validate` (requires docker)

notes: synthetic data is for pipeline testing only and must be clearly labeled/watermarked in any outputs. no unsafe local mode.
