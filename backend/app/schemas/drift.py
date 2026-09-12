"""Wire types for ``/drift/*`` — camera drift references and verdicts.

★ THE FOUR STATES ARE THE VENDOR'S, VERBATIM (OK / MOVED / CHANGED / DEGRADED).
Collapsing any of them is how a monitor lies: MOVED and CHANGED both mean "stop
trusting the coordinates" but their remedies differ (re-aim vs full re-solve),
and DEGRADED is "cannot judge", which is NOT an alert. The UI renders them
apart; the wire keeps them apart.

★ ``state`` vs ``status``: ``state`` is this frame's raw reading; ``status`` is
the temporally confirmed verdict (``confirm_n`` consecutive identical non-OK
readings). Alert on ``status``, log ``state`` — the vendored README's own rule.
"""

from __future__ import annotations

from typing import Literal, TypeVar
from uuid import UUID


from pydantic import Field

from app.schemas.common import ApiModel

DriftState = Literal["OK", "MOVED", "CHANGED", "DEGRADED"]

_M = TypeVar("_M", bound=ApiModel)


def fit(model: type[_M], data: dict) -> _M:
    """Build a wire model from OUR OWN stored/derived dict, keeping only the
    fields the wire declares.

    ★ ``extra="forbid"`` guards CLIENT typos — but the drift records on disk and
    the vendored monitor's verdict dicts legitimately carry more than the wire
    says (``patch_px``, ``claimed_px``, ``outlier_ids``, …), and forbid turned
    every listing into a 500 the moment a record held one such key (field
    report 2026-08-24). Our own data is filtered, never forbidden.
    """
    return model(**{k: v for k, v in data.items() if k in model.model_fields})


class DriftFreezeRequest(ApiModel):
    """Freeze the trusted state — call only while the mapping is known good."""

    name: str = Field(default="", max_length=120)
    #: A live device/URL (``/dev/video0``, ``rtsp://…``) or ``video:<id>`` from
    #: the video library — the same source grammar detection uses.
    source: str = Field(min_length=1)
    #: The LUT bundle the mapping lives in; its manifest supplies the pose.
    lut_site: str = Field(min_length=1)
    #: Fire above this much ground error, in metres, at ``ref_range_m``.
    alert_ground_m: float = Field(default=1.0, gt=0, le=100)
    #: Range the threshold is stated at; None = the frozen landmarks' median range.
    ref_range_m: float | None = Field(default=None, gt=0)
    #: Consecutive identical non-OK verdicts before ``status`` changes.
    confirm_n: int = Field(default=3, ge=1, le=10)
    n_landmarks: int = Field(default=24, ge=6, le=64)
    #: `video:` sources only — freeze from this clip second (e.g. the moment the
    #: LUT was solved at). Live sources ignore it.
    at_s: float | None = Field(default=None, ge=0)
    # >>> GEO-DRIFT-UPDATE D1 BEGIN — freeze from the photograph the GCPs are on >>>
    #: Freeze the reference from THIS library photograph instead of grabbing a
    #: fresh frame. It is the picture the GCPs were placed on and the LUT was
    #: solved from, so the frozen pose and the frozen pixels describe the same
    #: instant — a later grab may already have drifted, and the reference would
    #: then bake that drift in as "trusted".
    #:
    #: ``source`` still names what LATER CHECKS read (the live camera). Its frames
    #: must match this photograph's size, or every check is refused.
    freeze_from_image_id: UUID | None = None
    #: When no id is given, fall back to the photograph the LOOKUP TABLE records
    #: as its own — picking the table the surveyor trusted already says which
    #: frame the reference belongs on. Turn this off to force a fresh grab.
    use_lut_image: bool = True
    # <<< GEO-DRIFT-UPDATE D1 END <<<
    # >>> GEO-DRIFT-UPDATE C1 BEGIN — intrinsics without a calibration >>>
    #: Derive fx,fy,cx,cy from the field of view instead of the LUT's calibration
    #: — the geolocation GUI's own model. Needs ``fov_h_deg``.
    no_calibration: bool = False
    #: The camera's TRUE horizontal angle of view, in degrees. Not a spec sheet's
    #: diagonal figure (always larger), and not EXIF's rounded 35 mm focal.
    fov_h_deg: float | None = Field(default=None, gt=0, lt=180)
    #: Only when ``square_pixels`` is off; otherwise it is derived from fov_h.
    fov_v_deg: float | None = Field(default=None, gt=0, lt=180)
    #: Keep this on unless the sensor is known to have non-square pixels — a
    #: wrong aspect ratio is the one error a focal solve cannot repair.
    square_pixels: bool = True
    # <<< GEO-DRIFT-UPDATE C1 END <<<


