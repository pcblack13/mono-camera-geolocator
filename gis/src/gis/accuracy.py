"""Where pixels become metres — THE SINGLE PRODUCER of ``AccuracyEstimate`` (§4.20).

★ The module that must never see a degree or a Web-Mercator metre.

``ai_engine`` reports uncertainty in WINDOW PIXELS and stops there. This is where that
becomes a claim about the world — a number a surveyor may dig, build or file against.
There is exactly one producer of the survey numbers so that there is exactly one thing to
get right.

Confidence level
----------------
★ **CE90 AND ONLY CE90**, throughout, on every field. ``georef_ce90_m`` arrives at CE90
from the provider, so everything else meets it there; that makes ``total_ce90_m`` a
legitimate quadrature of two same-level quantities rather than a mix of a 2-sigma ellipse
semi-major with a 2-D circular radius (a number at no stated confidence level at all).
``AccuracyEstimate.confidence_level`` ships on the type so the value can never be read at
the wrong level.

The output frame
----------------
★ Every covariance this module RETURNS is in **local ENU metres: X east, Y north**.

Window pixels are ``x`` right, ``y`` **down** (south). The default path therefore applies
the y-flip ``F = diag(1, -1)`` as ``Sigma_enu = F Sigma F.T``. This is the same
prohibition §4.24(4) makes for the pose frame, for the same reason: handing a REFLECTED
basis to an eigendecomposition yields a plausible wrong azimuth — the ellipse would be
mirrored about the east-west axis, so a NE-trending error would be reported as SE-trending.
The flip negates the off-diagonal terms and leaves the eigenvalues untouched, so it can
never disturb the magnitude goldens — only the bearing, which is precisely what it fixes.

Manual mode (SCOPE.md §5)
-------------------------
In this build a GCP is a **direct observation**, not an inference: there is no homography
and no match score. Its accuracy comes from the imagery's ground sample distance and the
surveyor's click precision at the map's zoom level — a real, defensible number.
``manual_gcp_accuracy`` is that path and it is first-class. ``confidence`` remains
surveyor-declared and is never computed here or anywhere else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np

from gis.types import GeoTransform

__all__ = [
    "CE90_FROM_SIGMA_2D",
    "CE95_FROM_SIGMA_2D",
    "DEFAULT_CLICK_SIGMA_PX",
    "LANDMARK_PIXEL_TOLERANCE_PX",
    "AccuracyEstimate",
    "combine_accuracy",
    "manual_gcp_accuracy",
    "pixel_cov_to_metres",
    "rmse_px_to_ce90_m",
]


CE90_FROM_SIGMA_2D: Final[float] = 2.1460
"""2-D circular 90% radius, in units of sigma. ★ THE confidence level of this product."""

CE95_FROM_SIGMA_2D: Final[float] = 2.4477
"""2-D circular 95% radius, in units of sigma. Not used; recorded so nobody re-derives 2.0.

For the record, since this is where the mistake gets made: 2-sigma on the semi-major of a
2-D error ellipse is ~86.5%, NOT the ~95% it is routinely labelled.
"""

LANDMARK_PIXEL_TOLERANCE_PX: Final[float] = 1.0
"""★ THE LANDMARK PIXEL-ACCURACY CEILING — the largest per-point PIXEL error the product
accepts before it flags a control point as pixel-inaccurate (``top = 1 px``).

This is a *ceiling*, not the typical figure: a landmark placed on a clean, high-contrast
feature (the synthetic checkerboard/pattern the accuracy path is validated against) round-trips
through the pixel geometry with an error **well under 0.5 px** — half this ceiling. The exact
GeoTIFF path's mark quantisation (``_GEOTIFF_MARK_SIGMA_PX = 0.5``) is deliberately at that
half-pixel mark, comfortably inside the ceiling. Any GCP whose measured reprojection residual
(``gcps.residual_px``, non-null only on a direct/automatic fix) exceeds this value has a pixel
error the product will not silently vouch for.
"""

DEFAULT_CLICK_SIGMA_PX: Final[float] = 1.0
"""Landmark pointing precision, 1-sigma, in pixels. Matches ``Landmark.sigma_px``'s default.

