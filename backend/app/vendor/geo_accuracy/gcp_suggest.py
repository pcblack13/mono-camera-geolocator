r"""Where should the next control point go?

Scores candidate pixels across the frame and returns a few ranked REGIONS,
each with the reason it was chosen.

THE CRITERION
-------------
Both criteria start from the same object: the pose information matrix

    M = J'J          J = d(pixel) / d(rvec, tvec),  from cv2.projectPoints

and from the fact that adding one correspondence appends a 2x6 block A, so
M -> M + A'A.  The matrix determinant lemma and the Woodbury identity then
give the effect of that new point without refactorising anything.

  "ground"  (default)  How many metres of predicted error would a point here
            remove FROM THE PLACES THAT ARE ACTUALLY WRONG?  The pose
            covariance is M^-1, so the predicted pixel variance at an
            evaluation point with Jacobian B is tr(B M^-1 B'), and R/f turns
            that into metres on the ground.  Sum it over the evaluation set
            and a candidate is scored by the fraction it removes:

                dV = sum_j c_j tr(U_j S^-1 U_j'),  U_j = B_j M^-1 A',
                                                   S   = I2 + A M^-1 A'

            When a Stage D error map exists the evaluation set IS the locked
            tiles, weighted by the TANGENTIAL error measured at each - which
            is the whole point, because a GCP corrects the pose and cannot
            correct the DEM.  Scoring on total error would send the user to
            click where the error is radial, i.e. terrain height, and nothing
            would improve.

  "dopt"    Plain D-optimality, dlogdet = logdet(I2 + A M^-1 A').  Shrink the
            pose uncertainty ellipsoid as a whole, with no opinion about
            where accuracy is wanted.  Computed and reported either way.

Why the default is "ground": the translation block of the Jacobian scales as
f/Z, so D-optimality is dominated by whatever is nearest the camera and parks
every suggestion at the bottom of the frame.  That is not wrong - near points
really do pin the camera position best - but a far point is almost pure
rotation information, and rotation is what a far-field query needs.  Measured
on 113_100m, held out against 44 surveyed points: ranking by D-optimality put
every suggestion inside 130 m, while the point that actually helped most sat
at 1127 m.

TWO GATES
---------
Whatever the criterion, it is multiplied by two bounded [0,1] gates, so a
region has to be usable and not only informative:

  click   local image texture, saturating at the scene median.  A road
          junction or a wall corner is clickable to the pixel, an empty field
          is not - and a region nobody can click precisely is bad advice
          however informative it is.
  ground  DEM slope.  A GCP's world coordinate is read off the DEM, so on a
          slope the "truth" is itself wrong.  The flat-ground rule written as
          a weight rather than left as a rule of thumb.

Regions are then picked greedily with a minimum separation, so the answer is
several different places to look rather than five spots in one corner.

With only 4 points M is 6x6 built from 8 equations - barely invertible - so it
is regularised.  An earlier version also blended plain geometric spread into
the score until 8 points were placed; that was dropped after measurement.
Against the 44-point hold-out, spread alone predicted the truth at rank
correlation -0.54 and the criterion at -0.76, and because the blend weight
was zero at exactly 4 points it was REPLACING the criterion with the weaker
signal in precisely the case this feature exists for.  Spread is still
reported, and diversity is still enforced by the separation rule.

A NOTE ON THE EVALUATION SET
----------------------------
It has to be fair in RANGE.  A uniform grid of pixels is not: rows map to
range as roughly 1/(v - horizon), so most rows fall in the near field and any
criterion averaged over them quietly becomes a near-field criterion.  Without
a Stage D map the fallback set is therefore re-weighted so each range band
counts equally.  This was not a hypothetical - it is what made the first
version of this module recommend the bottom edge of the frame every time.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import stage_b

GRID = 36               # candidate pixels across the frame (GRID x GRID)
SEP_FRAC = 0.16         # min gap between two suggestions, as a fraction of width
                        # (a box is ~0.10 W wide, so this leaves a real gap -
                        # at 0.11 the boxes touched and read as one blob)
BOX_STEPS = 2.0         # region half-size, in grid steps
LAMBDA = 1e-6           # regularisation for the near-singular 4-point case
MAX_EVAL = 260          # evaluation points, subsampled if there are more
RANGE_BINS = 8          # equal-weight range bands for the fallback eval set
ERR_FLOOR = 0.5         # m, so zero-error places still count for something
FLAT = 0.25             # slope (m/m) at which the ground gate has halved
TANG_RADIUS = 260.0     # m, neighbourhood for reporting the measured error
CRITERIA = ("ground", "dopt")


def pose_jacobian(obj, R, C, K, dist):
    """The 2Nx6 derivative of pixel position w.r.t. (rvec, tvec).

    cv2.projectPoints already computes this and stage_a throws it away.
    Points are expressed relative to the camera centre - identical
    camera-frame coordinates, hence an identical Jacobian, but without
    burning ten of the sixteen available digits on the UTM easting.
    """
    R = np.asarray(R, float)
    C = np.asarray(C, float).reshape(3)
    pts = (np.asarray(obj, float).reshape(-1, 3) - C).reshape(-1, 1, 3)
    _, jac = cv2.projectPoints(pts, cv2.Rodrigues(R)[0], np.zeros((3, 1)),
                               np.asarray(K, float), np.asarray(dist, float))
    return np.asarray(jac[:, :6], float)


def information(points, R, C, K, dist, reg=LAMBDA):
    """M = J'J for the given control points, nudged to stay invertible."""
    obj = np.array([[p["X"], p["Y"], p["Z"]] for p in points], float)
    J = pose_jacobian(obj, R, C, K, dist)
    M = J.T @ J
    d = np.diag(M).copy()
    pos = d[d > 0]
    d[d <= 0] = pos.min() if pos.size else 1.0
    return M + reg * np.diag(d)      # scale-preserving: nudge, don't reshape


