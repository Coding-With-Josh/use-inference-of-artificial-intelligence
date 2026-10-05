from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Model(ABC):
    """The one interface every model -- mock or real provider -- implements.

    Conditions receive this type and nothing else, so a run can be executed with
    the mock and with a live provider without touching a single condition.
    """

    #: Configured provider name. Used for provenance and pricing lookups.
    provider: str = "unknown"

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Return the model's completion of `prompt`.

        Implementations must raise rather than return an empty string when a
        completion cannot be produced: an empty string would be written to disk
        and graded as a genuine (failing) attempt, which is a measurement error
        rather than a result.
        """

    def describe(self) -> dict[str, Any]:
        """Provenance for a run log.

        Records which model produced a result, never the credential used to reach
        it. Safe to log verbatim.
        """
        return {"provider": self.provider, "model_id": getattr(self, "model_id", None)}
