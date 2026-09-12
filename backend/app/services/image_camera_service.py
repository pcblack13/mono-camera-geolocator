"""``image_camera_service`` — the photograph's entered camera (intrinsics + position + tilt).

Thin by design: the camera is one row fetched whole and replaced whole. The three
things that are policy rather than SQL:

1. **Every operation 404s on a dead image first.** The camera is an attribute of a
   live photograph; writing one against a soft-deleted image would resurrect data the
   user believes gone.
2. **PUT is an upsert with full-replace semantics.** The image's setup page saves the
   whole form; an omitted field *is* a cleared field.
3. **The wire speaks ``lat``/``lon``; the row stores a PostGIS point.** The conversion
   happens here — in both directions the pair is kept whole (the schema already
   refuses a lone latitude).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImageNotFound
from app.db.repositories.image_cameras import ImageCameraRepository
from app.db.repositories.images import ImageRepository
from app.db.types import point_wkt
from app.models.image_camera import ImageCamera
from app.schemas.image_camera import ImageCameraPut

__all__ = ["ImageCameraService"]

#: The scalar columns PUT replaces verbatim — everything except ``position``, which
#: is assembled from the (lat, lon) pair.
_SCALAR_FIELDS = (
    "fx",
    "fy",
    "cx",
    "cy",
    "k1",
    "k2",
    "p1",
    "p2",
    "k3",
    "img_w",
    "img_h",
    # GEO-DRIFT-UPDATE C2 — a calibration is optional; these carry the alternative
    # (and the provenance that it WAS the alternative).
    "no_calibration",
    "fov_h_deg",
    "fov_v_deg",
    "mast_offset_m",
    "tilt_deg",
    "auto_gcp_enabled",
)


class ImageCameraService:
    """Get, upsert and delete the one entered camera a photograph may have."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cameras = ImageCameraRepository(session)
        self._images = ImageRepository(session)

    async def get(self, image_id: uuid.UUID) -> ImageCamera | None:
        """The camera, or ``None`` when the photograph has not saved one.

        Raises:
            ImageNotFound: no such live image — so the caller can tell "no camera
                yet" (200, ``configured: false``) apart from "no such image" (404),
                which are different answers.
        """
        await self._require_image(image_id)
        return await self._cameras.get(image_id)

    async def put(self, image_id: uuid.UUID, body: ImageCameraPut) -> ImageCamera:
        """``PUT /images/{id}/camera`` — create or fully replace the camera.

        Idempotent: the resulting row is a function of the body alone. ``{}``
        clears every field but keeps the row; DELETE removes it.
        """
        await self._require_image(image_id)
        camera = await self._cameras.get(image_id)
        if camera is None:
            camera = ImageCamera(image_id=image_id)
            self._cameras.add(camera)

        for field in _SCALAR_FIELDS:
            setattr(camera, field, getattr(body, field))
        # ★ The schema guarantees lat/lon arrive as a pair; POINT is (lon lat) — x y.
        camera.position = (
            point_wkt(body.lon, body.lat)
            if body.lat is not None and body.lon is not None
            else None
        )

        await self._cameras.flush()
        # ★ ``updated_at`` (and on insert ``created_at``) are server-maintained —
        #   the trigger/default changed them at flush time and SQLAlchemy holds them
        #   EXPIRED. The re-read is explicit and awaited here; reading them in the
        #   synchronous presenter would raise ``MissingGreenlet``.
        await self._cameras.refresh(camera)
        return camera

    async def delete(self, image_id: uuid.UUID) -> bool:
        """``DELETE /images/{id}/camera`` — **idempotent**.

        Returns:
            True when a camera was removed, False when there was none.
        """
        await self._require_image(image_id)
        return await self._cameras.delete_for_image(image_id)

    # ── internals ─────────────────────────────────────────────────────────────

    async def _require_image(self, image_id: uuid.UUID) -> None:
        if await self._images.get_active(image_id) is None:
            raise ImageNotFound(f"No image {image_id}.")
