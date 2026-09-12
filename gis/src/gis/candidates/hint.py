"""``SearchHint`` + ``resolve_hint()`` — where a search area comes from (CONTRACT.md §4.19).

★ A HINT IS A HARD INPUT REQUIREMENT, NOT AN OPTIMISATION.

A hintless global search is not slow, it is **arithmetically impossible**. At z18 the world
is ``2**18`` tiles on a side — ``6.87e10`` tiles, roughly a petabyte of imagery **per
photograph** — and the question is genuinely ambiguous anyway: a hectare of wheat looks like
every other hectare of wheat on the planet. There is no amount of compute that turns an
unhinted photograph into a coordinate we would let a surveyor dig against.

So this module never guesses. When no hint resolves it raises ``SearchHintRequired``, which
the API maps to ``422 SEARCH_HINT_REQUIRED``. That is designed into the UX as a blocking
wizard step, not discovered at runtime, and ``LE_SEARCH_REQUIRE_PRIOR`` was deleted (§12
C-37) precisely because a toggle implying global search is possible would be a lie.

★ THE HONEST CASE IS THE WHOLE POINT OF THIS MODULE. Everything else here is five lines of
precedence.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Final

from gis.errors import SearchHintRequired
from gis.exif import inflate_radius_m
from gis.geometry import disc_to_bbox
from gis.types import BBox, LonLat

__all__ = ["SearchHint", "resolve_hint"]

_log: Final = logging.getLogger(__name__)

_MAX_ZOOM_LEVEL: Final[int] = 24
"""Upper bound on a requested zoom level, matching ``gis.tiles``' own clamp domain."""


@dataclass(frozen=True, slots=True)
class SearchHint:
    """What the caller knows about where a photograph was taken.

    ★ A hint is a HARD INPUT REQUIREMENT, not an optimisation. See the module docstring
    for the arithmetic; see ``resolve_hint`` for the precedence.

    Attributes:
        aoi: An explicit area of interest. Wins over everything, and ``radius_m`` is then
            ignored — the caller drew a polygon; they meant it.
        center: A point to search around, used with ``radius_m``.
        radius_m: Search radius in TRUE ground metres. Applies to ``center`` and to an
            EXIF fix; never to ``aoi`` or a georeferenced footprint.
        zoom_levels: The zoom levels to search. ``gis.candidates.strategy.plan_search``
            CLAMPS these into what the provider serves and reports having done so; it
            never silently drops one.
        use_image_gps: Whether the image's own claims (EXIF GPS, a georeferenced
            footprint) may be used. False means "the operator says the file is lying" —
            which happens: a photo exported through desktop software can carry the
            *processing* location.

    Raises:
        ValueError: If ``radius_m`` is not finite and positive, if ``zoom_levels`` is
            empty, or if any zoom level is outside ``[0, 24]``. ★ An empty
            ``zoom_levels`` is refused rather than defaulted: a search at no zoom level
            finds nothing, and "found nothing" is indistinguishable from a genuine
            no-match by the time it reaches a user.
    """

    aoi: BBox | None = None
    center: LonLat | None = None
    radius_m: float = 1000.0
    zoom_levels: tuple[int, ...] = (18,)
    use_image_gps: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.radius_m) or self.radius_m <= 0.0:
            raise ValueError(f"radius_m must be finite and > 0, got {self.radius_m}")
        if not self.zoom_levels:
            raise ValueError("zoom_levels must not be empty; a search at no zoom is not a search")
        for z in self.zoom_levels:
            if not (0 <= z <= _MAX_ZOOM_LEVEL):
                raise ValueError(f"zoom level {z} outside [0, {_MAX_ZOOM_LEVEL}]")


