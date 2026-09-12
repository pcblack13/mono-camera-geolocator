"""LUT Generator - full-resolution pixel -> lat/lon lookup tables.

Builds, validates and packages a per-pixel geolocation table for a fixed camera
so a field unit (Raspberry Pi) can resolve a pixel to coordinates with a single
array read, without a DEM or any geometry code.
"""

__version__ = "1.0.0"

from .config import BuildConfig            # noqa: F401
from .dem import DEM                       # noqa: F401
from .pose import CameraPose, pose_from_project   # noqa: F401
from .builder import build_lut, LUTArrays  # noqa: F401
from .validator import validate_lut        # noqa: F401
from .bundle import write_bundle, archive_bundle  # noqa: F401

__all__ = [
    "BuildConfig", "DEM", "CameraPose", "pose_from_project",
    "build_lut", "LUTArrays", "validate_lut", "write_bundle", "archive_bundle",
    "__version__",
]