class DriftReferenceRead(ApiModel):
    ref_id: str
    name: str
    source: str
    source_label: str
    lut_site: str
    created_utc: str
    frame_width: int
    frame_height: int
    n_landmarks: int
    alert_ground_m: float
    ref_range_m: float
    confirm_n: int
    #: Freeze-time CONSISTENCY smoke test (~0.0 on a real LUT by construction —
    #: NOT a pose-accuracy figure; that is the manifest's own reproj_mean_px).
    ref_reproj_mean_px: float
    range_min_m: float
    range_median_m: float
    range_max_m: float
    #: Clips: the second the reference was frozen from; None for live sources.
    frozen_at_s: float | None = None
    # >>> GEO-DRIFT-UPDATE D1 BEGIN — which picture this was frozen on >>>
    #: ``"image"`` (the photograph the GCPs are on — pixels and pose share an
    #: instant), ``"clip"``, or ``"live"`` (a fresh grab, which may already have
    #: drifted away from the pose).
    frozen_from: str = "live"
    #: The photograph's filename, when ``frozen_from`` is ``"image"``.
    frozen_from_label: str | None = None
    # <<< GEO-DRIFT-UPDATE D1 END <<<
    # >>> GEO-DRIFT-UPDATE C1 BEGIN — which intrinsics produced this reference >>>
    #: ``"calibration"`` (the LUT's own K) or ``"fov"`` (derived from the field of
    #: view: centred principal point, no distortion). Never let a FOV reference be
    #: mistaken for a calibrated one.
    intrinsics_mode: str = "calibration"
    #: The angles used, when ``intrinsics_mode`` is ``"fov"``.
    fov: dict | None = None
    #: How the LOOKUP TABLE obtained its own K — ``"calibration"`` (measured) or
    #: ``"fov"`` (focal solved from the GCPs). A different question from
    #: ``intrinsics_mode``, which is about this freeze.
    lut_intrinsics_mode: str = "calibration"
    #: Set when derived intrinsics measurably disagree with the lookup table —
    #: shown to the surveyor, because the verdicts inherit the disagreement.
    intrinsics_warning: str | None = None
    # <<< GEO-DRIFT-UPDATE C1 END <<<


class DriftReferenceList(ApiModel):
    items: list[DriftReferenceRead]


class DriftCheckRequest(ApiModel):
    #: Override the frame source for this check only; None = the reference's own.
    source: str | None = None
    #: `video:` sources only — judge the clip's frame at this second. Without it
    #: a clip check re-reads frame 0, which may be the frozen frame itself: an
    #: always-OK tautology.
    at_s: float | None = Field(default=None, ge=0)


class DriftLandmarkShift(ApiModel):
    """One landmark, normalised 0–1: where it was frozen (u, v) and where this
    check found it (x, y) — None when lost."""

    u: float
    v: float
    x: float | None
    y: float | None


# >>> GEO-DRIFT-UPDATE A2 BEGIN — pan/tilt/roll on the wire >>>
class DriftAxisAngles(ApiModel):
    """The solved drift split along the camera's own axes, in degrees.

    Rotations about the camera's right / down / forward axes, from the
    axis-angle form of ``R_now·R_refᵀ``. ``axis_total_deg`` is the vector's
    norm and equals ``rot_deg`` — the parts always sum to the whole.
    """

    #: About the RIGHT axis — the view rose or fell.
    tilt_deg: float
    #: About the DOWN axis — the view swung left or right.
    pan_deg: float
    #: About the FORWARD axis — the horizon tipped.
    roll_deg: float
    #: ‖rvec‖; the same magnitude as ``rot_deg``.
    axis_total_deg: float


# <<< GEO-DRIFT-UPDATE A2 END <<<


