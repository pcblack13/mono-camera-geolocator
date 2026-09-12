"""Pixel -> (latitude, longitude) through a LUT bundle.

The bundle ships its own reader (pi_lookup.py, numpy only). This wraps it and
adds the one thing the app needs on top: the media being detected is rarely the
exact size the LUT was built for, so pixel coordinates are scaled from the media
into LUT space before the lookup.

A LUT is only valid while the camera does not move — manifest.json records the
pose it was built from, and the drift monitor (``drift_service``) is what says
whether that is still true.
"""
from __future__ import annotations

import csv
import json
import math
import os
from typing import Optional

import numpy as np


class LutError(RuntimeError):
    pass


class GeoLut:
    """One fixed camera view, frozen as a per-pixel lat/lon table."""

    def __init__(self, bundle_dir: str, mmap: bool = True):
        self.dir = os.path.abspath(os.path.expanduser(bundle_dir))
        man_path = os.path.join(self.dir, "manifest.json")
        if not os.path.isfile(man_path):
            raise LutError(f"no manifest.json in {self.dir} — is this a LUT bundle folder?")
        with open(man_path, "r", encoding="utf-8") as fh:
            self.manifest = json.load(fh)

        # mmap by default: the arrays are ~130 MB together and only a few
        # hundred pixels of them are ever read per run
        mode = "r" if mmap else None
        try:
            self.lat = np.load(os.path.join(self.dir, "lat.npy"), mmap_mode=mode)
            self.lon = np.load(os.path.join(self.dir, "lon.npy"), mmap_mode=mode)
        except OSError as exc:
            raise LutError(f"could not read the LUT arrays: {exc}") from exc
        if self.lat.shape != self.lon.shape:
            raise LutError("lat.npy and lon.npy have different shapes")
        self.height, self.width = self.lat.shape

    # ------------------------------------------------------------------ info
    @property
    def site(self) -> str:
        return self.manifest.get("site_name", os.path.basename(self.dir))

    def summary(self) -> dict:
        m = self.manifest
        pose = m.get("pose", {}) or {}
        return {
            "site": self.site,
            "dir": self.dir,
            "width": self.width,
            "height": self.height,
            "built_utc": m.get("built_utc"),
            "dem": (m.get("dem") or {}).get("file"),
            "coverage_percent": (m.get("build_stats") or {}).get("coverage_percent"),
            "azimuth_deg": pose.get("azimuth_deg"),
            "tilt_down_deg": pose.get("tilt_down_deg"),
            "reproj_mean_px": pose.get("reproj_mean_px"),
            "n_gcps_used": pose.get("n_gcps_used"),
            "target_height_m": m.get("target_height_m"),
        }

    def center(self) -> Optional[tuple[float, float]]:
        """A sensible place to point the map: the middle pixel, or the mean of
        the control points if the middle happens to be sky."""
        la, lo = self.lookup(self.width / 2, self.height / 2)
        if la is not None:
            return la, lo
        pts = [(float(g["lat"]), float(g["lon"])) for g in self.gcps()
               if g.get("lat") and g.get("lon")]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def gcps(self) -> list[dict]:
        path = os.path.join(self.dir, "gcps.csv")
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    # ---------------------------------------------------------------- lookup
    def scale_from(self, media_w: int, media_h: int) -> tuple[float, float]:
        """Factors that take a media pixel into LUT pixel space."""
        if not media_w or not media_h:
            return 1.0, 1.0
        return self.width / float(media_w), self.height / float(media_h)

    def lookup(self, u: float, v: float, media_size: Optional[tuple[int, int]] = None,
               scale: bool = True) -> tuple[Optional[float], Optional[float]]:
        """One pixel -> (lat, lon), or (None, None) where the ray hit no terrain.

        media_size lets a detection made on, say, a 1920x1080 copy of a
        3840x2160 view resolve against the full-resolution table.
        """
        if scale and media_size:
            sx, sy = self.scale_from(*media_size)
            u, v = u * sx, v * sy
        ui, vi = int(round(u)), int(round(v))
        if not (0 <= ui < self.width and 0 <= vi < self.height):
            return None, None
        la = float(self.lat[vi, ui])
        if math.isnan(la):
            return None, None
        return la, float(self.lon[vi, ui])
