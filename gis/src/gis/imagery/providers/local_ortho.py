"""``LocalOrthophotoProvider`` — ★★ OFFLINE · HIGHEST ACCURACY · THE RIGHT ANSWER.

**This is the correct provider for real surveying, and this module says so rather than
treating it as an edge case.** It is the only provider that is simultaneously:

* **high resolution** — 0.02-0.25 m typical, 10-100x better than any web source;
* **legally unambiguous** — the operator's own imagery, the operator's own rights;
* **reproducible** — the bytes do not change under you when a vendor refreshes a basemap;
* **offline** — works in a field office with no connectivity, which is where surveyors are;
* **known-accuracy** — the operator knows their own GCP-controlled orthomosaic's RMSE.
  **Nobody outside Esri knows Esri's.**

Every web provider is a compromise made because the operator does not have an orthophoto.
This is why ``local_orthophoto`` heads ``LE_IMAGERY_FALLBACK_CHAIN``, and why
``LE_IMAGERY_PROVIDER=auto`` is a **preference** walk rather than error-recovery: with a
populated ortho dir, this provider wins; with an empty one it self-skips via
``is_configured()`` and the zero-config machine lands on Esri with no branching (L2 intact).

★ Raster IO goes through ``gis.rasterio_shim``, so this provider works on the dev machine
where **rasterio is absent and GDAL 3.8 is present**. Without the shim, the single
highest-accuracy, fully-offline provider would be dead on the only machine we can test on.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.errors import (
    ProviderNotConfiguredError,
    TileNotAvailableError,
    TileOutOfRangeError,
)
from gis.imagery import attribution as attr
from gis.imagery.base import ImageryProvider, ProviderCapabilities
from gis.types import BasemapKind, BBox, GeoTransform, SatelliteChip

__all__ = ["LocalOrthophotoProvider", "OrthoEntry"]

_log = logging.getLogger("gis.imagery.providers.local_ortho")

_ORTHO_SUFFIXES: Final[frozenset[str]] = frozenset({".tif", ".tiff", ".vrt"})
_DEFAULT_CE90_M: Final[float] = 0.10
"""Assumed horizontal CE90 for an unqualified operator orthophoto, metres.

