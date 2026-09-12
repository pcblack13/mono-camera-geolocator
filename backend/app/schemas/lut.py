"""LUT builds — wire types for ``/lut/*``.

★ A LUT is FROZEN GEOMETRY: for one photograph of one fixed camera, the latitude/
longitude every pixel looks at, precomputed against the project's DEM so a field
unit resolves pixels with a single array read. The build inherits the pose solved
from the photograph's committed GCPs — its accuracy IS the pose's accuracy, and
the validation report says so rather than implying more.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .common import ApiModel

__all__ = ["LutBuildRequest", "LutBuildStatus", "LutLibraryEntry", "LutLookupRead"]


class LutBuildRequest(ApiModel):
    """``POST /lut/builds`` — build a pixel→lat/lon table for one photograph."""

    image_id: UUID
    #: Output folder becomes ``<site_name>_lut``. Defaults to the photograph's
    #: filename stem; sanitised to ``[A-Za-z0-9_-]`` either way.
    site_name: str | None = Field(default=None, max_length=64)
    #: Height of the target surface above bare earth; one bundle answers for one surface.
    target_height_m: float = Field(default=0.0, ge=-100.0, le=1000.0)
    #: float64 = exact (~146 MB full-res); float32 = half size, ~0.4 m quantisation.
    coord_dtype: Literal["float64", "float32"] = "float64"
    #: Random pixels re-computed one ray at a time and compared against the batch.
    validation_samples: int = Field(default=2000, ge=100, le=20000)


class LutBuildStatus(ApiModel):
    """One build, from queue to bundle. Progress is pixels ray-cast."""

    build_id: str
    image_id: UUID
    project_id: UUID
    site_name: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_done: int
    progress_total: int
    started_at: datetime
    #: The failure, verbatim — actionable text, not a code to decode.
    error: str | None
    #: `validator.py`'s report (max error vs the scalar reference, coverage, `passed`).
    report: dict[str, Any] | None
    #: Where the bundle folder landed (server-side path, for the operator).
    bundle_dir: str | None
    #: True once the ``.zip`` exists — gates the download button.
    archive_available: bool
    #: ★ Set when the build stood on an ADOPTED correction from the accuracy check
    #: rather than on the pose this photograph's GCPs alone imply. Null is the normal
    #: case. A LUT whose geometry came from somewhere other than its own control points
    #: must say so — here, and in ``adopted_correction.json`` inside the bundle.
    adopted: dict[str, Any] | None = None


class LutIntrinsicsInfo(ApiModel):
    """How a bundle got its intrinsics when built WITHOUT a calibration (2026-09-09):
    the seed the focal search started from (typed, or the default when the field
    of view was left blank) and the angle it SOLVED to from the control points."""

    mode: str = "fov"
    fov_h_seed_deg: float | None = None
    seed_defaulted: bool = False
    focal_solved: bool = False
    fov_h_solved_deg: float | None = None
    fx_solved: float | None = None


class LutLibraryEntry(ApiModel):
    """One bundle ON DISK — the durable record, read from its own manifest.

    ★ Disk is the library: builds outlive API restarts as folders, and a bundle
    copied in by hand is as real as one built here.
    """

    site_name: str
    built_utc: str | None = None
    #: ``{"width": ..., "height": ...}`` of the photograph the LUT answers for.
    image: dict[str, Any] = Field(default_factory=dict)
    payload_mb: float | None = None
    validation_passed: bool | None = None
    max_error_m: float | None = None
    #: ``(lat, lon)`` the bundle looks from — the map opens here before a run.
    #: None when the manifest predates the pose record or lacks the DEM's CRS.
    center: tuple[float, float] | None = None
    bundle_dir: str
    archive_available: bool
    #: ★ True when the manifest carries ``pose.R/C/K`` + the image size + ``dem.epsg``
    #: — everything the DRIFT monitor re-solves geometry from. Detection needs only the
    #: arrays, so a bundle imported payload-only is False here and perfectly usable for
    #: placement; the drift page uses this to say so BEFORE the surveyor presses Freeze.
    has_pose: bool = False
    #: GEO-DRIFT-UPDATE C1 — everything but the intrinsics is there; freezable
    #: once a field of view is supplied ('no calibration' mode).
    pose_needs_fov: bool = False
    #: ★ Present when the focal was SOLVED from the control points (no-calibration
    #: build): the seed, whether it was the default, and the solved angle.
    intrinsics: LutIntrinsicsInfo | None = None
    #: The photograph the pose was solved on (GEO-DRIFT D1 record), when known.
    source_image_id: str | None = None
    #: ★ Set when the bundle was IMPORTED rather than built here — when, from what, and
    #: whether its manifest travelled with it or had to be synthesised. A LUT the app
    #: cannot vouch for must say where it came from.
    imported: dict[str, Any] | None = None


class LutLookupRead(ApiModel):
    """``GET /lut/library/{site}/lookup`` — one pixel of a live picture, on the ground.

    ★ THE LIVE PREDICT READOUT (2026-09-10, owner ask). The monitoring page lets
    the operator point at any pixel of the stream and see where it lands, the
    way the GCP editor's live predict does on a photograph — but through the
    camera's LOOKUP TABLE, the same table every detection is placed through, so
    the cursor and the marks can never disagree. ``elevation_m`` is sampled from
    the camera project's own DEM when a ``project_id`` is given; it is null, not
    zero, when no DEM answers.
    """

    site_name: str
    #: The pixel as asked, in the MEDIA's own space.
    u: float
    v: float
    #: The same pixel in the table's space (a 1280×720 stream on a 4032×2268 table).
    lut_u: float
    lut_v: float
    placed: bool
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    elevation_source: str | None = None
    #: Why it was not placed: ``off_table`` (outside the picture) or ``no_terrain``
    #: (sky, or ground the DEM does not cover). Null when placed.
    reason: str | None = None
