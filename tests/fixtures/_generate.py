"""Regenerate the committed cross-package fixtures. Deterministic. NO NETWORK.

    python3 tests/fixtures/_generate.py [--check]

★ The committed JPEGs are the source of truth; this script is their provenance. Never run
it at test time — see `gis/src/gis/tests/fixtures/_generate.py` for the full reasoning.

**What is generated (§13.2 `tests/fixtures/`):**

| File | Purpose |
|---|---|
| `field_photo.jpg` | A ground-level field photo **with EXIF GPS** — exercises ingest -> prior -> search end to end |
| `field_photo_no_gps.jpg` | The same, EXIF stripped — exercises `422 SEARCH_HINT_REQUIRED` and the map-click hint path |
| `field_photo_rotated.jpg` | **EXIF `Orientation = 6`** — proves ingest normalises it and that `width`/`height` are stored post-rotation |

**The photo is a ground-level oblique, on purpose.** SCOPE.md §2 is explicit that this is
the geometry that made automatic matching untrustworthy: *"A planar homography is only
strictly valid for a planar scene or pure rotation; ground-level obliques violate both."* A
nadir-looking fixture would quietly misrepresent the product's actual input, so the scene is
rendered in true perspective — sky, horizon, and crop rows converging to a vanishing point.

**It stands on the same ground as the other fixtures.** The EXIF GPS is 15.0000000 E,
45.1534772 N — the exact top-left corner of `gis/src/gis/tests/fixtures/synthetic_ortho.tif`
(UTM 33N easting 500000 is the zone's central meridian, so the longitude is exactly 15.0).
The ortho, the committed tiles and this photograph are one place rather than three unrelated
synthetic worlds, which is what lets an e2e test hand the photo's GPS to the search and get
the ortho back.
"""

from __future__ import annotations

import argparse
import filecmp
import io
import math
import sys
import tempfile

from pathlib import Path
from typing import Any, Final

import numpy as np

HERE: Final[Path] = Path(__file__).parent

SEED: Final[int] = 20260717

# ★ The same ground as gis/src/gis/tests/fixtures/synthetic_ortho.tif.
PHOTO_LON: Final[float] = 15.0
PHOTO_LAT: Final[float] = 45.1534772
PHOTO_ALT_M: Final[float] = 120.0

WIDTH: Final[int] = 640
HEIGHT: Final[int] = 480
"""Landscape. ★ Non-square on purpose: `field_photo_rotated.jpg` carries Orientation=6, and
a square fixture would make "width/height are stored post-rotation" unfalsifiable."""

GPS_IFD: Final[int] = 0x8825
ORIENTATION_TAG: Final[int] = 0x0112


# =============================================================================
# The scene
# =============================================================================


