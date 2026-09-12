"""``matplotlib.tri`` stand-ins backed by SciPy — the ONE substitution in this vendor.

★ WHY THIS FILE EXISTS. The field tool interpolates its residual field with
``matplotlib.tri.Triangulation`` + ``LinearTriInterpolator``. The backend ships
``scipy`` (see ``backend/requirements.txt``) but **not** matplotlib, and pulling a
plotting library into an API process to get one Delaunay interpolator is the wrong
trade. Both libraries do the same thing — Qhull Delaunay triangulation, then linear
barycentric interpolation inside each triangle — so the numbers are the maths, not
the library.

★ THE SEMANTICS THE CALLERS DEPEND ON, preserved exactly:

* Construction **raises** on degenerate input (fewer than 3 points, all collinear).
  ``error_map.heat_from_points`` and ``solutions._field_cv`` both wrap the call in
  ``try/except Exception`` and fall back — that path must keep working.
* A query outside the convex hull comes back **masked**, so
  ``np.ma.is_masked(...)`` is True there — this is what stops the residual field
  from ever being EXTRAPOLATED onto unmeasured ground (``Correction.residual_at``
  returns ``(0, 0)`` outside, i.e. it corrects nothing rather than inventing a
  correction).
* The masked array's underlying data is **NaN** outside the hull, because
  ``heat_from_points`` does ``np.asarray(interp(...))`` and relies on those cells
  being NaN rather than a fabricated number.

Keeping the shim here — rather than editing the three call sites — means the
vendored modules stay one ``sed`` away from their standalone originals.
"""

from __future__ import annotations

import numpy as np

__all__ = ["Triangulation", "LinearTriInterpolator"]


class Triangulation:
    """Delaunay triangulation of scattered (x, y) points.

    Raises:
        ValueError: Fewer than three points.
        Exception: Qhull refuses a degenerate set (collinear points) — the same
            failure ``matplotlib.tri.Triangulation`` reports, and the callers
            already catch it.
    """

    def __init__(self, x, y) -> None:
        from scipy.spatial import Delaunay  # noqa: PLC0415 — heavy, used on demand

        self.x = np.asarray(x, dtype=float).ravel()
        self.y = np.asarray(y, dtype=float).ravel()
        if self.x.size != self.y.size:
            raise ValueError("x and y must have the same length")
        if self.x.size < 3:
            raise ValueError(f"a triangulation needs at least 3 points, got {self.x.size}")
        self.delaunay = Delaunay(np.column_stack([self.x, self.y]))


class LinearTriInterpolator:
    """Linear interpolation of ``values`` over a :class:`Triangulation`.

    Calling it returns a masked array — masked (and NaN underneath) wherever the
    query falls outside the triangulated hull.
    """

    def __init__(self, triangulation: Triangulation, values) -> None:
        from scipy.interpolate import LinearNDInterpolator  # noqa: PLC0415

        z = np.asarray(values, dtype=float).ravel()
        if z.size != triangulation.x.size:
            raise ValueError("values must have one entry per triangulation point")
        # ★ Hand SciPy the Delaunay object, not the raw points: the triangulation is
        #   built once and SHARED by the dE and dN interpolators, exactly as the
        #   original does. Two independent triangulations of the same points could
        #   differ on a degenerate quad and split a vector's components across
        #   different triangles.
        self._f = LinearNDInterpolator(triangulation.delaunay, z)

    def __call__(self, x, y):
        out = self._f(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        # NaN is what LinearNDInterpolator returns outside the hull; masking it is
        # what makes `np.ma.is_masked` — the callers' out-of-hull test — true there.
        return np.ma.masked_invalid(np.asarray(out, dtype=float), copy=False)
