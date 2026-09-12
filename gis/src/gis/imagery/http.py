"""Shared HTTP: session reuse, retry/backoff, and the User-Agent policy.

★ **``httpx`` IS BOUND AT CALL TIME, INSIDE THE REQUEST FUNCTION — NEVER AT MODULE SCOPE**
(§11.3). ``httpx`` is in ``gis``'s **base** dependencies (the provider registry imports
every provider eagerly, so it cannot be an extra) **and** it is call-time bound (so the
test suite collects with httpx absent). Both facts are deliberate and neither is
redundant: ``import gis.imagery.providers`` must succeed, and every provider's
``__init__``, ``is_configured()``, ``capabilities()`` and ``name`` must work, on a machine
where httpx is not installed. Only an actual fetch raises — and it raises
``ProviderTransportError``, a typed ``gis`` error, never ``ImportError``.

Every network provider funnels through ``fetch_bytes()``. That is what makes the
User-Agent policy, the timeout, the retry budget and the error taxonomy uniform rather
than per-provider folklore.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Mapping
from typing import Any, Final

from gis.errors import (
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTransportError,
    TileNotAvailableError,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "HttpConfig",
    "close_clients",
    "fetch_bytes",
    "fetch_json",
    "httpx_available",
    "post_form",
    "post_json",
]

_log = logging.getLogger("gis.imagery.http")

DEFAULT_USER_AGENT: Final[str] = "LandExplorer/1.0 (+https://example.invalid)"
"""★ Operators should set a real contact via ``LE_IMAGERY_USER_AGENT``.

