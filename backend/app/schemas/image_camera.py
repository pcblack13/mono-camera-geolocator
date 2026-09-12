"""The photograph's entered camera — intrinsics + position + tilt, from its setup page.

Two models only, because the surface is deliberately small:

* :class:`ImageCameraPut` — the ``PUT /images/{id}/camera`` body. **PUT, not
  PATCH**: the setup page always saves the whole form, so full-replace semantics are
  the truth of the interaction — an omitted field *is* a cleared field, and the
  UNSET machinery of :class:`~app.schemas.common.PatchModel` would be surface with
  no caller.
* :class:`ImageCameraRead` — the GET/PUT response. ``configured`` says whether a
  row exists at all; when it is ``False`` every data field is ``null`` and the
  timestamps too — an unconfigured camera has no ``created_at`` to report and none
  is invented.

★ **The position travels as ``lat`` + ``lon``** (EPSG:4326 decimal degrees, the
:class:`~app.schemas.common.LatLon` bounds), not GeoJSON — it is one point typed by
a human, and the field names disambiguate the order. The pair constraint (both or
neither) is enforced here so a lone longitude is a 422 naming the problem, not a
half-written station.

★ **``tilt_deg`` is degrees below horizontal, + = aimed down** — the field-tool
convention (``tilt_deg = -pitch_deg`` in ``camera_poses`` vocabulary). Bounded
[-90, 90], mirroring ``ck_image_cameras_tilt_range``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from .common import ApiModel

__all__ = [
    "AutoGcpEstimateRequest",
    "AutoGcpEstimateRead",
    "AutoGcpProjectRequest",
    "AutoGcpProjectRead",
    "ImageCameraPut",
    "ImageCameraRead",
]

#: Focal length in pixels. > 0 mirrors ``ck_image_cameras_focal_positive`` so a
#: violation is a clean 422 rather than a 23514 from Postgres.
FocalPx = Annotated[float, Field(gt=0)]

#: A calibration frame dimension in pixels.
FramePx = Annotated[int, Field(gt=0)]


class ImageCameraPut(ApiModel):
    """``PUT /images/{image_id}/camera`` — full replace, idempotent.

    ``{}`` is a legal body and means "clear everything but keep the station" —
    the honest encoding of a surveyor emptying the form. Use
    ``DELETE /images/{image_id}/camera`` to remove the station entirely.
    """

    # ── intrinsics — OpenCV pinhole + Brown–Conrady [k1, k2, p1, p2, k3] ─────
    fx: FocalPx | None = None
    fy: FocalPx | None = None
    cx: float | None = None
    cy: float | None = None
    k1: float | None = None
    k2: float | None = None
    p1: float | None = None
    p2: float | None = None
    k3: float | None = None
    img_w: FramePx | None = None
    img_h: FramePx | None = None
    # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
    #: Derive fx,fy,cx,cy from the field of view instead of a measured
    #: calibration. The flag is provenance — a derived K assumes a centred
    #: principal point and a perfect pinhole, and must never read as measured.
    no_calibration: bool = False
    #: A rough horizontal angle of view, degrees. Only a SEED: the build solves
    #: the focal from the GCPs, and the study behind this measured the same answer
    #: from a 60, 70 or 84 degree start.
    fov_h_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    #: None means square pixels (fy = fx); set only for a non-square sensor.
    fov_v_deg: float | None = Field(default=None, gt=0.0, lt=180.0)
    # <<< GEO-DRIFT-UPDATE C2 END <<<

    # ── position ─────────────────────────────────────────────────────────────
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    #: Metres above the bare-earth DEM at (lat, lon) — mast/tower height.
    mast_offset_m: float | None = None

    # ── orientation ──────────────────────────────────────────────────────────
    #: Degrees below horizontal, + = aimed down.
    tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)

    # ── auto GCP picking ─────────────────────────────────────────────────────
    #: ★ Intent only — the tool also needs FOUR located GCPs before it activates;
    #: that count is read live from the GCP list, never stored here.
    auto_gcp_enabled: bool = False

    @model_validator(mode="after")
    def _position_is_a_pair(self) -> Self:
        """A lone ``lat`` or ``lon`` is a 422, not half a point in the database."""
        if (self.lat is None) != (self.lon is None):
            raise ValueError(
                "lat and lon must be provided together (or both omitted)."
            )
        return self


class ImageCameraRead(ApiModel):
    """``GET``/``PUT`` response. ``configured=False`` ⇒ every other field is null."""

    image_id: UUID
    #: True iff a station row exists for this project.
    configured: bool

    fx: float | None
    fy: float | None
    cx: float | None
    cy: float | None
    k1: float | None
    k2: float | None
    p1: float | None
    p2: float | None
    k3: float | None
    img_w: int | None
    img_h: int | None
    # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
    no_calibration: bool = False
    fov_h_deg: float | None = None
    fov_v_deg: float | None = None
    # <<< GEO-DRIFT-UPDATE C2 END <<<

    lat: float | None
    lon: float | None
    mast_offset_m: float | None

    tilt_deg: float | None

    #: The surveyor turned auto GCP picking on for this photograph.
    auto_gcp_enabled: bool

    created_at: datetime | None
    updated_at: datetime | None


class AutoGcpEstimateRequest(ApiModel):
    """``POST /images/{image_id}/camera/estimate`` — geolocate one photo pixel.

    Solves the camera pose from this photo's ≥4 located GCPs (plus its entered
    intrinsics and position), then intersects the pixel's ray with the project DEM.
    """

    #: Full-resolution image pixels, y-down — the same space ``gcps.pixel_x/y`` uses.
    u: float = Field(ge=0)
    v: float = Field(ge=0)
    #: Metres above the terrain the TARGET sits (a rooftop, a vehicle). 0 = ground.
    height_offset_m: float = Field(default=0.0, ge=-100, le=1000)


class AutoGcpEstimateRead(ApiModel):
    """The estimate — an INFERENCE, labelled with the diagnostics that qualify it.

    ★ Every number here derives from the solve; none is a stored fact. ``distance_m``
    is horizontal range from the solved camera. The tilt/position diagnostics compare
    the solve against what the surveyor ENTERED at setup — large gaps mean a mistyped
    station or badly placed GCPs, and the client is expected to show them.
    """

    lat: float
    lon: float
    elevation_m: float
    distance_m: float

    gcps_used: int
    reproj_mean_px: float
    reproj_max_px: float
    azimuth_deg: float
    tilt_solved_deg: float
    tilt_entered_deg: float | None
    position_shift_m: float
    warnings: list[str]


class AutoGcpProjectRequest(ApiModel):
    """``POST /images/{image_id}/camera/project`` — the estimate run BACKWARDS.

    Given a world coordinate, solve the same pose and return the full-resolution
    pixel where that spot appears in the photograph. Used to keep the photo mark in
    lock-step when the surveyor drags a GCP's MAP endpoint in Auto mode.
    """

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    #: Metres above the terrain the TARGET sits (a rooftop, a vehicle). 0 = ground.
    height_offset_m: float = Field(default=0.0, ge=-100, le=1000)


class AutoGcpProjectRead(ApiModel):
    """The projected pixel — an INFERENCE through the same solved pose.

    ★ ``inside_image`` is judged against the entered calibration frame
    (``img_w``/``img_h``) when one was supplied; ``None`` means no frame size is on
    record and the client must judge against the rendered image itself. A point
    BEHIND the camera never reaches this model — that is a 422 naming the problem.
    """

    #: Full-resolution image pixels, y-down — the same space ``gcps.pixel_x/y`` uses.
    u: float
    v: float
    inside_image: bool | None
    gcps_used: int
    warnings: list[str]
