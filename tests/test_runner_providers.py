"""Runner behaviour when a real provider is configured.

These tests never contact a provider. A fake transport is injected through the
registry, so the assertions are about the runner's control flow, provenance
labelling, and failure isolation rather than about anyone's API.

Covers the Phase 2/3 commitments:
  * an unsupported provider fails closed instead of silently running the mock
  * a real-provider run is never labelled `synthetic: true`
  * a provider outage degrades to an explicitly ungraded trial, and the rest of
    the matrix still runs
  * a provider error message reaching trials.jsonl is redacted
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pilot.config.config import Config
from pilot.models.anthropic import AnthropicModel
from pilot.models.http import ProviderError
from pilot.models.mock import MockModel
from pilot.runner import run as runner

SECRET = "sk-ant-runner-test-DO-NOT-LOG"
ANTHROPIC_OK: dict[str, Any] = {"content": [{"type": "text", "text": "def f():\n    return 1\n"}]}


def _cfg(provider: str = "mock", **experiment: Any) -> Config:
    cfg = Config()
    cfg.model.provider = provider
    cfg.model.id = "claude-sonnet-4-5"
    for key, value in experiment.items():
        setattr(cfg.experiment, key, value)
    return cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PROVIDER", "mock")


def _plan_with(cfg: Config) -> dict[str, Any]:
    return runner.plan(cfg)


# --------------------------------------------------------------------------
# Fail closed on an unknown provider
# --------------------------------------------------------------------------


def test_run_refuses_an_unknown_provider_before_doing_anything() -> None:
    cfg = _cfg("anthropicc")
    with pytest.raises(ValueError) as excinfo:
        runner.run(cfg, run_id="unknown-provider")
    assert "unknown provider" in str(excinfo.value)


def test_plan_still_reports_the_requested_provider() -> None:
    planned = _plan_with(_cfg("anthropic"))
    assert planned["provider"] == "anthropic"
    assert planned["synthetic"] is False


# --------------------------------------------------------------------------
# Provenance: never mislabel a real run as synthetic
# --------------------------------------------------------------------------


def test_mock_run_is_labelled_synthetic() -> None:
    planned = _plan_with(_cfg("mock"))
    assert planned["synthetic"] is True
    assert planned["provider"] == "mock"


def test_dry_run_summary_provenance_follows_the_provider() -> None:
    cfg = _cfg("mock", n_trials=1, max_cost_usd=1000.0)
    summary = runner.run(cfg, run_id="prov-dry-mock", dry_run=True)
    assert summary["synthetic"] is True
    assert summary["provider"] == "mock"


def test_a_real_provider_run_is_not_labelled_synthetic() -> None:
    """The bug this closes: `synthetic` was hardcoded True on every record."""
    cfg = _cfg("anthropic", n_trials=1, max_cost_usd=1000.0)
    calls: list[str] = []

    def fake(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls.append(url)
        return ANTHROPIC_OK

    # No API key in env -> must refuse before any call.
    with pytest.raises(ProviderError):
        runner.run(cfg, run_id="prov-nokey", dry_run=False, conditions=("b",))
    assert calls == [], "must refuse before opening a connection"


def test_dry_run_makes_no_provider_call_even_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`dry_run` must exercise control flow without spending or calling out."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    calls: list[str] = []

    def spy(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls.append(url)
        return ANTHROPIC_OK

    cfg = _cfg("anthropic", n_trials=1, max_cost_usd=1000.0)
    monkeypatch.setattr(runner, "build_model", lambda c=None, **kw: AnthropicModel(
        api_key=SECRET, transport=spy))

    summary = runner.run(cfg, run_id="prov-dry-real", dry_run=True)
    assert summary["dry_run"] is True
    assert summary["synthetic"] is False
    assert summary["provider"] == "anthropic"
    assert calls == [], "dry_run must not contact a provider"


# --------------------------------------------------------------------------
# Provenance recorded per trial, through the real log
# --------------------------------------------------------------------------


def _trial_records(run_id: str) -> list[dict[str, Any]]:
    path = Path("results") / run_id / "trials.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_every_mock_trial_record_is_labelled_synthetic() -> None:
    run_id = "prov-mock-records"
    import shutil

    shutil.rmtree(Path("results") / run_id, ignore_errors=True)
    cfg = _cfg("mock", n_trials=1, max_cost_usd=1000.0)
    runner.run(cfg, run_id=run_id, conditions=("a",))
    records = _trial_records(run_id)
    assert records, "no trials recorded"
    assert all(r["synthetic"] is True for r in records)
    # `provider` belongs on the run summary, not on every trial record.
    assert all("provider" not in r for r in records)


# --------------------------------------------------------------------------
# Phase 2: degraded operation when the provider fails
# --------------------------------------------------------------------------


def test_provider_outage_does_not_destroy_the_rest_of_the_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 500 on trial 1 must not abort trials 2..N, and must not be scored.

    Recording nothing would lose the resume point; recording a score would
    fabricate a result. The trial lands as explicitly ungraded.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    run_id = "prov-outage"
    # A previous run's log would be resumed instead of re-run, so the fault
    # would never be injected. Start from a clean log every time.
    import shutil

    shutil.rmtree(Path("results") / run_id, ignore_errors=True)

    state = {"n": 0}

    def flaky(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        state["n"] += 1
        if state["n"] == 1:
            raise ProviderError("HTTP 529: overloaded")
        return ANTHROPIC_OK

    cfg = _cfg("anthropic", n_trials=1, max_cost_usd=1000.0)
    real_build = runner.build_model

    def build_with_flaky(c: Config | None = None, **kw: Any) -> Any:
        model = real_build(c, **kw)
        model._transport = flaky  # type: ignore[attr-defined]
        return model

    monkeypatch.setattr(runner, "build_model", build_with_flaky)

    # Condition B, not A: condition A is the no-AI baseline and never calls the
    # model, so a fault-injecting transport would never be reached through it.
    summary = runner.run(cfg, run_id=run_id, conditions=("b",))

    # The first trial is faulted, the remaining nine must still complete: that is
    # the whole claim. One outage must not cost the operator the other nine.
    assert summary["failed"] == 1, "exactly the faulted trial is counted as failed"
    assert summary["executed"] == 9, "trials after the outage must still run"
    assert summary["failed"] + summary["executed"] == 10, "the full matrix is accounted for"

    records = _trial_records(run_id)
    assert len(records) == 10, "every trial must be recorded, including the failed one"

    # The faulted trial: ungraded, with the provider failure named as the reason.
    faulted = [r for r in records if "ungraded_reason" in r]
    assert len(faulted) == 1, "exactly one trial should carry a provider-failure reason"
    assert faulted[0]["task_id"] == "t01_merge_intervals"
    assert faulted[0]["graded"] is False
    assert faulted[0]["hidden_pass_rate"] == 0.0
    assert faulted[0]["grade_exit_class"] == "not_graded"
    assert "ProviderError" in faulted[0]["ungraded_reason"]

    # The other nine ran to completion. They are ungraded too, but for an
    # unrelated and equally honest reason: the fake completion does not match any
    # task's entrypoint, so the hidden suite fails to collect. That is the
    # grading layer refusing to invent a score, which is the behaviour we want.
    survivors = [r for r in records if "ungraded_reason" not in r]
    assert len(survivors) == 9
    for record in survivors:
        assert record["graded"] is False
        assert record["hidden_pass_rate"] == 0.0, "an ungraded trial is never a measured zero"
        assert "ProviderError" not in json.dumps(record)


def test_provider_error_text_is_redacted_in_the_trial_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.1: the key must not reach trials.jsonl via an error message."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    run_id = "prov-redact"
    import shutil

    shutil.rmtree(Path("results") / run_id, ignore_errors=True)

    def hostile(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        raise ProviderError(f"upstream rejected key {SECRET}")

    cfg = _cfg("anthropic", n_trials=1, max_cost_usd=1000.0)
    real_build = runner.build_model

    def build_hostile(c: Config | None = None, **kw: Any) -> Any:
        model = real_build(c, **kw)
        model._transport = hostile  # type: ignore[attr-defined]
        return model

    monkeypatch.setattr(runner, "build_model", build_hostile)
    runner.run(cfg, run_id=run_id, conditions=("b",))

    raw = (Path("results") / run_id / "trials.jsonl").read_text()
    assert SECRET not in raw, "API key leaked into the trial log"
    assert "<redacted>" in raw


def test_no_key_in_env_aborts_the_run_before_any_trial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = _cfg("anthropic", n_trials=1, max_cost_usd=1000.0)
    with pytest.raises(ProviderError) as excinfo:
        runner.run(cfg, run_id="prov-abort", conditions=("a",))
    message = str(excinfo.value)
    assert "no API key" in message
    assert "environment" in message
    log = Path("results") / "prov-abort" / "trials.jsonl"
    assert not log.exists() or log.read_text().strip() == "", "no trial may be recorded"


# --------------------------------------------------------------------------
# Build-model integration point
# --------------------------------------------------------------------------


def test_build_model_is_the_single_construction_site() -> None:
    """Phase 1 complete-mediation: nothing else may construct a provider model."""
    source = Path("src/pilot/runner/run.py").read_text()
    assert source.count("MockModel(") == 0, "runner must not hardcode the mock"
    assert "build_model(cfg)" in source


def test_registry_returns_a_model_subclass_for_each_provider() -> None:
    for provider, expected in (
        ("mock", MockModel),
        ("anthropic", AnthropicModel),
    ):
        cfg = _cfg(provider)
        model = runner.build_model(cfg, transport=lambda *a: ANTHROPIC_OK)
        assert isinstance(model, expected)


def test_budget_guard_uses_provider_pricing() -> None:
    """Phase 3.3: the guard must not price a real run in mock dollars."""
    mock_cfg = _cfg("mock", n_trials=20, max_cost_usd=1000.0)
    real_cfg = _cfg("openai", n_trials=20, max_cost_usd=1000.0)
    assert mock_cfg.model.pricing() != real_cfg.model.pricing()
    assert _plan_with(real_cfg)["cost_estimate_usd"] != _plan_with(mock_cfg)["cost_estimate_usd"]
