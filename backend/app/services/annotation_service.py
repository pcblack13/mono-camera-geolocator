"""``annotation_service`` — reads, checked single edits, and bulk upsert + versioning.

★ SCOPE.md §3: the annotation toolbar (point/polygon/polyline, undo/redo, delete) and the
per-point landmark fields are BUILT in full. This service owns the orchestration; the SQL —
the optimistic-concurrency ``update_checked``, the ledger ``append``, the revision
allocation — lives in the repositories (L6).

★ **Revision allocation is the undo/redo lock** (``ProjectRepository.allocate_revision_seq``)
and MUST run inside the same transaction as the writes it numbers. This service holds one
session and never commits, so that invariant is preserved by construction: the request is
the transaction boundary.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from sqlalchemy import null
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AnnotationNotFound,
    RevisionConflict,
    StaleAnnotationVersion,
)
from app.core.pagination import MAX_LIMIT, PaginationParams, SortKey, SortParams
from app.db.repositories.annotations import (
    AnnotationRepository,
    AnnotationVersionRepository,
    RevisionRepository,
)
from app.db.repositories.images import ImageRepository
from app.db.repositories.projects import ProjectRepository
from app.models.annotation import Annotation, AnnotationVersion
from app.models.enums import AnnotationKind, AnnotationOp
from app.models.image import Image
from app.models.revision import ProjectRevision
from app.schemas.annotation import (
    ANNOTATION_SORT_FIELDS,
    AnnotationApplyCounts,
    AnnotationBulkUpsertItem,
    AnnotationBulkUpsertRequest,
    AnnotationBulkUpsertResponse,
    AnnotationBulkUpsertResultItem,
    AnnotationCreate,
    AnnotationRead,
)
from app.schemas.common import RevisionSummary
from app.schemas.enums import AnnotationOp as WireAnnotationOp

__all__ = ["AnnotationService"]

#: The canvas load order (§6.2): drawing order, then insertion order. Matches the
#: routers' ``_DEFAULT_SORT`` so the "full resulting set" a bulk write returns is in
#: the same order a subsequent ``GET`` would produce.
_DEFAULT_SORT: tuple[SortKey, ...] = (
    SortKey("ordering", descending=False),
    SortKey("created_at", descending=False),
)


class AnnotationService:
    """Read, edit and version annotations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._annotations = AnnotationRepository(session)
        self._versions = AnnotationVersionRepository(session)
        self._revisions = RevisionRepository(session)
        self._projects = ProjectRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, annotation_id: uuid.UUID) -> Annotation:
        annotation = await self._annotations.get_active(annotation_id)
        if annotation is None:
            raise AnnotationNotFound(f"No annotation {annotation_id}.")
        return annotation

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        kind_csv: str | None = None,
        geom_type_csv: str | None = None,
        is_gcp_candidate: bool | None = None,
        confidence_gte: float | None = None,
        include_deleted: bool = False,
        touched_at_or_before_seq: int | None = None,
        q: str | None = None,
    ) -> tuple[Sequence[Annotation], int]:
        """``GET /images/{id}/annotations`` (16)."""
        return await self._annotations.list_for_image(
            image_id,
            pagination=pagination,
            sort=sort,
            kind_csv=kind_csv,
            geom_type_csv=geom_type_csv,
            is_gcp_candidate=is_gcp_candidate,
            confidence_gte=confidence_gte,
            include_deleted=include_deleted,
            touched_at_or_before_seq=touched_at_or_before_seq,
            q=q,
        )

    async def gcp_ids_for(
        self, annotation_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """``AnnotationRead.gcp_ids`` for many annotations, batched (no N+1)."""
        from app.db.repositories.gcps import GcpRepository

        return await GcpRepository(self._session).gcp_ids_for_annotations(annotation_ids)

    # ── checked single edits ──────────────────────────────────────────────────

    async def update_fields(
        self,
        annotation_id: uuid.UUID,
        *,
        expected_version_no: int | None,
        revision_seq: int,
        values: Mapping[str, Any],
        updated_by: str | None = None,
    ) -> Annotation:
        """A compare-and-set metadata/geometry edit (``PATCH /annotations/{id}``).

        Raises:
            AnnotationNotFound: no such live annotation.
            StaleAnnotationVersion: the ``If-Match`` version lost the optimistic race.
        """
        updated = await self._annotations.update_checked(
            annotation_id,
            expected_version_no=expected_version_no,
            revision_seq=revision_seq,
            values=values,
            updated_by=updated_by,
        )
        if updated is None:
            # The repo returns None for both "gone" and "stale"; distinguish so the client
            # gets the right status (404 vs 412).
            if await self._annotations.get_active(annotation_id) is None:
                raise AnnotationNotFound(f"No annotation {annotation_id}.")
            raise StaleAnnotationVersion(
                f"Annotation {annotation_id} was modified since version "
                f"{expected_version_no}; refetch and retry."
            )
        return updated

    async def allocate_revision(self, project_id: uuid.UUID) -> int:
        """Allocate the next revision sequence — the undo/redo lock.

        ★ Must be called inside the request transaction that also writes the edits it
        numbers (which is exactly what this service does — it never commits). The
        row-level lock serialises concurrent editors here and nowhere else.
        """
        return await self._projects.allocate_revision_seq(project_id)

    async def project_id_for_image(self, image: Image) -> uuid.UUID:
        """The project a set of annotations belongs to — where the revision seq is allocated."""
        return image.project_id

    # ── create / bulk / delete — the versioned write paths (§6.2) ──────────────

    async def create(
        self, image: Image, body: AnnotationCreate, *, actor_id: str | None
    ) -> Annotation:
        """Create one annotation from a **pixel** GeoJSON body (endpoint 17).

        ★ SCOPE.md §5: the created annotation is the photo endpoint of a manual
        correspondence. The GeoJSON ``geometry`` is IMAGE PIXELS (SRID 0), not
        geographic; the repository derives ``pixel_geom`` and the representative
        ``pixel_x``/``pixel_y`` from it in PostGIS so they cannot drift.

        The write is versioned in this transaction: a revision seq is allocated (the
        undo/redo lock), a ``project_revisions`` row opened, and a ``'create'`` ledger
        event appended. Nothing is committed — the request is the transaction boundary.
        """
        revision = await self._open_revision(image.project_id, actor_id=actor_id)
        ordering = (
            body.ordering
            if body.ordering
            else await self._annotations.next_ordering(image.id)
        )
        annotation = await self._annotations.insert(
            image_id=image.id,
            geom_type=body.geom_type.value,
            geometry_geojson=body.geometry.model_dump_json(),
            revision_seq=revision.seq,
            kind=body.kind.value,
            label=body.label,
            description=body.description,
            confidence=body.confidence,
            ordering=ordering,
            style=body.style,
            attributes=body.attributes,
            created_by=actor_id,
        )
        await self._append_event(
            annotation=annotation,
            revision_id=revision.id,
            op=AnnotationOp.CREATE.value,
            before=None,
            after=self._snapshot(annotation),
            actor_id=actor_id,
        )
        await self._finalise_revision(revision, image.id)
        return annotation

    async def bulk_upsert(
        self,
        image: Image,
        body: AnnotationBulkUpsertRequest,
        *,
        actor_id: str | None,
    ) -> AnnotationBulkUpsertResponse:
        """Apply the canvas "save" as one atomic, versioned batch (endpoint 18).

        ★ **All-or-nothing** (§6.2): one revision seq for the whole batch, one
        ``project_revisions`` row, one ledger event per applied item. A partial save on
        a survey annotation set is worse than no save. Nothing commits here; if any item
        raises, the request's transaction rolls the batch back whole.

        Honours the request's optimistic ``base_revision_seq`` (stale ⇒ ``409
        REVISION_CONFLICT``) and each item's ``version_no`` (stale ⇒ ``412
        STALE_ANNOTATION_VERSION``).
        """
        await self._check_base_revision(image.project_id, body.base_revision_seq)
        revision = await self._open_revision(
            image.project_id, label=body.revision_label, actor_id=actor_id
        )

        existing_ids = [it.id for it in body.items if it.id is not None]
        existing = (
            await self._annotations.get_many(existing_ids, image_id=image.id)
            if existing_ids
            else {}
        )

        counts = {"created": 0, "updated": 0, "deleted": 0, "restored": 0, "unchanged": 0}
        result_items: list[AnnotationBulkUpsertResultItem] = []
        next_ordering: int | None = None
        # ★ Ids the client is keeping (created or referenced). In ``replace`` mode, any live
        #   annotation NOT in this set is a deletion — see the replace-sweep after the loop.
        kept_ids: set[uuid.UUID] = set()

        for item in body.items:
            if item.op is WireAnnotationOp.CREATE:
                if item.ordering is not None:
                    ordering = item.ordering
                else:
                    if next_ordering is None:
                        next_ordering = await self._annotations.next_ordering(image.id)
                    ordering = next_ordering
                    next_ordering += 1
                annotation = await self._annotations.insert(
                    image_id=image.id,
                    geom_type=item.geom_type.value,  # required for create (schema)
                    geometry_geojson=item.geometry.model_dump_json(),
                    revision_seq=revision.seq,
                    kind=(item.kind or AnnotationKind.GENERIC).value,
                    label=item.label,
                    description=item.description,
                    confidence=item.confidence if item.confidence is not None else 1.0,
                    ordering=ordering,
                    style=item.style,
                    attributes=item.attributes,
                    created_by=actor_id,
                )
                await self._append_event(
                    annotation=annotation,
                    revision_id=revision.id,
                    op=AnnotationOp.CREATE.value,
                    before=None,
                    after=self._snapshot(annotation),
                    actor_id=actor_id,
                    client_op_id=body.client_op_id,
                )
                counts["created"] += 1
                kept_ids.add(annotation.id)
                result_items.append(
                    self._result_item(annotation, item, status="created")
                )
                continue

            current = existing.get(item.id)  # type: ignore[arg-type]  # id non-null off-create
            if current is None:
                raise AnnotationNotFound(
                    f"No annotation {item.id} on image {image.id}."
                )

            if item.op is WireAnnotationOp.DELETE:
                before = self._snapshot(current)
                deleted = await self._annotations.soft_delete_checked(
                    current.id,
                    expected_version_no=item.version_no,
                    revision_seq=revision.seq,
                    updated_by=actor_id,
                )
                self._raise_if_lost(deleted, current.id, item.version_no)
                await self._append_event(
                    annotation=deleted,
                    revision_id=revision.id,
                    op=AnnotationOp.DELETE.value,
                    before=before,
                    after=None,
                    actor_id=actor_id,
                )
                counts["deleted"] += 1
                result_items.append(self._result_item(deleted, item, status="deleted"))
            elif item.op is WireAnnotationOp.RESTORE:
                before = self._snapshot(current)
                restored = await self._annotations.restore_checked(
                    current.id, revision_seq=revision.seq, updated_by=actor_id
                )
                self._raise_if_lost(restored, current.id, item.version_no)
                after = self._snapshot(restored)
                await self._append_event(
                    annotation=restored,
                    revision_id=revision.id,
                    op=AnnotationOp.RESTORE.value,
                    before=before,
                    after=after,
                    actor_id=actor_id,
                )
                counts["restored"] += 1
                kept_ids.add(current.id)
                result_items.append(self._result_item(restored, item, status="restored"))
            else:  # UPDATE
                before = self._snapshot(current)
                values = self._update_values(item, current)
                updated = await self._annotations.update_checked(
                    current.id,
                    expected_version_no=item.version_no,
                    revision_seq=revision.seq,
                    values=values,
                    updated_by=actor_id,
                )
                self._raise_if_lost(updated, current.id, item.version_no)
                after = self._snapshot(updated)
                await self._append_event(
                    annotation=updated,
                    revision_id=revision.id,
                    op=AnnotationOp.UPDATE.value,
                    before=before,
                    after=after,
                    actor_id=actor_id,
                )
                counts["updated"] += 1
                kept_ids.add(current.id)
                result_items.append(self._result_item(updated, item, status="updated"))

        # ★ REPLACE MODE: the client sent its FULL live set, so any annotation still live on
        #   the image but absent from that set is a deletion. Without this sweep, a deleted
        #   landmark survives on the server and the client's autosave response (the full live
        #   set) re-adds it — the mark "reappears after deleting it". Versioned like any other
        #   delete so undo/history stay correct. (merge mode leaves absent rows untouched.)
        if body.mode == "replace":
            for a in await self._all_live_for_image(image.id):
                if a.id in kept_ids:
                    continue
                before = self._snapshot(a)
                deleted = await self._annotations.soft_delete_checked(
                    a.id,
                    expected_version_no=a.version_no,
                    revision_seq=revision.seq,
                    updated_by=actor_id,
                )
                if deleted is None:
                    continue
                await self._append_event(
                    annotation=deleted,
                    revision_id=revision.id,
                    op=AnnotationOp.DELETE.value,
                    before=before,
                    after=None,
                    actor_id=actor_id,
                )
                counts["deleted"] += 1

        await self._finalise_revision(revision, image.id)
        return await self._build_response(revision, counts, result_items, image.id)

    async def bulk_delete(
        self, image: Image, *, kind_csv: str | None, actor_id: str | None
    ) -> AnnotationBulkUpsertResponse:
        """Tombstone the whole canvas (or the given kinds), versioned (endpoint 19).

        One revision, one ledger event per tombstoned row. Returns the same response
        shape as :meth:`bulk_upsert` so the client replaces its store wholesale.
        """
        from app.db.repositories.base import csv_enum_filter

        revision = await self._open_revision(image.project_id, actor_id=actor_id)
        kinds = csv_enum_filter(kind_csv, [m.value for m in AnnotationKind]) or None

        live = await self._all_live_for_image(image.id, kind_csv=kind_csv)
        before_by_id = {a.id: self._snapshot(a) for a in live}

        tombstoned = await self._annotations.soft_delete_all_for_image(
            image.id, revision_seq=revision.seq, kinds=kinds, updated_by=actor_id
        )
        result_items: list[AnnotationBulkUpsertResultItem] = []
        for row in tombstoned:
            await self._append_event(
                annotation=row,
                revision_id=revision.id,
                op=AnnotationOp.DELETE.value,
                before=before_by_id.get(row.id, self._snapshot(row)),
                after=None,
                actor_id=actor_id,
            )
            result_items.append(
                AnnotationBulkUpsertResultItem(
                    id=row.id,
                    client_ref=None,
                    op=WireAnnotationOp.DELETE,
                    status="deleted",
                    version_no=row.version_no,
                )
            )

        counts = {
            "created": 0,
            "updated": 0,
            "deleted": len(result_items),
            "restored": 0,
            "unchanged": 0,
        }
        await self._finalise_revision(revision, image.id)
        return await self._build_response(revision, counts, result_items, image.id)

    async def delete(self, annotation_id: uuid.UUID, *, actor_id: str | None) -> Annotation:
        """Tombstone one annotation and return the deleted row (endpoint 22).

        ★ Returns ``200 AnnotationRead`` with ``is_deleted: true`` (not a 204): the
        client needs the new ``version_no`` for its ETag and the undo stack needs the
        row to survive (§5.6). Versioned with a ``'delete'`` ledger event.
        """
        current = await self._annotations.get_active(annotation_id)
        if current is None:
            raise AnnotationNotFound(f"No annotation {annotation_id}.")
        before = self._snapshot(current)
        image = await ImageRepository(self._session).get(current.image_id)
        if image is None:  # pragma: no cover — the annotation's image FK is ON DELETE CASCADE.
            raise AnnotationNotFound(f"No image for annotation {annotation_id}.")
        revision = await self._open_revision(image.project_id, actor_id=actor_id)
        deleted = await self._annotations.soft_delete_checked(
            annotation_id,
            expected_version_no=None,
            revision_seq=revision.seq,
            updated_by=actor_id,
        )
        if deleted is None:  # pragma: no cover — we just read it as active.
            raise AnnotationNotFound(f"No annotation {annotation_id}.")
        await self._append_event(
            annotation=deleted,
            revision_id=revision.id,
            op=AnnotationOp.DELETE.value,
            before=before,
            after=None,
            actor_id=actor_id,
        )
        await self._finalise_revision(revision, deleted.image_id)
        return deleted

    # ── internals shared by the write paths ────────────────────────────────────

    async def _open_revision(
        self, project_id: uuid.UUID, *, label: str | None = None, actor_id: str | None = None
    ) -> ProjectRevision:
        """Allocate the next seq (the undo/redo lock) and open a non-checkpoint revision.

        The allocation and the revision row are one transaction with the writes they
        number — this service never commits — so a concurrent editor blocks on the
        project row rather than racing for the seq (§5.6).
        """
        seq = await self._projects.allocate_revision_seq(project_id)
        revision = ProjectRevision(
            project_id=project_id,
            seq=seq,
            label=label,
            actor_id=actor_id,
            is_checkpoint=False,
        )
        return await self._revisions.create(revision)

    async def _finalise_revision(
        self, revision: ProjectRevision, image_id: uuid.UUID
    ) -> None:
        """Stamp the live annotation count onto the revision for ``RevisionSummary``."""
        revision.annotation_count = await self._annotations.count_active(image_id)
        await self._revisions.flush()

    async def _check_base_revision(
        self, project_id: uuid.UUID, base_revision_seq: int | None
    ) -> None:
        """Optimistic concurrency for the whole SET: stale base ⇒ ``409``."""
        if base_revision_seq is None:
            return
        project = await self._projects.get(project_id)
        current = project.current_revision_seq if project is not None else 0
        if base_revision_seq != current:
            raise RevisionConflict(
                f"The annotation set changed since revision {base_revision_seq} "
                f"(current is {current}); refetch and retry."
            )

    async def _append_event(
        self,
        *,
        annotation: Annotation,
        revision_id: uuid.UUID,
        op: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor_id: str | None,
        client_op_id: str | None = None,
    ) -> AnnotationVersion:
        """Append one append-only ledger event for a write (§5.6).

        ``version_no`` is read off the resulting annotation, and ``pixel_geom_after`` is
        the row's stored geometry for canvas "ghost" rendering (NULL for a delete). The
        ``before``/``after`` biconditional (``ck_annotation_versions_payload``) is the
        caller's contract — ``create`` passes ``before=None``, ``delete`` ``after=None``.
        """
        # ★ JSONB defaults ``none_as_null=False``, so a Python ``None`` becomes the JSON
        #   literal ``null`` — which is ``IS NOT NULL`` in SQL and would break the
        #   ``op``/``before``/``after`` biconditional (``ck_annotation_versions_payload``).
        #   ``null()`` is a real SQL NULL, which the CHECK requires.
        event = AnnotationVersion(
            annotation_id=annotation.id,
            image_id=annotation.image_id,
            revision_id=revision_id,
            op=op,
            version_no=annotation.version_no,
            before=before if before is not None else null(),
            after=after if after is not None else null(),
            pixel_geom_after=annotation.pixel_geom if after is not None else None,
            actor_id=actor_id,
            client_op_id=client_op_id,
        )
        return await self._versions.append(event)

    def _update_values(
        self, item: AnnotationBulkUpsertItem, current: Annotation
    ) -> dict[str, Any]:
        """Translate a bulk update item into the columns ``update_checked`` sets.

        Only fields the client sent are included. A ``geometry`` change is translated to
        ``pixel_geom`` + the re-derived ``pixel_x``/``pixel_y`` in PostGIS; when the item
        sends geometry without ``geom_type`` the stored type is used (the schema only
        cross-checks the two when both are present).
        """
        values: dict[str, Any] = {}
        if item.kind is not None:
            values["kind"] = item.kind.value
        if item.geom_type is not None:
            values["geom_type"] = item.geom_type.value
        if item.label is not None:
            values["label"] = item.label
        if item.description is not None:
            values["description"] = item.description
        if item.confidence is not None:
            values["confidence"] = item.confidence
        if item.ordering is not None:
            values["ordering"] = item.ordering
        if item.style is not None:
            values["style"] = item.style
        if item.attributes is not None:
            values["attributes"] = item.attributes
        if item.geometry is not None:
            geom_type = (
                item.geom_type.value
                if item.geom_type is not None
                else str(getattr(current.geom_type, "value", current.geom_type))
            )
            values["geom_type"] = geom_type
            values.update(
                self._annotations.pixel_geom_values(
                    geom_type, item.geometry.model_dump_json()
                )
            )
        return values

    @staticmethod
    def _raise_if_lost(
        result: Annotation | None, annotation_id: uuid.UUID, expected_version_no: int | None
    ) -> None:
        """A ``None`` from a checked write is a stale ETag (the row is present)."""
        if result is None:
            raise StaleAnnotationVersion(
                f"Annotation {annotation_id} was modified since version "
                f"{expected_version_no}; refetch and retry."
            )

    @staticmethod
    def _result_item(
        annotation: Annotation, item: AnnotationBulkUpsertItem, *, status: str
    ) -> AnnotationBulkUpsertResultItem:
        return AnnotationBulkUpsertResultItem(
            id=annotation.id,
            client_ref=item.client_ref,
            op=item.op,
            status=status,  # type: ignore[arg-type]  # Literal validated by pydantic
            version_no=annotation.version_no,
        )

    def _snapshot(self, annotation: Annotation) -> dict[str, Any]:
        """A JSON-safe full-field snapshot of an annotation for the ledger payload.

        ``geometry`` is the decoded ``pixel_geom`` (GeoJSON-shaped IMAGE PIXELS), so the
        ledger carries enough to render a diff and to reconstruct the row on restore.
        """
        from app.api.presenters import decode_geometry

        return {
            "kind": str(getattr(annotation.kind, "value", annotation.kind)),
            "geom_type": str(getattr(annotation.geom_type, "value", annotation.geom_type)),
            "pixel_x": float(annotation.pixel_x),
            "pixel_y": float(annotation.pixel_y),
            "geometry": decode_geometry(annotation.pixel_geom),
            "label": annotation.label,
            "description": annotation.description,
            "confidence": float(annotation.confidence),
            "ordering": int(annotation.ordering),
            "style": dict(annotation.style or {}),
            "attributes": dict(annotation.attributes or {}),
            "version_no": int(annotation.version_no),
            "is_deleted": bool(annotation.is_deleted),
        }

    def _all_sort(self) -> SortParams:
        """The canvas-load sort, for reading a whole image's live set back."""
        return SortParams.parse(None, allowed=ANNOTATION_SORT_FIELDS, default=_DEFAULT_SORT)

    async def _all_live_for_image(
        self, image_id: uuid.UUID, *, kind_csv: str | None = None
    ) -> list[Annotation]:
        """Every live annotation on an image, paged past the ``MAX_LIMIT`` (200) cap.

        The per-image cap is ``MAX_ANNOTATIONS_PER_IMAGE`` (2000) but a single page is
        bounded at ``MAX_LIMIT``, so the whole live set is assembled in ``ceil(n/200)``
        index scans rather than one over-large query.
        """
        rows: list[Annotation] = []
        offset = 0
        sort = self._all_sort()
        while True:
            chunk, total = await self._annotations.list_for_image(
                image_id,
                pagination=PaginationParams(limit=MAX_LIMIT, offset=offset),
                sort=sort,
                kind_csv=kind_csv,
                include_deleted=False,
            )
            rows.extend(chunk)
            offset += len(chunk)
            if not chunk or offset >= total:
                return rows

    def _revision_summary(self, revision: ProjectRevision) -> RevisionSummary:
        return RevisionSummary(
            id=revision.id,
            project_id=revision.project_id,
            seq=revision.seq,
            label=revision.label,
            is_checkpoint=revision.is_checkpoint,
            annotation_count=revision.annotation_count,
            created_at=revision.created_at,
        )

    async def present_live_set(self, image_id: uuid.UUID) -> list[AnnotationRead]:
        """The full live annotation set of an image as wire ``AnnotationRead`` rows.

        ★ Batches ``gcp_ids`` (no N+1). Used to fill ``AnnotationBulkUpsertResponse
        .annotations`` — the client replaces its store wholesale rather than
        reconciling deltas (§6.2).
        """
        from app.api.presenters import to_annotation_read

        rows = await self._all_live_for_image(image_id)
        gcp_map = await self.gcp_ids_for([r.id for r in rows])
        return [
            to_annotation_read(r, gcp_ids=gcp_map.get(r.id, [])) for r in rows
        ]

    async def _build_response(
        self,
        revision: ProjectRevision,
        counts: Mapping[str, int],
        result_items: list[AnnotationBulkUpsertResultItem],
        image_id: uuid.UUID,
    ) -> AnnotationBulkUpsertResponse:
        return AnnotationBulkUpsertResponse(
            revision=self._revision_summary(revision),
            applied=AnnotationApplyCounts(**dict(counts)),
            items=result_items,
            annotations=await self.present_live_set(image_id),
            warnings=[],
        )
