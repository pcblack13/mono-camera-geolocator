"""``TileWindowSource`` — ★ THE SEAM (CONTRACT.md §4.19, §4.10, §10.3).

This module is the ONLY place in the codebase where a provider, a tile pyramid and the
matching engine are in the same room. Everything above it sees windows; everything below it
sees tiles. It is also the only place ``gis`` imports from ``ai_engine`` — the one permitted
cross-package import, and it points ``gis -> ai_engine``, which is the direction the layer
stack already points.

★ THE IMPORT IS PERMITTED BECAUSE OF WHAT IT IS NOT. ``ai_engine.types`` imports numpy and
stdlib and nothing else; it cannot drag in cv2 or torch. ``WindowSource`` is a structural
``typing.Protocol``, so ``TileWindowSource`` satisfies it WITHOUT INHERITING FROM IT — the
import exists purely so a type checker can verify conformance. ``ai_engine.errors`` is here
for exactly one name, ``WindowFetchError``, which §4.10 requires an implementation to raise
and which must live on the side that declares the Protocol: ``ai_engine.pipeline`` may not
import ``gis``, so it cannot name — let alone catch — a ``gis`` exception, and its only
alternative would be ``except Exception``.

★ WHY THE SEAM IS SHAPED LIKE THIS. Automatic matching is deferred in this build (see
docs/architecture/SCOPE.md): the surveyor marks the landmark and clicks the map, and the
coordinate is a direct observation rather than an inference. This module is NOT deferred. It
is real, working code, because the manual map view and the tile proxy need windows today —
and because it is the seam that makes turning the engine back on a zero-caller-change
operation. If re-enabling the engine required editing anything here, this file would be
wrong.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator, Sequence
from typing import Any, Final

import numpy as np

from ai_engine.errors import WindowFetchError  # ★ the seam's exception type — §10.3
from ai_engine.types import CandidateWindow, WindowRef  # ★ THE ONE PERMITTED CROSS-IMPORT
from gis.candidates.strategy import (
    GUARANTEED_FOOTPRINT_PX,
    WindowPlan,
    guaranteed_footprint_px,
    plan_search,
)
from gis.errors import AreaTooLargeError, ProviderError, TileNotAvailableError
from gis.imagery.base import ImageryProvider
from gis.tiles import choose_zoom
from gis.types import BasemapKind, BBox, SatelliteChip

__all__ = ["GUARANTEED_FOOTPRINT_PX", "TileWindowSource"]

_log: Final = logging.getLogger(__name__)

_DEFAULT_WINDOW_SIZE_PX: Final[int] = 1024
"""``LE_SEARCH_WINDOW_SIZE_PX``."""

_DEFAULT_OVERLAP_RATIO: Final[float] = 0.5
"""``LE_SEARCH_OVERLAP_RATIO``. ★ 0.5, NOT 0.25 — it is what buys ``GUARANTEED_FOOTPRINT_PX``."""

_DEFAULT_MAX_WINDOWS: Final[int] = 25
"""``LE_SEARCH_MAX_CANDIDATES``. Read ``gis.candidates.budget`` before changing it: 25
windows and the 512-tile job budget are two views of the same number."""

_DEFAULT_TARGET_GSD_M: Final[float] = 0.5
"""``LE_SEARCH_TARGET_GSD_M``. TRUE ground metres per pixel."""

_MATCHING_KIND: Final[BasemapKind] = BasemapKind.SATELLITE
"""★ NORMATIVE, and not a parameter. Matching always uses plain satellite imagery. Labels
and hillshade are for human eyes; feeding a label-burned tile to the engine would be a
genuine accuracy regression, and making the basemap switcher able to change the algorithm
would break the invariant that a provider swap changes DATA, not BEHAVIOUR."""


# ★ THE GUARANTEE, ASSERTED AT IMPORT, AGAINST THE VALUES WE ACTUALLY SHIP.
#   `raise`, not `assert`: `python -O` strips assertions, and this is exactly the kind of
#   silent, location-dependent defect that must not be able to reach production because
#   someone optimised the bytecode.
_DEFAULT_GUARANTEE_PX: Final[int] = guaranteed_footprint_px(
    _DEFAULT_WINDOW_SIZE_PX, _DEFAULT_OVERLAP_RATIO
)
if _DEFAULT_GUARANTEE_PX < GUARANTEED_FOOTPRINT_PX:  # pragma: no cover - import-time gate
    raise AssertionError(
        f"the shipped defaults (window {_DEFAULT_WINDOW_SIZE_PX} px, overlap "
        f"{_DEFAULT_OVERLAP_RATIO}) guarantee only a {_DEFAULT_GUARANTEE_PX} px footprint, "
        f"below the {GUARANTEED_FOOTPRINT_PX} px the design reasons from. Either the "
        f"defaults or the constant moved; they are not allowed to move apart."
    )


class TileWindowSource:
    """★ THE SEAM. Turns an area of interest into candidate windows of imagery.

    Structurally satisfies ``ai_engine.types.WindowSource`` — ``name``, ``__len__``,
    ``__iter__`` — WITHOUT inheriting from it. The engine iterates this and cannot tell it
    apart from ``SyntheticWindowSource``; that indistinguishability is the seam working.

    SYNCHRONOUS by design. The engine runs inside worker processes, and forcing an event
    loop into CPU-bound worker code buys nothing. Concurrency lives one layer down, inside
    the provider's tile fetching, behind this sync facade.

    Typical use — note that the plan, and therefore the cost, exists before any I/O::

        source = TileWindowSource(provider, aoi, zoom_levels=(18,))
        check_tile_budget(source.plans, provider=provider.name)   # refuse it here, or
        for window in source:                                     # pay for it here
            ...

    Attributes:
        name: The source's name, for provenance. Stable for a given provider.
        plans: The search plan. Public and read-only: the caller budgets against it
            (``gis.candidates.budget.check_tile_budget``) rather than re-planning, and a
            second ``plan_search`` with the same arguments would only be a chance to
            disagree with this one.
    """

    name: str

    def __init__(
        self,
        provider: ImageryProvider,
        aoi: BBox,
        *,
        zoom_levels: Sequence[int],
        window_size_px: int = _DEFAULT_WINDOW_SIZE_PX,
        overlap_ratio: float = _DEFAULT_OVERLAP_RATIO,
        max_windows: int = _DEFAULT_MAX_WINDOWS,
        target_gsd_m: float = _DEFAULT_TARGET_GSD_M,
    ) -> None:
        """Plan the search. ★ NO I/O HAPPENS HERE, and none may.

        Args:
            provider: The imagery source. Already resolved — this class never consults the
                registry, so ``LE_IMAGERY_STRICT``, the fallback chain and the offline
                allow-list are all settled before it sees anything (§11.4).
            aoi: The search area, EPSG:4326, from ``gis.candidates.hint.resolve_hint``.
            zoom_levels: The zoom levels to search, CLAMPED into what this provider serves
                and reported via ``CandidateWindow.meta["zoom_clamped"]``. ★ Empty means
                "choose one for ``target_gsd_m``": this class knows the provider, so it can
                turn a resolution into a zoom; ``plan_search`` cannot and refuses to guess.
            window_size_px: Window edge in pixels. ``LE_SEARCH_WINDOW_SIZE_PX``.
            overlap_ratio: Fraction shared with the neighbouring window. ★ 0.5 buys the
                512 px footprint guarantee; see ``GUARANTEED_FOOTPRINT_PX``.
            max_windows: Upper bound on the plan. ``LE_SEARCH_MAX_CANDIDATES``.
            target_gsd_m: Desired TRUE ground metres per pixel. ``LE_SEARCH_TARGET_GSD_M``.
                Used only when ``zoom_levels`` is empty.

        Raises:
            AreaTooLargeError: A single window is larger than this provider will serve in
                one request. ★ Refused HERE, at construction, rather than per-window during
                iteration: every window would fail identically, the engine would log 25
                fetch failures and return ``no_viable_candidate``, and a configuration
                error would present as "we looked and found nothing" — the one answer this
                system may never give by accident.
            ValueError: Any of the geometry arguments is invalid; see ``plan_search``.
        """
        caps = provider.capabilities()
        tile_size_px = caps.tile_size_px

        if caps.max_static_px is not None:
            max_w, max_h = caps.max_static_px
            if window_size_px > max_w or window_size_px > max_h:
                raise AreaTooLargeError(
                    f"a {window_size_px}x{window_size_px} px window exceeds what "
                    f"{provider.name} serves in one request ({max_w}x{max_h} px); lower "
                    f"LE_SEARCH_WINDOW_SIZE_PX",
                    provider=provider.name,
                )

        _, centre_lat = aoi.center()
        levels = tuple(int(z) for z in zoom_levels)
        if not levels:
            decision = choose_zoom(
                provider.min_zoom, provider.max_zoom, target_gsd_m, centre_lat, tile_size_px
            )
            levels = (decision.zoom,)
            _log.info(
                "no zoom levels requested; %.2f m/px at lat %.4f resolves to z%d (%.3f m/px)",
                target_gsd_m,
                centre_lat,
                decision.zoom,
                decision.achieved_mpp,
            )

        self._provider = provider
        self._caps = caps
        self._aoi = aoi
        self._window_size_px = window_size_px
        self.name = f"tiles:{provider.name}"
        self._plans: tuple[WindowPlan, ...] = tuple(
            plan_search(
                aoi,
                zoom_levels=levels,
                min_zoom=provider.min_zoom,
                max_zoom=provider.max_zoom,
                window_size_px=window_size_px,
                tile_size_px=tile_size_px,
                overlap_ratio=overlap_ratio,
                max_windows=max_windows,
            )
        )

    @property
    def plans(self) -> tuple[WindowPlan, ...]:
        """The planned windows, in iteration order. Known before any fetch."""
        return self._plans

    @property
    def provider_name(self) -> str:
        """The name of the provider these windows come from."""
        return self._provider.name

    def __len__(self) -> int:
        """The number of windows PLANNED — known up front, which is what makes progress honest.

        ★ An UPPER BOUND on the number yielded, and deliberately so. A window the provider
        has no imagery for is skipped (see ``__iter__``), and there is no way to know that
        without fetching it — so the alternative to an upper bound is not a better number,
        it is planning by network call. The engine reports "window i of N" against the plan
        and counts what it actually received; both figures are true.
        """
        return len(self._plans)

    def __iter__(self) -> Iterator[CandidateWindow]:
        """Fetch, stitch, crop and yield windows lazily, most probable first.

        ★ ERROR CONTRACT ACROSS THE SEAM (§4.10). Every ``gis.errors.ProviderError`` is
        wrapped in ``ai_engine.errors.WindowFetchError`` before it crosses, because the
        engine cannot import ``gis`` and therefore cannot catch what it cannot name. The
        engine logs it, counts it, and continues to the next window.

        ★ ``TileNotAvailableError`` IS NOT AN ERROR HERE. It is the provider's honest
        "there is no imagery at this location" — ocean, a coverage gap, a cloud — so the
        window is SKIPPED rather than raised. Windows that are only PARTLY missing are not
        skipped: the provider fills the holes and reports the fraction, which rides through
        on ``placeholder_fraction`` for the engine to gate on. Filling is not lying as long
        as the fill is declared, and this is where it gets declared.

        Yields:
            Windows with C-contiguous (H, W, 3) uint8 RGB pixels, their opaque transform,
            their TRUE ground scale, and their attribution.

        Raises:
            WindowFetchError: A provider failure on one window — a rate limit, a transport
                failure, a chip that violates the pixel contract.
        """
        for plan in self._plans:
            key = self._window_key(plan)
            try:
                chip = self._provider.get_static_bbox(plan.bbox, plan.zoom, kind=_MATCHING_KIND)
            except TileNotAvailableError:
                _log.info(
                    "%s has no imagery for window %d/%d (%s at z%d); skipping",
                    self._provider.name,
                    plan.ordinal + 1,
                    len(self._plans),
                    plan.bbox,
                    plan.zoom,
                )
                continue
            except ProviderError as exc:
                # ★ Wrapped, never re-raised bare, and never swallowed. `raise ... from exc`
                #   keeps the original traceback for our logs while the engine sees only a
                #   type it is allowed to know about.
                raise WindowFetchError(key, type(exc).__name__, str(exc)) from exc
            yield self._to_window(plan, chip, key)

    def _window_key(self, plan: WindowPlan) -> str:
        """Mint the opaque handle for a planned window.

        ★ A PURE FUNCTION OF THE WINDOW'S GEOMETRY — provider, basemap kind, zoom, extent —
        and of nothing else. The engine treats this as a cache key and never parses it, so
        the one property it must have is that the same key means the same pixels. That is
        why ``ordinal`` is not in it: the ordinal depends on the whole plan, so two jobs
        over overlapping areas would key identical imagery differently, and a truncated plan
        would re-key everything it kept.

        Nine decimal places is ~0.1 mm of longitude; adjacent windows are half a window
        apart (~216 m at z18). There is no collision to be had.
        """
        b = plan.bbox
        return (
            f"{self._provider.name}/{_MATCHING_KIND.value}/z{plan.zoom}/"
            f"{b.west:.9f},{b.south:.9f},{b.east:.9f},{b.north:.9f}"
        )

    def _to_window(self, plan: WindowPlan, chip: SatelliteChip, key: str) -> CandidateWindow:
        """Convert one provider chip into one candidate window.

        ★ THIS IS WHERE PIXELS ENTER THE MATCHING ENGINE, and it is the last place any of
        these invariants can be enforced — past here, nothing is allowed to know enough to
        check them.
        """
        self._validate_chip(chip, key)

        # ★ The window supports multispectral analysis IFF IT ACTUALLY CARRIES THE BANDS.
        #   The capability describes the PROVIDER; this flag describes THESE PIXELS, and a
        #   window claiming the capability while carrying no extra bands is a guaranteed
        #   ValueError inside the engine's water indices — which read `extra_bands` and
        #   refuse to substitute a green-band proxy, correctly. The type's own rule ("MUST
        #   be None when supports_multispectral is False") is one-directional and would not
        #   have caught this; the conjunction does.
        extra_bands = chip.extra_bands
        multispectral = bool(self._caps.supports_multispectral and extra_bands)

        return CandidateWindow(
            ref=WindowRef(
                key=key,
                # ★ What ACTUALLY served the pixels, not what we asked for. Attribution and
                #   provenance must describe the imagery in hand; a provider that fell back
                #   says so here, and a downstream report cannot misattribute (§11.4).
                provider=chip.provider_name or self._provider.name,
            ),
            # A no-op for every provider that honours the ABC; free insurance for the one
            # that returns a view or a transposed array. The type demands C-contiguity and
            # the engine's cv2 calls demand it harder.
            rgb=np.ascontiguousarray(chip.image),
            # ★ OPAQUE PAYLOAD, carried and never interpreted by anything downstream of
            #   here. Only gis may read these two, and gis does it elsewhere.
            geotransform=chip.geotransform,
            crs=chip.crs,
            # ★ TRUE ground metres per pixel, cos(phi)-corrected by the provider. NOT
            #   geotransform[1], which for a Web Mercator provider is inflated by 1/cos(phi)
            #   — 74% at 55 deg N, which is serious agricultural country. This field is the
            #   only sanctioned metric scale inside the engine, which is exactly why it is
            #   passed rather than derived: deriving it needs the window's position on the
            #   planet, which is what the engine may not know.
            gsd_m=chip.gsd_m,
            georef_ce90_m=chip.georef_ce90_m,
            attribution=chip.attribution,
            terms_url=chip.terms_url,
            captured_at=chip.captured_at,
            is_authoritative=chip.is_authoritative,
            placeholder_fraction=chip.placeholder_fraction,
            bands=chip.bands,
            supports_multispectral=multispectral,
            extra_bands=extra_bands if multispectral else None,
            meta=self._window_meta(plan),
        )

    def _window_meta(self, plan: WindowPlan) -> dict[str, Any]:
        """Build the window's normative metadata (§4.10).

        ``tile_z``/``tile_x``/``tile_y`` name the window's ANCHOR TILE — its north-west-most
        source tile. ★ Addressing metadata ONLY. A 1024 px window at overlap 0.5 is not
        addressable by a single tile triple, and the window's transform is its
        ``geotransform``, never these three. They are None for a provider with no tile
        pyramid, which is why the columns they land in are nullable (§5.6).
        """
        rng = plan.tile_range
        tiled = self._caps.supports_tiles
        return {
            "tile_z": plan.zoom if tiled else None,
            "tile_x": rng.min_x if tiled else None,
            "tile_y": rng.min_y if tiled else None,
            "mosaic_cols": rng.cols if tiled else None,
            "mosaic_rows": rng.rows if tiled else None,
            # ★ The one key the engine reads. It is how a job learns it is matching against
            #   upsampled mush, and it is routed on to a ZOOM_CLAMPED warning, degraded =
            #   true, and a quality flag (§11.8). ZoomDecision.clamped exists for this and
            #   for nothing else; in v1.0 nothing routed it anywhere.
            "zoom_clamped": plan.zoom_decision.clamped,
        }

    def _validate_chip(self, chip: SatelliteChip, key: str) -> None:
        """Enforce the pixel and licence contract at the seam.

        Everything here is a provider defect, not a user error, and every one of them would
        otherwise fail silently or far away: bad pixels crash inside the engine with a
        stack trace naming the wrong package; a bad scale produces a plausible coordinate
        that is wrong by a constant factor; missing attribution is a licence breach that no
        test downstream can detect, because by then the credit is simply not there to check.

        Raises:
            WindowFetchError: The chip violates the contract. Raised rather than repaired:
                a fabricated scale or an invented credit is worse than a skipped window.
        """
        image = chip.image
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise WindowFetchError(
                key,
                "ValueError",
                f"{self._provider.name} returned {image.shape!r} {image.dtype} pixels; "
                f"the window contract is (H, W, 3) uint8 RGB",
            )
        if image.shape[0] < 1 or image.shape[1] < 1:
            raise WindowFetchError(
                key, "ValueError", f"{self._provider.name} returned an empty {image.shape!r} chip"
            )
        if not math.isfinite(chip.gsd_m) or chip.gsd_m <= 0.0:
            raise WindowFetchError(
                key,
                "ValueError",
                f"{self._provider.name} returned gsd_m={chip.gsd_m!r}; it is the only "
                f"metric scale the engine has and it must be a positive number of TRUE "
                f"ground metres per pixel",
            )
        if not math.isfinite(chip.georef_ce90_m) or chip.georef_ce90_m < 0.0:
            raise WindowFetchError(
                key,
                "ValueError",
                f"{self._provider.name} returned georef_ce90_m={chip.georef_ce90_m!r}; it "
                f"is frequently the dominant term in the reported accuracy and must be a "
                f"non-negative number of metres",
            )
        if self._caps.requires_attribution and not chip.attribution.strip():
            raise WindowFetchError(
                key,
                "ValueError",
                f"{self._provider.name} requires attribution and returned none; pixels may "
                f"not travel without their credit — it is a licence condition, and making "
                f"the field required is what makes the obligation unforgeable",
            )

    def __repr__(self) -> str:
        zooms = sorted({plan.zoom for plan in self._plans})
        return (
            f"TileWindowSource(provider={self._provider.name!r}, windows={len(self._plans)}, "
            f"zoom={zooms}, window_size_px={self._window_size_px}, aoi={self._aoi})"
        )
