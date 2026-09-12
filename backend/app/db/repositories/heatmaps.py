"""``confidence_heatmaps`` + ``confidence_heatmap_cells`` — :class:`HeatmapRepository`.

★ SCOPE.md §4: the confidence heatmap is **deferred** (ABC only) and
``GET /images/{id}/heatmap`` reads what is here, which in this build is nothing. Per §4
rule 5 the tables exist as specified; per the unit brief this is real code.

★ **Absent ≠ score 0**, and the schema says so: the grid is sparse, ``cell_count`` is
stored next to ``grid_cols * grid_rows``, and :meth:`HeatmapRepository.sparsity` returns
both so the payload can state it. A cell that was never evaluated is *unknown*, not
*zero*, and rendering unknown as "cold" is a confident lie in a colour ramp.

★ **Vector, not raster** — ``postgis_raster`` is deliberately not installed. Only the
cell **centroid** is stored; the polygon is ``centroid ± cell_size_m/2``, fully
determined by the parent. Storing 10 000 five-vertex polygons is ~5× the bytes and ~5×
the GIST index for zero information.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, select

from app.core.exceptions import HeatmapNotAvailable
from app.db.repositories.base import BaseRepository, bbox_geography
from app.models.heatmap import ConfidenceHeatmap, ConfidenceHeatmapCell
from app.models.job import MatchJob
from app.models.match import MatchResult
from app.models.pose import CameraPose

__all__ = ["HeatmapRepository"]


class HeatmapRepository(BaseRepository[ConfidenceHeatmap]):
    """The posterior over candidate camera locations, and its sparse grid."""

    model = ConfidenceHeatmap

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_for_job(self, match_job_id: uuid.UUID) -> ConfidenceHeatmap | None:
        """One heatmap per job. ``uq_confidence_heatmaps_job``."""
        return await self._scalar_one_or_none(
            select(ConfidenceHeatmap).where(ConfidenceHeatmap.match_job_id == match_job_id)
        )

    async def get_latest_for_image(self, image_id: uuid.UUID) -> ConfidenceHeatmap | None:
        """The newest heatmap for a photograph — what endpoint 49 serves."""
        return await self._scalar_one_or_none(
            select(ConfidenceHeatmap)
            .where(ConfidenceHeatmap.image_id == image_id)
            .order_by(ConfidenceHeatmap.created_at.desc())
            .limit(1)
        )

    async def get_latest_for_image_or_raise(self, image_id: uuid.UUID) -> ConfidenceHeatmap:
        """:meth:`get_latest_for_image`, or the 404 endpoint 49 documents."""
        heatmap = await self.get_latest_for_image(image_id)
        if heatmap is None:
            raise HeatmapNotAvailable(f"No confidence heatmap for image {image_id}.")
        return heatmap

    async def cells(
        self,
        heatmap_id: uuid.UUID,
        *,
        min_score: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int | None = None,
    ) -> Sequence[ConfidenceHeatmapCell]:
        """A heatmap's cells, hottest first.

        Args:
            heatmap_id: The parent.
            min_score: Drop cells below a threshold. ★ Dropping a *cold* cell and never
                *having* a cell are different facts, and the client must not confuse
                them — which is why :meth:`sparsity` reports the true counts separately
                and the response carries a note.
            bbox: ``(min_lon, min_lat, max_lon, max_lat)`` — ★ **longitudes first**.
                Restricts to a viewport via ``ix_confidence_heatmap_cells_geom``.
            limit: Cap. ~10k cells per job is the design point; a client asking for a
                PNG wants all of them, one asking for JSON at a zoomed-in viewport does
                not.

        Returns:
            Cells ordered by score descending — so a truncating client keeps the peaks,
            which is the part of a posterior anyone looks at.

        Raises:
            ValueError: a transposed or inverted bbox.
        """
        stmt: Select[Any] = select(ConfidenceHeatmapCell).where(
            ConfidenceHeatmapCell.heatmap_id == heatmap_id
        )
        if min_score is not None:
            stmt = stmt.where(ConfidenceHeatmapCell.score >= min_score)
        if bbox is not None:
            stmt = stmt.where(
                func.ST_Intersects(ConfidenceHeatmapCell.geom, bbox_geography(*bbox))
            )
        stmt = stmt.order_by(
            ConfidenceHeatmapCell.score.desc(), ConfidenceHeatmapCell.id.asc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return await self._scalars(stmt)

    async def sparsity(self, heatmap_id: uuid.UUID) -> tuple[int, int]:
        """``(cell_count, grid_cols * grid_rows)`` — what ``HeatmapSparsity`` reports.

        ★ Read from the parent's stored columns rather than counted from the child
        table: ``ck_confidence_heatmaps_cell_count`` already binds the two, and counting
        10 000 rows to learn a number the parent knows is work done to distrust our own
        constraint. **The difference between the two numbers is the honest one** —
        absent is not score 0.

        Raises:
            HeatmapNotAvailable: no such heatmap.
        """
        row = (
            await self._execute(
                select(
                    ConfidenceHeatmap.cell_count,
                    ConfidenceHeatmap.grid_cols * ConfidenceHeatmap.grid_rows,
                ).where(ConfidenceHeatmap.id == heatmap_id)
            )
        ).one_or_none()
        if row is None:
            raise HeatmapNotAvailable(f"No confidence heatmap {heatmap_id}.")
        return int(row[0]), int(row[1])

    # ── writes ───────────────────────────────────────────────────────────────

    async def insert_cells(
        self, cells: Sequence[ConfidenceHeatmapCell]
    ) -> int:
        """Bulk-insert a grid.

        ★ ``add_all`` on ``BIGSERIAL`` primary keys, not the ORM's per-object flush: the
        ids are server-generated, sequential and never appear in a URL, so nothing needs
        them back and SQLAlchemy can batch the INSERT. A 10 000-row grid inserted one
        statement at a time is the difference between a second and a minute.

        The caller keeps ``confidence_heatmaps.cell_count`` in step — the CHECK is the
        authority and it will refuse a count that exceeds the grid.
        """
        if not cells:
            return 0
        self.add_all(cells)
        await self.flush()
        return len(cells)

    async def prune_cells_older_than(self, *, days: int) -> int:
        """§5.9 retention: drop cells of old heatmaps **whose parent is kept forever**.

        *"Cells for jobs > 30 days old whose heatmap is not referenced by a selected
        pose are deleted; the parent row is kept forever, so the map still shows the
        answer."* Both halves matter: deleting the parent would erase ``argmax_geom``
        and the summary statistics — the actual answer — to reclaim the grid that was
        merely how it was drawn.

        The "referenced by a selected pose" test goes through ``match_job_id``: a pose
        cites a ``match_result``, and a heatmap cites the ``match_job`` those results
        belong to. If any selected pose traces back to this job, the grid stays.

        Returns:
            Cells deleted.
        """
        if days <= 0:
            raise ValueError(f"days must be > 0, got {days}")
        cutoff = func.now() - timedelta(days=days)
        protected = (
            select(CameraPose.id)
            .join(MatchResult, MatchResult.id == CameraPose.match_result_id)
            .where(
                MatchResult.match_job_id == ConfidenceHeatmap.match_job_id,
                CameraPose.is_selected.is_(True),
            )
            .correlate(ConfidenceHeatmap)
            .exists()
        )
        stale_heatmaps = (
            select(ConfidenceHeatmap.id)
            .join(MatchJob, MatchJob.id == ConfidenceHeatmap.match_job_id)
            .where(MatchJob.created_at < cutoff, ~protected)
            .scalar_subquery()
        )
        stmt = delete(ConfidenceHeatmapCell).where(
            ConfidenceHeatmapCell.heatmap_id.in_(stale_heatmaps)
        )
        return int((await self._execute(stmt)).rowcount or 0)
