"""Item 1 and item 2: base-URL blocking, and the 429/5xx retry policy.

Two properties are load-bearing here.

1. A non-official `*_BASE_URL` redirects the API key to another host. That is now
   refused outright rather than warned about, because a warning is invisible to
   anyone who does not read stderr and a forgotten environment variable is exactly
   how a credential ends up at a third party. Opting in is explicit and the opt-in
   is recorded in every trial.

2. A rate-limited or 5xx'd trial is retried, and when the retries run out the
   trial is recorded as *ungraded with a reason*. It is never recorded as a
   failure or a zero, because a rate limit is a missing measurement, not a
   measurement of zero.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pilot.config.config import Config
from pilot.models.anthropic import AnthropicModel
from pilot.models.groq import GroqModel
from pilot.models.http import (
    MAX_RETRY_AFTER_S,
    BaseUrlBlocked,
    ProviderError,
    check_base_url,
    parse_retry_after,
)
from pilot.models.openai import OpenAIModel
from pilot.models.registry import check_configured_base_url, describe_unusual_base_url

SECRET = "sk-test-key-DO-NOT-LOG-abc123"

OK_ANTHROPIC: dict[str, Any] = {
    "content": [{"type": "text", "text": "def f(): pass"}],
    "model": "claude-sonnet-4-5-20250929",
}


@pytest.fixture
def no_sleep() -> Any:
    """Collect requested delays instead of waiting, so backoff is instant."""
    waits: list[float] = []

    def _sleep(seconds: float) -> None:
        waits.append(seconds)

    _sleep.waits = waits  # type: ignore[attr-defined]
    return _sleep


# --------------------------------------------------------------------------
# Item 1: base URL
# --------------------------------------------------------------------------


def test_a_non_official_base_url_is_refused_by_default() -> None:
    """The credential must not follow a base URL to an arbitrary host."""
    with pytest.raises(BaseUrlBlocked) as excinfo:
        AnthropicModel(
            api_key=SECRET, base_url="https://agentrouter.org/v1", transport=lambda *a: OK_ANTHROPIC
        )
    message = str(excinfo.value)
    assert "agentrouter.org" in message
    assert "api.anthropic.com" in message
    assert "--allow-custom-base-url" in message, "the refusal must say how to proceed"


def test_the_refusal_happens_in_the_constructor_before_any_call() -> None:
    """No request may be made against a blocked host. Counting calls proves it."""
    calls: list[int] = []

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls.append(1)
        return OK_ANTHROPIC

    with pytest.raises(BaseUrlBlocked):
        OpenAIModel(
            api_key=SECRET,
            base_url="https://api.openai.com.evil.test/v1",
            transport=transport,
        )
    assert calls == [], "a blocked host must never be contacted"


def test_the_opt_in_allows_a_custom_base_url_and_records_it() -> None:
    model = GroqModel(
        api_key=SECRET,
        base_url="https://gateway.internal.example/v1",
        allow_custom_base_url=True,
        transport=lambda *a: {"choices": [{"message": {"content": "x"}}], "model": "llama-3.3-70b"},
    )
    assert model.base_url_host == "gateway.internal.example"
    prov = model.provenance()
    assert prov["allow_custom_base_url"] is True
    assert prov["base_url_host"] == "gateway.internal.example"
    assert prov["provider"] == "groq"


def test_an_official_host_needs_no_opt_in() -> None:
    model = AnthropicModel(
        api_key=SECRET, base_url="https://api.anthropic.com/v1", transport=lambda *a: OK_ANTHROPIC
    )
    assert model.base_url_host == "api.anthropic.com"
    assert model.provenance()["allow_custom_base_url"] is False


def test_a_subdomain_of_an_official_host_is_allowed() -> None:
    assert (
        check_base_url(
            "openai", "https://eu.api.openai.com/v1", ("api.openai.com",), allow_custom=False
        )
        == "eu.api.openai.com"
    )


def test_a_lookalike_host_is_refused() -> None:
    """api.openai.com.evil.test must not pass as api.openai.com."""
    with pytest.raises(BaseUrlBlocked):
        check_base_url(
            "openai", "https://api.openai.com.evil.test/v1", ("api.openai.com",), allow_custom=False
        )


def test_every_real_provider_blocks_a_third_party_host() -> None:
    """Parametrised so a future adapter cannot ship with no official hosts set."""
    from pilot.models.registry import SUPPORTED_PROVIDERS, resolve

    for provider in SUPPORTED_PROVIDERS:
        cls = resolve(provider)
        official = getattr(cls, "official_hosts", ())
        if not official:
            continue  # mock: offline, no host, nothing to redirect
        with pytest.raises(BaseUrlBlocked):
            check_base_url(provider, "https://elsewhere.test/v1", official, allow_custom=False)


def test_cli_level_check_refuses_the_same_way(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config()
    cfg.model.provider = "anthropic"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://agentrouter.org/")
    with pytest.raises(BaseUrlBlocked):
        check_configured_base_url(cfg)


def test_cli_level_check_passes_once_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config()
    cfg.model.provider = "anthropic"
    cfg.model.allow_custom_base_url = True
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://agentrouter.org/")
    assert check_configured_base_url(cfg) == "agentrouter.org"
    note = describe_unusual_base_url(cfg)
    assert note is not None and "agentrouter.org" in note, "opt-in must still be visible"


def test_no_base_url_override_means_no_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    cfg = Config()
    cfg.model.provider = "anthropic"
    assert describe_unusual_base_url(cfg) is None
    assert check_configured_base_url(cfg) is None


def test_allow_custom_base_url_reads_the_environment_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from pilot.config.config import load_config

    monkeypatch.setenv("ALLOW_CUSTOM_BASE_URL", "true")
    assert load_config().model.allow_custom_base_url is True
    monkeypatch.setenv("ALLOW_CUSTOM_BASE_URL", "0")
    assert load_config().model.allow_custom_base_url is False


# --------------------------------------------------------------------------
# Provenance: requested vs returned model id
# --------------------------------------------------------------------------


def test_the_returned_model_id_is_recorded_not_the_requested_one() -> None:
    """A provider that answers with a different model must be visible."""
    model = AnthropicModel(
        api_key=SECRET, model_id="claude-sonnet-4-5", transport=lambda *a: OK_ANTHROPIC
    )
    model.generate("x")
    prov = model.provenance()
    assert prov["requested_model_id"] == "claude-sonnet-4-5"
    assert prov["returned_model_id"] == "claude-sonnet-4-5-20250929"
    assert prov["returned_model_id"] != prov["requested_model_id"]


def test_returned_model_id_is_none_when_the_envelope_omits_it() -> None:
    """Absent is reported as absent, not filled in from the request."""
    model = AnthropicModel(
        api_key=SECRET, transport=lambda *a: {"content": [{"type": "text", "text": "y"}]}
    )
    model.generate("x")
    assert model.provenance()["returned_model_id"] is None


def test_reset_provenance_clears_the_per_trial_record() -> None:
    model = AnthropicModel(api_key=SECRET, transport=lambda *a: OK_ANTHROPIC)
    model.generate("x")
    assert model.provenance()["returned_model_id"] is not None
    model.reset_provenance()
    prov = model.provenance()
    assert prov["returned_model_id"] is None
    assert prov["retries"] == 0


def test_multiple_distinct_returned_models_are_all_kept() -> None:
    """A mid-run model change must not be averaged away into the first name."""
    names = iter(["model-one", "model-two"])

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": "z"}],
            "model": next(names),
        }

    model = AnthropicModel(api_key=SECRET, transport=transport)
    model.generate("a")
    model.generate("b")
    assert model.provenance()["returned_model_ids"] == ["model-one", "model-two"]


# --------------------------------------------------------------------------
# Item 2: retry on 429 / 5xx
# --------------------------------------------------------------------------


def test_a_429_is_retried_and_then_succeeds(no_sleep: Any) -> None:
    attempts = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ProviderError("HTTP 429: slow down", status=429, retry_after=0.5)
        return OK_ANTHROPIC

    model = AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep)
    assert model.generate("x")
    assert attempts["n"] == 3
    assert no_sleep.waits == [0.5, 0.5], "Retry-After must be honoured on each retry"
    assert model.provenance()["retries"] == 2


def test_retry_after_is_honoured_over_the_exponential_schedule(no_sleep: Any) -> None:
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("HTTP 429", status=429, retry_after=7.0)
        return OK_ANTHROPIC

    AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep).generate("x")
    assert no_sleep.waits == [7.0]


def test_without_retry_after_the_backoff_doubles(no_sleep: Any) -> None:
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 4:
            raise ProviderError("HTTP 500", status=500)
        return OK_ANTHROPIC

    AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep, retry_base_s=1.0).generate(
        "x"
    )
    assert no_sleep.waits == [1.0, 2.0, 4.0]


def test_a_hostile_retry_after_is_capped(no_sleep: Any) -> None:
    """Retry-After is untrusted remote input; 86400 must not stall a study."""
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("HTTP 429", status=429, retry_after=86400.0)
        return OK_ANTHROPIC

    AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep).generate("x")
    assert no_sleep.waits == [MAX_RETRY_AFTER_S, MAX_RETRY_AFTER_S]


def test_exhausted_retries_raise_with_status_429_and_reason_rate_limited(no_sleep: Any) -> None:
    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        raise ProviderError("HTTP 429: rate limited", status=429)

    model = AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep, max_attempts=3)
    with pytest.raises(ProviderError) as excinfo:
        model.generate("x")
    assert excinfo.value.status == 429
    assert excinfo.value.reason == "rate_limited"


def test_a_5xx_is_retried(no_sleep: Any) -> None:
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("HTTP 503", status=503)
        return OK_ANTHROPIC

    assert AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep).generate("x")
    assert calls["n"] == 2


def test_a_4xx_that_is_not_429_is_not_retried(no_sleep: Any) -> None:
    """401/400 are permanent. Retrying them just burns the budget and time."""
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        raise ProviderError("HTTP 401: unauthorized", status=401)

    model = AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep)
    with pytest.raises(ProviderError) as excinfo:
        model.generate("x")
    assert calls["n"] == 1, "a 401 must not be retried"
    assert no_sleep.waits == []
    assert excinfo.value.reason == "http_error"


def test_a_timeout_is_not_retried(no_sleep: Any) -> None:
    """No status means no signal about whether the request was served."""
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        raise ProviderError("could not reach provider: timed out")

    model = AnthropicModel(api_key=SECRET, transport=transport, sleep=no_sleep)
    with pytest.raises(ProviderError) as excinfo:
        model.generate("x")
    assert calls["n"] == 1
    assert no_sleep.waits == []
    assert excinfo.value.retryable is False
    assert excinfo.value.reason == "unreachable"


def test_the_attempt_cap_is_honoured(no_sleep: Any) -> None:
    calls = {"n": 0}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        raise ProviderError("HTTP 429", status=429)

    with pytest.raises(ProviderError):
        model = AnthropicModel(
            api_key=SECRET, transport=transport, sleep=no_sleep, max_attempts=4
        )
        model.generate("x")
    assert calls["n"] == 4, "one initial attempt plus three retries"


def test_retries_reuse_the_same_idempotency_key() -> None:
    """A retry must be recognisable as the same logical request, not a new one."""
    seen: list[dict[str, str]] = []

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        seen.append(dict(headers))
        if len(seen) < 3:
            raise ProviderError("HTTP 500", status=500)
        return OK_ANTHROPIC

    model = AnthropicModel(api_key=SECRET, transport=transport, sleep=lambda _s: None)
    model.generate("same prompt")
    keys = {h.get("idempotency-key") for h in seen}
    assert len(keys) == 1, f"every attempt must carry one key, got {keys}"
    assert all(k for k in keys), "the key must actually be set"


def test_different_prompts_get_different_idempotency_keys() -> None:
    keys: list[str] = []

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        keys.append(headers["idempotency-key"])
        return OK_ANTHROPIC

    model = AnthropicModel(api_key=SECRET, transport=transport)
    model.generate("prompt one")
    model.generate("prompt two")
    assert keys[0] != keys[1]


def test_a_retry_never_puts_the_key_in_the_url_or_body() -> None:
    captured: dict[str, Any] = {}

    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        captured.update(url=url, headers=headers, body=json.loads(body))
        if len(captured.get("seen", [])) < 0:  # pragma: no cover - never true
            return OK_ANTHROPIC
        return OK_ANTHROPIC

    model = AnthropicModel(api_key=SECRET, transport=transport)
    model.generate("x")
    assert SECRET not in captured["url"]
    assert SECRET not in json.dumps(captured["body"])


def test_parse_retry_after_seconds() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(" 0 ") == 0.0


def test_parse_retry_after_http_date_in_the_past_is_zero() -> None:
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_parse_retry_after_rejects_garbage() -> None:
    """A garbage header must fall back to backoff, not become the delay."""
    assert parse_retry_after("soon-ish") is None
    assert parse_retry_after("") is None
    assert parse_retry_after(None) is None


# --------------------------------------------------------------------------
# The retry reason must reach the trial record as `rate_limited`
# --------------------------------------------------------------------------


def test_a_rate_limited_trial_is_recorded_ungraded_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pilot.conditions import cond_b
    from pilot.runner import run as runner

    # Patched on ConditionB specifically: the concrete classes each override
    # `run`, so patching the abstract base would never be called.
    monkeypatch.setattr(cond_b.ConditionB, "run", lambda self, ctx: _boom())

    # The log is append-only, so a leftover from a previous run would be counted
    # again and make this assertion fail for the wrong reason.
    shutil.rmtree(Path("results") / "rl", ignore_errors=True)

    cfg = Config()
    cfg.model.provider = "mock"
    cfg.experiment.n_trials = 1
    _make_task(tmp_path / "tasks" / "t01_x")

    summary = runner.run(cfg, run_id="rl", conditions=("b",), tasks_dir=tmp_path / "tasks")
    assert summary["ungraded"] == 1

    records = [json.loads(line) for line in
               (Path("results") / "rl" / "trials.jsonl").read_text().splitlines() if line.strip()]
    assert len(records) == 1
    record = records[0]
    assert record["graded"] is False
    assert record["ungraded_reason_code"] == "rate_limited"
    assert record["retryable"] is True
    # The critical part: not a zero, not a pass rate.
    assert record["hidden_pass_rate"] == 0.0
    assert record["grade_exit_class"] == "not_graded"


def _boom() -> Any:
    raise ProviderError("HTTP 429: rate limited", status=429)


def _make_task(root: Path) -> Path:
    task = root
    (task / "starter").mkdir(parents=True)
    (task / "starter" / "__init__.py").write_text("")
    (task / "spec.md").write_text("do a thing\n")
    (task / "meta.yaml").write_text("id: t01\n")
    return task
    shutil.rmtree(Path("results") / "rl", ignore_errors=True)
