"""``ingest_image_task`` — the REAL heavy half of an upload (SCOPE.md §3).

``image_service`` does the synchronous half (validate, hash, store, create the row) and
enqueues this. Here, off the request path (L5), we do the expensive part:

* decode the file and record its true dimensions, band count and sniffed MIME;
* extract EXIF — camera make/model/focal length and, critically, the GPS fix — via
  ``gis.exif`` (a prior for a manual placement, never an automatic coordinate);
* detect georeferencing via ``gis.raster``: a GeoTIFF's CRS, geotransform, bounds and GSD,
  which is what arms the exact GeoTIFF short-circuit (SCOPE.md §3, §5);
* render a thumbnail and, for large rasters, downscaled overviews;
* flip the image ``pending → ready`` (or ``failed``) and mark the job ``succeeded``.

★ **Sniffed, never trusted.** ``image_service`` used the client's declared MIME only as an
early reject; the authoritative type is decided here from the bytes.

★ **Domain reads go through the async repository** (the single home of ``select()``) via
the :func:`~app.tasks.base.run_async` bridge; the metadata *write* is a targeted Core
``UPDATE`` on the worker's sync session (there is no repository method for the full
ingest-metadata write, and a targeted UPDATE is exactly what ``ImageRepository.set_status``
already is). The heavy decoders (PIL / GDAL via ``gis``) are imported **inside** the
functions that use them (§11.3): importing this module must never require them.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any

from celery import shared_task
from sqlalchemy import func, update

from app.core.constants import JobStage
from app.core.logging import get_logger
from app.db.session import get_sessionmaker, sync_session
from app.models.enums import ImageStatus, JobType
from app.models.image import Image
from app.storage import get_storage, keys
from app.tasks.base import BaseJobTask, job_lifecycle
from app.tasks.celery_app import TASK_INGEST

__all__ = ["ingest_image_task"]

log = get_logger(__name__)

#: Longest edge of the generated thumbnail, pixels.
_THUMBNAIL_MAX_PX = 512


@dataclass(slots=True)
class _ImageRef:
    """The scalar fields the task needs off the (session-bound) image row."""

    storage_path: str
    filename: str
    project_id: uuid.UUID


@shared_task(bind=True, base=BaseJobTask, name=TASK_INGEST)
def ingest_image_task(self: Any, job_id: str, image_id: str) -> None:
    """Decode, extract metadata, thumbnail and finalise one uploaded image.

    Args:
        job_id: The ``aux_jobs`` (ingest) row id.
        image_id: The image to ingest.
    """
    with job_lifecycle(self, JobType.INGEST, job_id) as ctx:
        img_uuid = uuid.UUID(str(image_id))

        ctx.progress.set_stage(JobStage.DECODING)
        ref = run_load_image(img_uuid)
        if ref is None:
            # The image row vanished between upload and ingest (hard delete). Nothing to
            # ingest; the job simply succeeds with no work rather than failing loudly.
            log.warning("ingest.image_missing", image_id=str(img_uuid))
            return

        storage = get_storage()
        with _download_to_temp(storage, ref.storage_path) as temp_path:
            meta = _decode_metadata(temp_path)
            ctx.progress.advance(0.6)

            geo = _detect_georeferencing(temp_path)
            exif = _extract_exif(temp_path)

            ctx.progress.set_stage(JobStage.THUMBNAILING)
            thumbnail_path = _make_thumbnail(storage, ref.project_id, img_uuid, temp_path, meta)

        ctx.progress.set_stage(JobStage.PERSISTING)
        _write_metadata(
            img_uuid,
            meta=meta,
            geo=geo,
            exif=exif,
            thumbnail_path=thumbnail_path,
        )
        ctx.set_result()  # ingest has no extra success columns; status was set above
        log.info(
            "ingest.done",
            image_id=str(img_uuid),
            width=meta.width,
            height=meta.height,
            is_geotiff=geo.is_geotiff,
        )


# ── domain read (async bridge) ────────────────────────────────────────────────


def run_load_image(image_id: uuid.UUID) -> _ImageRef | None:
    """Load the scalar fields off the image row, through the async repository."""
    from app.db.repositories.images import ImageRepository
    from app.tasks.base import run_async

    async def _load() -> _ImageRef | None:
        factory = get_sessionmaker()
        async with factory() as session:
            image = await ImageRepository(session).get_active(image_id)
            if image is None:
                return None
            return _ImageRef(
                storage_path=image.storage_path,
                filename=image.filename,
                project_id=image.project_id,
            )

    return run_async(_load)


# ── decode / metadata ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class _DecodedMeta:
    width: int
    height: int
    band_count: int
    mime_type: str
    resolution_dpi: float | None
    camera: dict[str, Any]
    has_alpha: bool


@dataclass(slots=True)
class _GeoMeta:
    is_geotiff: bool
    crs_epsg: int | None
    crs_wkt: str | None
    geotransform: list[float] | None
    gsd_m: float | None
    bounds_wkt: str | None
    nodata_value: float | None


@dataclass(slots=True)
class _ExifMeta:
    point_wkt: str | None
    altitude_m: float | None
    hpe_m: float | None
    captured_at: Any
    raw: dict[str, Any]


_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
}

_BANDS_BY_MODE = {"1": 1, "L": 1, "LA": 2, "P": 1, "RGB": 3, "RGBA": 4, "CMYK": 4, "I": 1, "F": 1}


def _decode_metadata(path: str) -> _DecodedMeta:
    """True dimensions, band count and sniffed MIME, plus camera EXIF tags."""
    from PIL import Image as PILImage
    from PIL import ImageFile

    # A truncated upload should fail cleanly here, not decode into garbage. And a huge but
    # legitimate raster must not trip the decompression-bomb guard.
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    PILImage.MAX_IMAGE_PIXELS = None

    with PILImage.open(path) as im:
        width, height = im.size
        mode = im.mode
        fmt = (im.format or "").upper()
        dpi = im.info.get("dpi")
        resolution_dpi = float(dpi[0]) if isinstance(dpi, (tuple, list)) and dpi else None
        camera = _camera_tags(im)

    mime = _MIME_BY_FORMAT.get(fmt, "application/octet-stream")
    band_count = _BANDS_BY_MODE.get(mode, 3)
    return _DecodedMeta(
        width=int(width),
        height=int(height),
        band_count=int(band_count),
        mime_type=mime,
        resolution_dpi=resolution_dpi,
        camera=camera,
        has_alpha=mode in ("RGBA", "LA", "PA"),
    )


def _camera_tags(im: Any) -> dict[str, Any]:
    """Camera/lens EXIF tags as a plain, JSON-safe dict. Best-effort — a photo with no EXIF
    just yields an empty dict."""
    try:
        exif = im.getexif()
    except Exception:  # noqa: BLE001 — EXIF is optional metadata, never fatal to ingest
        return {}
    if not exif:
        return {}
    # Numeric EXIF tag ids for the fields the Image model carries.
    wanted = {
        0x010F: "camera_make",
        0x0110: "camera_model",
        0xA434: "lens_model",
        0x920A: "focal_length_mm",
        0xA405: "focal_length_35mm",
        0x829D: "f_number",
    }
    out: dict[str, Any] = {}
    for tag_id, name in wanted.items():
        if tag_id not in exif:
            continue
        value = exif.get(tag_id)
        out[name] = _exif_scalar(value)
    return {k: v for k, v in out.items() if v is not None}


def _exif_scalar(value: Any) -> Any:
    """Coerce an EXIF value (possibly a PIL rational) to a JSON-safe scalar."""
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            return float(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace").strip("\x00").strip() or None
        if isinstance(value, str):
            return value.strip("\x00").strip() or None
        if isinstance(value, (int, float)):
            return value
    except Exception:  # noqa: BLE001
        return None
    return None


def _detect_georeferencing(path: str) -> _GeoMeta:
    """GeoTIFF CRS / geotransform / bounds / GSD, via ``gis.raster``. Never raises."""
    from gis.raster import bounds_of, detect_georeferencing, gsd_of

    report = detect_georeferencing(path)
    if not report.is_georeferenced:
        return _GeoMeta(False, None, None, None, None, None, None)

    crs_epsg, crs_wkt = _split_crs(report.crs)
    geotransform = [float(v) for v in report.geotransform] if report.geotransform else None

    gsd_m: float | None = None
    try:
        gsd_m = gsd_of(path)
    except Exception:  # noqa: BLE001 — a missing GSD is not an ingest failure
        gsd_m = None

    bounds_wkt: str | None = None
    try:
        bbox, _crs = bounds_of(path)
        bounds_wkt = _bbox_polygon_wkt(bbox) if bbox is not None else None
    except Exception:  # noqa: BLE001
        bounds_wkt = None

    return _GeoMeta(
        is_geotiff=True,
        crs_epsg=crs_epsg,
        crs_wkt=crs_wkt if crs_epsg is None else None,
        geotransform=geotransform,
        gsd_m=float(gsd_m) if gsd_m and gsd_m > 0 else None,
        bounds_wkt=bounds_wkt,
        nodata_value=None,
    )


def _split_crs(crs: str | None) -> tuple[int | None, str | None]:
    """``"EPSG:32633"`` → ``(32633, None)``; a WKT string → ``(None, wkt)``."""
    if not crs:
        return None, None
    text = crs.strip()
    upper = text.upper()
    if upper.startswith("EPSG:"):
        try:
            return int(text.split(":", 1)[1]), None
        except ValueError:
            return None, text
    return None, text


def _extract_exif(path: str) -> _ExifMeta:
    """The GPS fix and its error, via ``gis.exif``. Absent GPS ⇒ all-null but valid."""
    from gis.exif import extract_exif_gps

    try:
        gps = extract_exif_gps(path)
    except Exception:  # noqa: BLE001 — EXIF parsing must never fail an ingest
        gps = None
    if gps is None:
        return _ExifMeta(None, None, None, None, {})

    lon = float(gps.position.lon)
    lat = float(gps.position.lat)
    point_wkt = f"SRID=4326;POINT({lon!r} {lat!r})"
    raw = {
        "altitude_ref": gps.altitude_ref,
        "hdop": gps.hdop,
        "is_differential": gps.is_differential,
    }
    return _ExifMeta(
        point_wkt=point_wkt,
        altitude_m=float(gps.altitude_m) if gps.altitude_m is not None else None,
        hpe_m=float(gps.estimated_error_m()),
        captured_at=gps.timestamp,
        raw={k: v for k, v in raw.items() if v is not None},
    )


# ── thumbnail / overviews ─────────────────────────────────────────────────────


def _make_thumbnail(
    storage: Any,
    project_id: uuid.UUID,
    image_id: uuid.UUID,
    path: str,
    meta: _DecodedMeta,
) -> str | None:
    """Render and store a thumbnail; return its storage key (or None on failure).

    Always JPEG, matching ``keys.image_thumbnail_key`` (``.jpg``): a thumbnail is a preview,
    not evidence, so alpha is flattened onto white rather than paid for in PNG bytes.
    """
    from PIL import Image as PILImage

    try:
        with PILImage.open(path) as im:
            if meta.has_alpha:
                rgba = im.convert("RGBA")
                flat = PILImage.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                thumb = flat
            else:
                thumb = im.convert("RGB")
            thumb.thumbnail((_THUMBNAIL_MAX_PX, _THUMBNAIL_MAX_PX))
            buf = io.BytesIO()
            thumb.save(buf, format="JPEG", quality=85)
        key = keys.image_thumbnail_key(project_id, image_id, str(_THUMBNAIL_MAX_PX))
        storage.put(key, buf.getvalue(), content_type="image/jpeg")
        return key
    except Exception as exc:  # noqa: BLE001 — a missing thumbnail is a degraded, not failed, ingest
        log.warning("ingest.thumbnail_failed", image_id=str(image_id), error=str(exc))
        return None


# ── persistence (sync Core UPDATE) ────────────────────────────────────────────


def _write_metadata(
    image_id: uuid.UUID,
    *,
    meta: _DecodedMeta,
    geo: _GeoMeta,
    exif: _ExifMeta,
    thumbnail_path: str | None,
) -> None:
    """Write the derived metadata and flip the image to ``ready`` in one guarded UPDATE.

    Guarded on ``status = pending`` (compare-and-set): a re-ingest must not clobber a state
    a faster path already advanced. Geography columns are set through ``ST_GeogFromText``
    so the worker never has to construct WKB by hand.
    """
    values: dict[str, Any] = {
        "status": ImageStatus.READY.value,
        "width": meta.width,
        "height": meta.height,
        "band_count": meta.band_count,
        "mime_type": meta.mime_type,
        "resolution_dpi": meta.resolution_dpi,
        "is_geotiff": geo.is_geotiff,
        "crs_epsg": geo.crs_epsg,
        "crs_wkt": geo.crs_wkt,
        "geotransform": geo.geotransform,
        "gsd_m": geo.gsd_m,
        "nodata_value": geo.nodata_value,
        "exif": {**meta.camera, **exif.raw},
        "exif_gps_altitude_m": exif.altitude_m,
        "exif_gps_hpe_m": exif.hpe_m,
        "gps_source": "exif" if exif.point_wkt is not None else None,
        "captured_at": exif.captured_at,
        "thumbnail_path": thumbnail_path,
        # Camera/lens columns (camera_make, camera_model, lens_model, focal_length_mm,
        # focal_length_35mm, f_number) — only those present in the EXIF.
        **meta.camera,
    }
    if exif.point_wkt is not None:
        values["exif_gps"] = func.ST_GeogFromText(exif.point_wkt)
    if geo.bounds_wkt is not None:
        values["bounds"] = func.ST_GeogFromText(geo.bounds_wkt)

    # Compare-and-set on the pre-ready states so a late re-ingest cannot overwrite a
    # ``ready`` a faster path already recorded, nor resurrect a hard ``failed``.
    stmt = (
        update(Image)
        .where(
            Image.id == image_id,
            Image.status.in_([ImageStatus.UPLOADED.value, ImageStatus.PROCESSING.value]),
        )
        .values(**values)
    )
    with sync_session() as db:
        result = db.execute(stmt)
        if result.rowcount == 0:
            # Already advanced by a concurrent path. Do not force a state.
            log.info("ingest.already_finalized", image_id=str(image_id))


# ── helpers ───────────────────────────────────────────────────────────────────


class _TempFile:
    """Context manager yielding a filesystem path to the downloaded object.

    ``gis.raster`` (GDAL) needs a real path, and ``gis.exif`` reads a path or stream — a
    temp file serves both and works for every storage backend, local or S3.
    """

    __slots__ = ("_storage", "_key", "_path")

    def __init__(self, storage: Any, key: str) -> None:
        self._storage = storage
        self._key = key
        self._path = ""

    def __enter__(self) -> str:
        suffix = os.path.splitext(self._key)[1]
        fd, self._path = tempfile.mkstemp(suffix=suffix, prefix="le_ingest_")
        with os.fdopen(fd, "wb") as out, self._storage.open(self._key) as src:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return self._path

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._path and os.path.exists(self._path):
                os.unlink(self._path)
        except OSError:
            pass


def _download_to_temp(storage: Any, key: str) -> _TempFile:
    return _TempFile(storage, key)


def _bbox_polygon_wkt(bbox: Any) -> str | None:
    """A closed EPSG:4326 polygon ring for a ``gis`` BBox, as EWKT."""
    try:
        min_lon = float(bbox.min_lon)
        min_lat = float(bbox.min_lat)
        max_lon = float(bbox.max_lon)
        max_lat = float(bbox.max_lat)
    except AttributeError:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
        except Exception:  # noqa: BLE001
            return None
    return (
        "SRID=4326;POLYGON(("
        f"{min_lon!r} {min_lat!r}, {max_lon!r} {min_lat!r}, "
        f"{max_lon!r} {max_lat!r}, {min_lon!r} {max_lat!r}, "
        f"{min_lon!r} {min_lat!r}))"
    )
