"""Build configuration: load, validate and describe a LUT build job.

A config is a small JSON file. Everything the builder needs comes from it, so a
build is fully reproducible from (config + project + DEM).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

VALID_DTYPES = ("float64", "float32")


@dataclass
class BuildConfig:
    """One LUT build job."""

    # ---- identity ----------------------------------------------------------
    site_name: str                      # goes into the output folder name
    # ---- inputs ------------------------------------------------------------
    dem_path: str                       # DEM GeoTIFF, projected metric CRS
    project_json: Optional[str] = None  # GUI project (.json); None when the pose
                                        # is supplied directly (live GUI build)
    # ---- geometry ----------------------------------------------------------
    image_width: Optional[int] = None   # None -> read from the project fields
    image_height: Optional[int] = None
    target_height_m: float = 0.0        # height of the target above bare earth
    # ---- output ------------------------------------------------------------
    output_dir: str = "output"
    coord_dtype: str = "float64"        # float64 = exact; float32 = half size, ~0.4 m
    # ---- ray marching ------------------------------------------------------
    max_range_m: float = 50_000.0
    bisection_iters: int = 40
    # ---- execution ---------------------------------------------------------
    chunk_pixels: int = 200_000         # rays marched per vectorised batch
    # ---- validation --------------------------------------------------------
    validation_samples: int = 5_000
    max_error_tolerance_m: float = 0.05   # vs the scalar reference implementation

    # ------------------------------------------------------------------ load
    @staticmethod
    def load(path: str) -> "BuildConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        unknown = set(raw) - set(BuildConfig.__dataclass_fields__)
        if unknown:
            raise ValueError("unknown config key(s): %s" % ", ".join(sorted(unknown)))
        cfg = BuildConfig(**raw)
        cfg._resolve_relative_to(os.path.dirname(os.path.abspath(path)))
        cfg.validate()
        return cfg

    def _resolve_relative_to(self, base: str) -> None:
        """Make relative paths resolve against the config file's folder."""
        for attr in ("project_json", "dem_path", "output_dir"):
            val = getattr(self, attr)
            if val and not os.path.isabs(val):
                setattr(self, attr, os.path.normpath(os.path.join(base, val)))

    # -------------------------------------------------------------- validate
    def validate(self) -> None:
        if not self.site_name.strip():
            raise ValueError("site_name must not be empty")
        if not os.path.isfile(self.dem_path):
            raise FileNotFoundError("dem_path does not exist: %s" % self.dem_path)
        # project_json is optional: absent when the caller supplies a live pose
        if self.project_json is not None and not os.path.isfile(self.project_json):
            raise FileNotFoundError("project_json does not exist: %s" % self.project_json)
        if self.coord_dtype not in VALID_DTYPES:
            raise ValueError("coord_dtype must be one of %s" % (VALID_DTYPES,))
        if self.target_height_m < 0:
            raise ValueError("target_height_m must be >= 0")
        if self.chunk_pixels < 1000:
            raise ValueError("chunk_pixels too small (>= 1000)")
        if self.max_range_m <= 0:
            raise ValueError("max_range_m must be > 0")

    # ----------------------------------------------------------------- misc
    @property
    def bundle_dir(self) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.site_name)
        return os.path.join(self.output_dir, "%s_lut" % safe)

    def to_dict(self) -> dict:
        return asdict(self)


def write_template(path: str) -> None:
    """Write a commented starter config next to the given path."""
    tmpl = {
        "site_name": "site_108",
        "project_json": "../../core/geolocation_gui/Results_analysis/outputs/108_50m/123.json",
        "dem_path": "../../core/geolocation_gui/Results_analysis/outputs/108_50m/DTM/"
                    "N34E036_FABDEM_V1-2_cropped_utm.tif",
        "target_height_m": 0.0,
        "output_dir": "../output",
        "coord_dtype": "float64",
        "chunk_pixels": 200000,
        "validation_samples": 5000,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tmpl, fh, indent=2)
