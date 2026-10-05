"""Groq chat-completions adapter.

Groq exposes an OpenAI-compatible `/chat/completions` endpoint, so the request
and response handling is inherited rather than duplicated. Only the endpoint,
the credential, the default model, and the pricing differ.

On cost: Groq's free tier is free, but this adapter is deliberately *not*
priced at 0.0. A zero price makes `estimate_cost_usd` return 0.0, which makes
`within_budget` unconditionally True and switches the budget guard off -- so a
misconfigured `GROQ_BASE_URL` pointing at a paid endpoint would run unbounded.
These are nominal list figures for guard-rail purposes; override with
PRICE_IN_PER_MTOK / PRICE_OUT_PER_MTOK if they drift.
"""

from __future__ import annotations

from pilot.models.openai import OpenAIModel


class GroqModel(OpenAIModel):
    """Generate via Groq's OpenAI-compatible chat-completions API.

    No automatic retry: the POST is not idempotent, and on a rate-limited free
    tier an automatic retry would amplify the very 429 that caused it.
    """

    provider = "groq"
    env_key = "GROQ_API_KEY"
    default_model_id = "llama-3.3-70b-versatile"
    default_base_url = "https://api.groq.com/openai/v1"

    #: The only host a GROQ_API_KEY is ever sent to unless the operator
    #: deliberately overrides the base URL. See `official_hosts` in registry.py.
    official_hosts = ("api.groq.com",)
