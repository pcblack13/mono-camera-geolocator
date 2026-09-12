"""``drift_service`` — the bridge in front of the vendored camera drift monitor.

★ THE MONITOR IS ENGINE-AGNOSTIC; THIS FILE IS THE ENGINE. The vendored package
(`app.vendor.drift_monitor`) asks its host for five things once, at setup: K,
dist, the camera position C, the trusted rotation R_ref, and a ``world_of(u, v)``
callback. Every one of them already lives in a LUT bundle's manifest — the pose
Stage C solved (``pose.R/C/K/dist``) and the per-pixel ground table itself. This
service does nothing but hand them over in the monitor's terms.

★ WORLD_OF RETURNS METRES, AND Z IS RECONSTRUCTED, NOT INVENTED. The LUT arrays
store lat/lon in degrees with no elevation; the monitor needs metric XYZ in C's
frame (the DEM's projected CRS). Horizontal comes from `gis.crs`; the height
comes from the ray itself — C, R and K fix the pixel's bearing, and the
horizontal distance to the LUT's ground point pins where along that bearing the
point sits. The Z this yields is exactly the Z the reference mapping implies,
which is the only honest choice for a monitor that measures CHANGE against that
mapping (it never measures correctness — see the vendored README).

★ FRAME SIZE IS A CONTRACT. The pose is stated at the LUT's build resolution;
live frames are usually smaller. K scales linearly with the frame (the
distortion coefficients live in normalised coordinates and survive scaling);
the template/search windows scale with it too, because the vendor's defaults
were validated at 4032×2268 and would smother a 640-wide preview. A frame whose
ASPECT disagrees with the LUT is refused — that is a crop or a different stream
profile, and scaling it would silently bend the geometry.

★ REFERENCES ARE FOLDERS, LIKE LUT BUNDLES: ``<drift_output_dir>/<ref_id>/``
holding ``landmarks.npz`` (templates + trusted pose, the vendor's own format),
``reference.json`` (what the library lists) and ``reference.jpg`` (the frozen
frame, for the UI). The folder is the durable record; the in-memory monitor
cache only carries the temporal-confirmation state and a restart loses nothing
but the current verdict.

Tests: ``app/tests/test_drift_service.py``.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


class DriftError(ValueError):
    """A drift operation that cannot succeed, refused with the fix named."""


#: Same handover the detector pays: the app's own preview may hold the camera at
#: the moment a freeze/check is requested; the page drops the preview as soon as
#: the request is in flight, and these few seconds are that handover.
DEVICE_HANDOVER_S = 6.0

#: The vendor's window sizes were validated at this frame width (README §Performance);
#: smaller frames get proportionally smaller windows, floored so NCC stays meaningful.
_TUNED_AT_W = 4032.0
_MIN_PATCH = 16
_MIN_SEARCH = 12

#: GEO-DRIFT-UPDATE C1 — above this freeze-time reprojection error, FOV-derived
#: intrinsics are demonstrably not the ones the LUT was built with. Chosen from
#: the measured pair: 0.11 px calibrated, 5.26 px mismatched.
_FOV_REPROJ_WARN_PX = 1.5

#: Warm-up frames discarded after opening a live source — V4L2 devices routinely
#: deliver dark or torn frames while auto-exposure settles.
_WARMUP_FRAMES = 3

_REF_ID_RE = re.compile(r"^[0-9a-f]{32}$")

#: ★ HOW MANY LANDMARKS A REFERENCE KEEPS (2026-09-09, owner ask: more). A check
#: costs ~0.1 ms per landmark and runs in its own thread once every 10 s, so the
#: count never touches the live rate; what it buys is robustness — more points to
#: agree, more to cull when a truck parks. Spread over a finer quota grid so they
#: cover the whole picture, near and far.
DRIFT_LANDMARKS = 24
_LANDMARK_GRID_MANY = (6, 4)

#: Where along the scene the alert threshold is stated (percentile of landmark range).
ALERT_RANGE_PERCENTILE = 90.0

#: ★ A LARGE MOVE MUST NOT READ AS FOG (2026-09-09). The vendor's search window is
#: ±40 px at 4032 (±19 px at 1920): a camera knocked by a degree loses every
#: landmark and the verdict is DEGRADED — "cannot judge" — on the one event the
#: monitor exists for. When no landmark is found, the service estimates the whole
#: frame's coherent shift by phase correlation; a clear shift beyond the window is
#: a MOVED verdict with the angle it implies. Fog, night noise and a changed scene
#: give no clear peak and stay DEGRADED.
LARGE_MOVE_MIN_RESPONSE = 0.30
#: Phase correlation runs on a downscaled frame — plenty for a shift of tens of px.
_LARGE_MOVE_SCALE = 0.25

#: The soak log is appended every look (every 10 s in the background watch, ~1.7 KB
#: a line): capped so a camera watched for months does not fill the disk — the
#: newest half survives a trim, and the soak report reads whatever is there.
LOG_MAX_BYTES = 24 * 1024 * 1024

_LOCK = threading.Lock()
#: ref_id → live DriftMonitor. Held so ``confirm_n`` temporal confirmation works
#: across repeated checks; dropped on delete.
_MONITORS: dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Building the monitor's inputs out of a LUT bundle
# ─────────────────────────────────────────────────────────────────────────────


def _pose_from_manifest(
    manifest: dict[str, Any], *, allow_missing_k: bool = False
) -> dict[str, Any]:
    """The solved pose, validated — or a refusal that names exactly what is missing.

    ★ GEO-DRIFT-UPDATE C1 — ``allow_missing_k`` lets a bundle with no calibration
    through, on the promise that the caller supplies intrinsics from the field of
    view instead (``app.services.intrinsics``). ``R``, ``C`` and the image size
    are still required: they are EXTRINSICS and the LUT's own geometry, and no
    field-of-view figure can stand in for them.
    """
    pose = manifest.get("pose") or {}
    required = ("R", "C", "image_width", "image_height")
    if not allow_missing_k:
        required = required + ("K",)  # type: ignore[assignment]
    missing = [k for k in required if not pose.get(k)]
    if missing:
        raise DriftError(
            "this LUT bundle's manifest has no usable pose (missing: "
            + ", ".join(missing)
            + ") — it predates the pose record. Rebuild the LUT with a current "
            "generator, or pick a bundle whose manifest carries pose.R/C/K."
            + (
                ""
                if "K" not in missing
                else " If this camera was never calibrated, tick 'no calibration' "
                "and give the horizontal field of view instead."
            )
        )
    epsg = (manifest.get("dem") or {}).get("epsg")
    if not epsg:
        raise DriftError(
            "this LUT bundle's manifest records no dem.epsg — without the projected "
            "CRS the camera position cannot be stated in metres. Rebuild the LUT."
        )
    return {
        "R": np.asarray(pose["R"], float).reshape(3, 3),
        "C": np.asarray(pose["C"], float).ravel()[:3],
        "K": None if not pose.get("K") else np.asarray(pose["K"], float).reshape(3, 3),
        "dist": None if pose.get("dist") is None else np.asarray(pose["dist"], float).ravel(),
        "lut_w": int(pose["image_width"]),
        "lut_h": int(pose["image_height"]),
        "epsg": int(epsg),
    }


def _scaled_K(K: np.ndarray, lut_w: int, lut_h: int, frame_w: int, frame_h: int) -> np.ndarray:
    """The intrinsics restated at the monitoring frame's resolution.

    ★ Refuses an aspect mismatch rather than bending it: a same-aspect frame is a
    pure rescale of the same view (fx, fy, cx, cy all scale linearly, and the
    normalised-coordinate distortion model is untouched); a different aspect is a
    crop or a different stream profile, and no K restatement makes the LUT's
    per-pixel table true for it.
    """
    if abs((frame_w / frame_h) - (lut_w / lut_h)) > 0.02 * (lut_w / lut_h):
        raise DriftError(
            f"the frame is {frame_w}×{frame_h} but the LUT was built for a "
            f"{lut_w}×{lut_h} view — different aspect ratio, so this is a crop "
            "or another stream profile, not a rescale of the same picture. Match the "
            "stream profile to the LUT's view, or build a LUT for this profile."
        )
    sx, sy = frame_w / lut_w, frame_h / lut_h
    S = np.diag([sx, sy, 1.0])
    return S @ K


def _make_world_of(
    lut: Any,
    pose: dict[str, Any],
    K_frame: np.ndarray,
    frame_w: int,
    frame_h: int,
):
    """``world_of(u, v)`` in the monitor's terms: frame pixel → metric XYZ, or None.

    Horizontal: the LUT's lat/lon, projected into the DEM's CRS (`gis.crs`, the
    repo's only transformer factory — cached, always-xy). Vertical: the ray. See
    the module docstring for why that is the honest Z.
    """
    import cv2  # noqa: PLC0415 — cv2 must stay service-local

    from gis.crs import get_transformer  # noqa: PLC0415

    to_metric = get_transformer("EPSG:4326", f"EPSG:{pose['epsg']}")
    R, C, dist = pose["R"], pose["C"], pose["dist"]

    def world_of(u: float, v: float) -> tuple[float, float, float] | None:
        lat, lon = lut.lookup(u, v, media_size=(frame_w, frame_h))
        if lat is None:
            return None
        x_arr, y_arr = to_metric.transform(lon, lat)
        x, y = float(np.ravel(x_arr)[0]), float(np.ravel(y_arr)[0])

        # the pixel's bearing in the world frame (R rows are camera axes ⇒ R.T maps
        # camera → world)
        uv = np.array([[[float(u), float(v)]]], dtype=np.float64)
        if dist is not None and np.any(dist != 0):
            n = cv2.undistortPoints(uv, K_frame, dist).reshape(2)
        else:
            n = np.array(
                [
                    (float(u) - K_frame[0, 2]) / K_frame[0, 0],
                    (float(v) - K_frame[1, 2]) / K_frame[1, 1],
                ]
            )
        b = np.array([n[0], n[1], 1.0])
        d = R.T @ (b / np.linalg.norm(b))

        horiz = float(np.hypot(x - C[0], y - C[1]))
        d_horiz = float(np.hypot(d[0], d[1]))
        if d_horiz < 1e-9:  # a truly vertical ray cannot be pinned by horizontal distance
            return None
        z = float(C[2] + (horiz / d_horiz) * d[2])
        return (x, y, z)

    return world_of


def _window_sizes(frame_w: int) -> tuple[int, int]:
    """PATCH/SEARCH restated for this frame width (vendor validated at 4032)."""
    s = frame_w / _TUNED_AT_W
    patch = max(_MIN_PATCH, int(round(48 * s / 2)) * 2)
    search = max(_MIN_SEARCH, int(round(40 * s)))
    return patch, search


def _reproj_mean_px(mon: Any) -> float:
    """Freeze-time CONSISTENCY check: landmarks reprojected through the pose.

    ★ WHAT IT DOES AND DOES NOT MEASURE (review finding). Each landmark's Z is
    reconstructed from the ray through its own pixel, so reprojecting it lands
    back on that pixel BY CONSTRUCTION — on a real LUT this reads ~0.0 px and
    says nothing about the pose's quality (that figure is the manifest's own
    ``pose.reproj_mean_px``). What a non-zero value here catches is plumbing:
    a wrong CRS transform, a mis-scaled K, an aspect mismatch that slipped
    through. Treat it as a smoke test, not an accuracy claim.
    """
    import cv2  # noqa: PLC0415

    obj = np.array([[lm["X"], lm["Y"], lm["Z"]] for lm in mon.landmarks], dtype=np.float64)
    img = np.array([[lm["u"], lm["v"]] for lm in mon.landmarks], dtype=np.float64)
    rvec = cv2.Rodrigues(mon.R_ref)[0]
    tvec = (-mon.R_ref @ mon.C).reshape(3, 1)
    d = np.zeros(5) if mon.dist is None else mon.dist
    uv, _ = cv2.projectPoints(obj.reshape(-1, 1, 3), rvec, tvec, mon.K, d)
    return float(np.mean(np.linalg.norm(uv.reshape(-1, 2) - img, axis=1)))


# ─────────────────────────────────────────────────────────────────────────────
# The live overlay's geometry — where the frozen view sits in the current frame
# ─────────────────────────────────────────────────────────────────────────────


def _outline(mon: Any, r_now: Any, fw: int, fh: int) -> list[list[float]] | None:
    """The frozen frame's four corners mapped into the current frame, normalised
    0–1 — ``H = K·R_now·R_refᵀ·K⁻¹`` (a pure-rotation homography; distortion is
    ignored because this is a picture OF the claim, not the claim). None when the
    check ended DEGRADED before a rotation was solved.
    """
    if r_now is None:
        return None
    K = np.asarray(mon.K, float)
    H = K @ (np.asarray(r_now, float) @ mon.R_ref.T) @ np.linalg.inv(K)
    corners = np.array([[0, 0, 1], [fw, 0, 1], [fw, fh, 1], [0, fh, 1]], dtype=float)
    mapped = (H @ corners.T).T
    if np.any(mapped[:, 2] <= 0):
        return None
    return [[round(float(x / z / fw), 4), round(float(y / z / fh), 4)] for x, y, z in mapped]


# >>> GEO-DRIFT-UPDATE A2 BEGIN — pan/tilt/roll on the wire >>>
def _axis_angles(mon: Any, r_now: Any) -> dict[str, float] | None:
    """The solved drift split into the three axes an operator can act on.

    ★ WHY NOT THE MATRIX. ``R_now`` is internal and never goes on the wire (the
    caller pops it). "Camera moved 0.77°" does not say which way to turn the
    mount; pan/tilt/roll does. So the decomposition happens HERE, while the
    matrix is still in hand, and three floats travel instead of nine.

    ★ AXIS-ANGLE, NOT EULER. The relative rotation is ``R_now·R_refᵀ`` — the
    same one ``_outline`` maps corners through. Rodrigues turns it into a
    rotation VECTOR whose components are the rotations about the camera's own
    right / down / forward axes. That is order-free (no gimbal convention to
    argue about) and its norm is exactly the ``rot_deg`` the monitor already
    reports, so the parts can never disagree with the whole.

    Signs follow the right-hand rule on the camera axes (rows of ``R``: right,
    down, forward). Self-consistent is all that is needed — the monitor only
    ever compares rotations it derived itself (vendored README, "R_ref").
    """
    if r_now is None:
        return None
    import cv2  # noqa: PLC0415

    r_rel = np.asarray(r_now, float) @ np.asarray(mon.R_ref, float).T
    rvec = cv2.Rodrigues(r_rel)[0].reshape(3)
    tilt, pan, roll = (float(np.degrees(a)) for a in rvec)
    return {
        # about the camera's RIGHT axis — the view rose or fell
        "tilt_deg": round(tilt, 4),
        # about the camera's DOWN axis — the view swung left or right
        "pan_deg": round(pan, 4),
        # about the camera's FORWARD axis — the horizon tipped
        "roll_deg": round(roll, 4),
        # ‖rvec‖ — the same magnitude as rot_deg, carried so a consumer that
        # reads only these three never has to re-derive it
        "axis_total_deg": round(float(np.degrees(np.linalg.norm(rvec))), 4),
    }


# <<< GEO-DRIFT-UPDATE A2 END <<<


# ─────────────────────────────────────────────────────────────────────────────
# Frames
# ─────────────────────────────────────────────────────────────────────────────


def _grab_frame(source: str, file_path: Path | None, at_s: float | None = None) -> np.ndarray:
    """One fresh BGR frame from a video file (optionally at ``at_s`` seconds) or
    a live source.

    ★ LIVE SOURCES BORROW BEFORE THEY FIGHT. A V4L2 device admits ONE opener,
    and this process usually already holds it — a running detection session, or
    the panel preview's own re-stream. Both are tapped first; only when nobody
    here has the device do we open it ourselves (with the same brief handover
    retry the detector pays), and release it before returning.
    """
    import cv2  # noqa: PLC0415

    from app.services import detection_service, live_stream_service  # noqa: PLC0415

    cap = None
    try:
        if file_path is not None:
            cap = cv2.VideoCapture(str(file_path))
            if not cap.isOpened():
                raise DriftError("the video file could not be decoded.")
            if at_s is not None and at_s > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(at_s) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                raise DriftError(
                    "the video file has no readable frame"
                    + (f" at t={at_s:g} s — is the clip that long?" if at_s else ".")
                )
            return frame

        tapped = detection_service.latest_raw_frame(source, max_age_s=TAP_MAX_AGE_S)
        if tapped is not None:
            return tapped
        previewed = live_stream_service.latest_preview_frame(source, max_age_s=TAP_MAX_AGE_S)
        if previewed is not None:
            return previewed

        deadline = time.monotonic() + DEVICE_HANDOVER_S
        while True:
            try:
                cap = open_capture_for_drift(source)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        frame = None
        for _ in range(_WARMUP_FRAMES + 1):
            ok, got = cap.read()
            if ok:
                frame = got
        if frame is None:
            raise DriftError("the live source opened but delivered no frame.")
        return frame
    finally:
        if cap is not None:
            cap.release()


def open_capture_for_drift(source: str):  # noqa: ANN201 — cv2.VideoCapture, service-local
    """Seam for the one real device open — patched in tests, trivial in life."""
    from app.services.live_stream_service import open_capture  # noqa: PLC0415

    return open_capture(source)


# ─────────────────────────────────────────────────────────────────────────────
# The reference library
# ─────────────────────────────────────────────────────────────────────────────


def _ref_dir(output_dir: Path, ref_id: str) -> Path:
    """Traversal-proof: a ref id is 32 hex chars or it does not name a folder."""
    if not _REF_ID_RE.fullmatch(ref_id):
        raise DriftError("not a drift reference id.")
    return output_dir / ref_id


def freeze_reference(
    output_dir: Path,
    lut_dir: Path,
    *,
    name: str,
    source: str,
    source_label: str | None = None,
    alert_ground_m: float = 1.0,
    ref_range: float | None = None,
    confirm_n: int = 3,
    n_landmarks: int = DRIFT_LANDMARKS,
    file_path: Path | None = None,
    at_s: float | None = None,
    frame: np.ndarray | None = None,
    # >>> GEO-DRIFT-UPDATE D1 BEGIN — freeze from the photograph the GCPs are on >>>
    image_path: Path | None = None,
    image_label: str | None = None,
    # <<< GEO-DRIFT-UPDATE D1 END <<<
    # >>> GEO-DRIFT-UPDATE C1 BEGIN — intrinsics without a calibration >>>
    no_calibration: bool = False,
    fov_h_deg: float | None = None,
    fov_v_deg: float | None = None,
    square_pixels: bool = True,
    # <<< GEO-DRIFT-UPDATE C1 END <<<
) -> dict[str, Any]:
    """Freeze the trusted state: landmarks + pose, saved as a library reference.

    ★ CALL THIS ONLY WHILE THE MAPPING IS KNOWN GOOD — the monitor measures change
    from this moment, never correctness (a reference frozen on a wrong mapping
    reports OK forever; the vendored README is blunt about it).

    ``frame`` bypasses capture for tests and for freeze-from-upload; otherwise the
    frame comes from ``file_path`` (a video) or ``source`` (a live device/URL).
    """
    import cv2  # noqa: PLC0415

    from app.vendor.drift_monitor import DriftMonitor  # noqa: PLC0415
    from app.vendor.drift_monitor import __version__ as monitor_version  # noqa: PLC0415
    from app.services.detection.lut import GeoLut, LutError  # noqa: PLC0415

    try:
        lut = GeoLut(str(lut_dir))
    except LutError as exc:
        raise DriftError(str(exc)) from exc
    pose = _pose_from_manifest(lut.manifest, allow_missing_k=no_calibration)

    # >>> GEO-DRIFT-UPDATE D1 BEGIN — freeze from the photograph the GCPs are on >>>
    # ★ THE REFERENCE SHOULD BE THE PICTURE THE POSE WAS SOLVED ON. The LUT's
    #   pose belongs to one specific photograph — the one the GCPs were placed on.
    #   Grabbing a fresh frame instead freezes a LATER instant against that pose:
    #   if the camera has already shifted between capture and freeze, the drift is
    #   baked into the reference as "trusted" and the monitor will report OK on a
    #   view that is already wrong. Freezing from the photograph itself makes the
    #   frozen pixels and the frozen pose the same moment.
    #
    # ★ `source` is NOT redirected. It still names what later checks read (the live
    #   camera), and its frames must match this photograph's size — the monitor
    #   compares pixel positions. A capture taken from that same stream matches by
    #   construction, which is the intended flow.
    if frame is None and image_path is not None:
        if not image_path.is_file():
            raise DriftError("the photograph's file is missing from storage.")
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise DriftError(
                f"could not decode the photograph {image_path.name!r} — it is not an "
                "image this build of OpenCV can read."
            )
    # <<< GEO-DRIFT-UPDATE D1 END <<<
    if frame is None:
        frame = _grab_frame(source, file_path, at_s)
    frame_h, frame_w = frame.shape[:2]

    # >>> GEO-DRIFT-UPDATE C1 BEGIN — intrinsics without a calibration >>>
    # ★ THE FOV MODEL IS STATED AT THE LUT'S SIZE, NOT THE FRAME'S. Everything
    #   downstream (`_scaled_K`, `_make_world_of`) expects a K in the LUT's own
    #   pixel space and rescales from there; deriving straight at the frame size
    #   would double-apply the scale. So build K at (lut_w, lut_h) and let the
    #   existing path restate it — one scaling rule, not two.
    intrinsics_mode = "calibration"
    fov_used: dict[str, Any] | None = None
    K_lut, dist = pose["K"], pose["dist"]
    if no_calibration:
        from app.services.intrinsics import IntrinsicsError, k_from_fov  # noqa: PLC0415

        if fov_h_deg is None:
            raise DriftError(
                "'no calibration' needs the camera's horizontal field of view "
                "in degrees. Use the TRUE sensor angle — not a spec sheet's "
                "diagonal figure, which is always larger."
            )
        try:
            K_lut, dist, fov_v_used = k_from_fov(
                pose["lut_w"], pose["lut_h"], fov_h_deg, fov_v_deg, square_pixels
            )
        except IntrinsicsError as exc:
            raise DriftError(str(exc)) from exc
        intrinsics_mode = "fov"
        fov_used = {
            "fov_h_deg": round(float(fov_h_deg), 4),
            "fov_v_deg": round(float(fov_v_used), 4),
            "square_pixels": bool(square_pixels),
        }
    elif K_lut is None:  # defensive: allow_missing_k was False, so this cannot happen
        raise DriftError("this LUT has no intrinsics and 'no calibration' was not set.")
    # <<< GEO-DRIFT-UPDATE C1 END <<<

    K_frame = _scaled_K(K_lut, pose["lut_w"], pose["lut_h"], frame_w, frame_h)
    world_of = _make_world_of(lut, {**pose, "K": K_lut}, K_frame, frame_w, frame_h)

    mon = DriftMonitor(
        K_frame,
        dist,
        ref_range=ref_range if ref_range is not None else 1000.0,
        alert_ground_m=alert_ground_m,
        confirm_n=confirm_n,
    )
    mon.PATCH, mon.SEARCH = _window_sizes(frame_w)

    grid = _LANDMARK_GRID_MANY if n_landmarks > 12 else (4, 3)
    count = mon.setup(frame, world_of, pose["C"], pose["R"], n=n_landmarks, grid=grid)
    if count < mon.MIN_INLIERS:
        raise DriftError(
            f"only {count} usable landmarks were found (need at least "
            f"{mon.MIN_INLIERS}) — the view is too featureless to monitor, or the "
            "LUT covers too little of it. Try a frame with more textured, static "
            "detail in LUT-covered ground."
        )

    ranges = sorted(lm["range"] for lm in mon.landmarks)
    if ref_range is None:
        # ★ State the threshold at the scene's ACTUAL range, not a nominal 1 km:
        #   "1 m of ground error" only means something at the range it is measured.
        # ★ …AND AT THE FAR END OF THE SCENE (2026-09-09, found on a real 1920 px
        #   frame). Ground error grows with range: at the median range (71 m on
        #   that scene) a 0.4° pan read 0.5 m and OK while the same pan was 5 m at
        #   the scene's far landmarks (770 m). The alert must hold for ALL the ground
        #   the reference covers, so the threshold is stated at the 90th percentile
        #   of landmark range — the far end, robust to one horizon point.
        mon.ref_range = float(np.percentile(ranges, ALERT_RANGE_PERCENTILE))

    ref_id = uuid.uuid4().hex
    folder = _ref_dir(output_dir, ref_id)
    folder.mkdir(parents=True, exist_ok=True)
    mon.save(str(folder / "landmarks.npz"))
    ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if ok:
        (folder / "reference.jpg").write_bytes(jpg.tobytes())

    record = {
        "ref_id": ref_id,
        "name": name.strip() or lut.site,
        "source": source,
        "source_label": source_label or source,
        "lut_site": lut.site,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # >>> GEO-DRIFT-UPDATE C1 BEGIN — record WHICH intrinsics were used >>>
        # ★ A verdict is only as good as the K behind it, and FOV-derived K
        #   assumes a centred principal point and no distortion. Recording the
        #   mode means a reference can never be mistaken later for a calibrated
        #   one — the export and the field unit carry it too.
        "intrinsics_mode": intrinsics_mode,
        "fov": fov_used,
        # ★ GEO-DRIFT-UPDATE C3 — and how the LUT got ITS K, which is a different
        #   question. `intrinsics_mode` above says how THIS freeze obtained K;
        #   when it read one from the bundle, that K may itself have been SOLVED
        #   from the GCPs rather than measured on a checkerboard. A field unit's
        #   log should not have to open the LUT to find that out.
        "lut_intrinsics_mode": (lut.manifest.get("pose") or {}).get(
            "intrinsics_mode", "calibration"
        ),
        # <<< GEO-DRIFT-UPDATE C1 END <<<
        "frame_width": frame_w,
        "frame_height": frame_h,
        "n_landmarks": count,
        "alert_ground_m": mon.alert_ground_m,
        "ref_range_m": mon.ref_range,
        "confirm_n": mon.confirm_n,
        "patch_px": mon.PATCH,
        "search_px": mon.SEARCH,
        "range_min_m": round(ranges[0], 1),
        "range_median_m": round(float(np.median(ranges)), 1),
        "range_max_m": round(ranges[-1], 1),
        "ref_reproj_mean_px": round(_reproj_mean_px(mon), 2),
        "monitor_version": monitor_version,
        # ★ Clips: which second the reference was frozen from — so a later check at
        #   the SAME second can be recognised for what it is (a frame compared with
        #   itself) instead of read as "perfectly steady".
        "frozen_at_s": None if file_path is None else float(at_s or 0.0),
        # >>> GEO-DRIFT-UPDATE D1 BEGIN — say WHICH picture this was frozen on >>>
        # ★ "A fresh grab" and "the photograph the GCPs are on" are different
        #   claims about how trustworthy the reference is, and only one of them
        #   guarantees the pixels and the pose share an instant. Recording it means
        #   a reference can be audited long after the surveyor has forgotten.
        "frozen_from": "image" if image_path is not None else ("clip" if file_path else "live"),
        "frozen_from_label": image_label,
        # <<< GEO-DRIFT-UPDATE D1 END <<<
    }
    # >>> GEO-DRIFT-UPDATE C1 BEGIN — catch derived-K disagreeing with the LUT >>>
    # ★ MEASURED, NOT THEORETICAL. `ref_reproj_mean_px` reads ~0 by construction
    #   when the K used here is the K the LUT was BUILT with. Supply a different
    #   one — FOV-derived, centred principal point, no distortion — against a LUT
    #   that was built from a real calibration, and the landmarks stop agreeing
    #   with each other. Measured on this exact pairing: the smoke test went 0.11
    #   px -> 5.26 px, and the monitor then reported CHANGED on 2 of 7 steady
    #   frames. CHANGED means "no rigid rotation explains this", which is a
    #   truthful reading of inconsistent inputs and a false alarm about the camera.
    #
    #   So say it at freeze time, where it is still cheap to fix. Not a refusal:
    #   an end-to-end uncalibrated pipeline (LUT built from the same FOV model)
    #   is a legitimate use, and there this figure stays near zero.
    if intrinsics_mode == "fov" and record["ref_reproj_mean_px"] > _FOV_REPROJ_WARN_PX:
        record["intrinsics_warning"] = (
            f"the derived intrinsics disagree with this lookup table by "
            f"{record['ref_reproj_mean_px']} px (a calibrated pairing reads ~0). "
            "The table was almost certainly built with a real calibration, so a "
            "field-of-view K is not the one it encodes — expect inflated rotation "
            "and occasional CHANGED verdicts on a steady camera. Use the bundle's "
            "own calibration, or rebuild the table from the same field of view."
        )
    # <<< GEO-DRIFT-UPDATE C1 END <<<
    (folder / "reference.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with _LOCK:
        _MONITORS[ref_id] = mon
        # ★ A watch guarding a SUPERSEDED reference guards nothing — and keeps
        #   waking the camera invisibly (the UI follows the newest reference).
        #   Freezing anew for a source retires every older watch on that source.
        stale = [
            r.ref_id
            for r in _RUNS.values()
            if r.source == source and r.status == "running" and r.ref_id != ref_id
        ]
    for stale_id in stale:
        stop_monitor(stale_id)
    return record


def scan_references(output_dir: Path) -> list[dict[str, Any]]:
    """Every saved reference, newest first — a folder whose record is unreadable
    is skipped, the library-scan rule every other library here follows."""
    out: list[dict[str, Any]] = []
    if not output_dir.is_dir():
        return out
    for rec_path in output_dir.glob("*/reference.json"):
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _REF_ID_RE.fullmatch(str(rec.get("ref_id", ""))):
            out.append(rec)
    out.sort(key=lambda r: r.get("created_utc") or "", reverse=True)
    return out


def read_reference(output_dir: Path, ref_id: str) -> dict[str, Any]:
    rec_path = _ref_dir(output_dir, ref_id) / "reference.json"
    try:
        return json.loads(rec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriftError("no such drift reference.") from exc


def delete_reference(output_dir: Path, ref_id: str) -> bool:
    folder = _ref_dir(output_dir, ref_id)
    if not (folder / "reference.json").is_file():
        return False
    stop_monitor(ref_id)  # a loop watching a deleted reference would fail on its next tick
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    with _LOCK:
        _MONITORS.pop(ref_id, None)
        _RUNS.pop(ref_id, None)
        _CHECK_LOCKS.pop(ref_id, None)
    return True


def _monitor_for(output_dir: Path, ref_id: str) -> Any:
    """The live monitor for a reference — cached, so ``confirm_n`` temporal
    confirmation accumulates across repeated checks."""
    with _LOCK:
        mon = _MONITORS.get(ref_id)
    if mon is not None:
        return mon
    from app.vendor.drift_monitor import DriftMonitor  # noqa: PLC0415

    npz = _ref_dir(output_dir, ref_id) / "landmarks.npz"
    if not npz.is_file():
        raise DriftError("no such drift reference.")
    mon = DriftMonitor.load(str(npz))
    rec = read_reference(output_dir, ref_id)
    # the window sizes are tuning, not state — restate them from the record
    mon.PATCH = int(rec.get("patch_px", mon.PATCH))
    mon.SEARCH = int(rec.get("search_px", mon.SEARCH))
    with _LOCK:
        _MONITORS.setdefault(ref_id, mon)
        return _MONITORS[ref_id]


def _check_lock(ref_id: str) -> threading.Lock:
    """One lock per reference around ``mon.check`` — a manual Check now racing
    the monitor loop on the SAME DriftMonitor would otherwise double-count one
    instant toward ``confirm_n`` (the temporal window is mutable state)."""
    with _LOCK:
        return _CHECK_LOCKS.setdefault(ref_id, threading.Lock())


_CHECK_LOCKS: dict[str, threading.Lock] = {}


def check_reference(
    output_dir: Path,
    ref_id: str,
    *,
    source: str | None = None,
    file_path: Path | None = None,
    at_s: float | None = None,
    frame: np.ndarray | None = None,
) -> dict[str, Any]:
    """One monitoring pass: fresh frame in, the vendor's verdict dict out.

    ★ ALERT ON ``status``, LOG ``state``: ``status`` is the temporally confirmed
    verdict (``confirm_n`` consecutive identical non-OK states), ``state`` is this
    frame's raw reading. The wire carries both, spelled exactly like the vendor.

    ★ FILE SOURCES: ``at_s`` picks the clip moment to judge. Without it a clip
    check re-reads the very frame the reference may have been frozen from — an
    always-OK tautology that proves nothing.
    """
    mon = _monitor_for(output_dir, ref_id)
    if frame is None:
        rec = read_reference(output_dir, ref_id)
        frame = _grab_frame(source or rec["source"], file_path, at_s)
    try:
        with _check_lock(ref_id):
            verdict = dict(mon.check(frame))
    except ValueError as exc:
        # the vendor's size guard — restate it with the product's remedy
        raise DriftError(
            f"{exc} If the stream profile changed, freeze a new reference for it."
        ) from exc
    r_now = verdict.pop("R_now", None)  # internal matrix — consumed here, never on the wire
    if verdict.get("state") == "DEGRADED":
        _reacquire_large_move(mon, output_dir, ref_id, frame, verdict)
    verdict["ref_id"] = ref_id
    verdict["checked_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fh, fw = (int(x) for x in mon.frame_shape)
    verdict["frame_w"], verdict["frame_h"] = fw, fh
    # ★ THE LIVE OVERLAY'S GEOMETRY: where the FROZEN frame's outline now sits in
    #   the current frame, from the solved rotation alone. At zero drift it is the
    #   frame edge; as the camera turns, the box slides off the picture.
    verdict["outline"] = _outline(mon, r_now, fw, fh)
    # >>> GEO-DRIFT-UPDATE A2 BEGIN — pan/tilt/roll on the wire >>>
    #   Same r_now, consumed in the same breath as the outline and before it
    #   goes out of scope. None on DEGRADED, exactly like the outline.
    verdict["angles"] = _axis_angles(mon, r_now)
    # <<< GEO-DRIFT-UPDATE A2 END <<<
    # Re-locate each landmark (twelve template matches — milliseconds) for the
    # overlay's dots. Read-only on the monitor, so it sits outside the check
    # lock; best-effort — the dots are a courtesy, the verdict is the product.
    locs: list[tuple[float, float, float] | None] = []
    try:
        gray = mon._as_gray(frame)  # noqa: SLF001 — our vendored copy
        locs = [mon._locate(gray, lm) for lm in mon.landmarks]  # noqa: SLF001
    except Exception:  # noqa: BLE001
        locs = []
    verdict["landmarks"] = (
        [
            {
                "u": round(lm["u"] / fw, 5),
                "v": round(lm["v"] / fh, 5),
                "x": None if loc is None else round(loc[0] / fw, 5),
                "y": None if loc is None else round(loc[1] / fh, 5),
            }
            for lm, loc in zip(mon.landmarks, locs, strict=True)
        ]
        if locs
        else None
    )
    # which clip second was judged — logged, so a run of "perfect" verdicts can be
    # told apart from a run of self-comparisons after the fact
    verdict["at_s"] = None if file_path is None else float(at_s or 0.0)
    _append_log(output_dir, ref_id, {"kind": "verdict", **verdict})
    return verdict


# ─────────────────────────────────────────────────────────────────────────────
# The soak log — every look, durable, for the validation day
# ─────────────────────────────────────────────────────────────────────────────


def _reacquire_large_move(
    mon: Any, output_dir: Path, ref_id: str, frame: np.ndarray, verdict: dict[str, Any]
) -> None:
    """A DEGRADED verdict with NO landmark found: was the camera simply knocked
    further than the search window reaches? Phase-correlate the whole frame with
    the frozen one; a clear, coherent shift beyond the window is a MOVED verdict.

    ★ Mutates the verdict in place AND the monitor's temporal window, because the
    vendor's ``_finish`` already counted this look as DEGRADED — the correction
    must replace that count, not add to it, or ``confirm_n`` would be off by one.
    """
    import cv2  # noqa: PLC0415

    # ★ THE EDGE OF THE WINDOW (a 0.8° pan on a 1920 px frame): most landmarks are
    #   still found and agree on one strong rotation, but one or two sit just past
    #   ±SEARCH and are lost, and the vendor's quota (60 % of those picked) falls
    #   short by one. That is not "cannot judge" — it is a coherent move seen by
    #   enough landmarks. Above the vendor's absolute floor and with the SNR a
    #   rigid rotation gives, it is MOVED, on the vendor's own numbers.
    rot = verdict.get("rot_deg")
    if (
        rot is not None
        and verdict.get("n_inliers", 0) >= int(mon.MIN_INLIERS)
        and (verdict.get("snr") or 0.0) >= float(mon.MIN_SNR)
        and (verdict.get("ground_err_at_ref") or 0.0) > float(mon.alert_ground_m)
    ):
        verdict.update(
            state="MOVED",
            why=(
                f"{verdict['n_inliers']} of {verdict['n_landmarks']} landmarks agree on a "
                f"rotation of {rot:.3f} deg = {verdict['ground_err_at_ref']:.2f} m of ground "
                f"error at {mon.ref_range:.0f} m (threshold {mon.alert_ground_m:.2f} m, SNR "
                f"{verdict['snr']:.1f}); the rest fell outside the ±{int(mon.SEARCH)} px "
                "search window. Re-aim, or re-freeze on a new frame."
            ),
        )
        _promote_to_moved(mon, verdict)
        return

    if verdict.get("n_inliers", 0) != 0:
        return  # a rotation was solved but weak or below threshold — the vendor's call stands

    ref_gray = getattr(mon, "_service_ref_gray", None)
    if ref_gray is None:
        jpg = _ref_dir(output_dir, ref_id) / "reference.jpg"
        ref_img = cv2.imread(str(jpg), cv2.IMREAD_GRAYSCALE) if jpg.is_file() else None
        if ref_img is None:
            return
        ref_gray = cv2.resize(ref_img, None, fx=_LARGE_MOVE_SCALE, fy=_LARGE_MOVE_SCALE)
        mon._service_ref_gray = ref_gray  # noqa: SLF001 — our vendored copy, cached once
    gray = mon._as_gray(frame)  # noqa: SLF001
    if tuple(gray.shape[:2]) != tuple(mon.frame_shape):
        return
    small = cv2.resize(gray, None, fx=_LARGE_MOVE_SCALE, fy=_LARGE_MOVE_SCALE)
    if small.shape != ref_gray.shape:
        return
    a = np.float32(ref_gray)
    b = np.float32(small)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, win)
    shift_px = float(np.hypot(dx, dy) / _LARGE_MOVE_SCALE)
    if response < LARGE_MOVE_MIN_RESPONSE or shift_px <= float(mon.SEARCH):
        return  # no coherent picture-wide shift: fog, night, a changed scene — DEGRADED stands
    f = 0.5 * (float(mon.K[0, 0]) + float(mon.K[1, 1]))
    ang = float(np.degrees(np.arctan2(shift_px, f)))
    ground = float(np.radians(ang) * mon.ref_range)
    verdict.update(
        state="MOVED",
        rot_deg=round(ang, 3),
        ground_err_at_ref=round(ground, 2),
        resid_mean_px=None,
        snr=None,
        mean_conf=None,
        large_move_px=round(shift_px, 1),
        why=(
            f"the whole picture shifted about {shift_px:.0f} px (≈ {ang:.2f}°, "
            f"{ground:.1f} m at {mon.ref_range:.0f} m) — further than the landmark "
            f"search window (±{int(mon.SEARCH)} px) reaches, so no landmark was found "
            "where it was left; the camera has moved a lot. Re-aim, or re-freeze on a "
            "new frame."
        ),
    )
    _promote_to_moved(mon, verdict)


def _promote_to_moved(mon: Any, verdict: dict[str, Any]) -> None:
    """Replace this look's DEGRADED count in the vendor's temporal window with
    MOVED, and restate status/confirmed exactly as its ``_finish`` would."""
    recent = mon._recent  # noqa: SLF001
    if len(recent) > 0:
        recent.pop()
    recent.append("MOVED")
    if len(recent) == recent.maxlen and len(set(recent)) == 1:
        mon.status = "MOVED"
    verdict["status"] = mon.status
    verdict["confirmed"] = mon.status == "MOVED"


def _append_log(output_dir: Path, ref_id: str, entry: dict[str, Any]) -> None:
    """One JSONL line per look, appended in the reference's own folder.

    ★ THE FIELD DAY'S RECORD. The in-memory ring dies with the process; the
    day-long lighting soak (validation runbook) needs every verdict to survive a
    restart. A day at 30 s is ~3k small lines — no rotation needed; deleting the
    reference deletes its log.

    ★ Best-effort: a full disk must not kill the monitor loop — the ring still
    holds the recent verdicts, and the next status poll still tells the truth.
    """
    path = _ref_dir(output_dir, ref_id) / "log.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if path.stat().st_size > LOG_MAX_BYTES:
            _trim_log(path)
    except OSError:
        pass


def _trim_log(path: Path) -> None:
    """Keep the newest half of an over-full log — whole lines, oldest first to go."""
    data = path.read_bytes()
    cut = data.find(b"\n", len(data) // 2)
    if cut < 0:
        return
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_bytes(data[cut + 1 :])
    tmp.replace(path)


def soak_report(output_dir: Path, ref_id: str) -> dict[str, Any]:
    """The validation day, summarised out of the log: did the light fool it?

    ★ WHAT PASSES THE SOAK (the runbook's criteria, computed here): the states
    tally shows no confirmed MOVED/CHANGED the operator cannot account for, the
    DEGRADED episodes line up with night/fog rather than clear daylight, and the
    OK-hours rotation stays well under the threshold. `hourly` exists exactly so
    a sunrise false alarm shows up as a sunrise-shaped bump.
    """
    from collections import Counter  # noqa: PLC0415

    read_reference(output_dir, ref_id)  # 404 before an empty report
    path = _ref_dir(output_dir, ref_id) / "log.jsonl"

    verdicts: list[dict[str, Any]] = []
    no_frames: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn tail line (power cut mid-write) is not a report-killer
            if entry.get("kind") == "no_frame":
                no_frames.append(entry)
            elif entry.get("kind") == "verdict":
                verdicts.append(entry)

    states = Counter(str(v.get("state")) for v in verdicts)
    confirmed_alerts = [
        {"status": v["status"], "checked_utc": v.get("checked_utc", ""), "why": v.get("why", "")}
        for v in verdicts
        if v.get("confirmed")
    ]

    # consecutive same-state runs — a sustained alarm is one episode, not 40 rows
    episodes: list[dict[str, Any]] = []
    for v in verdicts:
        state = str(v.get("state"))
        rot = v.get("rot_deg")
        if episodes and episodes[-1]["state"] == state:
            episodes[-1]["last_utc"] = v.get("checked_utc", "")
            episodes[-1]["checks"] += 1
            if rot is not None:
                prev = episodes[-1]["max_rot_deg"]
                episodes[-1]["max_rot_deg"] = rot if prev is None else max(prev, rot)
        else:
            episodes.append(
                {
                    "state": state,
                    "first_utc": v.get("checked_utc", ""),
                    "last_utc": v.get("checked_utc", ""),
                    "checks": 1,
                    "max_rot_deg": rot,
                }
            )
    non_ok_episodes = [e for e in episodes if e["state"] != "OK"][-100:]

    hourly: dict[str, Counter] = {}
    for v in verdicts:
        hourly.setdefault(str(v.get("checked_utc", ""))[:13], Counter())[str(v.get("state"))] += 1
    for n in no_frames:
        hourly.setdefault(str(n.get("checked_utc", ""))[:13], Counter())["NO_FRAME"] += 1
    hourly_rows = [
        {
            "hour": hour,
            "ok": c.get("OK", 0),
            "moved": c.get("MOVED", 0),
            "changed": c.get("CHANGED", 0),
            "degraded": c.get("DEGRADED", 0),
            "no_frame": c.get("NO_FRAME", 0),
        }
        for hour, c in sorted(hourly.items())
    ]

    ok_rots = [
        float(v["rot_deg"])
        for v in verdicts
        if v.get("state") == "OK" and v.get("rot_deg") is not None
    ]
    stamps = [str(v.get("checked_utc", "")) for v in verdicts] + [
        str(n.get("checked_utc", "")) for n in no_frames
    ]
    return {
        "ref_id": ref_id,
        "first_utc": min(stamps) if stamps else None,
        "last_utc": max(stamps) if stamps else None,
        "checks": len(verdicts),
        "no_frame": len(no_frames),
        "states": dict(states),
        "confirmed_alerts": confirmed_alerts,
        "episodes": non_ok_episodes,
        "rot_ok_mean_deg": round(float(np.mean(ok_rots)), 4) if ok_rots else None,
        "rot_ok_p95_deg": round(float(np.percentile(ok_rots, 95)), 4) if ok_rots else None,
        "rot_ok_max_deg": round(float(np.max(ok_rots)), 4) if ok_rots else None,
        "hourly": hourly_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The monitor loop — check every interval, forever, without owning the camera
# ─────────────────────────────────────────────────────────────────────────────

#: A tapped detector frame older than this means the reader is wedged — judging
#: drift from a stuck picture would report whatever was true when it stuck.
TAP_MAX_AGE_S = 5.0

#: History ring per run — at the default 30 s interval this is two hours.
HISTORY_LEN = 240


@dataclass
class DriftMonitorRun:
    """One reference being watched. Mutated only by its own thread; readers copy.

    ★ IN MEMORY ON PURPOSE, like a detection session: a restart loses the current
    verdict and the history ring, never the reference — the folder is the durable
    record, and the loop restarts in one API call.
    """

    ref_id: str
    source: str
    interval_s: float
    status: str = "running"  # running | stopped | failed
    started_utc: str = ""
    checks_done: int = 0
    #: Ticks that produced NO frame (device held elsewhere, reader wedged). NOT a
    #: verdict — DEGRADED is the monitor saying "I can't judge the camera"; this
    #: is the service saying "I couldn't even look".
    capture_failures: int = 0
    last_error: str | None = None
    last: dict[str, Any] | None = None
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None


_RUNS: dict[str, DriftMonitorRun] = {}


def _acquire_frame(
    source: str, frame_provider: Callable[[], np.ndarray] | None
) -> tuple[np.ndarray | None, str, str | None]:
    """One frame for this tick: ``(frame, via, error)``.

    Order: the test/injection provider, then a running detection session's tap
    (the camera admits ONE opener, and while detection runs that opener is the
    detector), then a brief open of our own — released before the next tick, so
    the device stays free between checks.
    """
    if frame_provider is not None:
        try:
            return frame_provider(), "provider", None
        except Exception as exc:  # noqa: BLE001 — a provider failure is a tick, not a death
            return None, "provider", f"no frame: {exc}"

    from app.services import detection_service  # noqa: PLC0415

    tapped = detection_service.latest_raw_frame(source, max_age_s=TAP_MAX_AGE_S)
    if tapped is not None:
        return tapped, "detector", None

    try:
        return _grab_frame(source, None), "capture", None
    except Exception as exc:  # noqa: BLE001 — the camera being busy is a tick, not a death
        return None, "capture", f"no frame: {exc}"


def _monitor_loop(
    run: DriftMonitorRun,
    output_dir: Path,
    frame_provider: Callable[[], np.ndarray] | None,
) -> None:
    try:
        while not run._stop.is_set():
            frame, via, err = _acquire_frame(run.source, frame_provider)
            if frame is None:
                run.capture_failures += 1
                run.last_error = err
                _append_log(
                    output_dir,
                    run.ref_id,
                    {
                        "kind": "no_frame",
                        "checked_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "via": via,
                        "error": err,
                    },
                )
            else:
                # ★ A DriftError here is terminal, not a tick: it means the frames
                #   no longer fit the reference (stream profile changed) or the
                #   reference is gone — repeating the same failure every interval
                #   would be an alarm clock, not a monitor.
                verdict = check_reference(output_dir, run.ref_id, frame=frame)
                verdict["via"] = via
                run.last = verdict
                run.history.append(verdict)
                run.checks_done += 1
                run.last_error = None
            run._stop.wait(run.interval_s)
        run.status = "stopped"
    except DriftError as exc:
        run.status = "failed"
        run.last_error = str(exc)
    except Exception as exc:  # noqa: BLE001 — the thread must never die silently
        run.status = "failed"
        run.last_error = f"{type(exc).__name__}: {exc}"


def start_monitor(
    output_dir: Path,
    ref_id: str,
    *,
    interval_s: float = 30.0,
    source: str | None = None,
    frame_provider: Callable[[], np.ndarray] | None = None,
) -> DriftMonitorRun:
    """Watch a reference: one check per interval until stopped.

    ★ LIVE SOURCES ONLY. A stored clip does not drift while it sits on disk —
    judge a clip once with a check; monitoring is for a camera that is out in
    the weather right now.
    """
    rec = read_reference(output_dir, ref_id)
    src = source or str(rec["source"])
    if src.startswith("video:") and frame_provider is None:
        raise DriftError(
            "monitoring watches a live source — a stored clip does not drift. "
            "Run a single check against the clip instead."
        )
    _monitor_for(output_dir, ref_id)  # fail fast while the caller can still see it

    run = DriftMonitorRun(
        ref_id=ref_id,
        source=src,
        interval_s=float(interval_s),
        started_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    thread = threading.Thread(
        target=_monitor_loop,
        args=(run, output_dir, frame_provider),
        name=f"drift-monitor-{ref_id[:8]}",
        daemon=True,
    )
    run._thread = thread
    # ★ Check-and-insert under ONE lock hold: two concurrent starts must not both
    #   pass the check and orphan a loop thread nothing can reach to stop.
    with _LOCK:
        existing = _RUNS.get(ref_id)
        if existing is not None and existing.status == "running":
            raise DriftError("this reference is already being monitored — stop that run first.")
        _RUNS[ref_id] = run
    thread.start()
    return run


def stop_monitor(ref_id: str) -> DriftMonitorRun | None:
    """Stop a run. Returns its final state, or None if nothing was ever started."""
    with _LOCK:
        run = _RUNS.get(ref_id)
    if run is None:
        return None
    run._stop.set()
    if run._thread is not None:
        run._thread.join(timeout=2.0)
    if run.status == "running":  # the thread outlived the join window
        run.status = "stopped"
    return run


def get_monitor(ref_id: str) -> DriftMonitorRun | None:
    with _LOCK:
        return _RUNS.get(ref_id)


def latest_status_for_source(source: str) -> dict[str, Any] | None:
    """The newest RUNNING watch on ``source`` and its confirmed verdict, or None.

    ★ FOR THE DETECTION STAMP (2026-09-02). ``detection_service`` asks this once
    per detected frame so every mark carries the camera's drift verdict at the
    moment it was placed. The answer is ``status`` (the temporally CONFIRMED
    verdict — alert on status, log state) or None for "no verdict yet"; a stopped
    or failed watch is not an answer, it is silence, and silence must read as
    ``unwatched`` rather than as the last thing anyone said.
    """
    with _LOCK:
        runs = [r for r in _RUNS.values() if r.source == source and r.status == "running"]
    if not runs:
        return None
    run = max(runs, key=lambda r: r.started_utc)
    last = run.last
    with _LOCK:
        mon = _MONITORS.get(run.ref_id)
    return {
        "ref_id": run.ref_id,
        "status": None if last is None else last.get("status"),
        "state": None if last is None else last.get("state"),
        "checked_utc": None if last is None else last.get("checked_utc"),
        # ★ THE MEASURED SHIFT (2026-09-09): the newest look's rotation, so every
        #   mark can carry the ground shift at ITS OWN range (radians × range).
        "rot_deg": None if last is None else last.get("rot_deg"),
        "ref_range_m": None if mon is None else float(mon.ref_range),
    }


def list_monitors() -> list[DriftMonitorRun]:
    with _LOCK:
        return sorted(_RUNS.values(), key=lambda r: r.started_utc, reverse=True)
