r"""Camera drift monitor - standalone, engine-agnostic.

Detects that a FIXED camera has moved, which is the failure mode that
silently invalidates any frozen pixel->world mapping: nothing crashes, no
error appears, the system simply keeps reporting confident coordinates that
are now wrong.

Dependencies: numpy and opencv-python. Nothing else. This file does not
import from any geolocation package - the host supplies its own pixel->world
function at setup, so the monitor works on top of ANY geolocation engine
(PnP, affine/PTZ, lookup table, homography, whatever).

HOW IT WORKS
    setup()  while the mapping is trusted: pick textured landmark patches
             spread over the frame, and record each one's WORLD position by
             asking the host's own engine. The landmarks become synthetic
             control points.
    check()  on a later frame: re-find each landmark by normalised
             cross-correlation, re-solve the camera ROTATION from
             (stored world XYZ, fresh pixel) pairs, and compare to the
             reference rotation.

Rotation only, position held fixed: a rigidly mounted camera rotates - a
knock, a thermal-warped mast, a loosening bolt - it does not translate.
Fixing the position makes the solve a closed-form Wahba/Kabsch SVD: no
iteration, no initial guess, microseconds per check.

FOUR STATES - collapsing any of them into OK is how a monitor lies:
    OK        landmarks matched; any rigid rotation is below threshold
    MOVED     coherent rotation above threshold -> re-aim or re-solve
    CHANGED   landmarks moved but NO rigid rotation explains the field:
              zoom, focus/focal change, translated mount, swapped lens.
              The mapping is broken even though the camera did not rotate.
    DEGRADED  too few or too weak matches (fog, night, scene change) ->
              the monitor cannot tell, and says so rather than guessing

MOVED and CHANGED both mean "stop trusting the coordinates"; they are kept
apart because the remedy differs (re-aim vs full re-solve).

WHAT IT CANNOT DO
  * It measures CHANGE from the reference, never CORRECTNESS. If the mapping
    was wrong when setup() ran, this reports OK forever. Pair it with an
    absolute check (ground truth points, or matching against satellite
    imagery) - the two cover different failure modes.
  * Digital image stabilisation is geometrically indistinguishable from a
    small pan/tilt. It is reported as MOVED, which is the right verdict (the
    mapping IS broken) even though the attributed cause may be wrong.
  * It never repairs the pose. Adopting its own corrected rotation would
    create a feedback loop: the landmarks' world positions came from the
    reference mapping, so re-anchoring to them lets the reference drift with
    nothing holding it. Detect, report, and let a human or an absolute check
    decide.
"""
from __future__ import annotations

import json
import os
from collections import deque

import numpy as np
import cv2

__version__ = "1.0.0"

OK, MOVED, CHANGED, DEGRADED = "OK", "MOVED", "CHANGED", "DEGRADED"


