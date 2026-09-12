"""Application-level imagery usage counters — the operator's OWN ledger.

★ **THESE ARE APPLICATION STATISTICS, NOT THE PROVIDER'S BILLING DASHBOARD.** They count
what THIS process (and, via the persisted daily file, this installation) asked upstream
and answered from cache. Mapbox's own usage page remains the billing truth; this ledger
exists so a surveyor can see the cache working and so the per-day request budget
(``LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY``) has something real to enforce against.

★ Process-wide singleton, because ``ImageryService`` is constructed per request: counters
on the service instance would reset every tile. Thread-safe — tiles arrive from the
Starlette threadpool and from pre-cache worker threads at once.

★ The daily upstream count is PERSISTED (a small JSON next to the tile cache) so the
per-day budget survives an app restart. Everything else is process-lifetime — an honest
"since the app started", never a fabricated total.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["ImageryUsage", "ProviderUsage", "get_usage"]

_log = logging.getLogger("app.services.imagery_usage")

_PERSIST_EVERY_N_UPSTREAM = 20
"""Flush the daily ledger at most once per this many upstream requests — a pre-cache run
must not turn into one fsync per tile."""


@dataclass
class ProviderUsage:
    """One provider's counters since process start."""

    upstream_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    negative_cache_hits: int = 0
    rate_limited_429: int = 0
    failed_requests: int = 0
    offline_cache_misses: int = 0
    upstream_by_source: dict[str, int] = field(default_factory=dict)
    """★ WHERE upstream requests came from: ``map`` (live tiles), ``precache`` (manual
    Offline Area download), ``viewport`` (automatic viewport caching). Lets the operator
    see which mechanism is spending the request budget."""

    @property
    def hit_ratio(self) -> float:
        """Hits (positive + negative) over all lookups; 0.0 before any traffic."""
        total = self.cache_hits + self.negative_cache_hits + self.cache_misses
        return (self.cache_hits + self.negative_cache_hits) / total if total else 0.0


@dataclass
class _State:
    started_at: float = field(default_factory=time.time)
    providers: dict[str, ProviderUsage] = field(
        default_factory=lambda: defaultdict(ProviderUsage)
    )


class ImageryUsage:
    """Thread-safe usage counters plus a persisted per-day upstream ledger."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _State()
        self._ledger_path: Path | None = None
        self._daily: dict[str, int] = {}
        self._daily_day: str = self._today()
        self._unflushed = 0
        self._loaded = False

    # ── configuration ─────────────────────────────────────────────────────────

    def configure_ledger(self, cache_dir: str | Path) -> None:
        """Point the daily ledger at ``{cache_dir}/usage_ledger.json``. Idempotent.

        A failure to read the ledger degrades to "no history", never to an error.
        """
        path = Path(cache_dir) / "usage_ledger.json"
        with self._lock:
            if self._ledger_path == path and self._loaded:
                return
            self._ledger_path = path
            self._load_locked()

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _load_locked(self) -> None:
        self._loaded = True
        self._daily = {}
        self._daily_day = self._today()
        if self._ledger_path is None:
            return
        try:
            raw = json.loads(self._ledger_path.read_text())
            if raw.get("day") == self._daily_day and isinstance(raw.get("upstream"), dict):
                self._daily = {str(k): int(v) for k, v in raw["upstream"].items()}
        except (OSError, ValueError, TypeError):
            pass  # no history is an honest starting point

    def _flush_locked(self) -> None:
        if self._ledger_path is None:
            return
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger_path.write_text(
                json.dumps({"day": self._daily_day, "upstream": self._daily})
            )
            self._unflushed = 0
        except OSError as exc:
            _log.debug("usage ledger flush failed: %s", exc)

    def _roll_day_locked(self) -> None:
        today = self._today()
        if today != self._daily_day:
            self._daily_day = today
            self._daily = {}

    # ── recording ─────────────────────────────────────────────────────────────

    def record_cache_hit(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].cache_hits += 1

    def record_negative_hit(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].negative_cache_hits += 1

    def record_miss(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].cache_misses += 1

    def record_upstream(self, provider: str, *, source: str = "map") -> None:
        with self._lock:
            self._roll_day_locked()
            usage = self._state.providers[provider]
            usage.upstream_requests += 1
            usage.upstream_by_source[source] = usage.upstream_by_source.get(source, 0) + 1
            self._daily[provider] = self._daily.get(provider, 0) + 1
            self._unflushed += 1
            if self._unflushed >= _PERSIST_EVERY_N_UPSTREAM:
                self._flush_locked()

    def record_429(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].rate_limited_429 += 1

    def record_failure(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].failed_requests += 1

    def record_offline_miss(self, provider: str) -> None:
        with self._lock:
            self._state.providers[provider].offline_cache_misses += 1

    # ── reading ───────────────────────────────────────────────────────────────

    def upstream_today(self, provider: str) -> int:
        """Upstream requests recorded for ``provider`` today (persisted across restarts)."""
        with self._lock:
            self._roll_day_locked()
            return self._daily.get(provider, 0)

    def snapshot(self) -> dict[str, object]:
        """A JSON-ready snapshot for ``GET /imagery/usage``. Flushes the ledger."""
        with self._lock:
            self._roll_day_locked()
            self._flush_locked()
            return {
                "started_at": datetime.fromtimestamp(
                    self._state.started_at, tz=UTC
                ).isoformat(),
                "day": self._daily_day,
                "providers": {
                    name: {
                        "upstream_requests": u.upstream_requests,
                        "upstream_requests_by_source": dict(u.upstream_by_source),
                        "upstream_requests_today": self._daily.get(name, 0),
                        "cache_hits": u.cache_hits,
                        "cache_misses": u.cache_misses,
                        "negative_cache_hits": u.negative_cache_hits,
                        "cache_hit_ratio": round(u.hit_ratio, 4),
                        "rate_limited_429": u.rate_limited_429,
                        "failed_requests": u.failed_requests,
                        "offline_cache_misses": u.offline_cache_misses,
                    }
                    for name, u in sorted(self._state.providers.items())
                },
            }

    def reset(self) -> None:
        """Drop every counter and the ledger binding. For tests."""
        with self._lock:
            self._state = _State()
            self._ledger_path = None
            self._daily = {}
            self._unflushed = 0
            self._loaded = False


_USAGE = ImageryUsage()


def get_usage() -> ImageryUsage:
    """The process-wide usage singleton."""
    return _USAGE
