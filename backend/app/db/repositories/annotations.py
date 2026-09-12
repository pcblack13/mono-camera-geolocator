"""``annotations`` · ``annotation_versions`` · ``project_revisions``, and **replay**.

Three tables, one module, because they are one mechanism: the hybrid event-log +
rolling-snapshot versioning design (§5.6). Splitting them would put the replay join —
``annotation_versions`` → ``project_revisions`` → ``seq`` — in a file that owns neither
side of it.

★ **Optimistic locking is a compare-and-set, exactly like the job transitions.**
``PATCH /annotations/{id}`` requires ``If-Match``; the ETag is ``version_no``. So the
update carries the expected version in its ``WHERE``:

    UPDATE annotations SET ..., version_no = version_no + 1
     WHERE id = :id AND version_no = :expected

A stale writer matches nothing and gets ``None``, which the service reports as ``412
STALE_ANNOTATION_VERSION``. The read-check-write alternative loses the second surveyor's
edit and tells them it succeeded.

★ **The ledger tolerates dangling references, on purpose.** ``annotation_versions``
carries no FK to ``annotations`` (§5.6): under one, a ``'create'`` event for a row that
was later hard-deleted would force us either to cascade-delete the audit trail or to
block the delete. **An append-only log that outlives its subject is the point**, not an
oversight, so the "annotation" of an event is a plain indexed UUID and this module never
joins the two as if it were a foreign key.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, Mapping, Sequence

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.sql import ColumnElement

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    csv_enum_filter,
    like_escape,
)
from app.models.annotation import Annotation, AnnotationVersion
from app.models.enums import AnnotationGeomType, AnnotationKind
from app.models.image import Image
from app.models.revision import ProjectRevision

__all__ = [
    "GCP_CANDIDATE_KINDS",
    "AnnotationRepository",
    "AnnotationVersionRepository",
    "RevisionRepository",
    "normalise_pixel_geom",
]

#: ★ ``AnnotationRead.is_gcp_candidate`` is **derived, not stored**, and this is the
#: derivation — mirrored from ``app.schemas.annotation`` (which owns the wire meaning)
#: because ``app.db`` may not import ``app.schemas`` (§10.2) and the ``?is_gcp_candidate=``
#: filter has to be expressible in SQL.
#:
#: ★ There is deliberately **no ``geom_type = 'point'`` clause**, and the two files agree
#: on why: the representative point *is* the candidate location for any geometry type —
#: that is what it is for — and ``gcps.landmark_id`` is FK'd to the general
#: ``annotations`` table precisely so that a polygon's corner can be a GCP.
GCP_CANDIDATE_KINDS: Final[frozenset[str]] = frozenset(
    {
        AnnotationKind.FIELD_CORNER.value,
        AnnotationKind.ROAD_INTERSECTION.value,
        AnnotationKind.BUILDING_CORNER.value,
    }
)


def normalise_pixel_geom(geom: Any) -> ColumnElement[Any]:
    """``ST_ForcePolygonCW(geom)`` — the write-time ring normalisation (§5.2).

    ★ **Why winding order is normalised at all**, given §5.2 also says not to attach
    meaning to it in pixel space: because the versioning system compares annotations for
    equality, and two byte-different encodings of one identical polygon would produce a
    spurious ``'update'`` event with a ``before``/``after`` pair that differ in nothing a
    human can see. Normalising makes byte-level equality *mean* geometric equality.

    ★ **Application-side, not a trigger** (§5.2). A trigger would rewrite the geometry
    after the ledger's ``after`` payload was computed from the un-normalised value, so
    the stored row and its own audit record would disagree — the one place they must not.

    Non-polygonal geometries are returned unchanged by PostGIS, so this is applied
    unconditionally rather than branching on ``geom_type``: a branch is a chance to
    forget, and there is nothing to gain by getting it right only most of the time.
    """
    return func.ST_ForcePolygonCW(geom)


class AnnotationRepository(BaseRepository[Annotation]):
    """Landmarks drawn on a photograph, in image pixel space."""

    model = Annotation

    @property
    def _sortable(self) -> SortableColumns:
        """``ANNOTATION_SORT_FIELDS`` resolved onto SQL."""
        return {
            "ordering": Annotation.ordering,
            "created_at": Annotation.created_at,
            "updated_at": Annotation.updated_at,
            "kind": Annotation.kind,
            "confidence": Annotation.confidence,
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_active(self, annotation_id: uuid.UUID) -> Annotation | None:
        """One annotation, excluding tombstones.

        ``is_deleted`` is a tombstone, not a soft delete of the §5.4 kind: the row
        survives its own deletion so the ledger stays referential. Reads that mean "what
        is on the canvas" want this; the undo path wants :meth:`get` and the tombstone.
        """
        return await self._scalar_one_or_none(
            select(Annotation).where(
                Annotation.id == annotation_id, Annotation.is_deleted.is_(False)
            )
        )

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
        """``GET /images/{image_id}/annotations`` (16).

        Args:
            image_id: The photograph.
            pagination: Validated limit/offset. The canvas loads them all (limit 2000).
            sort: Whitelisted against ``ANNOTATION_SORT_FIELDS``.
            kind_csv: ``?kind=field_corner,tree``.
            geom_type_csv: ``?geom_type=point,polygon``.
            is_gcp_candidate: Derived from ``kind`` — see :data:`GCP_CANDIDATE_KINDS`.
            confidence_gte: 0–1, the **surveyor's** certainty, not the algorithm's.
            include_deleted: Include tombstones.
            touched_at_or_before_seq: ★ **Not time travel.** ``annotations.revision_seq``
                records the revision that *last touched* this row, so this filter answers
                "which annotations have not changed since revision N" — an annotation
                edited later is excluded entirely rather than shown in its older state.
                **True "state as of revision N" is a replay**, from the nearest preceding
                checkpoint through :meth:`AnnotationVersionRepository.replay_events`, and
                that is what ``revision_service`` must use for ``?revision_seq=``. The
                parameter is named for what it does so the two cannot be confused.
            q: Free-text over ``label`` + ``description``.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(Annotation).where(Annotation.image_id == image_id)
        if not include_deleted:
            stmt = stmt.where(Annotation.is_deleted.is_(False))
        kinds = csv_enum_filter(kind_csv, [m.value for m in AnnotationKind])
        if kinds:
            stmt = stmt.where(Annotation.kind.in_(kinds))
        geom_types = csv_enum_filter(geom_type_csv, [m.value for m in AnnotationGeomType])
        if geom_types:
            stmt = stmt.where(Annotation.geom_type.in_(geom_types))
        if is_gcp_candidate is not None:
            predicate = Annotation.kind.in_(sorted(GCP_CANDIDATE_KINDS))
            stmt = stmt.where(predicate if is_gcp_candidate else ~predicate)
        if confidence_gte is not None:
            stmt = stmt.where(Annotation.confidence >= confidence_gte)
        if touched_at_or_before_seq is not None:
            stmt = stmt.where(Annotation.revision_seq <= touched_at_or_before_seq)
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(
                or_(
                    Annotation.label.ilike(pattern, escape="\\"),
                    Annotation.description.ilike(pattern, escape="\\"),
                )
            )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_active_for_project(
        self, project_id: uuid.UUID
    ) -> Sequence[Annotation]:
        """Every live annotation across a project's (non-deleted) images.

        The authoritative current state a revision restore diffs the target against —
        ``annotations`` carries no ``project_id``, so it joins through ``images``.
        Unpaginated: a restore is a whole-project operation, not a page.
        """
        stmt = (
            select(Annotation)
            .join(Image, Image.id == Annotation.image_id)
            .where(
                Image.project_id == project_id,
                Image.deleted_at.is_(None),
                Annotation.is_deleted.is_(False),
            )
            .order_by(Annotation.image_id, Annotation.ordering, Annotation.created_at)
        )
        return await self._scalars(stmt)

    async def get_many(
        self, annotation_ids: Sequence[uuid.UUID], *, image_id: uuid.UUID | None = None
    ) -> dict[uuid.UUID, Annotation]:
        """Load many annotations by id in one query — the bulk-upsert pre-read.

        ``PUT /images/{id}/annotations`` arrives with up to 2000 items, each naming an
        id and a ``version_no``. Fetching them one at a time is 2000 round trips before
        the first write.

        Args:
            annotation_ids: The ids. Empty ⇒ ``{}``, no query.
            image_id: Scope. Supplied, an id belonging to another image simply does not
                come back — which the caller reports as "unknown annotation" rather than
                editing a stranger's canvas.
        """
        if not annotation_ids:
            return {}
        stmt = select(Annotation).where(Annotation.id.in_(list(annotation_ids)))
        if image_id is not None:
            stmt = stmt.where(Annotation.image_id == image_id)
        return {a.id: a for a in await self._scalars(stmt)}

    async def count_active(self, image_id: uuid.UUID) -> int:
        """Live annotations on an image. Gates ``MAX_ANNOTATIONS_PER_IMAGE`` (2000)."""
        return int(
            await self._scalar(
                select(func.count())
                .select_from(Annotation)
                .where(Annotation.image_id == image_id, Annotation.is_deleted.is_(False))
            )
            or 0
        )

    async def next_ordering(self, image_id: uuid.UUID) -> int:
        """The next free ``ordering`` value for an image.

        ``COALESCE(MAX(ordering) + 1, 0)`` over live rows. Not unique-constrained — two
        annotations may share an ordering and ``ix_annotations_image_order`` breaks the
        tie on ``created_at`` — so this is a convenience for "append at the end", not a
        sequence allocator, and it does not need the lock
        :meth:`ProjectRepository.allocate_revision_seq` takes.
        """
        stmt = select(func.coalesce(func.max(Annotation.ordering) + 1, 0)).where(
            Annotation.image_id == image_id, Annotation.is_deleted.is_(False)
        )
        return int(await self._scalar(stmt) or 0)

    # ── writes ───────────────────────────────────────────────────────────────

    @staticmethod
    def _representative_point(
        geom: ColumnElement[Any], geom_type: str
    ) -> ColumnElement[Any]:
        """The ``(pixel_x, pixel_y)`` representative point for a geometry (§5.6).

        ★ *"identical to the vertex for points, ``ST_PointOnSurface`` for polygons,
        midpoint-along-arc for polylines"* — the model's own contract. Computed in
        PostGIS from the same geometry the row stores, so ``pixel_x``/``pixel_y`` can
        never drift from ``pixel_geom``.
        """
        if geom_type == AnnotationGeomType.POINT.value:
            return geom
        if geom_type == AnnotationGeomType.POLYLINE.value:
            return func.ST_LineInterpolatePoint(geom, 0.5)
        return func.ST_PointOnSurface(geom)

    @classmethod
    def pixel_geom_values(
        cls, geom_type: str, geometry_geojson: str
    ) -> dict[str, ColumnElement[Any]]:
        """SQL for the three geometry-derived columns from a pixel GeoJSON string.

        Returns ``pixel_geom`` (ring-normalised, SRID 0) plus the server-derived
        ``pixel_x``/``pixel_y`` representative point. ★ The geometry is IMAGE PIXELS,
        not geographic (§5.6): ``ST_GeomFromGeoJSON`` defaults the SRID to 4326, so it
        is forced back to 0 — the SRID ``ck_annotations_geom_srid`` demands and the one
        that makes ``ST_Transform`` mechanically impossible (invariant I1).

        Shared by :meth:`insert` (create) and the bulk/checked update path so the two
        derive the point the same way.
        """
        base = func.ST_SetSRID(func.ST_GeomFromGeoJSON(geometry_geojson), 0)
        rep = cls._representative_point(base, geom_type)
        return {
            "pixel_geom": normalise_pixel_geom(base),
            "pixel_x": func.ST_X(rep),
            "pixel_y": func.ST_Y(rep),
        }

    async def insert(
        self,
        *,
        image_id: uuid.UUID,
        geom_type: str,
        geometry_geojson: str,
        revision_seq: int,
        kind: str = AnnotationKind.GENERIC.value,
        label: str | None = None,
        description: str | None = None,
        confidence: float = 1.0,
        ordering: int = 0,
        style: Mapping[str, Any] | None = None,
        attributes: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> Annotation:
        """Insert one annotation, deriving ``pixel_geom`` + the representative point.

        ★ ``pixel_x``/``pixel_y`` are **derived server-side, never accepted from the
        client** (§5.6): they come out of PostGIS via :meth:`pixel_geom_values` so they
        cannot disagree with ``pixel_geom``. ``version_no`` takes its initial value from
        the column default (1). The row is flushed so its id and derived columns are
        readable in the same transaction (for the ledger event and the response).
        """
        values = self.pixel_geom_values(geom_type, geometry_geojson)
        annotation = Annotation(
            image_id=image_id,
            kind=kind,
            geom_type=geom_type,
            pixel_geom=values["pixel_geom"],
            pixel_x=values["pixel_x"],
            pixel_y=values["pixel_y"],
            label=label,
            description=description,
            confidence=confidence,
            ordering=ordering,
            style=dict(style or {}),
            attributes=dict(attributes or {}),
            revision_seq=revision_seq,
            created_by=created_by,
            updated_by=created_by,
        )
        self.add(annotation)
        await self.flush()
        return await self.refresh(annotation)

    async def update_checked(
        self,
        annotation_id: uuid.UUID,
        *,
        expected_version_no: int | None,
        revision_seq: int,
        values: Mapping[str, Any],
        updated_by: str | None = None,
    ) -> Annotation | None:
        """★ The optimistic-locked update. ``None`` ⇒ the caller's ETag was stale.

        Args:
            annotation_id: The row.
            expected_version_no: The ``If-Match`` value. None skips the check — used by
                the bulk path for items the client did not version, and **never** by
                ``PATCH /annotations/{id}``, where ``If-Match`` is required.
            revision_seq: The revision this edit belongs to, from
                :meth:`ProjectRepository.allocate_revision_seq` **in this transaction**.
            values: Columns to set. ``version_no``, ``revision_seq`` and ``updated_by``
                are managed here and are ignored if passed.
            updated_by: The principal.

        Returns:
            The refreshed annotation, or None when the version check failed **or** the
            row does not exist. The caller distinguishes those with a plain
            :meth:`get` — a 404 and a 412 are different answers and this layer will not
            guess which one is meant.

        ★ ``version_no = version_no + 1`` is computed by the database, not by the
        caller: ``version_no = :expected + 1`` would let two writers that somehow both
        passed the check settle on the same number, and ``version_no`` is the ETag.
        """
        payload = {
            k: v
            for k, v in values.items()
            if k not in {"version_no", "revision_seq", "updated_by", "id", "image_id"}
        }
        stmt = update(Annotation).where(Annotation.id == annotation_id)
        if expected_version_no is not None:
            stmt = stmt.where(Annotation.version_no == expected_version_no)
        stmt = stmt.values(
            **payload,
            version_no=Annotation.version_no + 1,
            revision_seq=revision_seq,
            updated_by=updated_by,
        ).returning(Annotation.id)

        if (await self._execute(stmt)).scalar_one_or_none() is None:
            return None
        return await self._reload(annotation_id)

    async def soft_delete_checked(
        self,
        annotation_id: uuid.UUID,
        *,
        expected_version_no: int | None,
        revision_seq: int,
        updated_by: str | None = None,
    ) -> Annotation | None:
        """Tombstone an annotation. ★ The row survives; the ledger stays referential.

        ``DELETE /annotations/{id}`` returns ``200 AnnotationRead`` with
        ``is_deleted: true`` rather than a 204 — the client needs the new ``version_no``
        to keep its ETag, and the undo stack needs the row to still be there.

        ★ Any GCP derived from this annotation is **not** touched here. ``landmark_id``
        is ``ON DELETE SET NULL`` and the coordinate the surveyor already exported must
        survive, orphaned but intact — which is why ``pixel_x``/``pixel_y`` are copied
        onto the GCP. Marking those GCPs stale is a separate, deliberate call to
        :meth:`GcpRepository.mark_stale`; **staleness is never a side effect** (§6.2).

        Returns:
            The tombstoned annotation, or None when the version check failed or the row
            is absent.
        """
        stmt = update(Annotation).where(
            Annotation.id == annotation_id, Annotation.is_deleted.is_(False)
        )
        if expected_version_no is not None:
            stmt = stmt.where(Annotation.version_no == expected_version_no)
        stmt = stmt.values(
            is_deleted=True,
            version_no=Annotation.version_no + 1,
            revision_seq=revision_seq,
            updated_by=updated_by,
        ).returning(Annotation.id)

        if (await self._execute(stmt)).scalar_one_or_none() is None:
            return None
        return await self._reload(annotation_id)

    async def restore_checked(
        self,
        annotation_id: uuid.UUID,
        *,
        revision_seq: int,
        updated_by: str | None = None,
    ) -> Annotation | None:
        """Un-tombstone an annotation — the ``'restore'`` op of the ledger."""
        stmt = (
            update(Annotation)
            .where(Annotation.id == annotation_id, Annotation.is_deleted.is_(True))
            .values(
                is_deleted=False,
                version_no=Annotation.version_no + 1,
                revision_seq=revision_seq,
                updated_by=updated_by,
            )
            .returning(Annotation.id)
        )
        if (await self._execute(stmt)).scalar_one_or_none() is None:
            return None
        return await self._reload(annotation_id)

    async def soft_delete_all_for_image(
        self,
        image_id: uuid.UUID,
        *,
        revision_seq: int,
        kinds: Sequence[str] | None = None,
        updated_by: str | None = None,
    ) -> Sequence[Annotation]:
        """``DELETE /images/{id}/annotations`` (19) — tombstone the canvas.

        ``X-Confirm-Delete`` is **required** on that endpoint, and the reason is visible
        here: one call, the whole canvas.

        Args:
            image_id: The photograph.
            revision_seq: The revision this bulk edit belongs to.
            kinds: Restrict to these ``annotation_kind`` values. None ⇒ everything live.
            updated_by: The principal.

        Returns:
            The tombstoned rows — **returned, not counted**, because the caller must
            write one ledger event per annotation and needs each row's new
            ``version_no`` to do it.
        """
        stmt = update(Annotation).where(
            Annotation.image_id == image_id, Annotation.is_deleted.is_(False)
        )
        if kinds:
            stmt = stmt.where(Annotation.kind.in_(list(kinds)))
        stmt = stmt.values(
            is_deleted=True,
            version_no=Annotation.version_no + 1,
            revision_seq=revision_seq,
            updated_by=updated_by,
        ).returning(Annotation.id)

        ids = list((await self._execute(stmt)).scalars().all())
        if not ids:
            return []
        return await self._scalars(
            select(Annotation).where(Annotation.id.in_(ids)).order_by(Annotation.ordering)
        )

    async def scale_pixels_for_image(
        self, image_id: uuid.UUID, sx: float, sy: float
    ) -> int:
        """★ Scale every LIVE annotation's pixel coordinates when the photo is resized.

        Part of ``POST /images/{id}/rescale``. When the stored photo is resized from
        ``(ow, oh)`` to ``(nw, nh)``, ``sx = nw/ow`` and ``sy = nh/oh``, and every
        landmark drawn on it must move with the pixels so it stays on the same feature:

            pixel_x   = pixel_x * sx
            pixel_y   = pixel_y * sy
            pixel_geom = ST_Scale(pixel_geom, sx, sy)

        ★ ``pixel_geom`` is **SRID 0 — pixel space**, and ``ST_Scale`` scales about the
        origin ``(0, 0)`` = top-left, which is exactly the anchor a photo resize uses.
        No translation is involved. ``pixel_x``/``pixel_y`` (the representative point)
        are scaled by the same factors in the **same statement** so they can never drift
        from the geometry, and both stay ≥ 0 (``ck_annotations_pixel_nonneg``) because
        the factors are strictly positive.

        Only ``is_deleted = FALSE`` rows are touched: a tombstone is not on the canvas
        and its stale pixels are never read. This is a pixel-space migration, not an
        edit — it deliberately does **not** bump ``version_no`` or write a ledger event.

        Returns:
            The number of annotations scaled.
        """
        stmt = (
            update(Annotation)
            .where(Annotation.image_id == image_id, Annotation.is_deleted.is_(False))
            .values(
                pixel_x=Annotation.pixel_x * sx,
                pixel_y=Annotation.pixel_y * sy,
                pixel_geom=func.ST_Scale(Annotation.pixel_geom, sx, sy),
            )
        )
        return int((await self._execute(stmt)).rowcount or 0)

    async def _reload(self, annotation_id: uuid.UUID) -> Annotation:
        """Read a row back after a Core ``UPDATE`` — the identity map still holds the old one."""
        found = await self.get(annotation_id)
        if found is None:  # pragma: no cover — the UPDATE just matched it.
            raise LookupError(f"annotation {annotation_id} vanished mid-transaction")
        return await self.refresh(found)


class AnnotationVersionRepository(BaseRepository[AnnotationVersion]):
    """The append-only annotation ledger.

    ★ ``id`` is ``BIGSERIAL`` and is **serialised as a JSON number**, not a string
    (§5.4). It is also the keyset cursor: ``ix_annotation_versions_image_time
    (image_id, id DESC)`` makes the undo stack's infinite scroll one index scan.
    """

    model = AnnotationVersion

    @property
    def _sortable(self) -> SortableColumns:
        """``ANNOTATION_VERSION_SORT_FIELDS`` resolved onto SQL."""
        return {
            "id": AnnotationVersion.id,
            "created_at": AnnotationVersion.created_at,
            "version_no": AnnotationVersion.version_no,
        }

    async def append(self, event: AnnotationVersion) -> AnnotationVersion:
        """Stage one ledger event and flush it so its ``id`` is readable.

        The caller is responsible for the ``before``/``after`` biconditional
        (``ck_annotation_versions_payload``): NULL ``before`` iff ``'create'``, NULL
        ``after`` iff ``'delete'``, both non-NULL for ``'update'``/``'restore'``. It is
        not re-checked here — the constraint is the authority and duplicating it would
        be drift.
        """
        self.add(event)
        await self.flush()
        return event

    async def latest_for_annotation(
        self, annotation_id: uuid.UUID
    ) -> AnnotationVersion | None:
        """★ The O(1) undo read. One indexed row, no fold over the log.

        This is what the whole "carry **both** ``before`` and ``after``" design buys:
        undo is *read the last event and apply its ``before``*, not *replay every event
        from the beginning*. ``ix_annotation_versions_annotation (annotation_id,
        version_no DESC)`` makes it a single backward index scan.
        """
        return await self._scalar_one_or_none(
            select(AnnotationVersion)
            .where(AnnotationVersion.annotation_id == annotation_id)
            .order_by(AnnotationVersion.version_no.desc())
            .limit(1)
        )

    async def find_by_client_op_id(self, client_op_id: str) -> AnnotationVersion | None:
        """The idempotency read. ``uq_annotation_versions_client_op``.

        One key per user gesture, minted by the client. A retried gesture — the tap that
        the flaky train wifi swallowed — finds its own event here and replays the answer
        instead of drawing a second polygon.
        """
        return await self._scalar_one_or_none(
            select(AnnotationVersion).where(AnnotationVersion.client_op_id == client_op_id)
        )

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        before_id: int | None = None,
    ) -> tuple[Sequence[AnnotationVersion], int]:
        """``GET /images/{id}/annotation-versions`` (27) — the undo stack.

        Args:
            image_id: The photograph.
            pagination: Limit/offset. ``offset`` is **ignored** when ``before_id`` is
                given; the two are mutually exclusive and ``deps`` already 422s the
                combination (``core.pagination.reject_param_conflict``).
            sort: Whitelisted against ``ANNOTATION_VERSION_SORT_FIELDS``.
            before_id: ★ Keyset mode. The undo stack scrolls while new events land at
                the head, and under offset pagination each new event shifts the window
                by one — so page 2 re-shows an event from page 1 and hides another
                forever. A cursor is immune, which is why this one endpoint has one.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(AnnotationVersion).where(
            AnnotationVersion.image_id == image_id
        )
        total = await self.count_of(stmt)

        if before_id is not None:
            rows = await self._scalars(
                stmt.where(AnnotationVersion.id < before_id)
                .order_by(AnnotationVersion.id.desc())
                .limit(pagination.limit)
            )
            return rows, total
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_for_annotation(
        self,
        annotation_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
    ) -> tuple[Sequence[AnnotationVersion], int]:
        """``GET /annotations/{id}/versions`` (28) — one annotation's history."""
        stmt: Select[Any] = select(AnnotationVersion).where(
            AnnotationVersion.annotation_id == annotation_id
        )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def replay_events(
        self,
        project_id: uuid.UUID,
        *,
        from_seq_exclusive: int,
        to_seq_inclusive: int,
        image_id: uuid.UUID | None = None,
        limit: int | None = None,
    ) -> Sequence[AnnotationVersion]:
        """★ The events to fold over a checkpoint to materialise a revision's state.

        The second half of a replay. The first is
        :meth:`RevisionRepository.nearest_checkpoint_at_or_before`, which bounds the
        work; this returns the events **after** that checkpoint and **up to and
        including** the target, in ledger order.

        ★ The seq bounds are reached by joining ``project_revisions``, because
        ``annotation_versions`` stores ``revision_id``, not ``seq``. The join is **inner**
        on purpose: ``revision_id`` is ``ON DELETE SET NULL``, and an event whose revision
        was pruned has no place in a sequence range — including it would fold a change
        into a revision that does not claim it. Those events are still readable through
        :meth:`list_for_image`; they are simply not replayable, which is honest.

        ★ Ordered by ``id``, the BIGSERIAL, **not** by ``created_at``: two events in one
        transaction share a ``now()`` to the microsecond, and a fold that applies them in
        the wrong order produces a different canvas. ``id`` is the insertion order and it
        is total.

        Args:
            project_id: The project whose revisions bound the range.
            from_seq_exclusive: The checkpoint's ``seq``. Its own events are already
                baked into the snapshot, hence exclusive.
            to_seq_inclusive: The target revision's ``seq``.
            image_id: Restrict the fold to one photograph.
            limit: A hard cap. ``revision_service`` passes ``LE_MAX_REPLAY_EVENTS`` + 1
                and reports ``422 REVISION_REPLAY_TOO_EXPENSIVE`` if it comes back full
                — **a history endpoint that can spin for 40 s is a DoS on your own
                database.** Prefer :meth:`count_events_between` to decide *before*
                loading; this is the belt to that's braces.

        Returns:
            The events, oldest first.
        """
        stmt: Select[Any] = (
            select(AnnotationVersion)
            .join(ProjectRevision, ProjectRevision.id == AnnotationVersion.revision_id)
            .where(
                ProjectRevision.project_id == project_id,
                ProjectRevision.seq > from_seq_exclusive,
                ProjectRevision.seq <= to_seq_inclusive,
            )
        )
        if image_id is not None:
            stmt = stmt.where(AnnotationVersion.image_id == image_id)
        stmt = stmt.order_by(AnnotationVersion.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return await self._scalars(stmt)

    async def count_events_between(
        self,
        project_id: uuid.UUID,
        *,
        from_seq_exclusive: int,
        to_seq_inclusive: int,
        image_id: uuid.UUID | None = None,
    ) -> int:
        """How many events a replay would fold — the cost check before paying it.

        ``revision_service`` compares this against ``LE_MAX_REPLAY_EVENTS`` (5000) and
        refuses with ``422 REVISION_REPLAY_TOO_EXPENSIVE`` + ``details
        .nearest_checkpoint_seq``. Counting first means the refusal costs one index scan
        rather than 40 000 rows of hydrated ORM objects.
        """
        stmt: Select[Any] = (
            select(func.count())
            .select_from(AnnotationVersion)
            .join(ProjectRevision, ProjectRevision.id == AnnotationVersion.revision_id)
            .where(
                ProjectRevision.project_id == project_id,
                ProjectRevision.seq > from_seq_exclusive,
                ProjectRevision.seq <= to_seq_inclusive,
            )
        )
        if image_id is not None:
            stmt = stmt.where(AnnotationVersion.image_id == image_id)
        return int(await self._scalar(stmt) or 0)

    async def count_since_checkpoint(self, project_id: uuid.UUID) -> int:
        """Events since the project's last checkpoint — drives ``LE_CHECKPOINT_EVERY_N_EVENTS``.

        Zero when there is no checkpoint yet, in which case every event counts.
        """
        last = (
            select(func.coalesce(func.max(ProjectRevision.seq), 0))
            .where(
                ProjectRevision.project_id == project_id,
                ProjectRevision.is_checkpoint.is_(True),
            )
            .scalar_subquery()
        )
        stmt = (
            select(func.count())
            .select_from(AnnotationVersion)
            .join(ProjectRevision, ProjectRevision.id == AnnotationVersion.revision_id)
            .where(ProjectRevision.project_id == project_id, ProjectRevision.seq > last)
        )
        return int(await self._scalar(stmt) or 0)

    async def prune_before(self, project_id: uuid.UUID, *, seq_exclusive: int) -> int:
        """Delete pre-checkpoint events, per the §5.9 retention policy.

        *"Keep all events < 90 days; older events compacted (force a checkpoint, then
        delete pre-checkpoint events)."* The order matters and this method does not
        enforce it: **checkpoint first, then prune.** Pruning without a snapshot to
        replay from destroys the history rather than compacting it.

        Returns:
            Rows deleted.
        """
        subq = (
            select(ProjectRevision.id)
            .where(
                ProjectRevision.project_id == project_id,
                ProjectRevision.seq < seq_exclusive,
            )
            .scalar_subquery()
        )
        stmt = delete(AnnotationVersion).where(AnnotationVersion.revision_id.in_(subq))
        return int((await self._execute(stmt)).rowcount or 0)


class RevisionRepository(BaseRepository[ProjectRevision]):
    """Checkpoints and markers in a project's annotation history."""

    model = ProjectRevision

    @property
    def _sortable(self) -> SortableColumns:
        """``REVISION_SORT_FIELDS`` resolved onto SQL."""
        return {"seq": ProjectRevision.seq, "created_at": ProjectRevision.created_at}

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        is_checkpoint: bool | None = None,
        seq_gte: int | None = None,
        seq_lte: int | None = None,
    ) -> tuple[Sequence[ProjectRevision], int]:
        """``GET /projects/{id}/revisions`` (23)."""
        stmt: Select[Any] = select(ProjectRevision).where(
            ProjectRevision.project_id == project_id
        )
        if is_checkpoint is not None:
            stmt = stmt.where(ProjectRevision.is_checkpoint.is_(is_checkpoint))
        if seq_gte is not None:
            stmt = stmt.where(ProjectRevision.seq >= seq_gte)
        if seq_lte is not None:
            stmt = stmt.where(ProjectRevision.seq <= seq_lte)
        return await self.page(stmt, pagination, sort, self._sortable)

    async def get_by_seq(self, project_id: uuid.UUID, seq: int) -> ProjectRevision | None:
        """One revision by its per-project sequence number. ``uq_project_revisions_project_seq``."""
        return await self._scalar_one_or_none(
            select(ProjectRevision).where(
                ProjectRevision.project_id == project_id, ProjectRevision.seq == seq
            )
        )

    async def nearest_checkpoint_at_or_before(
        self, project_id: uuid.UUID, seq: int
    ) -> ProjectRevision | None:
        """★ The replay's starting point — **one backward index scan**.

        ``ix_project_revisions_checkpoints (project_id, seq DESC) WHERE is_checkpoint``
        exists for exactly this query, and it is what bounds reconstruction: without a
        checkpoint the fold starts at revision 1 and a year-old project replays its
        entire history to answer one page load.

        Returns:
            The newest checkpoint at or before ``seq``, or None when the project has
            never been checkpointed — in which case the caller folds from the beginning,
            and :meth:`AnnotationVersionRepository.count_events_between` is what stops
            that being unbounded.
        """
        return await self._scalar_one_or_none(
            select(ProjectRevision)
            .where(
                ProjectRevision.project_id == project_id,
                ProjectRevision.seq <= seq,
                ProjectRevision.is_checkpoint.is_(True),
            )
            .order_by(ProjectRevision.seq.desc())
            .limit(1)
        )

    async def latest(self, project_id: uuid.UUID) -> ProjectRevision | None:
        """The most recent revision. ``ix_project_revisions_project_seq``."""
        return await self._scalar_one_or_none(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == project_id)
            .order_by(ProjectRevision.seq.desc())
            .limit(1)
        )

    async def create(self, revision: ProjectRevision) -> ProjectRevision:
        """Stage and flush a revision so its ``id`` is readable for the ledger events.

        The caller must have allocated ``seq`` via
        :meth:`ProjectRepository.allocate_revision_seq` **in this same transaction** —
        see that method for why. ``ck_project_revisions_snapshot_iff_checkpoint`` is the
        authority on the snapshot/flag pairing and is not re-checked here.
        """
        self.add(revision)
        await self.flush()
        return revision
