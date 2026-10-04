from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Model(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        pass