class DriftVerdictRead(ApiModel):
    ref_id: str
    checked_utc: str
    #: The judged frame's size — the overlay's coordinate space.
    frame_w: int | None = None
    frame_h: int | None = None
    #: The FROZEN frame's outline in the current frame, normalised 0–1, four
    #: corners clockwise from top-left. The frame edge at zero drift; slides off
    #: as the camera turns. None when no rotation was solved (DEGRADED).
    outline: list[list[float]] | None = None
    landmarks: list[DriftLandmarkShift] | None = None
    #: Where the frame came from: a running detection session's tap ("detector"),
    #: the monitor's own brief capture ("capture"), or a test injection.
    via: Literal["detector", "capture", "provider"] | None = None
    #: Clips: the second that was judged; None for live frames.
    at_s: float | None = None
    #: This frame's raw reading.
    state: DriftState
    #: The temporally confirmed verdict — ALERT ON THIS. None until first promotion.
    status: DriftState | None
    #: True on the check that promotes a non-OK status.
    confirmed: bool
    #: The vendor's honest sentence — safe to show an operator verbatim.
    why: str
    n_landmarks: int
    n_matched: int
    n_lost: int
    #: Solve figures — absent when the check ended DEGRADED before solving.
    n_inliers: int | None = None
    rot_deg: float | None = None
    ground_err_at_ref: float | None = None
    #: ★ Set when a DEGRADED look was re-read as a LARGE MOVE (2026-09-09): the
    #: whole picture's coherent shift in pixels, beyond the landmark search window.
    large_move_px: float | None = None
    resid_mean_px: float | None = None
    mean_conf: float | None = None
    snr: float | None = None
    # >>> GEO-DRIFT-UPDATE A2 BEGIN — pan/tilt/roll on the wire >>>
    #: Which WAY the camera moved, not just how far. None on DEGRADED, exactly
    #: like ``outline`` — both come from the same unsolved rotation.
    angles: DriftAxisAngles | None = None
    # <<< GEO-DRIFT-UPDATE A2 END <<<


class DriftMonitorStartRequest(ApiModel):
    #: Seconds between checks. One a minute is plenty (the vendored README's own
    #: cadence); the floor exists so a typo cannot busy-loop a camera.
    interval_s: float = Field(default=30.0, ge=2, le=3600)
    #: Override the reference's stored source; None = watch what was frozen.
    source: str | None = None
    #: The registered camera this watch belongs to. When given, the watch is
    #: recorded as the camera's DESIRED state and restarted after an API restart
    #: (``camera_service.reconcile_at_boot``); a stop clears it.
    camera_id: UUID | None = None


class DriftMonitorRead(ApiModel):
    """One reference being watched — the loop's state plus its recent verdicts.

    ★ ``capture_failures`` is NOT a verdict: DEGRADED is the monitor saying "I
    can't judge the camera"; a capture failure is this service saying "I couldn't
    even look" (device held elsewhere, reader wedged). The UI keeps them apart.
    """

    ref_id: str
    status: Literal["running", "stopped", "failed"]
    source: str
    interval_s: float
    started_utc: str
    checks_done: int
    capture_failures: int
    last_error: str | None
    #: The freshest verdict — the pill and the map banner render from this.
    last: DriftVerdictRead | None
    #: Newest last; capped by the wire, the loop keeps a longer ring.
    history: list[DriftVerdictRead]


class DriftMonitorList(ApiModel):
    items: list[DriftMonitorRead]


class DriftAlertRow(ApiModel):
    """One promotion moment — the check on which a non-OK status was confirmed."""

    status: DriftState
    checked_utc: str
    why: str


class DriftEpisodeRow(ApiModel):
    """A consecutive run of one non-OK raw state — a sustained alarm is one
    episode, not forty rows."""

    state: DriftState
    first_utc: str
    last_utc: str
    checks: int
    max_rot_deg: float | None


class DriftHourRow(ApiModel):
    hour: str
    ok: int
    moved: int
    changed: int
    degraded: int
    no_frame: int


class DriftSoakReport(ApiModel):
    """The validation day, summarised out of the reference's durable log.

    ★ The runbook's pass criteria read straight off this: no unexplained
    confirmed alert, DEGRADED lining up with night/fog (the `hourly` table makes
    a sunrise false alarm sunrise-shaped), OK-hours rotation well under the
    threshold.
    """

    ref_id: str
    first_utc: str | None
    last_utc: str | None
    checks: int
    #: Looks that produced no frame at all (device busy) — not verdicts.
    no_frame: int
    states: dict[str, int]
    confirmed_alerts: list[DriftAlertRow]
    episodes: list[DriftEpisodeRow]
    rot_ok_mean_deg: float | None
    rot_ok_p95_deg: float | None
    rot_ok_max_deg: float | None
    hourly: list[DriftHourRow]
