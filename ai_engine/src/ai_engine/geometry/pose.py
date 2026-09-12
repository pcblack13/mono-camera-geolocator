"""`PoseEstimator` — camera pose from a plane homography, **in the window frame**. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``): SCOPE §4 lists camera pose
(yaw/pitch/roll) estimation as ABC only.

★ WHAT THIS MODULE MAY NOT DO, AND WHY IT MATTERS (L3). It produces a pose in the WINDOW
frame. It does not, and cannot, produce a bearing relative to true north: that conversion
needs the window's transform rotation AND the grid convergence at the window's position on
the planet, which is precisely the knowledge `ai_engine` is forbidden to have.
`gis.pose.window_yaw_to_north_deg()` owns it.

Two conventions this module must honour, each of which was a silent, plausible-looking
error before it was written down (§4.7):

* **`t_cam_from_world` is the TRANSLATION, not the camera position.** Under
  ``p_cam = R @ p_world + t``, the camera's position is ``C = -R.T @ t``, which is what
  `PoseResult.camera_position_enu` carries and what `camera_height_m` reads. Taking
  ``camera_height_m = t[2]`` is EXACTLY RIGHT at nadir — where ``R ≈ diag(1,-1,-1)`` so
  ``t = (0,0,h)`` — and wrong everywhere else: `t_z` is the depth to the plane origin along
  the optical axis, so at a 60° tilt it overstates height by 2× and at 80° by ~5.8×. Three
  of the four supported regimes are oblique, and a nadir-only test cannot see any of it.
* **`yaw_deg = 0` means `-y` of the window frame** — UP the raster. A north-up raster has a
  negative pixel height in the standard transform order, so window `+y` points *south*;
  taking `0 = +y` puts a silent 180° error into the field that aims the map's view cone.

The plane's metric frame comes from `CandidateWindow.gsd_m` — **the only sanctioned metric
scale inside `ai_engine`**, and correct only because `gis` passes it already corrected for
where the window sits. The window's own transform coefficients are an opaque payload and
must never be read for this: for some providers they are not true ground metres at all, and
anything metric built from them is silently wrong by a factor that depends on position —
74% at 55°N, which is serious agricultural country.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import CameraIntrinsics, HomographyResult, PoseResult

__all__ = ["PoseEstimator"]


class PoseEstimator:
    """Recovers camera pose from a plane-induced homography.

    Zhang-plane is the PRIMARY method; `cv2.decomposeHomographyMat` is the fallback. Both
    report through `PoseResult.method`, whose every member is a storable `pose_method`
    label — a pose whose method has no label is a pose that cannot be written to the
    database at all.
    """

    #: The pixel scale used to build the plane's metric frame. Named here so the rule is
    #: unmissable: it comes from `CandidateWindow.gsd_m`, never from the opaque transform.
    metric_scale_field: ClassVar[str] = "gsd_m"

    def __init__(self, intrinsics: CameraIntrinsics | None = None) -> None:
        """Bind the camera intrinsics.

        Args:
            intrinsics: From EXIF, from a field of view, or estimated from vanishing
                points. None means they must be supplied per call.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="camera pose estimation")

    def estimate(
        self,
        homography: HomographyResult,
        *,
        gsd_m: float,
        intrinsics: CameraIntrinsics | None = None,
    ) -> PoseResult:
        """Recover the camera pose in the window frame.

        Args:
            homography: The plane-induced homography, query frame → window frame.
            gsd_m: True ground metres per window pixel, passed in from
                `CandidateWindow.gsd_m`. ★ Never derived here — deriving it needs the
                window's position on the planet, which this package may not know.
            intrinsics: Overrides the bound intrinsics for this call.

        Returns:
            A `PoseResult` in the WINDOW frame. Converting its `yaw_deg` to a true-north
            bearing is `gis.pose`'s job.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="camera pose estimation")

    def decompose(
        self,
        H: np.ndarray,
        intrinsics: CameraIntrinsics,
    ) -> tuple[PoseResult, ...]:
        """Return every pose consistent with `H` — the fallback path.

        `decomposeHomographyMat` yields up to four solutions, and disambiguation needs
        evidence this method does not have (a cheirality check, or a plane normal prior).
        Returning all of them and letting the caller carry them in `PoseResult.ambiguity`
        is honest; silently returning the first is not.

        Args:
            H: `(3,3)` the plane-induced homography.
            intrinsics: The camera intrinsics.

        Returns:
            The candidate poses, best-first when the caller supplied enough to order them.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="homography pose decomposition")
