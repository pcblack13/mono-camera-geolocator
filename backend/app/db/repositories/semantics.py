"""``semantic_features`` — :class:`SemanticFeatureRepository`.

★ SCOPE.md §4: semantic detection is **deferred** (ABC only) and ``POST
/images/{id}/segment`` returns 501. Per §4 rule 5 the table exists; per the unit brief
this is real code. The one live writer is the *manual* path — ``detector = 'manual'``,
``source_annotation_id`` set — which is a surveyor hand-drawing a region and needs no
model at all.

★ **The table is entirely optional even when the engine exists** (invariant I3). Empty ⇒
``match_results.semantic_similarity_score IS NULL`` ⇒ renormalised weights ⇒ the system
works. Nothing downstream requires a row here.

★ **Embeddings are not stored in Postgres.** ``pgvector`` is not in the mandated stack
and DINOv2 descriptors (768-D float32 × thousands of patches) are a poor fit for a row
store. They are ``.npy``/FAISS artifacts referenced by path in ``embedding_meta``, and
this module stores the path, never the vector.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, select

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    bbox_geography,
    csv_enum_filter,
)
from app.models.enums import FeatureSpace, SemanticClass
from app.models.semantic import SemanticFeature

__all__ = ["SemanticFeatureRepository"]


class SemanticFeatureRepository(BaseRepository[SemanticFeature]):
    """Detected or hand-drawn semantic regions, in exactly one of the two spaces."""

    model = SemanticFeature

    @property
    def _sortable(self) -> SortableColumns:
        """``SEMANTIC_SORT_FIELDS`` resolved onto SQL.

        ★ ``"class"`` is the **wire and column** name; ``class_`` is the Python
        attribute, because ``class`` is a keyword. This map is where the two meet — the
        one place in this module that has to know, and the reason ``?sort=class`` works
        without a case-mapping layer anywhere (L9).
        """
        return {
            "created_at": SemanticFeature.created_at,
            "confidence": SemanticFeature.confidence,
            "area_m2": SemanticFeature.area_m2,
            "class": SemanticFeature.class_,
        }

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        class_csv: str | None = None,
        space: FeatureSpace | None = None,
        detector: str | None = None,
        confidence_gte: float | None = None,
        match_result_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[SemanticFeature], int]:
        """``GET /images/{image_id}/semantic-features`` (46).

        Args:
            image_id: The photograph.
            pagination: Validated limit/offset.
            sort: Whitelisted against ``SEMANTIC_SORT_FIELDS``.
            class_csv: ``?class=road,tree_line``.
            space: ★ ``image_pixel`` or ``satellite_geo``. The two are physically
                different column types, so ``ck_semantic_features_space_xor`` makes
                invariant I1 mechanical for this table: a row lives in one space or the
                other, never both and never neither, and PostGIS itself refuses to
                confuse them.
            detector: ``classical_cv`` | ``sam`` | ``dinov2`` | ``manual`` | ``other``.
            confidence_gte: 0–1 — the detector's own, never a survey confidence.
            match_result_id: Only meaningful with ``space='satellite_geo'``, and
                ``ck_semantic_features_geo_needs_match`` says so.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(SemanticFeature).where(SemanticFeature.image_id == image_id)
        classes = csv_enum_filter(class_csv, [m.value for m in SemanticClass])
        if classes:
            stmt = stmt.where(SemanticFeature.class_.in_(classes))
        if space is not None:
            stmt = stmt.where(SemanticFeature.space == space)
        if detector is not None:
            stmt = stmt.where(SemanticFeature.detector == detector)
        if confidence_gte is not None:
            stmt = stmt.where(SemanticFeature.confidence >= confidence_gte)
        if match_result_id is not None:
            stmt = stmt.where(SemanticFeature.match_result_id == match_result_id)
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_for_match_result(
        self, match_result_id: uuid.UUID
    ) -> Sequence[SemanticFeature]:
        """Every geographic-space feature of one match result, most confident first."""
        return await self._scalars(
            select(SemanticFeature)
            .where(SemanticFeature.match_result_id == match_result_id)
            .order_by(SemanticFeature.confidence.desc(), SemanticFeature.id.asc())
        )

    async def find_in_bbox(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        image_id: uuid.UUID | None = None,
        limit: int = 1000,
    ) -> Sequence[SemanticFeature]:
        """Geographic-space features inside a viewport.

        ★ Restricted to ``space='satellite_geo'`` rather than merely to ``geo_geom IS
        NOT NULL``: the two are equivalent under ``ck_semantic_features_space_xor``, and
        querying the *column* the CHECK governs rather than the *flag* it governs means
        the index predicate and the query predicate are the same predicate
        (``ix_semantic_features_geo_geom WHERE geo_geom IS NOT NULL``).

        Args:
            min_lon: West edge. ★ **Longitude first.**
            min_lat: South edge.
            max_lon: East edge.
            max_lat: North edge.
            image_id: Restrict to one photograph.
            limit: Cap.

        Raises:
            ValueError: a transposed or inverted bbox.
        """
        stmt: Select[Any] = select(SemanticFeature).where(
            SemanticFeature.geo_geom.isnot(None),
            SemanticFeature.space == FeatureSpace.SATELLITE_GEO,
            func.ST_Intersects(
                SemanticFeature.geo_geom,
                bbox_geography(min_lon, min_lat, max_lon, max_lat),
            ),
        )
        if image_id is not None:
            stmt = stmt.where(SemanticFeature.image_id == image_id)
        return await self._scalars(
            stmt.order_by(SemanticFeature.confidence.desc(), SemanticFeature.id.asc()).limit(
                limit
            )
        )

    async def delete_for_image(
        self,
        image_id: uuid.UUID,
        *,
        class_csv: str | None = None,
        space: FeatureSpace | None = None,
        detector: str | None = None,
    ) -> int:
        """``SemanticFeatureDeleteParams`` — drop a filtered set.

        ★ Deliberately **not** guarded against deleting everything: an unfiltered call
        clears the image's features, which is what "re-segment from scratch" means. The
        confirmation gate is the endpoint's, not this layer's — but note that a
        ``detector='manual'`` row is a **human-drawn region**, and a caller that sweeps
        without filtering destroys the surveyor's own work alongside the model's. Pass
        ``detector`` when you mean "the model's output".

        Returns:
            Rows deleted.
        """
        stmt = delete(SemanticFeature).where(SemanticFeature.image_id == image_id)
        classes = csv_enum_filter(class_csv, [m.value for m in SemanticClass])
        if classes:
            stmt = stmt.where(SemanticFeature.class_.in_(classes))
        if space is not None:
            stmt = stmt.where(SemanticFeature.space == space)
        if detector is not None:
            stmt = stmt.where(SemanticFeature.detector == detector)
        return int((await self._execute(stmt)).rowcount or 0)

    async def count_by_class(self, image_id: uuid.UUID) -> dict[str, int]:
        """``{semantic_class: count}`` for an image — the legend's row counts.

        ``ix_semantic_features_image_class (image_id, class)`` serves the group-by
        directly.
        """
        stmt = (
            select(SemanticFeature.class_, func.count())
            .where(SemanticFeature.image_id == image_id)
            .group_by(SemanticFeature.class_)
        )
        return {
            str(getattr(cls, "value", cls)): int(count)
            for cls, count in (await self._execute(stmt)).all()
        }
