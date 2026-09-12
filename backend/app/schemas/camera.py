"""Cameras — wire types for ``/cameras/*`` (the server-side camera registry).

★ THE VALIDATOR IS THE FRONTEND'S, RESTATED. ``cameraRegistryStore.validateCamera``
refuses the same things: a blank name, an out-of-range pair, a serial line that
claims to carry video, a video camera with no source, a data integration with no
data source. The database CHECKs say it a third time. Three statements of one rule is
the price of a registry that survives a cleared browser; the frontend copy stays
because it answers BEFORE the round trip (and is the only one that can offer the
"swap lat/lon?" hint — by the time a pair reaches this model, the bounds have
already refused it).

★ ``desired`` IS INTENT, NOT STATUS. ``CameraDesired`` records what the operator asked
this camera to be doing; whether it IS doing it right now is the detection / drift /
feed status endpoints' answer. The boot reconciliation reads intent and produces
status; it never works the other way round.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .common import ApiModel, ListParams, PatchModel

__all__ = [
    "CAMERA_SORT_FIELDS",
    "DATA_ONLY_CONNECTIONS",
    "RETIRED_CONNECTIONS",
    "CameraCalibration",
    "CameraConnection",
    "CameraCreate",
    "CameraDesired",
    "CameraDesiredDetect",
    "CameraDesiredWatch",
    "CameraImportItem",
    "CameraImportRequest",
    "CameraImportResult",
    "CameraImported",
    "CameraListParams",
    "CameraProvides",
    "CameraRead",
    "CameraDriftRead",
    "CameraUpdate",
]

CAMERA_SORT_FIELDS = frozenset({"name", "created_at", "updated_at"})

#: ★ What the field plugs in (widened 2026-09-04): UTP/LAN, a stream URL, HDMI /
#: ★ Narrowed 2026-09-11 to the three things that differ: an address on the network
#: (an IP camera, a Pi, any stream URL), a capture device on this machine, a serial
#: line. See ``models.camera`` and migration 0023 for the fold.
CameraConnection = Literal["lan", "usb", "serial"]
#: The kinds that carry DATA and no picture.
DATA_ONLY_CONNECTIONS: frozenset[str] = frozenset({"serial"})

#: ★ WHAT THE RETIRED KINDS BECOME (2026-09-11). Migration 0023 folds the stored
#: rows, but an app that starts against a database one migration behind would
#: otherwise 500 on ``GET /cameras`` for EVERY camera because ONE row still says
#: 'bnc' — the 2026-09-08 scar, in a new place. The read applies the same fold the
#: SQL does, so an un-migrated row lists as the kind it will become.
#:
#: ★ AND THEY ARE ALIASES ON THE WAY IN, deliberately. The fold is lossless — the
#: old kinds asked for exactly what the new ones ask for — so a client that has
#: not reloaded yet (or a script written last week) may keep saying 'embedded'
#: and gets a camera that works, instead of a 422 in the middle of an upgrade.
#: A kind that was never real ('wifi') is still refused: aliasing what we retired
#: is kindness, inventing what we never had would be a guess.
RETIRED_CONNECTIONS: dict[str, str] = {
    "stream": "lan",
    "embedded": "lan",
    "hdmi": "usb",
    "bnc": "usb",
    "uart": "serial",
}
CameraProvides = Literal["camera", "data", "both"]

CameraName = Annotated[str, Field(min_length=1, max_length=120)]


def _looks_like_video_source(value: str) -> bool:
    v = value.strip().lower()
    return (
        v.startswith(("http://", "https://", "rtsp://", "/dev/", "device:"))
        or v.isdigit()
    )


def _looks_like_data_source(value: str) -> bool:
    """A sender this app can actually open — see ``live_data_service``'s transports.

    ★ ws(s):// and tcp:// joined http(s) and serial on 2026-09-11: a board on a
    mast usually PUSHES its detections rather than serving them.
    """
    v = value.strip().lower()
    return v.startswith(
        ("serial://", "/dev/tty", "http://", "https://", "ws://", "wss://", "tcp://")
    )


class CameraCalibration(ApiModel):
    """The optional calibration entered on the camera itself (2026-09-04).

    OpenCV pinhole intrinsics + Brown-Conrady distortion, the mast height above the
    DEM and the tilt below horizontal — the same vocabulary as ``ImageCameraPut``,
    minus the position (the registry's own ``lat``/``lon`` is the position). Every
    field is optional: a camera can be watched with none of this; the LOOKUP TABLE
    needs ``fx, fy, cx, cy``. Copied onto the frame's ``image_cameras`` row when a
    frame is chosen, so a re-capture inherits it.
    """

    fx: float | None = Field(default=None, gt=0)
    fy: float | None = Field(default=None, gt=0)
    cx: float | None = None
    cy: float | None = None
    k1: float | None = None
    k2: float | None = None
    p1: float | None = None
    p2: float | None = None
    k3: float | None = None
    #: Metres above the bare-earth DEM at the camera's position.
    mast_offset_m: float | None = None
    #: Degrees below horizontal, + = aimed down.
    tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)

    def is_empty(self) -> bool:
        """True when nothing was entered — stored as NULL, never as a blob of nulls."""
        return all(v is None for v in self.model_dump().values())


class _CameraFields(ApiModel):
    """The registry attributes, shared by create / import / read.

    ★ FIELDS ONLY. The cross-field rules live on :class:`_CameraWriteFields`, so a
    READ never refuses a row already in the database: on 2026-09-08 one stored
    camera whose source scheme had since been retired made ``GET /cameras`` 500
    for every camera. What the server stores, it must be able to list — the
    rules guard what comes IN.
    """

    name: CameraName
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    #: The video source: ``device:N``, ``/dev/videoN``, an http(s) MJPEG URL, or rtsp.
    source: str | None = Field(default=None, max_length=2000)
    connection: CameraConnection = "lan"

    @field_validator("connection", mode="before")
    @classmethod
    def _fold_retired_connection(cls, value: object) -> object:
        """A kind retired in 0023 becomes what it folded into — read AND write."""
        return RETIRED_CONNECTIONS.get(value, value) if isinstance(value, str) else value
    provides: CameraProvides = "camera"
    #: ``serial://<port>?baud=…``, a ``/dev/tty…`` path, or an http(s) line feed.
    data_source: str | None = Field(default=None, max_length=2000)
    heading_deg: float | None = Field(default=None, ge=0, le=360)
    fov_deg: float | None = Field(default=None, gt=0, le=180)
    fps: int | None = Field(default=None, ge=1, le=30)
    tags: list[str] = Field(default_factory=list)
    #: The LUT bundle last applied to this camera (a library site name).
    lut_site: str | None = Field(default=None, max_length=64)
    # ── the setup pipeline (2026-09-04) ──────────────────────────────────────
    #: The camera's backing project (its DEM, frame and control points live there).
    project_id: UUID | None = None
    #: The frame chosen from this camera — the photograph the control points sit on.
    frame_image_id: UUID | None = None
    #: Optional intrinsics / mast / tilt entered on the camera itself.
    calibration: CameraCalibration | None = None


class _CameraWriteFields(_CameraFields):
    """The fields PLUS the rules a camera must satisfy to be stored."""

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "_CameraWriteFields":
        if self.connection in DATA_ONLY_CONNECTIONS and self.provides != "data":
            raise ValueError(
                "a serial line carries no picture — it provides 'data'."
            )
        if self.calibration is not None and self.calibration.is_empty():
            self.calibration = None
        if self.provides != "data":
            if not self.source or not self.source.strip():
                raise ValueError("a camera that provides video needs a stream source.")
            if not _looks_like_video_source(self.source):
                raise ValueError(
                    "the source must be an http(s)/rtsp URL, a /dev/videoN path, "
                    "or a device id (device:N)."
                )
        if self.provides != "camera":
            if not self.data_source or not self.data_source.strip():
                raise ValueError("a data integration needs a data source.")
            if not _looks_like_data_source(self.data_source):
                raise ValueError(
                    "the data source must be serial://<port>?baud=…, a /dev/tty… path, "
                    "an http(s) URL, a ws(s):// websocket, or tcp://host:port."
                )
        return self


class CameraCreate(_CameraWriteFields):
    """``POST /cameras``."""


class CameraUpdate(PatchModel):
    """``PATCH /cameras/{id}`` — ★ UNSET semantics; the merged row is re-validated
    by the service with the rules of :class:`CameraCreate`."""

    name: CameraName | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    source: str | None = Field(default=None, max_length=2000)
    connection: CameraConnection | None = None
    provides: CameraProvides | None = None
    data_source: str | None = Field(default=None, max_length=2000)
    heading_deg: float | None = Field(default=None, ge=0, le=360)
    fov_deg: float | None = Field(default=None, gt=0, le=180)
    fps: int | None = Field(default=None, ge=1, le=30)
    tags: list[str] | None = None
    lut_site: str | None = Field(default=None, max_length=64)
    project_id: UUID | None = None
    frame_image_id: UUID | None = None
    calibration: CameraCalibration | None = None


class CameraDesiredWatch(ApiModel):
    """A drift watch this camera should be running."""

    ref_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    interval_s: float = Field(default=30.0, ge=2.0, le=3600.0)


class CameraDesiredDetect(ApiModel):
    """A detection session this camera should be running — the start request minus
    the source (the camera's own) — stored as sent."""

    lut_site: str | None = Field(default=None, max_length=64)
    conf: float = Field(default=0.25, ge=0.01, le=0.99)
    classes: list[int] | None = None
    imgsz: int = Field(default=640, ge=320, le=1920)
    tile: bool = False
    model: str | None = Field(default=None, max_length=128)
    tracker_start_frame: int = Field(default=0, ge=0, le=100_000)
    tracker_type: str = Field(default="csrt", max_length=16)
    tracker_refresh_every: int = Field(default=10, ge=0, le=10_000)
    centre_marks: bool = False


class CameraDesired(ApiModel):
    """What this camera SHOULD be doing — restored at boot (see the module header)."""

    watch: CameraDesiredWatch | None = None
    detect: CameraDesiredDetect | None = None
    feed: bool = False


class CameraRead(_CameraFields):
    """``CameraRead`` — every camera response."""

    id: UUID
    desired: CameraDesired
    created_at: datetime
    updated_at: datetime


class CameraDriftRead(ApiModel):
    """``POST /cameras/{id}/drift/freeze`` — the reference now frozen on the
    camera's frame, and the background watch on it (2026-09-08)."""

    ref_id: str
    interval_s: float
    n_landmarks: int
    frozen_from_label: str | None = None
    created_utc: str = ""
    intrinsics_mode: str = "calibration"
    intrinsics_warning: str | None = None
    watching: bool = True


class CameraListParams(ListParams):
    """``GET /cameras``."""

    q: str | None = Field(default=None, description="Free-text over name and source.")


class CameraImportItem(_CameraWriteFields):
    """One camera from a browser registry or a JSON export. ``client_id`` is the id
    the browser used (a ULID); the result maps it to the server's UUID so per-camera
    browser settings can be re-keyed."""

    client_id: str | None = Field(default=None, max_length=64)


class CameraImportRequest(ApiModel):
    """``POST /cameras/import`` — up to 500 cameras at once."""

    cameras: list[CameraImportItem] = Field(min_length=1, max_length=500)


class CameraImported(ApiModel):
    client_id: str | None
    id: UUID
    name: str


class CameraImportResult(ApiModel):
    created: int
    items: list[CameraImported]


def desired_from_row(value: Any) -> CameraDesired:
    """A row's ``desired`` JSONB → :class:`CameraDesired`, tolerating an old or
    partial dict (unknown keys are dropped rather than 500ing a listing)."""
    if not isinstance(value, dict):
        return CameraDesired()
    known = {k: v for k, v in value.items() if k in CameraDesired.model_fields}
    try:
        return CameraDesired.model_validate(known)
    except ValueError:
        return CameraDesired()
