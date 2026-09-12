"""Write the deployment bundle that gets copied to the Raspberry Pi.

Bundle layout (self-describing, numpy-only on the Pi side):

    <site>_lut/
        lat.npy          float[H, W]  latitude,  decimal degrees, NaN = no hit
        lon.npy          float[H, W]  longitude, decimal degrees, NaN = no hit
        manifest.json    provenance, pose, validation report
        pi_lookup.py     standalone reader (no dependency beyond numpy)
        README_PI.txt    operating instructions for the field unit
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import shutil

import numpy as np

from .config import BuildConfig
from .dem import DEM
from .pose import CameraPose

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

PI_LOOKUP_SRC = '''"""Standalone LUT reader for the field unit. Requires only numpy.

    from pi_lookup import GeoLUT
    lut = GeoLUT("path/to/site_lut")
    lat, lon = lut.lookup(u=2010, v=1400)
"""
import json
import os

import numpy as np


class GeoLUT:
    """Pixel -> (latitude, longitude) for one fixed camera pose."""

    def __init__(self, bundle_dir, mmap=False):
        self.dir = os.path.abspath(bundle_dir)
        with open(os.path.join(self.dir, "manifest.json"), "r", encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        mode = "r" if mmap else None
        self.lat = np.load(os.path.join(self.dir, "lat.npy"), mmap_mode=mode)
        self.lon = np.load(os.path.join(self.dir, "lon.npy"), mmap_mode=mode)
        self.height, self.width = self.lat.shape

    # --------------------------------------------------------------- lookup
    def lookup(self, u, v):
        """One pixel -> (lat, lon). Returns (None, None) if that ray hit no terrain."""
        ui, vi = int(round(u)), int(round(v))
        if not (0 <= ui < self.width and 0 <= vi < self.height):
            raise IndexError("pixel (%d, %d) outside %dx%d image"
                             % (ui, vi, self.width, self.height))
        la = float(self.lat[vi, ui])
        lo = float(self.lon[vi, ui])
        if np.isnan(la):
            return None, None
        return la, lo

    def lookup_many(self, u, v):
        """Vectorised lookup. Arrays in, (lat, lon) arrays out; NaN where no hit."""
        ui = np.rint(np.asarray(u)).astype(np.intp)
        vi = np.rint(np.asarray(v)).astype(np.intp)
        np.clip(ui, 0, self.width - 1, out=ui)
        np.clip(vi, 0, self.height - 1, out=vi)
        return self.lat[vi, ui], self.lon[vi, ui]

    # ----------------------------------------------------------------- info
    @property
    def site(self):
        return self.manifest.get("site_name")

    def describe(self):
        m = self.manifest
        return ("LUT '%s'  %dx%d px  built %s\\n"
                "  DEM      : %s\\n"
                "  coverage : %.2f %% of pixels hit terrain\\n"
                "  validated: max %.3f m over %d samples"
                % (m.get("site_name"), self.width, self.height, m.get("built_utc"),
                   m.get("dem", {}).get("file"),
                   m.get("build_stats", {}).get("coverage_percent", float("nan")),
                   m.get("validation", {}).get("max_error_m", float("nan")),
                   m.get("validation", {}).get("samples", 0)))


if __name__ == "__main__":
    import sys
    lut = GeoLUT(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(lut.describe())
    if len(sys.argv) > 3:
        print(lut.lookup(float(sys.argv[2]), float(sys.argv[3])))
'''

README_PI = """LUT bundle - field unit instructions
====================================================================
Site        : {site}
Image size  : {w} x {h} pixels
Built (UTC) : {built}
Payload     : lat.npy + lon.npy = {mb:.1f} MB

WHAT THIS IS
    A frozen table: for every pixel of THIS camera view, the latitude and
    longitude of the ground point it looks at. No DEM, no ray tracing and no
    pose maths are needed on the Pi - only numpy.

REQUIREMENTS
    python3, numpy.        sudo apt install python3-numpy

