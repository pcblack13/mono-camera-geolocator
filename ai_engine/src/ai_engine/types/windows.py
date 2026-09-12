"""★ THE PACKAGE SEAM.

This is how `gis` hands pixels to `ai_engine` without `ai_engine` learning what a
coordinate system is (L3). `gis.candidates.source.TileWindowSource` satisfies
`WindowSource` structurally; the composition root injects it; the engine iterates it and
never asks where the pixels came from.

A note on the wording in this file. The type that exists to be reference-system-agnostic
must not name a concrete authority code, and the CI gate that enforces L3 greps this
subtree for exactly such names. Both facts point the same way, so the fields below are
described by their ROLE and never by their content.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np

__all__ = ["CandidateWindow", "WindowRef", "WindowSource"]


@dataclass(frozen=True, slots=True)
class WindowRef:
    """Opaque handle. ai_engine treats `key` as a cache key and NEVER parses it."""

    key: str  # opaque provider-minted string. Structure is gis's business.
    provider: str  # provenance string only — never control flow


@dataclass(frozen=True, slots=True)
class CandidateWindow:
    """One searchable patch of satellite imagery, in PIXELS.

    ★ THE CONTRACT: `geotransform` and `crs` are an OPAQUE PAYLOAD. ai_engine carries
      them through to MatchJobResult and NEVER interprets them. Only gis may.
      This is what makes L3 mechanically true, and what makes swapping one provider for
      another unable to change the matching algorithm: the provider changes the pixels
      and six floats; ai_engine cannot tell the difference and does not care.
    """

    ref: WindowRef
    rgb: np.ndarray  # (H,W,3) uint8 RGB, C-contiguous
    geotransform: tuple[float, float, float, float, float, float]
    # ★ OPAQUE. GDAL order. CARRIED, NEVER READ.
    #   PROHIBITION (not a preference): no module under ai_engine/ may INDEX this tuple.
    #   Its linear coefficients are in the provider's projected units, which for some
    #   providers are NOT true ground metres — they are inflated by a factor that depends
    #   on where on the planet the window sits (74% at 55 deg N, which is serious
    #   agricultural country). Anything metric built from it is wrong by that factor,
    #   silently. `gsd_m` below is the ONLY sanctioned metric scale inside ai_engine.
    crs: str
    # ★ OPAQUE authority string minted by the provider. NEVER PARSED HERE.
    gsd_m: float
    # ★ TRUE GROUND METRES PER PIXEL at the window centre, corrected for where the window
    #   sits on the planet. PASSED IN by gis; never derived here (deriving it needs the
    #   window's ground position, which is exactly what ai_engine may not know).
    #   ★ "TRUE" IS LOAD-BEARING: PixelAccuracy consumers and the plane-pose frame both
    #     multiply pixels by this, and both are correct ONLY because it is corrected.
    georef_ce90_m: float
    # ★ the PROVIDER's own absolute georeferencing error, CE90 m. Frequently the DOMINANT
    #   error term and NOT reducible by anything ai_engine does. Carried into the
    #   accuracy estimate.
    attribution: str
    # ★ REQUIRED, and required for a legal reason rather than a cosmetic one. Pixels must
    #   not travel without their attribution — it is a licence condition. Making it a
    #   required field is what makes the obligation unforgeable at the one seam where
    #   pixels enter the matching engine.
    terms_url: str  # ★ same argument; surfaced in the UI and in PDF exports.
    captured_at: datetime | None = None
    # ★ Wired end to end: chip -> window -> match_results -> MatchResultRead -> CSV, where
    #   the normative column order requires it. This is the field
    #   ProviderCapabilities.imagery_date_known exists to answer.
    is_authoritative: bool = False  # True => survey-grade georeferencing (local orthophoto)
    placeholder_fraction: float = 0.0  # [0,1] fraction of blank/no-imagery source tiles -> H13
    bands: tuple[str, ...] = ("R", "G", "B")
    supports_multispectral: bool = False  # gates true water indices vs the HSV heuristic
    extra_bands: Mapping[str, np.ndarray] | None = None
    # ★ (H,W) float32 per band, keys matching bands[3:] (e.g. "NIR", "SWIR16").
    #   MUST be None when supports_multispectral is False; the water indices raise
    #   ValueError rather than silently substituting a green-band proxy.
    meta: Mapping[str, Any] = field(default_factory=dict)
    # ★ NORMATIVE KEYS, set by gis.candidates.source.TileWindowSource. ai_engine writes
    #   none of them and reads only `zoom_clamped`; the backend persists the rest.
    #     "tile_z" | "tile_x" | "tile_y"  : int — the window's ANCHOR tile (its NW-most
    #                                       source tile). Addressing metadata only; a
    #                                       1024px window at overlap 0.5 is NOT addressable
    #                                       by a single triple, and the transform is
    #                                       `geotransform`, never these.
    #     "mosaic_cols" | "mosaic_rows"   : int
    #     "zoom_clamped"                  : bool — the provider could not serve the
    #                                       requested zoom. Routed to a ZOOM_CLAMPED
    #                                       WarningItem + degraded=true.

    @property
    def size(self) -> tuple[int, int]:
        """(width, height) of `rgb`, in pixels."""
        return (int(self.rgb.shape[1]), int(self.rgb.shape[0]))


@runtime_checkable
class WindowSource(Protocol):
    """★ THE SEAM. `gis.candidates.source.TileWindowSource` satisfies this STRUCTURALLY
    (no inheritance). ai_engine declares the protocol it needs; gis implements it; the
    composition root injects it.

    SYNCHRONOUS by design: ai_engine runs inside Celery worker processes, and forcing an
    event loop into CPU-bound worker code buys nothing. Implementations may use asyncio
    and thread pools internally behind this sync facade.
    """

    name: str

    def __len__(self) -> int:
        """Total window count. Known up front — the search plan is computed before any
        fetching. This is what makes progress reporting honest.
        """
        ...

    def __iter__(self) -> Iterator[CandidateWindow]:
        """Yield windows lazily.

        ★ MAY raise `ai_engine.errors.WindowFetchError` for an INDIVIDUAL window; the
          orchestrator logs it, counts it, and continues to the next. It may raise no
          other non-programmer exception across this seam: an implementation MUST wrap
          its own transport errors in WindowFetchError, because `ai_engine.pipeline` MUST
          NOT import `gis` and therefore cannot name — let alone catch — a gis exception.
          Its only alternative would be `except Exception`, which is a defect.
        """
        ...
