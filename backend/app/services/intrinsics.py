"""GEO-DRIFT-UPDATE C1 — intrinsics without a calibration file.

★ WHERE THIS COMES FROM. This is the geolocation GUI's own "no calibration -
  derive fx,fy,cx,cy from the field of view" model, ported verbatim from
  ``core/geo-gui-dr/geolocation_gui_ned/app.py::_K_from_fov``. Same formula,
  same square-pixel rule, same refusal messages — so a pose solved there and a
  drift reference frozen here agree by construction rather than by luck.

      fx = W / (2 tan(fov_h / 2))        cx = W / 2
      fy = H / (2 tan(fov_v / 2))        cy = H / 2
      k1 = k2 = k3 = p1 = p2 = 0

★ THE SQUARE-PIXEL RULE IS THE TRAP. With square pixels ``fy = fx``, and the
  vertical field of view that IMPLIES is ``2·atan(H / 2fy)`` — equivalently
  ``tan(fov_v/2) = (H/W)·tan(fov_h/2)``. Deriving it the obvious-but-wrong way,
  ``fov_v = fov_h · H/W``, puts fy **10.6 % out** (measured in the source GUI),
  and the ground error then lands anywhere from 7.9 m to 48 m depending on the
  starting guess. Do not "simplify" this.

★ WHAT YOU GIVE UP, MEASURED (from the source GUI's own notes, on a DJI FC3582):
    * The principal point is assumed dead centre. Real ``cx`` was 2025.48
      against a geometric centre of 2016 — ~9 px that this mode cannot know.
    * ``fov_h``/``fov_v`` must be the TRUE sensor angles. Not the spec sheet's
      DIAGONAL figure (84° vs a true 71.5° → 46.79 m of ground error), and not
      EXIF ``FocalLengthIn35mmFilm`` (DJI rounds it to an integer 24 mm, a 6.7 %
      scale error → 23.56 m).
    * No distortion, ever. Dropping the coefficients disagreed with the full
      model by a median 1.6 px, up to 8.3 px at the corner — 1.75 mrad, i.e.
      1.75 m of ground error per kilometre of range.

  Use it when there is no calibration to be had. When one exists, use it.
"""

from __future__ import annotations

import math

import numpy as np


class IntrinsicsError(ValueError):
    """A refusal that names what is missing and how to supply it."""


#: ★ THE DEFAULT SEED (2026-09-09, owner ask). "No calibration" means the focal
#: is SOLVED from the control points; the typed field of view is only where the
#: search starts. When the operator leaves it blank the search starts here —
#: 60° is the middle of the phone / webcam / drone / CCTV range — with a WIDER
#: bracket than a typed seed gets (see ``DEFAULT_SEED_SPAN``), so the truth is
#: still inside it from roughly 37° to 125°. A telephoto (< 37°) or a fisheye
#: (> 125°) still needs its angle typed; the UI says so beside the switch.
DEFAULT_FOV_H_DEG = 60.0
#: The free-focal search bracket around a TYPED seed (0.55× .. 1.45× fx) — the
#: study's own value — and around the DEFAULT seed (0.30× .. 1.70× fx).
TYPED_SEED_SPAN = 0.45
DEFAULT_SEED_SPAN = 0.70


def seed_fov(fov_h_deg: float | None) -> tuple[float, float, bool]:
    """``(fov_h_deg, search_span, defaulted)`` for a focal solve.

    A typed angle is used as given with the study's bracket; None becomes the
    default seed with the wide bracket, and ``defaulted`` says so, because the
    manifest and the UI must record which it was.
    """
    if fov_h_deg is None:
        return DEFAULT_FOV_H_DEG, DEFAULT_SEED_SPAN, True
    return float(fov_h_deg), TYPED_SEED_SPAN, False


def k_from_fov(
    width: int,
    height: int,
    fov_h_deg: float,
    fov_v_deg: float | None = None,
    square_pixels: bool = True,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Intrinsics from the field of view and the image size.

    Returns ``(K, dist, fov_v_deg_used)``. ``dist`` is always five zeros — this
    model has no distortion to offer, and pretending otherwise would be worse
    than admitting it.

    ``square_pixels=True`` derives the vertical FOV from the horizontal one and
    ignores ``fov_v_deg``; keep it on unless you know the sensor's pixels are
    not square, because ``free`` fy is the one error a focal solve cannot repair.
    """
    if width <= 0 or height <= 0:
        raise IntrinsicsError(
            f"the frame size must be positive, got {width}x{height}. "
            "Load the image or read the stream first so the size is known."
        )
    fh = math.radians(float(fov_h_deg))
    if not 0.0 < fh < math.pi:
        raise IntrinsicsError(
            f"fov_h must be between 0 and 180 degrees, got {fov_h_deg}. "
            "It is the camera's TRUE horizontal angle of view — not the spec "
            "sheet's diagonal figure, which is always larger."
        )
    fx = width / (2.0 * math.tan(fh / 2.0))

    if square_pixels:
        fy = fx
        # ★ tan(fov_v/2) = (H/W)·tan(fov_h/2) — NOT fov_v = fov_h·H/W.
        fov_v_used = 2.0 * math.degrees(math.atan(height / (2.0 * fy)))
    else:
        if fov_v_deg is None:
            raise IntrinsicsError(
                "'square pixels' is off, so fov_v is required too — or turn it "
                "back on to derive fov_v from fov_h."
            )
        fv = math.radians(float(fov_v_deg))
        if not 0.0 < fv < math.pi:
            raise IntrinsicsError(
                f"fov_v must be between 0 and 180 degrees, got {fov_v_deg}."
            )
        fy = height / (2.0 * math.tan(fv / 2.0))
        fov_v_used = float(fov_v_deg)

    cx, cy = width / 2.0, height / 2.0
    K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=float)
    return K, np.zeros(5, dtype=float), fov_v_used


def fov_from_k(K: np.ndarray, width: int, height: int) -> tuple[float, float]:
    """The horizontal and vertical FOV a given K implies, in degrees.

    The inverse of :func:`k_from_fov`, for two jobs the source GUI also does:
    prefilling the FOV boxes from an existing calibration, and carrying a solved
    focal across to another camera or project.
    """
    K = np.asarray(K, float).reshape(3, 3)
    fx, fy = float(K[0, 0]), float(K[1, 1])
    if fx <= 0 or fy <= 0:
        raise IntrinsicsError("K has a non-positive focal length; it is not usable.")
    return (
        2.0 * math.degrees(math.atan(width / (2.0 * fx))),
        2.0 * math.degrees(math.atan(height / (2.0 * fy))),
    )
