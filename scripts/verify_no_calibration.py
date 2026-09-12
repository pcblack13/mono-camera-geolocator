#!/usr/bin/env python3
"""Does "no calibration" really work? Cross-validate it against a surveyed scene.

    python3 scripts/verify_no_calibration.py <project.geoproj>

★ WHY THIS IS IN THE REPO. `no_calibration` solves the camera's focal from the
  GCPs instead of trusting an entered calibration, and that is a claim about
  accuracy — the kind that must be measurable rather than asserted. This script
  measures it the way the claim was originally made: 10 repeats of 5-fold
  cross-validation, every configuration on the SAME folds so the comparisons are
  paired, held-out pixels raycast through the solved pose and the DEM and scored
  against their surveyed positions.

★ IT USES THE APP'S OWN SOLVER (`app.vendor.lut_generator`), not a
  re-implementation. That is the point: it tells you whether THIS build behaves,
  not whether the idea is sound in general.

★ Expects a `.geoproj` laid out as the desktop GUI writes one:
      inputs/gcps/gcps.csv          id,u,v,X,Y,Z,excluded
      inputs/calibration/*.csv      fx,fy,cx,cy,k1..k3,p1,p2
      inputs/camera/*.csv           X0,Y0,Z0,Zoff
      inputs/dtm/*.tif              metric CRS
  Reference figures for Yammouneh 200 m / DJI_0124 are in that project's own
  `outputs/calibration_study/results_table.txt`.
"""
import csv, sys, json, numpy as np
sys.path.insert(0, "/home/pcwhite/project/GEO-1/tools/mono-camera-geolocator/backend")
from app.vendor.lut_generator.pose import solve_pose, solve_pose_free_focal
from app.vendor.lut_generator.dem import DEM
from app.vendor.lut_generator.raycast import raycast_batch

import glob
import os

if len(sys.argv) < 2:
    sys.exit(__doc__.strip() + "\n\nerror: give the path to a .geoproj folder.")
P = os.path.abspath(sys.argv[1])
if not os.path.isdir(f"{P}/inputs"):
    sys.exit(f"error: {P} has no inputs/ — is it a .geoproj folder?")


def _kv(pattern):
    """The GUI's two-column `key,value` files (comments start with #)."""
    hits = glob.glob(pattern)
    if not hits:
        sys.exit(f"error: nothing matches {pattern}")
    out = {}
    for line in open(hits[0], encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        k, v = line.split(",", 1)
        try:
            out[k.strip()] = float(v.strip())
        except ValueError:
            pass
    return out


cal = _kv(f"{P}/inputs/calibration/*.csv")
cam = _kv(f"{P}/inputs/camera/*.csv")
W, H = int(cal["img_w"]), int(cal["img_h"])
C_SEED = np.array([cam["X0"], cam["Y0"], cam["Z0"] + cam.get("Zoff", 0.0)])

rows = [r for r in csv.DictReader(open(f"{P}/inputs/gcps/gcps.csv"))
        if r.get("excluded", "0").strip() != "1"]
OBJ = np.array([[float(r["X"]), float(r["Y"]), float(r["Z"])] for r in rows])
IMG = np.array([[float(r["u"]), float(r["v"])] for r in rows])
N = len(rows)
tifs = glob.glob(f"{P}/inputs/dtm/*.tif") or glob.glob(f"{P}/inputs/dem/*.tif")
if not tifs:
    sys.exit(f"error: no DTM .tif under {P}/inputs/dtm/")
dem = DEM(tifs[0])

CAL_K = np.array([[cal["fx"], 0, cal["cx"]], [0, cal["fy"], cal["cy"]], [0, 0, 1.0]])
# ★ The study's "radial zeroed" row: keep the tangential terms, zero the radial.
D_TANG = np.array([0.0, 0.0, cal.get("p1", 0.0), cal.get("p2", 0.0), 0.0])
# ★ And the entered radial, to price what loading it costs. Bending the frame
#   border by hundreds of pixels is physically impossible on a DJI JPEG, which is
#   distortion-corrected in-camera — this row exists to show the damage.
D_BAD = np.array([cal.get("k1", 0.0), cal.get("k2", 0.0),
                  cal.get("p1", 0.0), cal.get("p2", 0.0), cal.get("k3", 0.0)])
def K_fov(fov):
    fx = (W / 2) / np.tan(np.radians(fov) / 2)
    return np.array([[fx, 0, W / 2.0], [0, fx, H / 2.0], [0, 0, 1.0]])

CONFIGS = {
    "calib":       dict(K=CAL_K, dist=D_TANG, free=False),
    "nocal":       dict(K=K_fov(70.0), dist=np.zeros(5), free=True),
    "nocal_fov60": dict(K=K_fov(60.0), dist=np.zeros(5), free=True),
}
# ★ ONLY PRICE THE RADIAL TERMS IF THERE ARE ANY. A project that ships the
#   radial-ZEROED calibration has nothing to compare against, and running the row
#   anyway would silently duplicate the `calib` row — a configuration that looks
#   tested and is not. Say it is absent instead.
if np.any(D_BAD[[0, 1, 4]]):
    CONFIGS["calib_radial"] = dict(K=CAL_K, dist=D_BAD, free=False)
else:
    print("  note: this calibration carries no radial terms (k1=k2=k3=0), so the\n"
          "        'what the bad radial costs' row is skipped — there is nothing to price.\n")

import cv2
from scipy.optimize import minimize_scalar

def _rotation_only(obj, img, K, d, C):
    """Position FIXED: solve the ROTATION alone, with C held at the GPS seed.

    ★ Solving freely and then MOVING the camera to the seed is not the same
      thing and is much worse — the rotation was fitted for a different centre.
      This is Wahba's problem (Kabsch): pixels -> bearings, world points ->
      directions from the fixed C, one SVD for the rotation that best aligns them.
    """
    uv = np.asarray(img, float).reshape(-1, 1, 2)
    if np.any(d):
        n = cv2.undistortPoints(uv, K, np.asarray(d, float)).reshape(-1, 2)
    else:
        n = np.column_stack([(uv[:, 0, 0] - K[0, 2]) / K[0, 0],
                             (uv[:, 0, 1] - K[1, 2]) / K[1, 1]])
    c = np.column_stack([n, np.ones(len(n))])
    c /= np.linalg.norm(c, axis=1, keepdims=True)
    w = np.asarray(obj, float) - C
    w /= np.linalg.norm(w, axis=1, keepdims=True)
    U, _, Vt = np.linalg.svd(c.T @ w)
    R = U @ np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))]) @ Vt
    uvp, _ = cv2.projectPoints(np.asarray(obj, float).reshape(-1, 1, 3),
                               cv2.Rodrigues(R)[0], (-R @ C).reshape(3, 1), K,
                               np.asarray(d, float))
    rep = np.linalg.norm(uvp.reshape(-1, 2) - np.asarray(img, float), axis=1)
    return R, rep


