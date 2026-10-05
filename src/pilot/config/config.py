from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]


# Illustrative list prices, USD per million tokens, used only to estimate spend
# before a run. The mock costs nothing to serve; its figures exist so the budget
# guard has something to check before a real provider is used. Override per
# provider with PRICE_IN_PER_MTOK / PRICE_OUT_PER_MTOK when these drift.
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "mock": (3.0, 15.0),
    "anthropic": (3.0, 15.0),
    "openai": (2.0, 8.0),
    # Nominal, not zero: see pilot/models/groq.py. A 0.0 price would make
    # estimate_cost_usd return 0.0, which would make within_budget
    # unconditionally True and disable the budget guard entirely.
    "groq": (0.59, 0.79),
}


class ModelConfig(BaseModel):
    # Default provider. Groq, because it has a usable free tier; override with
    # PROVIDER=mock for an offline run, or PROVIDER=anthropic / openai.
    #
    # Note that "default" means the default for a *study* run. The paths whose
    # contract is to be offline and synthetic -- `demo-mock` and the test suite
    # -- pin provider="mock" explicitly rather than inheriting this value, so a
    # key in the environment cannot turn a watermarked pipeline test into a
    # real billed API run.
    provider: str = Field(default_factory=lambda: os.getenv("PROVIDER", "groq"))
    # A model id is provider-specific, so the default depends on the provider.
    # `ModelConfig.model_id` resolves it; this stays as the raw env override.
    id: str = Field(default_factory=lambda: os.getenv("MODEL_ID", ""))
    temperature: float = Field(
        default_factory=lambda: float(os.getenv("TEMPERATURE", "0.0"))
    )
    seed: int | None = None
    max_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "2048")))
    # Left None so the per-provider default applies unless explicitly overridden.
    price_in_per_mtok: float | None = Field(
        default_factory=lambda: (
            float(os.environ["PRICE_IN_PER_MTOK"])
            if "PRICE_IN_PER_MTOK" in os.environ
            else None
        )
    )
    price_out_per_mtok: float | None = Field(
        default_factory=lambda: (
            float(os.environ["PRICE_OUT_PER_MTOK"])
            if "PRICE_OUT_PER_MTOK" in os.environ
            else None
        )
    )

    def model_id(self) -> str:
        """The model to request, defaulting to the provider's own.

        `ModelConfig.id` is provider-agnostic (it comes from one shared
        MODEL_ID env var), so leaving it unset must NOT send a literal "mock"
        to Groq -- that is a 404. Resolve it per provider here.
        """
        configured = (self.id or "").strip()
        if configured:
            return configured
        try:
            from pilot.models.registry import resolve

            return str(getattr(resolve(self.provider), "default_model_id", ""))
        except (ValueError, ImportError):
            return ""

    def pricing(self) -> tuple[float, float]:
        """(price_in, price_out) per Mtok for the configured provider.

        Derived from the provider rather than hardcoded at the call site, so the
        budget guard is denominated in the currency the provider actually bills
        in. An unrecognised provider falls back to the mock figures and says so
        via a warning rather than silently estimating at $0.
        """
        key = (self.provider or "").strip().lower()
        default = DEFAULT_PRICING.get(key, DEFAULT_PRICING["mock"])
        return (
            self.price_in_per_mtok if self.price_in_per_mtok is not None else default[0],
            self.price_out_per_mtok if self.price_out_per_mtok is not None else default[1],
        )


class ExperimentConfig(BaseModel):
    n_trials: int = Field(default_factory=lambda: int(os.getenv("N_TRIALS", "20")))
    max_repair_rounds: int = Field(
        default_factory=lambda: int(os.getenv("MAX_REPAIR_ROUNDS", "3"))
    )
    max_cost_usd: float = Field(
        default_factory=lambda: float(os.getenv("MAX_COST_USD", "10.0"))
    )
    # Comma-separated, matching docs/conditions.md: context,decomposition,guardrails.
    # Validated here rather than at the point of use, so an unsupported ablation
    # is reported by `study1-plan` instead of silently running a full condition C.
    ablation: str | None = Field(default_factory=lambda: os.getenv("ABLATION") or None)


class SandboxConfig(BaseModel):
    # Must match the tag built by `make sandbox-image`. The runner refuses (it
    # does not fall back) when this image is absent, so a wrong default shows up
    # as an actionable error instead of a mysterious container-exec failure.
    docker_image: str = Field(
        default_factory=lambda: os.getenv("DOCKER_IMAGE", "pilot-sandbox:latest")
    )
    timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT_S", "120"))
    )
    mem_limit_mb: int = Field(
        default_factory=lambda: int(os.getenv("SANDBOX_MEM_LIMIT_MB", "512"))
    )
    cpu_limit: float = Field(
        default_factory=lambda: float(os.getenv("SANDBOX_CPU_LIMIT", "1.0"))
    )
    network_disabled: bool = True


class Config(BaseModel):
    # default_factory, not a shared instance. `model = ModelConfig()` was
    # evaluated once at class-definition time, so every later change to the
    # environment was invisible to load_config() -- "configurable by env vars"
    # was true only until the first import.
    model: ModelConfig = Field(default_factory=ModelConfig)
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    root: Path = ROOT


def load_config() -> Config:
    return Config()
