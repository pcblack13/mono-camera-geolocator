"""ORM entity → wire schema — the one place a stored row becomes a response body.

★ **EXEMPT from ``api-not-db``**, on the same footing as :mod:`app.api.deps` (§6.4 carve-out):
this module is ``app.api`` but **not** ``app.api.v1``, so the router import contract's
``source_modules = app.api.v1`` does not cover it. It needs ``app.db.types.as_lonlat`` to
decode a ``geography`` column into ``lat``/``lon``, and a router may not import ``app.db``.
Routers import these functions and call them; they never touch geometry themselves.

★ **This module is an addition to §2.4's canonical tree**, flagged in IU-21's report. The
contract left the ORM→wire seam unassigned (services return ORM entities; the wire read models
carry decoded geometry and nested value objects that ``model_validate`` cannot synthesise from
a bare row). Somebody has to convert, and — exactly as §4.22 reasoned for the gis/wire seam and
assigned it to ``services/_adapters`` — that somebody is named here rather than smeared across
sixteen routers.

The geometry decoders are hand-rolled EWKB readers (byte order, type word, doubles) rather than
``geoalchemy2.shape.to_shape``, for the reason ``app.db.types`` gives: ``shapely`` is an optional
dependency, and decoding a point or a ring needs no geometry library at all.
"""

from __future__ import annotations

import struct
from typing import Any, Sequence
from uuid import UUID

from gis.accuracy import LANDMARK_PIXEL_TOLERANCE_PX
from app.db.types import as_lonlat
from app.schemas.batch import (
    BatchCounts,
    BatchItemRead,
    BatchRead,
    BatchRollup,
    BatchSummary,
)
from app.schemas.album import AlbumRead, AlbumSummary
from app.schemas.common import AlbumRef, GeoJsonPolygon, LatLon, PixelXY, RevisionSummary
from app.schemas.export import ExportRead, ExportSummary
from app.schemas.gcp import (
    GcpAccuracy,
    GcpLandmarkRef,
    GcpOriginal,
    GcpOverview,
    GcpRead,
    GcpSummary,
)
from app.schemas.image import (
    CameraMetadata,
    GpsMetadata,
    ImageCounts,
    ImageRead,
    ImageSummary,
    ImageUrls,
    ImageVariant,
)
from app.schemas.job import JobProgress, JobRead, JobSummary
from app.schemas.image_camera import ImageCameraRead
from app.schemas.project import ProjectCounts, ProjectRead, ProjectSummary
from app.schemas.video import VideoRead, VideoSummary, VideoUrls

__all__ = [
    "to_album_read",
    "to_album_summary",
    "to_batch_read",
    "to_batch_summary",
    "to_export_read",
    "to_export_summary",
    "to_gcp_overview",
    "to_gcp_read",
    "to_gcp_summary",
    "to_image_read",
    "to_image_summary",
    "to_job_read",
    "to_job_summary",
    "to_image_camera_read",
    "to_project_read",
    "to_project_summary",
    "to_revision_summary",
    "to_video_read",
    "to_video_summary",
]


# ── enum-or-str coercion at the wire boundary ──────────────────────────────────


def _ev(value: Any) -> Any:
    """Return an enum member's ``.value``, or a plain string unchanged.

    ★ The three enum legs (``app.models.enums``, ``app.schemas.enums``,
    ``ai_engine.types.enums``) are separate ``StrEnum`` classes with identical values
    (§5.3), and a create service may assign a member's ``.value`` straight to a column
    (e.g. ``project_service`` line 84, ``image_service`` line 158). The freshly-added row
    then holds a plain ``str`` in memory until a refresh re-coerces it, so a presenter that
    blindly reads ``.value`` raises ``AttributeError`` on exactly the object it just
    created. This coerces either shape to the wire string, once, for every enum field —
    the response schema re-validates it into the correct wire enum. ``None`` passes through.
    """
    return value.value if hasattr(value, "value") else value


# ── geometry decoding — dependency-free EWKB ───────────────────────────────────

_SRID_FLAG = 0x20000000
_Z_FLAG = 0x80000000
_M_FLAG = 0x40000000
_TYPE_MASK = 0x0FFFFFFF


def _to_bytes(element: Any) -> bytes | None:
    if element is None:
        return None
    data = getattr(element, "data", element)
    if isinstance(data, str):
        return bytes.fromhex(data)
    return bytes(data)


