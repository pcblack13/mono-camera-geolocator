"""`CameraPosterior` — a mixture over camera locations, in WINDOW PIXELS. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``): SCOPE §4 lists the confidence
heatmap over candidate camera locations as ABC only.

The formula (§4.25, normative)::

    π_w  ∝ exp(c_w / T),   Σ_w π_w = 1                  # component weights, softmax
    π_bg  = 1 − max_w(c_w)/100                          # the "not here" mass

    p(x) = π_bg / A_aoi  +  (1 − π_bg) · Σ_w π_w · N(x; μ_w, Σ_w)
                            ^^^^^^^^^^ the scaling that makes the mass real

★ THE `(1 − π_bg)` FACTOR IS THE WHOLE POINT OF THE TYPE. Without it, the total
pre-normalisation mass is `π_bg + 1`, so after normalising, the background's actual share
is `π_bg / (1 + π_bg)` rather than `π_bg`. The intended 78% "not here" mass at `c_max = 22`
came out as 44%; at `c_max = 50` the intended 50% became 33%. The stated purpose of the
background term was that *"a posterior that cannot express 'I don't know' is not a
posterior"* — and it could not. It propagated into `entropy_norm` (the `> 0.6` ⇒ "we have
not localised" flag) and into every credible region, so the 95% rings were drawn from a
density whose "not here" mass was roughly half what was specified: **systematically too
tight and too confident**, which is the precise direction a survey tool must never err in.
Scaling by `(1 − π_bg)` makes the sum exactly 1 before rasterisation, demoting the
normalise step to a numerical safeguard rather than a semantic change.

★ AND WHILE `calibrated == False`, THE SURFACE IS ORDINAL ONLY. Both `π_bg = 1 −
max(c_w)/100` and the softmax temperature read `confidence` as a probability, which it is
not — it ships uncalibrated and says so. So the UI renders a relative surface with no
probability labelling, and `entropy_norm` stays usable as a *comparative* diffuseness
signal. We do not print a percentage derived from an uncalibrated quantity.

★ WINDOW PIXELS, NOT GROUND UNITS. Each `PixelHeatmap` lives in one window's pixel frame
and carries its `WindowRef`. Fusing several into one true-metre grid across zoom levels is
`gis.heatmap.fuse_pixel_heatmaps()`'s job — it can do it because the ref recovers the
window and hence its transform, and `ai_engine` cannot do it at all (L3).
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import PixelHeatmap, WindowResult

__all__ = ["DEFAULT_SOFTMAX_TEMPERATURE", "CameraPosterior"]

#: The softmax temperature over `confidence` when weighting mixture components.
DEFAULT_SOFTMAX_TEMPERATURE: float = 10.0


class CameraPosterior:
    """A Gaussian mixture over candidate camera locations, plus an explicit "not here" mass."""

    def __init__(
        self,
        *,
        temperature: float = DEFAULT_SOFTMAX_TEMPERATURE,
        grid_size: int = 128,
    ) -> None:
        """Bind the mixture parameters.

        Args:
            temperature: The softmax temperature `T` over `confidence`.
            grid_size: `N`, the side of the rasterised `(N,N)` grid.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="camera location heatmap")

    def build(self, results: Sequence[WindowResult]) -> tuple[PixelHeatmap, ...]:
        """Build one `PixelHeatmap` per window that produced a pose.

        Args:
            results: The ranked window results. Windows without a pose contribute nothing —
                there is no location to place a component at.

        Returns:
            One `PixelHeatmap` per contributing window, each in ITS OWN window's pixel
            frame and carrying its `WindowRef`. Plural, deliberately: a single window-pixel
            frame cannot express a grid spanning many windows across several zoom levels,
            and pretending it could is what left the fusion step with a type mismatch and no
            owner.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="camera location heatmap")
