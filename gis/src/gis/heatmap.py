"""Per-window pixel heatmaps to one true-metre geographic grid (§4.26).

★ THE MISSING CONVERTER, and the ONLY function permitted to see both a ``PixelHeatmap``
and a geotransform.

Each ``PixelHeatmap`` produced by ``ai_engine`` lives in **its own window's pixel frame**
— a different frame per window, none of which knows what a CRS is (L3). This module fuses
them into a single ``GeoHeatmap`` whose cells are EPSG:4326 centroids on a **local UTM
grid**.

Why UTM and not 3857 (§5.2's rule: never accumulate in Web Mercator)
--------------------------------------------------------------------
A density accumulated on a lon/lat or Web-Mercator grid has cells whose true ground area
shrinks with ``cos(phi)``, so the density is biased poleward and cells at the top of the
AOI silently count for less ground than cells at the bottom. The grid is built in a local
UTM zone, where a cell is a cell is a cell, and emitted as 4326 centroids at the end.

★ Per SCOPE.md the confidence heatmap over candidate camera locations is DEFERRED
(``ai_engine`` ships the ABC only), so nothing calls this in the current build. It is
implemented rather than stubbed because SCOPE.md §7 requires that enabling the engine
later touch nothing outside ``ai_engine/``.

★ STRUCTURAL COUPLING, DELIBERATE. ``ai_engine.types.PixelHeatmap`` is owned by IU-01 and
CONTRACT.md never states its fields (§2.2 names the module; §4.11 names only the type).
§4.26 writes this signature's annotation as a **string**, deliberately unresolved, and
§10.2 grants ``gis.heatmap`` the ``ai_engine.types`` import. Rather than import a type
whose shape is unspecified, this module reads the structural surface declared by
``_PixelHeatmapLike``/``_ComponentLike`` below. A mismatch surfaces as a loud
``AttributeError`` naming the field, never as a silently empty map.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from gis.crs import transform_points, utm_epsg_for
from gis.tiles import pixel_to_lonlat
from gis.types import BBox, LonLat

__all__ = [
    "GeoHeatmap",
    "GeoHeatmapCell",
    "fuse_pixel_heatmaps",
]


class _ComponentLike(Protocol):
    """Structural shape of ``ai_engine.types.heatmap.HeatmapComponent``, in WINDOW pixels."""

    mu_px: tuple[float, float]
    cov_px2: Any
    weight: float
    confidence: float
    window_id: str


class _PixelHeatmapLike(Protocol):
    """Structural shape of ``ai_engine.types.heatmap.PixelHeatmap``."""

    components: Sequence[_ComponentLike]
    background_weight: float


class _WindowLike(Protocol):
    """The part of ``ai_engine.types.CandidateWindow`` this module is allowed to read."""

    geotransform: tuple[float, float, float, float, float, float]
    crs: str
    gsd_m: float


@dataclass(frozen=True, slots=True)
class GeoHeatmapCell:
    """One cell of a fused geographic heatmap.

    Attributes:
        lon: Cell-centre longitude, EPSG:4326.
        lat: Cell-centre latitude, EPSG:4326.
        score: Normalised density in ``[0, 1]``, relative to the map's peak.
        sample_count: How many candidate windows contributed. ★ Absent != 0: a cell no
            window covered is not a cell every window agreed was empty, and the UI dims
            low-sample cells for exactly that reason.
        components: Per-window contributions, keyed by ``window_id``.
    """

    lon: float
    lat: float
    score: float
    sample_count: int
    components: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeoHeatmap:
    """A fused posterior over camera locations, ready for ``confidence_heatmaps``/``_cells``.

    Attributes:
        bbox: The EPSG:4326 extent the grid covers.
        cell_size_m: Cell edge in TRUE metres.
        grid_cols: Grid width in cells.
        grid_rows: Grid height in cells.
        cells: SPARSE — only cells with non-negligible mass are emitted.
        argmax: Position of the peak, or None if the map carries no mass at all.
        argmax_score: The peak's score, or None.
        entropy_norm: ``H(p) / log(N)`` in ``[0, 1]``. ``> 0.6`` means the posterior is
            diffuse and we have NOT localised, regardless of any single candidate's score.
            ★ While the score model is uncalibrated this is an ORDINAL, comparative
            signal only — it is never rendered as a probability.
    """

    bbox: BBox
    cell_size_m: float
    grid_cols: int
    grid_rows: int
    cells: tuple[GeoHeatmapCell, ...]
    argmax: LonLat | None
    argmax_score: float | None
    entropy_norm: float


# Cells below this share of the peak are dropped: the map is sparse by contract and a
# float64 Gaussian has support everywhere, so without a floor every grid is dense.
_SPARSE_FLOOR: float = 1e-6

# Component support is truncated at this many sigma. Beyond ~4 sigma a 2-D Gaussian holds
# under 0.03% of its mass, and evaluating it over the whole grid is what turns a fuse into
# an O(windows * cells) stall.
_SUPPORT_SIGMA: float = 4.0


def fuse_pixel_heatmaps(
    items: Sequence[tuple[_PixelHeatmapLike, _WindowLike]],
    *,
    cell_size_m: float,
) -> GeoHeatmap:
    """Fuse per-window pixel heatmaps into one geographic heatmap.

    Each component's mean is carried from its own window's pixel frame to lon/lat through
    that window's geotransform (pixel-CENTRE convention, as every coordinate in this
    system is), then into a shared local UTM grid where the densities are accumulated.
    Overlapping windows contribute to the same cell and ``sample_count`` aggregates.

    Component covariances are converted from window pixels to true metres by
    ``gsd_m**2 * cov_px`` — the same preferred, no-sign-to-reverse path
    ``gis.accuracy.pixel_cov_to_metres`` uses — with the y-flip that takes window ``v``
    (south-growing) to ENU north.

    Args:
        items: ``(pixel_heatmap, candidate_window)`` pairs. Each heatmap must be in the
            paired window's pixel frame. An empty sequence yields an empty map.
        cell_size_m: Grid cell edge in TRUE metres, ``> 0``.

    Returns:
        The fused ``GeoHeatmap``. Cells are sparse and scores are normalised so the peak
        is 1.0.

    Raises:
        ValueError: If ``cell_size_m <= 0``, a covariance is not a finite (2,2), or a
            window's ``gsd_m`` is not positive.
        AttributeError: If a supplied heatmap/window does not carry the fields §4.26
            requires — loudly, naming the field, rather than producing an empty map.
        CrsError: If a window's CRS needs a backend that cannot be bound.
        OutsideUtmError: If the fused extent's centre is beyond ``|lat| = 84``.
    """
    if not math.isfinite(cell_size_m) or cell_size_m <= 0.0:
        raise ValueError(f"cell_size_m must be finite and > 0, got {cell_size_m}")

    gaussians = _collect_gaussians(items)
    if not gaussians:
        return _empty_heatmap(cell_size_m)

    # One metric frame for the whole fusion, chosen from the mean of the component means.
    lon_c = float(np.mean([g["lon"] for g in gaussians]))
    lat_c = float(np.mean([g["lat"] for g in gaussians]))
    utm = utm_epsg_for(lon_c, lat_c)

    mus_x, mus_y = transform_points(
        np.asarray([g["lon"] for g in gaussians], dtype=np.float64),
        np.asarray([g["lat"] for g in gaussians], dtype=np.float64),
        "EPSG:4326",
        utm,
    )

    # Extent: every component's 4-sigma support, so nothing is clipped off the edge.
    pad = np.asarray([_SUPPORT_SIGMA * g["sigma_max"] for g in gaussians], dtype=np.float64)
    min_x = float(np.min(mus_x - pad))
    max_x = float(np.max(mus_x + pad))
    min_y = float(np.min(mus_y - pad))
    max_y = float(np.max(mus_y + pad))

    cols = max(1, int(math.ceil((max_x - min_x) / cell_size_m)))
    rows = max(1, int(math.ceil((max_y - min_y) / cell_size_m)))

    # Cell CENTRES, so a cell's reported position is where its mass actually is.
    xs = min_x + (np.arange(cols, dtype=np.float64) + 0.5) * cell_size_m
    ys = min_y + (np.arange(rows, dtype=np.float64) + 0.5) * cell_size_m
    grid_x, grid_y = np.meshgrid(xs, ys)

    density = np.zeros((rows, cols), dtype=np.float64)
    counts = np.zeros((rows, cols), dtype=np.int32)
    per_window: dict[str, np.ndarray] = {}

    for g, mu_x, mu_y in zip(gaussians, mus_x, mus_y, strict=True):
        contribution = _evaluate_gaussian(grid_x, grid_y, float(mu_x), float(mu_y), g)
        if contribution is None:
            continue
        weighted = g["weight"] * contribution
        density += weighted
        counts += (contribution > 0.0).astype(np.int32)
        wid = g["window_id"]
        if wid not in per_window:
            per_window[wid] = np.zeros((rows, cols), dtype=np.float64)
        per_window[wid] += weighted

    # ★ The background is spread UNIFORMLY over the AOI and the components are scaled by
    #   (1 - pi_bg) so the total is exactly 1 BEFORE rasterisation. Without the scaling the
    #   pre-normalisation mass is (pi_bg + 1) and the background's ACTUAL share collapses
    #   to pi_bg/(1 + pi_bg) — 44% where 78% was intended. A posterior that cannot express
    #   "the camera is in none of these" is not a posterior, and that is the whole reason
    #   the background term exists.
    pi_bg = _background_weight(items)
    area_aoi = cols * rows * cell_size_m * cell_size_m
    if area_aoi > 0.0 and pi_bg > 0.0:
        density = (1.0 - pi_bg) * density + pi_bg / area_aoi

    total = float(density.sum())
    if total <= 0.0:
        return _empty_heatmap(cell_size_m)
    probability = density / total
    entropy = _normalised_entropy(probability)

    peak = float(density.max())
    scores = density / peak if peak > 0.0 else density

    lons, lats = transform_points(grid_x.ravel(), grid_y.ravel(), utm, "EPSG:4326")
    lons = lons.reshape(rows, cols)
    lats = lats.reshape(rows, cols)

    cells = _emit_cells(scores, counts, lons, lats, per_window, peak)
    argmax_idx = int(np.argmax(density))
    r, c = divmod(argmax_idx, cols)

    west = float(np.min(lons))
    east = float(np.max(lons))
    south = float(np.min(lats))
    north = float(np.max(lats))

    return GeoHeatmap(
        bbox=BBox(west=west, south=south, east=east, north=north),
        cell_size_m=cell_size_m,
        grid_cols=cols,
        grid_rows=rows,
        cells=cells,
        argmax=LonLat(lon=float(lons[r, c]), lat=float(lats[r, c])),
        argmax_score=float(scores[r, c]),
        entropy_norm=entropy,
    )


def _collect_gaussians(
    items: Sequence[tuple[_PixelHeatmapLike, _WindowLike]],
) -> list[dict[str, Any]]:
    """Carry every component from its own window's pixel frame into lon/lat + metric covariance."""
    out: list[dict[str, Any]] = []
    for heatmap, window in items:
        gsd_m = float(window.gsd_m)
        if not math.isfinite(gsd_m) or gsd_m <= 0.0:
            raise ValueError(f"window gsd_m must be finite and > 0, got {gsd_m}")
        gt = window.geotransform
        crs = window.crs
        for comp in heatmap.components:
            weight = float(comp.weight)
            if not math.isfinite(weight) or weight <= 0.0:
                continue
            cov = np.asarray(comp.cov_px2, dtype=np.float64)
            if cov.shape != (2, 2) or not np.all(np.isfinite(cov)):
                raise ValueError(f"component cov_px2 must be a finite (2,2), got {cov.shape}")
            cov = (cov + cov.T) / 2.0

            # Window pixels -> true metres, with the y-flip into ENU. Same preferred path
            # as gis.accuracy: multiply by gsd_m**2, never by a geotransform coefficient
            # (which for a Web-Mercator window is inflated by 1/cos(phi)).
            flip = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.float64)
            cov_m = flip @ ((gsd_m**2) * cov) @ flip.T

            eigvals = np.linalg.eigvalsh(cov_m)
            sigma_max = math.sqrt(max(float(eigvals[1]), 0.0))
            if sigma_max <= 0.0:
                continue  # a zero-variance component is a point mass we cannot rasterise

            lon, lat = pixel_to_lonlat(gt, crs, float(comp.mu_px[0]), float(comp.mu_px[1]))
            out.append(
                {
                    "lon": lon,
                    "lat": lat,
                    "cov_m": cov_m,
                    "sigma_max": sigma_max,
                    "weight": weight,
                    "window_id": str(comp.window_id),
                }
            )
    return out


