"""Provider adapters: credential handling, request shape, failure modes.

No test in this file contacts a provider or needs a key. Every adapter is
constructed with an injected fake transport, so the suite is deterministic,
offline, and costs nothing. The tests that matter most here are the negative
ones -- they assert that a credential does NOT appear in the places it would
land by accident.

Covered from the Phase 3 review:
  3.1 credential disclosure: header-only, never URL/body/log/repr/describe/exception
  3.2 untrusted response: no second JSONL record from a newline-bearing completion
  3.3 integrity: an unknown provider raises instead of silently becoming the mock
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from pilot.models.anthropic import AnthropicModel
from pilot.models.base import Model
from pilot.models.http import ProviderError, RedactedSecret, redact
from pilot.models.openai import OpenAIModel
from pilot.models.registry import SUPPORTED_PROVIDERS, build_model, is_synthetic, resolve

SECRET = "sk-ant-test-DEADBEEF-do-not-log-me"

ANTHROPIC_OK: dict[str, Any] = {"content": [{"type": "text", "text": "def f(): pass"}]}
OPENAI_OK: dict[str, Any] = {
    "choices": [{"message": {"role": "assistant", "content": "def f(): pass"}}]
}


def anthropic_ok(captured: dict[str, Any]) -> Any:
    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        captured.update(url=url, headers=headers, body=json.loads(body))
        return ANTHROPIC_OK

    return transport


def openai_ok(captured: dict[str, Any]) -> Any:
    def transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        captured.update(url=url, headers=headers, body=json.loads(body))
        return OPENAI_OK

    return transport


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's real key in their shell must not reach a test."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# Typed as `Any` on purpose: the parametrised tests need the *concrete*
# adapters' constructor keywords (api_key, transport) and attributes
# (env_key, model_id), which the abstract `Model` base does not declare.
Adapter = Any


def _adapters() -> list[tuple[Adapter, dict[str, Any]]]:
    return [(AnthropicModel, ANTHROPIC_OK), (OpenAIModel, OPENAI_OK)]


# --------------------------------------------------------------------------
# Interface conformance
# --------------------------------------------------------------------------


def test_both_adapters_satisfy_the_common_interface() -> None:
    assert issubclass(AnthropicModel, Model)
    assert issubclass(OpenAIModel, Model)
    assert AnthropicModel.provider == "anthropic"
    assert OpenAIModel.provider == "openai"


@pytest.mark.parametrize("cls,ok", _adapters())
def test_generate_returns_text_through_the_interface(cls: Adapter, ok: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    model = cls(api_key=SECRET, transport=cls_ok(cls, captured))
    assert model.generate("write a function") == "def f(): pass"
    assert captured["body"]["messages"][0]["content"] == "write a function"


def cls_ok(cls: Adapter, captured: dict[str, Any]) -> Any:
    return anthropic_ok(captured) if cls is AnthropicModel else openai_ok(captured)


# --------------------------------------------------------------------------
# 3.1 Credential disclosure
# --------------------------------------------------------------------------


def test_redacted_secret_never_reveals_itself() -> None:
    secret = RedactedSecret(SECRET)
    assert str(secret) == "<redacted>"
    assert repr(secret) == "<redacted>"
    assert f"{secret}" == "<redacted>"
    assert SECRET not in f"{secret!r} {secret}"
    assert json.dumps({"key": str(secret)}) == '{"key": "<redacted>"}'
    assert secret.reveal() == SECRET  # the single explicit escape hatch
    assert bool(RedactedSecret("")) is False


def test_redact_removes_every_occurrence_and_ignores_empty() -> None:
    assert SECRET not in redact(f"a {SECRET} b {SECRET}", SECRET)
    assert redact("clean", SECRET) == "clean"
    assert redact("clean", None, "") == "clean"


@pytest.mark.parametrize("cls,ok", _adapters())
def test_key_is_sent_in_the_header(cls: Adapter, ok: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    model = cls(api_key=SECRET, transport=cls_ok(cls, captured))
    model.generate("x")
    # OpenAI sends "Bearer <key>", so this must be a substring test.
    assert any(SECRET in value for value in captured["headers"].values())


@pytest.mark.parametrize("cls,ok", _adapters())
def test_key_never_appears_in_the_url_or_the_body(cls: Adapter, ok: dict[str, Any]) -> None:
    """Phase 3.1: a key in the URL leaks via Referer, proxy logs, access logs."""
    captured: dict[str, Any] = {}
    model = cls(api_key=SECRET, transport=cls_ok(cls, captured))
    model.generate("x")
    assert SECRET not in captured["url"]
    assert SECRET not in json.dumps(captured["body"])


@pytest.mark.parametrize("cls,ok", _adapters())
def test_key_absent_from_repr_and_describe(cls: Adapter, ok: dict[str, Any]) -> None:
    model = cls(api_key=SECRET, transport=lambda *a: ok)
    assert SECRET not in repr(model)
    assert SECRET not in str(model)
    described = model.describe()
    assert described["has_api_key"] is True
    assert SECRET not in json.dumps(described)
    # describe() is written into run provenance, so it must be safe to log verbatim.
    # An exact key set is asserted deliberately: it is what makes "no new field can
    # quietly start carrying the key" checkable. The provenance and retry fields
    # added here are non-secret by construction, and `base_url_host` is a hostname.
    assert set(described) == {
        "provider",
        "model_id",
        "requested_model_id",
        "returned_model_id",
        "temperature",
        "max_tokens",
        "base_url",
        "base_url_host",
        "allow_custom_base_url",
        "returned_model_ids",
        "retries",
        "has_api_key",
    }
    # The override is recorded rather than hidden, so a proxied run is identifiable.
    assert described["base_url_host"] == urlparse(described["base_url"]).netloc


@pytest.mark.parametrize("cls,ok", _adapters())
def test_provider_error_echoing_the_key_is_scrubbed(cls: Adapter, ok: dict[str, Any]) -> None:
    """Phase 3.1: error bodies can echo the Authorization header back at us."""

    def hostile(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        raise ProviderError(f"HTTP 401: invalid key {headers[list(headers)[0]]}")

    model = cls(api_key=SECRET, transport=hostile)
    with pytest.raises(ProviderError) as excinfo:
        model.generate("x")
    assert SECRET not in str(excinfo.value)
    assert "<redacted>" in str(excinfo.value)


@pytest.mark.parametrize("cls,ok", _adapters())
def test_missing_key_refuses_before_any_network_call(cls: Adapter, ok: dict[str, Any]) -> None:
    calls: list[int] = []

    def counting(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        calls.append(1)
        return ok

    model = cls(api_key="", transport=counting)
    with pytest.raises(ProviderError) as excinfo:
        model.generate("x")
    assert calls == [], "generate() must refuse before opening a connection"
    assert cls.env_key in str(excinfo.value)
    assert "never" in str(excinfo.value).lower()  # explains it is never logged


@pytest.mark.parametrize("cls,ok", _adapters())
def test_env_var_supplies_the_key_and_a_flag_cannot(cls: Adapter, ok: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    monkey = pytest.MonkeyPatch()
    monkey.setenv(cls.env_key, SECRET)
    try:
        model = cls(transport=cls_ok(cls, captured))
        model.generate("x")
        assert any(SECRET in value for value in captured["headers"].values())
    finally:
        monkey.undo()
    # No constructor parameter anywhere accepts a bare key except api_key=, which
    # is how a test injects one; there is deliberately no CLI flag for it.
    import inspect

    assert "api_key" in inspect.signature(cls.__init__).parameters


# --------------------------------------------------------------------------
# 3.2 Untrusted response handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cls,ok", _adapters())
def test_malformed_envelope_raises_rather_than_returning_empty(
    cls: Adapter, ok: dict[str, Any]
) -> None:
    """An empty string would be written out and graded as a real failing attempt.

    That is a measurement error, not a result, so it must raise.
    """
    bad_payloads: list[dict[str, Any]] = [
        {},
        {"content": []},
        {"content": [{"type": "text", "text": "  "}]},
        {"choices": []},
    ]
    for bad in bad_payloads:
        model = cls(api_key=SECRET, transport=lambda *a, b=bad: b)
        with pytest.raises(ValueError):
            model.generate("x")


@pytest.mark.parametrize("cls,ok", _adapters())
def test_completion_with_newlines_cannot_forge_a_second_trial_record(
    cls: Adapter, ok: dict[str, Any], tmp_path: Any
) -> None:
    """Phase 3.2: a hostile completion must not produce two lines in trials.jsonl.

    A forged record would make `_completed_keys` treat the trial as done on
    resume, silently dropping it from the results.
    """
    from pilot.logging.logger import JsonlLogger

    poisoned = 'x\n{"task_id": "forged", "condition": "a", "graded": true, "hidden_pass_rate": 1.0}'
    payload = (
        {"content": [{"type": "text", "text": poisoned}]}
        if cls is AnthropicModel
        else {"choices": [{"message": {"content": poisoned}}]}
    )
    model = cls(api_key=SECRET, transport=lambda *a: payload)
    text = model.generate("x")

    logger = JsonlLogger("jsonl-injection", tmp_path)
    logger.log_trial({"task_id": "real", "condition": "a", "note": text})

    lines = (tmp_path / "results" / "jsonl-injection" / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_id"] == "real"

    from pilot.runner.run import _completed_keys

    completed = _completed_keys(tmp_path / "results" / "jsonl-injection" / "trials.jsonl")
    # The key is (task_id, condition, trial_index); a forged record lacking a
    # trial_index would otherwise be resumable as ("forged", "a", 0).
    assert completed == {("real", "a", 0)}, "forged trial key must not be resumable"
    assert ("forged", "a", 0) not in completed


# --------------------------------------------------------------------------
# 3.3 Registry integrity -- no silent synthetic substitution
# --------------------------------------------------------------------------


def test_unknown_provider_raises_instead_of_falling_back_to_mock() -> None:
    """Phase 3.3: a typo'd PROVIDER must not quietly produce synthetic data."""
    with pytest.raises(ValueError) as excinfo:
        resolve("anthropicc")
    message = str(excinfo.value)
    assert "unknown provider" in message
    assert "synthetic" in message
    for provider in SUPPORTED_PROVIDERS:
        assert provider in message


