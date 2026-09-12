"""Token buckets: per-provider request budgets. ★ A rate limit is a CONTRACTUAL TERM.

Not a performance tuning knob. Several providers' terms state a rate; Esri publishes none,
which is not permission for unlimited traffic but an obligation to self-limit (§2.1 of
``40-imagery.md`` sets 8 rps for exactly that reason).

★ **``redis`` IS BOUND AT CALL TIME, NEVER AT MODULE SCOPE** (§11.3). ``import
gis.imagery.ratelimit`` succeeds with redis absent, and ``TokenBucket`` silently uses the
in-process bucket. The distributed bucket exists because tile fetching happens **inside
Celery workers**: a per-process bucket set to 8 rps across four replicas is 32 rps against
the provider, which is not the budget anyone agreed to.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Final

__all__ = [
    "PROVIDER_RATE_LIMITS",
    "RateLimiter",
    "TokenBucket",
    "get_limiter",
    "redis_available",
    "reset_limiters",
]

_log = logging.getLogger("gis.imagery.ratelimit")

PROVIDER_RATE_LIMITS: Final[dict[str, float | None]] = {
    "esri_world_imagery": 8.0,
    "local_orthophoto": None,
    "fixture": None,
    "mapbox_satellite": 10.0,
    "bing_aerial": 10.0,
    "sentinel_copernicus": 5.0,
    "google_maps_static": 10.0,
    "google_map_tiles": 10.0,
}
"""Self-imposed requests-per-second per provider. None means "no network, no budget".

