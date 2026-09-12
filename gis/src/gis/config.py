"""``GisConfig`` — framework-free configuration for the ``gis`` package (§9).

Plain stdlib dataclasses. **NOT pydantic**: ``gis`` is an installable library that must
import with zero runtime installs, and a settings framework in a library is a dependency
every consumer inherits whether they want it or not. The backend owns the pydantic
``Settings`` and constructs a ``GisConfig`` from it.

★ L10 — EVERY SETTING HAS A WORKING DEFAULT. ``GisConfig()`` and
``GisConfig.from_env({})`` both succeed on an empty environment and yield a working,
keyless, zero-config system. There are no required env vars. Nothing here raises for a
missing key; ``is_configured()`` on the relevant provider reports readiness instead.

★ L2 — THE DEFAULT IMAGERY PROVIDER IS KEYLESS. ``provider="auto"`` walks the fallback
chain and takes the first configured provider, which on a bare machine is Esri.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Final, Self

__all__ = [
    "ElevationConfig",
    "ExifConfig",
    "GisConfig",
    "ImageryConfig",
    "SearchConfig",
    "TileCacheConfig",
]

_ENV_PREFIX: Final[str] = "LE_"


def _get_str(env: Mapping[str, str], key: str, default: str) -> str:
    """Read a string setting. An unset or blank var means the default."""
    value = env.get(key)
    return value.strip() if value and value.strip() else default


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    """Read a boolean setting.

    ★ Anything unrecognised is the DEFAULT, with no exception. ``LE_IMAGERY_STRICT=yes``
    must not silently become False, and ``=maybe`` must not take the process down at
    import — L10 says an empty or malformed environment never raises.
    """
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return default


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    """Read a float setting. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    """Read an int setting. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_tuple(env: Mapping[str, str], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Read a comma-separated list setting. Blank entries are dropped."""
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class TileCacheConfig:
    """Tile cache settings. ``LE_IMAGERY_TILE_CACHE_*``.

    ★ Several provider terms CAP caching duration. ``ProviderCapabilities.allows_caching``
    gates whether a persistent backend may be used at all; this only says how.
    """

    backend: str = "disk"
    """``memory | disk | redis``. ``redis`` in prod: tile fetching happens inside Celery
    workers and a disk cache in a container is per-replica, so four workers searching the
    same AOI would fetch every tile four times."""
    directory: str = "./data/tile_cache"
    ttl_seconds: int = 2_592_000
    max_bytes: int = 21_474_836_480

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build from an environment mapping. Never raises."""
        return cls(
            backend=_get_str(env, "LE_IMAGERY_TILE_CACHE_BACKEND", "disk"),
            directory=_get_str(env, "LE_IMAGERY_TILE_CACHE_DIR", "./data/tile_cache"),
            ttl_seconds=_get_int(env, "LE_IMAGERY_TILE_CACHE_TTL_SECONDS", 2_592_000),
            max_bytes=_get_int(env, "LE_IMAGERY_TILE_CACHE_MAX_BYTES", 21_474_836_480),
        )


@dataclass(frozen=True, slots=True)
class ImageryConfig:
    """Imagery provider settings. ``LE_IMAGERY_*`` and the per-provider keys."""

    provider: str = "auto"
    """★ ``auto`` is a PREFERENCE: walk ``fallback_chain`` and take the first configured
    provider. An explicit name means THAT provider, with the chain as error-recovery only."""
    fallback_chain: tuple[str, ...] = ("local_orthophoto", "mapbox_satellite", "esri_world_imagery")
    """★ ``local_orthophoto`` FIRST: mounted orthophotos are definitionally better than any
    web tile source. It self-skips via ``is_configured()`` when the dir is empty, so the
    zero-config machine lands on Esri with no branching (L2)."""
    strict: bool = False
    """``true`` in prod: no silent fallback. Dev is forgiving; prod is loud."""
    offline: bool = False
    """``true`` restricts resolution to ``local_orthophoto`` and ``fixture``. A first-class
    supported mode, not a test flag."""
    allowed_providers: tuple[str, ...] = ()
    """Empty means all registered. The operator's hard allow-list."""
    direct_tile_urls: bool = False
    """``false`` keeps every provider behind the proxy, preserving the ToS chokepoint, the
    shared quota bucket and worker/browser cache identity."""
    max_concurrent_fetches: int = 4
    rate_limit_rps: float = 5.0
    request_timeout_seconds: float = 15.0
    max_retries: int = 3
    user_agent: str = "LandExplorer/1.0 (+https://example.invalid)"
    """★ Operators should set a real contact. Several providers' terms require it."""
    local_ortho_dir: str = "./data/orthophotos"
    cache: TileCacheConfig = field(default_factory=TileCacheConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build from an environment mapping. Never raises."""
        return cls(
            provider=_get_str(env, "LE_IMAGERY_PROVIDER", "auto"),
            fallback_chain=_get_tuple(
                env,
                "LE_IMAGERY_FALLBACK_CHAIN",
                ("local_orthophoto", "mapbox_satellite", "esri_world_imagery"),
            ),
            strict=_get_bool(env, "LE_IMAGERY_STRICT", False),
            offline=_get_bool(env, "LE_IMAGERY_OFFLINE", False),
            allowed_providers=_get_tuple(env, "LE_ALLOWED_PROVIDERS", ()),
            direct_tile_urls=_get_bool(env, "LE_IMAGERY_DIRECT_TILE_URLS", False),
            max_concurrent_fetches=_get_int(env, "LE_IMAGERY_MAX_CONCURRENT_FETCHES", 4),
            rate_limit_rps=_get_float(env, "LE_IMAGERY_RATE_LIMIT_RPS", 5.0),
            request_timeout_seconds=_get_float(
                env, "LE_IMAGERY_REQUEST_TIMEOUT_SECONDS", 15.0
            ),
            max_retries=_get_int(env, "LE_IMAGERY_MAX_RETRIES", 3),
            user_agent=_get_str(
                env, "LE_IMAGERY_USER_AGENT", "LandExplorer/1.0 (+https://example.invalid)"
            ),
            local_ortho_dir=_get_str(env, "LE_LOCAL_ORTHO_DIR", "./data/orthophotos"),
            cache=TileCacheConfig.from_env(env),
        )


@dataclass(frozen=True, slots=True)
class ElevationConfig:
    """Elevation settings (§9.6a). ``LE_ELEVATION_*``."""

    provider: str = "none"
    """★ ``none`` is KEYLESS, OFFLINE and TERMINAL: ``elevation_m`` and ``elevation_source``
    are both NULL and the job says ``ELEVATION_UNAVAILABLE``. Honest beats absent."""
    local_dem_dir: str = "./data/dem"
    """An empty dir means unavailable, no crash."""
    copernicus_dem_url: str = ""
    cache_ttl_seconds: int = 2_592_000

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build from an environment mapping. Never raises."""
        return cls(
            provider=_get_str(env, "LE_ELEVATION_PROVIDER", "none"),
            local_dem_dir=_get_str(env, "LE_LOCAL_DEM_DIR", "./data/dem"),
            copernicus_dem_url=_get_str(env, "LE_COPERNICUS_DEM_URL", ""),
            cache_ttl_seconds=_get_int(env, "LE_ELEVATION_CACHE_TTL_SECONDS", 2_592_000),
        )


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Candidate-search settings (§9.7). ``LE_SEARCH_*``."""

    default_zoom: int = 18
    default_radius_m: float = 1000.0
    max_radius_m: float = 50_000.0
    max_candidates: int = 25
    window_size_px: int = 1024
    overlap_ratio: float = 0.5
    """★ 0.5 buys the 512 px footprint guarantee. At 0.25 the guarantee is only 256 px."""
    target_gsd_m: float = 0.5
    max_tiles_per_job: int = 512
    max_static_tiles: int = 16
    max_static_pixels: int = 4_194_304
    """★ 4 MP, not 64 MP. A 64-megapixel stitch inside a GET is the workload L5 forbids."""
    max_bbox_area_km2: float = 2500.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build from an environment mapping. Never raises."""
        return cls(
            default_zoom=_get_int(env, "LE_SEARCH_DEFAULT_ZOOM", 18),
            default_radius_m=_get_float(env, "LE_SEARCH_DEFAULT_RADIUS_M", 1000.0),
            max_radius_m=_get_float(env, "LE_SEARCH_MAX_RADIUS_M", 50_000.0),
            max_candidates=_get_int(env, "LE_SEARCH_MAX_CANDIDATES", 25),
            window_size_px=_get_int(env, "LE_SEARCH_WINDOW_SIZE_PX", 1024),
            overlap_ratio=_get_float(env, "LE_SEARCH_OVERLAP_RATIO", 0.5),
            target_gsd_m=_get_float(env, "LE_SEARCH_TARGET_GSD_M", 0.5),
            max_tiles_per_job=_get_int(env, "LE_MAX_TILES_PER_JOB", 512),
            max_static_tiles=_get_int(env, "LE_MAX_STATIC_TILES", 16),
            max_static_pixels=_get_int(env, "LE_MAX_STATIC_PIXELS", 4_194_304),
            max_bbox_area_km2=_get_float(env, "LE_SEARCH_MAX_BBOX_AREA_KM2", 2500.0),
        )


@dataclass(frozen=True, slots=True)
class ExifConfig:
    """EXIF hint settings (§9.7). ``LE_EXIF_*``."""

    radius_inflation: float = 3.0
    """Multiply a claimed horizontal error by this. A receiver's own estimate is
    optimistic exactly where this product is used."""
    min_radius_m: float = 250.0
    """Floor for an inflated radius. Catches the exported-through-desktop-software case,
    where the claimed error is small and simply wrong."""

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build from an environment mapping. Never raises."""
        return cls(
            radius_inflation=_get_float(env, "LE_EXIF_RADIUS_INFLATION", 3.0),
            min_radius_m=_get_float(env, "LE_EXIF_MIN_RADIUS_M", 250.0),
        )


@dataclass(frozen=True, slots=True)
class GisConfig:
    """The ``gis`` package's complete configuration.

    ★ ``GisConfig()`` with no arguments is a fully working, keyless, offline-capable,
    zero-config system. That is L10 and L2 expressed as a default argument list.
    """

    imagery: ImageryConfig = field(default_factory=ImageryConfig)
    elevation: ElevationConfig = field(default_factory=ElevationConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    exif: ExifConfig = field(default_factory=ExifConfig)
    gcp_consistency_tolerance_m: float = 0.5
    """How far a forward-projected ``satellite_px`` may disagree with a supplied lat/lon
    before a GCP adjustment is ambiguous. ★ At 0.5 m, a half-pixel round-trip
    inconsistency (~0.21 m at z18, ~0.42 m at z17) would spuriously reject correct edits —
    which is why ``lonlat_to_pixel`` is the exact inverse of ``pixel_to_lonlat``."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        """Build the whole config from an environment mapping.

        ★ NEVER RAISES. An empty mapping yields the working defaults; an unparseable
        value falls back to its default rather than taking the process down (L10). This is
        what makes ``docker compose up`` with an empty ``.env`` work.

        Args:
            env: The environment. Defaults to ``os.environ``.

        Returns:
            A fully populated ``GisConfig``.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        return cls(
            imagery=ImageryConfig.from_env(source),
            elevation=ElevationConfig.from_env(source),
            search=SearchConfig.from_env(source),
            exif=ExifConfig.from_env(source),
            gcp_consistency_tolerance_m=_get_float(
                source, "LE_GCP_CONSISTENCY_TOLERANCE_M", 0.5
            ),
        )

    def with_overrides(self, **kwargs: object) -> Self:
        """Return a copy with the given top-level fields replaced.

        Args:
            **kwargs: Field names and values.

        Returns:
            A new ``GisConfig``.
        """
        return replace(self, **kwargs)  # type: ignore[arg-type]
