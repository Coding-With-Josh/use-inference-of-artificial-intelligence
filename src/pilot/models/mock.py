from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pilot.models.base import Model


class MockModel(Model):
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def generate(self, prompt: str, **kwargs: Any) -> str:
        h = hashlib.md5((prompt + str(self.seed)).encode()).hexdigest()
        if "security" in prompt.lower() or "sql" in prompt.lower() or "path" in prompt.lower():
            return "insecure"
        if int(h[0], 16) < 8:
            return "correct"
        return "subtly_wrong"