class DriftMonitor:
    """Watch one camera. Construct once, setup() once, check() forever.

    K            3x3 intrinsics of the camera the frames come from
    dist         optional 5-vector [k1,k2,p1,p2,k3]; None means no distortion
    ref_range    metres; the range at which the alert threshold is stated
    alert_ground_m  fire above this much ground error at ref_range
    confirm_n    consecutive identical non-OK verdicts before .status changes
                 (kills transients: a bird on the housing, a gust, autofocus)
    """

    # tuning - defaults validated on 4032x2268 frames at f~2800 px
    PATCH = 48          # landmark template side, px
    SEARCH = 40         # search half-window around the stored pixel, px
    MIN_CONF = 0.60     # NCC peak below this = landmark not found
    MIN_INLIERS = 5     # absolute floor on surviving landmarks
    INLIER_FRAC = 0.6   # ...and strictly more than half of those picked
    MIN_MEAN_CONF = 0.70    # mean NCC of survivors
    CULL_FACTOR = 3.0   # residual > this x median = outlier, dropped
    MIN_SNR = 2.0       # claimed pixel shift vs landmark disagreement
    RESID_FLOOR = 1.5   # px of disagreement worth reacting to at all

    def __init__(self, K, dist=None, ref_range=1000.0, alert_ground_m=1.0,
                 confirm_n=3):
        self.K = np.asarray(K, float).reshape(3, 3)
        self.dist = None if dist is None else np.asarray(dist, float).ravel()
        self.ref_range = float(ref_range)
        self.alert_ground_m = float(alert_ground_m)
        self.confirm_n = int(confirm_n)
        self.landmarks = []
        self.R_ref = None
        self.C = None
        self.frame_shape = None
        self._recent = deque(maxlen=max(1, self.confirm_n))
        self.status = None          # confirmed state, after the temporal filter
        self.last = None            # raw dict from the most recent check()

    # ------------------------------------------------------------------ setup
    def setup(self, gray, world_of, C, R_ref, n=12, grid=(4, 3)):
        """Freeze the reference. Call while the mapping is known good.

        gray      grayscale reference frame, uint8 (H, W)
        world_of  callable (u, v) -> (X, Y, Z) or None. The HOST's engine.
                  Must return metric world coordinates in the same frame as C.
        C         camera position (X, Y, Z), metric, same frame as world_of
        R_ref     3x3 world->camera rotation of the trusted pose. Rows are the
                  camera right/down/forward axes in world coordinates.
        n         how many landmarks to keep
        grid      (cols, rows) quota cells, so one busy region cannot supply
                  every landmark - this also mixes near and far ranges, which
                  is what separates rotation from residual translation effects

        Returns the number of landmarks stored. Fewer than MIN_INLIERS means
        the scene is too featureless to monitor; treat that as a setup error.
        """
        gray = self._as_gray(gray)
        H, W = gray.shape[:2]
        self.frame_shape = (H, W)
        self.C = np.asarray(C, float).ravel()
        self.R_ref = np.asarray(R_ref, float).reshape(3, 3)

        m = self.PATCH // 2 + self.SEARCH + 2
        corners = cv2.goodFeaturesToTrack(gray, 600, 0.02, 25)
        corners = [] if corners is None else corners.reshape(-1, 2)
        cells = {}
        for u, v in corners:
            if not (m <= u < W - m and m <= v < H - m):
                continue
            cells.setdefault((int(u * grid[0] / W), int(v * grid[1] / H)),
                             []).append((float(u), float(v)))

        lms, h = [], self.PATCH // 2
        depth = max((len(c) for c in cells.values()), default=0)
        for rank in range(depth):                 # round-robin over cells
            for key in sorted(cells):
                if len(lms) >= n:
                    break
                cell = cells[key]
                if rank >= len(cell):
                    continue
                u, v = cell[rank]
                P = world_of(u, v)
                if P is None:
                    continue
                t = gray[int(v) - h:int(v) + h, int(u) - h:int(u) + h].astype(np.float32)
                if t.std() < 4.0:                 # flat patch: NCC meaningless
                    continue
                P = np.asarray(P, float).ravel()
                lms.append(dict(u=u, v=v, X=float(P[0]), Y=float(P[1]), Z=float(P[2]),
                                range=float(np.hypot(P[0] - self.C[0], P[1] - self.C[1])),
                                template=t))
            if len(lms) >= n:
                break
        self.landmarks = lms
        self._recent.clear()
        self.status = None
        return len(lms)

    # ------------------------------------------------------------------ check
    def check(self, gray):
        """One monitoring pass over a fresh frame. Returns the verdict dict.

        Cheap: N template matches plus one SVD. No DEM or terrain model is
        needed here - the landmarks already carry their world positions - so
        this runs on a field unit that has no elevation data at all.
        """
        if not self.landmarks:
            raise RuntimeError("call setup() before check()")
        gray = self._as_gray(gray)
        if self.frame_shape and gray.shape[:2] != self.frame_shape:
            raise ValueError("frame is %s but the reference was %s - the monitor "
                             "compares pixel positions, so the size must match"
                             % (gray.shape[:2], self.frame_shape))

        found, lost = [], 0
        for lm in self.landmarks:
            loc = self._locate(gray, lm)
            if loc is None:
                lost += 1
            else:
                found.append((lm, loc))

        out = dict(n_landmarks=len(self.landmarks), n_matched=len(found),
                   n_lost=lost, outlier_ids=[])
        need = max(self.MIN_INLIERS, int(np.ceil(self.INLIER_FRAC * len(self.landmarks))))
        if len(found) < need:
            out.update(state=DEGRADED,
                       why="only %d of %d landmarks found (need %d) - fog, night "
                           "or a changed scene; cannot judge the camera"
                           % (len(found), len(self.landmarks), need))
            return self._finish(out)

        # rotation-only re-solve with iterative culling: one MOVED OBJECT (a
        # parked truck, a felled tree) is a single large residual and is
        # dropped; a MOVED CAMERA shifts every landmark coherently and survives
        live = list(found)
        while True:
            obj = np.array([[lm["X"], lm["Y"], lm["Z"]] for lm, _ in live])
            img = np.array([[loc[0], loc[1]] for _, loc in live])
            R = self._solve_rotation(obj, img)
            r = self._reproj(R, obj, img)
            med = float(np.median(r))
            worst = int(np.argmax(r))
            if len(live) > self.MIN_INLIERS and r[worst] > self.CULL_FACTOR * max(med, 0.5):
                out["outlier_ids"].append(int(worst))
                live.pop(worst)
                continue
            break

        dR = R @ self.R_ref.T
        ang = float(np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1))))
        ground = float(np.radians(ang) * self.ref_range)
        resid = float(np.mean(r))
        conf = float(np.mean([loc[2] for _, loc in live]))
        f = 0.5 * (self.K[0, 0] + self.K[1, 1])
        claimed = float(np.radians(ang) * f)
        snr = claimed / max(resid, 0.5)
        out.update(n_inliers=len(live), rot_deg=ang, ground_err_at_ref=ground,
                   resid_mean_px=resid, mean_conf=conf, claimed_px=claimed,
                   snr=float(snr), R_now=R.tolist())

        if len(live) < need:
            out.update(state=DEGRADED,
                       why="only %d of %d landmarks agree after culling (need %d)"
                           % (len(live), len(self.landmarks), need))
        elif conf < self.MIN_MEAN_CONF:
            out.update(state=DEGRADED,
                       why="matches are weak (mean NCC %.2f < %.2f) - degraded "
                           "view; any drift figure would be match noise"
                           % (conf, self.MIN_MEAN_CONF))
        elif resid > self.RESID_FLOOR and snr < self.MIN_SNR:
            out.update(state=CHANGED,
                       why="landmarks moved %.1f px on average but no rigid "
                           "rotation explains it (rotation accounts for only "
                           "%.1f px, SNR %.1f) - suspect zoom, focus/focal "
                           "change, a shifted mount or a swapped lens; the "
                           "mapping needs re-solving, not re-aiming"
                           % (resid, claimed, snr))
        elif ground > self.alert_ground_m:
            out.update(state=MOVED,
                       why="camera rotated %.3f deg = %.2f m of ground error at "
                           "%.0f m (threshold %.2f m); %d/%d landmarks agree, "
                           "SNR %.1f" % (ang, ground, self.ref_range,
                                         self.alert_ground_m, len(live),
                                         len(self.landmarks), snr))
        else:
            out.update(state=OK,
                       why="drift %.3f deg = %.2f m at %.0f m, below the %.2f m "
                           "threshold" % (ang, ground, self.ref_range,
                                          self.alert_ground_m))
        return self._finish(out)

    # ------------------------------------------------------------- persistence
    def save(self, path):
        """One .npz holding the templates and everything needed to resume."""
        meta = dict(version=__version__, K=self.K.tolist(),
                    dist=None if self.dist is None else self.dist.tolist(),
                    ref_range=self.ref_range, alert_ground_m=self.alert_ground_m,
                    confirm_n=self.confirm_n, C=self.C.tolist(),
                    R_ref=self.R_ref.tolist(), frame_shape=list(self.frame_shape),
                    landmarks=[{k: v for k, v in lm.items() if k != "template"}
                               for lm in self.landmarks])
        np.savez_compressed(
            path, meta=json.dumps(meta),
            templates=np.stack([lm["template"] for lm in self.landmarks])
            if self.landmarks else np.zeros((0, self.PATCH, self.PATCH), np.float32))
        return path

    @classmethod
    def load(cls, path):
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        m = cls(meta["K"], meta["dist"], meta["ref_range"],
                meta["alert_ground_m"], meta["confirm_n"])
        m.C = np.array(meta["C"], float)
        m.R_ref = np.array(meta["R_ref"], float)
        m.frame_shape = tuple(meta["frame_shape"])
        tpl = z["templates"]
        m.landmarks = [dict(lm, template=tpl[i]) for i, lm in enumerate(meta["landmarks"])]
        return m

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _as_gray(frame):
        a = np.asarray(frame)
        if a.ndim == 3:
            a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        return a

    def _locate(self, gray, lm):
        H, W = gray.shape[:2]
        h, S = self.PATCH // 2, self.SEARCH
        u0, v0 = int(lm["u"]), int(lm["v"])
        x0, x1 = max(0, u0 - h - S), min(W, u0 + h + S)
        y0, y1 = max(0, v0 - h - S), min(H, v0 + h + S)
        win = gray[y0:y1, x0:x1].astype(np.float32)
        if win.shape[0] < self.PATCH or win.shape[1] < self.PATCH:
            return None
        sc = cv2.matchTemplate(win, lm["template"], cv2.TM_CCOEFF_NORMED)
        _, conf, _, loc = cv2.minMaxLoc(sc)
        if not np.isfinite(conf) or conf < self.MIN_CONF:
            return None
        return (x0 + loc[0] + h, y0 + loc[1] + h, float(conf))

    def _bearings(self, img_uv):
        """Pixels -> unit bearings in the camera frame."""
        uv = np.asarray(img_uv, float).reshape(-1, 1, 2)
        if self.dist is not None and np.any(self.dist != 0):
            n = cv2.undistortPoints(uv, self.K, self.dist).reshape(-1, 2)
        else:
            n = np.column_stack([(uv[:, 0, 0] - self.K[0, 2]) / self.K[0, 0],
                                 (uv[:, 0, 1] - self.K[1, 2]) / self.K[1, 1]])
        b = np.column_stack([n, np.ones(len(n))])
        return b / np.linalg.norm(b, axis=1, keepdims=True)

    def _solve_rotation(self, obj_xyz, img_uv):
        """Wahba's problem, closed form (Kabsch/Umeyama). Position is fixed,
        so only the rotation is free: maximise sum(c_i . R w_i)."""
        w = np.asarray(obj_xyz, float) - self.C
        w = w / np.linalg.norm(w, axis=1, keepdims=True)
        c = self._bearings(img_uv)
        U, _, Vt = np.linalg.svd(c.T @ w)
        d = np.sign(np.linalg.det(U @ Vt))          # reject reflections
        return U @ np.diag([1.0, 1.0, d]) @ Vt

    def _reproj(self, R, obj_xyz, img_uv):
        rv = cv2.Rodrigues(R)[0]
        tv = (-R @ self.C).reshape(3, 1)
        d = np.zeros(5) if self.dist is None else self.dist
        uv, _ = cv2.projectPoints(np.asarray(obj_xyz, float).reshape(-1, 1, 3),
                                  rv, tv, self.K, d)
        return np.linalg.norm(uv.reshape(-1, 2) - np.asarray(img_uv, float), axis=1)

    def _finish(self, out):
        """Temporal confirmation: a non-OK state must repeat confirm_n times
        before .status follows it. OK takes effect immediately - being quick
        to trust again is safe, being quick to alarm is not."""
        self.last = out
        self._recent.append(out["state"])
        if out["state"] == OK:
            self.status = OK
        elif (len(self._recent) == self._recent.maxlen
              and len(set(self._recent)) == 1):
            self.status = out["state"]
        out["status"] = self.status
        out["confirmed"] = (self.status == out["state"] and out["state"] != OK)
        return out
