from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]


class ModelConfig(BaseModel):
    id: str = Field(default=os.getenv("MODEL_ID", "mock"))
    provider: str = Field(default=os.getenv("PROVIDER", "mock"))
    temperature: float = Field(default=float(os.getenv("TEMPERATURE", "0.0")))
    seed: int | None = None
    max_tokens: int = Field(default=int(os.getenv("MAX_TOKENS", "2048")))


class ExperimentConfig(BaseModel):
    n_trials: int = Field(default=int(os.getenv("N_TRIALS", "20")))
    max_repair_rounds: int = Field(default=int(os.getenv("MAX_REPAIR_ROUNDS", "3")))
    max_cost_usd: float = Field(default=float(os.getenv("MAX_COST_USD", "10.0")))
    ablation: str | None = None


class SandboxConfig(BaseModel):
    docker_image: str = Field(default=os.getenv("DOCKER_IMAGE", "python:3.11-slim"))
    timeout_s: int = Field(default=int(os.getenv("SANDBOX_TIMEOUT_S", "120")))
    mem_limit_mb: int = Field(default=int(os.getenv("SANDBOX_MEM_LIMIT_MB", "512")))
    cpu_limit: float = Field(default=float(os.getenv("SANDBOX_CPU_LIMIT", "1.0")))
    network_disabled: bool = True


class Config(BaseModel):
    model: ModelConfig = ModelConfig()
    experiment: ExperimentConfig = ExperimentConfig()
    sandbox: SandboxConfig = SandboxConfig()
    root: Path = ROOT


def load_config() -> Config:
    return Config()