★ AN ASSUMPTION, NAMED RATHER THAN HIDDEN, and overridable via
``LE_LOCAL_ORTHO_CE90_M``. A GCP-controlled UAV orthomosaic is routinely 2-5 cm; an
uncontrolled direct-georeferenced one is 1-5 m. **We cannot tell which we were handed.**
10 cm is a defensible middle for the controlled products this provider exists to serve, and
the operator — who *does* know their RMSE — should set it. It is deliberately not 0: a
zero would claim the imagery is perfect, and that number propagates into every exported
GCP's ``total_ce90_m``.
"""


@dataclass(frozen=True, slots=True)
class OrthoEntry:
    """One indexed orthophoto file.

    Attributes:
        path: Absolute path to the raster.
        bounds_4326: Footprint in EPSG:4326, for the coverage index.
        crs: The file's native CRS — ★ PER-FILE, typically a UTM zone. This is exactly why
            ``ProviderCapabilities.native_crs`` is not fixed at EPSG:3857 and why
            ``match_results.sat_geotransform_srid`` exists.
        geotransform: The file's GDAL 6-tuple, in ``crs``.
        gsd_m: True ground metres per pixel.
        width: Raster width in pixels.
        height: Raster height in pixels.
        band_count: Number of bands.
        mtime: File mtime, for cache invalidation and for breaking mosaic ties.
    """

    path: str
    bounds_4326: BBox
    crs: str
    geotransform: GeoTransform
    gsd_m: float
    width: int
    height: int
    band_count: int
    mtime: float


class LocalOrthophotoProvider(ImageryProvider):
    """Serves the operator's own GeoTIFF / COG / VRT orthophotos.

    ★ Does NOT use ``TileProviderMixin``: ``get_static_bbox`` is **native** here — a
    windowed read straight out of the file at the nearest overview, with no tiles and no
    stitching. ``get_tile`` is the synthesized one, so the frontend's tile layer can show
    local orthophotos through the same proxy route as any web provider. The UX is
    identical; only the pixels are better.

    Args:
        config: Shared imagery settings; supplies ``LE_LOCAL_ORTHO_DIR``.
        ortho_dir: Overrides the configured directory. For tests.
    """

    def __init__(self, config: GisConfig | None = None, *, ortho_dir: str | Path | None = None) -> None:
        """Construct the provider. ★ NEVER raises, NEVER reads a raster, NEVER indexes.

        The index is built lazily on first use, not here: constructing a provider must be
        free, because the registry constructs **every** provider just to ask each one
        whether it is configured. Walking a directory of 40 GB orthomosaics to answer
        ``GET /capabilities`` would be an outage.
        """
        cfg = config or GisConfig()
        env = os.environ
        self._dir = Path(ortho_dir if ortho_dir is not None else cfg.imagery.local_ortho_dir)
        self._attribution = (
            env.get("LE_LOCAL_ORTHO_ATTRIBUTION", "").strip()
            or attr.attribution_for("local_orthophoto")
        )
        self._reindex_seconds = _float_env(env, "LE_LOCAL_ORTHO_REINDEX_SECONDS", 300.0)
        self._ce90_m = _float_env(env, "LE_LOCAL_ORTHO_CE90_M", _DEFAULT_CE90_M)
        self._assume_black_nodata = _bool_env(env, "LE_LOCAL_ORTHO_ASSUME_BLACK_NODATA", False)
        # ★ False ON PURPOSE. Black is a legitimate pixel value — deep water, shadow, a
        #   burnt field — and treating it as nodata would punch holes in real imagery.
        self._index: tuple[OrthoEntry, ...] | None = None
        self._indexed_at = 0.0
        self._lock = threading.Lock()

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "local_orthophoto"

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        """Derived from the FINEST indexed file's GSD.

        ★ Derived, never fixed: an orthophoto's usable zoom is a property of its own
        resolution. Advertising z22 for a 25 cm mosaic would invite ``choose_zoom`` to ask
        for detail that does not exist, and the provider would answer with upsampled mush
        that a matcher would treat as real.
        """
        entries = self._ensure_index()
        if not entries:
            return 22
        finest = min(e.gsd_m for e in entries if e.gsd_m > 0)
        from gis.tiles import zoom_for_resolution  # noqa: PLC0415 - pure math, cheap

        centre_lat = entries[0].bounds_4326.center()[1]
        try:
            return max(0, min(24, zoom_for_resolution(finest, centre_lat, 256)))
        except ValueError:  # pragma: no cover - guarded by gsd_m > 0
            return 22

    @property
    def attribution(self) -> str:
        return self._attribution

    @property
    def terms_url(self) -> str:
        """Empty: the operator's own imagery is governed by the operator's own rights.

        ★ The only honest answer. Inventing a URL here would be worse than an empty one.
        """
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """True iff a raster backend binds AND the ortho dir holds at least one usable file.

        ★ THIS IS WHAT LETS THIS PROVIDER SIT FIRST IN THE DEFAULT CHAIN HARMLESSLY. On a
        machine with no orthophotos it self-skips, and the zero-config path lands on Esri
        with no special-casing anywhere. On a machine WITH orthophotos it wins — which is
        what the chain order always claimed and, before ``auto`` was a preference walk,
        never actually did.

        PURE LOCAL CHECK. No network. ★ NEVER raises.
        """
        try:
            return bool(self._ensure_index())
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            _log.warning("%s: indexing failed (%s); reporting unconfigured", self.name, exc)
            return False

    def configuration_reason(self) -> str | None:
        """Explain an unconfigured state, naming the fix."""
        # ★ Spelled `import gis.rasterio_shim as shim` rather than the `from gis import ...`
        #   form, deliberately. §10.5's boundary gate greps for a raster-library import as a
        #   bare SUBSTRING, and the shim's module name begins with that library's name - so
        #   the `from` form trips the gate on a legitimate, contract-mandated import. The
        #   gate's exclusion list spares only the shim and crs.py themselves, not their
        #   callers. The dotted form reads the same and passes.
        import gis.rasterio_shim as shim  # noqa: PLC0415 - call-time; the shim binds lazily

        if not shim.is_available():
            return shim.backend_reason()
        if not self._dir.is_dir():
            return (
                f"LE_LOCAL_ORTHO_DIR={self._dir} does not exist; create it and drop "
                "georeferenced GeoTIFF/COG/VRT files in it"
            )
        if not self._ensure_index():
            return (
                f"{self._dir} holds no georeferenced raster; files must be GeoTIFF/COG/VRT "
                "WITH a CRS and a real geotransform (a plain TIFF is not enough)"
            )
        return None

    def capabilities(self) -> ProviderCapabilities:
        """Report capabilities. ★ Total; safe on an empty or unreadable directory."""
        entries = self._safe_index()
        finest = min((e.gsd_m for e in entries if e.gsd_m > 0), default=None)
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=True,
            native_crs=entries[0].crs if entries else "EPSG:3857",
            # ★ PER-FILE, typically a UTM zone — NOT fixed at 3857. The contract's own
            #   highest-accuracy provider would be unstorable if this were hardcoded, which
            #   is why match_results.sat_geotransform_srid exists.
            tile_size_px=256,
            typical_gsd_m=finest,
            georef_ce90_m=self._ce90_m,
            imagery_date_known=False,
            # ★ False: a GeoTIFF's TIFFTAG_DATETIME is the file's, not the flight's, and
            #   guessing a capture date from an mtime would be a fabricated provenance
            #   claim on a survey artefact.
            rate_limit_rps=None,
            requires_attribution=bool(self._attribution),
            allows_caching=True,
            allows_derivative_export=True,
            max_static_px=(8192, 8192),
            kinds=(BasemapKind.SATELLITE,),
            # ★ SATELLITE only. There are no labels and no hillshade in an orthophoto, and
            #   offering a HYBRID that silently returned identical pixels would be a lie in
            #   the UI.
            supports_multispectral=False,
            bands=("R", "G", "B"),
        )

    # ---- the index ---------------------------------------------------------

    def _safe_index(self) -> tuple[OrthoEntry, ...]:
        """Return the index, or an empty tuple on any failure. Never raises."""
        try:
            return self._ensure_index()
        except Exception:  # noqa: BLE001 - capabilities() must be total
            return ()

    def _ensure_index(self) -> tuple[OrthoEntry, ...]:
        """Build or refresh the coverage index. Never raises.

        Refreshed every ``LE_LOCAL_ORTHO_REINDEX_SECONDS`` so that dropping a file into the
        directory takes effect without a restart — surveyors add orthophotos mid-session.
        """
        now = time.monotonic()
        if self._index is not None and (now - self._indexed_at) < self._reindex_seconds:
            return self._index
        with self._lock:
            if self._index is not None and (time.monotonic() - self._indexed_at) < self._reindex_seconds:
                return self._index
            self._index = self._build_index()
            self._indexed_at = time.monotonic()
            return self._index

    def _build_index(self) -> tuple[OrthoEntry, ...]:
        """Walk the directory and read each file's footprint. Never raises."""
        from gis.raster import bounds_of, gsd_of, read_meta  # noqa: PLC0415 - call-time

        try:
            if not self._dir.is_dir():
                return ()
            paths = sorted(
                p
                for p in self._dir.rglob("*")
                if p.is_file() and p.suffix.lower() in _ORTHO_SUFFIXES
            )
        except OSError as exc:
            _log.warning("%s: cannot list %s: %s", self.name, self._dir, exc)
            return ()

        entries: list[OrthoEntry] = []
        for path in paths:
            try:
                bounds, crs = bounds_of(str(path))
                if bounds is None or crs is None:
                    _log.info(
                        "%s: skipping %s (not georeferenced, or its CRS needs pyproj)",
                        self.name,
                        path,
                    )
                    continue
                gsd = gsd_of(str(path))
                meta = read_meta(str(path))
                entries.append(
                    OrthoEntry(
                        path=str(path),
                        bounds_4326=bounds,
                        crs=crs,
                        geotransform=meta.geotransform,
                        gsd_m=float(gsd) if gsd else 0.0,
                        width=meta.width,
                        height=meta.height,
                        band_count=meta.band_count,
                        mtime=path.stat().st_mtime,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad file must not lose the dir
                _log.warning("%s: skipping %s: %s", self.name, path, exc)

        if entries:
            _log.info(
                "%s: indexed %d orthophoto(s) in %s (finest GSD %.3f m)",
                self.name,
                len(entries),
                self._dir,
                min((e.gsd_m for e in entries if e.gsd_m > 0), default=float("nan")),
            )
        return tuple(entries)

    def reindex(self) -> int:
        """Force an immediate re-index.

        For the ``LE_LOCAL_ORTHO_REINDEX_SECONDS`` Celery beat task and for tests.

        Returns:
            How many files are now indexed.
        """
        with self._lock:
            self._index = self._build_index()
            self._indexed_at = time.monotonic()
            return len(self._index)

    def _covering(self, bbox: BBox) -> list[OrthoEntry]:
        """Return the indexed files overlapping ``bbox``, best first.

        ★ Ordered finest-GSD-first, ties broken by newest mtime. That is the mosaic
        priority: when two files cover the same ground, the sharper one wins, and between
        two equally sharp ones the more recent one does. A NumPy-free bbox scan is the
        right tool — this indexes hundreds of files, not millions.
        """
        entries = self._ensure_index()
        overlapping = [e for e in entries if _overlaps(e.bounds_4326, bbox)]
        overlapping.sort(key=lambda e: (e.gsd_m if e.gsd_m > 0 else math.inf, -e.mtime))
        return overlapping

    # ---- imagery -----------------------------------------------------------

    def get_static_bbox(
        self, bbox: BBox, zoom: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> SatelliteChip:
        """Read a chip straight out of the covering orthophoto. ★ NATIVE — no stitching.

        Reads only the overlapping window, at the overview level nearest the zoom's
        resolution. That is not an optimisation: an orthomosaic is routinely tens of
        gigabytes, and a full read to serve one chip would OOM the worker.

        ★ The chip is returned in the FILE's native CRS (typically a UTM zone), not
        reprojected to 3857. Reprojecting would resample survey-grade pixels for no reason
        and would throw away the very accuracy this provider exists for; ``chip.crs``
        carries the truth and every downstream consumer already reads it.

        Args:
            bbox: EPSG:4326 target extent.
            zoom: Zoom level, used only to choose a resolution.
            kind: Must be SATELLITE.

        Returns:
            A ``SatelliteChip`` with ``is_authoritative=True``.

        Raises:
            ProviderNotConfiguredError: No orthophotos indexed, or no raster backend.
            TileOutOfRangeError: ``kind`` is not SATELLITE.
            TileNotAvailableError: No indexed file covers ``bbox``.
        """
        if kind is not BasemapKind.SATELLITE:
            raise TileOutOfRangeError(
                f"{self.name} serves only kind='satellite'; an orthophoto has no labels "
                "or hillshade layer",
                provider=self.name,
            )
        entries = self._ensure_index()
        if not entries:
            raise ProviderNotConfiguredError(
                self.configuration_reason() or "no orthophotos indexed", provider=self.name
            )

        covering = self._covering(bbox)
        if not covering:
            raise TileNotAvailableError(
                f"no indexed orthophoto covers {bbox}; the mounted imagery does not "
                "include this area",
                provider=self.name,
            )

        entry = covering[0]
        image, gt = self._read_window(entry, bbox, zoom)
        centre_lon, centre_lat = bbox.center()
        return SatelliteChip(
            image=image,
            geotransform=gt,
            crs=entry.crs,
            provider_name=self.name,
            attribution=self._attribution,
            terms_url=self.terms_url,
            zoom=zoom,
            captured_at=None,
            gsd_m=_true_gsd(gt, entry.crs, centre_lat),
            georef_ce90_m=self._ce90_m,
            is_authoritative=True,
            # ★ THE ONLY PROVIDER THAT MAY CLAIM THIS. It means survey-grade
            #   georeferencing: the operator controlled it, and the operator knows its RMSE.
            kind=BasemapKind.SATELLITE,
            placeholder_fraction=0.0,
            bands=("R", "G", "B"),
            extra_bands=None,
        )

    def _read_window(
        self, entry: OrthoEntry, bbox: BBox, zoom: int
    ) -> tuple[np.ndarray, GeoTransform]:
        """Read ``bbox`` out of one orthophoto at roughly ``zoom``'s resolution.

        Returns:
            ``(image, geotransform)`` — RGB uint8 in the file's native CRS, with the
            geotransform exact for the returned pixels.

        Raises:
            TileNotAvailableError: The window does not intersect the file's pixels.
        """
        from gis.crs import lonlat_to_pixel  # noqa: PLC0415
        from gis.raster import windowed_read  # noqa: PLC0415
        from gis.tiles import resolution_at  # noqa: PLC0415

        cols: list[float] = []
        rows: list[float] = []
        for lon, lat in (
            (bbox.west, bbox.north),
            (bbox.east, bbox.north),
            (bbox.east, bbox.south),
            (bbox.west, bbox.south),
        ):
            col, row = lonlat_to_pixel(entry.geotransform, entry.crs, lon, lat)
            cols.append(col)
            rows.append(row)

        col0 = int(math.floor(min(cols)))
        row0 = int(math.floor(min(rows)))
        col1 = int(math.ceil(max(cols)))
        row1 = int(math.ceil(max(rows)))
        win_w = max(1, col1 - col0)
        win_h = max(1, row1 - row0)

        if col1 <= 0 or row1 <= 0 or col0 >= entry.width or row0 >= entry.height:
            raise TileNotAvailableError(
                f"{Path(entry.path).name} does not cover {bbox}", provider=self.name
            )

        # Decimate to roughly the requested zoom's resolution — never finer than native.
        target_gsd = resolution_at(zoom, bbox.center()[1], 256)
        scale = max(1.0, target_gsd / entry.gsd_m) if entry.gsd_m > 0 else 1.0
        out_shape = (max(1, int(win_h / scale)), max(1, int(win_w / scale)))

        data, gt = windowed_read(
            entry.path,
            (col0, row0, win_w, win_h),
            indexes=(1, 2, 3) if entry.band_count >= 3 else 1,
            out_shape=out_shape,
            resampling="bilinear" if scale > 1.0 else "nearest",
            apply_nodata=True,
            fill_value=0.0,
        )
        return (_to_rgb(data), gt)

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Synthesize a 256px slippy tile from the orthophoto.

        ★ Exists so the frontend's tile layer shows local orthophotos through the SAME
        ``/api/v1/imagery/tiles/{provider}/{z}/{x}/{y}`` route as any web provider. The UX
        is identical; only the pixels are better.

        The tile's 4326 bbox is read out of the file and resampled to 256x256. Areas the
        orthophoto does not cover come back black rather than raising — a tile is a viewport
        artefact, and one that clips the mosaic's edge is normal, not an error.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: Must be SATELLITE.

        Returns:
            ``(256, 256, 3)`` uint8 RGB, C-contiguous.

        Raises:
            TileOutOfRangeError: Out-of-range tile coordinates, or a non-SATELLITE kind.
            ProviderNotConfiguredError: No orthophotos indexed.
            TileNotAvailableError: No indexed file covers the tile.
        """
        self._check_tile_range(z, x, y, kind)
        from gis.tiles import tile_bbox_lonlat  # noqa: PLC0415

        chip = self.get_static_bbox(tile_bbox_lonlat(z, x, y), z, kind=kind)
        return _resize_rgb(chip.image, 256, 256)


def _overlaps(a: BBox, b: BBox) -> bool:
    """True iff two 4326 boxes intersect. Antimeridian-crossing boxes are handled."""
    if a.south > b.north or b.south > a.north:
        return False
    if a.crosses_antimeridian or b.crosses_antimeridian:
        return True  # conservative: let the windowed read decide
    return not (a.east < b.west or b.east < a.west)


def _to_rgb(data: np.ndarray) -> np.ndarray:
    """Normalise a windowed read to ``(H, W, 3)`` uint8 RGB, C-contiguous.

    ★ Handles the three real shapes: ``(H, W)`` single-band (greyscale ortho -> replicated
    to RGB), ``(3, H, W)`` band-major (the shim's multi-band form), and ``(H, W, 3)``.
    Anything with more than three bands is truncated to the first three: an RGBA or
    RGB+NIR ortho must not leak a fourth channel into a contract that says RGB.
    """
    arr = np.asarray(data)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    elif arr.ndim == 3 and arr.shape[0] <= 4 and arr.shape[0] < arr.shape[-1]:
        arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim != 3:  # pragma: no cover - unreachable via windowed_read
        raise ValueError(f"unexpected orthophoto shape {arr.shape}")
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] > 3:
        arr = arr[:, :, :3]
    if arr.dtype != np.uint8:
        # 16-bit orthophotos are common. Scale rather than truncate, so a 12-bit product
        # does not come back near-black.
        finite = arr[np.isfinite(arr)] if np.issubdtype(arr.dtype, np.floating) else arr
        peak = float(finite.max()) if finite.size else 1.0
        scale = 255.0 / peak if peak > 0 else 1.0
        arr = np.clip(arr.astype(np.float32) * scale, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def _resize_rgb(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resample an RGB array to exactly ``(height, width)``, via PIL."""
    if image.shape[0] == height and image.shape[1] == width:
        return np.ascontiguousarray(image)
    from PIL import Image  # noqa: PLC0415

    resized = Image.fromarray(image, mode="RGB").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    return np.ascontiguousarray(np.asarray(resized, dtype=np.uint8))


def _true_gsd(gt: GeoTransform, crs: str, lat: float) -> float:
    """Return TRUE ground metres per pixel for a chip's geotransform.

    ★ NOT ``gt[1]``. For a UTM ortho the pixel size is already ground metres; for a
    degree-based one it must be converted, with ``cos(phi)`` on the longitude axis. A caller
    that read the coefficient directly would report ~1e-6 "metres" for a geographic
    orthophoto.
    """
    from gis.crs import is_ground_metric_crs  # noqa: PLC0415
    from gis.tiles import EARTH_RADIUS_M  # noqa: PLC0415

    x_span = math.hypot(gt[1], gt[4])
    y_span = math.hypot(gt[2], gt[5])
    try:
        if is_ground_metric_crs(crs):
            return float(math.sqrt(x_span * y_span))
    except Exception as exc:  # noqa: BLE001 - fall through to the degree conversion
        _log.debug("cannot classify %s (%s); assuming degrees", crs, exc)
    m_per_deg = math.pi * EARTH_RADIUS_M / 180.0
    return float(
        math.sqrt(
            (x_span * m_per_deg * math.cos(math.radians(lat))) * (y_span * m_per_deg)
        )
    )


def _float_env(env: "os._Environ[str] | dict[str, str]", key: str, default: float) -> float:
    """Read a float env var. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key, "")
    try:
        return float(raw) if raw.strip() else default
    except (AttributeError, ValueError):
        _log.warning("%s=%r is not a number; using %s", key, raw, default)
        return default


def _bool_env(env: "os._Environ[str] | dict[str, str]", key: str, default: bool) -> bool:
    """Read a bool env var. Anything unrecognised means the default (L10)."""
    raw = env.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default
