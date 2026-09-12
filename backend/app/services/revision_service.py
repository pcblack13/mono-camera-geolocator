"""``revision_service`` — project revision history: list, get, checkpoint, restore.

★ SCOPE.md §3: version history for annotations and project revisions is BUILT in full.
This service reads the revision ledger and drives checkpoint/restore; the replay SQL and
the event ledger live in the repositories (``RevisionRepository``,
``AnnotationVersionRepository``). Restore re-applies a past state and — because it can
invalidate GCPs derived from the annotations it moves — marks those GCPs stale via
``GcpRepository`` (a deliberate call: staleness is never a side effect, §6.2).
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AnnotationVersionNotFound,
    RevisionNotFound,
    RevisionReplayTooExpensive,
)
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.annotations import (
    AnnotationRepository,
    AnnotationVersionRepository,
    RevisionRepository,
)
from app.db.repositories.gcps import GcpRepository
from app.db.repositories.projects import ProjectRepository
from app.models.annotation import AnnotationVersion
from app.models.enums import AnnotationOp, GcpStaleReason
from app.models.revision import ProjectRevision
from app.schemas.common import WarningItem
from app.schemas.enums import AnnotationOp as WireAnnotationOp
from app.schemas.revision import (
    MAX_REPLAY_EVENTS,
    AnnotationVersionChangeSummary,
    AnnotationVersionRead,
    AnnotationVersionSummary,
    RevisionRestoreResponse,
)
from app.services.annotation_service import AnnotationService

__all__ = ["RevisionService"]


class RevisionService:
    """Read and navigate the annotation revision history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._revisions = RevisionRepository(session)
        self._versions = AnnotationVersionRepository(session)
        self._projects = ProjectRepository(session)
        self._gcps = GcpRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
    ) -> tuple[Sequence[ProjectRevision], int]:
        """``GET /projects/{id}/revisions`` (23)."""
        return await self._revisions.list_for_project(
            project_id, pagination=pagination, sort=sort
        )

    async def get_by_seq(self, project_id: uuid.UUID, seq: int) -> ProjectRevision:
        """One revision by its sequence number, or ``RevisionNotFound``."""
        revision = await self._revisions.get_by_seq(project_id, seq)
        if revision is None:
            raise RevisionNotFound(f"No revision seq {seq} for project {project_id}.")
        return revision

    async def latest(self, project_id: uuid.UUID) -> ProjectRevision | None:
        """The most recent revision, or None for a project with no edits yet."""
        return await self._revisions.latest(project_id)

    # ── checkpoint ────────────────────────────────────────────────────────────

    async def checkpoint(
        self,
        project_id: uuid.UUID,
        *,
        image_id: uuid.UUID | None = None,
        label: str | None = None,
        actor_id: str | None = None,
    ) -> ProjectRevision:
        """Create an explicit checkpoint revision (``POST /projects/{id}/revisions``).

        Allocates the next sequence (the undo/redo lock) inside this transaction and
        records a revision row marked ``is_checkpoint``. The snapshot content is assembled
        by the repository from the current annotation state.
        """
        seq = await self._projects.allocate_revision_seq(project_id)
        revision = ProjectRevision(
            project_id=project_id,
            seq=seq,
            label=label,
            actor_id=actor_id,
            is_checkpoint=True,
        )
        return await self._revisions.create(revision)

    # ── restore ───────────────────────────────────────────────────────────────

    async def mark_gcps_stale_after_restore(self, image_id: uuid.UUID) -> int:
        """After a restore re-applies annotations, flag GCPs derived from them stale.

        ★ A deliberate call, never a side effect of the restore itself (§6.2). The GCPs are
        flagged and never recomputed — a coordinate already in a survey report changes only
        when a human opens ``POST .../gcps/recompute``.

        Returns:
            How many GCPs were newly marked stale.
        """
        return await self._gcps.mark_stale(
            reason=GcpStaleReason.ANNOTATIONS_RESTORED, image_id=image_id
        )

    # ── single revision read (endpoint 25) ──────────────────────────────────────

    async def get(self, revision_id: uuid.UUID) -> ProjectRevision:
        """One revision by its id, or ``RevisionNotFound`` (endpoint 25).

        Returns the ORM row; the router's ``_revision_read`` fills the flat columns.
        """
        revision = await self._revisions.get(revision_id)
        if revision is None:
            raise RevisionNotFound(f"No revision {revision_id}.")
        return revision

    # ── restore (endpoint 26) ───────────────────────────────────────────────────

    async def restore(
        self, revision_id: uuid.UUID, *, label: str | None = None, actor_id: str | None = None
    ) -> RevisionRestoreResponse:
        """Restore the project's annotation set to a past revision, **forward-only**.

        ★ Restore never rewinds ``current_revision_seq`` (§6.2): it materialises the
        target state by folding the ledger up to the target ``seq``, diffs it against the
        current live set, and applies the delta as a **new** revision emitting normal
        events — so a restore is itself undoable and the append-only log never lies.

        ★ Restore never recomputes GCPs. Any GCP derived from a moved annotation is
        flagged stale via a deliberate :meth:`mark_gcps_stale_after_restore` call and the
        response warns ``GCPS_NOW_STALE`` — a coordinate already in a survey report
        changes only when a human opens ``.../gcps/recompute`` (§6.2).
        """
        target = await self.get(revision_id)
        project_id = target.project_id

        target_state = await self._materialise_state(project_id, target.seq)

        annotations = AnnotationRepository(self._session)
        writer = AnnotationService(self._session)
        current = {a.id: a for a in await annotations.list_active_for_project(project_id)}

        revision = await writer._open_revision(project_id, label=label, actor_id=actor_id)
        counts = {"created": 0, "updated": 0, "deleted": 0, "restored": 0}
        affected_images: set[uuid.UUID] = set()

        # Rows live now but absent at the target → tombstone them.
        for annotation_id, row in current.items():
            if annotation_id in target_state:
                continue
            before = writer._snapshot(row)
            deleted = await annotations.soft_delete_checked(
                annotation_id,
                expected_version_no=None,
                revision_seq=revision.seq,
                updated_by=actor_id,
            )
            if deleted is None:  # pragma: no cover — read as live one statement ago.
                continue
            await writer._append_event(
                annotation=deleted,
                revision_id=revision.id,
                op=AnnotationOp.DELETE.value,
                before=before,
                after=None,
                actor_id=actor_id,
            )
            counts["deleted"] += 1
            affected_images.add(deleted.image_id)

        # Rows the target carries → restore (if tombstoned) and set to the target state.
        for annotation_id, snap in target_state.items():
            row = current.get(annotation_id)
            values = self._restore_values(annotations, snap)
            if row is None:
                restored = await annotations.restore_checked(
                    annotation_id, revision_seq=revision.seq, updated_by=actor_id
                )
                if restored is None:
                    # Never existed as a live/tombstoned row we can reach — an honest skip
                    # rather than inventing a landmark (L12).
                    continue
                before = writer._snapshot(restored)
                updated = await annotations.update_checked(
                    annotation_id,
                    expected_version_no=None,
                    revision_seq=revision.seq,
                    values=values,
                    updated_by=actor_id,
                )
                target_row = updated if updated is not None else restored
                await writer._append_event(
                    annotation=target_row,
                    revision_id=revision.id,
                    op=AnnotationOp.RESTORE.value,
                    before=before,
                    after=writer._snapshot(target_row),
                    actor_id=actor_id,
                )
                counts["restored"] += 1
                affected_images.add(target_row.image_id)
            else:
                before = writer._snapshot(row)
                updated = await annotations.update_checked(
                    annotation_id,
                    expected_version_no=None,
                    revision_seq=revision.seq,
                    values=values,
                    updated_by=actor_id,
                )
                if updated is None:
                    continue
                after = writer._snapshot(updated)
                if after == before:
                    continue  # byte-identical → no event, no inflation (§6.2).
                await writer._append_event(
                    annotation=updated,
                    revision_id=revision.id,
                    op=AnnotationOp.UPDATE.value,
                    before=before,
                    after=after,
                    actor_id=actor_id,
                )
                counts["updated"] += 1
                affected_images.add(updated.image_id)

        live = await annotations.list_active_for_project(project_id)
        revision.annotation_count = len(live)
        await self._revisions.flush()

        warnings: list[WarningItem] = []
        stale = 0
        for image_id in affected_images:
            stale += await self.mark_gcps_stale_after_restore(image_id)
        if stale:
            warnings.append(
                WarningItem(
                    code="GCPS_NOW_STALE",
                    message=(
                        f"{stale} GCP(s) derived from restored annotations were marked "
                        "stale. Recompute them explicitly to update their coordinates."
                    ),
                )
            )

        from app.api.presenters import to_annotation_read

        gcp_map = await writer.gcp_ids_for([a.id for a in live])
        return RevisionRestoreResponse(
            revision=writer._revision_summary(revision),
            annotations=[
                to_annotation_read(a, gcp_ids=gcp_map.get(a.id, [])) for a in live
            ],
            warnings=warnings,
        )

    async def _materialise_state(
        self, project_id: uuid.UUID, seq: int
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Fold the ledger up to ``seq`` into ``{annotation_id: snapshot}`` (live only).

        No checkpoints exist to fold from in this build, so the fold starts at the
        beginning; :data:`MAX_REPLAY_EVENTS` bounds it (``422
        REVISION_REPLAY_TOO_EXPENSIVE`` otherwise), for the reason
        ``replay_events`` documents — a history endpoint that can spin for 40 s is a DoS
        on your own database.
        """
        events = await self._versions.replay_events(
            project_id,
            from_seq_exclusive=0,
            to_seq_inclusive=seq,
            limit=MAX_REPLAY_EVENTS + 1,
        )
        if len(events) > MAX_REPLAY_EVENTS:
            raise RevisionReplayTooExpensive(
                f"Restoring to revision seq {seq} would replay more than "
                f"{MAX_REPLAY_EVENTS} events."
            )
        state: dict[uuid.UUID, dict[str, Any]] = {}
        for event in events:  # already ordered by the BIGSERIAL id (insertion order)
            op = str(getattr(event.op, "value", event.op))
            if op == AnnotationOp.DELETE.value:
                state.pop(event.annotation_id, None)
            elif event.after is not None:
                state[event.annotation_id] = event.after
        return state

    @staticmethod
    def _restore_values(
        annotations: AnnotationRepository, snap: dict[str, Any]
    ) -> dict[str, Any]:
        """A target snapshot → the columns to set when re-applying it."""
        values: dict[str, Any] = {
            "kind": snap["kind"],
            "geom_type": snap["geom_type"],
            "label": snap.get("label"),
            "description": snap.get("description"),
            "confidence": snap.get("confidence", 1.0),
            "ordering": snap.get("ordering", 0),
            "style": snap.get("style") or {},
            "attributes": snap.get("attributes") or {},
        }
        geometry = snap.get("geometry")
        if geometry is not None:
            values.update(
                annotations.pixel_geom_values(snap["geom_type"], json.dumps(geometry))
            )
        return values

    # ── annotation version ledger (endpoints 27–29) ─────────────────────────────

    async def list_versions_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        before_id: int | None = None,
        include_payloads: bool = False,
    ) -> tuple[list[AnnotationVersionSummary], int]:
        """``GET /images/{id}/annotation-versions`` (27) — the undo stack."""
        rows, total = await self._versions.list_for_image(
            image_id, pagination=pagination, sort=sort, before_id=before_id
        )
        return [
            self._to_version_summary(r, include_payloads=include_payloads) for r in rows
        ], total

    async def list_versions_for_annotation(
        self,
        annotation_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        include_payloads: bool = False,
    ) -> tuple[list[AnnotationVersionSummary], int]:
        """``GET /annotations/{id}/versions`` (28) — one annotation's history."""
        rows, total = await self._versions.list_for_annotation(
            annotation_id, pagination=pagination, sort=sort
        )
        return [
            self._to_version_summary(r, include_payloads=include_payloads) for r in rows
        ], total

    async def get_version(self, version_id: int) -> AnnotationVersionRead:
        """``GET /annotation-versions/{id}`` (29) — one event, full payloads."""
        event = await self._versions.get(version_id)
        if event is None:
            raise AnnotationVersionNotFound(f"No annotation version {version_id}.")
        return self._to_version_read(event)

    # ── ledger presentation helpers ─────────────────────────────────────────────

    def _to_version_summary(
        self, event: AnnotationVersion, *, include_payloads: bool
    ) -> AnnotationVersionSummary:
        return AnnotationVersionSummary(
            id=event.id,
            annotation_id=event.annotation_id,
            image_id=event.image_id,
            revision_id=event.revision_id,
            op=WireAnnotationOp(str(getattr(event.op, "value", event.op))),
            version_no=event.version_no,
            actor_id=event.actor_id,
            client_op_id=event.client_op_id,
            created_at=event.created_at,
            summary=self._change_summary(event.before, event.after),
            before=event.before if include_payloads else None,
            after=event.after if include_payloads else None,
        )

    def _to_version_read(self, event: AnnotationVersion) -> AnnotationVersionRead:
        return AnnotationVersionRead(
            id=event.id,
            annotation_id=event.annotation_id,
            image_id=event.image_id,
            revision_id=event.revision_id,
            op=WireAnnotationOp(str(getattr(event.op, "value", event.op))),
            version_no=event.version_no,
            actor_id=event.actor_id,
            client_op_id=event.client_op_id,
            created_at=event.created_at,
            summary=self._change_summary(event.before, event.after),
            before=event.before,
            after=event.after,
            diff=self._json_patch(event.before, event.after),
            pixel_geom_after=(event.after or {}).get("geometry"),
        )

    @classmethod
    def _change_summary(
        cls, before: dict[str, Any] | None, after: dict[str, Any] | None
    ) -> AnnotationVersionChangeSummary:
        """A cheap, renderable description of one event, from its payloads."""
        b = before or {}
        a = after or {}
        fields_changed = sorted(
            key for key in set(b) | set(a) if b.get(key) != a.get(key)
        )
        vertex_delta: int | None = None
        moved_px: float | None = None
        if before is not None and after is not None:
            vb = cls._vertex_count(b.get("geometry"))
            va = cls._vertex_count(a.get("geometry"))
            if vb is not None and va is not None:
                vertex_delta = va - vb
            if {"pixel_x", "pixel_y"} <= set(b) and {"pixel_x", "pixel_y"} <= set(a):
                moved_px = math.hypot(
                    float(a["pixel_x"]) - float(b["pixel_x"]),
                    float(a["pixel_y"]) - float(b["pixel_y"]),
                )
        return AnnotationVersionChangeSummary(
            fields_changed=fields_changed, vertex_delta=vertex_delta, moved_px=moved_px
        )

    @staticmethod
    def _vertex_count(geometry: dict[str, Any] | None) -> int | None:
        """Count positions in a GeoJSON-shaped geometry dict, or None if absent."""
        if not geometry:
            return None

        def walk(coords: Any) -> int:
            if coords and isinstance(coords[0], (int, float)):
                return 1
            return sum(walk(c) for c in coords)

        try:
            return walk(geometry.get("coordinates", []))
        except (TypeError, IndexError):  # pragma: no cover — payloads are our own shape.
            return None

    @staticmethod
    def _json_patch(
        before: dict[str, Any] | None, after: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """A field-level RFC 6902 JSON Patch from ``before`` to ``after``."""
        b = before or {}
        a = after or {}
        ops: list[dict[str, Any]] = []
        for key in sorted(set(b) | set(a)):
            if key not in a:
                ops.append({"op": "remove", "path": f"/{key}"})
            elif key not in b:
                ops.append({"op": "add", "path": f"/{key}", "value": a[key]})
            elif b[key] != a[key]:
                ops.append({"op": "replace", "path": f"/{key}", "value": a[key]})
        return ops
