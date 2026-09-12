"""Elevation from the DEM processed on the DEM page (§4.27). ``LE_ACTIVE_DEM_PATH``.

★ **The DEM the surveyor prepared is the DEM their control points are measured against.**

``local_dem`` samples whatever GeoTIFFs happen to sit in a directory; this provider samples
**one specific raster** — the output of a DEM processing run — so the elevation a GCP
carries and the surface the surveyor cropped, reprojected and inspected are the same
object. That is the whole difference, and it is the reason to prefer this one: the number
in ``gcps.elevation_m`` is traceable to a run whose CRS, cell size, elevation range and
void coverage were all shown on screen before it was adopted.

Keyless and fully offline. No active DEM means ``is_configured() -> False`` and the
provider self-skips to a null elevation — never a crash, never a fabricated zero (L11).

★ **Sampling is delegated to** :func:`gis.dem.sample_points`, deliberately, so this
provider and the DEM page's own "sample elevations" panel cannot disagree about the height
at a point. That function applies the pixel-centre half-pixel, refuses to interpolate
across a nodata void, and treats the sentinel voids (-32768, -9999) as absent rather than
as terrain 32 km below the geoid.

★ **On the vertical datum.** This provider reports the DEM's elevations as it finds them.
Copernicus GLO-30 and FABDEM are orthometric (EGM2008); a GNSS or EXIF altitude is
ellipsoidal, and the two differ by up to +/-107 m globally (~20 m across Lebanon). The
active DEM's declared datum travels in the run sidecar so the UI can state it; it is not
converted here, because a silent datum conversion is worse than an unconverted one.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Final

from gis.elevation.base import ElevationProvider, ElevationSample
from gis.errors import ProviderNotConfiguredError
from gis.types import LonLat

__all__ = ["DemRunProvider"]

_log = logging.getLogger("gis.elevation.dem_run")

_DEFAULT_VERTICAL_CE90_M: Final[float] = 6.6
"""Assumed vertical CE90 for a processed DEM, metres. ``LE_ACTIVE_DEM_CE90_M``.

★ An ASSUMPTION, named rather than hidden, and deliberately not flattering. It is
Copernicus GLO-30's figure — the same constant ``copernicus_dem.py`` carries — because a
30 m global DEM is the most likely thing to be uploaded and reporting better than that
would launder an estimate into a measurement.

The right value depends entirely on what was uploaded, and the spread is enormous:

* a drone photogrammetric DTM ....... 0.05-0.15 m
* national LIDAR ................... ~0.3 m
* FABDEM (buildings/forest removed)  ~4 m
* Copernicus GLO-30 / SRTM ......... ~6.6-16 m

An operator who knows their product's accuracy should set ``LE_ACTIVE_DEM_CE90_M``. This
number propagates into every GCP's ``elevation_ce90_m``, so it is a claim, not a label.
"""


class DemRunProvider(ElevationProvider):
    """Samples elevation from the active processed DEM.

    ★ KEYLESS · OFFLINE. Construction never raises and never touches the filesystem
    beyond a stat.
    """

    name: ClassVar[str] = "dem_run"

    def __init__(
        self,
        dem_path: str | Path = "",
        *,
        vertical_ce90_m: float = _DEFAULT_VERTICAL_CE90_M,
    ) -> None:
        """Construct the provider. NEVER raises on a missing or absent path.

        Args:
            dem_path: The active processed DEM. ``LE_ACTIVE_DEM_PATH``. Empty means no DEM
                has been processed yet, which is an unconfigured provider, not an error.
            vertical_ce90_m: Vertical error to report, CE90 metres. See
                :data:`_DEFAULT_VERTICAL_CE90_M` — it is an assumption, so it is overridable.
        """
        self._dem_path = Path(dem_path) if dem_path else None
        self._vertical_ce90_m = float(vertical_ce90_m)

    @property
    def dem_path(self) -> Path | None:
        """The active DEM, or None when none has been adopted."""
        return self._dem_path

    def _resolved(self) -> Path | None:
        """The active DEM if it is actually readable. Never raises."""
        if self._dem_path is None:
            return None
        try:
            return self._dem_path if self._dem_path.is_file() else None
        except OSError as exc:  # pragma: no cover - permissions, races
            _log.warning("cannot stat active DEM %s: %s", self._dem_path, exc)
            return None

    def is_configured(self) -> bool:
        """True iff an active DEM exists on disk AND a raster backend is bindable.

        PURE LOCAL CHECK. NEVER raises, NEVER reads the raster. A surveyor who has not yet
        processed a DEM lands on a null elevation with no branching and no error.
        """
        if self._resolved() is None:
            return False
        # ★ find_spec, NOT `import rasterio`: a pure presence probe with no import cost,
        #   and it keeps §10.5 true — raster BINDING stays in the sanctioned modules
        #   (rasterio_shim, crs, gis.dem's warp stage); a probe is not a binding.
        from importlib.util import find_spec

        if find_spec("rasterio") is None:
            _log.warning("rasterio is unavailable; dem_run cannot serve elevation")
            return False
        return True

    def sample(self, points: Sequence[LonLat]) -> list[ElevationSample]:
        """Sample the active DEM at each point.

        A point outside the DEM's extent, or landing on a nodata void, yields an honest
        empty sample — ``elevation_m`` and ``source`` both None, per the base contract.
        ★ This is the case that matters most in practice: the active DEM is usually
        cropped to one AOI, so a GCP placed outside it has genuinely not been measured,
        and saying so is the only correct answer.

        Args:
            points: Positions to sample, EPSG:4326.

        Returns:
            One sample per input point, in input order.

        Raises:
            ProviderNotConfiguredError: If no active DEM or no raster backend.
        """
        if not points:
            return []

        dem = self._resolved()
        if dem is None:
            raise ProviderNotConfiguredError(
                "no active DEM: process a DEM on the DEM page (or set LE_ACTIVE_DEM_PATH) "
                "before elevations can be sampled",
                provider=self.name,
            )

        from gis.dem import sample_points

        try:
            samples, _dem_crs, _out_crs = sample_points(
                dem,
                [(f"p{i}", p.lon, p.lat) for i, p in enumerate(points)],
                method="bilinear",
            )
        except Exception as exc:  # noqa: BLE001 - a bad DEM degrades; it never fails a GCP
            raise ProviderNotConfiguredError(
                f"the active DEM {dem.name} could not be sampled: {exc}",
                provider=self.name,
            ) from exc

        outside = sum(1 for s in samples if not s.inside_dem)
        if outside:
            _log.info(
                "%d of %d point(s) fall outside the active DEM %s; their elevation is null",
                outside, len(samples), dem.name,
            )

        return [
            ElevationSample(
                elevation_m=s.z_m,
                # ★ The pairing the base class enforces and the DB CHECK mirrors: a source
                #   may never name a producer that yielded nothing.
                source=self.name if s.z_m is not None else None,
                vertical_ce90_m=self._vertical_ce90_m if s.z_m is not None else None,
            )
            if s.z_m is not None and math.isfinite(s.z_m)
            else ElevationSample(None, None, None)
            for s in samples
        ]
