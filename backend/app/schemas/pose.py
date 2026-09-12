"""Camera pose **and** the confidence heatmap (§6.2) — endpoints 48, 49.

★★ **DEFERRED** (SCOPE.md §4): *"Camera pose (yaw/pitch/roll) estimation"* and
*"Confidence heatmap over candidate camera locations"* are **ABCs only**. Both
endpoints are **registered and documented** and return ``501`` +
``feature: "deferred"``. The ``camera_poses``, ``confidence_heatmaps`` and
``confidence_heatmap_cells`` tables ARE created exactly as specified (rule 5) —
they simply hold no rows.

★ §6.2 puts the heatmap types in this module (``pose.py``) even though §2.4 gives
the heatmap its own router entry and §8.2 gives it its own TS module
(``heatmap.ts``). Following §6.2: the two share ``pose.py``'s router (endpoints
48 and 49 are both in ``pose.py``) and a heatmap is a posterior **over camera
locations**, which is the same subject.

★ **THE ANGLE CONVENTIONS**, and they are the classic silent-disagreement bug
between a CV module and a map renderer (§5.6): ``yaw_deg`` is **0 = TRUE North**,
clockwise, ``[0, 360)``; ``pitch_deg`` 0 = horizon, + = up, ``[-90, 90]``;
``roll_deg`` + = clockwise, ``[-180, 180]``.

★ ``ai_engine``'s ``PoseResult.yaw_deg`` is 0 = **up the window raster** — a
different quantity. For a north-up EPSG:3857 window they coincide; for a rotated
or UTM window they do **not**, and ``gis.pose.window_yaw_to_north_deg()`` — which
applies the geotransform rotation **and the grid convergence** — is the only
thing permitted to convert. What arrives here is already converted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from .common import ApiModel, BBox, GeoJsonPolygon, LatLon, PatchModel
from .enums import Colormap, HeatmapFormat, PoseMethod

__all__ = [
    "CameraIntrinsics",
    "CameraIntrinsicsInput",
    "CameraPoseRead",
    "CameraPoseUpdate",
    "HeatmapCandidate",
    "HeatmapCell",
    "HeatmapGrid",
    "HeatmapParams",
    "HeatmapRead",
    "HeatmapScoreRange",
    "HeatmapSparsity",
    "Orientation",
    "OrientationInput",
    "PoseAmbiguity",
    "PoseUncertainty",
]

#: A 3×3 matrix, row-major. ★ ROW-MAJOR EVERYWHERE — H, Σ_H, A_h, the DB, the
#: API (§4.24(1)). One convention, stated once, never re-decided.
Matrix3x3 = Annotated[list[float], Field(min_length=9, max_length=9)]


class CameraIntrinsics(ApiModel):
    """``K`` and its provenance.

    ★ ``source`` is not decoration: an ``assumed`` focal length and one read from
    EXIF produce poses of wildly different trustworthiness, and a reviewer must
    be able to tell which they are looking at.
    """

    k: Matrix3x3 = Field(description="9 floats, ROW-MAJOR.")
    fx: float
    fy: float
    cx: float
    cy: float
    source: Literal["exif", "fov", "vanishing_points", "assumed", "manual"]


class CameraIntrinsicsInput(ApiModel):
    """What a surveyor may assert about the camera."""

    fx: float | None = Field(default=None, gt=0.0)
    fy: float | None = Field(default=None, gt=0.0)
    cx: float | None = None
    cy: float | None = None
    hfov_deg: float | None = Field(default=None, gt=0.0, lt=180.0)


class Orientation(ApiModel):
    """★ 0 = TRUE North, clockwise. See the module docstring."""

    yaw_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    pitch_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    roll_deg: float | None = Field(default=None, ge=-180.0, le=180.0)


class OrientationInput(ApiModel):
    """A surveyor's asserted orientation."""

    yaw_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    pitch_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    roll_deg: float | None = Field(default=None, ge=-180.0, le=180.0)


class PoseUncertainty(ApiModel):
    """★ Honest error bars. ``null`` is honest; ``0`` would not be."""

    sigma_yaw_deg: float | None = Field(default=None, ge=0.0)
    sigma_pitch_deg: float | None = Field(default=None, ge=0.0)
    sigma_roll_deg: float | None = Field(default=None, ge=0.0)
    sigma_position_m: float | None = Field(default=None, ge=0.0)
    sigma_altitude_m: float | None = Field(default=None, ge=0.0)


class PoseAlternative(ApiModel):
    """One rejected decomposition, kept so a reviewer can see what was discarded."""

    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    score: float


class PoseAmbiguity(ApiModel):
    """★ ``decomposeHomographyMat`` returns up to four solutions. When the
    plane's metric frame is unknown they cannot be disambiguated, and reporting
    one as *the* answer would be a fabrication (L12).

    This is the type that says so on the wire rather than picking quietly.
    """

    is_ambiguous: bool
    solution_count: int = Field(ge=0)
    alternatives: list[PoseAlternative] = Field(default_factory=list)
    disambiguated_by: str | None = None


