"""The camera-location posterior — in WINDOW PIXELS.

★ This is NOT a heatmap of tile scores. Each window's pose solve yields an actual camera
ground position, so the posterior is over *where the photographer stood* — which is both
more useful and more honest than colouring in tiles.

★ AND IT IS PER-WINDOW, IN THAT WINDOW'S OWN PIXEL FRAME. `MatchJobResult.heatmaps` is
plural and each entry carries its own `WindowRef`. Fusing them into a single true-metre
geographic grid spanning many windows across several zoom levels is
`gis.heatmap.fuse_pixel_heatmaps()`'s job — it is the only function permitted to see both
a `PixelHeatmap` and a geotransform. A single window-pixel frame cannot express an
area-wide grid, and pretending otherwise is how a type mismatch becomes an improvised
conversion in a service layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ai_engine.types.windows import WindowRef

__all__ = ["HeatmapComponent", "PixelHeatmap"]


@dataclass(frozen=True, slots=True)
class HeatmapComponent:
    """One window's pose solve, as a Gaussian component of the mixture.

    All geometry is in the OWNING window's pixel frame — `mu_px` is where in *those*
    pixels the camera appears to have stood.
    """

    mu_px: tuple[float, float]  # camera position from THIS window's pose solve, WINDOW px
    cov_px2: np.ndarray  # (2,2) float64, WINDOW pixels squared
    weight: float  # pi_w — softmax over confidence, sums to 1 across components
    window_key: str  # echoes WindowRef.key; opaque, never parsed
    confidence: float  # 0..100, the window's own score


@dataclass(frozen=True, slots=True)
class PixelHeatmap:
    """A rasterised posterior over camera location, for ONE window.

    The density is::

        p(x) = pi_bg / A  +  (1 - pi_bg) * sum_w pi_w * N(x; mu_w, Sigma_w)
                             ^^^^^^^^^^^ the scaling that makes pi_bg mean what it says

        pi_w  ∝ exp(c_w / T),  sum_w pi_w = 1          # component weights, softmax
        pi_bg  = 1 - max_w(c_w)/100                    # the "not here" mass

    ★ THE (1 - pi_bg) SCALING IS LOAD-BEARING. Rasterising ``pi_bg/A + sum_w pi_w*N(...)``
      and then "normalising to sum 1" gives the background an ACTUAL share of
      ``pi_bg/(1+pi_bg)``, not ``pi_bg``: at a best candidate of 22 the intended 78%
      "not here" mass becomes 44%, and at 50 the intended 50% becomes 33%. The stated
      purpose — *a posterior that cannot express "I don't know" is not a posterior* —
      then fails silently, and the credible regions drawn from it are systematically too
      tight and too confident. Scaling the components makes the sum exactly 1 before
      rasterisation, which demotes normalisation to a numerical safeguard rather than a
      semantic change.

    ★ ORDINAL ONLY WHILE `calibrated` IS FALSE. Both `pi_bg` and the softmax temperature
      read `confidence` as if it were a probability, and out of the box it is not — the
      default calibration is the identity. While `calibrated` is False this surface is a
      RELATIVE one: `entropy_norm` stays usable as a comparative diffuseness signal, and
      nothing derived from it may be printed as a percentage.
    """

    ref: WindowRef  # ★ which window's pixel frame this grid lives in
    grid: np.ndarray  # (N,N) float32, normalised to sum 1 — a DENSITY, not a score map
    grid_size: int  # N
    cell_size_px: float  # window pixels per grid cell
    origin_px: tuple[float, float] = (0.0, 0.0)  # window-pixel coords of grid cell (0,0)'s centre
    components: tuple[HeatmapComponent, ...] = ()
    background_weight: float = 1.0  # pi_bg — P(none of these). Defaults to "no information".
    entropy_norm: float = 1.0  # H(p)/log(N^2) in [0,1] — localisation ambiguity; >0.6 => diffuse
    calibrated: bool = False  # ★ ships FALSE. Never label an uncalibrated surface a probability.

    @property
    def size_px(self) -> tuple[float, float]:
        """(width, height) of the grid's footprint in window pixels."""
        extent = self.grid_size * self.cell_size_px
        return (extent, extent)