def _texture(gray, u, v, half=26):
    """Local high-frequency energy = how sharply a point can be clicked."""
    h, w = gray.shape
    x0, x1 = max(0, int(u) - half), min(w, int(u) + half)
    y0, y1 = max(0, int(v) - half), min(h, int(v) + half)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    patch = gray[y0:y1, x0:x1].astype(np.float32)
    return float((patch - cv2.GaussianBlur(patch, (0, 0), 6)).std())


def _slope(dem, X, Y):
    """DEM slope (m per m). Steep ground makes the GCP's own truth wrong."""
    s = max(dem.res, 5.0)
    zc = dem.Z(X, Y)
    zx, zy = dem.Z(X + s, Y), dem.Z(X, Y + s)
    if not (np.isfinite(zc) and np.isfinite(zx) and np.isfinite(zy)):
        return np.nan
    return float(np.hypot((zx - zc) / s, (zy - zc) / s))


def _range_fair(P, C):
    """Weights that make each range band contribute equally.

    Without this a pixel-uniform evaluation set is a near-field evaluation
    set, and every criterion averaged over it becomes a near-field criterion.
    """
    r = np.hypot(P[:, 0] - C[0], P[:, 1] - C[1])
    lo, hi = r.min(), r.max()
    if hi - lo < 1e-6:
        return np.ones(len(P))
    b = np.clip(((r - lo) / (hi - lo) * RANGE_BINS).astype(int), 0, RANGE_BINS - 1)
    cnt = np.bincount(b, minlength=RANGE_BINS).astype(float)
    return 1.0 / cnt[b]


def _thin(seq, cap):
    """Even stride down to `cap` items - not a random draw, so it is stable."""
    if len(seq) <= cap:
        return seq
    return seq[::int(np.ceil(len(seq) / float(cap)))]


