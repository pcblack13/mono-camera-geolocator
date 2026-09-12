"""DEM/DTM preparation — crop to an AOI, reproject to metres, sample elevations.

★ The executable form of ``DTM_Proccesing/`` (the three-stage algorithm folder), moved
into ``gis`` because **this package is the only place a coordinate is born** and every
one of these stages is coordinate work. Nothing here imports FastAPI, SQLAlchemy or
``ai_engine``.

The three stages, in the order the algorithm runs them::

    1. crop       AOI corners (DMS or decimal) + tolerance  ->  cropped GeoTIFF
    2. reproject  geographic degrees                        ->  projected metres (UTM)
    3. sample     (lon, lat) points                         ->  (X, Y, Z) in the DEM's CRS

Stage 2 is the one that matters most to a surveyor and it is why the pipeline exists:
**degrees are not a length unit.** Ray directions, camera positions, buffers and
distances must be computed in metres, and a degree of longitude is 111 km at the equator
and 64 km at 55N. ``(lambda, phi, H) -> (E, N, H)`` is the whole point.

★ Two deliberate departures from the original scripts, both correctness fixes:

* **UTM zone selection routes through :func:`gis.crs.utm_epsg_for`.** The original
  ``utm_epsg_from_lonlat`` computed ``int((lon + 180) // 6) + 1`` with no clamp, which
  returns zone **61** at ``lon = 180`` and yields EPSG:32661 — UPS North, a polar
  stereographic CRS that is not a UTM zone at all. ``gis.crs`` clamps to 60 and rejects
  ``|lat| > 84``.
* **shapely is not used.** The original built a ``Polygon`` only to read ``.bounds``;
  four corners' min/max is the same answer without the dependency, and reprojecting the
  corners through ``gis.crs`` keeps the CRS work in the one module allowed to do it.

★ **rasterio is bound at CALL time**, never at import (§11.3). Importing ``gis.dem`` on a
machine with no raster stack is fine; calling a stage without one raises
:class:`gis.errors.RasterBackendUnavailable`, which names the dependency that would fix it.
"""

from __future__ import annotations

from gis.dem.aoi import (
    AoiCorner,
    AoiExtent,
    corners_from_camera,
    corners_to_lonlat,
    dms_to_decimal,
    parse_dms_string,
    utm_zone_for_camera,
)
from gis.dem.crop import CropReport, crop_to_aoi
from gis.dem.pipeline import DemPipelineReport, process_dem
from gis.dem.reproject import ReprojectReport, reproject_to_metric, resolve_target_crs
from gis.dem.sample import SampledPoint, sample_points, summarise_elevation

__all__ = [
    "AoiCorner",
    "AoiExtent",
    "CropReport",
    "DemPipelineReport",
    "ReprojectReport",
    "SampledPoint",
    "corners_from_camera",
    "corners_to_lonlat",
    "crop_to_aoi",
    "dms_to_decimal",
    "parse_dms_string",
    "process_dem",
    "reproject_to_metric",
    "resolve_target_crs",
    "sample_points",
    "summarise_elevation",
    "utm_zone_for_camera",
]