def fit(cfg, idx, fixpos):
    """Solve on the training subset. fixpos: C stays at the GPS seed."""
    K, d, free = cfg["K"], cfg["dist"], cfg["free"]
    obj, img = OBJ[idx], IMG[idx]
    if fixpos:
        if free:
            fx0, ratio = float(K[0, 0]), float(K[1, 1]) / float(K[0, 0])
            def at(fx):
                Kf = K.copy(); Kf[0, 0] = fx; Kf[1, 1] = fx * ratio; return Kf
            def cost(fx):
                try:
                    return float(np.mean(_rotation_only(obj, img, at(fx), d, C_SEED)[1]))
                except Exception:
                    return 1e9
            r = minimize_scalar(cost, bounds=(fx0 * 0.55, fx0 * 1.45),
                                method="bounded", options={"xatol": 0.01})
            K = at(float(r.x))
        R, rep = _rotation_only(obj, img, K, d, C_SEED)
        return R, C_SEED, K, d, float(np.mean(rep[np.isfinite(rep)]))
    if free:
        R, C, rep, K = solve_pose_free_focal(obj, img, K, d, C_SEED)
    else:
        R, C, rep = solve_pose(obj, img, K, d, C_SEED)
    return R, C, K, d, float(np.mean(rep[np.isfinite(rep)]))

def predict(R, C, K, d, idx):
    """Held-out pixels -> ground XY, and the errors the study reports."""
    xyz = raycast_batch(IMG[idx, 0], IMG[idx, 1], R, C, K, d, dem)
    truth = OBJ[idx]
    ok = np.isfinite(xyz[:, 0])
    err = np.full(len(idx), np.nan)
    err[ok] = np.linalg.norm(xyz[ok, :2] - truth[ok, :2], axis=1)
    # cross-track: bearing error x range — pointing only, no DTM in it
    xt = np.full(len(idx), np.nan)
    if ok.any():
        vp, vt = xyz[ok, :2] - C[:2], truth[ok, :2] - C[:2]
        rng = np.linalg.norm(vt, axis=1)
        cross = np.abs(vp[:, 0] * vt[:, 1] - vp[:, 1] * vt[:, 0]) / np.maximum(rng, 1e-9)
        xt[ok] = cross
    return err, xt

REPEATS, FOLDS = 10, 5
rng = np.random.default_rng(20260904)
folds = []
for _ in range(REPEATS):
    order = rng.permutation(N)
    folds += [(np.setdiff1d(order, order[i::FOLDS]), order[i::FOLDS]) for i in range(FOLDS)]
print(f"  {N} GCPs, {len(folds)} folds ({REPEATS} repeats x {FOLDS}-fold), same folds for every config\n")

out = {}
for fixpos in (True, False):
    for name, cfg in CONFIGS.items():
        errs, xts, failed = [], [], 0
        for tr, te in folds:
            try:
                R, C, K, d, _ = fit(cfg, tr, fixpos)
                e, x = predict(R, C, K, d, te)
            except Exception:
                failed += 1
                continue
            errs.append(e); xts.append(x)
        e = np.concatenate(errs); x = np.concatenate(xts)
        e = e[np.isfinite(e)]; x = x[np.isfinite(x)]
        R, C, K, d, rep = fit(cfg, np.arange(N), fixpos)   # full-data fit, for reproj/fx
        fov = 2 * np.degrees(np.arctan(W / (2 * K[0, 0])))
        key = f"{name}|{'fixpos' if fixpos else 'freepos'}"
        out[key] = dict(n=int(e.size), failed=failed, reproj=rep, fx=float(K[0, 0]), fov_h=fov,
                        med=float(np.median(e)), mean=float(e.mean()),
                        rmse=float(np.sqrt((e**2).mean())), p90=float(np.percentile(e, 90)),
                        xtrack=float(np.median(x)))
        # keep the per-point errors for the paired tests
        out[key]["_e"] = e.tolist()
        print(f"  {key:24s} n={out[key]['n']:4d} reproj {rep:6.2f}px  fx {K[0,0]:8.2f}  "
              f"fov_h {fov:6.3f}  median {out[key]['med']:5.2f} m  mean {out[key]['mean']:5.2f}  "
              f"p90 {out[key]['p90']:5.2f}")
json.dump(out, open("cv_results.json", "w"))
print("\n  wrote cv_results.json  (per-point errors under each config's '_e')")
