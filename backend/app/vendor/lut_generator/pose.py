"""Camera pose recovery from a GUI project file.

This mirrors core/stage_a.py of the geolocation GUI (SQPnP + Levenberg-Marquardt
refinement through the full distortion model). It is vendored rather than
imported so the generator can run standalone on any machine; tests/ contains a
comparison against the GUI implementation to catch drift.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

_UP = np.array([0.0, 0.0, 1.0])


@dataclass
class CameraPose:
    """Solved exterior + interior orientation."""

    R: np.ndarray            # 3x3 world->camera rotation
    C: np.ndarray            # camera centre in the DEM's projected CRS
    K: np.ndarray            # 3x3 intrinsics
    dist: np.ndarray         # (5,) [k1, k2, p1, p2, k3]
    width: int
    height: int
    azimuth_deg: float
    tilt_down_deg: float
    roll_deg: float
    reproj_mean_px: float
    reproj_max_px: float
    n_gcps_used: int
    position_shift_m: float

    def summary(self) -> str:
        return ("pose: az %.3f deg  tilt %.3f deg  roll %.3f deg | "
                "reproj mean %.2f max %.2f px on %d GCPs | pos shift %.2f m"
                % (self.azimuth_deg, self.tilt_down_deg, self.roll_deg,
                   self.reproj_mean_px, self.reproj_max_px, self.n_gcps_used,
                   self.position_shift_m))

    def to_dict(self) -> dict:
        return {
            "R": self.R.tolist(),
            "C": self.C.tolist(),
            "K": self.K.tolist(),
            "dist": self.dist.tolist(),
            "image_width": self.width,
            "image_height": self.height,
            "azimuth_deg": round(self.azimuth_deg, 6),
            "tilt_down_deg": round(self.tilt_down_deg, 6),
            "roll_deg": round(self.roll_deg, 6),
            "reproj_mean_px": round(self.reproj_mean_px, 4),
            "reproj_max_px": round(self.reproj_max_px, 4),
            "n_gcps_used": self.n_gcps_used,
            "position_shift_m": round(self.position_shift_m, 4),
        }


def roll_from_R(R: np.ndarray) -> float:
    """Roll (deg): angle of the camera x-axis off the horizon."""
    f = R[2]
    r0 = np.cross(f, _UP)
    n = np.linalg.norm(r0)
    if n < 1e-9:
        return 0.0
    r0 = r0 / n
    d0 = np.cross(f, r0)
    return float(np.degrees(np.arctan2(R[0] @ d0, R[0] @ r0)))


def solve_pose(obj_xyz: np.ndarray, img_uv: np.ndarray, K: np.ndarray,
               dist: np.ndarray, cam_C: np.ndarray):
    """SQPnP + LM refinement. Returns (R, C, reproj_errors)."""
    obj = np.asarray(obj_xyz, float)
    img = np.asarray(img_uv, float)
    C = np.asarray(cam_C, float)
    dist = np.asarray(dist, float)

    ok, rvec, tvec = cv2.solvePnP((obj - C).reshape(-1, 1, 3),
                                  img.reshape(-1, 1, 2), K, dist,
                                  flags=cv2.SOLVEPNP_SQPNP)
    if not ok:
        raise RuntimeError("solvePnP (SQPnP) failed")
    rvec, tvec = cv2.solvePnPRefineLM((obj - C).reshape(-1, 1, 3),
                                      img.reshape(-1, 1, 2), K, dist, rvec, tvec)
    R = cv2.Rodrigues(rvec)[0]
    Cc = C - R.T @ tvec.reshape(3)

    # residuals through the same distortion model the solve used
    rep = np.full(len(obj), np.inf)
    in_front = ((obj - Cc) @ R[2]) > 0
    if np.any(in_front):
        uv, _ = cv2.projectPoints(obj[in_front].reshape(-1, 1, 3),
                                  cv2.Rodrigues(R)[0], (-R @ Cc).reshape(3, 1), K, dist)
        rep[in_front] = np.linalg.norm(uv.reshape(-1, 2) - img[in_front], axis=1)
    return R, Cc, rep


# >>> GEO-DRIFT-UPDATE C3 BEGIN — solve the focal when there is no calibration >>>
def solve_pose_free_focal(obj_xyz: np.ndarray, img_uv: np.ndarray, K: np.ndarray,
                          dist: np.ndarray, cam_C: np.ndarray,
                          span: float = 0.45):
    """:func:`solve_pose`, but with ONE focal scale free. Returns (R, C, rep, K).

    ★ WHY THIS EXISTS. "No calibration" does not mean "assume a focal" — it means
    RECOVER it. A pinhole has nine intrinsics; without a calibration the principal
    point is assumed at the image centre and all distortion assumed zero, and
    those assumptions are nearly degenerate with heading/tilt at this geometry, so
    they land in the pose rather than in the ground coordinates. The focal is the
    one intrinsic that is NOT absorbed — so it is the one that must be solved.

    ★ MEASURED, on Yammouneh 200 m / DJI_0124 with 49 surveyed GCPs
    (``outputs/calibration_study/REPORT.md``): freezing the focal at a typed field
    of view costs 37 m of ground error from a 60 deg guess and 61 m from 84 deg,
    while solving it lands at 2.08 m from ANY seed. The entered focal is a
    starting point, not an input.

    ★ ONE SCALE, NOT TWO. ``fy`` follows ``fx`` at the ratio already in ``K``.
    Solving ``fy`` independently was tried and rejected upstream: at grazing
    geometry it trades off almost perfectly against tilt and runs away.

    ``span`` is the fractional bracket around the seed (0.45 -> 0.55x .. 1.45x),
    wide enough that a badly wrong guess still contains the answer.
    """
    from scipy.optimize import minimize_scalar  # noqa: PLC0415

    K = np.asarray(K, float)
    fx0 = float(K[0, 0])
    ratio = float(K[1, 1]) / fx0 if fx0 else 1.0

    def _at(fx: float):
        Kf = K.copy()
        Kf[0, 0] = fx
        Kf[1, 1] = fx * ratio
        return Kf

    def _cost(fx: float) -> float:
        try:
            _, _, rep = solve_pose(obj_xyz, img_uv, _at(fx), dist, cam_C)
        except Exception:  # a focal the solver cannot use is simply not the answer
            return float("inf")
        m = float(np.mean(rep))
        return m if np.isfinite(m) else float("inf")

    res = minimize_scalar(_cost, bounds=(fx0 * (1 - span), fx0 * (1 + span)),
                          method="bounded", options={"xatol": 0.01})
    # ★ Never return something WORSE than the seed: a bounded search on a badly
    #   conditioned scene can land off the true minimum, and silently degrading
    #   the answer would be the one outcome nobody could detect.
    best = _at(float(res.x)) if _cost(float(res.x)) <= _cost(fx0) else K
    R, C, rep = solve_pose(obj_xyz, img_uv, best, dist, cam_C)
    return R, C, rep, best


# <<< GEO-DRIFT-UPDATE C3 END <<<


def load_project(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if "fields" not in data or "points" not in data:
        raise ValueError("not a GUI project file (missing 'fields'/'points'): %s" % path)
    return data


def pose_from_project(project_path: str,
                      width: Optional[int] = None,
                      height: Optional[int] = None) -> CameraPose:
    """Read a GUI project and recover the camera pose from its GCPs."""
    data = load_project(project_path)
    f = data["fields"]

    def num(key: str, default: Optional[float] = None) -> float:
        raw = str(f.get(key, "")).strip()
        if raw == "":
            if default is None:
                raise ValueError("project field '%s' is empty" % key)
            return default
        return float(raw)

    K = np.array([[num("fx"), 0.0, num("cx")],
                  [0.0, num("fy"), num("cy")],
                  [0.0, 0.0, 1.0]])
    dist = np.array([num(k, 0.0) for k in ("k1", "k2", "p1", "p2", "k3")])
    C_entered = np.array([num("X0"), num("Y0"), num("Z0") + num("Zoff", 0.0)])

    W = int(width or num("img_w"))
    H = int(height or num("img_h"))

    pts = [p for p in data["points"]
           if p.get("u") is not None and p.get("X") is not None
           and p.get("Z") is not None and not p.get("excl")]
    if len(pts) < 4:
        raise ValueError("project has only %d usable GCPs (need >= 4)" % len(pts))

    obj = np.array([[p["X"], p["Y"], p["Z"]] for p in pts], float)
    img = np.array([[p["u"], p["v"]] for p in pts], float)
    R, C, rep = solve_pose(obj, img, K, dist, C_entered)

    axis = R.T @ _UP
    az = float(np.degrees(np.arctan2(axis[0], axis[1])) % 360.0)
    el = float(np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0))))

    return CameraPose(
        R=R, C=C, K=K, dist=dist, width=W, height=H,
        azimuth_deg=az, tilt_down_deg=-el, roll_deg=roll_from_R(R),
        reproj_mean_px=float(np.mean(rep)), reproj_max_px=float(np.max(rep)),
        n_gcps_used=len(pts),
        position_shift_m=float(np.linalg.norm(C - C_entered)),
    )