Several providers' terms REQUIRE an identifying User-Agent, and for the keyless default
it is the only way Esri can identify and contact us. Silent aggressive scraping from an
anonymous UA is how a keyless endpoint stops being keyless for everyone.
"""

_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
_NOT_AVAILABLE_STATUS: Final[frozenset[int]] = frozenset({404, 204})
"""★ A 404 is a PERMANENT answer worth caching as a negative (open ocean, a coverage gap);
a 503 is transient and must be retried. Collapsing the two means either hammering a
provider for tiles that will never exist, or permanently caching a blank tile because of
one bad minute."""
_UNAUTHORISED_STATUS: Final[frozenset[int]] = frozenset({401, 403})


class HttpConfig:
    """Per-request HTTP policy. A plain object: ``gis`` carries no settings framework."""

    __slots__ = ("max_retries", "rate_limit_rps", "timeout_seconds", "user_agent")

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        rate_limit_rps: float | None = None,
    ) -> None:
        """Build an HTTP policy.

        Args:
            user_agent: Sent on every request. See ``DEFAULT_USER_AGENT``.
            timeout_seconds: Per-attempt timeout.
            max_retries: Additional attempts after the first. 0 means one attempt.
            rate_limit_rps: Token-bucket budget, or None for unlimited.
        """
        self.user_agent = user_agent
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.rate_limit_rps = rate_limit_rps


def httpx_available() -> tuple[bool, str | None]:
    """Report whether ``httpx`` can be bound. ★ Total; callable with httpx absent.

    Uses ``importlib.util.find_spec`` rather than an import: discovering a dependency
    should have no side effects.

    Returns:
        ``(available, reason)``. ``reason`` is None when available, else a sentence
        naming the fix.
    """
    import importlib.util  # noqa: PLC0415 - stdlib, but keeps module scope minimal

    if importlib.util.find_spec("httpx") is None:
        return (False, "requires httpx (pip install 'landexplorer-gis')")
    return (True, None)


def _import_httpx() -> Any:
    """Bind ``httpx`` at CALL time.

    Raises:
        ProviderTransportError: When httpx is not installed. ★ A typed ``gis`` error, NOT
            an ``ImportError``: a caller handling ``ProviderError`` must not have to also
            handle our import failures.
    """
    try:
        import httpx  # noqa: PLC0415 - ★ CALL-TIME BINDING, §11.3. Never move this up.
    except ImportError as exc:
        raise ProviderTransportError(
            "httpx is not installed, so no network provider can fetch. Install "
            "'landexplorer-gis', or use an offline provider (local_orthophoto, fixture) "
            "via LE_IMAGERY_OFFLINE=true."
        ) from exc
    return httpx


_CLIENT_LOCK: Final[threading.Lock] = threading.Lock()
_CLIENTS: dict[tuple[str, float], Any] = {}


def _client(config: HttpConfig) -> Any:
    """Return a shared, thread-safe ``httpx.Client`` for this policy.

    ★ Sessions are pooled per ``(user_agent, timeout)``, not created per request. A new
    client per tile means a new TCP + TLS handshake per tile, which for a 200-tile chip is
    the difference between one second and thirty — and it burns the provider's connection
    budget for no benefit. ``httpx.Client`` is thread-safe, which is what Celery's worker
    pool needs.
    """
    httpx = _import_httpx()
    key = (config.user_agent, config.timeout_seconds)
    client = _CLIENTS.get(key)
    if client is not None:
        return client
    with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = httpx.Client(
                headers={"User-Agent": config.user_agent},
                timeout=config.timeout_seconds,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            )
            _CLIENTS[key] = client
    return client


def close_clients() -> None:
    """Close every pooled client. NEVER raises.

    For worker shutdown and for tests. Idempotent.
    """
    with _CLIENT_LOCK:
        for client in _CLIENTS.values():
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                _log.debug("error closing http client: %s", exc)
        _CLIENTS.clear()


def _backoff_seconds(attempt: int, base: float = 0.25, cap: float = 8.0) -> float:
    """Return a jittered exponential backoff delay for ``attempt`` (0-based).

    ★ Full jitter, not fixed backoff: N workers that all failed on the same provider at the
    same instant must not retry in lockstep and re-create the burst that throttled them.
    """
    ceiling = min(cap, base * (2.0**attempt))
    return random.uniform(0.0, ceiling)  # noqa: S311 - jitter, not cryptography


def _retry_after_seconds(response: Any) -> float | None:
    """Parse a ``Retry-After`` header, seconds form. Returns None when absent/unparseable."""
    raw = response.headers.get("Retry-After") if response is not None else None
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None  # HTTP-date form; the caller's backoff covers it


def _raise_for_status(response: Any, provider: str, url: str) -> None:
    """Translate an HTTP status into this package's error taxonomy.

    Raises:
        TileNotAvailableError: 404/204 — a permanent, cacheable "nothing here".
        ProviderNotConfiguredError: 401/403 — the credential is missing, wrong or
            unauthorised for this resource.
        ProviderRateLimitError: 429 — retryable, carries ``retry_after``.
        ProviderTransportError: Any other non-2xx.
    """
    status = response.status_code
    if 200 <= status < 300:
        return
    if status in _NOT_AVAILABLE_STATUS:
        raise TileNotAvailableError(
            f"{provider} has no content at {url} (HTTP {status})", provider=provider
        )
    if status in _UNAUTHORISED_STATUS:
        raise ProviderNotConfiguredError(
            f"{provider} rejected our credential (HTTP {status}); check the provider's "
            "API key env var and that the key is authorised for this product",
            provider=provider,
        )
    if status == 429:
        raise ProviderRateLimitError(
            f"{provider} is throttling us (HTTP 429)",
            provider=provider,
            retry_after=_retry_after_seconds(response),
        )
    raise ProviderTransportError(
        f"{provider} returned HTTP {status} for {url}", provider=provider
    )


def fetch_bytes(
    url: str,
    *,
    provider: str,
    config: HttpConfig | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> tuple[bytes, str]:
    """GET a URL and return its body + content type. ★ THE single network entry point.

    ★ ``httpx`` binds inside this function (§11.3). Every retryable failure is retried with
    jittered exponential backoff up to ``config.max_retries``; every non-retryable one
    raises immediately, because retrying a 404 or a bad key is pure latency.

    Args:
        url: Absolute URL.
        provider: Registry key, for error attribution and logging.
        config: HTTP policy. Defaults apply when None.
        headers: Extra request headers.
        params: Query parameters.

    Returns:
        ``(body, content_type)``.

    Raises:
        TileNotAvailableError: A permanent 404/204 — cache the negative.
        ProviderNotConfiguredError: 401/403.
        ProviderRateLimitError: 429 after the retry budget is spent.
        ProviderTransportError: Transport failure, or a 5xx after the retry budget is
            spent, or httpx is not installed. ★ Never a bare httpx exception.
    """
    cfg = config or HttpConfig()
    httpx = _import_httpx()
    client = _client(cfg)
    attempts = max(1, cfg.max_retries + 1)
    last: Exception | None = None

    for attempt in range(attempts):
        try:
            response = client.get(url, headers=dict(headers or {}), params=dict(params or {}))
            _raise_for_status(response, provider, url)
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return (response.content, content_type.split(";")[0].strip())
        except (ProviderRateLimitError, ProviderTransportError) as exc:
            last = exc
            if attempt == attempts - 1:
                raise
            delay = exc.retry_after if isinstance(exc, ProviderRateLimitError) else None
            if delay is None:
                delay = _backoff_seconds(attempt)
            _log.warning(
                "%s: %s (attempt %d/%d); retrying in %.2fs",
                provider,
                exc,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)
        except httpx.HTTPError as exc:
            # Connect/read timeouts, DNS failures, TLS errors: transient by nature.
            last = exc
            if attempt == attempts - 1:
                raise ProviderTransportError(
                    f"{provider}: {type(exc).__name__} fetching {url}: {exc}",
                    provider=provider,
                ) from exc
            delay = _backoff_seconds(attempt)
            _log.warning(
                "%s: %s (attempt %d/%d); retrying in %.2fs",
                provider,
                exc,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)

    raise ProviderTransportError(  # pragma: no cover - the loop always raises or returns
        f"{provider}: exhausted {attempts} attempts fetching {url}: {last}",
        provider=provider,
    )


def fetch_json(
    url: str,
    *,
    provider: str,
    config: HttpConfig | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> Any:
    """GET a URL and parse its body as JSON.

    Used by the metadata handshakes (Bing) and the OAuth2 flow (Sentinel).

    Args:
        url: Absolute URL.
        provider: Registry key, for error attribution.
        config: HTTP policy.
        headers: Extra request headers.
        params: Query parameters.

    Returns:
        The decoded JSON.

    Raises:
        ProviderTransportError: On a transport failure or a body that is not JSON.
        TileNotAvailableError | ProviderNotConfiguredError | ProviderRateLimitError: As
            ``fetch_bytes``.
    """
    import json  # noqa: PLC0415 - stdlib; keeps module scope minimal

    body, _content_type = fetch_bytes(
        url, provider=provider, config=config, headers=headers, params=params
    )
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderTransportError(
            f"{provider} returned a non-JSON body from {url}: {exc}", provider=provider
        ) from exc


def post_json(
    url: str,
    body: Mapping[str, Any],
    *,
    provider: str,
    config: HttpConfig | None = None,
    params: Mapping[str, str] | None = None,
) -> Any:
    """POST a JSON body and parse the JSON response.

    Exists for the one flow that needs it: Google Map Tiles ``createSession``, which is
    the only session-token handshake in the provider set. Kept beside
    :func:`post_form` rather than folded into it — a server that wants
    ``application/json`` and one that wants ``application/x-www-form-urlencoded`` are not
    interchangeable, and guessing produces a 400 that reads like a credential failure.

    Args:
        url: The endpoint.
        body: The JSON request body.
        provider: Registry key, for error attribution.
        config: HTTP policy.
        params: Query parameters (the API key rides here, not in the body).

    Returns:
        The decoded JSON.

    Raises:
        ProviderNotConfiguredError: The credentials were rejected.
        ProviderTransportError: Transport failure or a non-JSON body.
        ProviderRateLimitError: The endpoint is throttling us.
    """
    import json  # noqa: PLC0415

    cfg = config or HttpConfig()
    httpx = _import_httpx()
    client = _client(cfg)
    try:
        response = client.post(url, json=dict(body), params=dict(params or {}))
    except httpx.HTTPError as exc:
        raise ProviderTransportError(
            f"{provider}: {type(exc).__name__} posting to {url}: {exc}", provider=provider
        ) from exc
    _raise_for_status(response, provider, url)
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderTransportError(
            f"{provider} returned a non-JSON session response: {exc}", provider=provider
        ) from exc


def post_form(
    url: str,
    form: Mapping[str, str],
    *,
    provider: str,
    config: HttpConfig | None = None,
) -> Any:
    """POST a form-encoded body and parse the JSON response.

    Exists for the one flow that needs it: Sentinel/Copernicus OAuth2 client credentials.

    Args:
        url: The token endpoint.
        form: Form fields.
        provider: Registry key, for error attribution.
        config: HTTP policy.

    Returns:
        The decoded JSON.

    Raises:
        ProviderNotConfiguredError: The credentials were rejected.
        ProviderTransportError: Transport failure or a non-JSON body.
        ProviderRateLimitError: The token endpoint is throttling us.
    """
    import json  # noqa: PLC0415

    cfg = config or HttpConfig()
    httpx = _import_httpx()
    client = _client(cfg)
    try:
        response = client.post(url, data=dict(form))
    except httpx.HTTPError as exc:
        raise ProviderTransportError(
            f"{provider}: {type(exc).__name__} posting to {url}: {exc}", provider=provider
        ) from exc
    _raise_for_status(response, provider, url)
    try:
        return json.loads(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderTransportError(
            f"{provider} returned a non-JSON token response: {exc}", provider=provider
        ) from exc
