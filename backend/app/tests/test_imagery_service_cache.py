"""``ImageryService`` tile path — read-through caching, negatives, offline cache-only.

★ All through the ``fixture`` provider (synthetic tiles, ZERO network) or a pre-seeded
cache; nothing here may touch a third party. What these pin:

- second request for a tile is a CACHE HIT (the provider is not called again);
- a genuine "no imagery here" is negative-cached and answered from the marker;
- transient failures (429, transport) are NEVER negative-cached;
- ``LE_IMAGERY_OFFLINE=true`` + an explicitly named network provider serves CACHED
  tiles and returns a controlled miss for uncached ones — never a network attempt;
- the usage ledger counts what actually happened.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from gis.errors import (
    ProviderTransportError,
    TileNotAvailableError,
)
from gis.types import BasemapKind

from app.core.config import Settings
from app.services import imagery_service as svc_module
from app.services.imagery_service import ImageryService
from app.services.imagery_usage import get_usage


@pytest.fixture(autouse=True)
def _fresh_cache_and_usage(tmp_path) -> Iterator[Settings]:
    """A per-test disk cache dir + reset usage counters + reset the lru_cache."""
    svc_module._tile_cache_for.cache_clear()
    get_usage().reset()
    settings = Settings(
        imagery_tile_cache_backend="disk",
        imagery_tile_cache_dir=tmp_path / "tile_cache",
        allowed_providers=[],
    )
    yield settings
    svc_module._tile_cache_for.cache_clear()
    get_usage().reset()


def test_read_through_cache_hits_on_second_request(_fresh_cache_and_usage: Settings) -> None:
    settings = _fresh_cache_and_usage
    service = ImageryService(settings)
    provider = service.get_provider("fixture")
    calls = {"n": 0}
    original = provider.get_tile_bytes

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    provider.get_tile_bytes = counting  # type: ignore[method-assign]
    try:
        first, _ = service.get_tile_bytes("fixture", 10, 1, 2)
        second, _ = service.get_tile_bytes("fixture", 10, 1, 2)
    finally:
        provider.get_tile_bytes = original  # type: ignore[method-assign]

    assert first == second
    assert calls["n"] == 1  # ★ the second answer came from the cache

    snap = get_usage().snapshot()
    fx = snap["providers"]["fixture"]  # type: ignore[index]
    assert fx["upstream_requests"] == 1
    assert fx["cache_hits"] == 1
    assert fx["cache_misses"] == 1


def test_no_imagery_is_negative_cached(_fresh_cache_and_usage: Settings) -> None:
    settings = _fresh_cache_and_usage
    service = ImageryService(settings)
    provider = service.get_provider("fixture")
    calls = {"n": 0}

    def gone(*_args, **_kwargs):
        calls["n"] += 1
        raise TileNotAvailableError("nothing here", provider="fixture")

    original = provider.get_tile_bytes
    provider.get_tile_bytes = gone  # type: ignore[method-assign]
    try:
        with pytest.raises(TileNotAvailableError):
            service.get_tile_bytes("fixture", 10, 3, 4)
        with pytest.raises(TileNotAvailableError):
            service.get_tile_bytes("fixture", 10, 3, 4)
    finally:
        provider.get_tile_bytes = original  # type: ignore[method-assign]

    assert calls["n"] == 1  # ★ the second 204 cost zero upstream requests
    assert get_usage().snapshot()["providers"]["fixture"]["negative_cache_hits"] == 1  # type: ignore[index]


def test_transient_failure_is_not_negative_cached(_fresh_cache_and_usage: Settings) -> None:
    settings = _fresh_cache_and_usage
    service = ImageryService(settings)
    provider = service.get_provider("fixture")
    calls = {"n": 0}
    original = provider.get_tile_bytes

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderTransportError("upstream hiccup", provider="fixture")
        return original(*args, **kwargs)

    provider.get_tile_bytes = flaky  # type: ignore[method-assign]
    try:
        with pytest.raises(ProviderTransportError):
            service.get_tile_bytes("fixture", 10, 5, 6)
        data, _ = service.get_tile_bytes("fixture", 10, 5, 6)  # ★ retried, not entombed
    finally:
        provider.get_tile_bytes = original  # type: ignore[method-assign]

    assert calls["n"] == 2
    assert len(data) > 0
    assert get_usage().snapshot()["providers"]["fixture"]["failed_requests"] == 1  # type: ignore[index]


def test_offline_serves_cached_tiles_for_a_network_provider(
    _fresh_cache_and_usage: Settings, tmp_path
) -> None:
    """★ THE FIELD WORKFLOW: cache online, unplug, keep working over cached ground."""
    online = _fresh_cache_and_usage
    service = ImageryService(online)
    # Seed the cache exactly as the proxy would — under mapbox's variant fingerprint.
    provider = service.get_provider("mapbox_satellite")
    key_variant = provider.cache_variant(BasemapKind.SATELLITE)
    from gis.imagery.cache.base import TileCacheKey

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    service.tile_cache.put(
        TileCacheKey(provider="mapbox_satellite", z=15, x=7, y=8, variant=key_variant),
        jpeg,
    )

    offline = Settings(
        imagery_tile_cache_backend="disk",
        imagery_tile_cache_dir=online.imagery_tile_cache_dir,
        imagery_offline=True,
        allowed_providers=[],
    )
    offline_service = ImageryService(offline)

    data, mime = offline_service.get_tile_bytes("mapbox_satellite", 15, 7, 8)
    assert data == jpeg
    assert mime == "image/jpeg"

    # An uncached tile is a CONTROLLED miss (→ 204), never a network attempt.
    with pytest.raises(TileNotAvailableError):
        offline_service.get_tile_bytes("mapbox_satellite", 15, 9, 9)
    assert (
        get_usage().snapshot()["providers"]["mapbox_satellite"]["offline_cache_misses"] == 1  # type: ignore[index]
    )


def test_offline_still_honours_the_allow_list(_fresh_cache_and_usage: Settings) -> None:
    """Offline widens nothing: a provider outside LE_ALLOWED_PROVIDERS stays a 403."""
    from app.core.exceptions import ProviderToSForbidden

    settings = Settings(
        imagery_tile_cache_backend="disk",
        imagery_tile_cache_dir=_fresh_cache_and_usage.imagery_tile_cache_dir,
        imagery_offline=True,
        allowed_providers=["local_orthophoto"],
    )
    service = ImageryService(settings)
    with pytest.raises(ProviderToSForbidden):
        service.get_tile_bytes("mapbox_satellite", 15, 7, 8)


def test_mapbox_ttl_rides_the_cache_write(_fresh_cache_and_usage: Settings, monkeypatch) -> None:
    """The provider's ToS TTL is passed to the cache on put (redis/memory expiry) and
    enforced by the disk cache at read time via the registry hook."""
    captured: dict[str, object] = {}
    settings = _fresh_cache_and_usage
    service = ImageryService(settings)

    original_put = service.tile_cache.put

    def spy_put(key, data, *, ttl_s=None):
        captured["ttl_s"] = ttl_s
        return original_put(key, data, ttl_s=ttl_s)

    monkeypatch.setattr(service.tile_cache, "put", spy_put)
    service.get_tile_bytes("fixture", 10, 1, 1)
    # fixture has no provider-specific cap → None → the cache's own default applies.
    assert captured["ttl_s"] is None

    monkeypatch.setenv("LE_MAPBOX_CACHE_TTL_SECONDS", "12345")
    from gis.imagery.providers.mapbox import MapboxSatelliteProvider

    assert MapboxSatelliteProvider(access_token="t").cache_ttl_seconds == 12345


def test_in_flight_dedup_single_upstream_for_concurrent_misses(
    _fresh_cache_and_usage: Settings,
) -> None:
    """★ N concurrent requests for one missing tile → ONE upstream fetch; the rest wait
    on the per-tile lock and answer from the cache."""
    import threading

    settings = _fresh_cache_and_usage
    service = ImageryService(settings)
    provider = service.get_provider("fixture")
    calls = {"n": 0}
    entered = threading.Event()
    release = threading.Event()
    original = provider.get_tile_bytes

    def slow(*args, **kwargs):
        calls["n"] += 1
        entered.set()
        release.wait(5.0)
        return original(*args, **kwargs)

    provider.get_tile_bytes = slow  # type: ignore[method-assign]
    results: list[bytes] = []
    errors: list[Exception] = []

    def request_tile() -> None:
        try:
            data, _ = service.get_tile_bytes("fixture", 11, 6, 7, source="viewport")
            results.append(data)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        threads = [threading.Thread(target=request_tile) for _ in range(6)]
        for t in threads:
            t.start()
        entered.wait(5.0)
        release.set()
        for t in threads:
            t.join(10.0)
    finally:
        provider.get_tile_bytes = original  # type: ignore[method-assign]

    assert errors == []
    assert len(results) == 6
    assert len({bytes(r) for r in results}) == 1
    assert calls["n"] == 1  # ★ one upstream request, six answers

    fx = get_usage().snapshot()["providers"]["fixture"]  # type: ignore[index]
    assert fx["upstream_requests"] == 1
    assert fx["upstream_requests_by_source"] == {"viewport": 1}
    assert fx["cache_hits"] == 5  # the five waiters answered from the cache
