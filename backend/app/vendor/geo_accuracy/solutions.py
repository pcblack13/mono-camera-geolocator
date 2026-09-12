r"""The competing answers to "where is this pixel really?", side by side.

Stages D/E/F leave four ways to turn a pixel into a coordinate:

    raw      the pose solved from your GCPs, nothing removed
    pose     Stage E - the pose re-solved against the satellite truth
    field    Stage E + the residual field laid on top of that pose
    stagef   Stage F - pick the better base per region, then subtract the
             leftover local error, shrunk by its own signal-to-noise

This module measures all four ON THE SAME TILES so they can be ranked by one
number, and renders each on the same grid with one shared colour scale.

HONESTY: three of the four are FITTED to these tiles
-----------------------------------------------------
Only `raw` is a pure measurement.  `pose` fits 6 parameters to ~2N equations,
so its in-sample residual is barely optimistic.  But `field` interpolates a
vector through every tile, so its in-sample residual is EXACTLY ZERO - the
old report printed 0.00 m for it, which is not an accuracy, it is a
restatement of the fit.  `stagef` averages its neighbours, so its in-sample
residual is optimistic too.

So `field` and `stagef` are measured by CROSS-VALIDATION: the correction is
rebuilt without the tile it is then tested on.  That is the number a user
comparing methods actually needs, and the only one comparable with `raw` and
`pose` on equal terms.  `pose` is left in-sample; refitting 6 parameters per
fold moves it far less than the tile noise, and would make it the one stage
measured differently from the way it is used.

The folds are SPATIAL BLOCKS WITH A BUFFER, not a random split
--------------------------------------------------------------
Stage D tiles are 128 m wide on a 64 m stride, so neighbouring tiles overlap
by half and share half their pixels - and therefore half their noise.  Under
a random k-fold split, a held-out tile still has a training tile 64 m away
that overlaps it, and interpolating between them reproduces the held-out
tile's own noise.  Measured on 124_200m that made the residual field look
like 0.15 m median error, better than every other stage by a factor of ten.
It is an artefact: the field was being asked to predict a measurement it had
already half seen.

So each fold holds out a contiguous BLOCK of ground, and any training tile
within one tile-width of a test tile is dropped as well.  What is left is the
honest question: how well does this correct a place that was not itself
measured?
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .error_correction import _tile_errors, pseudo_gcps
from .stage_f import StageF

FOLDS = 5
ORDER = ("raw", "pose", "field", "stagef")
LABEL = {"raw": "Raw pose (no correction)",
         "pose": "Stage E - refined pose",
         "field": "Stage E + residual field",
         "stagef": "Stage F - pose + vector removal"}
# pink -> amber -> blue -> deep green, worst to best; the same colours the
# map pins use, so a pin needs no legend
COLOUR = {"raw": "#ec4899", "pose": "#f59e0b",
          "field": "#2563eb", "stagef": "#15803d"}


@dataclass
class Solution:
    key: str
    tiles: list                       # the Stage D tiles these residuals belong to
    vec: np.ndarray                   # (N,2) residual error vector per tile
    held_out: bool = False            # measured on tiles the fit never saw
    available: bool = True
    note: str = ""
    _err: np.ndarray = field(default=None, repr=False)

    @property
    def label(self):
        return LABEL[self.key]

    @property
    def colour(self):
        return COLOUR[self.key]

    @property
    def err(self):
        if self._err is None:
            self._err = np.hypot(self.vec[:, 0], self.vec[:, 1])
        return self._err

    @property
    def p95(self):
        return float(np.percentile(self.err, 95)) if len(self.err) else float("nan")

    @property
    def worst20(self):
        """Share of ALL the error carried by the worst 20% of tiles.

        A correction can halve the median and still be worse to stand under:
        measured on 106_40m, the pose fix took the median from 14.8 m to
        4.5 m while the p95 went 22 m -> 38 m and this share went 0.56 ->
        0.80. Most of the scene improved and a minority got much worse, which
        the median alone cannot say."""
        e = np.sort(self.err)[::-1]
        if not len(e) or e.sum() <= 0:
            return float("nan")
        k = max(1, int(round(len(e) * 0.20)))
        return float(e[:k].sum() / e.sum())

    def bands(self, params):
        """{band name: median |error|} plus 'all'."""
        out = {}
        e = self.err
        for lo, hi, name in params.bands:
            m = np.array([lo <= t["range"] < hi for t in self.tiles])
            if m.any():
                out[name] = float(np.median(e[m]))
        out["all"] = float(np.median(e)) if len(e) else float("nan")
        return out

    def heat(self, result, vmax=None):
        """(Z, step) on the Stage D ortho grid - same grid for every stage."""
        from .error_map import heat_from_points
        X = np.array([t["x0"] + t["tile"] / 2 for t in self.tiles], float)
        Y = np.array([t["y0"] + t["tile"] / 2 for t in self.tiles], float)
        return heat_from_points(result, X, Y, self.err,
                                tile=max(t["tile"] for t in self.tiles))


def blocked_folds(pts, tile_m, k=FOLDS, block=4.0, buffer=1.0, seed=0):
    """[(test idx, train idx), ...] - contiguous ground blocks, buffered.

    Deterministic: the same tiles must always give the same table. `block` and
    `buffer` are in tile-widths; the buffer is what stops a 50%-overlapping
    neighbour from leaking the answer into the training set."""
    pts = np.asarray(pts, float)
    B = max(block * tile_m, 1.0)
    bx = np.floor((pts[:, 0] - pts[:, 0].min()) / B).astype(int)
    by = np.floor((pts[:, 1] - pts[:, 1].min()) / B).astype(int)
    ids = bx * (by.max() + 1) + by
    uniq = np.unique(ids)
    rng = np.random.default_rng(seed)
    assign = {b: i % k for i, b in enumerate(rng.permutation(uniq))}
    fold_of = np.array([assign[b] for b in ids])
    out = []
    for f in range(min(k, len(uniq))):
        te = np.where(fold_of == f)[0]
        if not len(te):
            continue
        cand = np.where(fold_of != f)[0]
        d = np.hypot(pts[cand, 0][:, None] - pts[te, 0][None, :],
                     pts[cand, 1][:, None] - pts[te, 1][None, :])
        tr = cand[d.min(axis=1) > buffer * tile_m]
        out.append((te, tr))
    return out


def _field_cv(pts, vec, folds):
    """Residual-field prediction at each tile, from a field built without it.

    Returns (prediction, reached) - `reached` marks the tiles the field could
    actually say something about. Outside the training hull it is NOT
    extrapolated, which is its real behaviour too; but then it corrects
    nothing there, and a stage that corrects nothing should say so rather than
    quietly scoring the same as the stage underneath it."""
    from ._interp import Triangulation, LinearTriInterpolator
    pred = np.zeros_like(vec)
    reached = np.zeros(len(pts), bool)
    for te, tr in folds:
        if len(tr) < 4:
            pred[te] = np.nan
            continue
        try:
            tri = Triangulation(pts[tr, 0], pts[tr, 1])
            fx = LinearTriInterpolator(tri, vec[tr, 0])
            fy = LinearTriInterpolator(tri, vec[tr, 1])
        except Exception:                                  # noqa: BLE001
            pred[te] = np.nan
            continue
        for j in te:
            a = fx(pts[j, 0], pts[j, 1])
            b = fy(pts[j, 0], pts[j, 1])
            ok = not (np.ma.is_masked(a) or np.ma.is_masked(b))
            reached[j] = ok
            pred[j] = (float(a), float(b)) if ok else (0.0, 0.0)
    return pred, reached


def _stagef_cv(pts, raw_vec, cor_vec, folds):
    """Stage F prediction per tile, from a Stage F built without that tile.

    Returns (subtracted vector, base-is-raw flag)."""
    sub = np.zeros_like(cor_vec)
    from_raw = np.zeros(len(pts), bool)
    for te, tr in folds:
        if len(tr) < 8:
            continue
        sf = StageF(pts[tr], raw_vec[tr], pts[tr], cor_vec[tr])
        for j in te:
            s, raw_base, _ = sf.correction_at(pts[j, 0], pts[j, 1])
            sub[j] = s
            from_raw[j] = raw_base
    return sub, from_raw


def build(result, dem, raw_pose, corr, folds=FOLDS, progress=None):
    """Measure every stage on the same tiles.

    result   : core.error_map.Result (Stage D)
    raw_pose : (R, C, K, dist) as solved on page 1
    corr     : core.error_correction.Correction, or None for raw only

    Returns {key: Solution} - always contains "raw"; the rest appear only
    when a correction exists and there are enough tiles to cross-validate.
    """
    prog = progress or (lambda p, m: None)
    R, C, K, dist = raw_pose
    prog(5, "collecting the matched tiles...")
    uv, xyz_true, tiles = pseudo_gcps(result, dem, R, C, K, dist)
    if len(tiles) < 4:
        raise RuntimeError("only %d matched tiles - nothing to compare."
                           % len(tiles))

    prog(20, "measuring the raw pose at every tile...")
    raw_vec = _tile_errors(uv, xyz_true, R, C, K, dist, dem)
    ok = np.isfinite(raw_vec).all(axis=1)
    out = {}

    if corr is None:
        keep = np.where(ok)[0]
        out["raw"] = Solution("raw", [tiles[i] for i in keep], raw_vec[keep],
                              note="the measurement itself - nothing fitted")
        return out

    prog(45, "measuring the refined pose at every tile...")
    pose_vec = _tile_errors(uv, xyz_true, corr.R, corr.C, corr.K,
                            corr.dist, dem)
    ok &= np.isfinite(pose_vec).all(axis=1)
    keep = np.where(ok)[0]
    tiles = [tiles[i] for i in keep]
    pts = xyz_true[keep, :2]
    raw_vec, pose_vec = raw_vec[keep], pose_vec[keep]

    out["raw"] = Solution("raw", tiles, raw_vec,
                          note="the measurement itself - nothing fitted")
    out["pose"] = Solution("pose", tiles, pose_vec,
                           note="6 parameters fitted to %d tiles, so the "
                                "in-sample number is barely optimistic"
                                % len(tiles))

    tile_m = float(result.params.tile)
    fl = blocked_folds(pts, tile_m, folds)
    cv = ("%d spatially blocked folds, each held-out block buffered by one "
          "tile width so an overlapping neighbour cannot leak the answer"
          % len(fl))

    prog(65, "cross-validating the residual field...")
    if corr.report.get("residual_field", True) and len(fl) >= 2:
        pred, reached = _field_cv(pts, pose_vec, fl)
        good = np.isfinite(pred).all(axis=1)
        note = (cv + ". In-sample this stage is exactly zero, which restates "
                     "the fit rather than measuring it.")
        hit = float(reached[good].mean()) if good.any() else 0.0
        if hit < 0.5:
            note += (" NOTE: on %.0f%% of the held-out tiles the field had "
                     "nothing to interpolate from - it is never extrapolated "
                     "outside the measured area, so on unmeasured ground it "
                     "corrects nothing and scores the same as the pose alone."
                     % (100 * (1 - hit)))
        out["field"] = Solution(
            "field", [t for t, g in zip(tiles, good) if g],
            (pose_vec - pred)[good], held_out=True, note=note)
    else:
        out["field"] = Solution("field", tiles, np.zeros_like(pose_vec),
                                available=False,
                                note="not built (no residual field, or too few "
                                     "tiles to cross-validate)")

    prog(85, "cross-validating Stage F...")
    if len(fl) >= 2 and len(tiles) >= 40:
        sub, from_raw = _stagef_cv(pts, raw_vec, pose_vec, fl)
        base = np.where(from_raw[:, None], raw_vec, pose_vec)
        out["stagef"] = Solution(
            "stagef", tiles, base - sub, held_out=True,
            note=cv + ". Base chosen from the neighbours: raw in %.0f%% of "
                      "tiles, refined pose in the rest." % (100.0 * from_raw.mean()))
    else:
        out["stagef"] = Solution("stagef", tiles, np.zeros_like(pose_vec),
                                 available=False,
                                 note="needs about 40 matched tiles to "
                                      "cross-validate")
    prog(100, "comparison ready")
    return out


def table(sols, params):
    """[(band, {key: median m}), ...] with 'all' last - the comparison grid."""
    per = {k: s.bands(params) for k, s in sols.items() if s.available}
    names = []
    for k in ORDER:
        if k in per:
            names = [b for b in per[k] if b != "all"]
            break
    rows = [(b, {k: v.get(b) for k, v in per.items()}) for b in names]
    rows.append(("all", {k: v.get("all") for k, v in per.items()}))
    return rows


def best_key(sols, params):
    """Which stage actually wins on the all-band median, held-out where it
    matters. Raw is the fallback: if nothing beats doing nothing, say so."""
    best, bv = "raw", float("inf")
    for k in ORDER:
        s = sols.get(k)
        if s is None or not s.available or not len(s.err):
            continue
        v = s.bands(params)["all"]
        if np.isfinite(v) and v < bv:
            best, bv = k, v
    return best
