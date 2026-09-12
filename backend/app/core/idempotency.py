"""``Idempotency-Key`` handling — Redis SETNX (CONTRACT.md §2.4, §12 C-27).

§12 C-27 ruled that LandExplorer has **two** idempotency mechanisms and not three:
the ``Idempotency-Key`` header (this module) and the active-job conflict check
(``409 MATCH_JOB_ALREADY_RUNNING`` + ``?force=true``). The overview's
content-derived ``match_jobs.idempotency_key`` column is **deleted** — the two here
already cover both failures it defended (a double-click, and a redundant in-flight
match), and the conflict check is *more* informative because it returns the job id
and offers a way through. A third mechanism is a third thing to get wrong.

The mechanism is a Redis ``SET key value NX EX ttl``: the first request through wins
the slot and runs; a concurrent duplicate sees the slot held and gets
``409 IDEMPOTENCY_IN_PROGRESS``; a later duplicate sees the recorded response and
gets it replayed with ``Idempotency-Replayed: true``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Literal, Mapping, Protocol

from app.core.config import Settings
from app.core.exceptions import IdempotencyInProgress, IdempotencyKeyReused
from app.core.logging import get_logger

__all__ = [
    "IDEMPOTENCY_HEADER",
    "IDEMPOTENCY_REPLAYED_HEADER",
    "IdempotencyContext",
    "IdempotencyRecord",
    "IdempotencyStore",
    "NullIdempotencyStore",
    "RedisIdempotencyStore",
    "fingerprint_request",
]

log = get_logger(__name__)

IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
IDEMPOTENCY_REPLAYED_HEADER: Final = "Idempotency-Replayed"

_KEY_PREFIX: Final = "idem"
#: How long a slot may stay "in progress" before another request may claim it.
#: Bounded by the hard Celery time limit: an API call that has not recorded a
#: response by then is never going to, and leaving the slot held forever would mean a
#: single crashed request permanently bricks that key for the client.
_IN_PROGRESS_TTL_SECONDS: Final = 900

RecordState = Literal["in_progress", "completed"]


def fingerprint_request(*, method: str, path: str, body: bytes | Mapping[str, Any] | None) -> str:
    """A stable digest of the request a key was first used for.

    Used to detect key *reuse*: the same ``Idempotency-Key`` sent with a different
    request body is a client bug, and replaying the first response would hide it
    behind a plausible 200 (§6.3 ``IdempotencyKeyReused``).
    """
    hasher = hashlib.sha256()
    hasher.update(method.upper().encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(path.encode("utf-8"))
    hasher.update(b"\0")
    if isinstance(body, bytes):
        hasher.update(body)
    elif body is not None:
        # sort_keys: JSON object order is not semantic, and a client that reorders
        # its fields between retries has not changed its request.
        hasher.update(json.dumps(body, sort_keys=True, default=str).encode("utf-8"))
    return hasher.hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """What a previous request with this key left behind."""

    state: RecordState
    fingerprint: str
    status_code: int | None = None
    body: Any | None = None

    @property
    def is_replayable(self) -> bool:
        return self.state == "completed" and self.status_code is not None


class IdempotencyStore(Protocol):
    """The storage seam. Redis in every real deployment; a Protocol so it is fakeable."""

    def claim(self, key: str, fingerprint: str, *, ttl_seconds: int) -> IdempotencyRecord | None:
        """Atomically claim the slot for ``key``.

        Returns:
            None if the slot was free and is now ours (the caller should proceed), or
            the existing record if somebody else got there first.
        """
        ...

    def complete(self, key: str, *, status_code: int, body: Any, ttl_seconds: int) -> None:
        """Record the response so a later duplicate can be replayed it."""
        ...

    def release(self, key: str) -> None:
        """Drop the slot after a failure, so the client's retry is not a 409 forever."""
        ...


class NullIdempotencyStore:
    """No-op store: every claim succeeds. Used when Redis is unreachable.

    ★ Fail-OPEN, and the reasoning is the same as §6.5's for the rate limiter: this is
    a protection mechanism, not a correctness one, and failing closed converts a Redis
    blip into a total outage of every mutating endpoint. It is safe to fail open here
    *specifically because C-27 kept a second, independent mechanism*: a duplicate
    match still hits ``409 MATCH_JOB_ALREADY_RUNNING`` from the database, which does
    not depend on Redis at all. The worst case is a duplicated upload, not a
    duplicated survey.

    It logs a warning every time (L11: never silent), and ``/health/ready`` reports
    Redis as not-ready so the instance is pulled from rotation anyway.
    """

    def claim(self, key: str, fingerprint: str, *, ttl_seconds: int) -> IdempotencyRecord | None:
        log.warning(
            "idempotency.store_unavailable",
            reason="no Redis; Idempotency-Key not enforced for this request",
        )
        return None

    def complete(self, key: str, *, status_code: int, body: Any, ttl_seconds: int) -> None:
        return None

    def release(self, key: str) -> None:
        return None