@pytest.mark.parametrize("provider", ["MOCK ", "Mock", " mock\n"])
def test_provider_matching_is_normalised(provider: str) -> None:
    assert resolve(provider).__name__ == "MockModel"


@pytest.mark.parametrize("provider", ["", "   ", None])
def test_blank_provider_raises_rather_than_becoming_the_mock(provider: str | None) -> None:
    """An unset/blank PROVIDER must not silently resolve to the mock.

    Asserting the opposite was the fail-open bug this registry is meant to close.
    """
    with pytest.raises(ValueError):
        resolve(provider)  # type: ignore[arg-type]


def test_supported_providers_are_exactly_the_known_adapters() -> None:
    """An exhaustive list on purpose: a new adapter must be a deliberate act.

    If this fails after adding a provider, the adapter is registered but its
    tests are not, and it would be reachable in production unverified.
    """
    assert set(SUPPORTED_PROVIDERS) == {"mock", "anthropic", "openai", "groq"}


def test_build_model_returns_the_mock_for_the_mock_provider() -> None:
    from pilot.config.config import Config
    from pilot.models.mock import MockModel

    cfg = Config()
    cfg.model.provider = "mock"
    assert isinstance(build_model(cfg), MockModel)
    assert is_synthetic(cfg) is True


def test_build_model_rejects_unknown_provider_at_construction() -> None:
    from pilot.config.config import Config

    cfg = Config()
    cfg.model.provider = "definitely-not-a-provider"
    with pytest.raises(ValueError):
        build_model(cfg)


