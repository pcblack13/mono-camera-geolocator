"""``gcps`` — ★ **THE DELIVERABLE**. All PostGIS spatial SQL lives here.

``gcps.geom`` is the canonical truth of this entire system (§5.8 step [7]). Everything
after it is serialisation; nothing before it is stored as a coordinate. **If an export
disagrees with the map, the exporter is wrong, not the database.**

★★ **THE LON/LAT ORDERING TRAP — read this before touching a line below.**
Every human says "lat, lon". Every OGC construct says the opposite: ``ST_MakePoint``,
``ST_Point``, WKT ``POINT(x y)`` and ``ST_MakeEnvelope`` all take **X first, and X is
longitude**. A transposed coordinate is not a rounding error — it is a point in a
different hemisphere that will parse, store, index and export without a single warning,
and ``geography(Point,4326)`` cannot catch it because a transposed pair is usually still
a valid coordinate. There is therefore exactly **one** transposition site in this module:
:func:`app.db.types.point_wkt`, which takes ``(lon, lat)``, range-checks both, and says
so in its error message. **This module never builds a point literal any other way.** The
bbox helper does the same job for ``ST_MakeEnvelope`` and is the module's only envelope
site.

★ **Manual mode is the product** (SCOPE.md §5). :meth:`GcpRepository.create_manual` is
the writer for it, and it hardcodes ``source = 'manual'`` — a caller cannot pass it,
because the whole point of the column is that an *observed* coordinate can never be
confused with an *inferred* one downstream or in an export. The automatic writer does
not exist in this build (SCOPE.md §1); when the engine is re-enabled it constructs a
:class:`~app.models.gcp.GCP` and stages it with the inherited ``add()`` — no new
repository method, no caller change (SCOPE.md §7).

★ **``confidence`` is never computed here.** In manual mode it is the surveyor's own
1–5 judgement mapped to the 0–100 column by the schema layer, and this module writes
whatever it is handed. It is not touched by :meth:`adjust`, ever — see that method.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, Sequence

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import GcpCodeConflict, GcpNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    apply_pagination,
    apply_sort,
    bbox_geography,
    constraint_name_of,
    count_stmt_of,
    like_escape,
)
from app.db.types import point_wkt, st_x, st_y
from app.models.album import album_projects
from app.models.annotation import Annotation
from app.models.enums import GcpSource, GcpStaleReason
from app.models.gcp import GCP
from app.models.image import Image
from app.models.match import MatchResult
from app.models.project import Project

__all__ = ["ACCURACY_DOMINANT_TERMS", "GcpRepository"]

#: ``ck_gcps_accuracy_dominant_term``'s value set. Mirrored so a caller error surfaces
#: as a legible ``ValueError`` naming the four legal values, rather than as a
#: ``CheckViolation`` from psycopg after the flush — by which point the offending value
#: is three frames away.
ACCURACY_DOMINANT_TERMS: Final[frozenset[str]] = frozenset(
    {"match", "georeference", "landmark_click", "rectification"}
)


class GcpRepository(BaseRepository[GCP]):
    """Ground control points: creation, adjustment, reset, staleness, spatial search."""

    model = GCP

    #: ``GCP_SORT_FIELDS`` (``app.schemas.gcp``) resolved onto SQL. Three of the seven
    #: are **not columns**: ``lat``/``lon`` are projected out of ``geom``, and
    #: ``total_ce90_m`` is the wire name of ``accuracy_total_ce90_m``. This map is the
    #: only place that knows it. ``id`` is appended by ``apply_sort`` for the
    #: tiebreaker.
    @property
    def _sortable(self) -> SortableColumns:
        return {
            "code": GCP.code,
            "confidence": GCP.confidence,
            "created_at": GCP.created_at,
            "updated_at": GCP.updated_at,
            "lat": st_y(GCP.geom),
            "lon": st_x(GCP.geom),
            "total_ce90_m": GCP.accuracy_total_ce90_m,
        }

    # ── creation — SCOPE.md §5, the product's core interaction ───────────────

    async def create_manual(
        self,
        *,
        image_id: uuid.UUID,
        lon: float,
        lat: float,
        pixel_x: float,
        pixel_y: float,
        confidence: float,
        accuracy_relative_ce90_m: float,
        georef_ce90_m: float,
        accuracy_total_ce90_m: float,
        accuracy_dominant_term: str,
        landmark_id: uuid.UUID | None = None,
        match_result_id: uuid.UUID | None = None,
        code: str | None = None,
        name: str | None = None,
        elevation_m: float | None = None,
        elevation_source: str | None = None,
        elevation_ce90_m: float | None = None,
        accuracy_semi_major_ce90_m: float | None = None,
        accuracy_semi_minor_ce90_m: float | None = None,
        accuracy_azimuth_deg: float | None = None,
        is_included_in_export: bool = True,
        reference_imagery: dict | None = None,
    ) -> GCP:
        """Record a surveyor's photo-pixel ↔ map-click correspondence as a GCP.

        ★ **The coordinate is a direct observation, not an inference** (SCOPE.md §2).
        There is no homography in this path, so there is nothing to be degenerate and
        no estimated confidence to calibrate: ``lat``/``lon`` are exactly where the
        surveyor clicked, and ``confidence`` is exactly what they declared.

        Args:
            image_id: The photograph.
            lon: **Longitude first.** EPSG:4326, from the map click.
            lat: Latitude.
            pixel_x: ORIGINAL full-resolution image pixel space, y-down, top-left
                origin — independent of viewer zoom and brightness/contrast
                (SCOPE.md §5). Sub-pixel; never rounded.
            pixel_y: As ``pixel_x``.
            confidence: **0–100**, the surveyor's declared 1–5 judgement mapped by
                ``app.schemas.gcp.SURVEYOR_CONFIDENCE_TO_SCORE``. **Never computed**,
                here or anywhere.
            accuracy_relative_ce90_m: From imagery GSD + click precision at the map's
                zoom (``gis.accuracy``) — a real, defensible number, not a match score.
            georef_ce90_m: The provider's own contribution.
            accuracy_total_ce90_m: ``sqrt(relative² + georef²)``. The headline number.
            accuracy_dominant_term: One of :data:`ACCURACY_DOMINANT_TERMS`. For a
                manual GCP this is normally ``landmark_click`` or ``georeference`` —
                never ``match``, because nothing matched.
            landmark_id: The annotation this GCP hangs off, when the surveyor picked
                one. NULL for a bare click; ``pixel_x``/``pixel_y`` are copied onto the
                row either way, so the GCP stays self-describing if the annotation is
                later tidied away (``landmark_id`` is ``ON DELETE SET NULL``).
            match_result_id: The manual-session provenance row, if the service made
                one. Nullable for ``source='manual'`` — there was no matching, so there
                is no homography to point at, and ``ck_gcps_automatic_has_provenance``
                keeps the requirement exactly where it applies.
            code: ``'GCP01'``. Unique per image.
            elevation_m: Filled by ``elevation_service`` when a DEM answered.
            elevation_source: **Must be non-NULL iff ``elevation_m`` is**
                (``ck_gcps_elevation_source_consistent``) — the source may never name a
                producer that did not run.
            elevation_ce90_m: Vertical CE90. NULL is honest; 0 would not be.
            accuracy_semi_major_ce90_m: Error-ellipse major axis.
            accuracy_semi_minor_ce90_m: Error-ellipse minor axis.
            accuracy_azimuth_deg: Major-axis bearing, 0 = North, clockwise.
            is_included_in_export: Export filter flag.

        Returns:
            The staged :class:`GCP`, flushed so its server-generated ``id`` and
            timestamps are readable in the same transaction.

        Raises:
            ValueError: ``lon``/``lat`` out of range (the transposition guard), or an
                ``accuracy_dominant_term`` outside the four legal values.
            GcpCodeConflict: ``code`` is already used on this image.

        ★ ``satellite_pixel_x``/``_y`` are left NULL and ``has_direct_fix`` False: a
        manual GCP has no stored satellite mosaic, so there are no mosaic pixels to
        record and — by ``ck_gcps_residual_iff_direct_fix`` — no ``residual_px``
        either. NULL here means "there is no such thing for this row", which is the
        truth. Writing 0 would mean "we measured zero error", which is not.
        """
        if accuracy_dominant_term not in ACCURACY_DOMINANT_TERMS:
            raise ValueError(
                f"accuracy_dominant_term {accuracy_dominant_term!r} is not one of "
                f"{sorted(ACCURACY_DOMINANT_TERMS)} (ck_gcps_accuracy_dominant_term)."
            )

        gcp = GCP(
            image_id=image_id,
            landmark_id=landmark_id,
            match_result_id=match_result_id,
            # ★ Hardcoded, never a parameter. SCOPE.md §5: every GCP this build writes
            #   is an observation, and the column exists so nothing downstream can
            #   mistake it for an inference.
            source=GcpSource.MANUAL.value,
            code=code,
            name=name,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            satellite_pixel_x=None,
            satellite_pixel_y=None,
            has_direct_fix=False,
            geom=point_wkt(lon, lat),  # ★ the one transposition site
            elevation_m=elevation_m,
            elevation_source=elevation_source,
            elevation_ce90_m=elevation_ce90_m,
            confidence=confidence,
            accuracy_relative_ce90_m=accuracy_relative_ce90_m,
            georef_ce90_m=georef_ce90_m,
            accuracy_total_ce90_m=accuracy_total_ce90_m,
            accuracy_semi_major_ce90_m=accuracy_semi_major_ce90_m,
            accuracy_semi_minor_ce90_m=accuracy_semi_minor_ce90_m,
            accuracy_azimuth_deg=accuracy_azimuth_deg,
            accuracy_dominant_term=accuracy_dominant_term,
            residual_px=None,
            manually_adjusted=False,
            is_stale=False,
            stale_reason=None,
            is_included_in_export=is_included_in_export,
            # ★ Recorded at click time or not at all — never backfilled (0017).
            reference_imagery=reference_imagery,
        )
        self.add(gcp)
        await self._flush_mapping_code_conflict(image_id=image_id, code=code)
        return gcp

    async def scale_pixels_for_image(
        self, image_id: uuid.UUID, sx: float, sy: float
    ) -> int:
        """★ Scale every GCP's PHOTO-pixel position when the photo is resized.

        Part of ``POST /images/{id}/rescale``. With ``sx = nw/ow``, ``sy = nh/oh``::

            pixel_x = pixel_x * sx
            pixel_y = pixel_y * sy

        ★★ **``pixel_x``/``pixel_y`` are the ONLY columns touched.** They are the
        landmark's location in *photo* pixel space, and that space is exactly what a
        resize changes. Everything else on the row is independent of photo resolution and
        must be left byte-for-byte alone:

        * ``geom`` — **the canonical truth** (lat/lon). It came from the surveyor's map
          click, not the photo. Resizing the photo cannot move a survey coordinate, and
          this method is the guarantee that it does not.
        * ``satellite_pixel_x``/``_y`` — mosaic pixel space, a different raster entirely.
        * ``original_geom``, ``original_satellite_pixel_x``/``_y`` — the preserved answer.
        * ``accuracy_*`` — real ground metres, a property of the coordinate, not the JPEG.

        One UPDATE, all GCPs of the image (stale ones included — a stale GCP is still
        pinned to a photo feature and must track it). Factors are strictly positive, so
        ``ck_gcps_pixel_nonneg`` holds.

        Returns:
            The number of GCPs scaled.
        """
        stmt = (
            update(GCP)
            .where(GCP.image_id == image_id)
            .values(pixel_x=GCP.pixel_x * sx, pixel_y=GCP.pixel_y * sy)
        )
        return int((await self._execute(stmt)).rowcount or 0)

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_for_image(self, gcp_id: uuid.UUID, image_id: uuid.UUID) -> GCP | None:
        """One GCP, scoped to an image.

        The scoped read exists so a caller holding both ids cannot be tricked into
        acting on a GCP belonging to a different photograph by a guessed UUID.
        """
        return await self._scalar_one_or_none(
            select(GCP).where(GCP.id == gcp_id, GCP.image_id == image_id)
        )

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        match_result_id: uuid.UUID | None = None,
        source: str | None = None,
        confidence_gte: float | None = None,
        confidence_lte: float | None = None,
        manually_adjusted: bool | None = None,
        is_stale: bool | None = None,
        is_included_in_export: bool | None = None,
        q: str | None = None,
    ) -> tuple[Sequence[GCP], int]:
        """``GET /images/{image_id}/gcps`` (38) — filtered, sorted, counted.

        Args:
            image_id: The photograph.
            pagination: Validated limit/offset.
            sort: Whitelisted against ``GCP_SORT_FIELDS``.
            match_result_id: Provenance filter.
            source: ★ ``'manual'`` | ``'automatic'`` — SCOPE.md §5's filter, the one
                that keeps an observed coordinate from being confused with an inferred
                one in an export.
            confidence_gte: 0–100 lower bound.
            confidence_lte: 0–100 upper bound.
            manually_adjusted: Adjustment filter.
            is_stale: Staleness filter.
            is_included_in_export: Export-flag filter.
            q: Free-text over ``code`` **and the landmark's label** — hence the outer
                join below.

        Returns:
            ``(rows, total)`` where total ignores limit/offset.
        """
        stmt = self._filtered(
            select(GCP).where(GCP.image_id == image_id),
            match_result_id=match_result_id,
            source=source,
            confidence_gte=confidence_gte,
            confidence_lte=confidence_lte,
            manually_adjusted=manually_adjusted,
            is_stale=is_stale,
            is_included_in_export=is_included_in_export,
            q=q,
        )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_for_match_result(
        self,
        match_result_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        source: str | None = None,
        confidence_gte: float | None = None,
        confidence_lte: float | None = None,
        manually_adjusted: bool | None = None,
        is_stale: bool | None = None,
        is_included_in_export: bool | None = None,
        q: str | None = None,
    ) -> tuple[Sequence[GCP], int]:
        """``GET /match-results/{id}/gcps`` (64) — the route ``gcps_url`` points at."""
        stmt = self._filtered(
            select(GCP).where(GCP.match_result_id == match_result_id),
            match_result_id=None,
            source=source,
            confidence_gte=confidence_gte,
            confidence_lte=confidence_lte,
            manually_adjusted=manually_adjusted,
            is_stale=is_stale,
            is_included_in_export=is_included_in_export,
            q=q,
        )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_for_export(
        self,
        *,
        image_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        source: str | None = None,
        confidence_gte: float | None = None,
        include_stale: bool = False,
    ) -> Sequence[GCP]:
        """Every GCP an export should contain — **unpaginated, deterministic**.

        Serves ``render_export_task``. Unpaginated on purpose: an export is a whole
        deliverable, and paging it would mean a file whose contents depend on a limit
        nobody chose. Ordered by ``code`` then ``created_at`` so two runs of the same
        export produce byte-identical row order, which is what makes the checksum on
        ``exports.checksum_sha256`` mean anything.

        ★ ``is_included_in_export`` is applied unconditionally — it is the flag's only
        purpose — and uncommitted correspondences cannot appear because they were never
        written (SCOPE.md §5: they live in the browser's store until the pairing is
        committed).

        Args:
            image_id: Single-image export. Mutually exclusive with ``project_id``.
            project_id: Whole-project export; joins through ``images``.
            source: ★ ``'manual'``/``'automatic'``. An export that mixes observations
                and inferences without saying which is which is the failure SCOPE.md §5
                added the column to prevent.
            confidence_gte: Drop anything below the surveyor's threshold.
            include_stale: Stale GCPs are excluded by default — a stale coordinate is
                one the system has already said it cannot stand behind, and shipping it
                in a deliverable is exactly what L12 forbids.

        Raises:
            ValueError: neither or both of ``image_id``/``project_id``.
        """
        if (image_id is None) == (project_id is None):
            raise ValueError("Pass exactly one of image_id or project_id.")

        stmt: Select[Any] = select(GCP).where(GCP.is_included_in_export.is_(True))
        if image_id is not None:
            stmt = stmt.where(GCP.image_id == image_id)
        else:
            stmt = stmt.join(Image, Image.id == GCP.image_id).where(
                Image.project_id == project_id, Image.deleted_at.is_(None)
            )
        if source is not None:
            stmt = stmt.where(GCP.source == source)
        if confidence_gte is not None:
            stmt = stmt.where(GCP.confidence >= confidence_gte)
        if not include_stale:
            stmt = stmt.where(GCP.is_stale.is_(False))

        stmt = stmt.order_by(GCP.code.asc().nulls_last(), GCP.created_at.asc(), GCP.id.asc())
        return await self._scalars(stmt)

    async def count_for_image(self, image_id: uuid.UUID) -> int:
        """How many GCPs an image has. Feeds ``ImageRead.gcp_count``."""
        return int(
            await self._scalar(
                select(func.count()).select_from(GCP).where(GCP.image_id == image_id)
            )
            or 0
        )

    async def list_overview(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
        album_id: uuid.UUID | None = None,
        min_confidence: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> tuple[Sequence[Any], int]:
        """★ ``GET /gcps`` — **every GCP, across every project.** Powers the dashboard map.

        Until this existed a GCP could only be read through the image that owns it. A
        surveyor with forty photographs across six projects could not answer *"where are
        all my control points?"* without forty requests.

        ★★ **ONE STATEMENT. NO N+1, BY CONSTRUCTION.** ``project_name``,
        ``image_filename`` and ``landmark_name`` are joined here, not walked from
        ``gcp.image.project.name`` — every relationship on every model is ``lazy="raise"``
        exactly so that walk cannot compile. This endpoint may return thousands of points
        for a single map render, and a per-row name lookup is thousands of round trips
        per pan.

        ★ The two joins are deliberately different. ``images`` and ``projects`` are
        **inner** joins: a GCP cannot exist without them (``image_id`` is NOT NULL and
        CASCADEs), so an outer join would only add a NULL branch that can never be taken.
        ``annotations`` is an **outer** join: ``landmark_id`` is nullable — a bare map
        click has no annotation, and ``ON DELETE SET NULL`` means a tidied-away landmark
        leaves the coordinate intact. An inner join there would silently drop exactly the
        GCPs whose landmark the surveyor cleaned up, and the map would just have fewer
        dots on it.

        ★ Soft-deleted images and projects are excluded: a point the surveyor has
        deleted the photograph for must not still be on the dashboard.

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``GCP_SORT_FIELDS``. The router defaults it to
                ``-created_at`` — newest first.
            project_id: One project.
            image_id: One photograph.
            album_id: Every project filed in this album. Joined through
                ``album_projects``; the composite PK's leading column is ``album_id``, so
                it is an index scan.
            min_confidence: 0–100 floor.
            bbox: ``(min_lon, min_lat, max_lon, max_lat)`` — ★ **longitudes first**,
                range-checked by :func:`~app.db.repositories.base.bbox_geography`. Uses
                ``ix_gcps_geom``.

        Returns:
            ``(rows, total)`` where each row carries the labelled columns
            ``id, project_id, project_name, image_id, image_filename, code,
            landmark_name, lat, lon, confidence, source, total_ce90_m`` —
            ``GcpOverview``'s fields, in its order. ``total`` ignores limit/offset.

        Raises:
            ValueError: a transposed or inverted bbox.
        """
        stmt: Select[Any] = (
            select(
                GCP.id.label("id"),
                Image.project_id.label("project_id"),
                Project.name.label("project_name"),
                GCP.image_id.label("image_id"),
                Image.filename.label("image_filename"),
                GCP.code.label("code"),
                Annotation.label.label("landmark_name"),
                st_y(GCP.geom).label("lat"),
                st_x(GCP.geom).label("lon"),
                GCP.confidence.label("confidence"),
                GCP.source.label("source"),
                GCP.accuracy_total_ce90_m.label("total_ce90_m"),
            )
            .join(Image, Image.id == GCP.image_id)
            .join(Project, Project.id == Image.project_id)
            .outerjoin(Annotation, Annotation.id == GCP.landmark_id)
            .where(Image.deleted_at.is_(None), Project.deleted_at.is_(None))
        )

        if project_id is not None:
            stmt = stmt.where(Image.project_id == project_id)
        if image_id is not None:
            stmt = stmt.where(GCP.image_id == image_id)
        if album_id is not None:
            stmt = stmt.join(
                album_projects, album_projects.c.project_id == Project.id
            ).where(album_projects.c.album_id == album_id)
        if min_confidence is not None:
            stmt = stmt.where(GCP.confidence >= min_confidence)
        if bbox is not None:
            stmt = stmt.where(func.ST_Intersects(GCP.geom, bbox_geography(*bbox)))

        # ★ Not ``self.page()``: that returns ``.scalars()``, which would throw away
        #   every joined name and hand back bare GCP entities — the exact N+1 this
        #   method exists to avoid. The count/sort/paginate helpers are shared, so the
        #   total is still derived from the *same* predicate as the page.
        total = int(await self._scalar(count_stmt_of(stmt)) or 0)
        ordered = apply_sort(stmt, sort, self._sortable, tiebreaker=GCP.id)
        return (await self._execute(apply_pagination(ordered, pagination))).all(), total

    async def gcp_ids_for_annotations(
        self, annotation_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """``AnnotationRead.gcp_ids`` for many annotations in **one** query.

        ★ Batch-loaded rather than per-annotation: the canvas loads up to 2000
        annotations at once (``MAX_ANNOTATIONS_PER_IMAGE``), and a per-row lookup is
        2000 round trips to render one screen. Every relationship on every model is
        ``lazy="raise"`` precisely so that this kind of N+1 fails loudly in development
        instead of quietly in production.

        Ordered by ``match_results.rank`` ASC, per ``AnnotationRead.gcp_ids``. The join
        is an **outer** join because a manual GCP may have no ``match_result_id`` at all
        (SCOPE.md §5) — an inner join would silently drop every GCP this build creates,
        which is all of them. Rank-less rows sort last, then by creation, so the order
        is total and stable.

        Args:
            annotation_ids: The annotations to look up. Empty ⇒ ``{}``, no query.

        Returns:
            ``{annotation_id: [gcp_id, ...]}``. Annotations with no GCPs are **absent**
            from the mapping; the caller defaults them to ``[]``.
        """
        if not annotation_ids:
            return {}
        stmt = (
            select(GCP.landmark_id, GCP.id)
            .outerjoin(MatchResult, MatchResult.id == GCP.match_result_id)
            .where(GCP.landmark_id.in_(list(annotation_ids)))
            .order_by(
                GCP.landmark_id.asc(),
                MatchResult.rank.asc().nulls_last(),
                GCP.created_at.asc(),
                GCP.id.asc(),
            )
        )
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for landmark_id, gcp_id in (await self._execute(stmt)).all():
            out.setdefault(landmark_id, []).append(gcp_id)
        return out

    # ── spatial — ★ the hottest queries in the product ───────────────────────

    async def find_in_bbox(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        image_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 1000,
    ) -> Sequence[GCP]:
        """Every GCP inside a viewport. **The hottest spatial query in the product.**

        ``ST_Intersects(geom, envelope)`` uses ``ix_gcps_geom`` (GIST), which is why
        §5.6 additionally sets ``ALTER TABLE gcps ALTER COLUMN geom SET STATISTICS
        1000``: the default sample badly misestimates viewport selectivity on clustered
        survey data and the planner picks a sequential scan.

        ★ The envelope is built lon-first and range-checked by
        :func:`~app.db.repositories.base.bbox_geography` — see it for why an
        unvalidated envelope is a bug that survives review.

        Args:
            min_lon: West edge. **Longitude first.**
            min_lat: South edge.
            max_lon: East edge.
            max_lat: North edge.
            image_id: Restrict to one photograph.
            project_id: Restrict to one project, joining through ``images``.
            limit: Hard cap. A viewport query is a map render, not an export; an
                unbounded one is a whole-table download triggered by a zoom-out.

        Raises:
            ValueError: transposed or inverted ordinates.
        """
        stmt: Select[Any] = select(GCP).where(
            func.ST_Intersects(GCP.geom, bbox_geography(min_lon, min_lat, max_lon, max_lat))
        )
        stmt = self._scope(stmt, image_id=image_id, project_id=project_id)
        return await self._scalars(stmt.order_by(GCP.id.asc()).limit(limit))

    async def find_within_radius_m(
        self,
        *,
        lon: float,
        lat: float,
        radius_m: float,
        image_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        exclude_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[tuple[GCP, float]]:
        """GCPs within ``radius_m`` **true metres**, nearest first, with their distances.

        ★ ``ST_DWithin(geom, pt, r)`` rather than ``ST_Distance(geom, pt) < r``: the
        former uses the GIST index, the latter computes a distance for every row in the
        table first. Same answer, different asymptote.

        ★ The metres are **true spheroidal metres**, which is the entire reason storage
        is ``geography`` and not ``geometry(...,3857)``: on 3857 the same call returns
        Mercator metres, inflated by ``1/cos(φ)`` — a 60% error at 53°N, which is much
        of European farmland (§5.2).

        Args:
            lon: **Longitude first.**
            lat: Latitude.
            radius_m: Radius in real ground metres.
            image_id: Restrict to one photograph.
            project_id: Restrict to one project.
            exclude_id: Skip this GCP — for "is there already one near where I just
                clicked?", where the row itself would otherwise always be the nearest
                hit at distance 0.
            limit: Cap.

        Returns:
            ``[(gcp, distance_m), ...]`` ordered by distance ascending.

        Raises:
            ValueError: ``radius_m`` non-positive, or transposed ordinates.
        """
        if radius_m <= 0:
            raise ValueError(f"radius_m must be > 0, got {radius_m}")
        point = point_wkt(lon, lat)  # ★ the one transposition site
        distance = func.ST_Distance(GCP.geom, point).label("distance_m")

        stmt: Select[Any] = select(GCP, distance).where(
            func.ST_DWithin(GCP.geom, point, radius_m)
        )
        stmt = self._scope(stmt, image_id=image_id, project_id=project_id)
        if exclude_id is not None:
            stmt = stmt.where(GCP.id != exclude_id)
        stmt = stmt.order_by(distance.asc(), GCP.id.asc()).limit(limit)
        return [(row[0], float(row[1])) for row in (await self._execute(stmt)).all()]

    async def count_within_radius_m(
        self,
        *,
        lon: float,
        lat: float,
        radius_m: float,
        image_id: uuid.UUID | None = None,
        exclude_id: uuid.UUID | None = None,
    ) -> int:
        """How many GCPs sit within ``radius_m`` of a point — duplicate suppression.

        The cheap form of :meth:`find_within_radius_m` for the "you already placed a
        GCP two metres from here" warning on the manual-create path. Warning, never
        blocking: two GCPs a metre apart on a field corner is a legitimate thing for a
        surveyor to want, and refusing it would be the tool overruling the person
        holding the evidence.
        """
        if radius_m <= 0:
            raise ValueError(f"radius_m must be > 0, got {radius_m}")
        point = point_wkt(lon, lat)
        stmt: Select[Any] = (
            select(func.count())
            .select_from(GCP)
            .where(func.ST_DWithin(GCP.geom, point, radius_m))
        )
        if image_id is not None:
            stmt = stmt.where(GCP.image_id == image_id)
        if exclude_id is not None:
            stmt = stmt.where(GCP.id != exclude_id)
        return int(await self._scalar(stmt) or 0)

    async def nearest(
        self,
        *,
        lon: float,
        lat: float,
        image_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 1,
    ) -> list[tuple[GCP, float]]:
        """The ``limit`` GCPs nearest a point, with their true-metre distances.

        Ordered with the ``<->`` KNN operator, which on a ``geography`` column is
        index-assisted against ``ix_gcps_geom`` and returns spheroidal metres. Unlike
        :meth:`find_within_radius_m` this has no radius to bound it, so the index-order
        scan is what keeps it from being a full table sort.

        Args:
            lon: **Longitude first.**
            lat: Latitude.
            image_id: Restrict to one photograph.
            project_id: Restrict to one project.
            limit: How many neighbours.

        Returns:
            ``[(gcp, distance_m), ...]``, nearest first. Empty when there are none.
        """
        point = point_wkt(lon, lat)
        knn = GCP.geom.op("<->")(point).label("distance_m")
        stmt: Select[Any] = select(GCP, knn)
        stmt = self._scope(stmt, image_id=image_id, project_id=project_id)
        stmt = stmt.order_by(knn.asc()).limit(limit)
        return [(row[0], float(row[1])) for row in (await self._execute(stmt)).all()]

    # ── adjustment — §6.2, and every clause of it is load-bearing ────────────

    async def adjust(
        self,
        gcp_id: uuid.UUID,
        *,
        lon: float,
        lat: float,
        pixel_x: float | None = None,
        pixel_y: float | None = None,
        satellite_pixel_x: float | None = None,
        satellite_pixel_y: float | None = None,
        adjusted_by: str | None = None,
        adjustment_note: str | None = None,
        accuracy_relative_ce90_m: float | None = None,
        accuracy_total_ce90_m: float | None = None,
        confidence: float | None = None,
    ) -> GCP:
        """Move a GCP, preserving the original answer forever. One statement, one transaction.

        ★★ **``original_geom`` is written once and never again.** It is the algorithm's
        answer (or, in manual mode, the first committed observation) and there is only
        one of those. The ``COALESCE(original_geom, geom)`` below is what enforces it:
        on the first adjustment ``original_geom`` is NULL so it takes the *old* ``geom``;
        on every subsequent adjustment it is already set, so it keeps itself. **In
        PostgreSQL every right-hand side of an ``UPDATE ... SET`` sees the OLD row**, so
        this is exact — no read-modify-write, no race between two adjusters, and nothing
        for a service to get wrong by checking ``manually_adjusted`` first.

        ★★ **``confidence`` is left untouched unless a caller explicitly passes one.**
        Tempting to set it to 100 on a human edit, and wrong: ``gcps.confidence`` is the
        score for this correspondence — it feeds ``best_confidence``, the ranking and
        the export filter. Overwriting it destroys the only record of how well the
        algorithm did, makes ``?confidence__gte=70`` meaningless (every adjusted point
        passes), and asserts a certainty the human never claimed. A surveyor nudging a
        marker three metres is *guessing better*, not measuring. Human certainty is
        carried by ``manually_adjusted`` + ``adjustment_offset_m`` + ``adjusted_by`` +
        the note. The ``confidence`` parameter exists only for the manual-mode
        re-commit, where the surveyor **re-declares** their 1–5 judgement with the new
        pairing (``GcpCorrespondenceUpdate``) — that is the human restating their own
        number, not the server inventing one.

        ★ ``adjustment_offset_m`` is ``ST_Distance`` on ``geography`` — **real ground
        metres** from the original answer to the new one, which is the whole reason
        storage is ``geography`` (§5.2).

        Args:
            gcp_id: The GCP to move.
            lon: New longitude. **Longitude first.**
            lat: New latitude.
            satellite_pixel_x: The other representation, derived by the service through
                the inverse chain (4326 → 3857 → ``inv(sat_geotransform)`` → mosaic px).
                None leaves the column alone — which is the manual-mode case, where
                there is no mosaic and the column is NULL by construction.
            satellite_pixel_y: As ``satellite_pixel_x``.
            adjusted_by: The principal. Recorded, not enforced.
            adjustment_note: Free text.
            accuracy_relative_ce90_m: Recomputed from the new click's zoom, when the
                caller recomputed it. None leaves it.
            accuracy_total_ce90_m: As above. Passing one without the other is legal —
                ``ck_gcps_accuracy_total_ge_parts`` is the DB's check on the pair, and
                it is the authority.
            confidence: **Only** for a manual re-declaration. See above.

        Returns:
            The refreshed :class:`GCP`.

        Raises:
            GcpNotFound: no such GCP.
            ValueError: transposed ordinates.
        """
        new_geom = point_wkt(lon, lat)  # ★ the one transposition site

        # Every RHS below reads the OLD row. That is what makes the COALESCEs correct.
        values: dict[str, Any] = {
            "geom": new_geom,
            "original_geom": func.coalesce(GCP.original_geom, GCP.geom),
            "original_satellite_pixel_x": func.coalesce(
                GCP.original_satellite_pixel_x, GCP.satellite_pixel_x
            ),
            "original_satellite_pixel_y": func.coalesce(
                GCP.original_satellite_pixel_y, GCP.satellite_pixel_y
            ),
            "original_confidence": func.coalesce(GCP.original_confidence, GCP.confidence),
            "manually_adjusted": True,
            "adjusted_by": adjusted_by,
            "adjusted_at": func.now(),
            "adjustment_note": adjustment_note,
            # Distance from the ORIGINAL answer — not from the previous adjustment —
            # so a surveyor who nudges five times still sees how far they are from
            # where the system put it.
            "adjustment_offset_m": func.ST_Distance(
                func.coalesce(GCP.original_geom, GCP.geom), new_geom
            ),
        }
        if satellite_pixel_x is not None:
            values["satellite_pixel_x"] = satellite_pixel_x
        if satellite_pixel_y is not None:
            values["satellite_pixel_y"] = satellite_pixel_y
        # ★ The PHOTO endpoint (1.2.6): a bare manual GCP's pixel lives on THIS row and
        #   nowhere else, so re-committing the pairing may move it here. None = untouched.
        if pixel_x is not None:
            values["pixel_x"] = pixel_x
        if pixel_y is not None:
            values["pixel_y"] = pixel_y
        if accuracy_relative_ce90_m is not None:
            values["accuracy_relative_ce90_m"] = accuracy_relative_ce90_m
        if accuracy_total_ce90_m is not None:
            values["accuracy_total_ce90_m"] = accuracy_total_ce90_m
        if confidence is not None:
            values["confidence"] = confidence

        stmt = update(GCP).where(GCP.id == gcp_id).values(**values).returning(GCP.id)
        if (await self._execute(stmt)).scalar_one_or_none() is None:
            raise GcpNotFound(f"No GCP {gcp_id}.")
        return await self._reload(gcp_id)

    async def reset(self, gcp_id: uuid.UUID) -> tuple[GCP, bool]:
        """Restore a GCP to its original answer and clear the adjustment. **Idempotent.**

        ★ The ``WHERE ... AND manually_adjusted`` is what makes it idempotent: a second
        reset matches no row, changes nothing, and returns the same GCP. The
        ``reverted`` flag reports which happened, so the caller can decide — endpoint 41
        is specified as idempotent *and* as ``409 GCP_ORIGINAL_UNAVAILABLE`` when there
        was never an adjustment to undo, and only the service knows which of those its
        caller asked for. **This layer refuses to guess, and it refuses to lie about
        what it did.**

        ★ Every ``original_*`` column is cleared, including ``original_geom``. That is
        not losing the algorithm's answer — after a reset ``geom`` **is** the original
        answer — and ``ck_gcps_no_adjustment_metadata_unless_adjusted`` requires it: a
        row that is not adjusted may carry no adjustment metadata, and a lingering
        ``original_geom`` would be exactly that.

        Args:
            gcp_id: The GCP to reset.

        Returns:
            ``(gcp, reverted)``. ``reverted`` is False when the GCP was already
            unadjusted.

        Raises:
            GcpNotFound: no such GCP.
        """
        stmt = (
            update(GCP)
            .where(GCP.id == gcp_id, GCP.manually_adjusted.is_(True))
            .values(
                geom=GCP.original_geom,
                satellite_pixel_x=GCP.original_satellite_pixel_x,
                satellite_pixel_y=GCP.original_satellite_pixel_y,
                # COALESCE, not a bare assignment: original_confidence is written by
                # `adjust`, but a row adjusted by some future path that forgot it must
                # not have its confidence nulled — the column is NOT NULL.
                confidence=func.coalesce(GCP.original_confidence, GCP.confidence),
                manually_adjusted=False,
                original_geom=None,
                original_satellite_pixel_x=None,
                original_satellite_pixel_y=None,
                original_confidence=None,
                adjustment_offset_m=None,
                adjusted_by=None,
                adjusted_at=None,
                adjustment_note=None,
            )
            .returning(GCP.id)
        )
        reverted = (await self._execute(stmt)).scalar_one_or_none() is not None
        gcp = await self.get(gcp_id)
        if gcp is None:
            raise GcpNotFound(f"No GCP {gcp_id}.")
        if reverted:
            gcp = await self.refresh(gcp)
        return gcp, reverted

    async def update_metadata(
        self,
        gcp_id: uuid.UUID,
        *,
        code: str | None = None,
        set_code: bool = False,
        name: str | None = None,
        set_name: bool = False,
        is_included_in_export: bool | None = None,
        adjustment_note: str | None = None,
        set_note: bool = False,
    ) -> GCP:
        """A metadata-only edit. ★ **Does not set ``manually_adjusted``.**

        §6.2: *"Renaming a GCP is not adjusting it."* A metadata edit that flipped
        ``manually_adjusted`` would put a false claim into every export — that a human
        had reviewed and moved this coordinate — on the strength of someone fixing a
        typo in a label.

        ``set_code``/``set_note`` distinguish "not supplied" from "explicitly set to
        null", which a bare ``None`` cannot. Both columns are nullable and clearing them
        is a legitimate edit.

        Raises:
            GcpNotFound: no such GCP.
            GcpCodeConflict: ``code`` is already used on this image.
        """
        values: dict[str, Any] = {}
        if set_code:
            values["code"] = code
        if set_name:
            values["name"] = name
        if is_included_in_export is not None:
            values["is_included_in_export"] = is_included_in_export
        if set_note:
            values["adjustment_note"] = adjustment_note

        if not values:
            gcp = await self.get(gcp_id)
            if gcp is None:
                raise GcpNotFound(f"No GCP {gcp_id}.")
            return gcp

        stmt = update(GCP).where(GCP.id == gcp_id).values(**values).returning(GCP.id)
        try:
            found = (await self._execute(stmt)).scalar_one_or_none()
        except IntegrityError as exc:
            self._reraise_code_conflict(exc, code=code)
            raise
        if found is None:
            raise GcpNotFound(f"No GCP {gcp_id}.")
        return await self._reload(gcp_id)

    async def list_for_project(
        self, project_id: uuid.UUID
    ) -> Sequence[tuple[GCP, float, float]]:
        """Every live GCP in a project as ``(gcp, lon, lat)``, whatever its export flag.

        ★ **Deliberately wider than :meth:`list_for_export`.** That method answers "what
        belongs in the deliverable" and so drops ``is_included_in_export = false`` and
        stale rows. This one answers "what could an incoming file be talking about", and
        those two rows are exactly the ones an operator is most likely to be importing a
        correction for — a point they excluded because they doubted it, or one the system
        marked stale. Filtering them here would make the fix unreachable and give the
        operator an "unmatched" report naming points that are plainly in their project.

        ★ **Longitude and latitude come back from PostGIS, not from a Python decode.**
        The caller needs numbers to compare an incoming coordinate against, and
        ``ST_X``/``ST_Y`` on the stored column is the same read the map and the exporter
        do. Decoding the EWKB in a service would be a second implementation of the one
        thing this system must never get wrong, and would live above the layer that owns
        geometry.

        Ordered like the export so a preview lists points the way the table does.
        """
        stmt = (
            select(GCP, st_x(GCP.geom).label("lon"), st_y(GCP.geom).label("lat"))
            .join(Image, Image.id == GCP.image_id)
            .where(Image.project_id == project_id, Image.deleted_at.is_(None))
            .order_by(GCP.code.asc().nulls_last(), GCP.created_at.asc(), GCP.id.asc())
        )
        rows = (await self._execute(stmt)).all()
        return [(row[0], float(row[1]), float(row[2])) for row in rows]

    async def set_elevation(
        self,
        gcp_id: uuid.UUID,
        *,
        elevation_m: float | None,
        elevation_source: str | None,
        elevation_ce90_m: float | None,
    ) -> GCP:
        """Write the third coordinate and the source that produced it, as one fact.

        ★ **The three columns move together, and that is the whole point.**
        ``ck_gcps_elevation_source_consistent`` requires ``(elevation_m IS NULL) =
        (elevation_source IS NULL)``, so a caller that could set one without the other
        would be able to write a row the schema rejects — or, worse, a row that passes
        because a *previous* source is still sitting in the column, silently attributing
        this elevation to a DEM that never saw it. Taking all three in one signature makes
        that unrepresentable rather than merely discouraged.

        ★ ``elevation_ce90_m`` is passed explicitly, including as ``None``. A vertical
        error bar is not derivable from the elevation, and defaulting it to anything —
        least of all 0 — would launder an unquantified number into a measured one
        (``gis.elevation.base``). NULL says "we do not know how wrong this is", which for
        a value the operator supplied from outside the system is the true answer.

        Args:
            gcp_id: The GCP to write.
            elevation_m: Metres above the vertical datum, or None to clear.
            elevation_source: ``local_dem|copernicus_dem|srtm|exif|manual``, or None —
                and None **iff** ``elevation_m`` is None.
            elevation_ce90_m: Vertical CE90 in metres, or None when unquantified.

        Raises:
            GcpNotFound: no such GCP.
            ValueError: the source/value pair violates the consistency rule. Raised here
                rather than left to the database so the caller gets a usable message
                instead of an IntegrityError from a constraint name.
        """
        if (elevation_m is None) != (elevation_source is None):
            raise ValueError(
                "elevation_m and elevation_source must both be set or both be None "
                f"(got elevation_m={elevation_m!r}, elevation_source={elevation_source!r})"
            )

        stmt = (
            update(GCP)
            .where(GCP.id == gcp_id)
            .values(
                elevation_m=elevation_m,
                elevation_source=elevation_source,
                elevation_ce90_m=elevation_ce90_m,
            )
            .returning(GCP.id)
        )
        found = (await self._execute(stmt)).scalar_one_or_none()
        if found is None:
            raise GcpNotFound(f"No GCP {gcp_id}.")
        return await self._reload(gcp_id)

    # ── staleness — the three writer paths, one SQL site ─────────────────────

    async def mark_stale(
        self,
        *,
        reason: GcpStaleReason,
        image_id: uuid.UUID | None = None,
        landmark_id: uuid.UUID | None = None,
        match_result_id: uuid.UUID | None = None,
        exclude_match_result_id: uuid.UUID | None = None,
    ) -> int:
        """Flag GCPs as stale. **Never recomputes them.**

        ★ Staleness is a flag and never an auto-recompute (§6.2). A GCP is a coordinate
        that may already be in a survey report, a contract, or a machine-control file.
        **It changes when a human decides it changes.** Every path that *could*
        invalidate one marks it and says so; ``POST /images/{id}/gcps/recompute`` is the
        only door, and it is one a person opens.

        There are exactly three writer paths, and each supplies a different selector:

        * the source annotation was edited or deleted → ``landmark_id`` +
          ``landmark_moved`` / ``landmark_deleted``;
        * a revision was restored → ``image_id`` + ``annotations_restored``;
        * a different match result was selected → ``image_id`` +
          ``exclude_match_result_id`` (the newly selected one) +
          ``homography_superseded``.

        ★ ``is_stale`` and ``stale_reason`` are set in one statement because
        ``ck_gcps_stale_reason`` is a biconditional — ``(is_stale) = (stale_reason IS
        NOT NULL)`` — and two statements would leave a moment where the row violates it,
        or a path that sets one and forgets the other.

        Already-stale rows are skipped, so the **first** reason a GCP went stale is the
        one that survives. That is the useful one: "the landmark moved" explains the
        staleness; "a revision was restored" ten minutes later merely re-states it.

        Args:
            reason: Why.
            image_id: Every GCP on a photograph.
            landmark_id: Every GCP derived from one annotation.
            match_result_id: Every GCP citing one match result.
            exclude_match_result_id: Spare GCPs citing this result. Combines with
                ``image_id`` for the "selection moved" path.

        Returns:
            How many rows were newly marked.

        Raises:
            ValueError: no selector, which would mark **every GCP in the database**.
        """
        conditions: list[Any] = []
        if image_id is not None:
            conditions.append(GCP.image_id == image_id)
        if landmark_id is not None:
            conditions.append(GCP.landmark_id == landmark_id)
        if match_result_id is not None:
            conditions.append(GCP.match_result_id == match_result_id)
        if exclude_match_result_id is not None:
            conditions.append(
                or_(
                    GCP.match_result_id.is_(None),
                    GCP.match_result_id != exclude_match_result_id,
                )
            )
        if not conditions:
            raise ValueError(
                "mark_stale requires at least one selector; an unselected UPDATE would "
                "mark every GCP in the database stale."
            )

        stmt = (
            update(GCP)
            .where(and_(*conditions), GCP.is_stale.is_(False))
            .values(is_stale=True, stale_reason=reason)
        )
        return int((await self._execute(stmt)).rowcount or 0)

    async def clear_stale(self, gcp_id: uuid.UUID) -> bool:
        """Clear the stale flag on one GCP, after a human recomputed or accepted it.

        Both columns again, for ``ck_gcps_stale_reason``.

        Returns:
            True when the row was stale and is no longer.
        """
        stmt = (
            update(GCP)
            .where(GCP.id == gcp_id, GCP.is_stale.is_(True))
            .values(is_stale=False, stale_reason=None)
            .returning(GCP.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def count_stale_for_image(self, image_id: uuid.UUID) -> int:
        """How many of an image's GCPs are stale. Uses ``ix_gcps_stale``."""
        return int(
            await self._scalar(
                select(func.count())
                .select_from(GCP)
                .where(GCP.image_id == image_id, GCP.is_stale.is_(True))
            )
            or 0
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _filtered(
        self,
        stmt: Select[Any],
        *,
        match_result_id: uuid.UUID | None,
        source: str | None,
        confidence_gte: float | None,
        confidence_lte: float | None,
        manually_adjusted: bool | None,
        is_stale: bool | None,
        is_included_in_export: bool | None,
        q: str | None,
    ) -> Select[Any]:
        """``GcpListParams`` → predicates. One site, so the two list endpoints agree."""
        if match_result_id is not None:
            stmt = stmt.where(GCP.match_result_id == match_result_id)
        if source is not None:
            stmt = stmt.where(GCP.source == source)
        if confidence_gte is not None:
            stmt = stmt.where(GCP.confidence >= confidence_gte)
        if confidence_lte is not None:
            stmt = stmt.where(GCP.confidence <= confidence_lte)
        if manually_adjusted is not None:
            stmt = stmt.where(GCP.manually_adjusted.is_(manually_adjusted))
        if is_stale is not None:
            stmt = stmt.where(GCP.is_stale.is_(is_stale))
        if is_included_in_export is not None:
            stmt = stmt.where(GCP.is_included_in_export.is_(is_included_in_export))
        if q:
            # Free-text spans `code` and the landmark's label, so the annotation has to
            # be reachable — outer join, because `landmark_id` is nullable and a bare
            # click has no annotation at all.
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.outerjoin(Annotation, Annotation.id == GCP.landmark_id).where(
                or_(
                    GCP.code.ilike(pattern, escape="\\"),
                    Annotation.label.ilike(pattern, escape="\\"),
                )
            )
        return stmt

    def _scope(
        self,
        stmt: Select[Any],
        *,
        image_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
    ) -> Select[Any]:
        """Restrict a spatial query to an image or a project."""
        if image_id is not None:
            stmt = stmt.where(GCP.image_id == image_id)
        if project_id is not None:
            stmt = stmt.join(Image, Image.id == GCP.image_id).where(
                Image.project_id == project_id, Image.deleted_at.is_(None)
            )
        return stmt

    async def _reload(self, gcp_id: uuid.UUID) -> GCP:
        """Read a row back after a Core ``UPDATE``.

        The identity map still holds the pre-update values — a Core UPDATE does not go
        through the ORM's unit of work — so returning the cached object would return
        the old coordinate. Every relationship is ``lazy="raise"``, so there is no lazy
        refresh to paper over it either. This is the honest re-read.
        """
        gcp = await self.get(gcp_id)
        if gcp is None:  # pragma: no cover — the UPDATE just matched it.
            raise GcpNotFound(f"No GCP {gcp_id}.")
        return await self.refresh(gcp)

    async def _flush_mapping_code_conflict(
        self, *, image_id: uuid.UUID, code: str | None
    ) -> None:
        """Flush an INSERT, turning ``uq_gcps_image_code`` into a domain conflict."""
        try:
            await self.flush()
        except IntegrityError as exc:
            self._reraise_code_conflict(exc, code=code)
            raise

    @staticmethod
    def _reraise_code_conflict(exc: IntegrityError, *, code: str | None) -> None:
        """Map ``uq_gcps_image_code`` → ``GcpCodeConflict``; leave anything else alone.

        ★ Only the **named** constraint is mapped. When the driver gives no constraint
        name the exception is re-raised untouched: guessing which constraint fired is
        how a 409 lands on a 500 — or worse, how a NOT NULL violation is reported to a
        surveyor as "that code is taken".
        """
        if constraint_name_of(exc) == "uq_gcps_image_code":
            raise GcpCodeConflict(
                f"GCP code {code!r} is already used on this image."
            ) from exc
