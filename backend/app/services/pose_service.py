"""``pose_service`` — fronts DEFERRED camera-pose estimation.

★ SCOPE.md §4: camera pose (yaw/pitch/roll) estimation is an ABC only. The *run* path
(``POST /images/{id}/camera-pose``, endpoint 48) raises
:class:`~app.core.exceptions.FeatureDeferredError` → ``501`` + ``feature: "deferred"``.

The read (``GET /images/{id}/camera-pose``, endpoint 49) is real against the empty
``camera_poses`` table. A photograph with no pose is a
:class:`~app.core.exceptions.CameraPoseNotAvailable` (404) — deliberately distinct from
the 501 the run path returns: 404 is "this live path has no row", 501 is "this feature is
not built".
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import FeatureDeferredError
from app.db.repositories.poses import CameraPoseRepository

__all__ = ["PoseService"]

_COMPONENT = "ai_engine.geometry.pose"
_DEFERRED_MESSAGE = (
    "Automatic camera-pose estimation is not enabled in this build. Place GCPs manually."
)


class PoseService:
    """Camera pose — deferred run path, real reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = CameraPoseRepository(session)

    def estimate(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/camera-pose`` (48) — **DEFERRED** (501)."""
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)

    async def get_selected_for_image(self, image_id: uuid.UUID):
        """``GET /images/{id}/camera-pose`` (49) — real; None in this build."""
        return await self._repo.get_selected_for_image(image_id)

    async def get_selected_or_raise(self, image_id: uuid.UUID):
        """The pose or ``CameraPoseNotAvailable`` (404). Empty in this build."""
        return await self._repo.get_selected_or_raise(image_id)