def test_an_unset_model_id_resolves_per_provider_not_to_mock() -> None:
    """An unset MODEL_ID must resolve to the provider's own default.

    One shared `id` field used to default to the literal "mock", which a real
    endpoint would reject. Each provider now resolves its own default.
    """
    from pilot.config.config import Config

    for provider, expected in (
        ("anthropic", AnthropicModel.default_model_id),
        ("openai", OpenAIModel.default_model_id),
    ):
        cfg = Config()
        cfg.model.provider = provider
        cfg.model.id = ""
        assert cfg.model.model_id() == expected
        assert cfg.model.model_id() != "mock"


def test_an_explicit_model_id_is_respected() -> None:
    from pilot.config.config import Config

    cfg = Config()
    cfg.model.provider = "anthropic"
    cfg.model.id = "claude-opus-4-1"
    built = build_model(cfg, transport=lambda *a: ANTHROPIC_OK)
    assert built.describe()["model_id"] == "claude-opus-4-1"


def test_real_provider_is_not_labelled_synthetic() -> None:
    from pilot.config.config import Config

    cfg = Config()
    cfg.model.provider = "anthropic"
    assert is_synthetic(cfg) is False


# --------------------------------------------------------------------------
# Pricing is provider-denominated (Phase 3.3: wrong-currency budget guard)
# --------------------------------------------------------------------------


def test_pricing_differs_by_provider() -> None:
    from pilot.config.config import Config

    mock, real = Config(), Config()
    mock.model.provider, real.model.provider = "mock", "openai"
    assert mock.model.pricing() != real.model.pricing()


def test_pricing_can_be_overridden_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from pilot.config.config import ModelConfig

    monkeypatch.setenv("PRICE_IN_PER_MTOK", "1.25")
    monkeypatch.setenv("PRICE_OUT_PER_MTOK", "9.5")
    assert ModelConfig().pricing() == (1.25, 9.5)