class Scorer:
    """Value of adding one world point, under either criterion.

    Separated from suggest() so the criterion can be tested against real
    surveyed points rather than only against itself.
    """

    def __init__(self, points, dem, R, C, K, dist, stage_d=None, fallback=None):
        self.R = np.asarray(R, float)
        self.C = np.asarray(C, float).reshape(3)
        self.K = np.asarray(K, float)
        self.dist = np.asarray(dist, float)
        self.Minv = np.linalg.inv(information(points, R, C, K, dist))
        self.f = 0.5 * (float(self.K[0, 0]) + float(self.K[1, 1]))

        P, w = self._eval_points(stage_d, dem, fallback)
        self.evals = P
        self.B = pose_jacobian(P, R, C, K, dist).reshape(-1, 2, 6)
        slant = np.linalg.norm(P - self.C, axis=1)
        self.coef = w * (slant / self.f) ** 2      # pixel variance -> m^2
        self.V0 = float(np.einsum("nij,jk,nik,n->", self.B, self.Minv,
                                  self.B, self.coef))
        if not np.isfinite(self.V0) or self.V0 <= 0:
            raise RuntimeError("the predicted error at the evaluation points "
                               "is degenerate - re-solve the pose first.")

    def _eval_points(self, stage_d, dem, fallback):
        """Where accuracy is wanted, and how badly."""
        good = list(getattr(stage_d, "good", []) or [])
        if len(good) >= 8:
            P, w = [], []
            for t in _thin(good, MAX_EVAL):
                z = dem.Z(t["cE"], t["cN"])
                if np.isfinite(z):
                    P.append([t["cE"], t["cN"], z])
                    w.append(ERR_FLOOR + abs(float(t["tangential"])))
            if len(P) >= 8:
                # tiles sit on a WORLD grid, so they are already range-fair;
                # the weight is the measured pose-fixable error itself
                self.measured = True
                return np.array(P, float), np.array(w, float)
        if not fallback or len(fallback) < 8:
            raise RuntimeError("not enough evaluation points to score against.")
        self.measured = False
        P = np.array(_thin([list(p) for p in fallback], MAX_EVAL), float)
        return P, _range_fair(P, self.C)

    def value(self, X, Y, Z):
        """(fraction of predicted error removed, D-optimality dlogdet)."""
        A = pose_jacobian(np.array([[X, Y, Z]], float), self.R, self.C,
                          self.K, self.dist)
        G = self.Minv @ A.T                              # 6x2
        S = np.eye(2) + A @ G
        sgn, gain = np.linalg.slogdet(S)
        gain = float(gain) if (sgn > 0 and np.isfinite(gain)) else 0.0
        try:
            Sinv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return 0.0, gain
        U = self.B @ G                                   # Ne x 2 x 2
        cut = float(np.einsum("nij,jk,nik,n->", U, Sinv, U, self.coef) / self.V0)
        return cut, gain


class _TangentialField:
    """Measured pose-fixable error, for reporting at a candidate."""

    def __init__(self, res, radius=TANG_RADIUS):
        self.ok = False
        self.radius = radius
        if res is None or len(getattr(res, "good", []) or []) < 6:
            return
        good = res.good
        self.P = np.array([[t["cE"], t["cN"]] for t in good], float)
        self.T = np.abs(np.array([t["tangential"] for t in good], float))
        self.ok = True

    def at(self, X, Y):
        if not self.ok:
            return None
        d = np.hypot(self.P[:, 0] - X, self.P[:, 1] - Y)
        nb = d <= self.radius
        if nb.sum() < 3:
            return None
        return float(self.T[nb].mean())


def default_range(points, C, stage_d=None, floor=1500.0, margin=1.6):
    """How far out to look.

    Deliberately generous: a tight cap silently amputates the far field,
    which is exactly where the error lives.  Capping at 600 m on 113_100m put
    every candidate inside 500 m while the terrain - and the points that
    actually helped - ran out to 1127 m.  Rays that cannot reach are rejected
    for free by ray_reach(), so there is little to pay for the headroom."""
    C = np.asarray(C, float).reshape(3)
    r = [np.hypot(p["X"] - C[0], p["Y"] - C[1]) for p in points]
    out = max(floor, margin * max(r)) if r else floor
    if stage_d is not None and getattr(stage_d, "params", None) is not None:
        out = max(out, float(stage_d.params.max_range))
    return float(out)


