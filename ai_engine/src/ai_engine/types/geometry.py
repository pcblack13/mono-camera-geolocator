"""Homography, pose and intrinsics — all of it in PIXELS.

★ L3 lives here more than anywhere else in the package. This module ends at pixels and a
covariance in pixels. Turning any of it into ground units is `gis`'s job, and the fact
that nothing here can do it is what makes the boundary mechanical rather than
aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ai_engine.types.enums import HomographyMethod, PoseMethod

__all__ = [
    "CameraIntrinsics",
    "HomographyResult",
    "PoseResult",
    "RansacConfig",
]


@dataclass(frozen=True, slots=True)
class RansacConfig:
    """Robust-fit settings.

    `method` is a ROBUST-FIT METHOD, not a component registry key — see
    `HomographyMethod`. `AiEngineConfig.estimator_backend` selects the component.
    """

    method: HomographyMethod = HomographyMethod.USAC_MAGSAC
    threshold_px: float = 3.0  # for MAGSAC this is an UPPER BOUND on noise, not a tuned gate
    confidence: float = 0.999
    max_iters: int = 10_000
    min_inliers: int = 12  # hard floor; 4 is the algebraic minimum, 12 the statistical one
    refine: bool = True  # LM re-fit on inliers (symmetric transfer)
    compute_covariance: bool = True
    lo_method: int = 4  # cv2.LOCAL_OPTIM_SIGMA
    lo_iterations: int = 10
    seed: int = 42  # -> UsacParams.randomGeneratorState. VERIFIED settable.
    normalize: bool = True  # Hartley pre-conditioning


@dataclass(frozen=True, slots=True)
class HomographyResult:
    """A robust planar fit, a-frame -> b-frame, plus everything needed to judge it.

    ★ SORT-ORDER-IN, SORT-ORDER-OUT. `inlier_mask` and `residuals` are ALWAYS aligned to
      the `Correspondences` object handed to the estimator — never to any internal sort
      order. PROSAC needs its input sorted by weight; un-permuting afterwards is the
      caller's job (`step6_estimate_homography` does both, normatively), so the
      permutation never escapes into this type. Get this wrong and every landmark support
      count, every `LandmarkEvidence.support_count` and every `gcps.residual_px` silently
      indexes the WRONG correspondence — no crash, entirely plausible numbers.
    """

    H: np.ndarray
    # (3,3) float64, a-frame -> b-frame. Scale-fixed: H /= H[2,2] if |H[2,2]| > 1e-12
    #   else H /= ||H||_F. |H[2,2]| ~= 0 is legal — it means the line at infinity maps
    #   through the principal point.
    inlier_mask: np.ndarray  # (M,) bool, aligned to the INPUT correspondences
    num_inliers: int
    reproj_error: float  # symmetric transfer RMS over INLIERS, px
    method: HomographyMethod
    num_iters: int
    threshold_px: float
    refined: bool
    condition_number: float  # ★ cond_2 on the HARTLEY-NORMALISED H~, not H
    determinant: float  # ★ det(H~)
    covariance: np.ndarray | None = None
    # ★ (9,9) float64. cov of vec_ROW(H), in the SAME GAUGE AS `H` — see cov_gauge.
    #   ROW-MAJOR ordering, normatively and everywhere.
    cov_gauge: Literal["h33_1", "unit_norm"] = "h33_1"
    # ★ LOAD-BEARING. Which gauge `covariance` is expressed in, matching how `H` was
    #   scale-fixed. "h33_1" is the normal case; "unit_norm" ONLY in the
    #   |H[2,2]| <= 1e-12 branch, where the h33=1 Jacobian is undefined. Consumers
    #   building A_h MUST branch on this field.
    normalization: tuple[np.ndarray, np.ndarray] | None = None  # (T_a, T_b)
    residuals: np.ndarray | None = None
    # (M,) per-correspondence symmetric transfer error, px, aligned to the INPUT
    sigma_r: float | None = None
    # ★ recovered per-residual noise sigma, px. Persisted so the geometry suite can assert
    #   it against known injected noise — the executable pin on the DOF factor.

    def warp_points(self, pts: np.ndarray) -> np.ndarray:
        """(N,2) -> (N,2). Map points from the a-frame to the b-frame.

        Raises ValueError if any point maps onto the line at infinity: silently emitting
        an enormous plausible-looking coordinate is precisely the failure the degeneracy
        checks exist to prevent.
        """
        query = np.asarray(pts, dtype=np.float64)
        if query.ndim != 2 or query.shape[1] != 2:
            raise ValueError(f"pts must be (N,2); got shape {query.shape}")
        if query.shape[0] == 0:
            return np.zeros((0, 2), dtype=np.float64)

        homogeneous = np.column_stack([query, np.ones(query.shape[0], dtype=np.float64)])
        mapped = homogeneous @ np.asarray(self.H, dtype=np.float64).T
        w = mapped[:, 2]
        if not np.all(np.abs(w) > 1e-12):
            raise ValueError(
                "H maps at least one point onto the line at infinity; the transferred "
                "coordinate is undefined (this is what degeneracy check H4 detects)"
            )
        return mapped[:, :2] / w[:, None]

    def warp_points_with_cov(
        self, pts: np.ndarray, pt_cov: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """-> ((N,2) warped, (N,2,2) covariance). PIXEL covariance. Metres are gis's job.

        Propagates two independent sources through the transfer:

        * the input point's own uncertainty, through the local Jacobian ``J_p``;
        * the fit's uncertainty ``Sigma_H``, through ``A_h`` (d(warped)/d(vec_ROW(H))).

        Args:
            pts: (N,2) points in the a-frame.
            pt_cov: (2,2) shared, or (N,2,2) per-point, covariance of `pts` in a-frame
                pixels. None => the points are treated as exact.

        Raises:
            NotImplementedError: when `cov_gauge` is "unit_norm". The h33=1 Jacobian is
                undefined in that gauge, and returning a number computed with the wrong
                one would be a fabricated uncertainty — the one thing this type must
                never produce.
        """
        query = np.asarray(pts, dtype=np.float64)
        warped = self.warp_points(query)
        n = warped.shape[0]
        out = np.zeros((n, 2, 2), dtype=np.float64)
        if n == 0:
            return warped, out

        H = np.asarray(self.H, dtype=np.float64)
        w = query @ H[2, :2] + H[2, 2]

        # J_p = d(warped)/d(p) — the local linearisation of the projective map.
        jac_p = np.empty((n, 2, 2), dtype=np.float64)
        jac_p[:, 0, 0] = H[0, 0] - warped[:, 0] * H[2, 0]
        jac_p[:, 0, 1] = H[0, 1] - warped[:, 0] * H[2, 1]
        jac_p[:, 1, 0] = H[1, 0] - warped[:, 1] * H[2, 0]
        jac_p[:, 1, 1] = H[1, 1] - warped[:, 1] * H[2, 1]
        jac_p /= w[:, None, None]

        if pt_cov is not None:
            cov_in = np.asarray(pt_cov, dtype=np.float64)
            if cov_in.shape == (2, 2):
                cov_in = np.broadcast_to(cov_in, (n, 2, 2))
            elif cov_in.shape != (n, 2, 2):
                raise ValueError(f"pt_cov must be (2,2) or (N,2,2) with N={n}; got {cov_in.shape}")
            out += jac_p @ cov_in @ jac_p.transpose(0, 2, 1)

        if self.covariance is not None:
            if self.cov_gauge != "h33_1":
                raise NotImplementedError(
                    f"covariance is in the {self.cov_gauge!r} gauge; A_h is derived for the "
                    "h33_1 gauge only. Convert the gauge before propagating rather than "
                    "reporting an uncertainty computed with the wrong Jacobian."
                )
            sigma_h = np.asarray(self.covariance, dtype=np.float64)
            if sigma_h.shape != (9, 9):
                raise ValueError(f"covariance must be (9,9); got shape {sigma_h.shape}")
            # A_h = d(warped)/d(vec_ROW(H)), ROW-MAJOR: [h11 h12 h13 h21 h22 h23 h31 h32 h33].
            a_h = np.zeros((n, 2, 9), dtype=np.float64)
            ones = np.ones(n, dtype=np.float64)
            row = np.stack([query[:, 0], query[:, 1], ones], axis=1)  # (N,3)
            a_h[:, 0, 0:3] = row / w[:, None]
            a_h[:, 1, 3:6] = row / w[:, None]
            a_h[:, 0, 6:9] = -row * (warped[:, 0] / w)[:, None]
            a_h[:, 1, 6:9] = -row * (warped[:, 1] / w)[:, None]
            out += a_h @ sigma_h @ a_h.transpose(0, 2, 1)

        return warped, out

    @property
    def inlier_ratio(self) -> float:
        """num_inliers / M. Zero-safe: an empty correspondence set has ratio 0.0."""
        m = int(self.inlier_mask.shape[0])
        return float(self.num_inliers) / m if m else 0.0


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """The camera's internal geometry, and how much we believe it.

    `source` is not decoration: an assumed focal length and one read from EXIF carry very
    different uncertainty, and `confidence` is what stops the pose path treating a guess
    as a measurement.
    """

    K: np.ndarray  # (3,3) float64
    source: str  # "exif" | "fov" | "vanishing_points" | "assumed" | "manual"
    focal_px: float
    principal_point: tuple[float, float]
    confidence: float  # [0,1]


@dataclass(frozen=True, slots=True)
class PoseResult:
    """★ THE FRAME CONVENTION, stated once:

        World  = local east-north-up, metres: X east, Y north, Z up.
        Camera = OpenCV: x right, y down, z forward.
        Relation:  p_cam = R @ p_world + t_cam_from_world.
    """

    R: np.ndarray  # (3,3) float64, world->camera
    t_cam_from_world: np.ndarray
    # ★ (3,) float64, METRES. The TRANSLATION in `p_cam = R p_world + t`. It is the world
    #   origin expressed in CAMERA coordinates. It is NOT the camera's position.
    camera_position_enu: np.ndarray
    # ★ (3,) float64, METRES, local east-north-up. = -R.T @ t_cam_from_world. THIS is the
    #   camera. camera_height_m := camera_position_enu[2].
    #
    #   Taking `t` for the position is EXACTLY RIGHT AT NADIR (where R ~= diag(1,-1,-1) so
    #   t = (0,0,h)) and wrong everywhere else: t_z is the DEPTH to the plane origin along
    #   the optical axis, so at tau=60 deg it overstates height by 2x and at 80 deg by
    #   ~5.8x. Three of the four supported regimes are oblique.
    yaw_deg: float
    # ★ 0 = -y of the WINDOW frame (i.e. UP the raster), clockwise, [0,360).
    #   For a north-up raster this IS north, so PoseResult.yaw_deg == camera_poses.yaw_deg
    #   and the common case needs no conversion. A north-up raster has NEGATIVE pixel
    #   height (GDAL order), so window +y points the other way — defining 0 as +y would
    #   mean a silent 180 deg error in the field that aims the map view cone.
    #
    #   NOTE this is still a WINDOW-frame bearing. Converting it to a true North bearing
    #   for camera_poses.yaw_deg needs the geotransform's rotation AND grid convergence,
    #   and is gis.pose.window_yaw_to_north_deg()'s job — ai_engine cannot do it (L3).
    pitch_deg: float  # 0=horizon, + = up, [-90,90]
    roll_deg: float  # + = clockwise, [-180,180]
    intrinsics: CameraIntrinsics
    method: PoseMethod  # ★ an ENUM, and every member is a `pose_method` PG label
    reproj_error_px: float
    inlier_count: int
    ambiguity: tuple[PoseResult, ...] = ()  # alternative solutions, disambiguation failed
    sigma_deg: tuple[float, float, float] | None = None  # (yaw, pitch, roll) 1-sigma