def test_provider_env_vars_are_read_at_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_config() must observe the current environment.

    These fields used to be a shared instance built at class-definition time, so
    'configurable by env vars' held only until the first import.
    """
    from pilot.config.config import load_config

    monkeypatch.setenv("PROVIDER", "openai")
    monkeypatch.setenv("MODEL_ID", "gpt-4.1-mini")
    monkeypatch.setenv("MAX_TOKENS", "4096")
    cfg = load_config()
    assert cfg.model.provider == "openai"
    assert cfg.model.id == "gpt-4.1-mini"
    assert cfg.model.max_tokens == 4096

    monkeypatch.setenv("PROVIDER", "anthropic")
    assert load_config().model.provider == "anthropic", "stale cached config"


def test_config_sub_configs_are_not_shared_between_instances() -> None:
    from pilot.config.config import load_config

    a, b = load_config(), load_config()
    assert a.model is not b.model
    assert a.sandbox is not b.sandbox
    assert a.experiment is not b.experiment


# --------------------------------------------------------------------------
# Groq
# --------------------------------------------------------------------------


def test_groq_is_a_registered_provider() -> None:
    from pilot.models.groq import GroqModel

    assert "groq" in SUPPORTED_PROVIDERS
    assert resolve("groq") is GroqModel
    assert issubclass(GroqModel, Model)


def test_groq_speaks_the_openai_compatible_shape() -> None:
    """Groq reuses OpenAI's request/response handling rather than duplicating it."""
    from pilot.models.groq import GroqModel

    assert issubclass(GroqModel, OpenAIModel)
    assert GroqModel.env_key == "GROQ_API_KEY"
    assert GroqModel.provider == "groq"
    assert GroqModel.official_hosts == ("api.groq.com",)


def test_groq_resolves_its_own_default_model_not_the_mock() -> None:
    from pilot.config.config import Config

    cfg = Config()
    cfg.model.provider = "groq"
    cfg.model.id = ""
    assert cfg.model.model_id() == "llama-3.3-70b-versatile"
    built = build_model(cfg, transport=lambda *a: OPENAI_OK)
    assert built.describe()["model_id"] == "llama-3.3-70b-versatile"
    assert built.describe()["model_id"] != "mock"


def test_groq_request_shape_and_key_placement() -> None:
    from pilot.models.groq import GroqModel

    captured: dict[str, Any] = {}
    model = GroqModel(api_key=SECRET, transport=openai_ok(captured))
    model.generate("write a function", system="be terse")

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert any(SECRET in v for v in captured["headers"].values()), "key must be in a header"
    assert SECRET not in captured["url"], "Phase 3.1: never a URL parameter"
    assert SECRET not in json.dumps(captured["body"])
    # The system message is passed through, not dropped.
    assert captured["body"]["messages"][0] == {"role": "system", "content": "be terse"}


def test_groq_key_is_read_from_its_own_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from pilot.models.groq import GroqModel

    captured: dict[str, Any] = {}
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    GroqModel(transport=openai_ok(captured)).generate("x")
    assert any(SECRET in v for v in captured["headers"].values())


def test_groq_missing_key_names_groq_api_key() -> None:
    from pilot.models.groq import GroqModel

    with pytest.raises(ProviderError) as excinfo:
        GroqModel(api_key="", transport=lambda *a: OPENAI_OK).generate("x")
    assert "GROQ_API_KEY" in str(excinfo.value)


def test_groq_is_not_priced_at_zero() -> None:
    """A 0.0 price would make estimate_cost_usd return 0.0, which would make
    within_budget unconditionally True and switch the budget guard off -- so a
    misconfigured GROQ_BASE_URL pointing at a paid endpoint could run unbounded.
    """
    from pilot.config.config import Config
    from pilot.scoring import metrics

    cfg = Config()
    cfg.model.provider = "groq"
    price_in, price_out = cfg.model.pricing()
    assert price_in > 0 and price_out > 0

    cfg.experiment.n_trials = 20
    assert runner_plan(cfg)["within_budget"] is True
    cfg.experiment.max_cost_usd = 0.0001
    assert runner_plan(cfg)["within_budget"] is False, "budget guard must still bite"

    assert metrics.estimate_cost_usd(1000, 1000, price_in, price_out) > 0


def runner_plan(cfg: Any) -> dict[str, Any]:
    from pilot.runner import run as runner

    return runner.plan(cfg)


def test_default_provider_is_groq_but_study_paths_pin_the_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default is groq; the watermarked paths must not inherit it.

    `demo-mock` promises to be offline and synthetic. If it inherited the
    ambient provider, a key in the operator's shell would make a real billed run
    whose manifest still asserted `synthetic: true`.
    """
    from pilot.config.config import load_config

    monkeypatch.delenv("PROVIDER", raising=False)
    assert load_config().model.provider == "groq"

    from typer.testing import CliRunner

    from pilot.cli import app

    monkeypatch.setenv("PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    result = CliRunner().invoke(app, ["demo-mock", "--dry-run"])
    assert result.exit_code == 0, result.output

    manifest_path = (
        Path(__file__).resolve().parents[1] / "results" / "demo-mock" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["provider"] == "mock", "demo-mock must pin the mock"
    assert manifest["synthetic"] is True