def _read_geometry(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    """Decode one geometry at ``offset``. Returns ``(geojson_dict, next_offset)``.

    Handles Point (1), LineString (2), Polygon (3) and MultiPolygon (6) with optional
    SRID/Z/M flags. Only x,y are emitted — every geometry on this wire is 2-D (§6.1).
    """
    endian = "<" if data[offset] == 1 else ">"
    (type_word,) = struct.unpack_from(endian + "I", data, offset + 1)
    cursor = offset + 5
    if type_word & _SRID_FLAG:
        cursor += 4
    has_z = bool(type_word & _Z_FLAG)
    has_m = bool(type_word & _M_FLAG)
    stride = 2 + (1 if has_z else 0) + (1 if has_m else 0)
    geom_type = type_word & _TYPE_MASK

    def read_point() -> tuple[list[float], int]:
        nonlocal cursor
        coords = struct.unpack_from(endian + "d" * stride, data, cursor)
        cursor += 8 * stride
        return [float(coords[0]), float(coords[1])], cursor

    def read_ring() -> list[list[float]]:
        nonlocal cursor
        (npts,) = struct.unpack_from(endian + "I", data, cursor)
        cursor += 4
        ring: list[list[float]] = []
        for _ in range(npts):
            pt, _ = read_point()
            ring.append(pt)
        return ring

    if geom_type == 1:
        pt, cursor = read_point()
        return {"type": "Point", "coordinates": pt}, cursor
    if geom_type == 2:
        (npts,) = struct.unpack_from(endian + "I", data, cursor)
        cursor += 4
        line = [read_point()[0] for _ in range(npts)]
        return {"type": "LineString", "coordinates": line}, cursor
    if geom_type == 3:
        (nrings,) = struct.unpack_from(endian + "I", data, cursor)
        cursor += 4
        rings = [read_ring() for _ in range(nrings)]
        return {"type": "Polygon", "coordinates": rings}, cursor
    if geom_type == 6:
        (npolys,) = struct.unpack_from(endian + "I", data, cursor)
        cursor += 4
        polys: list[list[list[list[float]]]] = []
        for _ in range(npolys):
            sub, cursor = _read_geometry(data, cursor)
            polys.append(sub["coordinates"])
        return {"type": "MultiPolygon", "coordinates": polys}, cursor
    raise ValueError(f"unsupported WKB geometry type {geom_type}")


def decode_geometry(element: Any) -> dict[str, Any] | None:
    """A stored geometry column → a GeoJSON-shaped dict, or None. Pydantic validates it."""
    data = _to_bytes(element)
    if data is None:
        return None
    return _read_geometry(data, 0)[0]


def _decode_polygon(element: Any) -> GeoJsonPolygon | None:
    geo = decode_geometry(element)
    if geo is None or geo.get("type") != "Polygon":
        return None
    return GeoJsonPolygon.model_validate(geo)


def _latlon(element: Any) -> LatLon | None:
    lonlat = as_lonlat(element)
    if lonlat is None:
        return None
    return LatLon(lat=lonlat[1], lon=lonlat[0])


def _pixel_or_none(x: float | None, y: float | None) -> PixelXY | None:
    if x is None or y is None:
        return None
    return PixelXY(x=float(x), y=float(y))


# ── projects ───────────────────────────────────────────────────────────────────


def to_project_read(project: Any, *, counts: ProjectCounts | None = None) -> ProjectRead:
    """A ``Project`` ORM row → ``ProjectRead``.

    ★ ``aoi_area_km2`` is left ``None``: it is a PostGIS ``ST_Area`` the repository does not
    project onto the returned row. ``counts`` is None unless the router supplied the rollup
    (five aggregate subqueries — ``ProjectRead`` only). Both are honestly null rather than
    fabricated. (Flagged: the projects repository could compute them; the service returns a
    bare ORM row today.)
    """
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        aoi=_decode_polygon(project.aoi),
        aoi_area_km2=None,
        default_provider=_ev(project.default_provider),
        default_extractor=_ev(project.default_extractor),
        default_matcher=_ev(project.default_matcher),
        default_estimator=_ev(project.default_estimator),
        default_search_radius_m=project.default_search_radius_m,
        default_search_zoom=project.default_search_zoom,
        tags=list(project.tags),
        metadata=dict(project.meta),
        current_revision_seq=project.current_revision_seq,
        counts=counts,
        created_at=project.created_at,
        updated_at=project.updated_at,
        deleted_at=project.deleted_at,
    )


