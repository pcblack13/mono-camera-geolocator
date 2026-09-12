"""Where a detected object touches the ground — and, on request, where it stands.

A box says where something *is*, not where it *stands*. For anything resting on
the ground and seen from above, the contact point is the middle of the box's
BOTTOM edge — the last row of pixels the object occupies before the ground
takes over. That is the pixel this app looks up, always.

It is the object's NEAR edge rather than its middle, so a long vehicle is
marked at the end facing the camera. That is a known, consistent bias, and a
consistent bias is worth more than a cleverer estimate by default: correcting
it means assuming how long the object is, and an assumption that is wrong moves
the mark somewhere the object has never been.

★ THE CORRECTION IS OPT-IN AND RECORDED (2026-09-02). A session that asks for
``centre_marks`` has each placed mark pushed AWAY from the camera, along the
bearing camera → mark, by half the class's typical length
(``models.CLASS_CENTRE_OFFSET_M``). The metres applied travel on the mark and
into ``detection_events.centre_offset_m``; a mark that could not be corrected
(no camera position, a class with no entry) carries ``None`` — never a silent 0.
"""
from __future__ import annotations

import math
from typing import Optional

from .models import CLASS_CENTRE_OFFSET_M, Box, DetectSettings

#: Metres per degree of latitude — the equirectangular step used to push a mark
#: a few metres; at the ranges a fixed camera sees (≤ a few km) the error of the
#: flat-earth step is millimetres.
_M_PER_DEG_LAT = 111_320.0


def ground_point(box: Box, settings: DetectSettings,
                 media_size: Optional[tuple[int, int]] = None) -> tuple[float, float]:
    """The (u, v) pixel of this box to look up, in MEDIA pixels."""
    u = box.cx
    v = box.y2
    if media_size:
        w, h = media_size
        # never hand the LUT a pixel outside the frame; it has nothing there
        u = min(max(u, 0.0), w - 1.0)
        v = min(max(v, 0.0), h - 1.0)
    return u, v


def centre_offset_m(cls_name: str) -> Optional[float]:
    """Half the class's typical length, or None for a class with no entry."""
    return CLASS_CENTRE_OFFSET_M.get(str(cls_name).lower())


def push_from_camera(
    lat: float,
    lon: float,
    camera: Optional[tuple[float, float]],
    metres: Optional[float],
) -> tuple[float, float, Optional[float]]:
    """``(lat, lon, applied_m)`` — the mark moved ``metres`` away from the camera.

    Returns the mark untouched with ``applied_m = None`` when there is no camera
    position, no metres, or the mark sits ON the camera (no bearing to push along).
    """
    if camera is None or not metres or metres <= 0.0:
        return lat, lon, None
    cam_lat, cam_lon = camera
    cos_lat = math.cos(math.radians(lat))
    if cos_lat < 1e-9:
        return lat, lon, None
    dx = (lon - cam_lon) * _M_PER_DEG_LAT * cos_lat   # metres east of the camera
    dy = (lat - cam_lat) * _M_PER_DEG_LAT             # metres north of the camera
    dist = math.hypot(dx, dy)
    if dist < 0.01:
        return lat, lon, None
    ux, uy = dx / dist, dy / dist
    new_lat = lat + (uy * metres) / _M_PER_DEG_LAT
    new_lon = lon + (ux * metres) / (_M_PER_DEG_LAT * cos_lat)
    return new_lat, new_lon, float(metres)