★ Esri's 8.0 is self-imposed precisely BECAUSE no limit is published. The offline
providers are None because they touch no third party's infrastructure.
"""


def redis_available() -> tuple[bool, str | None]:
    """Report whether ``redis`` can be bound. ★ Total; callable with redis absent.

    Returns:
        ``(available, reason)``. ``reason`` is None when available, else a sentence.
    """
    import importlib.util  # noqa: PLC0415

    if importlib.util.find_spec("redis") is None:
        return (False, "requires redis (pip install 'landexplorer-gis[redis]')")
    return (True, None)


class TokenBucket:
    """A thread-safe, monotonic-clock token bucket.

    Refills continuously at ``rate`` tokens/second up to ``capacity``. ``acquire()``
    blocks until a token is free.

    ★ The clock is ``time.monotonic``, never ``time.time``: an NTP step or a DST change
    must not hand out a burst of free tokens or hang the bucket for an hour.
    """

    __slots__ = ("_capacity", "_lock", "_rate", "_tokens", "_updated")

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        """Build a bucket.

        Args:
            rate: Tokens per second. Must be > 0.
            capacity: Burst size. Defaults to ``max(1, rate)`` — one second of burst,
                which absorbs a chip's opening volley without exceeding the sustained rate.

        Raises:
            ValueError: If ``rate <= 0``.
        """
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate}")
        self._rate = float(rate)
        self._capacity = float(capacity if capacity is not None else max(1.0, rate))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add the tokens that have accrued since the last update. Caller holds the lock."""
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Take ``tokens`` if available, without blocking.

        Args:
            tokens: How many to take.

        Returns:
            True if taken, False if the bucket is short.
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0, *, timeout: float | None = None) -> bool:
        """Take ``tokens``, blocking until they are available.

        Args:
            tokens: How many to take.
            timeout: Give up after this many seconds. None waits forever.

        Returns:
            True if taken, False if ``timeout`` expired first.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                shortfall = tokens - self._tokens
                wait = shortfall / self._rate
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            time.sleep(max(wait, 0.001))


class RateLimiter:
    """One provider's request budget, in-process or shared via Redis.

    ★ Degrades, never fails. If Redis is absent, unreachable, or errors mid-flight, the
    limiter falls back to its in-process bucket with a WARNING and keeps serving (L11). A
    rate limiter that takes the fleet down when its coordination store hiccups has
    inverted its own purpose.
    """

    __slots__ = ("_local", "_provider", "_rate", "_redis", "_redis_url", "_warned")

    def __init__(
        self, provider: str, rate: float | None, *, redis_url: str | None = None
    ) -> None:
        """Build a limiter.

        Args:
            provider: Registry key, for the Redis key namespace and for log lines.
            rate: Requests per second, or None for unlimited (offline providers).
            redis_url: When set AND redis is importable, the budget is shared fleet-wide.
        """
        self._provider = provider
        self._rate = rate
        self._local = TokenBucket(rate) if rate and rate > 0 else None
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._warned = False

    @property
    def rate(self) -> float | None:
        """Requests per second, or None when unlimited."""
        return self._rate

    def _client(self) -> Any | None:
        """Bind a Redis client at CALL time, or None. NEVER raises."""
        if self._redis_url is None:
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis  # noqa: PLC0415 - ★ CALL-TIME BINDING, §11.3.

            self._redis = redis.Redis.from_url(self._redis_url)
            return self._redis
        except Exception as exc:  # noqa: BLE001 - ImportError, bad URL, anything
            if not self._warned:
                _log.warning(
                    "%s: cannot use the shared rate-limit bucket (%s); falling back to a "
                    "per-process bucket. With multiple workers the effective rate against "
                    "the provider is multiplied by the worker count.",
                    self._provider,
                    exc,
                )
                self._warned = True
            self._redis_url = None
            return None

    def _acquire_distributed(self, client: Any) -> bool:
        """Take one token from the Redis-backed bucket.

        A fixed-window counter (``INCR`` + ``EXPIRE``) rather than a Lua token bucket:
        one round trip, no scripting, no reliance on ``EVAL`` being permitted on a managed
        Redis. The window is coarser than a true bucket, and that is the right trade — the
        budget is respected on average, which is what a terms-of-service rate is about.

        Returns:
            True if a token was taken; False when the window is exhausted. On ANY Redis
            error, returns True after falling back to the local bucket — never blocks.
        """
        assert self._rate is not None  # guarded by the caller
        try:
            window = int(time.time())
            key = f"le:ratelimit:{self._provider}:{window}"
            pipe = client.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, 2)
            count = int(pipe.execute()[0])
            return count <= self._rate
        except Exception as exc:  # noqa: BLE001 - a broker hiccup must not stop imagery
            if not self._warned:
                _log.warning(
                    "%s: shared rate-limit bucket failed (%s); using the per-process "
                    "bucket from here on",
                    self._provider,
                    exc,
                )
                self._warned = True
            self._redis = None
            self._redis_url = None
            return True

    def acquire(self, *, timeout: float | None = 30.0) -> bool:
        """Take one request's worth of budget, blocking as needed.

        Args:
            timeout: Give up after this many seconds. None waits forever.

        Returns:
            True when the budget was granted; False on timeout. ★ Never raises.
        """
        if self._local is None:
            return True  # unlimited: an offline provider

        client = self._client()
        if client is None:
            return self._local.acquire(timeout=timeout)

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._client() is None:  # fell back mid-flight
                return self._local.acquire(timeout=timeout)
            if self._acquire_distributed(client):
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(1.0 / max(self._rate or 1.0, 1.0))


_LIMITER_LOCK: Final[threading.Lock] = threading.Lock()
_LIMITERS: dict[tuple[str, float | None, str | None], RateLimiter] = {}


def get_limiter(
    provider: str, *, rate: float | None = None, redis_url: str | None = None
) -> RateLimiter:
    """Return the shared limiter for a provider, creating it once.

    ★ Memoised per ``(provider, rate, redis_url)``. A limiter constructed per request would
    hand out a full bucket every time, which is not a limiter — it is a formality.

    Args:
        provider: Registry key.
        rate: Requests per second. When None, ``PROVIDER_RATE_LIMITS`` supplies the
            provider's own budget.
        redis_url: Set to share the budget across workers.

    Returns:
        The ``RateLimiter``. Never raises.
    """
    effective = PROVIDER_RATE_LIMITS.get(provider) if rate is None else rate
    key = (provider, effective, redis_url)
    limiter = _LIMITERS.get(key)
    if limiter is not None:
        return limiter
    with _LIMITER_LOCK:
        limiter = _LIMITERS.get(key)
        if limiter is None:
            limiter = RateLimiter(provider, effective, redis_url=redis_url)
            _LIMITERS[key] = limiter
    return limiter


def reset_limiters() -> None:
    """Drop every memoised limiter. For tests. NEVER raises."""
    with _LIMITER_LOCK:
        _LIMITERS.clear()
