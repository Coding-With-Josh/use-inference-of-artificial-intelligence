# Sandbox image for executing untrusted task solutions.
#
# Built by `make sandbox-image`. Nothing in the harness runs task code on the
# host: this image is the only place untrusted Python is ever executed.
#
# Pinning notes:
#   - The base is pinned by *manifest list* digest, not a platform digest, so the
#     same Dockerfile builds on arm64 (local Docker Desktop) and amd64 (CI).
#   - Every tool version is pinned. An unpinned build would let the corpus's
#     pass/fail results drift with an upstream release.
FROM python:3.11-slim@sha256:bab1b7ef4b450c81002278d035eff85ebe394ae94df904f7a3ba14f7e16e487b

ARG PYTEST_VERSION=9.1.1
ARG PYTEST_COV_VERSION=7.1.0
ARG RUFF_VERSION=0.16.10
ARG BANDIT_VERSION=1.9.4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ruff and bandit are installed alongside pytest because the scoring stage runs
# static checks on the same untrusted solutions, inside the same sandbox, with
# no network. --no-cache-dir keeps pip state out of the image.
RUN pip install --no-cache-dir \
        "pytest==${PYTEST_VERSION}" \
        "pytest-cov==${PYTEST_COV_VERSION}" \
        "ruff==${RUFF_VERSION}" \
        "bandit==${BANDIT_VERSION}"

# Non-root account matching the uid/gid the runner passes via --user 1000:1000.
# Giving it a real home keeps tools that want one (ruff cache, tmp) from failing
# in confusing ways; the runner additionally mounts /tmp as a writable tmpfs.
RUN groupadd --gid 1000 pilot \
 && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin pilot \
 && mkdir -p /app \
 && chown 1000:1000 /app

# Task directories are bind-mounted over /app read-only at run time.
WORKDIR /app
USER 1000:1000

# Prove the toolchain works at build time. An image that cannot run its own
# pytest/ruff/bandit must fail here rather than masquerade as "built" and then
# produce exit-code-4 collection errors that look like task failures.
RUN python -c "import pytest; assert pytest.__version__ == '${PYTEST_VERSION}', pytest.__version__" \
 && ruff --version \
 && bandit --version