def ray_reach(d, C, dem, max_range):
    """How far along a ray it is still POSSIBLE to hit the DEM. 0 = never.

    Two exact bounds, both cheap, and both needed before max_range can be
    generous.  Elevation: a climbing ray above the highest ground can never
    come back down, and a descending ray past the lowest ground has already
    crossed the surface.  Extent: a ray outside the DEM's bounding box is
    over nodata.  Without these, horizon-grazing rows march the full distance
    on every candidate and the whole pass takes minutes instead of seconds.
    """
    reach = float(max_range)
    if d[2] > 1e-9:
        if C[2] >= dem.zmax:
            return 0.0
        reach = min(reach, (dem.zmax - C[2]) / d[2])
    elif d[2] < -1e-9:
        reach = min(reach, (C[2] - dem.zmin) / (-d[2]))
    for axis, (lo, hi) in enumerate(dem.bbox):     # slab test, x then y
        if abs(d[axis]) < 1e-12:
            if not (lo <= C[axis] <= hi):
                return 0.0
            continue
        t0 = (lo - C[axis]) / d[axis]
        t1 = (hi - C[axis]) / d[axis]
        if t0 > t1:
            t0, t1 = t1, t0
        if t1 <= 0:
            return 0.0
        reach = min(reach, t1)
    return max(0.0, reach + 4.0 * dem.res)


def _dem_bounds(dem):
    """Cache zmin/zmax/bbox on the DEM object - reading them is not free."""
    if not hasattr(dem, "zmin"):
        dem.zmin = float(np.nanmin(dem.arr))
        dem.zmax = float(np.nanmax(dem.arr))
        b = dem.ds.bounds
        dem.bbox = ((float(b.left), float(b.right)),
                    (float(b.bottom), float(b.top)))
    return dem


def candidates(image_rgb, dem, R, C, K, dist, max_range, grid=GRID, progress=None):
    """Every grid pixel that lands on usable ground, with its local terms."""
    prog = progress or (lambda f, m: None)
    H, W = image_rgb.shape[:2]
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    _dem_bounds(dem)
    xs = np.linspace(W * 0.04, W * 0.96, grid)
    ys = np.linspace(H * 0.02, H * 0.97, grid)
    out = []
    seen, total = 0, grid * grid
    for v in ys:
        for u in xs:
            seen += 1
            if seen % 120 == 0:
                prog(0.7 * seen / float(total), "tracing candidate rays...")
            d = stage_b.pixel_to_ray(u, v, R, K, dist)
            reach = ray_reach(d, C, dem, max_range)
            if reach <= dem.res:
                continue
            hit = stage_b.raycast(u, v, R, C, K, dist, dem.Z, dem.res,
                                  max_range=reach)
            if hit is None:
                continue
            X, Y, Z = float(hit[0]), float(hit[1]), float(hit[2])
            rng = float(np.hypot(X - C[0], Y - C[1]))
            if rng > max_range:
                continue
            slope = _slope(dem, X, Y)
            if not np.isfinite(slope):
                continue
            tex = _texture(gray, u, v)
            if tex <= 0:
                continue
            out.append(dict(u=float(u), v=float(v), X=X, Y=Y, Z=Z,
                            range=rng, slope=slope, tex=tex))
    return out, float(xs[1] - xs[0])


