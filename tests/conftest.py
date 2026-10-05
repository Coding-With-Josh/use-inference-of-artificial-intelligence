"""Session-wide test isolation.

The default provider is `groq`, chosen because it has a usable free tier. That
makes the environment a genuine hazard for the test suite: a developer with
`GROQ_API_KEY` exported would otherwise have the whole suite attempt real,
rate-limited, billed API calls -- and, worse, several tests assert on
`synthetic` provenance, which would then be describing live data.

So the provider is pinned to the mock for every test, here, once. Individual
tests that need a real provider construct it explicitly with an injected fake
transport and override the relevant env var themselves.

This also removes a pre-existing source of flakiness: results were previously
written into the repository's own `results/` directory by tests that did not
isolate them.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, scope="session")
def _offline_provider() -> Iterator[None]:
    """Pin every test to the mock provider and a clean model configuration."""
    saved = {
        key: os.environ.get(key)
        for key in (
            "PROVIDER",
            "MODEL_ID",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GROQ_API_KEY",
            "ANTHROPIC_BASE_URL",
            "OPENAI_BASE_URL",
            "GROQ_BASE_URL",
        )
    }
    os.environ["PROVIDER"] = "mock"
    os.environ["MODEL_ID"] = "mock"
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_BASE_URL",
        "GROQ_BASE_URL",
    ):
        os.environ.pop(key, None)

    yield

    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
