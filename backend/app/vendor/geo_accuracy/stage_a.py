"""
Stage A - camera pose recovery (spatial resection / PnP) from Ground Control Points.

Pure numpy/cv2 - no GUI. Given GCPs (known world X,Y,Z <-> image u,v), the camera
intrinsics, and the camera position, this solves the camera ORIENTATION (and,
unless position is fixed, refines the position too).

The camera location and tilt the user enters are NOT used to constrain the solve.
They are only compared afterwards to the SOLVED values (see pose_errors) as an
independent accuracy / consistency check:
  * position_shift_m  - how far the solved camera moved from the entered location
  * tilt_diff_deg     - solved depression angle minus the entered tilt
A large value in either flags a calibration/GCP problem, exactly like a large
reprojection error does.
"""
import numpy as np
import cv2

_UP = np.array([0.0, 0.0, 1.0])


def rotation_from_angles(heading_deg, tilt_down_deg, roll_deg=0.0):
    """World->camera rotation (OpenCV axes: x right, y down, z forward) from
    heading (deg clockwise from north), tilt below horizontal, and roll
    (deg, positive = image rotates clockwise). World frame: X=east, Y=north, Z=up."""
    az, t, ro = np.radians([heading_deg, tilt_down_deg, roll_deg])
    f = np.array([np.sin(az) * np.cos(t), np.cos(az) * np.cos(t), -np.sin(t)])
    r0 = np.cross(f, _UP)
    n = np.linalg.norm(r0)
    if n < 1e-9:
        raise ValueError("tilt_down = +/-90 deg: heading undefined (camera pointing straight up/down)")
    r0 /= n
    d0 = np.cross(f, r0)                       # camera 'down' at zero roll
    r = np.cos(ro) * r0 + np.sin(ro) * d0      # apply roll about the optical axis
    d = np.cross(f, r)
    return np.stack([r, d, f])


def roll_from_R(R):
    """Roll (deg) of a world->camera rotation: angle of camera-x off the horizon."""
    f = R[2]
    r0 = np.cross(f, _UP)
    n = np.linalg.norm(r0)
    if n < 1e-9:
        return 0.0
    r0 /= n
    d0 = np.cross(f, r0)
    return float(np.degrees(np.arctan2(R[0] @ d0, R[0] @ r0)))


def _angdiff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def project_point(P, R, C, K, dist):
    """World point -> image pixel through the full distortion model.
    Returns (u, v) or None if the point is behind the camera."""
    P = np.asarray(P, float)
    C = np.asarray(C, float)
    if (R @ (P - C))[2] <= 0:
        return None
    rv = cv2.Rodrigues(np.asarray(R, float))[0]
    tv = (-np.asarray(R, float) @ C).reshape(3, 1)
    uv, _ = cv2.projectPoints(P.reshape(1, 1, 3), rv, tv,
                              np.asarray(K, float), np.asarray(dist, float))
    return float(uv[0, 0, 0]), float(uv[0, 0, 1])