def resolve_hint(
    hint: SearchHint,
    *,
    exif_gps: LonLat | None,
    geotiff_bounds: BBox | None,
    project_aoi: BBox | None,
    exif_hpe_m: float | None = None,
) -> BBox:
    """Resolve every available hint into one search area.

    ★ NORMATIVE PRECEDENCE — the first that yields a geometry wins:

    1. ``hint.aoi`` — an explicit box. ``radius_m`` is ignored.
    2. ``hint.center`` + ``radius_m`` — a geodesic buffer.
    3. ``use_image_gps`` and ``exif_gps`` — a buffer by ``radius_m``, inflated per the
       EXIF horizontal positioning error.
    4. ``use_image_gps`` and ``geotiff_bounds`` — the footprint. ``radius_m`` is ignored:
       a georeferenced raster states its own extent and padding it would only add
       territory the file already told us is not in the picture.
    5. ``project_aoi``.
    6. Otherwise → ``SearchHintRequired``.

    ★ On the EXIF/GeoTIFF order (3 before 4). A georeferenced footprint is far more
    precise than a consumer GNSS fix, so this order looks inverted. It is the contract's,
    and it is right: a georeferenced upload short-circuits the whole search — it yields
    exact coordinates with no matching at all — so in practice a file that reaches here
    with a footprint AND an EXIF fix is one whose georeferencing the operator has already
    declined to trust. The EXIF fix is then the better evidence about the *camera*, which
    is what a search area is about.

    ★ On the inflation (step 3). ``exif_hpe_m`` is the fix's own claimed horizontal error.
    ``gis.exif.inflate_radius_m`` turns that claim into a radius we can actually trust —
    it multiplies (a receiver's estimate is optimistic exactly where this product is used)
    and it applies a floor (the claimed error can simply be wrong). The result is a SEARCH
    RADIUS, so it composes with the requested radius by ``max``, not by addition: both
    quantities answer "how far out must we look", and the answer is the larger of them.
    Adding a floor meant as a minimum radius onto another radius would be a category error
    that quietly grows every box by 250 m.

    The EXIF fix can therefore only ever INFLATE the search area, never shrink it. A box
    that confidently excludes the right answer is the worst failure available here: the
    search returns a plausible match from the neighbouring field and the surveyor believes
    it.

    Args:
        hint: What the caller asked for.
        exif_gps: The position the photograph's EXIF claims, or None. Extract it with
            ``gis.exif.extract_exif_gps``.
        geotiff_bounds: The upload's own georeferenced footprint, or None. Detect it with
            ``gis.raster.detect_georeferencing``.
        project_aoi: The project's default area of interest, or None.
        exif_hpe_m: The EXIF fix's claimed horizontal error in metres, or None. Get it
            from ``ExifGps.estimated_error_m()``. Ignored unless ``exif_gps`` is the
            winning hint; a non-finite or negative value is treated as absent.

    Returns:
        The search area, EPSG:4326.

    Raises:
        SearchHintRequired: Nothing resolved. ★ NOT a fallback to a global search, and
            not an empty box either — both would be a lie with a different failure mode.
        ValueError: If a winning geodesic buffer could not be built (see
            ``gis.geometry.disc_to_bbox``).
    """
    if hint.aoi is not None:
        _log.debug("search area from an explicit aoi: %s", hint.aoi)
        return hint.aoi

    if hint.center is not None:
        aoi = disc_to_bbox(hint.center, hint.radius_m)
        _log.debug(
            "search area from center %s + %.0f m -> %s", hint.center, hint.radius_m, aoi
        )
        return aoi

    if hint.use_image_gps and exif_gps is not None:
        radius_m = hint.radius_m
        if exif_hpe_m is not None and math.isfinite(exif_hpe_m) and exif_hpe_m >= 0.0:
            trusted_m = inflate_radius_m(exif_hpe_m)
            if trusted_m > radius_m:
                _log.info(
                    "EXIF claims %.1f m of horizontal error; inflating the search radius "
                    "from %.0f m to %.0f m",
                    exif_hpe_m,
                    radius_m,
                    trusted_m,
                )
                radius_m = trusted_m
        aoi = disc_to_bbox(exif_gps, radius_m)
        _log.debug("search area from EXIF GPS %s + %.0f m -> %s", exif_gps, radius_m, aoi)
        return aoi

    if hint.use_image_gps and geotiff_bounds is not None:
        _log.debug("search area from the upload's own footprint: %s", geotiff_bounds)
        return geotiff_bounds

    if project_aoi is not None:
        _log.debug("search area from the project aoi: %s", project_aoi)
        return project_aoi

    raise SearchHintRequired(
        "no search area could be resolved: the request carried no aoi and no centre, the "
        "image has no usable GPS and no georeferencing, and the project has no default "
        "aoi. A hint is a hard input requirement — an unhinted search is ~6.9e10 tiles at "
        "z18 and ambiguous even then. Draw an area, drop a pin, or upload a photograph "
        "with GPS."
    )
