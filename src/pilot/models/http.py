"""Provider adapters behind the common `Model` interface.

Both adapters speak HTTP through an injectable transport rather than importing a
vendor SDK. That is deliberate on two counts:

  * The study must run with no network, and the sandbox forbids it. A vendored SDK
    would make "does this code make an unexpected call?" hard to answer.
  * Tests inject a fake transport and therefore never contact a provider, never
    need a key, and never spend money. Nothing in this test suite performs a real
    API call.

Keys come from the environment only. They are read into the adapter instance and
never returned by any attribute, `repr`, exception message, or log record -- see
`RedactedSecret` and `redact()`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from pilot.models.base import Model

# A transport takes (url, headers, body) and returns the decoded JSON response.
Transport = Callable[[str, dict[str, str], bytes], dict[str, Any]]


class ProviderError(RuntimeError):
    """A provider call failed.

    The message is built from the response body with secrets already redacted, so
    raising this can never leak a key into a traceback.
    """


class RedactedSecret:
    """A string that refuses to reveal itself.

    `str(secret)` returns a placeholder, so the value cannot reach a log line, an
    f-string, a repr in a traceback, or a JSON dump by accident. `reveal()` is the
    single explicit way out, and it is called only where the wire format needs it.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "<redacted>"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        # Length is safe to expose and useful for "is this set?" checks without
        # revealing the value.
        return len(self._value)


def redact(text: str, *secrets: str | None) -> str:
    """Replace any non-empty secret occurring in `text` with a placeholder."""
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


class HttpTransport(Protocol):
    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]: ...


def urllib_transport(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
    """The real transport. Only reached when a run actually has a key set."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            decoded: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            return decoded
    except urllib.error.HTTPError as err:
        # The error body can echo the Authorization header back; redact before it
        # becomes an exception message.
        detail = err.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"HTTP {err.code}: {detail}") from None
    except urllib.error.URLError as err:
        raise ProviderError(f"could not reach provider: {err.reason}") from None


class _HttpModel(Model):
    """Shared plumbing for the HTTP providers: endpoint construction, auth header,
    response unwrapping.

    Subclasses `Model`, so `isinstance(adapter, Model)` is true and the runner's
    credential guard actually fires. Without this the adapters satisfied no
    interface at all and every caller's type check silently did nothing.
    """

    provider = ""
    env_key = ""
    default_model_id = ""
    default_base_url = ""

    #: Hosts this provider's credential may legitimately be sent to. Used only to
    #: *warn* when a *_BASE_URL override points elsewhere -- proxies are legitimate,
    #: so this never blocks. See `warn_if_unusual_base_url`.
    official_hosts: tuple[str, ...] = ()

    def __init__(
        self,
        model_id: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.model_id = model_id or os.getenv("MODEL_ID") or self.default_model_id
        key = api_key if api_key is not None else os.getenv(self.env_key, "")
        # Stored wrapped, so `self._key` is not a plain string anywhere.
        self._key = RedactedSecret(key)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = (base_url or os.getenv(f"{self.provider.upper()}_BASE_URL")
                         or self.default_base_url).rstrip("/")
        self._transport: Transport = transport or urllib_transport

    # -- Model interface ---------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self._key:
            raise ProviderError(
                f"{self.provider}: no API key. Set {self.env_key} in the environment. "
                "Keys are never accepted as command-line arguments and are never logged."
            )
        url, headers, body = self._request(prompt, **kwargs)
        try:
            payload = self._transport(url, headers, body)
        except ProviderError as err:
            raise ProviderError(redact(str(err), self._key.reveal())) from None
        return self._unwrap(payload)

    # -- provider hooks ----------------------------------------------------

    def _request(self, prompt: str, **kwargs: Any) -> tuple[str, dict[str, str], bytes]:
        raise NotImplementedError

    def _unwrap(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def auth_headers(self) -> dict[str, str]:
        return {}

    def describe(self) -> dict[str, Any]:
        """Provenance for a run log: identifies the model, never the credential."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
            "has_api_key": bool(self._key),
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider={self.provider!r}, model_id={self.model_id!r}, "
            f"has_api_key={bool(self._key)})"
        )

    __str__ = __repr__
