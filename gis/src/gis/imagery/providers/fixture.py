"""``FixtureProvider`` — ★★ deterministic, offline, NO NETWORK. Tests **and** demo.

★ **NOT "test-only".** This provider is the front door of ``LE_IMAGERY_OFFLINE=true`` and
of ``make seed && make up``. The brief's hard requirement is that the system work end to
end **on this machine**, and it gives no network guarantee — so the disconnected
out-of-the-box experience must be *upload -> mark -> export*, not *job failed*. Esri needs
network; ``local_orthophoto`` self-skips because ``./data/orthophotos`` ships empty. This
provider is what is left, and it must therefore be reachable by a human, not only by a
conftest.

**Deterministic, by construction.** Tiles are generated procedurally from a SHA-256 of
``(z, x, y, kind)``. The same tile is byte-identical in every process, on every machine,
forever — which is what makes it usable as a fixture at all.

★ ``hashlib``, never ``hash()``. Python's ``hash()`` of a str is **salted per process**
(PYTHONHASHSEED), so seeding from it would produce different imagery in every worker and
in every test run — a fixture that is not reproducible is not a fixture.

**The pixels are synthetic and say so.** ``attribution`` states it in words, so a chip that
somehow reaches a PDF cannot be mistaken for real imagery.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
from pathlib import Path
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.types import BasemapKind

__all__ = ["FixtureProvider"]

_log = logging.getLogger("gis.imagery.providers.fixture")

_TILE_SIZE: Final[int] = 256
_MAX_ZOOM: Final[int] = 22

_CAPTURED_AT: Final[_dt.datetime] = _dt.datetime(2026, 6, 15, 10, 30, tzinfo=_dt.UTC)
"""A fixed, deterministic capture date.