def _evaluate_gaussian(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    mu_x: float,
    mu_y: float,
    g: dict[str, Any],
) -> np.ndarray | None:
    """Evaluate one 2-D Gaussian over the grid, truncated at ``_SUPPORT_SIGMA``."""
    cov = g["cov_m"]
    det = float(np.linalg.det(cov))
    if det <= 0.0:
        return None
    inv = np.linalg.inv(cov)
    dx = grid_x - mu_x
    dy = grid_y - mu_y
    # Mahalanobis distance squared.
    m2 = inv[0, 0] * dx * dx + 2.0 * inv[0, 1] * dx * dy + inv[1, 1] * dy * dy
    density = np.exp(-0.5 * m2) / (2.0 * math.pi * math.sqrt(det))
    return np.where(m2 <= _SUPPORT_SIGMA**2, density, 0.0)


def _background_weight(items: Sequence[tuple[_PixelHeatmapLike, _WindowLike]]) -> float:
    """Return the "the camera is in none of these" mass, in ``[0, 1]``.

    Taken as the MINIMUM of the per-window background weights: the fused map is at most as
    uncertain as its most confident contributor, and taking a mean would let a pile of
    diffuse windows wash out one good fix.
    """
    weights = [
        float(h.background_weight)
        for h, _ in items
        if math.isfinite(float(h.background_weight))
    ]
    if not weights:
        return 0.0
    return max(0.0, min(1.0, min(weights)))