class CameraPoseRead(ApiModel):
    """``GET /images/{image_id}/camera-pose`` — endpoint 48.

    ★★ **DEFERRED** — the endpoint returns ``501``. No row carries this.
    """

    id: UUID
    image_id: UUID
    match_result_id: UUID | None = Field(
        default=None, description="Null for exif_gps_only / manual."
    )
    position: LatLon
    altitude_m: float | None
    orientation: Orientation
    hfov_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    vfov_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    footprint: GeoJsonPolygon | None = Field(
        default=None, description="Drives the Leaflet view cone."
    )
    method: PoseMethod
    confidence: float = Field(ge=0.0, le=100.0, description="★ 0-100.")
    rotation_matrix: Matrix3x3 | None = Field(
        default=None, description="9 floats, ROW-MAJOR, world->camera."
    )
    intrinsics: CameraIntrinsics | None = None
    reproj_error_px: float | None = Field(default=None, ge=0.0)
    inlier_count: int | None = Field(default=None, ge=0)
    uncertainty: PoseUncertainty
    ambiguity: PoseAmbiguity | None = None
    is_selected: bool
    created_at: datetime
    updated_at: datetime


class CameraPoseUpdate(PatchModel):
    """``PATCH /images/{image_id}/camera-pose``. ★ The surveyor overrides an
    estimate; ``method`` becomes ``manual``.

    ★ This is **not** deferred in the same way the *estimator* is: a human
    asserting where they stood needs no CV at all. It is listed under the
    deferred surface only because there is nothing to override yet — no pose row
    exists until an estimator writes one. IU-21 should register it with the same
    501 as endpoint 48 for consistency in this build, and flipping it on costs
    nothing (SCOPE.md §7).
    """

    position: LatLon | None = None
    altitude_m: float | None = None
    orientation: OrientationInput | None = None
    intrinsics: CameraIntrinsicsInput | None = None
    hfov_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    is_selected: bool | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Heatmap — endpoint 49 (§6.2 places these here)
# ─────────────────────────────────────────────────────────────────────────────


class HeatmapCell(ApiModel):
    """One evaluated cell.

    ★ **Only the CENTROID is stored** (§5.6). The cell polygon is
    ``centroid ± cell_size_m/2``, fully determined by the parent. Storing 10 000
    five-vertex polygons is ~5× the bytes and ~5× the GIST index **for zero
    information**.
    """

    col: int = Field(ge=0)
    row: int = Field(ge=0)
    center: LatLon = Field(description="★ The cell CENTROID, EPSG:4326.")
    score: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(
        ge=1,
        description=(
            "★ A cell AGGREGATES every candidate whose centre fell in it. A cell "
            "with sample_count=1 is far less trustworthy than one with 12, and "
            "the UI dims it accordingly."
        ),
    )
    components: dict[str, float] = Field(
        default_factory=dict, description="Per-term score breakdown for the hover tooltip."
    )


class HeatmapGrid(ApiModel):
    """The lattice the cells sit on."""

    cols: int = Field(ge=1)
    rows: int = Field(ge=1)
    cell_size_m: float = Field(
        gt=0.0, description="★ TRUE ground metres, never projected metres."
    )
    bbox: BBox


class HeatmapCandidate(ApiModel):
    """A named point on the posterior — the argmax, or a ranked candidate."""

    match_result_id: UUID | None = None
    center: LatLon
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)


class HeatmapScoreRange(ApiModel):
    """The posterior's spread. ``min <= mean <= max``."""

    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)
    mean: float = Field(ge=0.0, le=1.0)


class HeatmapSparsity(ApiModel):
    """★ Heatmap cells are **sparse and the payload says so**.

    **Absent ≠ score 0.** A cell with no candidate was never evaluated, which is
    a different claim from "we evaluated it and it scored zero". Rendering the
    first as the second would paint confident emptiness over unexplored ground —
    which is precisely the kind of confidently-wrong output L12 exists to
    prevent, in map form.
    """

    cell_count: int = Field(ge=0, description="Cells actually present.")
    total_cells: int = Field(ge=0, description="grid.cols * grid.rows.")
    note: str = Field(
        description="Human-readable statement that absent cells were not evaluated."
    )


class HeatmapRead(ApiModel):
    """``GET /images/{image_id}/heatmap`` — endpoint 49, ``format=json``.

    ★★ **DEFERRED** — the endpoint returns ``501``. No row carries this.
    """

    id: UUID
    match_job_id: UUID
    image_id: UUID
    grid: HeatmapGrid
    cells: list[HeatmapCell]
    sparsity: HeatmapSparsity
    score_range: HeatmapScoreRange
    argmax: HeatmapCandidate | None
    candidates: list[HeatmapCandidate] = Field(default_factory=list)
    colormap: Colormap
    render_url: str | None
    created_at: datetime


class HeatmapParams(ApiModel):
    """``GET /images/{image_id}/heatmap`` query — endpoint 49."""

    format: HeatmapFormat = HeatmapFormat.JSON
    colormap: Colormap = Colormap.VIRIDIS_R
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Drop cells below this score to cut payload. ★ Dropped cells stay "
            "ABSENT, not zero — and `sparsity` still tells the truth about what "
            "the absence means."
        ),
    )
    include_components: bool = False
