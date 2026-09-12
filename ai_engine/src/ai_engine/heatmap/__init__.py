"""Heatmap: the posterior over candidate camera locations, in WINDOW PIXELS.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Everything here stops at window pixels. Fusing per-window heatmaps into one geographic grid
is `gis.heatmap.fuse_pixel_heatmaps()`'s job — a `PixelHeatmap` carries the `WindowRef` that
makes that possible, and nothing here can do it (L3).
"""

from __future__ import annotations

from ai_engine.heatmap.posterior import CameraPosterior

__all__ = ["CameraPosterior"]
