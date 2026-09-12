"""``images`` — :class:`ImageRepository`.

The de-duplication read (:meth:`ImageRepository.find_by_checksum`) is the one worth
reading twice: ``uq_images_project_checksum`` is a **partial** unique index
(``WHERE deleted_at IS NULL``), so the pre-check and the constraint must agree about
soft-deleted rows or an upload that should have been a 200-with-the-existing-image
becomes a 500.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    constraint_name_of,
    csv_enum_filter,
    like_escape,
)
from app.models.enums import ImageStatus
from app.models.image import Image

__all__ = ["ImageRepository"]


class ImageRepository(BaseRepository[Image]):
    """Uploaded photographs and GeoTIFFs."""

    model = Image

    @property
    def _sortable(self) -> SortableColumns:
        """``IMAGE_SORT_FIELDS`` resolved onto SQL."""
        return {
            "filename": Image.filename,
            "uploaded_at": Image.uploaded_at,
            "created_at": Image.created_at,
            "updated_at": Image.updated_at,
            "size_bytes": Image.size_bytes,
            "captured_at": Image.captured_at,
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_active(self, image_id: uuid.UUID) -> Image | None:
        """One image, excluding soft-deleted rows. The default read."""
        return await self._scalar_one_or_none(
            select(Image).where(Image.id == image_id, Image.deleted_at.is_(None))
        )

    async def list_images(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        status_csv: str | None = None,
        is_geotiff: bool | None = None,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Image], int]:
        """``GET /images`` (10).

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``IMAGE_SORT_FIELDS``.
            project_id: Restrict to one project. Uses ``ix_images_project_uploaded``.
            status_csv: ``?status=processing,failed``.
            is_geotiff: ★ A property **discovered** at ingest, never a declared type.
            q: Free-text over ``filename`` + ``notes``. ``filename`` carries the trigram
                GIN index.
            include_deleted: Include soft-deleted images.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(Image)
        if not include_deleted:
            stmt = stmt.where(Image.deleted_at.is_(None))
        if project_id is not None:
            stmt = stmt.where(Image.project_id == project_id)
        statuses = csv_enum_filter(status_csv, [m.value for m in ImageStatus])
        if statuses:
            stmt = stmt.where(Image.status.in_(statuses))
        if is_geotiff is not None:
            stmt = stmt.where(Image.is_geotiff.is_(is_geotiff))
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(
                or_(
                    Image.filename.ilike(pattern, escape="\\"),
                    Image.notes.ilike(pattern, escape="\\"),
                )
            )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def find_by_checksum(
        self, project_id: uuid.UUID, checksum_sha256: str
    ) -> Image | None:
        """The de-duplication read behind a re-upload.

        ★ **``deleted_at IS NULL`` is not an optional nicety here.**
        ``uq_images_project_checksum`` is a *partial* unique index with exactly that
        predicate, so a soft-deleted image does **not** occupy the slot. A pre-check
        that ignored the predicate would find the tombstone, report "already uploaded",
        and hand the surveyor back a deleted image; one that checked a *different*
        predicate than the index would let an insert through that the index then
        rejects. The two must agree, and this is where they do.

        Args:
            project_id: Scope — the same file in two projects is two images.
            checksum_sha256: Lowercase hex, 64 chars (``ck_images_checksum_hex``).

        Returns:
            The existing image, or None.
        """
        return await self._scalar_one_or_none(
            select(Image).where(
                Image.project_id == project_id,
                Image.checksum_sha256 == checksum_sha256,
                Image.deleted_at.is_(None),
            )
        )

    async def find_by_storage_path(self, storage_path: str) -> Image | None:
        """Reverse lookup for the storage GC sweep. ``uq_images_storage_path``."""
        return await self._scalar_one_or_none(
            select(Image).where(Image.storage_path == storage_path)
        )

    async def list_for_project(
        self, project_id: uuid.UUID, *, only_ready: bool = False
    ) -> Sequence[Image]:
        """Every live image of a project, ordered. For batch fan-out and exports.

        Unpaginated: a batch is defined over the whole set, and a batch whose membership
        depended on a page size would be a different batch each time it ran.

        Args:
            project_id: The project.
            only_ready: Restrict to ``status='ready'`` — an image still processing has
                no dimensions or EXIF yet, so a batch that included it would fan out to
                tasks that immediately fail.
        """
        stmt = select(Image).where(
            Image.project_id == project_id, Image.deleted_at.is_(None)
        )
        if only_ready:
            stmt = stmt.where(Image.status == ImageStatus.READY)
        return await self._scalars(stmt.order_by(Image.uploaded_at.asc(), Image.id.asc()))

    async def exists_in_project(self, image_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Whether an image belongs to a project — the batch-membership guard."""
        stmt = (
            select(func.count())
            .select_from(Image)
            .where(
                Image.id == image_id,
                Image.project_id == project_id,
                Image.deleted_at.is_(None),
            )
        )
        return bool(await self._scalar(stmt))

    # ── writes ───────────────────────────────────────────────────────────────

    async def insert(self, image: Image) -> Image:
        """Stage and flush an image, mapping the duplicate-upload constraint.

        Raises:
            IntegrityError: re-raised untouched for any constraint other than the two
                named below — guessing which one fired is how a 409 lands on a 500.
        """
        self.add(image)
        try:
            await self.flush()
        except IntegrityError as exc:
            name = constraint_name_of(exc)
            if name == "uq_images_project_checksum":
                # Not mapped to a domain error here: §6.2 makes a duplicate upload a
                # *success* that returns the existing image, and only the service knows
                # whether this caller wants that or a 409. This layer reports the fact.
                raise
            if name == "uq_images_storage_path":
                raise
            raise
        return image

    async def set_status(
        self,
        image_id: uuid.UUID,
        status: ImageStatus,
        *,
        from_statuses: Sequence[ImageStatus] | None = None,
    ) -> bool:
        """Move an image's ingest status, optionally as a compare-and-set.

        ``ingest_image_task`` and the API both write this column, so the guarded form
        exists for the same reason the job transitions are guarded: a late ``processing``
        must not overwrite a ``ready`` that a faster path already recorded.

        Args:
            image_id: The image.
            status: The new status.
            from_statuses: The states the caller believes it is in. None ⇒ unguarded.

        Returns:
            True when a row moved.
        """
        stmt = update(Image).where(Image.id == image_id)
        if from_statuses:
            stmt = stmt.where(Image.status.in_([s.value for s in from_statuses]))
        stmt = stmt.values(status=status).returning(Image.id)
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def update_dimensions(
        self,
        image_id: uuid.UUID,
        *,
        width: int,
        height: int,
        checksum_sha256: str,
        size_bytes: int,
    ) -> bool:
        """★ Record a rescale's new raster facts, in one statement.

        ``POST /images/{id}/rescale`` resized the stored bytes: the pixel grid, the
        content hash and the byte count all changed together, and they are written
        together so the row never describes bytes that no longer exist. ``width``/
        ``height`` feed every coordinate transform on the frontend; ``checksum_sha256``
        keeps ``uq_images_project_checksum`` honest about the file it now points at; and
        ``size_bytes`` keeps ``GET /images/{id}/file``'s ``Content-Length`` truthful.

        This is the DB half of the rescale transaction and is executed **before** the
        storage overwrite, so that if either the scaling UPDATEs or the storage write
        fail the whole request transaction rolls back and the row keeps its old bytes.

        Returns:
            True when the row existed and was updated.
        """
        stmt = (
            update(Image)
            .where(Image.id == image_id)
            .values(
                width=width,
                height=height,
                checksum_sha256=checksum_sha256,
                size_bytes=size_bytes,
            )
            .returning(Image.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def soft_delete(self, image_id: uuid.UUID) -> bool:
        """Set ``deleted_at``. Idempotent.

        ★ Frees the ``uq_images_project_checksum`` slot, by design: the index's
        ``WHERE deleted_at IS NULL`` means a soft-deleted image no longer blocks a
        re-upload of the same file. A surveyor who deletes a photo and uploads it again
        expects that to work.
        """
        stmt = (
            update(Image)
            .where(Image.id == image_id, Image.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Image.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def soft_delete_all_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every live image of a project. Returns the count affected.

        ★ Called when a PROJECT is deleted, so its photographs stop appearing in the image
        list and the dashboard's photo count. Deleting a project does not cascade in the DB
        (the FK is ``ON DELETE RESTRICT``-shaped for a soft-delete world), so the cascade is
        applied here in the same request transaction — otherwise a deleted project's images
        stay live and the counts drift.
        """
        stmt = (
            update(Image)
            .where(Image.project_id == project_id, Image.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Image.id)
        )
        return len((await self._execute(stmt)).scalars().all())

    async def restore(self, image_id: uuid.UUID) -> bool:
        """Clear ``deleted_at``. Idempotent.

        May raise ``IntegrityError`` on ``uq_images_project_checksum`` if the same file
        was re-uploaded while this one was deleted — two live rows would then hold one
        checksum. That is the constraint doing its job, and the caller must decide which
        of the two images the surveyor meant.
        """
        stmt = (
            update(Image)
            .where(Image.id == image_id, Image.deleted_at.isnot(None))
            .values(deleted_at=None)
            .returning(Image.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None


async def count_points_per_image(
    db: Any, image_ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """GCP and annotation counts per image, in two dicts keyed by image id.

    ★ Lives HERE, not in the router (2026-09-02): the .importlinter contract
    forbids ``app.api.v1`` importing ``app.models`` directly, and the image-list
    endpoint's count query was the one place that did. Same query, right layer.
    """
    gcp_counts: dict[uuid.UUID, int] = {}
    annotation_counts: dict[uuid.UUID, int] = {}
    if not image_ids:
        return gcp_counts, annotation_counts
    from app.models.annotation import Annotation
    from app.models.gcp import GCP

    for model, sink in ((GCP, gcp_counts), (Annotation, annotation_counts)):
        result = await db.execute(
            select(model.image_id, func.count())
            .where(model.image_id.in_(image_ids))
            .group_by(model.image_id)
        )
        sink.update({row[0]: row[1] for row in result.all()})
    return gcp_counts, annotation_counts