USE
    from pi_lookup import GeoLUT
    lut = GeoLUT("/home/pi/{folder}")
    lat, lon = lut.lookup(u=2010, v=1400)     # ~0.5 microseconds
    lats, lons = lut.lookup_many(u_array, v_array)

    A returned (None, None) means that pixel is sky or outside DEM coverage.

    Pass mmap=True to page the arrays from disk instead of loading them into
    RAM. Recommended only on NVMe; on microSD prefer the default (full load,
    {mb:.1f} MB, {load} at startup).

VALIDITY - IMPORTANT
    This table is only correct while the camera does not move. Rebuild it on
    the PC if the camera is moved or rotated, the lens/zoom changes, the DEM
    changes, or the pose is re-solved with different GCPs.
    manifest.json records the exact pose and the DEM checksum used.

SELF TEST
    python3 pi_lookup.py .
====================================================================
"""


def write_bundle(lut, cfg: BuildConfig, pose: CameraPose, dem: DEM,
                 validation: dict) -> str:
    """Write the deployable folder; returns its path."""
    out = cfg.bundle_dir
    if os.path.isdir(out):
        log.warning("output folder exists, replacing: %s", out)
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)

    lat_path = os.path.join(out, "lat.npy")
    lon_path = os.path.join(out, "lon.npy")
    np.save(lat_path, lut.lat)
    np.save(lon_path, lut.lon)
    payload_mb = (os.path.getsize(lat_path) + os.path.getsize(lon_path)) / 1e6

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "site_name": cfg.site_name,
        "built_utc": datetime.datetime.now(datetime.timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "LUT Generator (full-resolution, option A)",
        "image": {"width": pose.width, "height": pose.height},
        "arrays": {
            "lat": {"file": "lat.npy", "dtype": str(lut.lat.dtype),
                    "units": "degrees north", "nodata": "NaN"},
            "lon": {"file": "lon.npy", "dtype": str(lut.lon.dtype),
                    "units": "degrees east", "nodata": "NaN"},
            "layout": "row-major [v, u]; index as lat[v, u]",
            "payload_mb": round(payload_mb, 2),
        },
        "target_height_m": cfg.target_height_m,
        "dem": {
            "file": os.path.basename(dem.path),
            "path_at_build": dem.path,
            "epsg": dem.epsg,
            "resolution_m": round(dem.res, 4),
            "md5": dem.md5(),
        },
        # None for a live build driven from the GUI (pose supplied in memory)
        "project_json": os.path.abspath(cfg.project_json) if cfg.project_json else None,
        "pose_source": "project_json" if cfg.project_json else "live (GUI Stage C)",
        "pose": pose.to_dict(),
        "build_stats": lut.stats,
        "validation": validation,
        "build_config": cfg.to_dict(),
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    with open(os.path.join(out, "pi_lookup.py"), "w", encoding="utf-8") as fh:
        fh.write(PI_LOOKUP_SRC)

    load_hint = "~%.1f s from microSD, ~%.1f s from NVMe" % (payload_mb / 60.0,
                                                            payload_mb / 450.0)
    with open(os.path.join(out, "README_PI.txt"), "w", encoding="utf-8") as fh:
        fh.write(README_PI.format(site=cfg.site_name, w=pose.width, h=pose.height,
                                  built=manifest["built_utc"], mb=payload_mb,
                                  folder=os.path.basename(out), load=load_hint))

    log.info("bundle written: %s (%.1f MB payload)", out, payload_mb)
    return out


def archive_bundle(bundle_dir: str) -> str:
    """Zip the bundle for transfer; returns the archive path."""
    archive = shutil.make_archive(bundle_dir, "zip",
                                  root_dir=os.path.dirname(bundle_dir),
                                  base_dir=os.path.basename(bundle_dir))
    log.info("archive ready for upload: %s (%.1f MB)",
             archive, os.path.getsize(archive) / 1e6)
    return archive
