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

import hashlib
import json
import os
import time
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

    `status` and `retry_after` carry the transport's view of the failure so the
    retry policy can be a decision about the *status code* rather than a substring
    match on a message. Both are None for transport-level failures (no HTTP
    response was ever received).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Whether retrying this specific failure is safe and bounded.

        429 means the request was rejected before execution, so no completion
        exists to double-charge -- safe. 5xx is ambiguous: the provider may have
        completed the request and failed on the response path, so a retry can
        double-charge. It is retried anyway (the alternative is losing the trial
        to a transient blip) but mitigated with an Idempotency-Key and bounded by
        a small attempt cap.

        Everything else -- notably a timeout or a refused connection -- is NOT
        retryable. There is no HTTP status, no `Retry-After` to bound the wait,
        and no signal about whether the request was served.
        """
        if self.status is None:
            return False
        return self.status == 429 or 500 <= self.status <= 599

    @property
    def reason(self) -> str:
        """A short machine-readable code for the trial record."""
        if self.status == 429:
            return "rate_limited"
        if self.status is not None and 500 <= self.status <= 599:
            return "provider_error"
        if self.status is not None:
            return "http_error"
        return "unreachable"


class BaseUrlBlocked(ProviderError):
    """A custom base URL was configured without the explicit opt-in.

    Separate from `ProviderError` so the CLI can exit with the configuration-error
    code rather than the provider-error code, and so it cannot be mistaken for a
    transient provider problem and retried.
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


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Parse a `Retry-After` header into seconds.

    The header is either delta-seconds or an HTTP-date. A date is converted
    against the current clock, so it becomes a small number when it is already in
    the past rather than a large negative one.

    Unparseable input returns None: the caller then falls back to its own
    exponential schedule. Guessing is worse than ignoring, because a garbage value
    silently becomes the retry delay.
    """
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    import datetime as _dt

    if target.tzinfo is None:
        target = target.replace(tzinfo=_dt.UTC)
    now_dt = _dt.datetime.now(_dt.UTC) if now is None else _dt.datetime.fromtimestamp(now, _dt.UTC)
    return max(0.0, (target - now_dt).total_seconds())


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
        # Status and Retry-After are carried structurally, so the retry policy
        # never has to parse them back out of the message text.
        raise ProviderError(
            f"HTTP {err.code}: {detail}",
            status=err.code,
            retry_after=parse_retry_after(err.headers.get("Retry-After")),
        ) from None
    except urllib.error.URLError as err:
        # No HTTP response was received: no status, therefore not retryable.
        raise ProviderError(f"could not reach provider: {err.reason}") from None


#: Upper bound on any single wait between attempts. A provider-supplied
#: `Retry-After: 86400` is data from an untrusted remote party; without a cap it
#: silently stalls a study run for a day. Exceeding it is reported in the trial
#: record rather than hidden.
MAX_RETRY_AFTER_S = 60.0

#: Default attempt count, including the first. Small on purpose: a free tier that
#: rate-limits for minutes is not going to be served by four rapid retries, and
#: each retry of a 5xx risks a second charge.
DEFAULT_MAX_ATTEMPTS = 4

#: First backoff delay; subsequent delays double it.
DEFAULT_RETRY_BASE_S = 1.0


def check_base_url(provider: str, base_url: str, official_hosts: tuple[str, ...],
                   *, allow_custom: bool) -> str:
    """Return the host of `base_url`, or refuse if it is not an official one.

    Blocking is the default because a `*_BASE_URL` override redirects the API key
    to whatever host it names. Proxies and gateways are legitimate, so an operator
    who needs one must say so explicitly -- an override that silently redirects a
    credential is exactly the kind of thing that should be a deliberate act and a
    line in the provenance record, not a forgotten environment variable.

    Refusing happens in the constructor, so a misconfiguration costs nothing: no
    trial runs and no spend occurs.
    """
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    if not official_hosts:
        # Provider declares no official host (the mock): nothing to check.
        return host
    if host and any(host == known or host.endswith(f".{known}") for known in official_hosts):
        return host
    if allow_custom:
        return host
    raise BaseUrlBlocked(
        f"{provider}: base URL host {host or base_url!r} is not an official {provider} "
        f"host ({', '.join(official_hosts)}). Overriding it sends {provider.upper()}_API_KEY "
        "to that host instead. If this is a proxy or gateway you trust, re-run with "
        "--allow-custom-base-url; the override is then recorded in every trial's "
        "provenance. To go back to the default, unset the *_BASE_URL variable."
    )


class _HttpModel(Model):
    """Shared plumbing for the HTTP providers: endpoint construction, auth header,
    response unwrapping, retry policy.

    Subclasses `Model`, so `isinstance(adapter, Model)` is true and the runner's
    credential guard actually fires. Without this the adapters satisfied no
    interface at all and every caller's type check silently did nothing.
    """

    provider = ""
    env_key = ""
    default_model_id = ""
    default_base_url = ""

    #: Hosts this provider's credential may legitimately be sent to. A base URL
    #: outside this set is refused unless the operator passed
    #: `--allow-custom-base-url`. See `check_base_url`.
    official_hosts: tuple[str, ...] = ()

    def __init__(
        self,
        model_id: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        base_url: str | None = None,
        transport: Transport | None = None,
        *,
        allow_custom_base_url: bool = False,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_s: float = DEFAULT_RETRY_BASE_S,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.model_id = model_id or os.getenv("MODEL_ID") or self.default_model_id
        key = api_key if api_key is not None else os.getenv(self.env_key, "")
        # Stored wrapped, so `self._key` is not a plain string anywhere.
        self._key = RedactedSecret(key)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = (base_url or os.getenv(f"{self.provider.upper()}_BASE_URL")
                         or self.default_base_url).rstrip("/")
        # Refused here rather than at first request: construction happens before
        # the trial loop, so a bad base URL stops the run at zero cost.
        self.base_url_host = check_base_url(
            self.provider, self.base_url, self.official_hosts, allow_custom=allow_custom_base_url
        )
        self.allow_custom_base_url = bool(allow_custom_base_url)
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_s = float(retry_base_s)
        # Injectable so the backoff schedule is tested without wall-clock delay.
        self._sleep = sleep if sleep is not None else time.sleep
        self._transport: Transport = transport or urllib_transport
        #: Distinct model names the API reported answering, across every call this
        #: instance made. Compared against the requested id in the report, because
        #: a provider that silently routes a request elsewhere is otherwise
        #: invisible in the results.
        self.returned_model_ids: list[str] = []
        #: Retries performed, exposed in each trial's provenance.
        self.retry_count = 0

    # -- Model interface ---------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self._key:
            raise ProviderError(
                f"{self.provider}: no API key. Set {self.env_key} in the environment. "
                "Keys are never accepted as command-line arguments and are never logged."
            )
        url, headers, body = self._request(prompt, **kwargs)
        attempt = 0
        while True:
            attempt += 1
            try:
                payload = self._transport(url, headers, body)
            except ProviderError as err:
                # Rebuild with the secret scrubbed but the status preserved: the
                # retry policy reads `err.retryable`, which needs it.
                scrubbed = ProviderError(
                    redact(str(err), self._key.reveal()),
                    status=err.status,
                    retry_after=err.retry_after,
                )
                if attempt >= self.max_attempts or not scrubbed.retryable:
                    raise scrubbed from None
                self._sleep(self._delay(scrubbed.retry_after, attempt))
                self.retry_count += 1
                continue
            self._record_returned_model(payload)
            return self._unwrap(payload)

    def _delay(self, retry_after: float | None, attempt: int) -> float:
        """Seconds to wait before the next attempt.

        A provider-supplied `Retry-After` wins over the exponential schedule, but
        is capped: the header is untrusted remote input and an uncapped
        `Retry-After: 86400` would stall the run indefinitely.
        """
        if retry_after is not None:
            return min(float(retry_after), MAX_RETRY_AFTER_S)
        return min(self.retry_base_s * float(2 ** (attempt - 1)), MAX_RETRY_AFTER_S)

    def _record_returned_model(self, payload: dict[str, Any]) -> None:
        name = self._returned_model_id(payload)
        if name and name not in self.returned_model_ids:
            self.returned_model_ids.append(str(name))

    # -- provider hooks ----------------------------------------------------

    def _returned_model_id(self, payload: dict[str, Any]) -> str | None:
        """The model name the API reported, if its envelope carries one."""
        return None

    def _request(self, prompt: str, **kwargs: Any) -> tuple[str, dict[str, str], bytes]:
        raise NotImplementedError

    def _unwrap(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def auth_headers(self) -> dict[str, str]:
        return {}

    def _idempotency_headers(self, prompt: str, system: Any = None) -> dict[str, str]:
        """A stable key for one logical request, so a retry is not a second request.

        Derived from the request content rather than a counter, so it is identical
        across every attempt at the *same* call and different for a different
        call. This is what makes retrying a 5xx tolerable: a conforming provider
        dedupes on the key and returns the original result rather than generating
        and billing a second completion.

        It does not remove the double-charge risk on its own -- a provider that
        ignores the header still bills twice -- which is why the retry count is
        recorded and the attempt cap is small.
        """
        digest = hashlib.sha256(
            "\x00".join([self.provider, self.model_id, str(system or ""), prompt]).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()
        return {"idempotency-key": f"pilot-{digest[:32]}"}

    def describe(self) -> dict[str, Any]:
        """Provenance for a run log: identifies the model, never the credential."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
            "has_api_key": bool(self._key),
            **self.provenance(),
        }

    def provenance(self) -> dict[str, Any]:
        """The four fields recorded on every trial this model produces.

        `requested_model_id` is what we asked for and `returned_model_id` is what
        the API said answered. They can differ -- an alias, a deprecation
        redirect, a gateway that rewrites the model -- and when they do, the
        results describe a model the study did not name. `returned_model_id` is
        None when the provider's envelope does not carry one, which is itself
        worth knowing rather than papering over with the requested id.
        """
        return {
            "provider": self.provider,
            "base_url_host": self.base_url_host,
            "requested_model_id": self.model_id,
            "returned_model_id": self.returned_model_ids[0] if self.returned_model_ids else None,
            "returned_model_ids": list(self.returned_model_ids),
            "allow_custom_base_url": self.allow_custom_base_url,
            "retries": self.retry_count,
        }

    def reset_provenance(self) -> None:
        """Clear the per-trial call record, so it describes one trial.

        Called by the runner before each trial. Without it, a long run's records
        all accumulate every model name the adapter ever saw, and the `retries`
        count becomes the run total rather than the trial's own.
        """
        self.returned_model_ids = []
        self.retry_count = 0

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider={self.provider!r}, model_id={self.model_id!r}, "
            f"has_api_key={bool(self._key)})"
        )

    __str__ = __repr__