def _normalised_entropy(probability: np.ndarray) -> float:
    """Return ``H(p) / log(N)`` in ``[0, 1]``, the localisation-ambiguity summary."""
    n = probability.size
    if n <= 1:
        return 0.0
    nz = probability[probability > 0.0]
    if nz.size == 0:
        return 0.0
    entropy = float(-np.sum(nz * np.log(nz)))
    return max(0.0, min(1.0, entropy / math.log(n)))


def _emit_cells(
    scores: np.ndarray,
    counts: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    per_window: Mapping[str, np.ndarray],
    peak: float,
) -> tuple[GeoHeatmapCell, ...]:
    """Emit the sparse cell list, dropping negligible mass."""
    rows, cols = scores.shape
    cells: list[GeoHeatmapCell] = []
    for r in range(rows):
        for c in range(cols):
            score = float(scores[r, c])
            if score < _SPARSE_FLOOR:
                continue
            components = {
                wid: float(grid[r, c] / peak)
                for wid, grid in per_window.items()
                if peak > 0.0 and grid[r, c] > 0.0
            }
            cells.append(
                GeoHeatmapCell(
                    lon=float(lons[r, c]),
                    lat=float(lats[r, c]),
                    score=score,
                    sample_count=int(counts[r, c]),
                    components=components,
                )
            )
    return tuple(cells)


def _empty_heatmap(cell_size_m: float) -> GeoHeatmap:
    """An honest empty map: no cells, no argmax, maximal entropy.

    ``entropy_norm = 1.0`` because "we have nothing" and "we have not localised" are the
    same claim, and this is the value the ``> 0.6`` diffuseness flag must see.
    """
    return GeoHeatmap(
        bbox=BBox(west=0.0, south=0.0, east=0.0, north=0.0),
        cell_size_m=cell_size_m,
        grid_cols=0,
        grid_rows=0,
        cells=(),
        argmax=None,
        argmax_score=None,
        entropy_norm=1.0,
    )
