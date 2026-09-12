"""``image_cameras`` — :class:`ImageCameraRepository`.

★ The smallest repository in the package, because the table is 1:1 with ``images``
and keyed on ``image_id``: there is nothing to list, sort or paginate — a camera
is fetched by its image, written by its image, and removed by its image.
:meth:`BaseRepository.get` already serves the fetch (the PK *is* ``image_id``);
this class adds only the idempotent delete.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete

from app.db.repositories.base import BaseRepository
from app.models.image_camera import ImageCamera

__all__ = ["ImageCameraRepository"]


class ImageCameraRepository(BaseRepository[ImageCamera]):
    """One entered camera per image; fetched and replaced whole."""

    model = ImageCamera

    async def delete_for_image(self, image_id: uuid.UUID) -> bool:
        """Remove the station. **Idempotent** — a second call matches nothing.

        Returns:
            True when a row was deleted, False when there was none. The router
            answers 204 either way: the caller asked for no station to exist,
            and none does.
        """
        stmt = (
            delete(ImageCamera)
            .where(ImageCamera.image_id == image_id)
            .returning(ImageCamera.image_id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None