def suggest(points, image_rgb, dem, R, C, K, dist, n=4, stage_d=None,
            max_range=None, criterion="ground", box_frac=None, progress=None):
    """Ranked suggestion regions, best first.

    box_frac  : region HALF-size as a fraction of image width. None keeps the
                default of BOX_STEPS candidate spacings. A bigger box is
                easier to satisfy in the field - anywhere inside it counts -
                but says less about where to stand; a smaller one is precise
                advice you may not be able to follow.

    points    : GCPs already placed - dicts with u, v, X, Y, Z
    stage_d   : optional core.error_map.Result; enables the measured weighting
    max_range : None derives it from the GCPs already placed
    criterion : "ground" (metres of predicted error removed where the error
                actually is) or "dopt" (plain D-optimality)

    Each result is a dict with u, v, half (pixels), score, rank, reasons and
    the component values that produced it.
    """
    prog = progress or (lambda f, m: None)
    if criterion not in CRITERIA:
        raise ValueError("criterion must be one of %s" % (CRITERIA,))
    used = [p for p in points
            if p.get("u") is not None and p.get("X") is not None
            and p.get("Z") is not None and np.isfinite(p.get("Z", np.nan))]
    if len(used) < 4:
        raise RuntimeError("place at least 4 control points and solve first - "
                           "there is no pose to improve on yet.")
    if max_range is None:
        max_range = default_range(used, C, stage_d)

    cands, dx = candidates(image_rgb, dem, R, C, K, dist, max_range,
                           progress=prog)
    if len(cands) < 8:
        raise RuntimeError("only %d candidate pixels landed on the DEM - check "
                           "that the DEM covers the scene and the pose is sane."
                           % len(cands))
    try:
        sc = Scorer(used, dem, R, C, K, dist, stage_d=stage_d,
                    fallback=[(c["X"], c["Y"], c["Z"]) for c in cands])
    except np.linalg.LinAlgError:
        raise RuntimeError("the current pose is too weakly constrained to "
                           "score candidates - add one well-spread point by "
                           "hand, then try again.")

    W = image_rgb.shape[1]
    uv_used = np.array([[p["u"], p["v"]] for p in used], float)
    tang = _TangentialField(stage_d)
    tex_ref = float(np.median([c["tex"] for c in cands])) or 1.0

    for i, c in enumerate(cands):
        if i % 120 == 0:
            prog(0.7 + 0.3 * i / float(len(cands)), "scoring candidate regions...")
        c["cut"], c["gain"] = sc.value(c["X"], c["Y"], c["Z"])
        c["click"] = c["tex"] / (c["tex"] + tex_ref)     # saturating gate
        c["ground"] = 1.0 / (1.0 + (c["slope"] / FLAT) ** 2)
        c["spread"] = float(np.hypot(*(uv_used - np.array([c["u"], c["v"]])).T).min())
        c["tangential"] = tang.at(c["X"], c["Y"])
        base = max(c["cut"] if criterion == "ground" else c["gain"], 1e-12)
        c["score"] = float(base * c["click"] * c["ground"])

    cands.sort(key=lambda c: -c["score"])
    half = int(box_frac * W) if box_frac else int(BOX_STEPS * dx)
    half = max(8, min(half, int(0.35 * W)))
    # boxes must not touch, or several suggestions read as one blob - so the
    # separation follows the box size rather than staying at a fixed fraction
    sep = max(SEP_FRAC * W, 2.15 * half)
    picked = []
    for c in cands:
        if all(np.hypot(c["u"] - p["u"], c["v"] - p["v"]) >= sep for p in picked):
            picked.append(c)
            if len(picked) >= n:
                break

    tex_hi = float(np.percentile([c["tex"] for c in cands], 70))
    for i, c in enumerate(picked, 1):
        why = []
        if c["spread"] >= 0.25 * W:
            why.append("fills a gap in the point spread")
        if criterion == "ground":
            why.append("cuts %.0f%% of the predicted error" % (100 * c["cut"]))
        else:
            why.append("dlogdet %.2f - pose weakly constrained here" % c["gain"])
        if c["tangential"] is not None and c["tangential"] >= 1.0:
            why.append("%.1f m of pose-fixable error measured nearby"
                       % c["tangential"])
        if c["tex"] >= tex_hi:
            why.append("sharp features to click")
        if c["slope"] <= 0.12:
            why.append("flat ground")
        c["rank"] = i
        c["half"] = half
        c["measured"] = sc.measured
        c["max_range"] = max_range
        c["reasons"] = why
        # what fits INSIDE the drawn box; the full list is for hover and the log
        c["short"] = ("cuts %.0f%%" % (100 * c["cut"]) if criterion == "ground"
                      else "dlogdet %.1f" % c["gain"])
        if c["tangential"] is not None and c["tangential"] >= 1.0:
            c["short"] += "  |  %.1f m err" % c["tangential"]
    return picked


def d_efficiency(points, R, C, K, dist, extra=None):
    """logdet(J'J) for the current points, optionally plus one extra (X,Y,Z).

    The scalar D-optimality criterion itself - exposed so a suggestion can be
    checked against a real re-solve rather than trusted."""
    obj = [[p["X"], p["Y"], p["Z"]] for p in points]
    if extra is not None:
        obj = obj + [list(extra)]
    J = pose_jacobian(np.array(obj, float), R, C, K, dist)
    return float(np.linalg.slogdet(J.T @ J)[1])
