"""``dem_service`` — orchestrates ``gis.dem`` for the DEM processing page.

★ **A DEM run owns no database row, and that is deliberate.** It is a stateless file
transformation: bytes in, bytes out, plus a report. It belongs to no project, references
no image, and produces no GCP. Giving it a table would mean a migration, a repository and
a lifecycle to maintain, in exchange for nothing the run id in the URL does not already
provide. Artefacts live under ``dem/{run_id}/`` in object storage and are swept on TTL
like exports.

★ **The blocking work runs off the event loop.** ``gis.dem`` is synchronous rasterio/GDAL
and a full-tile reprojection is seconds of CPU, so every call goes through
``anyio.to_thread.run_sync``. ADR-005's rule is that FastAPI never blocks; a thread keeps
that true without inventing a Celery job type and a table for a transformation that has no
state to track. If DEM inputs ever grow to the point where a request timeout is the
constraint, the upgrade path is a queue — and because this service already returns a
report keyed by ``run_id``, that change would not touch the router or the page.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Sequence

from anyio import to_thread

from gis.errors import GisError, RasterBackendUnavailable

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    NotFoundError,
    ProviderToSForbidden,
    ValidationError,
)
from app.schemas.dem import (
    DemAoiCorner,
    DemCameraSummary,
    DemCropSummary,
    DemProcessResponse,
    DemReprojectSummary,
    DemSampledPoint,
    DemSampleRequest,
    DemSampleResponse,
    DemStatistics,
)
from app.storage import keys
from app.storage.base import ObjectStorage

__all__ = ["DemRunNotFound", "DemService"]

_log = logging.getLogger("app.services.dem")

#: Accepted upload extensions. Mirrors the page's dropzone; GDAL reads all of them.
_ACCEPTED_SUFFIXES: frozenset[str] = frozenset(
    {".tif", ".tiff", ".asc", ".dem", ".img", ".hgt", ".xyz", ".vrt", ".bil", ".dt2"}
)

_OUTPUT_FILENAME = "dem_processed.tif"

#: Global terrarium tiles, ``(z, x, y) -> png bytes``. Terrain tiles are immutable and
#: re-requested constantly while tilting/panning; 256 tiles ≈ 15 MB. Same pattern as the
#: video preview cache.
_GLOBAL_TERRAIN_CACHE: "OrderedDict[tuple[int, int, int], bytes]" = OrderedDict()
_GLOBAL_TERRAIN_LOCK = threading.Lock()
_GLOBAL_TERRAIN_MAX = 256

#: AWS Open Data terrain tiles (the former Mapzen tileset): terrarium-encoded heights
#: from SRTM, 3DEP, GMTED2010, ETOPO1 et al. Public, keyless, open licence — but
#: ~30 m source data, so it is a VISUALISATION surface, not a survey one.
_GLOBAL_TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

#: ★ 14, and refusal above it, exactly as the Sentinel provider refuses beyond its
#: native detail: the tileset's deepest real level is 14, and serving an upscaled 15
#: would render invented relief that LOOKS like measurement.
GLOBAL_TERRAIN_MAX_ZOOM = 14

GLOBAL_TERRAIN_ATTRIBUTION = (
    "Terrain: Mapzen/AWS Terrain Tiles — SRTM, 3DEP, GMTED2010, ETOPO1 (NASA/USGS/NOAA)"
)


class DemRunNotFound(NotFoundError):
    """No DEM run with that id — it expired, or was never created."""


class DemService:
    """Run the DEM pipeline and keep its artefacts.

    Args:
        settings: Backend settings (upload size cap).
        storage: Object storage for the source and the processed output.
    """

    def __init__(self, settings: Settings, storage: ObjectStorage) -> None:
        self._settings = settings
        self._storage = storage

    # ── processing ────────────────────────────────────────────────────────────

    async def process(
        self,
        *,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
        filename: str,
        stream: BinaryIO | None,
        source_path: Path | None = None,
        aoi_corners: Sequence[DemAoiCorner] | None,
        camera: tuple[float, float, float] | None,
        tolerance: float,
        reproject: bool,
        target_srid: int | None,
        resampling: str,
        target_resolution_m: float | None,
        set_as_elevation_source: bool = True,
    ) -> DemProcessResponse:
        """Crop and reproject an uploaded DEM, and report what happened.

        Args:
            filename: The upload's original name — used for the extension check and to
                name the source artefact.
            stream: The upload's byte stream, or None when ``source_path`` is given.
            source_path: ★ A file already ON THIS MACHINE (the desktop shell's route):
                it is read in place — never spooled, never copied — so a multi-GB DEM
                costs no extra disk and no HTTP body. Exactly one of
                ``stream``/``source_path``.
            aoi_corners: AOI to crop to, or None to process the whole DEM.
            camera: ``(lon, lat, radius_m)`` of the camera station. ★ When given it
                defines the AOI (a disc around the camera) AND fixes the UTM zone, so
                ``target_srid`` is not needed and a hand-typed zone cannot be wrong.
            tolerance: Padding fraction around the AOI.
            reproject: Whether to run the metric reprojection stage.
            target_srid: Explicit EPSG code, or None to auto-pick the UTM zone.
            resampling: Resampling kernel.
            target_resolution_m: Output cell size in metres, or None to preserve source.
            set_as_elevation_source: Adopt this run's output as the DEM that new GCPs
                sample their elevation from. ★ Default True — the DEM a surveyor just
                prepared is the one they mean to measure against.

        Returns:
            The :class:`DemProcessResponse`.

        Raises:
            ValidationError: Bad extension, unreadable raster, or any ``gis.dem``
                validation failure (no CRS, AOI off the tile, non-metric target…).
            ConfigurationError: rasterio is not installed on this deployment.
        """
        suffix = Path(filename).suffix.lower()
        if suffix not in _ACCEPTED_SUFFIXES:
            raise ValidationError(
                f"{filename!r} is not a DEM this build reads. Accepted: "
                f"{', '.join(sorted(_ACCEPTED_SUFFIXES))}."
            )

        run_id = uuid.uuid4()
        work_dir = Path(tempfile.mkdtemp(prefix=f"dem-{run_id}-"))
        try:
            if source_path is not None:
                # ★ LOCAL-PATH MODE: read the raster where it lies. The pipeline only
                #   READS the source (outputs land in work_dir), so nothing needs the
                #   copy — which for a 3.8 GB tile is the whole point.
                source = source_path
                written = source_path.stat().st_size
                limit = int(getattr(self._settings, "upload_max_bytes", 0) or 0)
                if limit and written > limit:
                    raise ValidationError(
                        f"the DEM exceeds the {limit / (1024 * 1024):.0f} MB upload limit."
                    )
                if written == 0:
                    raise ValidationError("the DEM file is empty.")
                _log.info("DEM run %s: local file %s (%d bytes)", run_id, source, written)
            else:
                assert stream is not None
                source = work_dir / f"source{suffix}"
                written = self._spool(stream, source)
                _log.info("DEM run %s: received %s (%d bytes)", run_id, filename, written)

            # ★ A GEOGRAPHIC DEM CAN NEVER BE A PROJECT'S "ALREADY PREPARED" SURFACE.
            #   The project path defaults to reproject=False because the file is meant
            #   to be preprocessed — but a raster in degrees breaks the auto-GCP
            #   raycast (a march step of one cell would be one DEGREE-scale hop) and
            #   its cell size is meaningless in metres. Adopting one as-is stranded a
            #   real project; the reprojection stage now switches itself on instead,
            #   with a warning that says so.
            forced_reproject_note: str | None = None
            if set_as_elevation_source and project_id is not None and not reproject:
                src_crs = self._source_crs(source)
                if src_crs is not None:
                    from gis.crs import is_ground_metric_crs

                    if not is_ground_metric_crs(src_crs):
                        reproject = True
                        forced_reproject_note = (
                            f"The uploaded DEM is in a geographic CRS ({src_crs}), which "
                            "cannot serve raycasts — it was reprojected to a metric UTM "
                            "zone automatically."
                        )

            camera_summary: DemCameraSummary | None = None
            if camera is not None:
                cam_lon, cam_lat, radius_m = camera
                corners, camera_summary = self._camera_aoi(cam_lon, cam_lat, radius_m)
                # ★ The camera's own zone wins over an explicitly requested one: the whole
                #   point of capturing the station is that the zone follows from it.
                target_srid = int(camera_summary.utm_epsg.split(":")[1])
            else:
                corners = (
                    [{"lon": c.lon, "lat": c.lat} for c in aoi_corners] if aoi_corners else None
                )
            report = await to_thread.run_sync(
                lambda: self._run_pipeline(
                    source=source,
                    work_dir=work_dir,
                    corners=corners,
                    tolerance=tolerance,
                    reproject=reproject,
                    target_srid=target_srid,
                    resampling=resampling,
                    target_resolution_m=target_resolution_m,
                )
            )

            output = Path(report.output_path)
            output_bytes = output.stat().st_size

            # Persist the source too: re-running with a different tolerance or CRS should
            # not mean re-uploading a large file over a field connection.
            # ★ EXCEPT in local-path mode: the "source artefact" already lives on this
            #   machine at source_path, and duplicating a multi-GB tile into storage
            #   would cost the disk the path route exists to save.
            if source_path is None:
                with source.open("rb") as fh:
                    self._storage.put(
                        keys.dem_source_key(run_id, filename), fh, content_type="image/tiff"
                    )
            with output.open("rb") as fh:
                self._storage.put(
                    keys.dem_output_key(run_id, _OUTPUT_FILENAME),
                    fh,
                    content_type="image/tiff",
                )

            warnings = list(report.warnings)
            if forced_reproject_note:
                warnings.append(forced_reproject_note)
            adopted = False
            if set_as_elevation_source:
                adopted, adoption_note = self._adopt_as_elevation_source(
                    output, run_id=run_id, filename=filename, report=report,
                    project_id=project_id, image_id=image_id,
                )
                if adoption_note:
                    warnings.append(adoption_note)

            self._export_to_library(output, filename=filename, report=report)

            return DemProcessResponse(
                run_id=str(run_id),
                camera=camera_summary,
                source_name=filename,
                source_crs=report.source_crs,
                output_crs=report.output_crs,
                output_size=report.output_size,
                output_pixel_size_m=report.output_pixel_size_m,
                output_bytes=output_bytes,
                crop=_crop_summary(report.crop),
                reproject=_reproject_summary(report.reproject),
                statistics=DemStatistics(**report.statistics),
                aoi_geojson=report.aoi_geojson,
                warnings=warnings,
                download_url=f"/api/v1/dem/{run_id}/download",
                is_elevation_source=adopted,
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _camera_aoi(
        self, lon: float, lat: float, radius_m: float
    ) -> tuple[list[dict[str, Any]], DemCameraSummary]:
        """Build the AOI and resolve the UTM zone from a camera station.

        ★ The zone is DERIVED from the position, through ``gis.crs.utm_epsg_for``, which
        clamps to zone 60 and rejects ``|lat| > 84``. That is the reason to capture the
        camera at all: it is the one input that cannot disagree with itself.
        """
        from gis.dem import corners_from_camera, utm_zone_for_camera

        try:
            corners = corners_from_camera(lon, lat, radius_m)
            epsg = utm_zone_for_camera(lon, lat)
        except GisError as exc:
            raise ValidationError(f"the camera position is unusable: {exc}") from exc

        return (
            [{"lon": c.lon, "lat": c.lat} for c in corners],
            DemCameraSummary(lat=lat, lon=lon, radius_m=radius_m, utm_epsg=epsg),
        )

    # ── adoption — this DEM becomes the GCP elevation source ──────────────────

    def project_dem_path(self, project_id: uuid.UUID) -> Path:
        """Where a project's own DEM lives. One file per project, named by its id."""
        return Path(self._settings.project_dem_dir) / f"{project_id}.tif"

    def image_dem_path(self, project_id: uuid.UUID, image_id: uuid.UUID) -> Path:
        """Where ONE image's own DEM lives — its per-image override of the project DEM.

        ★ A survey can span terrain that no single DEM tile covers well, so a photograph
        may need a DEM the rest of the project does not use. This is that file. Named
        ``{project}__{image}.tif`` beside the project DEM; absent ⇒ the image simply uses
        the project DEM (:meth:`elevation_dem_path`).
        """
        return Path(self._settings.project_dem_dir) / f"{project_id}__{image_id}.tif"

    def elevation_dem_path(
        self, project_id: uuid.UUID, image_id: uuid.UUID | None = None
    ) -> Path:
        """The DEM that answers for THIS image: its own if it has one, else the project's.

        ★ THE ONE RESOLUTION RULE, in one place. Every consumer that needs "the surface
        under this photograph" — the auto-GCP raycast, a GCP's Z — calls this, so the
        image-overrides-project precedence can never disagree between them. Returns a
        path that may not exist (the caller checks); with no ``image_id`` it is exactly
        the project DEM path.
        """
        if image_id is not None:
            own = self.image_dem_path(project_id, image_id)
            if own.is_file():
                return own
        return self.project_dem_path(project_id)

    def image_elevation_dem(
        self, project_id: uuid.UUID, image_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Describe an image's OWN DEM, or None when it has none (it uses the project's)."""
        target = self.image_dem_path(project_id, image_id)
        if not target.is_file():
            return None
        record: dict[str, Any] = {
            "path": str(target),
            "project_id": str(project_id),
            "image_id": str(image_id),
            "provider_enabled": True,
            "vertical_ce90_m": self._settings.active_dem_ce90_m,
        }
        sidecar = target.with_suffix(".json")
        if sidecar.is_file():
            try:
                record.update(json.loads(sidecar.read_text()))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("image DEM sidecar %s unreadable: %s", sidecar, exc)
        record["provider_enabled"] = True
        record["project_id"] = str(project_id)
        record["image_id"] = str(image_id)
        return record

    def delete_image_dem(self, project_id: uuid.UUID, image_id: uuid.UUID) -> bool:
        """Remove an image's own DEM — it reverts to using the project DEM.

        ★ Like :meth:`delete_project_dem`, elevations already recorded on this image's
        GCPs are untouched: they are observations of what the DEM said when placed.
        """
        target = self.image_dem_path(project_id, image_id)
        if not target.is_file():
            return False
        target.unlink(missing_ok=True)
        target.with_suffix(".json").unlink(missing_ok=True)
        _log.info("image %s DEM removed; it now uses the project DEM", image_id)
        return True

    async def terrain_tile(
        self, project_id: uuid.UUID, z: int, x: int, y: int
    ) -> bytes | None:
        """One Terrarium-encoded terrain tile from this project's DEM, or None.

        ★ **None means 404, and 404 means "no terrain here"** — the renderer draws flat
        ground. The alternative, an all-zero tile, would carpet the world in a fabricated
        sea-level surface indistinguishable from real data.

        ★ **THE TILE IS FOR RENDERING ONLY.** It is resampled and quantised to 1/256 m,
        and voids inside a partly-covered tile encode as 0 m so the mesh does not tear.
        A GCP's elevation never comes from here — it comes from
        ``ElevationService.sample``, which returns null where there is no data and carries
        a vertical CE90. ``gis.dem.terrain``'s module docstring is the long version.

        ★ Off the event loop: a tile is a windowed raster read plus a PNG encode, both
        blocking and both CPU-bound. Running them inline would stall every other request
        on this worker while a 3D view drags a few dozen tiles across the network.
        """
        target = self.project_dem_path(project_id)

        from gis.dem.terrain import terrain_tile_png

        def _render() -> bytes | None:
            # ★ The global terrarium tile plays two roles: it FILLS the pixels a
            #   partly-covered tile lacks (no more kilometre-high cliff wall at the
            #   DEM's edge), and it IS the answer where the project DEM has nothing at
            #   all — so the whole world has relief, with the survey DEM seamlessly on
            #   top wherever it exists. Offline (or AWS unreachable) degrades exactly
            #   as before: floor-fill inside, 404/flat outside. Never fatal.
            fallback: bytes | None = None
            if z <= GLOBAL_TERRAIN_MAX_ZOOM and not self._settings.imagery_offline:
                try:
                    fallback = self.global_terrain_tile(z, x, y)
                except Exception as exc:  # noqa: BLE001 - a fallback failing is not an error
                    _log.debug("global terrain fallback %s/%s/%s unavailable: %s", z, x, y, exc)

            if not target.is_file():
                return fallback  # no project DEM: global relief, or None -> 404 -> flat

            try:
                return terrain_tile_png(target, z, x, y, fallback_png=fallback) or fallback
            except GisError as exc:
                # A CRS the backend cannot transform, or a singular geotransform. The 3D
                # view degrades to the global surface (or flat); never takes the request down.
                _log.warning(
                    "terrain tile %s/%s/%s for project %s failed: %s", z, x, y, project_id, exc
                )
                return fallback

        return await to_thread.run_sync(_render)

    def project_elevation_dem(self, project_id: uuid.UUID) -> dict[str, Any] | None:
        """Describe a project's own DEM, or None when it has none."""
        target = self.project_dem_path(project_id)
        if not target.is_file():
            return None
        record: dict[str, Any] = {
            "path": str(target),
            "project_id": str(project_id),
            "provider_enabled": True,  # a project DEM needs no server-wide switch
            "vertical_ce90_m": self._settings.active_dem_ce90_m,
        }
        sidecar = target.with_suffix(".json")
        if sidecar.is_file():
            try:
                record.update(json.loads(sidecar.read_text()))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("project DEM sidecar %s unreadable: %s", sidecar, exc)
        record["provider_enabled"] = True
        record["project_id"] = str(project_id)
        return record

    def delete_project_dem(self, project_id: uuid.UUID) -> bool:
        """Remove a project's DEM.

        ★ Does NOT touch elevations already recorded on that project's GCPs — those are
        observations of what the DEM said when each point was placed. Nulling a column of
        survey heights because a file was removed would be far the worse failure.
        """
        target = self.project_dem_path(project_id)
        if not target.is_file():
            return False
        target.unlink(missing_ok=True)
        target.with_suffix(".json").unlink(missing_ok=True)
        _log.info("project %s DEM removed; recorded elevations unchanged", project_id)
        return True

    def _export_to_library(self, output: Path, *, filename: str, report) -> None:
        """Drop the processed GeoTIFF into the surveyor's DEM library, best-effort.

        ★ THE LIBRARY IS THE POINT OF PROCESSING TWICE-USED TERRAIN ONCE: the same
        cropped, metre-projected tile serves every project on the same site. A
        `.json` sidecar carries what the picker shows (CRS, cell size, source) so
        listing the folder never has to open rasters.

        ★ Best-effort like the capture export: the run's own artefacts and any
        project adoption are already safe; a full disk here must not fail the run.
        """
        library = getattr(self._settings, "dem_library_dir", None)
        if not library:
            return
        try:
            root = Path(library).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            stem = Path(filename).stem or "dem"
            crs_tag = (report.output_crs or "unknown").replace(":", "")
            target = root / f"{stem}_{crs_tag}.tif"
            counter = 2
            while target.exists():
                target = root / f"{stem}_{crs_tag}-{counter}.tif"
                counter += 1
            shutil.copyfile(output, target)
            sidecar = {
                "source_name": filename,
                "output_crs": report.output_crs,
                "output_pixel_size_m": report.output_pixel_size_m,
                "output_size": report.output_size,
            }
            target.with_suffix(".tif.json").write_text(json.dumps(sidecar))
            _log.info("DEM library: exported %s", target)
        except OSError:
            _log.warning("could not export processed DEM to the library", exc_info=True)

    def _adopt_as_elevation_source(
        self,
        output: Path,
        *,
        run_id: uuid.UUID,
        filename: str,
        report: Any,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
    ) -> tuple[bool, str | None]:
        """Install ``output`` as the active DEM that ``gis.elevation.dem_run`` samples.

        ★ **The surface the surveyor prepared becomes the surface their control points are
        measured against.** Every GCP created after this call samples THIS raster, so the
        adoption is recorded with its provenance — a height in a survey deliverable must
        be traceable to the DEM it came from, and "some DEM, once" is not traceable.

        ★ **Written atomically**, via a temp file and ``os.replace``. A GCP created while a
        half-copied GeoTIFF sat at the active path would sample a truncated raster and
        record whatever fell out — the failure mode ``ObjectStorage.put`` guards against
        for the same reason.

        Returns:
            ``(adopted, warning_or_None)``. Adoption failure is never fatal: the run
            succeeded and is downloadable regardless, so a filesystem problem here
            degrades to a warning rather than discarding the work.
        """
        # ★ image DEM > project DEM > server-wide. An image_id (with its project)
        #   adopts for that ONE photograph; a project_id alone adopts for the project.
        if project_id is not None and image_id is not None:
            target = self.image_dem_path(project_id, image_id)
        elif project_id is not None:
            target = self.project_dem_path(project_id)
        else:
            target = Path(self._settings.active_dem_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_suffix(f".{run_id.hex[:8]}.staging")
            shutil.copyfile(output, staged)
            staged.replace(target)

            sidecar = {
                "run_id": str(run_id),
                "project_id": str(project_id) if project_id else None,
                "image_id": str(image_id) if image_id else None,
                "source_name": filename,
                "adopted_at": datetime.now(tz=timezone.utc).isoformat(),
                "output_crs": report.output_crs,
                "output_size": list(report.output_size),
                "output_pixel_size_m": (
                    list(report.output_pixel_size_m) if report.output_pixel_size_m else None
                ),
                "statistics": report.statistics,
                "vertical_ce90_m": self._settings.active_dem_ce90_m,
                # ★ Recorded as UNKNOWN, and deliberately not guessed. Copernicus and
                #   FABDEM are orthometric (EGM2008); a GNSS/EXIF altitude is ellipsoidal,
                #   and the two differ by ~20 m across Lebanon. Naming a datum we cannot
                #   verify would be worse than admitting we do not know it.
                "vertical_datum": "unknown",
            }
            target.with_suffix(".json").write_text(json.dumps(sidecar, indent=2))
            _log.info(
                "DEM run %s adopted as the GCP elevation source at %s (%s, %s m/px)",
                run_id, target, report.output_crs,
                f"{report.output_pixel_size_m[0]:.3f}" if report.output_pixel_size_m else "n/a",
            )
        except OSError as exc:
            _log.warning("could not adopt DEM run %s as the elevation source: %s", run_id, exc)
            return (
                False,
                f"The DEM was processed but could not be installed as the elevation "
                f"source ({exc}). Existing GCP elevations are unaffected.",
            )

        note: str | None = None
        if project_id is not None:
            # ★ Adoptions that feed GCPs: per-image (this photo only) or per-project.
            if report.statistics.get("valid_cells", 0) == 0:
                scope = "this image" if image_id is not None else "this project"
                note = (
                    f"This DEM has no valid elevation cells, so GCPs in {scope} will "
                    "record a null elevation."
                )
            return (True, note)
        # Global adoption is informational only (GET /dem/active): under strict
        # per-project opt-in no project samples it, and the note says so rather than
        # implying a Z source was configured.
        note = (
            "Recorded as the server-wide active DEM for reference. Projects choose their "
            "elevation source individually in the workspace setup; this run feeds no "
            "project until adopted there."
        )
        return (True, note)

    def global_terrain_tile(self, z: int, x: int, y: int) -> bytes:
        """Proxy one AWS terrarium tile — the 3D pane's fallback when a project has no DEM.

        ★ PROXIED, NOT FETCHED BY THE BROWSER, for the same reason every imagery source
        is: the 3D pane's style contract says its only sources are our own endpoints, so
        it cannot silently become a third-party fetch — and the offline promise stays
        enforceable in ONE place (below) instead of in a browser we do not control.

        Raises:
            ValidationError: z beyond the tileset's real detail, or x/y out of range.
            ProviderToSForbidden: LE_IMAGERY_OFFLINE is set — same refusal as Esri tiles.
            DemRunNotFound: the tile does not exist upstream (ocean at deep zooms).
        """
        if not (0 <= z <= GLOBAL_TERRAIN_MAX_ZOOM):
            raise ValidationError(
                f"global terrain serves z0-{GLOBAL_TERRAIN_MAX_ZOOM}; z{z} would be "
                "upsampled invention, not measured relief."
            )
        n = 1 << z
        if not (0 <= x < n and 0 <= y < n):
            raise ValidationError(f"tile {x}/{y} is outside the z{z} grid (0..{n - 1}).")
        if self._settings.imagery_offline:
            # ★ The offline mode's promise is "never touches the network", and a terrain
            #   fetch is a network fetch. Same error shape as the imagery providers.
            raise ProviderToSForbidden(
                "LE_IMAGERY_OFFLINE=true: global terrain tiles are a network source and "
                "are refused in offline mode. Attach a project DEM for offline terrain."
            )

        key = (z, x, y)
        with _GLOBAL_TERRAIN_LOCK:
            cached = _GLOBAL_TERRAIN_CACHE.get(key)
            if cached is not None:
                _GLOBAL_TERRAIN_CACHE.move_to_end(key)
                return cached

        import httpx

        try:
            resp = httpx.get(
                _GLOBAL_TERRAIN_URL.format(z=z, x=x, y=y),
                timeout=15.0,
                headers={"User-Agent": "LandExplorer/1.0"},
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise DemRunNotFound(f"global terrain tile {z}/{x}/{y} unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise DemRunNotFound(
                f"global terrain tile {z}/{x}/{y} not available upstream "
                f"(HTTP {resp.status_code})."
            )

        data = resp.content
        with _GLOBAL_TERRAIN_LOCK:
            _GLOBAL_TERRAIN_CACHE[key] = data
            _GLOBAL_TERRAIN_CACHE.move_to_end(key)
            while len(_GLOBAL_TERRAIN_CACHE) > _GLOBAL_TERRAIN_MAX:
                _GLOBAL_TERRAIN_CACHE.popitem(last=False)
        return data

    def active_elevation_dem(self) -> dict[str, Any] | None:
        """Describe the DEM currently feeding GCP elevations, or None if there is none.

        Reads the sidecar written by :meth:`_adopt_as_elevation_source`. A DEM present
        without its sidecar (hand-placed by an operator) still reports, with provenance
        marked unknown rather than fabricated.
        """
        target = Path(self._settings.active_dem_path)
        if not target.is_file():
            return None
        record: dict[str, Any] = {
            "path": str(target),
            "provider_enabled": self._settings.elevation_provider == "dem_run",
            "vertical_ce90_m": self._settings.active_dem_ce90_m,
        }
        sidecar = target.with_suffix(".json")
        if sidecar.is_file():
            try:
                record.update(json.loads(sidecar.read_text()))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("active DEM sidecar %s is unreadable: %s", sidecar, exc)
                record["provenance"] = "unreadable"
        else:
            record["provenance"] = "unknown (no sidecar; placed outside the DEM page)"
        return record

    @staticmethod
    def _source_crs(path: Path) -> str | None:
        """The raster's CRS string, or None when unreadable.

        ★ Best-effort ONLY — a truncated or CRS-less file returns None here and gets
        its real, named error from the pipeline moments later; this probe must never
        pre-empt that with a vaguer one.
        """
        try:
            import rasterio

            with rasterio.open(path) as ds:
                return str(ds.crs) if ds.crs is not None else None
        except (ImportError, OSError, ValueError):
            return None

    def _run_pipeline(
        self,
        *,
        source: Path,
        work_dir: Path,
        corners: list[dict[str, Any]] | None,
        tolerance: float,
        reproject: bool,
        target_srid: int | None,
        resampling: str,
        target_resolution_m: float | None,
    ) -> Any:
        """The synchronous body, run in a worker thread.

        ``gis`` errors are translated here rather than in the router: ``GisError`` is not a
        ``LandExplorerError``, so an untranslated one would escape the envelope handlers
        and surface as a bare 500 with no ``error_code``.
        """
        from gis.dem import process_dem

        try:
            return process_dem(
                source,
                work_dir,
                aoi_corners=corners,
                tolerance=tolerance,
                reproject=reproject,
                target_crs=f"EPSG:{target_srid}" if target_srid else None,
                resampling=resampling,
                target_resolution_m=target_resolution_m,
                output_stem="dem_processed",
            )
        except RasterBackendUnavailable as exc:
            raise ConfigurationError(
                f"DEM processing is unavailable on this deployment: {exc}"
            ) from exc
        except GisError as exc:
            raise ValidationError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            # A corrupt or truncated upload surfaces from GDAL as an OSError/ValueError.
            raise ValidationError(
                f"the DEM could not be read: {exc}. The file may be truncated, or not a "
                "raster this build supports."
            ) from exc

    # ── sampling — stage 3 ────────────────────────────────────────────────────

    async def sample(self, run_id: str, body: DemSampleRequest) -> DemSampleResponse:
        """Sample elevations from a processed DEM at the given points.

        Raises:
            DemRunNotFound: No such run.
            ValidationError: Unreadable coordinates or an unusable output CRS.
        """
        key = self._output_key(run_id)
        names = body.names or [f"P{i}" for i in range(1, len(body.points) + 1)]

        def _work() -> tuple[list[Any], str, str]:
            from gis.dem import sample_points
            from gis.dem.aoi import parse_dms_string

            with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
                local = Path(tmp.name)
            try:
                with self._storage.open(key) as fh:
                    local.write_bytes(fh.read())
                try:
                    points = [
                        (name, parse_dms_string(p.lon), parse_dms_string(p.lat))
                        for name, p in zip(names, body.points, strict=True)
                    ]
                except GisError as exc:
                    raise ValidationError(str(exc)) from exc
                try:
                    return sample_points(
                        local,
                        points,
                        output_crs=body.output_crs,
                        method=body.method,
                        offset_m=body.offset_m,
                    )
                except RasterBackendUnavailable as exc:
                    raise ConfigurationError(str(exc)) from exc
                except GisError as exc:
                    raise ValidationError(str(exc)) from exc
            finally:
                local.unlink(missing_ok=True)

        samples, dem_crs, out_crs = await to_thread.run_sync(_work)
        rows = [
            DemSampledPoint(
                name=s.name, lat=s.lat, lon=s.lon, x=s.x, y=s.y, dem_z_m=s.dem_z_m,
                offset_m=s.offset_m, z_m=s.z_m, inside_dem=s.inside_dem,
                suspicious=s.suspicious,
            )
            for s in samples
        ]
        return DemSampleResponse(
            run_id=run_id,
            dem_crs=dem_crs,
            output_crs=out_crs,
            method=body.method,
            offset_m=body.offset_m,
            points=rows,
            inside_count=sum(1 for r in rows if r.inside_dem),
            with_elevation_count=sum(1 for r in rows if r.z_m is not None),
        )

    # ── download ──────────────────────────────────────────────────────────────

    def open_output(self, run_id: str) -> tuple[bytes, str]:
        """Return the processed GeoTIFF's bytes and its download filename.

        Raises:
            DemRunNotFound: No such run, or its artefacts have been swept.
        """
        key = self._output_key(run_id)
        return (self._storage.get(key), _OUTPUT_FILENAME)

    def _output_key(self, run_id: str) -> str:
        """Validate the run id and return its output key.

        ★ The id is parsed as a UUID before it reaches the key builder. A run id is the
        only handle to a run, so it is also the only thing an attacker can vary — and a
        key built from unvalidated input is how ``../`` reaches the storage root.
        """
        try:
            parsed = uuid.UUID(str(run_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise DemRunNotFound(f"{run_id!r} is not a DEM run id.") from exc

        key = keys.dem_output_key(parsed, _OUTPUT_FILENAME)
        if not self._storage.exists(key):
            raise DemRunNotFound(
                f"DEM run {parsed} has no processed output. It may have expired, or "
                "processing never completed."
            )
        return key

    # ── internals ─────────────────────────────────────────────────────────────

    def _spool(self, stream: BinaryIO, destination: Path) -> int:
        """Write the upload to disk in chunks, enforcing the size cap as it goes.

        ★ Streamed, never read whole: ``LE_UPLOAD_MAX_BYTES`` defaults to 4 GB — a
        real DEM tile is routinely hundreds of megabytes and the old 500 MB ceiling
        refused them. The cap is enforced DURING the copy so an oversized upload is
        refused after one chunk over the limit, not after it has all landed, and the
        1 MB chunking means the ceiling costs disk rather than RAM.
        """
        limit = int(getattr(self._settings, "upload_max_bytes", 0) or 0)
        written = 0
        with destination.open("wb") as out:
            while chunk := stream.read(1024 * 1024):
                written += len(chunk)
                if limit and written > limit:
                    raise ValidationError(
                        f"the DEM exceeds the {limit / (1024 * 1024):.0f} MB upload limit."
                    )
                out.write(chunk)
        if written == 0:
            raise ValidationError("the uploaded DEM is empty.")
        return written


def _crop_summary(report: Any) -> DemCropSummary | None:
    if report is None:
        return None
    return DemCropSummary(
        source_crs=report.source_crs,
        tolerance=report.tolerance,
        output_size=report.output_size,
        pixel_size=report.pixel_size,
        clipped=report.clipped,
        aoi_corners_lonlat=report.aoi_corners_lonlat,
    )


def _reproject_summary(report: Any) -> DemReprojectSummary | None:
    if report is None:
        return None
    return DemReprojectSummary(
        source_crs=report.source_crs,
        target_crs=report.target_crs,
        resampling=report.resampling,
        auto_utm=report.auto_utm,
        source_pixel_size=report.source_pixel_size,
        output_pixel_size_m=report.output_pixel_size_m,
        output_size=report.output_size,
        output_bounds_m=report.output_bounds_m,
    )
