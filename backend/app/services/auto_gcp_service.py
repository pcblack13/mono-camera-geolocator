"""``auto_gcp_service`` — the solved pose run BOTH ways, from 4+ located GCPs.

* ``estimate`` — photo pixel → world position (ray/DEM intersection).
* ``project`` — world position → photo pixel (the inverse, for keeping the two
  panels in lock-step while a GCP is edited in Auto mode).

The orchestration around :mod:`app.services.geolocate` (the field tool's solver):

1. Gather the photograph's prerequisites — its entered camera (intrinsics + position,
   ``auto_gcp_enabled``), its located GCPs, the project DEM — and refuse with a **422
   naming exactly what is missing** rather than solving on air (L12).
2. Move everything into the DEM's projected CRS (``gis.crs``): GCP lat/lon → X/Y,
   heights from the stored ``elevation_m`` or the DEM itself, the camera's ground
   point + mast offset → its entered centre.
3. Solve the pose (PnP over the correspondences), raycast the clicked pixel against
   the DEM, and return the hit as lat/lon **with the diagnostics that qualify it** —
   reprojection error, solved-vs-entered tilt and position shift. An estimate is an
   inference; the numbers that say how much to trust it travel with it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ImageNotFound, ValidationError
from app.core.pagination import PaginationParams, SortKey, SortParams
from app.db.repositories.gcps import GcpRepository
from app.db.repositories.image_cameras import ImageCameraRepository
from app.db.repositories.images import ImageRepository
from app.db.types import as_lonlat
from app.schemas.gcp import GCP_SORT_FIELDS
from app.schemas.image_camera import (
    AutoGcpEstimateRead,
    AutoGcpEstimateRequest,
    AutoGcpProjectRead,
    AutoGcpProjectRequest,
)
from app.services import geolocate

__all__ = ["AutoGcpService"]

#: The activation threshold — the solver needs four correspondences.
REQUIRED_GCPS = 4

_WGS84 = "EPSG:4326"


def _gcp_label(gcp: Any) -> str:  # noqa: ANN401 — the Gcp row; service-local
    """How a GCP is named to a HUMAN in a warning.

    ★ A WARNING MUST NAME SOMETHING THE SURVEYOR CAN FIND. This used to fall back
      to ``gcp.id`` — a full UUID that appears nowhere in the GCP table, so the one
      actionable part of the message was unusable. Order matches what the table
      actually shows: the free-text NAME first, then the survey CODE, and only then
      a short id prefix (which the table's Point ID column does display).
    """
    name = (getattr(gcp, "name", None) or "").strip()
    if name:
        return name
    code = (getattr(gcp, "code", None) or "").strip()
    if code:
        return code
    return f"#{str(gcp.id)[:8]}"


@dataclass
class _Solved:
    """Everything the two directions share: the solved pose and its ingredients."""

    camera: Any  # the ImageCamera row — intrinsics + entered station
    dem: geolocate.DemGrid
    k_matrix: np.ndarray
    dist: np.ndarray
    pose: geolocate.SolvedPose
    gcps_used: int
    warnings: list[str]
    #: Human labels of the points ACTUALLY used, in the same order as
    #: ``pose.reproj_px`` — so the worst-fitting point can be named, not just counted.
    labels: list[str]


class AutoGcpService:
    """Solve-and-raycast for one photograph; stateless per call."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._images = ImageRepository(session)
        self._cameras = ImageCameraRepository(session)
        self._gcps = GcpRepository(session)
        self._settings = settings

    async def _solve(self, image_id: uuid.UUID) -> _Solved:
        """Prerequisites → pose: the shared front half of BOTH directions.

        ★ ``estimate`` (pixel → world) and ``project`` (world → pixel) are the same
        solve run opposite ways; extracting it here keeps their 422 vocabulary and
        DEM-resolution rules identical by construction.
        """
        image = await self._images.get_active(image_id)
        if image is None:
            raise ImageNotFound(f"No image {image_id}.")

        camera = await self._cameras.get(image_id)
        if camera is None or not camera.auto_gcp_enabled:
            raise ValidationError(
                "Auto GCP picking is not enabled for this photo — turn it on in the "
                "image setup or the GCP panel first."
            )
        # >>> GEO-DRIFT-UPDATE C2 (integration) BEGIN — a calibration is optional here too >>>
        # ★ THE SAME TWO WAYS THE LUT BUILD ACCEPTS: a measured calibration, or
        #   "no calibration" with a rough field of view — in which case the focal is
        #   SOLVED from the located points (C3), never assumed from the angle.
        no_calibration = bool(getattr(camera, "no_calibration", False))
        fov_h = getattr(camera, "fov_h_deg", None)
        missing: list[str] = []
        if no_calibration:
            # ★ A blank field of view is no longer missing (2026-09-09, owner ask):
            #   the focal solve below starts from the default seed instead.
            pass
        else:
            missing = [
                name
                for name in ("fx", "fy", "cx", "cy")
                if getattr(camera, name) is None
            ]
        cam_lonlat = as_lonlat(camera.position)
        if cam_lonlat is None:
            missing.append("camera position (lat/lon)")
        if missing:
            raise ValidationError(
                "The camera setup is incomplete for estimation — missing: "
                + ", ".join(missing)
                + ". Enter the calibration on the camera's settings page (step 5)."
            )

        # ── the DEM under THIS photograph: its own if it has one, else the ────
        #    project's. The SAME image-overrides-project rule as
        #    DemService.elevation_dem_path and ElevationService, kept here in
        #    lockstep so the raycast and a GCP's recorded Z can never disagree
        #    about which surface is real.
        image_dem = self._settings.project_dem_dir / f"{image.project_id}__{image_id}.tif"
        project_dem = self._settings.project_dem_dir / f"{image.project_id}.tif"
        dem_path = image_dem if image_dem.exists() else project_dem
        if not dem_path.exists():
            raise ValidationError(
                "There is no DEM for this photo — attach one on the camera's settings page "
                "(step 4). The estimate intersects the "
                "pixel's ray with the terrain; without a surface there is nothing to "
                "intersect."
            )
        from gis.crs import is_ground_metric_crs, transform_point

        dem = geolocate.DemGrid(dem_path)
        if not is_ground_metric_crs(dem.crs):
            raise ValidationError(
                f"This photo's DEM CRS ({dem.crs}) is not a projected metric CRS — "
                "reprocess it on the DEM page (reproject to UTM) first."
            )

        # ── correspondences, in the DEM's CRS ─────────────────────────────────
        rows, _total = await self._gcps.list_for_image(
            image_id,
            pagination=PaginationParams(limit=200),
            sort=SortParams.parse(
                None, allowed=GCP_SORT_FIELDS, default=(SortKey("created_at"),)
            ),
        )
        warnings: list[str] = []
        obj_xyz: list[tuple[float, float, float]] = []
        img_uv: list[tuple[float, float]] = []
        # ★ Kept in lockstep with obj_xyz/img_uv — a skipped point must not shift the
        #   labels, or the worst-reprojection warning would accuse the wrong GCP.
        labels: list[str] = []
        for gcp in rows:
            lonlat = as_lonlat(gcp.geom)
            if lonlat is None:
                continue
            x, y = transform_point(lonlat[0], lonlat[1], _WGS84, dem.crs)
            z = gcp.elevation_m if gcp.elevation_m is not None else dem.z(x, y)
            if math.isnan(z):
                warnings.append(
                    f"GCP {_gcp_label(gcp)} has no elevation and falls outside this "
                    "photo's DEM, so it was left out of the camera solve. Either the "
                    "DEM does not cover it, or its coordinate is wrong."
                )
                continue
            obj_xyz.append((x, y, float(z)))
            img_uv.append((float(gcp.pixel_x), float(gcp.pixel_y)))
            labels.append(_gcp_label(gcp))

        if len(obj_xyz) < REQUIRED_GCPS:
            raise ValidationError(
                f"Auto GCP estimation needs {REQUIRED_GCPS} usable located points; "
                f"this photo has {len(obj_xyz)}."
            )

        # ── the entered camera centre: ground + mast, in the DEM's CRS ────────
        x0, y0 = transform_point(cam_lonlat[0], cam_lonlat[1], _WGS84, dem.crs)
        ground = dem.z(x0, y0)
        if math.isnan(ground):
            raise ValidationError(
                "The camera position falls outside this photo's DEM — check the "
                "latitude/longitude on the camera's settings page."
            )
        cam_xyz = np.array([x0, y0, ground + (camera.mast_offset_m or 0.0)])

        if no_calibration:
            # ★ K from the field of view is only the SEED. With four or more points
            #   the focal is recovered from them (one scale free, fy following fx —
            #   the study's 2 m against 37–61 m for a fixed guess); the solved K is
            #   what the pose below is then built with.
            from app.services.intrinsics import (  # noqa: PLC0415
                IntrinsicsError,
                k_from_fov,
                seed_fov,
            )
            from app.vendor.lut_generator.pose import solve_pose_free_focal  # noqa: PLC0415

            fov_seed, seed_span, seed_defaulted = seed_fov(fov_h)
            if seed_defaulted:
                warnings.append(
                    f"no field of view is set on this camera — the focal was solved from "
                    f"the default {fov_seed:.0f}° seed (covers roughly 37°–125°). Type the "
                    "true angle at step 3 for a telephoto or an ultra-wide lens."
                )
            try:
                k_matrix, dist, _fov_v = k_from_fov(
                    int(image.width),
                    int(image.height),
                    fov_seed,
                    getattr(camera, "fov_v_deg", None),
                    square_pixels=getattr(camera, "fov_v_deg", None) is None,
                )
            except IntrinsicsError as exc:
                raise ValidationError(str(exc)) from exc
            try:
                _r, _c, _rep, k_matrix = solve_pose_free_focal(
                    np.array(obj_xyz, dtype=float),
                    np.array(img_uv, dtype=float),
                    k_matrix,
                    dist,
                    cam_xyz,
                    span=seed_span,
                )
            except Exception as exc:  # noqa: BLE001 — the seed stands when the search cannot improve it
                warnings.append(f"focal solve fell back to the field-of-view seed ({exc}).")
        else:
            k_matrix = np.array(
                [
                    [camera.fx, 0.0, camera.cx],
                    [0.0, camera.fy, camera.cy],
                    [0.0, 0.0, 1.0],
                ],
                dtype=float,
            )
            dist = np.array(
                [camera.k1 or 0.0, camera.k2 or 0.0, camera.p1 or 0.0, camera.p2 or 0.0, camera.k3 or 0.0],
                dtype=float,
            )
        # <<< GEO-DRIFT-UPDATE C2 (integration) END <<<

        # ── solve ─────────────────────────────────────────────────────────────
        try:
            pose = geolocate.solve_pose(
                np.array(obj_xyz), np.array(img_uv), k_matrix, dist, cam_xyz
            )
        except geolocate.PoseSolveError as exc:
            raise ValidationError(
                f"The camera pose could not be solved from these GCPs ({exc}). "
                "Spread the points out — clustered or collinear points are degenerate."
            ) from exc

        return _Solved(
            camera=camera,
            dem=dem,
            k_matrix=k_matrix,
            dist=dist,
            pose=pose,
            gcps_used=len(obj_xyz),
            warnings=warnings,
            labels=labels,
        )

    async def estimate(
        self, image_id: uuid.UUID, body: AutoGcpEstimateRequest
    ) -> AutoGcpEstimateRead:
        """``POST /images/{image_id}/camera/estimate`` — pixel → world."""
        s = await self._solve(image_id)
        from gis.crs import transform_point

        pose, dem, warnings = s.pose, s.dem, s.warnings

        hit = geolocate.raycast(
            body.u,
            body.v,
            pose.rotation,
            pose.camera_xyz,
            s.k_matrix,
            s.dist,
            dem.z,
            dem.res,
            height_offset_m=body.height_offset_m,
        )
        if hit is None:
            raise ValidationError(
                "The ray through this pixel never meets the terrain — it points at "
                "the sky, past the DEM's edge, or beyond 50 km. Pick a point on the "
                "ground inside the DEM."
            )
        hx, hy, hz = hit
        lon, lat = transform_point(hx, hy, dem.crs, _WGS84)

        # ── diagnostics ───────────────────────────────────────────────────────
        reproj_mean = float(np.mean(pose.reproj_px))
        reproj_max = float(np.max(pose.reproj_px))
        bad_bar = max(3.0 * float(np.median(pose.reproj_px)), 8.0)
        # ★ THE ONE WARNING KEPT: a large worst-reprojection means the PnP solve
        #   could not fit one of the correspondences — a genuinely misplaced GCP, a
        #   data-entry mistake the surveyor should fix. This is the actionable signal.
        if reproj_max > bad_bar:
            # ★ NAME THE OFFENDER. `reproj_px` is per-point and in the same order as
            #   the labels collected during the solve, so the worst point is one
            #   index lookup — and a warning that names a point is a task, while one
            #   that says "one of them" is only a worry.
            worst = s.labels[int(np.argmax(pose.reproj_px))] if s.labels else "one point"
            warnings.append(
                f"GCP {worst} reprojects {reproj_max:.1f}px off — far worse than the "
                f"other {s.gcps_used - 1} points used. Its photo mark or its "
                "coordinate is probably misplaced; check it before trusting estimates."
            )
        tilt_entered = s.camera.tilt_deg
        # ★ THE TWO SILENCED (still returned as NUMBERS below, just not toasted):
        #   position_shift_m and the solved-vs-entered tilt delta. These compare the
        #   PnP-SOLVED pose to what the surveyor TYPED in setup — but the entered
        #   camera position is usually a rough handheld-GPS fix and the entered tilt
        #   an estimate, so the solve legitimately REFINING them is expected, not an
        #   error. Toasting "camera sits 71 m from entered" / "tilt differs by >5°"
        #   on every click cried wolf; the values remain in the response
        #   (position_shift_m, tilt_solved_deg, tilt_entered_deg) for a calm readout.

        return AutoGcpEstimateRead(
            lat=lat,
            lon=lon,
            elevation_m=float(hz),
            distance_m=float(math.hypot(hx - pose.camera_xyz[0], hy - pose.camera_xyz[1])),
            gcps_used=s.gcps_used,
            reproj_mean_px=reproj_mean,
            reproj_max_px=reproj_max,
            azimuth_deg=pose.azimuth_deg,
            tilt_solved_deg=pose.tilt_deg,
            tilt_entered_deg=tilt_entered,
            position_shift_m=pose.position_shift_m,
            warnings=warnings,
        )

    async def project(
        self, image_id: uuid.UUID, body: AutoGcpProjectRequest
    ) -> AutoGcpProjectRead:
        """``POST /images/{image_id}/camera/project`` — world → pixel, the inverse.

        Same solve, run the other way: the map coordinate is dropped onto the DEM
        (its elevation comes from the terrain, plus ``height_offset_m``), then
        projected through the solved pose back into the photograph. Read-only, like
        ``estimate`` — the client decides what to do with the pixel.
        """
        s = await self._solve(image_id)
        from gis.crs import transform_point

        x, y = transform_point(body.lon, body.lat, _WGS84, s.dem.crs)
        z = s.dem.z(x, y)
        if math.isnan(z):
            raise ValidationError(
                "This location falls outside the photo's DEM — the terrain height "
                "there is unknown, so it cannot be projected into the photograph."
            )

        pixel = geolocate.project_point(
            np.array([x, y, float(z) + body.height_offset_m]),
            s.pose.rotation,
            s.pose.camera_xyz,
            s.k_matrix,
            s.dist,
        )
        if pixel is None:
            raise ValidationError(
                "This location sits behind the camera — it cannot appear in the "
                "photograph, so there is no pixel to give."
            )
        u, v = pixel

        # ★ inside_image is judged against the ENTERED calibration frame when the
        #   surveyor supplied one; ``None`` = "no frame size on record", and the
        #   client (which knows the rendered image's natural size) decides.
        inside: bool | None = None
        if s.camera.img_w is not None and s.camera.img_h is not None:
            inside = 0.0 <= u < float(s.camera.img_w) and 0.0 <= v < float(
                s.camera.img_h
            )

        return AutoGcpProjectRead(
            u=u,
            v=v,
            inside_image=inside,
            gcps_used=s.gcps_used,
            warnings=s.warnings,
        )
