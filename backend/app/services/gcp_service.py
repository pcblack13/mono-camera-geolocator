"""``gcp_service`` — ★★ **THE HEART OF THIS BUILD** (SCOPE.md §5).

With the automatic matching engine deferred, a GCP is created by a **manual
correspondence**: the surveyor marks a landmark in the photograph, clicks the same
physical spot on the satellite map, and the coordinate is recorded. **It is a DIRECT
OBSERVATION, not an inference** (SCOPE.md §2) — there is no homography, so there is nothing
degenerate and no estimated confidence to calibrate.

This service is where a request becomes that observation. It:

* derives the photo-pixel endpoint (from an annotation's representative point, or a bare
  click) in **original image pixel space**;
* resolves the imagery provider the surveyor was looking at, and reads its ground-sample
  distance and its own georeferencing error;
* computes **reported positional accuracy from imagery GSD + click precision at the map's
  zoom level** via ``gis.accuracy.manual_gcp_accuracy`` — a real, defensible number, NOT a
  match score (SCOPE.md §5);
* maps the surveyor's declared 1–5 judgement to the ``confidence`` column
  (``SURVEYOR_CONFIDENCE_TO_SCORE``) — **never computing it**;
* fills the third coordinate from ``elevation_service``, or records null honestly;
* writes through ``GcpRepository.create_manual``, which hardcodes ``source='manual'`` so an
  observation can never be confused with an inference downstream or in an export.

★ **The GeoTIFF short-circuit** (SCOPE.md §3): when the photograph is itself a georeferenced
raster, a marked pixel maps to lat/lon **exactly** through the file's geotransform, with no
map click and no matching. :meth:`create_from_geotiff` is that path — the only *automatic*
path that exists in this build, and it is exact rather than estimated.

★ **Recompute is DEFERRED** (SCOPE.md §4): both ``refit`` and ``rederive`` need the
homography estimator, which is an ABC only. :meth:`recompute` raises the 501.
"""

from __future__ import annotations

import logging
import uuid

from gis.accuracy import AccuracyEstimate, LANDMARK_PIXEL_TOLERANCE_PX, manual_gcp_accuracy
from gis.tiles import resolution_at

from app.core.config import Settings
from app.core.exceptions import (
    AnnotationNotFound,
    FeatureDeferredError,
    GcpNotFound,
    GcpOriginalUnavailable,
    ValidationError,
)
from app.db.repositories.annotations import AnnotationRepository
from app.db.repositories.gcps import GcpRepository
from app.db.repositories.images import ImageRepository
from app.models.gcp import GCP
from app.models.image import Image
from app.schemas.gcp import (
    SURVEYOR_CONFIDENCE_TO_SCORE,
    GcpCorrespondenceUpdate,
    GcpManualCreate,
    GcpUpdate,
)
from app.schemas.enums import ProviderName
from app.services.elevation_service import ElevationResult, ElevationService
from app.services.imagery_service import ImageryService

__all__ = ["GcpService"]

_log = logging.getLogger("app.services.gcp")

#: The click zoom a copied point falls back to when the original recorded none —
#: a street-level satellite zoom, so the derived accuracy is neither flattering nor absurd.
_COPY_DEFAULT_ZOOM = 18

#: Half-pixel discretisation error (1-sigma) for the GeoTIFF short-circuit: there is no
#: map click, only the marked pixel's own quantisation, so the pointing term is smaller than
#: the ``gis.accuracy.DEFAULT_CLICK_SIGMA_PX`` (1 px) a satellite-map landmark click carries —
#: half of it, and half the 1 px landmark pixel-accuracy ceiling.
_GEOTIFF_MARK_SIGMA_PX = 0.5

#: ★ The exact path's mark accuracy MUST sit within the product's landmark pixel-accuracy
#: ceiling (``top = 1 px``). This codifies the guarantee — the synthetic-pattern figure is the
#: half-pixel mark, comfortably under the 1 px ceiling — and trips at import if either constant
#: is ever edited into an inconsistent pair.
assert _GEOTIFF_MARK_SIGMA_PX <= LANDMARK_PIXEL_TOLERANCE_PX, (
    "GeoTIFF mark sigma must not exceed the landmark pixel-accuracy ceiling"
)