★ Set to **1 px**, in line with the product's landmark pixel-accuracy stance
(``LANDMARK_PIXEL_TOLERANCE_PX``): a landmark is pointed to within a pixel. This is the
relative (pointing) error term of a manual GCP — ``relative_ce90_m = 2.146 · this · gsd_m`` —
so a tighter pointing precision reports a tighter relative accuracy. On typical satellite
imagery the provider's georeferencing (``georef_ce90_m``, several metres) still DOMINATES the
headline ``total_ce90_m``; the pointing term only becomes the limit on survey-grade orthophotos,
where a 1 px point is exactly the claim being made.
"""

DominantTerm = Literal["match", "georeference", "landmark_click", "rectification"]


@dataclass(frozen=True, slots=True)
class AccuracyEstimate:
    """The survey numbers for one GCP. ★ EVERY FIELD CARRIES CE90; no level mixing.

    Attributes:
        semi_major_ce90_m: Error-ellipse semi-major axis, CE90 metres.
        semi_minor_ce90_m: Error-ellipse semi-minor axis, CE90 metres.
        azimuth_deg: Major-axis bearing, 0 = TRUE North, clockwise, in ``[0, 180)``.
            ★ The anisotropy is KEPT. An oblique solve's error is strongly directional and
            collapsing it to one number throws away the most actionable part of the estimate.
        relative_ce90_m: Our own fit/click error, circularised: ``2.146 * sqrt(lambda_max)``.
        georef_ce90_m: The imagery provider's own absolute georeferencing error, CE90.
            Frequently the DOMINANT term and not reducible by anything we do.
        total_ce90_m: ``sqrt(relative_ce90_m**2 + georef_ce90_m**2)``.
        dominant_term: Which term the total is actually made of — what the UI surfaces so
            a user knows whether a better click or better imagery is the way forward.
        confidence_level: Always ``"ce90"``. Present so the numbers cannot be misread.
    """

    semi_major_ce90_m: float
    semi_minor_ce90_m: float
    azimuth_deg: float
    relative_ce90_m: float
    georef_ce90_m: float
    total_ce90_m: float
    dominant_term: DominantTerm
    confidence_level: Literal["ce90"] = "ce90"


def _validate_cov(cov_px: np.ndarray) -> np.ndarray:
    """Coerce and check a 2x2 covariance. Returns a symmetrised float64 copy."""
    cov = np.asarray(cov_px, dtype=np.float64)
    if cov.shape != (2, 2):
        raise ValueError(f"cov_px must be (2,2), got {cov.shape}")
    if not np.all(np.isfinite(cov)):
        raise ValueError("cov_px contains non-finite values")
    # Symmetrise: a covariance that is asymmetric by 1e-17 of rounding is not an error,
    # but eigh would silently read only one triangle. Do it explicitly.
    return (cov + cov.T) / 2.0


def pixel_cov_to_metres(
    cov_px: np.ndarray,
    gsd_m: float,
    *,
    gt: GeoTransform | None = None,
    lat: float | None = None,
) -> np.ndarray:
    """Convert a window-pixel covariance to a TRUE-metre covariance in local ENU.

    ★ PREFERRED AND DEFAULT PATH — no round trip, no sign to get backwards::

        Sigma_true = gsd_m**2 * cov_px          (then y-flipped into ENU)

    ★ The geotransform path (``gt`` and ``lat`` both given, for rotated/skewed rasters)
    states the OPERATION, not merely the factor::

        Sigma_proj = J_gt @ cov_px @ J_gt.T             # units: PROJECTED metres/px
        Sigma_true = cos(radians(lat))**2 * Sigma_proj  # ★ for a Web-Mercator gt ONLY

    **MULTIPLY BY cos^2.** The projected metre is INFLATED by ``1/cos(phi)``, so the
    correction DIVIDES BY that factor. Naming the factor without naming the operation is
    how this gets applied backwards: doing so inflates linear error by ``1/cos^2(phi)``
    (3.04x at 55N) and variance by ``1/cos^4`` (9.2x). Both directions are plausible on
    inspection — a true +/-0.3 m becomes +/-0.91 m (over-conservative, hides the product's
    real accuracy) or the reverse (over-confident, the dangerous one). Hence the preferred
    path above, which works from a true-metre resolution and has no factor to reverse.

    Args:
        cov_px: (2,2) covariance in WINDOW pixels (x right, y down).
        gsd_m: ★ TRUE ground metres per pixel, cos(phi)-corrected. NOT a geotransform
            coefficient and NOT a Web-Mercator metre.
        gt: Optional geotransform, for the rotated/skewed path. Requires ``lat``.
        lat: Latitude in degrees, for the ``cos^2`` correction on the ``gt`` path.

    Returns:
        (2,2) float64 covariance in TRUE metres, local ENU (X east, Y north).

    Raises:
        ValueError: If ``cov_px`` is not a finite (2,2); if ``gsd_m`` is not positive on
            the default path; if exactly one of ``gt``/``lat`` is supplied; or if ``gt``
            is singular.
    """
    cov = _validate_cov(cov_px)

    # y-flip: window v grows SOUTH, ENU Y grows NORTH.
    flip = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.float64)

    if (gt is None) != (lat is None):
        raise ValueError(
            "the geotransform path needs BOTH gt and lat: lat drives the cos^2 correction "
            "and without it the result would be in projected, not ground, metres"
        )

    if gt is None:
        if not math.isfinite(gsd_m) or gsd_m <= 0.0:
            raise ValueError(f"gsd_m must be finite and > 0, got {gsd_m}")
        sigma_px_frame = (gsd_m**2) * cov
        return flip @ sigma_px_frame @ flip.T

    assert lat is not None  # narrowed by the paired check above
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat={lat} outside [-90, 90]")
    j_gt = np.array([[gt[1], gt[2]], [gt[4], gt[5]]], dtype=np.float64)
    if not np.all(np.isfinite(j_gt)) or abs(float(np.linalg.det(j_gt))) < 1e-30:
        raise ValueError(f"geotransform is singular or non-finite: {gt}")
    sigma_proj = j_gt @ cov @ j_gt.T
    cos_phi = math.cos(math.radians(lat))
    sigma_true = (cos_phi**2) * sigma_proj
    # J_gt already maps into the projected frame (X east, Y north) — a north-up gt has a
    # NEGATIVE pixel_height, so the y-flip is baked into the Jacobian. No extra flip here.
    return sigma_true


def _ellipse(sigma_m: np.ndarray) -> tuple[float, float, float]:
    """Return ``(sqrt(lambda_max), sqrt(lambda_min), azimuth_deg)`` for an ENU covariance.

    ``azimuth_deg`` is the major axis's bearing: 0 = North, clockwise, folded into
    ``[0, 180)`` because an ellipse axis is undirected.
    """
    # eigh: sigma is symmetric by construction, eigenvalues ascending, orthonormal vectors.
    eigvals, eigvecs = np.linalg.eigh(sigma_m)
    # Numerical noise can push a near-zero eigenvalue slightly negative.
    lam_min = max(0.0, float(eigvals[0]))
    lam_max = max(0.0, float(eigvals[1]))
    major = eigvecs[:, 1]
    east, north = float(major[0]), float(major[1])
    azimuth = math.degrees(math.atan2(east, north)) % 180.0
    return (math.sqrt(lam_max), math.sqrt(lam_min), azimuth)


def combine_accuracy(
    cov_px: np.ndarray,
    gsd_m: float,
    georef_ce90_m: float,
    click_sigma_px: float,
    *,
    gt: GeoTransform | None = None,
    lat: float | None = None,
) -> AccuracyEstimate:
    """★ THE ONLY producer of ``AccuracyEstimate``. ``ai_engine`` does not compute metres.

    The two pixel-space inputs are **disjoint** and are not double-counted:

    * ``cov_px`` is the uncertainty the fit carries into the window frame — the
      homography, rectification and mosaic terms. In manual mode it is **zero**: there is
      no fit, so there is no fit error.
    * ``click_sigma_px`` is the WINDOW-side pointing error — the surveyor's click on the
      satellite map, or the propagated query-side landmark click. It enters as
      ``click_sigma_px**2 * I2``.

    So ``Sigma_win = cov_px + click_sigma_px**2 * I2``, converted to true metres by
    ``pixel_cov_to_metres``, then reported at CE90 with its ellipse intact.

    Args:
        cov_px: (2,2) covariance in WINDOW pixels. Pass zeros when there is no fit.
        gsd_m: TRUE ground metres per pixel, cos(phi)-corrected.
        georef_ce90_m: The provider's absolute georeferencing error, CE90 metres, ``>= 0``.
        click_sigma_px: Window-frame click precision, 1-sigma pixels, ``>= 0``.
        gt: Optional geotransform for the rotated/skewed path. Requires ``lat``.
        lat: Latitude in degrees, required with ``gt``.

    Returns:
        The ``AccuracyEstimate``, every field at CE90.

    Raises:
        ValueError: On a malformed covariance, a non-positive ``gsd_m``, a negative
            ``georef_ce90_m`` or ``click_sigma_px``, or an unpaired ``gt``/``lat``.
    """
    if not math.isfinite(georef_ce90_m) or georef_ce90_m < 0.0:
        raise ValueError(f"georef_ce90_m must be finite and >= 0, got {georef_ce90_m}")
    if not math.isfinite(click_sigma_px) or click_sigma_px < 0.0:
        raise ValueError(f"click_sigma_px must be finite and >= 0, got {click_sigma_px}")

    cov_fit = _validate_cov(cov_px)
    sigma_win = cov_fit + (click_sigma_px**2) * np.eye(2, dtype=np.float64)
    sigma_ground = pixel_cov_to_metres(sigma_win, gsd_m, gt=gt, lat=lat)

    s_major, s_minor, azimuth = _ellipse(sigma_ground)
    semi_major = CE90_FROM_SIGMA_2D * s_major
    semi_minor = CE90_FROM_SIGMA_2D * s_minor
    relative = semi_major  # circularised: the ellipse's worst direction
    total = math.hypot(relative, georef_ce90_m)

    return AccuracyEstimate(
        semi_major_ce90_m=semi_major,
        semi_minor_ce90_m=semi_minor,
        azimuth_deg=azimuth,
        relative_ce90_m=relative,
        georef_ce90_m=georef_ce90_m,
        total_ce90_m=total,
        dominant_term=_dominant_term(cov_fit, click_sigma_px, relative, georef_ce90_m),
    )


def _dominant_term(
    cov_fit: np.ndarray,
    click_sigma_px: float,
    relative_ce90_m: float,
    georef_ce90_m: float,
) -> DominantTerm:
    """Name the term that actually drives ``total_ce90_m``.

    Compared in variance (the quantity that adds), not in metres, so the answer reflects
    the real contribution rather than the square root of it.
    """
    if georef_ce90_m**2 >= relative_ce90_m**2:
        return "georeference"
    click_var = click_sigma_px**2
    fit_var = float(np.max(np.linalg.eigvalsh(cov_fit))) if np.any(cov_fit) else 0.0
    return "landmark_click" if click_var >= fit_var else "match"


def manual_gcp_accuracy(
    gsd_m: float,
    georef_ce90_m: float,
    *,
    click_sigma_px: float = DEFAULT_CLICK_SIGMA_PX,
) -> AccuracyEstimate:
    """Accuracy of a MANUALLY placed GCP (SCOPE.md §5) — the first-class path in this build.

    A manual GCP is a **direct observation**: the surveyor identified a landmark and
    clicked the same physical spot on the satellite map. There is no homography, so there
    is no fit covariance and no estimated confidence to calibrate. The positional error is
    exactly two things — how precisely a human can place a click at the map's zoom level,
    and how well the provider's imagery is georeferenced::

        Sigma_win  = click_sigma_px**2 * I2        (isotropic: a click has no preferred axis)
        Sigma_true = gsd_m**2 * Sigma_win
        relative_ce90_m = 2.146 * click_sigma_px * gsd_m
        total_ce90_m    = hypot(relative_ce90_m, georef_ce90_m)

    The estimate is isotropic and its ``azimuth_deg`` is therefore not meaningful; it is
    reported as 0.0 and ``semi_major == semi_minor`` says so honestly.

    ★ This does NOT set ``confidence``. Manual-mode confidence is a deliberate
    surveyor-declared judgement and is never computed — not here, not anywhere.

    Args:
        gsd_m: TRUE ground metres per pixel of the imagery the surveyor clicked on, at the
            zoom level they clicked at. Get it from ``gis.tiles.resolution_at(z, lat,
            tile_size)`` or ``SatelliteChip.gsd_m``. ★ Never a Web-Mercator metre.
        georef_ce90_m: The provider's absolute georeferencing error, CE90 metres.
        click_sigma_px: Click precision, 1-sigma pixels. Defaults to
            ``DEFAULT_CLICK_SIGMA_PX``.

    Returns:
        The ``AccuracyEstimate``, at CE90, with ``dominant_term`` naming whichever of the
        click and the imagery's own georeferencing actually dominates.

    Raises:
        ValueError: On a non-positive ``gsd_m`` or a negative input.
    """
    return combine_accuracy(
        np.zeros((2, 2), dtype=np.float64),
        gsd_m,
        georef_ce90_m,
        click_sigma_px,
    )


def rmse_px_to_ce90_m(rmse_px: float, gsd_m: float) -> float:
    """Convert a pixel RMSE to a CE90 radius in true ground metres.

    ``= CE90_FROM_SIGMA_2D * rmse_px * gsd_m``

    Args:
        rmse_px: RMSE in window pixels, ``>= 0``.
        gsd_m: TRUE ground metres per pixel, cos(phi)-corrected.

    Returns:
        The CE90 radius in true metres.

    Raises:
        ValueError: If ``rmse_px`` is negative or ``gsd_m`` is not positive.
    """
    if not math.isfinite(rmse_px) or rmse_px < 0.0:
        raise ValueError(f"rmse_px must be finite and >= 0, got {rmse_px}")
    if not math.isfinite(gsd_m) or gsd_m <= 0.0:
        raise ValueError(f"gsd_m must be finite and > 0, got {gsd_m}")
    return CE90_FROM_SIGMA_2D * rmse_px * gsd_m
