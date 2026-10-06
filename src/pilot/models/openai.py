"""OpenAI Chat Completions adapter."""

from __future__ import annotations

import json
from typing import Any

from pilot.models.http import _HttpModel


class OpenAIModel(_HttpModel):
    """Generate via the OpenAI Chat Completions API.

    Like the Anthropic adapter there is no automatic retry: the POST is not
    idempotent, so retrying after a timeout risks a second charge and a second,
    different completion for the same trial.
    """

    provider = "openai"
    env_key = "OPENAI_API_KEY"
    default_model_id = "gpt-4.1"
    default_base_url = "https://api.openai.com/v1"
    official_hosts = ("api.openai.com",)

    def _request(self, prompt: str, **kwargs: Any) -> tuple[str, dict[str, str], bytes]:
        messages: list[dict[str, str]] = []
        if system := kwargs.get("system"):
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": kwargs.get("model_id", self.model_id),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": messages,
        }
        if seed := kwargs.get("seed"):
            body["seed"] = seed
        # Bearer token in the header only -- never a query parameter.
        headers = {
            "authorization": f"Bearer {self._key.reveal()}",
            "content-type": "application/json",
        }
        headers.update(self._idempotency_headers(prompt, system))
        return f"{self.base_url}/chat/completions", headers, json.dumps(body).encode("utf-8")

    def _returned_model_id(self, payload: dict[str, Any]) -> str | None:
        """Both OpenAI and Groq echo the resolved model id in `model`."""
        name = payload.get("model")
        return str(name) if isinstance(name, str) else None

    def _unwrap(self, payload: dict[str, Any]) -> str:
        try:
            choices = payload["choices"]
        except (KeyError, TypeError):
            raise ValueError(
                f"openai: response had no 'choices' field: {sorted(payload)}"
            ) from None
        if not isinstance(choices, list) or not choices:
            raise ValueError("openai: 'choices' was empty or not a list")
        text = choices[0].get("message", {}).get("content", "")
        if not isinstance(text, str) or not text.strip():
            # An empty completion would be written out and graded as a genuine
            # (failing) attempt, which is a measurement error, not a result.
            raise ValueError("openai: response contained no assistant content")
        return text