class GcpService:
    """Create, adjust, reset and re-pair ground control points.

    Args:
        session: The request's async session — the transaction boundary. Repositories are
            constructed over it; nothing here commits.
        settings: The backend settings.
        imagery: Resolves the provider the accuracy is computed against. Shares the
            process-wide registry when injected.
        elevation: Fills the third coordinate, or records null honestly.
    """

    def __init__(
        self,
        session,
        settings: Settings,
        *,
        imagery: ImageryService | None = None,
        elevation: ElevationService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._gcps = GcpRepository(session)
        self._images = ImageRepository(session)
        self._annotations = AnnotationRepository(session)
        self._imagery = imagery if imagery is not None else ImageryService(settings)
        self._elevation = elevation if elevation is not None else ElevationService(settings)

    # ── creation — SCOPE.md §5, the product's core interaction ────────────────

    async def create_manual(self, image: Image, body: GcpManualCreate) -> GCP:
        """Record a surveyor's photo-pixel ↔ map-click correspondence as a GCP.

        Args:
            image: The photograph the correspondence is on. Loaded by ``deps``.
            body: The validated request — exactly one of ``landmark_id``/``image_px``, the
                map click (``lat``/``lon``), the zoom at the moment of the click, the
                surveyor's 1–5 judgement, and the basemap they were looking at.

        Returns:
            The created :class:`GCP`, flushed so its id and timestamps are readable in the
            same transaction. ``source='manual'`` by construction.

        Raises:
            AnnotationNotFound: ``landmark_id`` names no annotation on this image.
            GcpCodeConflict: ``code`` is already used on the image (from the repository).
            ValidationError: an impossible accuracy input (e.g. a zoom that yields a
                non-positive GSD).
        """
        pixel_x, pixel_y = await self._resolve_photo_endpoint(image.id, body)

        provider = self._imagery.resolve(body.provider)
        caps = provider.capabilities()
        accuracy = self._manual_accuracy(
            lat=body.lat, map_zoom=body.map_zoom, tile_size_px=caps.tile_size_px,
            georef_ce90_m=caps.georef_ce90_m,
        )
        reference_imagery = self._reference_imagery_record(
            provider, lon=body.lon, lat=body.lat, map_zoom=body.map_zoom
        )
        elevation = self._elevation.sample_one(
            body.lon, body.lat, project_id=image.project_id, image_id=image.id
        )

        return await self._gcps.create_manual(
            image_id=image.id,
            lon=body.lon,
            lat=body.lat,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            confidence=self._score_for(body.declared_confidence),
            accuracy_relative_ce90_m=accuracy.relative_ce90_m,
            georef_ce90_m=accuracy.georef_ce90_m,
            accuracy_total_ce90_m=accuracy.total_ce90_m,
            accuracy_dominant_term=accuracy.dominant_term,
            accuracy_semi_major_ce90_m=accuracy.semi_major_ce90_m,
            accuracy_semi_minor_ce90_m=accuracy.semi_minor_ce90_m,
            accuracy_azimuth_deg=accuracy.azimuth_deg,
            landmark_id=body.landmark_id,
            match_result_id=body.match_result_id,
            code=body.code,
            name=body.name,
            elevation_m=elevation.elevation_m,
            elevation_source=elevation.source,
            elevation_ce90_m=elevation.vertical_ce90_m,
            is_included_in_export=body.is_included_in_export,
            reference_imagery=reference_imagery,
        )

    async def copy_to(self, source: Image, target: Image) -> list[GCP]:
        """Carry every control point of ``source`` onto ``target`` — same pixel, same spot.

        ★ A NEW FRAME, THE SAME AIM (2026-09-09, owner ask). When a camera adopts a
        fresh frame and the operator says it has not moved, each point is valid at
        the same pixel of the new picture. Each one is recreated through
        :meth:`create_manual` — its own annotation on the new frame, its elevation
        re-sampled there, the declared judgement, code and name kept, the basemap
        and zoom of the original click kept as provenance — never cloned as a bare
        row that would point at another image's annotation.
        """
        from app.core.pagination import MAX_LIMIT, PaginationParams, SortKey, SortParams
        from app.db.types import as_lonlat
        from app.schemas.common import PixelXY
        from app.schemas.gcp import GCP_SORT_FIELDS

        rows, _total = await self._gcps.list_for_image(
            source.id,
            pagination=PaginationParams(limit=MAX_LIMIT, offset=0),
            sort=SortParams.parse(None, allowed=GCP_SORT_FIELDS, default=(SortKey("created_at"),)),
        )
        copied: list[GCP] = []
        for gcp in rows:
            lonlat = as_lonlat(gcp.geom)
            if lonlat is None:
                continue
            ref = gcp.reference_imagery if isinstance(gcp.reference_imagery, dict) else {}
            zoom = ref.get("zoom")
            # ★ Provenance, not a gate: a basemap this build no longer knows must not
            #   stop the point from travelling — the default provider stands in.
            provider = ref.get("provider")
            if provider not in {p.value for p in ProviderName}:
                provider = None
            body = GcpManualCreate(
                image_px=PixelXY(x=float(gcp.pixel_x), y=float(gcp.pixel_y)),
                lat=float(lonlat[1]),
                lon=float(lonlat[0]),
                declared_confidence=self._declared_for(float(gcp.confidence)),
                map_zoom=int(zoom) if isinstance(zoom, int | float) else _COPY_DEFAULT_ZOOM,
                provider=provider,
                code=gcp.code,
                name=gcp.name,
                is_included_in_export=bool(gcp.is_included_in_export),
            )
            copied.append(await self.create_manual(target, body))
        return copied

    @staticmethod
    def _declared_for(score: float) -> int:
        """The surveyor's 1–5 judgement back from the stored score — nearest band, the
        same inversion the presenter shows the client."""
        return min(SURVEYOR_CONFIDENCE_TO_SCORE, key=lambda k: abs(SURVEYOR_CONFIDENCE_TO_SCORE[k] - score))

    def _reference_imagery_record(
        self, provider, *, lon: float, lat: float, map_zoom: int
    ) -> dict:
        """The imagery-provenance record stored on the GCP row (``gcps.reference_imagery``).

        ★ TRACEABILITY, honestly: everything here is what was KNOWN at click time —
        provider, cache variant (the config fingerprint), zoom, the tile the click fell
        in, the epistemic status of the GSD/CE90 figures, whether the imagery date is
        even knowable, and whether that tile was in the local cache. Nothing is invented;
        an unknown is recorded as unknown.
        """
        from datetime import UTC, datetime

        from gis.imagery.cache.base import TileCacheKey
        from gis.tiles import lonlat_to_tile
        from gis.types import BasemapKind as GisBasemapKind

        caps = provider.capabilities()
        tile = lonlat_to_tile(lon, lat, map_zoom)
        variant = provider.cache_variant(GisBasemapKind.SATELLITE)
        cached = None
        cache = self._imagery.tile_cache
        if cache is not None:
            try:
                cached = cache.contains(
                    TileCacheKey(
                        provider=provider.name, z=tile.z, x=tile.x, y=tile.y, variant=variant
                    )
                )
            except Exception:  # noqa: BLE001 — provenance must not fail a GCP
                cached = None
        beyond_native = (
            caps.native_max_zoom is not None and map_zoom > caps.native_max_zoom
        )
        return {
            "provider": provider.name,
            "variant": variant,
            "zoom": map_zoom,
            "tile_x": tile.x,
            "tile_y": tile.y,
            "tile_size_px": caps.tile_size_px,
            "gsd_status": caps.gsd_status,
            "accuracy_status": caps.accuracy_status,
            "native_max_zoom": caps.native_max_zoom,
            "native_resolution_status": caps.native_resolution_status,
            "beyond_native_resolution": beyond_native,
            "imagery_date_known": caps.imagery_date_known,
            "imagery_date": None,  # ★ never fabricated; a date-known provider would set it
            "tile_was_cached": cached,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    async def create_from_geotiff(
        self,
        image: Image,
        *,
        pixel_x: float,
        pixel_y: float,
        declared_confidence: int,
        landmark_id: uuid.UUID | None = None,
        code: str | None = None,
        is_included_in_export: bool = True,
    ) -> GCP:
        """★ **The GeoTIFF short-circuit** (SCOPE.md §3) — an EXACT GCP, no map click.

        When the photograph is a georeferenced raster, a marked pixel maps to lat/lon
        exactly through the file's own geotransform. There is no matching and no map
        click; the coordinate is as good as the file's georeferencing.

        Args:
            image: The georeferenced photograph. Must carry a CRS and a 6-tuple
                geotransform.
            pixel_x: The marked pixel, original image space (pixel-centre convention).
            pixel_y: As ``pixel_x``.
            declared_confidence: The surveyor's 1–5 judgement of the *landmark
                identification* — the coordinate itself is exact, but which pixel is the
                landmark is still a human call.
            landmark_id: The annotation this hangs off, if any.
            code: ``'GCP01'``.
            is_included_in_export: Export filter flag.

        Returns:
            The created :class:`GCP`, exact for the file's georeferencing.

        Raises:
            ValidationError: the image is not georeferenced, or its CRS cannot be resolved.
        """
        lon, lat = self._geotiff_lonlat(image, pixel_x, pixel_y)

        gsd_m = image.gsd_m if image.gsd_m and image.gsd_m > 0 else self._geotiff_gsd(image)
        # No map-click error — only the marked pixel's own discretisation — and the file's
        # own georeferencing, which for a survey-grade ortho is small. ``georef_ce90_m`` is
        # unknown per-file and is taken as 0.0: the exact path claims no absolute error it
        # cannot substantiate, and the honest residual is the half-pixel mark.
        accuracy = manual_gcp_accuracy(
            gsd_m, georef_ce90_m=0.0, click_sigma_px=_GEOTIFF_MARK_SIGMA_PX
        )
        elevation = self._elevation.sample_one(
            lon, lat, project_id=image.project_id, image_id=image.id
        )

        return await self._gcps.create_manual(
            image_id=image.id,
            lon=lon,
            lat=lat,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            confidence=self._score_for(declared_confidence),
            accuracy_relative_ce90_m=accuracy.relative_ce90_m,
            georef_ce90_m=accuracy.georef_ce90_m,
            accuracy_total_ce90_m=accuracy.total_ce90_m,
            # ★ For the exact path the limiting term is the imagery's georeferencing, not a
            #   map click — say so, so the UI tells the surveyor the right thing to improve.
            accuracy_dominant_term="georeference",
            accuracy_semi_major_ce90_m=accuracy.semi_major_ce90_m,
            accuracy_semi_minor_ce90_m=accuracy.semi_minor_ce90_m,
            accuracy_azimuth_deg=accuracy.azimuth_deg,
            landmark_id=landmark_id,
            code=code,
            elevation_m=elevation.elevation_m,
            elevation_source=elevation.source,
            elevation_ce90_m=elevation.vertical_ce90_m,
            is_included_in_export=is_included_in_export,
        )

    # ── cross-project reads ───────────────────────────────────────────────────

    async def list_overview(
        self,
        *,
        pagination,
        sort,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
        album_id: uuid.UUID | None = None,
        min_confidence: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ):
        """★ ``GET /gcps`` — every GCP across every project, for the dashboard map.

        Pure delegation: there is no policy in this read, and the interesting part — the
        joins that resolve ``project_name``/``image_filename``/``landmark_name`` in one
        statement — is SQL and therefore lives in the repository. The service exists in
        the path so the router keeps its one and only door into the data layer.

        Returns:
            ``(rows, total)``; each row carries ``GcpOverview``'s fields as labelled
            columns.
        """
        return await self._gcps.list_overview(
            pagination=pagination,
            sort=sort,
            project_id=project_id,
            image_id=image_id,
            album_id=album_id,
            min_confidence=min_confidence,
            bbox=bbox,
        )

    # ── adjustment (§6.2) ─────────────────────────────────────────────────────

    async def adjust(self, gcp: GCP, body: GcpUpdate) -> GCP:
        """``PATCH /gcps/{id}`` (40) — move a GCP, or edit its metadata.

        The two modes §6.2 defines, restricted to what a manual observation can honour:

        * ``lat``/``lon`` present → a positional adjustment. ``geom`` moves; the original
          answer is preserved forever by the repository's ``COALESCE`` (see
          ``GcpRepository.adjust``). ``declared_confidence`` may accompany it — the surveyor
          restating their own 1–5 judgement, never the server inventing one.
        * neither → a metadata-only edit (``code`` / ``is_included_in_export`` /
          ``adjustment_note``). ★ Does **not** set ``manually_adjusted``: renaming a GCP is
          not adjusting it.

        ★ ``satellite_px`` adjustment is not honoured in this build: it is the automatic
        path's inverse-chain edit, and a manual observation has no satellite mosaic to
        project against. A ``satellite_px``-only PATCH is refused rather than silently
        dropped.

        Raises:
            GcpNotFound: the row vanished between load and write.
            ValidationError: ``satellite_px`` on a manual GCP (no mosaic to derive from).
        """
        changed = body.changed_fields()
        has_latlon = "lat" in changed and "lon" in changed
        has_sat = "satellite_px" in changed
        # ★ The PHOTO endpoint (1.2.6): movable in the same edit, for a BARE GCP only.
        has_image_px = "image_px" in changed and body.image_px is not None
        if has_image_px:
            if gcp.landmark_id is not None:
                raise ValidationError(
                    "This GCP's photo mark comes from its landmark — move the landmark "
                    "on the photograph (PATCH /annotations/{id}) instead of the GCP."
                )
            if not has_latlon:
                raise ValidationError(
                    "image_px travels with lat/lon: an edit re-commits the whole "
                    "pairing, not half of it."
                )

        confidence = (
            self._score_for(body.declared_confidence)
            if body.declared_confidence is not None
            else None
        )

        # Renaming is independent of moving the point — apply it first so it lands on
        # whichever path (move or metadata) the rest of this edit takes.
        if "name" in changed:
            await self._gcps.update_metadata(gcp.id, name=body.name, set_name=True)

        if has_latlon:
            return await self._gcps.adjust(
                gcp.id,
                lon=body.lon,  # type: ignore[arg-type]  # narrowed by has_latlon
                lat=body.lat,  # type: ignore[arg-type]
                pixel_x=body.image_px.x if has_image_px else None,  # type: ignore[union-attr]
                pixel_y=body.image_px.y if has_image_px else None,  # type: ignore[union-attr]
                adjustment_note=body.adjustment_note,
                confidence=confidence,
            )

        if has_sat:
            raise ValidationError(
                "satellite_px adjustment is part of the deferred automatic path: a "
                "manually observed GCP has no satellite mosaic to project a pixel against. "
                "Move the marker on the map (send lat/lon), or re-pair via "
                "PUT /gcps/{id}/correspondence."
            )

        # Metadata-only. ★ Never sets manually_adjusted (§6.2).
        return await self._gcps.update_metadata(
            gcp.id,
            code=body.code,
            set_code="code" in changed,
            is_included_in_export=body.is_included_in_export,
            adjustment_note=body.adjustment_note,
            set_note="adjustment_note" in changed,
        )

    async def reset(self, gcp_id: uuid.UUID) -> GCP:
        """``POST /gcps/{id}/reset`` (41) — restore the original answer. **Idempotent-safe**.

        Raises:
            GcpNotFound: no such GCP.
            GcpOriginalUnavailable: the GCP was never adjusted, so there is no original to
                return to (409). The repository reports which happened; this layer turns a
                "nothing to undo" into the documented conflict.
        """
        gcp, reverted = await self._gcps.reset(gcp_id)
        if not reverted and not gcp.manually_adjusted:
            raise GcpOriginalUnavailable(
                f"GCP {gcp_id} was never adjusted, so there is no original answer to "
                "restore."
            )
        return gcp

    async def delete(self, gcp: GCP) -> None:
        """``DELETE /gcps/{id}`` — permanently remove a manual GCP.

        A hard delete: ``gcps`` carries no ``deleted_at``, nothing references a GCP as a FK
        child, and the backing landmark annotation is deliberately untouched. The row is the
        surveyor's own observation — removing it is exactly removing that record.
        """
        await self._gcps.delete(gcp)

    async def update_correspondence(self, gcp: GCP, body: GcpCorrespondenceUpdate) -> GCP:
        """``PUT /gcps/{id}/correspondence`` (66) — re-commit the pairing (SCOPE.md §5).

        The surveyor dragged the map endpoint and re-declared their judgement. The new
        click's zoom re-computes the accuracy; the confidence is re-mapped from the
        re-declared 1–5.

        ★ The photo endpoint (``image_px``) is re-committable **only** for a bare-click GCP
        (``landmark_id is null``); a landmark-backed GCP re-commits its photo endpoint
        through ``PATCH /annotations/{id}`` so ``gcps.pixel_x`` never forks from
        ``annotations.pixel_x`` without a revision record (§6.2). Because moving the photo
        pixel is an annotation edit and this build's ``GcpRepository`` exposes no pixel-move
        writer, an ``image_px`` on a bare-click correspondence is refused with that pointer
        rather than silently ignored.

        Raises:
            ValidationError: ``image_px`` sent for a landmark-backed GCP, or for a
                bare-click GCP (see above).
            GcpNotFound: the row vanished.
        """
        if body.image_px is not None:
            if gcp.landmark_id is not None:
                raise ValidationError(
                    "image_px cannot be re-committed here for a landmark-backed GCP: "
                    "moving the point on the photograph is editing the annotation. Use "
                    "PATCH /annotations/{id}."
                )
            raise ValidationError(
                "re-committing image_px is not supported in this build; re-pair the map "
                "endpoint (lat/lon) here, or delete and re-create the GCP with the new "
                "photo pixel."
            )

        provider = self._imagery.resolve(None)
        caps = provider.capabilities()
        accuracy = self._manual_accuracy(
            lat=body.lat, map_zoom=body.map_zoom, tile_size_px=caps.tile_size_px,
            georef_ce90_m=caps.georef_ce90_m,
        )
        return await self._gcps.adjust(
            gcp.id,
            lon=body.lon,
            lat=body.lat,
            adjustment_note=body.note,
            accuracy_relative_ce90_m=accuracy.relative_ce90_m,
            accuracy_total_ce90_m=accuracy.total_ce90_m,
            confidence=self._score_for(body.declared_confidence),
        )

    # ── recompute — DEFERRED (SCOPE.md §4) ────────────────────────────────────

    def recompute(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/gcps/recompute`` (42) — **DEFERRED** (501).

        Both ``refit`` and ``rederive`` need the homography estimator, which is an ABC only
        in this build. The endpoint stays registered and documented; re-enabling costs no
        caller a change (SCOPE.md §7).
        """
        raise FeatureDeferredError(
            "GCP recompute requires the automatic matching engine (homography refit / "
            "re-derivation), which is not enabled in this build. Adjust GCPs manually.",
            component="ai_engine.geometry.homography",
        )

    # ── internals ─────────────────────────────────────────────────────────────

    async def _resolve_photo_endpoint(
        self, image_id: uuid.UUID, body: GcpManualCreate
    ) -> tuple[float, float]:
        """The photo-pixel endpoint, from an annotation's representative point or a click.

        ★ Original image pixel space, independent of viewer zoom/brightness (SCOPE.md §5).
        The schema already guaranteed exactly one of ``landmark_id``/``image_px`` is set.
        """
        if body.landmark_id is not None:
            annotation = await self._annotations.get_active(body.landmark_id)
            if annotation is None or annotation.image_id != image_id:
                raise AnnotationNotFound(
                    f"No annotation {body.landmark_id} on image {image_id} to hang this GCP off."
                )
            return float(annotation.pixel_x), float(annotation.pixel_y)

        assert body.image_px is not None  # schema invariant
        return float(body.image_px.x), float(body.image_px.y)

    def _manual_accuracy(
        self, *, lat: float, map_zoom: int, tile_size_px: int, georef_ce90_m: float
    ) -> AccuracyEstimate:
        """Compute a manual GCP's accuracy from imagery GSD + click precision (SCOPE.md §5).

        ★ A real, defensible number — NOT a match score. The GSD is the *true* ground
        metres per pixel at the map's zoom and latitude (``gis.tiles.resolution_at``), and
        the georeferencing error is the provider's own. There is no homography, so
        ``gis.accuracy.manual_gcp_accuracy`` passes a zero fit covariance.
        """
        try:
            gsd_m = resolution_at(map_zoom, lat, tile_size_px)
            return manual_gcp_accuracy(gsd_m, georef_ce90_m)
        except ValueError as exc:
            raise ValidationError(f"cannot compute accuracy for this click: {exc}") from exc

    def _geotiff_lonlat(self, image: Image, col: float, row: float) -> tuple[float, float]:
        """Exact pixel → (lon, lat) through a georeferenced image's geotransform.

        Call-time import of ``gis.crs`` — it binds pyproj/osr itself, and nothing on the
        manual-map path needs a CRS backend.
        """
        from gis.crs import pixel_to_lonlat

        crs = self._image_crs(image)
        gt = self._image_geotransform(image)
        try:
            return pixel_to_lonlat(gt, crs, col, row)
        except Exception as exc:  # noqa: BLE001 - CrsError/backend absence → an honest 422
            raise ValidationError(
                f"cannot convert pixel ({col}, {row}) to a coordinate: the image's CRS "
                f"{crs!r} could not be resolved ({exc})."
            ) from exc

    def _geotiff_gsd(self, image: Image) -> float:
        """The true-metre GSD for a georeferenced image whose ``gsd_m`` was not stored."""
        from gis.raster import gsd_of

        if not image.storage_path:
            raise ValidationError("the georeferenced image has no readable storage path.")
        gsd = gsd_of(image.storage_path)
        if gsd is None or gsd <= 0.0:
            raise ValidationError(
                "could not determine the georeferenced image's ground sample distance."
            )
        return gsd

    @staticmethod
    def _image_crs(image: Image) -> str:
        """A CRS authority string for a georeferenced image, or a 422."""
        if image.crs_epsg is not None:
            return f"EPSG:{image.crs_epsg}"
        if image.crs_wkt:
            return image.crs_wkt
        raise ValidationError(
            "the image carries no CRS, so its pixels cannot become a coordinate; place "
            "the GCP manually on the map instead."
        )

    @staticmethod
    def _image_geotransform(image: Image):
        """The image's 6-tuple geotransform, or a 422 when it is not georeferenced."""
        gt = image.geotransform
        if not gt or len(gt) != 6:
            raise ValidationError(
                "the image has no usable geotransform; it is not a georeferenced raster."
            )
        return tuple(float(v) for v in gt)

    @staticmethod
    def _score_for(declared: int) -> float:
        """Map the surveyor's 1–5 judgement to the 0–100 ``confidence`` column.

        ★ Never a measurement. The mapping is ``SURVEYOR_CONFIDENCE_TO_SCORE`` (§ the
        schema owns it), reused here so the DB CHECK, the export column and the
        ``?confidence__gte=`` filter keep working while the number stays a human judgement.
        """
        key = int(getattr(declared, "value", declared))
        try:
            return SURVEYOR_CONFIDENCE_TO_SCORE[key]
        except KeyError as exc:
            raise ValidationError(
                f"declared_confidence must be 1–5, got {declared!r}."
            ) from exc
