"""LandExplorer ``gis`` — geospatial math, imagery access, and the birthplace of lat/lon.

``ai_engine`` ends at pixels; **this package is the only place a coordinate is born.**
Everything that turns a window pixel into a survey claim — the geotransform, the CRS, the
metres, the North — lives here and nowhere else.

★ THIS MODULE STAYS IMPORT-CHEAP. It re-exports only the pure value types, the errors and
the config. It does NOT import ``gis.imagery`` (httpx), ``gis.exif`` (PIL),
``gis.crs`` (pyproj/osgeo) or ``gis.raster`` (GDAL) at module scope, because
``import gis.tiles`` runs this file first and §4.18 requires ``gis.tiles`` to pull in
nothing but numpy and stdlib. Import the submodule you need:

    from gis.tiles import lonlat_to_tile, resolution_at
    from gis.crs import get_transformer, utm_epsg_for
    from gis.accuracy import manual_gcp_accuracy
"""

from __future__ import annotations

from gis.config import GisConfig
from gis.errors import (
    AreaTooLargeError,
    CrsBackendUnavailable,
    CrsError,
    ExportError,
    GisError,
    NonMetricCrsError,
    OutOfCoverage,
    OutsideUtmError,
    ProviderDisabledError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTransportError,
    RasterBackendUnavailable,
    SearchHintRequired,
    TileNotAvailableError,
    TileOutOfRangeError,
    UnknownProviderError,
)
from gis.types import (
    BasemapKind,
    BBox,
    GeoTransform,
    LonLat,
    RasterMeta,
    SatelliteChip,
    TileRange,
    TileRef,
    ZoomDecision,
)

__version__ = "1.0.0"

__all__ = [
    "AreaTooLargeError",
    "BBox",
    "BasemapKind",
    "CrsBackendUnavailable",
    "CrsError",
    "ExportError",
    "GeoTransform",
    "GisConfig",
    "GisError",
    "LonLat",
    "NonMetricCrsError",
    "OutOfCoverage",
    "OutsideUtmError",
    "ProviderDisabledError",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderRateLimitError",
    "ProviderTransportError",
    "RasterBackendUnavailable",
    "RasterMeta",
    "SatelliteChip",
    "SearchHintRequired",
    "TileNotAvailableError",
    "TileOutOfRangeError",
    "TileRange",
    "TileRef",
    "UnknownProviderError",
    "ZoomDecision",
    "__version__",
]


def version() -> str:
    """Return the installed ``gis`` package version."""
    return __version__