def _refine_constrained(obj, img, K, dist, C0, h0, t0, r0, free_mask, iters=100,
                        free_focal=False):
    """Levenberg-Marquardt over the FREE subset of
    [heading, tilt, roll, X, Y, Z, fx] (angles in degrees, position in
    metres, focal in pixels); fixed entries stay at their input value.

    `free_focal` frees ONE focal scale: fy always follows fx at the entered
    fy/fx ratio. Solving fy independently is near-degenerate at grazing
    geometry - the ground occupies a narrow vertical band of the frame, so
    vertical focal trades off almost perfectly against tilt, and on real data
    fy ran off by tens of percent while the held-out error doubled. One
    shared scale is pinned by the wide horizontal spread instead. Principal
    point and distortion stay fixed. Returns the full 8-vector (index 7 =
    fy, recomputed from the solved fx)."""
    fy_ratio = float(K[1, 1]) / float(K[0, 0])
    p_full = np.array([h0, t0, r0, C0[0], C0[1], C0[2], K[0, 0], K[1, 1]], float)
    mask = np.concatenate([np.asarray(free_mask, bool), [free_focal, False]])
    idx = np.where(mask)[0]
    if idx.size == 0:          # everything fixed: nothing to optimize
        return p_full
    obj_r = obj.reshape(-1, 1, 3)

    def resid(pv):
        q = p_full.copy()
        q[idx] = pv
        Kq = np.asarray(K, float).copy()
        Kq[0, 0], Kq[1, 1] = q[6], q[6] * fy_ratio
        R = rotation_from_angles(q[0], q[1], q[2])
        rv = cv2.Rodrigues(R)[0]
        tv = (-R @ q[3:6]).reshape(3, 1)
        uv, _ = cv2.projectPoints(obj_r, rv, tv, Kq, dist)
        return (uv.reshape(-1, 2) - img).ravel()

    steps = np.array([1e-4, 1e-4, 1e-4, 1e-3, 1e-3, 1e-3, 1e-2, 1e-2])[idx]
    pv = p_full[idx].copy()
    f = resid(pv)
    cost = float(f @ f)
    lam = 1e-3
    for _ in range(iters):
        J = np.empty((f.size, pv.size))
        for j in range(pv.size):
            d = np.zeros_like(pv)
            d[j] = steps[j]
            J[:, j] = (resid(pv + d) - f) / steps[j]
        A = J.T @ J
        g = J.T @ f
        moved = small = False
        for _ in range(12):
            try:
                dp = np.linalg.solve(A + lam * (np.diag(np.diag(A)) + 1e-12 * np.eye(len(pv))), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            f2 = resid(pv + dp)
            c2 = float(f2 @ f2)
            if c2 <= cost:
                small = (cost - c2) < 1e-12 * max(cost, 1.0) or float(np.max(np.abs(dp))) < 1e-10
                pv, f, cost = pv + dp, f2, c2
                lam = max(lam * 0.3, 1e-9)
                moved = True
                break
            lam *= 10
        if not moved or small:
            break
    p_full[idx] = pv
    p_full[7] = p_full[6] * fy_ratio        # fy follows the solved fx
    return p_full


def solve_pose(obj_xyz, img_uv, K, dist, cam_C, fix_position=False,
               fixed_heading=None, fixed_tilt=None, fixed_roll=None,
               free_focal=False):
    """Return dict(R, C, K, reproj[], azimuth, elevation, tilt_down, roll).

    obj_xyz : (N,3) world coordinates of the GCPs (metres, projected CRS)
    img_uv  : (N,2) their pixel coordinates
    K, dist : intrinsics matrix (3x3) and distortion [k1,k2,p1,p2,k3]
    cam_C   : (3,) entered camera position (X0,Y0,Z0+Zoff)
    fix_position : if True, keep C = cam_C and solve rotation only
    fixed_heading : if not None, clamp heading (deg cw from N) to this value
    fixed_tilt    : if not None, clamp tilt below horizontal (deg) to this value
    fixed_roll    : if not None, clamp roll (deg) to this value
    free_focal    : if True, also solve ONE focal scale - fy follows fx at
                    the entered ratio (principal point and distortion stay
                    fixed). The returned dict's "K" carries the solved
                    values - callers must use THAT K for any raycasting/
                    projection, not the K they passed in.
    Any combination of the constraints is allowed; the solver estimates
    whatever remains free (with everything fixed, it just evaluates the pose).
    """
    obj = np.asarray(obj_xyz, float)
    img = np.asarray(img_uv, float)
    C = np.asarray(cam_C, float)
    dist = np.asarray(dist, float)
    K_out = np.asarray(K, float).copy()

    if free_focal or fixed_heading is not None or fixed_tilt is not None or fixed_roll is not None:
        # start from the unconstrained (or position-fixed) solution, then clamp
        try:
            init = solve_pose(obj_xyz, img_uv, K, dist, cam_C, fix_position=fix_position)
            h0, t0, r0 = init["azimuth"], init["tilt_down"], init["roll"]
            C0 = np.asarray(init["C"], float)
        except Exception:
            h0, t0, r0, C0 = 0.0, 0.0, 0.0, C.copy()
        if fixed_heading is not None:
            h0 = float(fixed_heading)
        if fixed_tilt is not None:
            t0 = float(fixed_tilt)
        if fixed_roll is not None:
            r0 = float(fixed_roll)
        if fix_position:
            C0 = C.copy()
        free = np.array([fixed_heading is None, fixed_tilt is None, fixed_roll is None,
                         not fix_position, not fix_position, not fix_position])
        p = _refine_constrained(obj, img, K, dist, C0, h0, t0, r0, free,
                                free_focal=free_focal)
        R = rotation_from_angles(p[0], p[1], p[2])
        Cc = p[3:6].copy()
        K_out[0, 0], K_out[1, 1] = p[6], p[7]
    elif fix_position:
        wd = obj - C
        wd = wd / np.linalg.norm(wd, axis=1, keepdims=True)
        if np.any(dist != 0):
            cd = cv2.undistortPoints(img.reshape(-1, 1, 2), K, dist).reshape(-1, 2)
            cd = np.hstack([cd, np.ones((len(cd), 1))])
        else:
            cd = np.stack([(img[:, 0] - K[0, 2]) / K[0, 0],
                           (img[:, 1] - K[1, 2]) / K[1, 1],
                           np.ones(len(img))], axis=1)
        cd = cd / np.linalg.norm(cd, axis=1, keepdims=True)
        Hm = cd.T @ wd
        U, S, Vt = np.linalg.svd(Hm)
        R = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
        Cc = C.copy()
    else:
        ok, rv, tv = cv2.solvePnP((obj - C).reshape(-1, 1, 3), img.reshape(-1, 1, 2),
                                  K, dist, flags=cv2.SOLVEPNP_SQPNP)
        if not ok:
            raise RuntimeError("solvePnP failed")
        rv, tv = cv2.solvePnPRefineLM((obj - C).reshape(-1, 1, 3), img.reshape(-1, 1, 2),
                                      K, dist, rv, tv)
        R = cv2.Rodrigues(rv)[0]
        Cc = C - R.T @ tv.reshape(3)

    # residuals through the FULL distortion model (same model the solve used;
    # a pinhole-only reprojection here would misreport corner points by several
    # px whenever k/p coefficients are non-zero). K_out, not K: with
    # free_focal the pose was fitted with the SOLVED focal, and residuals
    # against the entered one would misstate the fit.
    rep = np.full(len(obj), 1e9)
    in_front = ((obj - Cc) @ R[2]) > 0
    if np.any(in_front):
        rv_ = cv2.Rodrigues(R)[0]
        tv_ = (-R @ Cc).reshape(3, 1)
        uv_, _ = cv2.projectPoints(obj[in_front].reshape(-1, 1, 3), rv_, tv_, K_out, dist)
        rep[in_front] = np.linalg.norm(uv_.reshape(-1, 2) - img[in_front], axis=1)

    axis = R.T @ np.array([0, 0, 1.0])           # optical axis in world frame
    az = np.degrees(np.arctan2(axis[0], axis[1])) % 360.0
    el = np.degrees(np.arcsin(np.clip(axis[2], -1, 1)))
    return dict(R=R, C=Cc, K=K_out, reproj=rep, azimuth=az, elevation=el,
                tilt_down=-el, roll=roll_from_R(R),
                position_shift=float(np.linalg.norm(Cc - C)))


def pose_errors(result, cam_C, entered_tilt_down=None, entered_heading=None, entered_roll=None):
    """Diagnostic errors comparing the SOLVED pose to what the user entered."""
    out = {
        "reproj_mean_px": float(np.mean(result["reproj"])),
        "reproj_max_px": float(np.max(result["reproj"])),
        "position_shift_m": float(np.linalg.norm(np.asarray(result["C"]) - np.asarray(cam_C))),
    }
    if entered_tilt_down is not None:
        out["tilt_solved_deg"] = float(result["tilt_down"])
        out["tilt_entered_deg"] = float(entered_tilt_down)
        out["tilt_diff_deg"] = float(result["tilt_down"] - entered_tilt_down)
    if entered_heading is not None:
        out["heading_solved_deg"] = float(result["azimuth"])
        out["heading_entered_deg"] = float(entered_heading)
        out["heading_diff_deg"] = float(_angdiff(result["azimuth"], entered_heading))
    if entered_roll is not None:
        out["roll_solved_deg"] = float(result["roll"])
        out["roll_entered_deg"] = float(entered_roll)
        out["roll_diff_deg"] = float(_angdiff(result["roll"], entered_roll))
    return out