★ ``imagery_date_known`` is True for this provider precisely so that the ``captured_at``
path is exercised offline. A fixed timestamp keeps every test that touches it stable.
"""


class FixtureProvider(TileProviderMixin, ImageryProvider):
    """Synthetic farmland imagery, generated deterministically with no I/O.

    Two sources, in order:

    1. **Committed tiles** under ``tile_dir`` (``gis/tests/fixtures/tiles/{z}/{x}/{y}.png``,
       owned by IU-14), when the requested tile is present. These make a specific demo
       scene reproducible byte-for-byte.
    2. **Procedural generation**, for everything else. ★ This is why the provider is
       ``is_configured() -> True`` unconditionally: it can serve **any** tile at **any**
       zoom with no files on disk, which is what makes the offline demo work on a fresh
       clone with nothing seeded.

    Args:
        config: Shared imagery settings. Unused beyond concurrency; kept for a uniform
            constructor signature across every provider.
        tile_dir: Optional directory of committed fixture tiles.
    """

    def __init__(self, config: GisConfig | None = None, *, tile_dir: str | Path | None = None) -> None:
        cfg = config or GisConfig()
        self._tile_dir = Path(tile_dir) if tile_dir is not None else None
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = 256

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "fixture"

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        return _MAX_ZOOM

    @property
    def attribution(self) -> str:
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """Always True. ★ No key, no path, no network — that is this provider's purpose."""
        return True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=True,
            native_crs="EPSG:3857",
            tile_size_px=_TILE_SIZE,
            typical_gsd_m=0.037,  # ~resolution_at(22, 0)
            georef_ce90_m=0.0,
            # ★ Genuinely zero, and not a flattering number: these pixels are DEFINED by
            #   the slippy grid, so there is no registration error between the imagery and
            #   its geotransform. It is exact in the same way a ruler's own markings are.
            #   It is NOT a claim that a fixture GCP is survey-grade — is_authoritative
            #   stays False (TileProviderMixin's default) because the pixels are synthetic.
            imagery_date_known=True,
            rate_limit_rps=None,
            requires_attribution=False,
            allows_caching=True,
            allows_derivative_export=True,
            max_static_px=(4096, 4096),
            kinds=(BasemapKind.SATELLITE, BasemapKind.HYBRID, BasemapKind.TERRAIN),
            supports_multispectral=False,
            bands=("R", "G", "B"),
        )

    def _captured_at(self, bbox: object, zoom: int) -> _dt.datetime:
        """Return the fixed synthetic capture date."""
        return _CAPTURED_AT

    # ---- imagery -----------------------------------------------------------

    def _committed_path(self, z: int, x: int, y: int) -> Path | None:
        """Return the committed tile's path, or None when there is no tile dir / no file."""
        if self._tile_dir is None:
            return None
        path = self._tile_dir / str(z) / str(x) / f"{y}.png"
        try:
            return path if path.is_file() else None
        except OSError:  # pragma: no cover - permissions
            return None

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Return one deterministic tile. See ``ImageryProvider.get_tile``.

        ★ Never touches the network, never raises ``ProviderTransportError``. The only
        error it can raise is ``TileOutOfRangeError``, for a genuine caller bug.
        """
        self._check_tile_range(z, x, y, kind)

        path = self._committed_path(z, x, y)
        if path is not None:
            try:
                return decode_rgb(
                    path.read_bytes(), provider=self.name, expect_size=_TILE_SIZE
                )
            except Exception as exc:  # noqa: BLE001 - a bad fixture must not kill the demo
                _log.warning(
                    "%s: committed tile %s is unreadable (%s); generating procedurally",
                    self.name,
                    path,
                    exc,
                )
        return _synthesize_tile(z, x, y, kind)

    def get_tile_bytes(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> tuple[bytes, str]:
        """Return the tile as PNG bytes, passing committed files through untouched."""
        self._check_tile_range(z, x, y, kind)
        path = self._committed_path(z, x, y)
        if path is not None:
            try:
                return (path.read_bytes(), "image/png")
            except OSError:  # pragma: no cover - falls through to generation
                pass
        return super().get_tile_bytes(z, x, y, kind=kind)


def _seed_for(z: int, x: int, y: int, kind: BasemapKind) -> int:
    """Return a stable 64-bit seed for a tile.

    ★ SHA-256, not ``hash()``. Python salts str hashing per process, so ``hash()`` would
    make this provider non-deterministic across workers and across test runs — destroying
    the single property it exists to provide.
    """
    digest = hashlib.sha256(f"landexplorer/{z}/{x}/{y}/{kind.value}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _synthesize_tile(z: int, x: int, y: int, kind: BasemapKind) -> np.ndarray:
    """Generate one 256x256 RGB tile of synthetic farmland, deterministically.

    Agricultural on purpose: field patches with distinct crop colours, seeded crop-row
    striping, a track, and per-pixel noise. It is textured and structured rather than
    random, so an offline demo looks like the product's actual domain — and so a future
    matcher exercised against it is not being handed white noise.

    ★ Neighbouring tiles do NOT align into a continuous landscape. Each tile is
    independent, which is exactly right for a fixture (byte-stable, order-free, cheap) and
    exactly wrong to read as a map. Nothing in the system depends on cross-tile continuity.

    Args:
        z: Zoom level.
        x: Tile column.
        y: Tile row.
        kind: Which basemap rendering. Shifts the palette so a UI switch is visibly real.

    Returns:
        ``(256, 256, 3)`` uint8 RGB, C-contiguous.
    """
    rng = np.random.default_rng(_seed_for(z, x, y, kind))
    size = _TILE_SIZE
    rows, cols = np.mgrid[0:size, 0:size].astype(np.float32)

    palette = _PALETTES[kind]
    tile = np.zeros((size, size, 3), dtype=np.float32)

    # Fields: a few seeded rectangles, each with its own crop colour and row direction.
    tile[:, :] = np.asarray(palette[0], dtype=np.float32)
    for _ in range(int(rng.integers(3, 6))):
        r0, r1 = sorted(rng.integers(0, size, size=2))
        c0, c1 = sorted(rng.integers(0, size, size=2))
        if r1 - r0 < 24 or c1 - c0 < 24:
            continue
        colour = np.asarray(palette[int(rng.integers(0, len(palette)))], dtype=np.float32)
        tile[r0:r1, c0:c1] = colour * rng.uniform(0.85, 1.15)

        # Crop rows: a sinusoid across the field at a seeded orientation and spacing.
        angle = float(rng.uniform(0.0, np.pi))
        spacing = float(rng.uniform(4.0, 12.0))
        projected = rows[r0:r1, c0:c1] * np.cos(angle) + cols[r0:r1, c0:c1] * np.sin(angle)
        stripe = np.sin(projected * (2.0 * np.pi / spacing))[:, :, None]
        tile[r0:r1, c0:c1] += stripe * 14.0

    # A track: one straight line, the kind of linear feature this domain is full of.
    track_angle = float(rng.uniform(0.0, np.pi))
    track_offset = float(rng.uniform(0.0, size))
    distance = np.abs(
        rows * np.cos(track_angle) + cols * np.sin(track_angle) - track_offset
    )
    track_mask = distance < rng.uniform(1.5, 3.5)
    tile[track_mask] = np.asarray(palette[-1], dtype=np.float32)

    # Per-pixel noise: keeps the tile from being flat, which matters for anything that
    # looks for texture.
    tile += rng.normal(0.0, 4.0, size=(size, size, 3)).astype(np.float32)

    return np.ascontiguousarray(np.clip(tile, 0, 255).astype(np.uint8))


_PALETTES: Final[dict[BasemapKind, tuple[tuple[int, int, int], ...]]] = {
    BasemapKind.SATELLITE: (
        (86, 104, 58),   # bare soil / stubble
        (108, 138, 62),  # young crop
        (72, 112, 48),   # mature crop
        (132, 148, 96),  # dry pasture
        (156, 146, 120),  # track
    ),
    BasemapKind.HYBRID: (
        (86, 104, 58),
        (108, 138, 62),
        (72, 112, 48),
        (132, 148, 96),
        (236, 232, 224),  # a label-white track, so the switch is visibly different
    ),
    BasemapKind.TERRAIN: (
        (168, 156, 132),
        (186, 172, 144),
        (146, 140, 118),
        (200, 190, 166),
        (120, 112, 96),
    ),
}
"""Per-kind palettes. ★ The kinds are visibly distinct so that a UI basemap switch can be
seen to actually change the pixels — the defect ``BasemapKind`` was introduced to fix was a
switcher that could only ever re-render identical tiles."""
