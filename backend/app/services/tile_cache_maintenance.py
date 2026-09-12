"""Tile-cache maintenance shared by Celery beat AND the desktop API process.

★ WHY BOTH. The packaged desktop app runs uvicorn with no Celery beat, so relying on the
hourly ``tile_cache_gc_task`` alone meant the desktop cache NEVER swept: it grew until the
disk did. The sweep itself lives on ``DiskTileCache.sweep`` (expiry incl. per-provider
ToS caps, negatives, temp files, corruption, the size cap); this module is just the two
entry points — the Celery task calls :func:`sweep_tile_cache` once an hour on servers,
and :func:`start_periodic_sweeper` gives the API process a startup sweep plus a periodic
one when ``LE_IMAGERY_TILE_CACHE_SWEEP_*`` says so.

★ NEVER on the tile hot path, and never fatal: a sweep that cannot run logs and returns.
"""

from __future__ import annotations

import logging
import threading

from app.core.config import Settings

__all__ = ["start_periodic_sweeper", "sweep_tile_cache"]

_log = logging.getLogger("app.services.tile_cache_maintenance")


def sweep_tile_cache(settings: Settings) -> dict[str, int]:
    """One maintenance pass over the shared disk tile cache. Never raises.

    Returns the sweep counters, or ``{"skipped": 1}`` when there is nothing to sweep
    (non-disk backend, cache unavailable).
    """
    if str(settings.imagery_tile_cache_backend) != "disk":
        return {"skipped": 1}
    try:
        from app.services.imagery_service import _build_tile_cache  # noqa: PLC0415

        cache = _build_tile_cache(settings)
        if cache is None or not hasattr(cache, "sweep"):
            return {"skipped": 1}
        result = cache.sweep(
            negative_ttl_s=settings.imagery_negative_tile_cache_ttl_seconds
        )
        _log.info("tile_cache.sweep", extra=dict(result))
        return result
    except Exception as exc:  # noqa: BLE001 — maintenance must never take the app down
        _log.warning("tile_cache.sweep_failed", extra={"error": str(exc)})
        return {"failed": 1}


def start_periodic_sweeper(settings: Settings) -> threading.Event | None:
    """Run a startup sweep and schedule periodic ones. Returns a stop event, or None.

    ★ A daemon ``threading.Timer`` chain, not an asyncio task: the sweep is blocking
    filesystem work and must not sit on the event loop. The returned event stops the
    chain on shutdown.
    """
    if str(settings.imagery_tile_cache_backend) != "disk":
        return None

    stop = threading.Event()

    if settings.imagery_tile_cache_sweep_on_startup:
        threading.Thread(
            target=sweep_tile_cache, args=(settings,), name="tile-cache-sweep-startup",
            daemon=True,
        ).start()

    interval = int(settings.imagery_tile_cache_sweep_interval_seconds)
    if interval > 0:

        def tick() -> None:
            while not stop.wait(interval):
                sweep_tile_cache(settings)

        threading.Thread(target=tick, name="tile-cache-sweeper", daemon=True).start()

    return stop
