"""Anthropic Messages API adapter."""

from __future__ import annotations

import json
from typing import Any

from pilot.models.http import _HttpModel

API_VERSION = "2023-06-01"


class AnthropicModel(_HttpModel):
    """Generate via the Anthropic Messages API.

    Note on retries: there are none, deliberately. A POST that times out may
    still have been served, so an automatic retry can double-charge and can yield
    two different completions for the same trial. The runner records a provider
    failure as an *ungraded* trial and continues instead.
    """

    provider = "anthropic"
    env_key = "ANTHROPIC_API_KEY"
    default_model_id = "claude-sonnet-4-5"
    default_base_url = "https://api.anthropic.com/v1"
    official_hosts = ("api.anthropic.com",)

    def _request(self, prompt: str, **kwargs: Any) -> tuple[str, dict[str, str], bytes]:
        body = {
            "model": kwargs.get("model_id", self.model_id),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system := kwargs.get("system"):
            body["system"] = system
        # The key goes in the header and nowhere else. It is never interpolated
        # into the URL: URLs land in proxy logs, Referer headers, and access logs.
        headers = {
            "x-api-key": self._key.reveal(),
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        return f"{self.base_url}/messages", headers, json.dumps(body).encode("utf-8")

    def _unwrap(self, payload: dict[str, Any]) -> str:
        # Raise on a malformed envelope rather than returning "" -- an empty
        # string here would be written to a file and graded as a real attempt.
        try:
            blocks = payload["content"]
        except (KeyError, TypeError):
            raise ValueError(
                f"anthropic: response had no 'content' field: {sorted(payload)}"
            ) from None
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("anthropic: 'content' was empty or not a list")
        parts = [
            b.get("text", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "".join(parts)
        if not text.strip():
            raise ValueError("anthropic: response contained no text block")
        return text