def to_project_summary(
    project: Any,
    *,
    image_count: int = 0,
    albums: Sequence[tuple[UUID, str]] | None = None,
) -> ProjectSummary:
    """A ``Project`` ORM row → ``ProjectSummary``.

    ★ ``albums`` arrives as ``(id, name)`` pairs the router fetched for the **whole page
    in one query** (``AlbumRepository.albums_for_projects``). It is not read from
    ``project.albums``, which is ``lazy="raise"`` precisely so the N+1 cannot happen —
    the many-to-many makes it a per-row query otherwise. ``None`` ⇒ ``[]``, which is the
    truth for a project in no album and for a caller that did not ask.
    """
    return ProjectSummary(
        id=project.id,
        name=project.name,
        description=project.description,
        tags=list(project.tags),
        aoi_area_km2=None,
        image_count=image_count,
        albums=[AlbumRef(id=aid, name=name) for aid, name in (albums or ())],
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def to_image_camera_read(camera: Any, *, image_id: UUID) -> ImageCameraRead:
    """An ``ImageCamera`` ORM row → ``ImageCameraRead`` — or the honest empty shape.

    ``camera=None`` is a real answer ("this photograph has not saved a camera") and
    gets ``configured=False`` with every field null — including the timestamps,
    because an unconfigured camera has no ``created_at`` and none is invented.
    """
    if camera is None:
        return ImageCameraRead(
            image_id=image_id,
            configured=False,
            fx=None, fy=None, cx=None, cy=None,
            k1=None, k2=None, p1=None, p2=None, k3=None,
            img_w=None, img_h=None,
            no_calibration=False, fov_h_deg=None, fov_v_deg=None,  # GEO-DRIFT-UPDATE C2
            lat=None, lon=None, mast_offset_m=None,
            tilt_deg=None,
            auto_gcp_enabled=False,
            created_at=None, updated_at=None,
        )  # fmt: skip
    lonlat = as_lonlat(camera.position)
    return ImageCameraRead(
        image_id=camera.image_id,
        configured=True,
        fx=camera.fx,
        fy=camera.fy,
        cx=camera.cx,
        cy=camera.cy,
        k1=camera.k1,
        k2=camera.k2,
        p1=camera.p1,
        p2=camera.p2,
        k3=camera.k3,
        no_calibration=bool(getattr(camera, "no_calibration", False)),  # GEO-DRIFT-UPDATE C2
        fov_h_deg=getattr(camera, "fov_h_deg", None),
        fov_v_deg=getattr(camera, "fov_v_deg", None),
        img_w=camera.img_w,
        img_h=camera.img_h,
        lat=lonlat[1] if lonlat is not None else None,
        lon=lonlat[0] if lonlat is not None else None,
        mast_offset_m=camera.mast_offset_m,
        tilt_deg=camera.tilt_deg,
        auto_gcp_enabled=camera.auto_gcp_enabled,
        created_at=camera.created_at,
        updated_at=camera.updated_at,
    )


# ── albums ─────────────────────────────────────────────────────────────────────


def to_album_read(album: Any, *, project_count: int = 0) -> AlbumRead:
    """An ``Album`` ORM row → ``AlbumRead``.

    ``project_count`` is supplied by the caller from a batched aggregate; ``Album.projects``
    is ``lazy="raise"`` and reading ``len(album.projects)`` here would raise rather than
    quietly issue a query — which is the design working.
    """
    return AlbumRead(
        id=album.id,
        name=album.name,
        description=album.description,
        color=album.color,
        project_count=project_count,
        created_at=album.created_at,
        updated_at=album.updated_at,
        deleted_at=album.deleted_at,
    )


def to_album_summary(album: Any, *, project_count: int = 0) -> AlbumSummary:
    return AlbumSummary(
        id=album.id,
        name=album.name,
        description=album.description,
        color=album.color,
        project_count=project_count,
        created_at=album.created_at,
        updated_at=album.updated_at,
    )


# ── videos ─────────────────────────────────────────────────────────────────────


def to_video_read(video: Any, *, prefix: str, preview_available: bool = False) -> VideoRead:
    """A ``Video`` ORM row → ``VideoRead``.

    ``urls.file`` is the Range-capable stream the browser scrubs; ``urls.frame`` is the
    preview base the client appends ``?t=<seconds>`` to. ``storage_path`` is never emitted.
    """
    base = f"{prefix}/videos/{video.id}"
    return VideoRead(
        id=video.id,
        project_id=video.project_id,
        filename=video.filename,
        mime_type=video.mime_type,
        size_bytes=video.size_bytes,
        checksum_sha256=video.checksum_sha256,
        duration_s=video.duration_s,
        fps=video.fps,
        width=video.width,
        height=video.height,
        frame_count=video.frame_count,
        codec=video.codec,
        preview_available=preview_available,
        urls=VideoUrls(
            file=f"{base}/file", frame=f"{base}/frame", preview=f"{base}/preview"
        ),
        created_at=video.created_at,
        updated_at=video.updated_at,
        deleted_at=video.deleted_at,
    )


def to_video_summary(video: Any) -> VideoSummary:
    return VideoSummary(
        id=video.id,
        project_id=video.project_id,
        filename=video.filename,
        duration_s=video.duration_s,
        fps=video.fps,
        width=video.width,
        height=video.height,
        size_bytes=video.size_bytes,
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


# ── images ─────────────────────────────────────────────────────────────────────


def _image_version(image: Any) -> str:
    """A cache-busting token tied to the stored FILE BYTES (the checksum).

    ★ Appended to the file URL so a **rescale** — which overwrites the bytes in place at the
    same storage key and changes the checksum — yields a NEW url. Both the browser HTTP cache
    and the viewer's url-keyed reload effect then fetch the resized pixels. A metadata-only
    update leaves the checksum (and the url) unchanged, so it costs no needless re-fetch.
    """
    return (getattr(image, "checksum_sha256", "") or "0")[:16]


def _image_urls(image: Any, prefix: str) -> ImageUrls:
    base = f"{prefix}/images/{image.id}"
    v = _image_version(image)
    return ImageUrls(
        file=f"{base}/file?v={v}",
        thumbnail=f"{base}/thumbnail?v={v}" if image.thumbnail_path else None,
        preview=None,
        metadata=f"{base}/metadata",
    )


def _image_gps(image: Any) -> GpsMetadata | None:
    lonlat = as_lonlat(image.exif_gps)
    if lonlat is None:
        return None
    return GpsMetadata(
        lat=lonlat[1],
        lon=lonlat[0],
        altitude_m=image.exif_gps_altitude_m,
        direction_deg=image.exif_gps_direction_deg,
        hpe_m=image.exif_gps_hpe_m,
        source=image.gps_source if image.gps_source in ("exif", "manual") else "exif",
    )


def _image_camera(image: Any) -> CameraMetadata:
    return CameraMetadata(
        make=image.camera_make,
        model=image.camera_model,
        lens_model=image.lens_model,
        focal_length_mm=image.focal_length_mm,
        focal_length_35mm=image.focal_length_35mm,
        sensor_width_mm=image.sensor_width_mm,
        f_number=image.f_number,
    )


def to_image_read(image: Any, *, prefix: str, counts: ImageCounts | None = None) -> ImageRead:
    """An ``Image`` ORM row → ``ImageRead``.

    ★ ``variants`` carries the ``original`` variant, built exactly from the stored
    post-normalisation ``width``/``height`` (``display_scale = 1.0``). The ``thumbnail`` /
    ``preview`` variants and their dimensions are produced by the ingest task and are **not**
    columns on this row, so they are not fabricated here (flagged: ImageRead's derived
    renditions want ingest output the service does not return). ``counts`` defaults to zeros
    unless the router supplied them; ``latest_match`` is always null (matching deferred).
    """
    variant = ImageVariant(
        name="original",
        # ★ Same checksum cache-buster as `urls.file`: the viewer's bitmap-load effect keys on
        # THIS url, so after a rescale (new bytes → new checksum) the url changes and the new
        # pixels load without a manual refresh.
        url=f"{prefix}/images/{image.id}/file?v={_image_version(image)}",
        width=image.width,
        height=image.height,
        original_width=image.width,
        original_height=image.height,
        display_scale=1.0,
        size_bytes=image.size_bytes,
    )
    return ImageRead(
        id=image.id,
        project_id=image.project_id,
        filename=image.filename,
        mime_type=image.mime_type,
        size_bytes=image.size_bytes,
        checksum_sha256=image.checksum_sha256,
        width=image.width,
        height=image.height,
        band_count=image.band_count,
        status=_ev(image.status),
        is_geotiff=image.is_geotiff,
        gps=_image_gps(image),
        camera=_image_camera(image),
        captured_at=image.captured_at,
        notes=image.notes,
        metadata=dict(image.meta),
        urls=_image_urls(image, prefix),
        variants=[variant],
        counts=counts or ImageCounts(annotations=0, gcps=0, match_jobs=0),
        latest_match=None,
        warnings=[],
        source_video_id=getattr(image, "source_video_id", None),
        source_video_time_s=getattr(image, "source_video_time_s", None),
        uploaded_at=image.uploaded_at,
        created_at=image.created_at,
        updated_at=image.updated_at,
        deleted_at=image.deleted_at,
    )


def _bounds_envelope(element: Any) -> list[float] | None:
    geo = decode_geometry(element)
    if geo is None:
        return None
    lons: list[float] = []
    lats: list[float] = []

    def walk(coords: Any) -> None:
        if coords and isinstance(coords[0], (int, float)):
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
        else:
            for c in coords:
                walk(c)

    walk(geo.get("coordinates", []))
    if not lons:
        return None
    return [min(lons), min(lats), max(lons), max(lats)]


def to_image_metadata(image: Any, *, metadata_id: Any) -> Any:
    """An ``Image`` ORM row → ``ImageMetadataRead`` (endpoint 14).

    ★ ``raster.dtype`` / ``color_interpretation`` / ``has_alpha`` and the variant list are ingest
    output not stored as columns on this row; they are filled with honest, conservative defaults
    (flagged). The forensic ``exif`` blob, the camera/GPS/geotiff facts and the file digest are
    real, from the row.
    """
    from app.schemas.image import (
        CaptureMetadata,
        DerivedMetadata,
        FileMetadata,
        GeoTiffMetadata,
        ImageMetadataRead,
        RasterMetadata,
    )

    geotiff = None
    if image.is_geotiff:
        crs = f"EPSG:{image.crs_epsg}" if image.crs_epsg is not None else image.crs_wkt
        geotiff = GeoTiffMetadata(
            crs=crs,
            geotransform=list(image.geotransform) if image.geotransform else None,
            bounds=_bounds_envelope(image.bounds),
            gsd_m=image.gsd_m,
            nodata=image.nodata_value,
            overview_count=0,
        )
    original = ImageVariant(
        name="original",
        url="",
        width=image.width,
        height=image.height,
        original_width=image.width,
        original_height=image.height,
        display_scale=1.0,
        size_bytes=image.size_bytes,
    )
    return ImageMetadataRead(
        id=metadata_id,
        image_id=image.id,
        file=FileMetadata(
            filename=image.filename,
            mime_type=image.mime_type,
            size_bytes=image.size_bytes,
            checksum_sha256=image.checksum_sha256,
        ),
        raster=RasterMetadata(
            width=image.width,
            height=image.height,
            band_count=image.band_count,
            dtype="uint8",
            color_interpretation=[],
            has_alpha=image.band_count >= 4,
        ),
        camera=_image_camera(image),
        gps=_image_gps(image),
        capture=CaptureMetadata(
            captured_at=image.captured_at,
            orientation=None,
            orientation_normalized=True,
        ),
        geotiff=geotiff,
        derived=DerivedMetadata(variants=[original], histogram_url=None),
        exif=dict(image.exif or {}),
        metadata=dict(image.meta),
        warnings=[],
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


def to_image_summary(
    image: Any, *, prefix: str, annotation_count: int = 0, gcp_count: int = 0
) -> ImageSummary:
    return ImageSummary(
        id=image.id,
        project_id=image.project_id,
        filename=image.filename,
        status=_ev(image.status),
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
        is_geotiff=image.is_geotiff,
        thumbnail_url=f"{prefix}/images/{image.id}/thumbnail" if image.thumbnail_path else None,
        annotation_count=annotation_count,
        gcp_count=gcp_count,
        source_video_id=getattr(image, "source_video_id", None),
        source_video_time_s=getattr(image, "source_video_time_s", None),
        captured_at=image.captured_at,
        uploaded_at=image.uploaded_at,
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


# ── annotations ────────────────────────────────────────────────────────────────

_GCP_CANDIDATE_ANNOTATION_KINDS = frozenset({"field_corner", "road_intersection", "building_corner"})


def to_annotation_read(annotation: Any, *, gcp_ids: Sequence[Any] = (), gcp_id: Any = None) -> Any:
    """An ``Annotation`` ORM row → ``AnnotationRead``.

    ``geometry`` is the decoded ``pixel_geom`` — GeoJSON-**shaped** but IMAGE PIXELS, ``[x, y]``,
    y-down, SRID 0 (never fed to Leaflet as degrees). ``is_gcp_candidate`` is derived from
    ``kind``; ``gcp_ids`` / ``gcp_id`` are supplied by the router's batched lookup.
    """
    from app.schemas.annotation import AnnotationRead

    kind = str(getattr(annotation.kind, "value", annotation.kind))
    geometry = decode_geometry(annotation.pixel_geom)
    return AnnotationRead(
        id=annotation.id,
        image_id=annotation.image_id,
        kind=kind,
        geom_type=str(getattr(annotation.geom_type, "value", annotation.geom_type)),
        pixel_x=annotation.pixel_x,
        pixel_y=annotation.pixel_y,
        geometry=geometry,
        label=annotation.label,
        description=annotation.description,
        confidence=annotation.confidence,
        ordering=annotation.ordering,
        style=dict(annotation.style or {}),
        attributes=dict(annotation.attributes or {}),
        version_no=annotation.version_no,
        revision_seq=annotation.revision_seq,
        is_deleted=annotation.is_deleted,
        is_gcp_candidate=kind in _GCP_CANDIDATE_ANNOTATION_KINDS,
        gcp_ids=list(gcp_ids),
        gcp_id=gcp_id,
        created_by=annotation.created_by,
        updated_by=annotation.updated_by,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
    )


# ── GCPs — the deliverable ─────────────────────────────────────────────────────

_GCP_CANDIDATE_KINDS = frozenset({"field_corner", "road_intersection", "building_corner"})


def _gcp_accuracy(gcp: Any) -> GcpAccuracy:
    return GcpAccuracy(
        relative_ce90_m=gcp.accuracy_relative_ce90_m,
        georef_ce90_m=gcp.georef_ce90_m,
        total_ce90_m=gcp.accuracy_total_ce90_m,
        semi_major_ce90_m=gcp.accuracy_semi_major_ce90_m,
        semi_minor_ce90_m=gcp.accuracy_semi_minor_ce90_m,
        azimuth_deg=gcp.accuracy_azimuth_deg,
        dominant_term=gcp.accuracy_dominant_term,
    )


def _gcp_original(gcp: Any) -> GcpOriginal | None:
    if not gcp.manually_adjusted or gcp.original_geom is None:
        return None
    lonlat = as_lonlat(gcp.original_geom)
    if lonlat is None:
        return None
    return GcpOriginal(
        lat=lonlat[1],
        lon=lonlat[0],
        satellite_px=PixelXY(
            x=float(gcp.original_satellite_pixel_x or 0.0),
            y=float(gcp.original_satellite_pixel_y or 0.0),
        ),
        confidence=float(gcp.original_confidence if gcp.original_confidence is not None else gcp.confidence),
    )


def _surveyor_confidence(gcp: Any) -> int | None:
    """The 0–100 ``confidence`` back to the surveyor's 1–5, for ``manual`` GCPs.

    Inverts ``SURVEYOR_CONFIDENCE_TO_SCORE`` by nearest band, so the round trip a client sees
    (declared 4 → 85 → declared 4) is stable. Null for an ``automatic`` GCP (none in this build).
    """
    if gcp.source != "manual":
        return None
    from app.schemas.gcp import SURVEYOR_CONFIDENCE_TO_SCORE

    score = float(gcp.confidence)
    return min(SURVEYOR_CONFIDENCE_TO_SCORE, key=lambda k: abs(SURVEYOR_CONFIDENCE_TO_SCORE[k] - score))


def to_gcp_read(gcp: Any, *, landmark: GcpLandmarkRef | None = None) -> GcpRead:
    """A ``GCP`` ORM row → ``GcpRead``.

    ★ **Flagged cross-unit tension:** ``GcpRead.match_result_id`` and ``GcpRead.satellite_px``
    are declared *required* by IU-17, but a **manual** GCP has both NULL by construction
    (SCOPE.md §5 / the ``gcps`` model). They are passed through as their true (possibly null)
    values here; for a manual GCP to serialise, IU-17 must relax those two fields to
    ``Optional[...] = None``. This presenter does not fabricate a mosaic pixel it does not have.
    """
    lonlat = as_lonlat(gcp.geom)
    lat, lon = (lonlat[1], lonlat[0]) if lonlat is not None else (0.0, 0.0)
    accuracy = _gcp_accuracy(gcp)
    return GcpRead(
        id=gcp.id,
        image_id=gcp.image_id,
        match_result_id=gcp.match_result_id,  # type: ignore[arg-type]  # nullable for manual — see docstring
        landmark_id=gcp.landmark_id,
        code=gcp.code,
        name=getattr(gcp, "name", None),
        image_px=PixelXY(x=float(gcp.pixel_x), y=float(gcp.pixel_y)),
        satellite_px=_pixel_or_none(gcp.satellite_pixel_x, gcp.satellite_pixel_y),  # type: ignore[arg-type]
        lat=lat,
        lon=lon,
        elevation_m=gcp.elevation_m,
        elevation_source=gcp.elevation_source,
        source=gcp.source,
        confidence=gcp.confidence,
        declared_confidence=_surveyor_confidence(gcp),
        horizontal_accuracy_m=gcp.accuracy_total_ce90_m,
        accuracy=accuracy,
        residual_px=gcp.residual_px,
        pixel_accuracy_ceiling_px=LANDMARK_PIXEL_TOLERANCE_PX,
        # ★ A residual is a MEASURED pixel error (direct/automatic fix only); null in manual
        #   mode, where the pixel is the surveyor's own observation and there is nothing to
        #   judge — so "within ceiling" is true unless a real residual exceeds the ceiling.
        pixel_accuracy_within_ceiling=(
            gcp.residual_px is None or gcp.residual_px <= LANDMARK_PIXEL_TOLERANCE_PX
        ),
        manually_adjusted=gcp.manually_adjusted,
        original=_gcp_original(gcp),
        adjustment_offset_m=gcp.adjustment_offset_m,
        adjusted_by=gcp.adjusted_by,
        adjusted_at=gcp.adjusted_at,
        adjustment_note=gcp.adjustment_note,
        is_included_in_export=gcp.is_included_in_export,
        is_stale=gcp.is_stale,
        stale_reason=_ev(gcp.stale_reason) if gcp.stale_reason is not None else None,
        landmark=landmark,
        reference_imagery=getattr(gcp, "reference_imagery", None),
        created_at=gcp.created_at,
        updated_at=gcp.updated_at,
    )


def to_gcp_summary(gcp: Any) -> GcpSummary:
    lonlat = as_lonlat(gcp.geom)
    lat, lon = (lonlat[1], lonlat[0]) if lonlat is not None else (0.0, 0.0)
    return GcpSummary(
        id=gcp.id,
        image_id=gcp.image_id,
        code=gcp.code,
        image_px=PixelXY(x=float(gcp.pixel_x), y=float(gcp.pixel_y)),
        lat=lat,
        lon=lon,
        source=gcp.source,
        confidence=gcp.confidence,
        declared_confidence=_surveyor_confidence(gcp),
        total_ce90_m=gcp.accuracy_total_ce90_m,
        manually_adjusted=gcp.manually_adjusted,
        is_stale=gcp.is_stale,
        is_included_in_export=gcp.is_included_in_export,
    )


def to_gcp_overview(row: Any) -> GcpOverview:
    """A cross-project overview **row** → ``GcpOverview``.

    ★ Takes a joined result row, not an ORM entity. ``lat``/``lon`` arrive already
    projected out of ``geom`` by ``ST_Y``/``ST_X`` in the repository, so there is no EWKB
    to decode here — one fewer place a coordinate can be transposed, and the position
    comes back as two floats rather than as bytes this module would have to parse per row
    for a map with thousands of markers.
    """
    return GcpOverview(
        id=row.id,
        project_id=row.project_id,
        project_name=row.project_name,
        image_id=row.image_id,
        image_filename=row.image_filename,
        code=row.code,
        landmark_name=row.landmark_name,
        lat=float(row.lat),
        lon=float(row.lon),
        confidence=float(row.confidence),
        source=_ev(row.source),
        total_ce90_m=(
            float(row.total_ce90_m) if row.total_ce90_m is not None else None
        ),
    )


# ── jobs — model_validate over the JobView read model ──────────────────────────


def _job_progress(job: Any) -> JobProgress:
    stage = job.progress_stage or "pending"
    return JobProgress(
        percent=float(job.progress) * 100.0,
        stage=stage,
        message=job.progress_message,
        tiles_fetched=job.tiles_fetched,
        tiles_total=job.tiles_total,
        candidates_evaluated=job.candidates_evaluated,
    )


def to_job_read(job: Any, *, result_url: str | None = None) -> JobRead:
    """A ``JobView`` → ``JobRead``. The DB stores ``progress`` 0–1; the wire is 0–100."""
    from app.schemas.errors import ErrorBody

    error = None
    if job.error_message:
        from datetime import datetime, timezone

        error = ErrorBody(
            code=(job.error_type or "INTERNAL_ERROR"),
            message=job.error_message,
            status=500,
            details=None,
            request_id="job",
            timestamp=job.finished_at or datetime.now(tz=timezone.utc),
            docs_url=None,
            feature=None,
        )
    return JobRead(
        id=job.id,
        type=_ev(job.type),
        status=_ev(job.status),
        image_id=job.image_id,
        project_id=job.project_id,
        batch_id=job.batch_id,
        cancel_requested=job.cancel_requested,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        progress=_job_progress(job),
        degraded=job.degraded,
        degradation_reason=job.degradation_reason,
        warnings=list(job.warnings or []),
        result_ref=None,
        result_url=result_url,
        error=error,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def to_job_summary(job: Any) -> JobSummary:
    return JobSummary(
        id=job.id,
        type=_ev(job.type),
        status=_ev(job.status),
        image_id=job.image_id,
        project_id=job.project_id,
        percent=float(job.progress) * 100.0,
        stage=job.progress_stage or "pending",
        degraded=job.degraded,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


# ── exports ────────────────────────────────────────────────────────────────────


def to_export_read(export: Any, *, prefix: str) -> ExportRead:
    from app.schemas.export import ExportFilter, ExportOptions

    download = (
        f"{prefix}/exports/{export.id}/download"
        if str(getattr(export.status, "value", export.status)) == "succeeded"
        else None
    )
    return ExportRead(
        id=export.id,
        project_id=export.project_id,
        image_id=export.image_id,
        format=str(getattr(export.format, "value", export.format)),
        status=str(getattr(export.status, "value", export.status)),
        cancel_requested=getattr(export, "cancel_requested", False),
        download_url=download,
        filename=getattr(export, "filename", None),
        size_bytes=getattr(export, "size_bytes", None),
        checksum_sha256=getattr(export, "checksum_sha256", None),
        gcp_count=getattr(export, "gcp_count", None),
        target_srid=export.target_srid,
        options=ExportOptions.model_validate(export.options or {}),
        filter=ExportFilter.model_validate(export.filter or {}),
        warnings=list(getattr(export, "warnings", []) or []),
        error_message=getattr(export, "error_message", None),
        requested_by=getattr(export, "requested_by", None),
        expires_at=getattr(export, "expires_at", None),
        created_at=export.created_at,
        updated_at=export.updated_at,
    )


def to_export_summary(export: Any, *, prefix: str) -> ExportSummary:
    download = (
        f"{prefix}/exports/{export.id}/download"
        if str(getattr(export.status, "value", export.status)) == "succeeded"
        else None
    )
    return ExportSummary(
        id=export.id,
        format=str(getattr(export.format, "value", export.format)),
        status=str(getattr(export.status, "value", export.status)),
        filename=getattr(export, "filename", None),
        size_bytes=getattr(export, "size_bytes", None),
        gcp_count=getattr(export, "gcp_count", None),
        download_url=download,
        expires_at=getattr(export, "expires_at", None),
        created_at=export.created_at,
    )


# ── batches ────────────────────────────────────────────────────────────────────


def _batch_counts(batch: Any, tally: dict[str, int] | None) -> BatchCounts:
    t = tally or {}
    return BatchCounts(
        total=batch.total_items,
        pending=t.get("pending", 0) + t.get("queued", 0),
        running=t.get("running", 0) + t.get("retrying", 0),
        succeeded=t.get("succeeded", 0),
        failed=t.get("failed", 0),
        cancelled=t.get("cancelled", 0),
    )


def to_batch_read(batch: Any, *, tally: dict[str, int] | None = None, items: Sequence[Any] = ()) -> BatchRead:
    return BatchRead(
        id=batch.id,
        project_id=batch.project_id,
        name=batch.name,
        status=str(getattr(batch.status, "value", batch.status)),
        cancel_requested=batch.cancel_requested,
        counts=_batch_counts(batch, tally),
        progress=float(batch.progress),
        rollup=None if batch.finished_at is None else BatchRollup(
            gcp_count=0, mean_confidence=None, images_with_results=0, images_without_results=batch.total_items
        ),
        provider=str(getattr(batch.provider, "value", batch.provider)),
        params=dict(batch.params or {}),
        concurrency=batch.concurrency,
        continue_on_error=batch.continue_on_error,
        items=[_batch_item(i) for i in items],
        warnings=list(getattr(batch, "warnings", []) or []),
        error_message=batch.error_message,
        requested_by=batch.requested_by,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _batch_item(item: Any) -> BatchItemRead:
    return BatchItemRead(
        id=item.id,
        batch_job_id=item.batch_job_id,
        image_id=item.image_id,
        match_job_id=item.match_job_id,
        ordinal=item.ordinal,
        status=str(getattr(item.status, "value", item.status)),
        error_message=item.error_message,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def to_batch_summary(batch: Any, *, tally: dict[str, int] | None = None) -> BatchSummary:
    return BatchSummary(
        id=batch.id,
        project_id=batch.project_id,
        name=batch.name,
        status=str(getattr(batch.status, "value", batch.status)),
        counts=_batch_counts(batch, tally),
        progress=float(batch.progress),
        created_at=batch.created_at,
        finished_at=batch.finished_at,
    )


# ── revisions ──────────────────────────────────────────────────────────────────


def to_revision_summary(revision: Any, *, annotation_count: int = 0) -> RevisionSummary:
    return RevisionSummary(
        id=revision.id,
        project_id=revision.project_id,
        seq=revision.seq,
        label=revision.label,
        is_checkpoint=revision.is_checkpoint,
        annotation_count=annotation_count,
        created_at=revision.created_at,
    )
