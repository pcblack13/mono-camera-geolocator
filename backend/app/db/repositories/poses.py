"""``camera_poses`` — :class:`CameraPoseRepository`.

★ SCOPE.md §4: camera-pose estimation is **deferred** (ABC only), and
``GET /images/{id}/camera-pose`` reads whatever is here — which in this build is nothing.
Per §4 rule 5 the table is created as specified and per the unit brief this repository is
real code, not a stub: the reads are correct, and the day the estimator lands there is
nothing here to write.

★ **The yaw convention is the trap.** ``camera_poses.yaw_deg`` is **0 = TRUE North**;
``ai_engine``'s ``PoseResult.yaw_deg`` is 0 = up the window raster. For a north-up
EPSG:3857 window those coincide; for a rotated or UTM window they do **not**, and
``gis.pose.window_yaw_to_north_deg()`` is the only thing permitted to convert.
**This layer stores degrees and asks no questions** — it never does frame math, and a
caller that hands it a window-frame yaw has already made the mistake.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, select, update

from app.core.exceptions import CameraPoseNotAvailable
from app.db.repositories.base import BaseRepository
from app.models.pose import CameraPose

__all__ = ["CameraPoseRepository"]


class CameraPoseRepository(BaseRepository[CameraPose]):
    """Where a photograph was taken from, and which way it was pointing."""

    model = CameraPose

    async def get_selected_for_image(self, image_id: uuid.UUID) -> CameraPose | None:
        """The pose the map is drawing. ``uq_camera_poses_image_selected``.

        At most one per image, enforced by a partial unique index — hence
        ``scalar_one_or_none`` rather than an ordered ``limit(1)`` that would quietly
        pick a winner if the invariant ever broke.
        """
        return await self._scalar_one_or_none(
            select(CameraPose).where(
                CameraPose.image_id == image_id, CameraPose.is_selected.is_(True)
            )
        )

    async def get_selected_or_raise(self, image_id: uuid.UUID) -> CameraPose:
        """:meth:`get_selected_for_image`, or the 404 endpoint 48 documents."""
        pose = await self.get_selected_for_image(image_id)
        if pose is None:
            raise CameraPoseNotAvailable(f"No camera pose for image {image_id}.")
        return pose

    async def list_for_image(
        self, image_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[CameraPose]:
        """Every pose candidate for an image, most confident first.

        ``ix_camera_poses_image (image_id, confidence DESC)`` serves it directly.
        """
        return await self._scalars(
            select(CameraPose)
            .where(CameraPose.image_id == image_id)
            .order_by(CameraPose.confidence.desc(), CameraPose.id.asc())
            .limit(limit)
        )

    async def list_for_match_result(
        self, match_result_id: uuid.UUID
    ) -> Sequence[CameraPose]:
        """Poses derived from one match result — the ambiguity set.

        A planar homography decomposes to **two** physically plausible poses; both are
        stored, and which is real is a question about the world that the decomposition
        alone cannot answer. Returning both is the honest interface.
        """
        return await self._scalars(
            select(CameraPose)
            .where(CameraPose.match_result_id == match_result_id)
            .order_by(CameraPose.confidence.desc(), CameraPose.id.asc())
        )

    async def select_pose(
        self, pose_id: uuid.UUID
    ) -> tuple[CameraPose, uuid.UUID | None]:
        """Promote one pose to the image's selected pose.

        ★ Two statements for the same reason as
        :meth:`MatchResultRepository.select_result`: ``uq_camera_poses_image_selected``
        is a partial unique index, and a single ``SET is_selected = (id = :chosen)`` can
        trip it mid-scan. Clear, then set.

        Returns:
            ``(pose, previously_selected_id)``.

        Raises:
            CameraPoseNotAvailable: no such pose.
        """
        target = await self.get(pose_id)
        if target is None:
            raise CameraPoseNotAvailable(f"No camera pose {pose_id}.")

        previous = await self._scalar(
            select(CameraPose.id).where(
                CameraPose.image_id == target.image_id,
                CameraPose.is_selected.is_(True),
                CameraPose.id != pose_id,
            )
        )
        await self._execute(
            update(CameraPose)
            .where(
                CameraPose.image_id == target.image_id,
                CameraPose.is_selected.is_(True),
                CameraPose.id != pose_id,
            )
            .values(is_selected=False)
        )
        await self._execute(
            update(CameraPose).where(CameraPose.id == pose_id).values(is_selected=True)
        )
        return await self.refresh(target), previous

    async def delete_for_image(self, image_id: uuid.UUID) -> int:
        """Drop every pose of an image — a re-estimation starts from nothing.

        A DELETE rather than a supersede chain: unlike ``match_results``, no GCP cites a
        pose, so there is no evidence to protect and no ``RESTRICT`` to respect. The
        pose is a derived view of the match, and the match is what is kept.
        """
        stmt = delete(CameraPose).where(CameraPose.image_id == image_id)
        return int((await self._execute(stmt)).rowcount or 0)

    async def count_for_image(self, image_id: uuid.UUID) -> int:
        """How many pose candidates an image has."""
        stmt: Select[Any] = (
            select(func.count())
            .select_from(CameraPose)
            .where(CameraPose.image_id == image_id)
        )
        return int(await self._scalar(stmt) or 0)