def _ground_level_field(width: int, height: int, *, seed: int) -> np.ndarray:
    """Render a deterministic ground-level oblique view of a field.

    True perspective, not a fake gradient: for a pinhole camera of focal length ``f`` at
    height ``h`` looking at the horizon, a ground point imaged at row ``v`` below the
    horizon lies at distance ``d = f * h / (v - v_horizon)``. Crop rows are laid out in
    *ground* coordinates and projected, so they converge to a vanishing point the way a real
    photograph's do.

    Args:
        width: Image width in px.
        height: Image height in px.
        seed: Deterministic seed.

    Returns:
        ``(height, width, 3)`` uint8 RGB.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)

    horizon = height * 0.34
    focal_px = width * 0.9
    camera_height_m = 1.6
    cx = width * 0.5

    image = np.zeros((height, width, 3), dtype=np.float64)

    # --- Sky: a vertical gradient, lighter towards the horizon ----------------
    sky_t = np.clip(yy / max(horizon, 1.0), 0.0, 1.0)
    sky_top = np.array([96.0, 138.0, 190.0])
    sky_low = np.array([186.0, 206.0, 224.0])
    for c in range(3):
        image[..., c] = sky_top[c] + (sky_low[c] - sky_top[c]) * sky_t

    # --- Ground --------------------------------------------------------------
    below = yy > horizon
    depth = np.full_like(yy, np.inf)
    depth[below] = focal_px * camera_height_m / (yy[below] - horizon)

    # Lateral ground offset of each pixel, in metres.
    lateral = np.zeros_like(yy)
    lateral[below] = (xx[below] - cx) * depth[below] / focal_px

    # Crop rows every 0.75 m, running away from the camera.
    row_phase = 0.5 + 0.5 * np.sin(2.0 * math.pi * lateral / 0.75)
    soil = np.array([128.0, 100.0, 72.0])
    crop = np.array([74.0, 116.0, 52.0])
    for c in range(3):
        ground = soil[c] + (crop[c] - soil[c]) * row_phase
        image[..., c] = np.where(below, ground, image[..., c])

    # Haze with distance: far ground tends towards the sky colour.
    haze = np.zeros_like(yy)
    haze[below] = np.clip(depth[below] / 90.0, 0.0, 0.85)
    for c in range(3):
        image[..., c] = np.where(below, image[..., c] * (1 - haze) + sky_low[c] * haze, image[..., c])

    # A tree line just below the horizon, and a track heading to the vanishing point.
    treeline = (yy > horizon - height * 0.045) & (yy <= horizon + 1.0)
    tree_noise = 0.5 + 0.5 * np.sin(xx * 0.35) * np.sin(xx * 0.11 + 1.3)
    for c in range(3):
        tree = np.array([48.0, 74.0, 44.0])[c] + tree_noise * 14.0
        image[..., c] = np.where(treeline, tree, image[..., c])

    track = below & (np.abs(lateral - 1.9) < 0.42)
    for c in range(3):
        image[..., c] = np.where(track, soil[c] * 1.18, image[..., c])

    image += rng.normal(0.0, 2.2, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


# =============================================================================
# EXIF
# =============================================================================


def _rational(value: float, denominator: int = 10000) -> Any:
    """Encode a real number as PIL's native EXIF rational.

    ★ ``IFDRational``, not ``fractions.Fraction``. PIL carries a type table for the GPS tags
    it knows, and infers the encoding from the Python type for the ones it does not.
    ``GPSHPositioningError`` (tag 31) is one it does not know, and a bare ``Fraction`` there
    fails inside PIL's own error-reporting path with a bewildering
    ``TypeError: object of type 'Fraction' has no len()``. ``IFDRational`` is accepted for
    every rational tag, typed or untyped, so it is used for all of them.
    """
    from PIL.TiffImagePlugin import IFDRational

    return IFDRational(round(value * denominator), denominator)


def _dms(value: float) -> tuple[Any, Any, Any]:
    """Convert signed decimal degrees to the EXIF (deg, min, sec) rational triple."""
    magnitude = abs(value)
    degrees = int(magnitude)
    minutes_full = (magnitude - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60.0
    return (_rational(degrees, 1), _rational(minutes, 1), _rational(seconds))


def _build_exif(image: Any, *, gps: bool, orientation: int | None) -> Any:
    """Return a PIL ``Exif`` carrying the requested GPS / Orientation tags.

    ★ Pure PIL — `piexif` is not installed and is not a dependency. IU-09's `test_exif.py`
    builds its in-memory JPEGs the same way, so the committed fixtures and that suite
    exercise one encoder rather than two.
    """
    exif = image.getexif()
    if orientation is not None:
        exif[ORIENTATION_TAG] = orientation
    if gps:
        ifd = exif.get_ifd(GPS_IFD)
        ifd[1] = "N" if PHOTO_LAT >= 0 else "S"  # GPSLatitudeRef
        ifd[2] = _dms(PHOTO_LAT)  # GPSLatitude
        ifd[3] = "E" if PHOTO_LON >= 0 else "W"  # GPSLongitudeRef
        ifd[4] = _dms(PHOTO_LON)  # GPSLongitude
        ifd[5] = 0  # GPSAltitudeRef: 0 == above sea level
        ifd[6] = _rational(PHOTO_ALT_M, 100)  # GPSAltitude, metres
        ifd[7] = (_rational(10, 1), _rational(30, 1), _rational(0, 1))  # GPSTimeStamp, UTC
        ifd[11] = _rational(1.8, 10)  # GPSDOP
        ifd[29] = "2026:06:15"  # GPSDateStamp
        ifd[31] = _rational(4.5, 10)  # GPSHPositioningError, metres
        exif[GPS_IFD] = ifd
    return exif


def _save(path: Path, array: np.ndarray, *, gps: bool, orientation: int | None) -> None:
    from PIL import Image

    image = Image.fromarray(array, mode="RGB")
    exif = _build_exif(image, gps=gps, orientation=orientation)
    kwargs: dict[str, Any] = {"format": "JPEG", "quality": 82, "optimize": True}
    # ★ An EXIF block with nothing in it is not the same as no EXIF block. The no-GPS
    #   fixture must carry NO exif argument at all, or `extract_exif_gps` is asked a
    #   different question than the one the test means to ask.
    if gps or orientation is not None:
        kwargs["exif"] = exif
    image.save(path, **kwargs)


# =============================================================================
# Driver
# =============================================================================


def generate(into: Path) -> None:
    """Write every fixture into ``into``."""
    into.mkdir(parents=True, exist_ok=True)
    scene = _ground_level_field(WIDTH, HEIGHT, seed=SEED)
    _save(into / "field_photo.jpg", scene, gps=True, orientation=None)
    _save(into / "field_photo_no_gps.jpg", scene, gps=False, orientation=None)
    _save(into / "field_photo_rotated.jpg", scene, gps=True, orientation=6)


def verify(directory: Path) -> list[str]:
    """Read the fixtures back and assert what the suite depends on.

    A read-back, not a claim: "I passed exif=" and "the file on disk carries that GPS IFD"
    are different statements, and only the second is what a test loads.
    """
    from PIL import Image

    problems: list[str] = []

    with Image.open(directory / "field_photo.jpg") as im:
        exif = im.getexif()
        gps = exif.get_ifd(GPS_IFD)
        if not gps:
            problems.append("field_photo.jpg carries NO GPS IFD — its entire purpose")
        if (im.width, im.height) != (WIDTH, HEIGHT):
            problems.append(f"field_photo.jpg is {im.size}, expected {(WIDTH, HEIGHT)}")
        if exif.get(ORIENTATION_TAG) not in (None, 1):
            problems.append("field_photo.jpg must not carry a rotating Orientation")

    with Image.open(directory / "field_photo_no_gps.jpg") as im:
        if im.getexif().get_ifd(GPS_IFD):
            problems.append("field_photo_no_gps.jpg carries GPS — its entire purpose is not to")

    with Image.open(directory / "field_photo_rotated.jpg") as im:
        exif = im.getexif()
        if exif.get(ORIENTATION_TAG) != 6:
            problems.append(
                f"field_photo_rotated.jpg Orientation is {exif.get(ORIENTATION_TAG)}, expected 6"
            )
        if (im.width, im.height) != (WIDTH, HEIGHT):
            problems.append(f"field_photo_rotated.jpg stored size is {im.size}")
        if im.width == im.height:
            problems.append("a square fixture cannot prove post-rotation width/height")

    for name in ("field_photo.jpg", "field_photo_no_gps.jpg", "field_photo_rotated.jpg"):
        size = (directory / name).stat().st_size
        if size > 200_000:
            problems.append(f"{name} is {size} bytes; §13.2 caps it at 200 KB")

    return problems


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or check the committed fixtures."""
    parser = argparse.ArgumentParser(description="Regenerate tests/fixtures/.")
    parser.add_argument("--check", action="store_true", help="diff against the committed bytes")
    args = parser.parse_args(argv)

    names = ("field_photo.jpg", "field_photo_no_gps.jpg", "field_photo_rotated.jpg")

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp)
            generate(fresh)
            drifted = [n for n in names if not filecmp.cmp(fresh / n, HERE / n, shallow=False)]
            if drifted:
                print("DRIFT: committed fixtures differ from a fresh generation:")
                for name in drifted:
                    print(f"  - {name}")
                return 1
        print("fixtures match a fresh generation")
        return 0

    generate(HERE)
    problems = verify(HERE)
    if problems:
        print("FIXTURES ARE NOT SOUND:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    total = sum((HERE / n).stat().st_size for n in names)
    print(f"fixtures regenerated and verified ({total} bytes total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