class RedisIdempotencyStore:
    """The real store. ``SET NX EX`` for the claim; a JSON blob for the replay."""

    def __init__(self, client: Any, *, namespace: str = _KEY_PREFIX) -> None:
        """
        Args:
            client: A ``redis.Redis``. Injected rather than constructed so this module
                does not own connection lifecycle, and so tests can pass a fake.
            namespace: Key prefix, keeping idempotency slots distinguishable from the
                rate limiter's and the pubsub channels' keys in a shared Redis.
        """
        self._client = client
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    def claim(self, key: str, fingerprint: str, *, ttl_seconds: int) -> IdempotencyRecord | None:
        payload = json.dumps({"state": "in_progress", "fingerprint": fingerprint})
        # nx=True makes this a single atomic round trip. A GET-then-SET would have a
        # window exactly the width of a double-click, which is the thing being
        # defended against.
        acquired = self._client.set(self._key(key), payload, nx=True, ex=ttl_seconds)
        if acquired:
            return None
        raw = self._client.get(self._key(key))
        if raw is None:
            # The slot expired between the failed SET and the GET. Rare; treat it as
            # free rather than raising — the client's retry is exactly what we want.
            return None
        return _decode(raw)

    def complete(self, key: str, *, status_code: int, body: Any, ttl_seconds: int) -> None:
        existing = self._client.get(self._key(key))
        fingerprint = _decode(existing).fingerprint if existing else ""
        payload = json.dumps(
            {
                "state": "completed",
                "fingerprint": fingerprint,
                "status_code": status_code,
                "body": body,
            },
            default=str,
        )
        self._client.set(self._key(key), payload, ex=ttl_seconds)

    def release(self, key: str) -> None:
        self._client.delete(self._key(key))


def _decode(raw: Any) -> IdempotencyRecord:
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    return IdempotencyRecord(
        state=data.get("state", "in_progress"),
        fingerprint=data.get("fingerprint", ""),
        status_code=data.get("status_code"),
        body=data.get("body"),
    )


@dataclass(slots=True)
class IdempotencyContext:
    """Per-request idempotency handle, built by ``api.deps.get_idempotency``.

    When the client sent no ``Idempotency-Key``, ``key`` is None and every method is a
    no-op: the header is optional on every endpoint that accepts it (§7 marks it
    ``Idempotency-Key?``), and a client that does not use it must not be made slower
    or more fragile by its existence.
    """

    key: str | None
    fingerprint: str
    store: IdempotencyStore
    ttl_seconds: int = _IN_PROGRESS_TTL_SECONDS
    replayed: bool = False

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def begin(self) -> IdempotencyRecord | None:
        """Claim the slot, or surface what a previous request left.

        Returns:
            None to proceed with the request; a completed ``IdempotencyRecord`` to
            replay it verbatim (the caller sets ``Idempotency-Replayed: true``).

        Raises:
            IdempotencyKeyReused: this key was used for a *different* request.
            IdempotencyInProgress: an identical request is still running.
        """
        if self.key is None:
            return None

        existing = self.store.claim(self.key, self.fingerprint, ttl_seconds=self.ttl_seconds)
        if existing is None:
            return None

        if existing.fingerprint and existing.fingerprint != self.fingerprint:
            raise IdempotencyKeyReused(
                f"Idempotency-Key {self.key!r} was already used for a different request. "
                f"Use a fresh key for each distinct operation."
            )

        if existing.state == "in_progress":
            raise IdempotencyInProgress(
                f"A request with Idempotency-Key {self.key!r} is still being processed. "
                f"Retry shortly.",
                headers={"Retry-After": "2"},
            )

        self.replayed = True
        return existing

    def complete(self, *, status_code: int, body: Any, ttl_seconds: int | None = None) -> None:
        """Record a successful response for replay."""
        if self.key is None:
            return
        self.store.complete(
            self.key,
            status_code=status_code,
            body=body,
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.ttl_seconds,
        )

    def fail(self) -> None:
        """Release the slot after a failed request.

        A failure is not an outcome worth replaying — the client should be free to
        retry immediately and get a real attempt, not a cached 500.
        """
        if self.key is None:
            return
        self.store.release(self.key)


def build_store(settings: Settings, client: Any | None = None) -> IdempotencyStore:
    """Pick a store: Redis when a client is available, the fail-open null otherwise.

    ``client`` is injected by the composition root, which owns the Redis connection
    pool. When it is None — no Redis configured, or the connection failed at boot —
    this degrades to ``NullIdempotencyStore`` with a warning rather than refusing to
    build (L11).
    """
    if client is None:
        log.warning(
            "idempotency.degraded",
            redis_url=settings.redacted_redis_url(),
            effect="Idempotency-Key headers will not be enforced",
        )
        return NullIdempotencyStore()
    return RedisIdempotencyStore(client)
