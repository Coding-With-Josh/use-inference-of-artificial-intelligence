"""Resolve a configured provider string to a model instance.

This is the single production path from config to a model. `run()` used to
construct `MockModel` unconditionally, which meant `PROVIDER=anthropic` produced
synthetic data while looking like a real run. Resolution is therefore an explicit
allow-list that *raises* on anything it does not recognise.

It deliberately does not fall back to the mock. A typo'd provider silently
becoming the mock is precisely the failure this module exists to prevent.
"""

from __future__ import annotations

from typing import Any

from pilot.config.config import Config, ModelConfig
from pilot.models.base import Model

# provider name -> (import path, class name). Imported lazily so that a missing
# optional dependency cannot break `import pilot.models`.
_REGISTRY: dict[str, tuple[str, str]] = {
    "mock": ("pilot.models.mock", "MockModel"),
    "anthropic": ("pilot.models.anthropic", "AnthropicModel"),
    "openai": ("pilot.models.openai", "OpenAIModel"),
    "groq": ("pilot.models.groq", "GroqModel"),
}

SUPPORTED_PROVIDERS = tuple(sorted(_REGISTRY))


def resolve(provider: str) -> type[Any]:
    """Return the adapter class for `provider`, or raise."""
    key = (provider or "").strip().lower()
    try:
        module_path, class_name = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"unknown provider {provider!r}; supported: {', '.join(SUPPORTED_PROVIDERS)}. "
            "Refusing to fall back to the mock model, because a silent fallback "
            "turns a real study into synthetic data."
        ) from None
    import importlib

    cls: type[Any] = getattr(importlib.import_module(module_path), class_name)
    return cls


def build_model(cfg: Config | None = None, **overrides: Any) -> Model:
    """Build the configured model.

    `overrides` wins over config, which wins over the environment. Used by tests
    to inject a fake transport without touching process env.
    """
    from pilot.config.config import load_config

    cfg = cfg or load_config()
    model_cfg: ModelConfig = cfg.model
    provider = overrides.pop("provider", None) or model_cfg.provider
    cls = resolve(provider)
    kwargs: dict[str, Any] = {
        # `ModelConfig.model_id` resolves the provider-specific default, so an
        # unset MODEL_ID never sends a literal "mock" to a real endpoint.
        "model_id": overrides.pop("model_id", None) or model_cfg.model_id(),
        "temperature": model_cfg.temperature,
        "max_tokens": model_cfg.max_tokens,
        # The single construction site, so the base-URL block cannot be bypassed.
        # `check_base_url` refuses here, before the trial loop and before any spend.
        "allow_custom_base_url": bool(model_cfg.allow_custom_base_url),
    }
    if overrides:
        kwargs.update(overrides)

    if provider == "mock":
        # MockModel's signature is (seed); it takes no credential and no transport.
        from pilot.models.mock import MockModel

        seed = kwargs.pop("seed", None) or model_cfg.seed or 42
        mock_model: Model = MockModel(seed=seed)
        return mock_model

    built: Model = cls(**kwargs)
    return built


def check_configured_base_url(cfg: Config | None = None) -> str | None:
    """Raise `BaseUrlBlocked` if the configured base URL would need the opt-in.

    Called from the CLI before a run, so the refusal happens as a configuration
    error with a clear exit code rather than as a `ProviderError` from inside the
    trial loop. Construction enforces the same rule; this is the earlier, cheaper
    check that gives the operator the message before any work starts.
    """
    from pilot.config.config import load_config
    from pilot.models.http import check_base_url

    cfg = cfg or load_config()
    provider = (cfg.model.provider or "").strip().lower()
    try:
        cls = resolve(provider)
    except ValueError:
        return None
    official = getattr(cls, "official_hosts", ())
    if not official:
        return None
    import os

    override = os.getenv(f"{provider.upper()}_BASE_URL")
    if not override:
        return None
    host = check_base_url(
        provider, override.rstrip("/"), official,
        allow_custom=bool(getattr(cfg.model, "allow_custom_base_url", False)),
    )
    return host or None


def describe_unusual_base_url(cfg: Config | None = None) -> str | None:
    """Return a note if a custom base URL is in effect, else None.

    Unlike `check_configured_base_url` this does not refuse: it is used on the
    paths where the operator has *already* opted in, to record in plain sight that
    the key is going somewhere other than the provider's own host.
    """
    from pilot.config.config import load_config

    cfg = cfg or load_config()
    provider = (cfg.model.provider or "").strip().lower()
    try:
        cls = resolve(provider)
    except ValueError:
        return None
    official = getattr(cls, "official_hosts", ())
    if not official:
        return None
    import os
    from urllib.parse import urlparse

    override = os.getenv(f"{provider.upper()}_BASE_URL")
    if not override:
        return None
    host = (urlparse(override).hostname or "").lower()
    if not host or any(host == k or host.endswith(f".{k}") for k in official):
        return None
    return (
        f"{provider}: sending {provider.upper()}_API_KEY to non-official host "
        f"{host!r} (official: {', '.join(official)}); recorded in trial provenance"
    )


def is_synthetic(cfg: Config | None = None) -> bool:
    """True when the configured provider is the mock.

    Every provenance field that says `synthetic` derives from this, so a real
    provider run can never be mislabelled as synthetic or vice versa.
    """
    from pilot.config.config import load_config

    cfg = cfg or load_config()
    return (cfg.model.provider or "").strip().lower() == "mock"
