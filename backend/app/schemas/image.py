"""Uploaded imagery (§6.2) — endpoints 9–15.

★ **This module imports ``job.py``**, for ``ImageUploadAccepted.job``. §6.2 says
*"No schema module imports another domain schema module"*, and its stated reasons
are (a) keep the graph acyclic and (b) let any schema be imported into a Celery
worker without dragging in FastAPI. Both hold here: ``job`` does not import
``image``, and neither touches FastAPI. §6.2 fixed its own first violation by
moving ``RevisionSummary`` to ``common`` — a value object with two owners. A
``202`` body that is *literally* ``{image: ImageRead, job: JobRead}`` is not that:
moving ``JobRead`` to ``common`` to dodge an import would put the whole job
vocabulary in the shared module and mean nothing. The rule the package actually
keeps is **acyclic, one-way**, and the three edges that exist
(``image → job``, ``batch → matching``, ``revision → annotation``) are declared
in ``schemas/__init__.py``'s DAG and flagged in IU-17's report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, Field

from .common import META_FIELD, ApiModel, ListParams, PatchModel, WarningItem
from .enums import ImageFormat, ImageStatus, ThumbnailSize
from .job import JobRead

__all__ = [
    "IMAGE_SORT_FIELDS",
    "CameraMetadata",
    "CaptureMetadata",
    "DerivedMetadata",
    "FileMetadata",
    "GeoTiffMetadata",
    "GpsMetadata",
    "ImageCounts",
    "ImageListParams",
    "ImageMetadataRead",
    "ImageRead",
    "ImageRescaleRequest",
    "ImageSummary",
    "ImageUpdate",
    "ImageUploadAccepted",
    "ImageUploadForm",
    "ImageUrls",
    "ImageVariant",
    "LatestMatchRef",
    "RasterMetadata",
    "ThumbnailParams",
]

IMAGE_SORT_FIELDS = frozenset(
    {"filename", "uploaded_at", "created_at", "updated_at", "size_bytes", "captured_at"}
)


class ImageVariant(ApiModel):
    """One rendition of an uploaded image.

    ★ §12 C-36 / §8.6. **THE frontend's load-bearing requirement.** Without
    ``original_width`` the client cannot compute ``D = width / original_width``
    and the entire coordinate model collapses. PRESENT ON EVERY VARIANT,
    NON-NULL, ALWAYS.

    The failure this prevents: the naive viewer reads
    ``stage.getPointerPosition()``, divides by scale, subtracts pan, and stores
    **display** pixels. That silently disagrees with the backend — which
    computed everything on the ORIGINAL — and every annotation jumps by
    ``D₁/D₂`` when a variant swaps. It survives development because ``D ≈ 1`` on
    small test images and detonates on the first real 5000 px upload.

    ★ This matters more in this build, not less. SCOPE.md §5 makes the manual
    pixel↔map correspondence *the product*, and requires the photo pixel to be
    stored in **original image pixel space, independent of viewer zoom or
    brightness/contrast**. ``display_scale`` is the number that conversion is
    made of.
    """

    name: Literal["thumbnail", "preview", "full", "original"]
    url: str
    width: int = Field(gt=0, description="This variant's raster width.")
    height: int = Field(gt=0)
    original_width: int = Field(gt=0, description="★ ALWAYS the full-resolution width.")
    original_height: int = Field(gt=0, description="★ ALWAYS the full-resolution height.")
    display_scale: float = Field(
        gt=0.0, description="★ = width / original_width. Server-computed. THE `D` of §8.6."
    )
    size_bytes: int | None = None


class GpsMetadata(ApiModel):
    """Where the photograph says it was taken.

    ★ ``source`` distinguishes an EXIF fix from a human assertion. They are not
    the same evidence and the search-hint precedence (§6.2) treats them
    differently.
    """

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    altitude_m: float | None
    direction_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    hpe_m: float | None = Field(default=None, description="Horizontal positional error, metres.")
    source: Literal["exif", "manual"]


class CameraMetadata(ApiModel):
    """★ Non-optional on ``ImageRead`` but every FIELD is nullable — a photo with
    no EXIF still has a ``camera`` object, full of nulls. That is the response
    null rule (§6.1): a nullable field is always present with value ``null``, and
    clients must not distinguish absent from null.
    """

    make: str | None
    model: str | None
    lens_model: str | None
    focal_length_mm: float | None
    focal_length_35mm: float | None
    sensor_width_mm: float | None
    f_number: float | None


class ImageUrls(ApiModel):
    """★ ``storage_path`` is **NEVER serialised**. It is a server-controlled
    filesystem/S3 path; exposing it invites path-traversal probing and leaks the
    storage layout. Clients get ``file``.
    """

    file: str
    thumbnail: str | None
    preview: str | None
    metadata: str


class ImageCounts(ApiModel):
    """Cheap correlated counts."""

    annotations: int
    gcps: int
    match_jobs: int


class LatestMatchRef(ApiModel):
    """The most recent match job for this image, for the list badge.

    ★★ In this build no row exists behind this: matching is DEFERRED
    (SCOPE.md §1), so ``ImageRead.latest_match`` is always ``null``. The field
    stays because the ``match_jobs`` table is NOT cut (SCOPE.md §4 rule 5) and
    re-enabling must cost no caller a change (rule 7).
    """

    match_job_id: UUID
    match_result_id: UUID | None
    status: str
    overall_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    created_at: datetime


class ImageUploadForm(ApiModel):
    """``POST /images`` — endpoint 9. **multipart**, not JSON.

    ★ The file part itself is NOT modelled here: it is a ``fastapi.UploadFile``
    on the route signature, because it must be **streamed** — 1 MB chunks with a
    running SHA-256 and byte count, checked *during* the stream.
    ``await file.read()`` into memory lets eight concurrent 500 MB uploads OOM
    the container. A pydantic model cannot express "stream me", so it does not
    pretend to; this carries the metadata parts only.

    ★ **MIME is determined by magic bytes, never by the client.** The part
    header and the filename extension are both untrusted and recorded only as
    advisory metadata. Sniff 32 bytes, then confirm by opening with GDAL.
    ``application/octet-stream`` is accepted at the header level and resolved by
    sniffing — browsers and ``curl`` both send it for ``.tif``.
    """

    project_id: UUID
    filename: str | None = Field(
        default=None,
        max_length=512,
        description="Advisory only. Overrides the part's filename for display.",
    )
    notes: str | None = Field(default=None, max_length=4000)
    captured_at: datetime | None = None
    metadata: dict[str, Any] = META_FIELD


class ImageUploadAccepted(ApiModel):
    """``202`` from ``POST /images`` when the upload exceeds
    ``LE_ASYNC_INGEST_THRESHOLD_BYTES`` (50 MB): the row is inserted
    ``status='processing'`` and an ``ingest`` aux job is enqueued.

    ★ The two-tier design exists for ``local_orthophoto``, the single
    highest-accuracy path in the product: orthophoto GeoTIFFs are routinely
    100–400 MB, so a 50 MB cap would make the accuracy path un-uploadable, while
    decoding a 400 MB ortho inline would hold a worker thread for 20 s. Cap at
    500 MB, go async above 50 (§12 C-06).
    """

    image: "ImageRead"
    job: JobRead


class ImageUpdate(PatchModel):
    """``PATCH /images/{image_id}``. ★ UNSET semantics.

    ★ ``width``/``height``/``mime_type``/``checksum_sha256`` are absent by
    design: they are facts about the bytes, established at ingest by sniffing and
    by GDAL. A client that could PATCH them could make the row lie about the file
    it points at.
    """

    filename: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=4000)
    captured_at: datetime | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )


class ImageRescaleRequest(ApiModel):
    """``POST /images/{image_id}/rescale`` — resize an already-stored photo.

    ★ **The recorded lat/lon of every GCP does NOT change.** A GCP's coordinate comes
    from the surveyor's map click, not from the photo, so resizing the photo cannot move
    it. What *does* scale is the photo-pixel position of each landmark and GCP, by
    ``sx = width/old_width`` / ``sy = height/old_height``, so each marker stays on the
    same feature. The satellite/mosaic pixels are likewise untouched — they live in a
    different pixel space entirely.

    Bounds mirror ``image_ops.MAX_DIMENSION`` (the resize helper's own guard) so a
    rejected size is rejected identically whether it arrives here or through an upload's
    ``target_*`` form fields.
    """

    width: int = Field(ge=1, le=20000, description="Target width in pixels.")
    height: int = Field(ge=1, le=20000, description="Target height in pixels.")


class ImageRead(ApiModel):
    """``ImageRead`` — endpoints 9, 11.

    ★ ``exif`` — the verbatim blob, hundreds of tags including embedded
    thumbnails — is **NOT here**. It lives at ``/metadata`` (endpoint 14).
    """

    id: UUID
    project_id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    width: int = Field(
        gt=0,
        description=(
            "★ POST orientation normalisation. EXIF orientation is normalised at "
            "ingest and width/height stored post-rotation. If they were not, "
            "Konva, OpenCV imread, GDAL and the PDF exporter would each "
            "independently re-apply the tag — **and they do not agree with each "
            "other** — so annotation pixel coordinates would mean different "
            "things in different components, corrupting GCP output. The original "
            "EXIF block is preserved verbatim at /metadata, so nothing is lost."
        ),
    )
    height: int = Field(gt=0)
    band_count: int
    status: ImageStatus
    is_geotiff: bool = Field(
        description=(
            "★ True IFF GDAL reports a non-null projection AND a geotransform "
            "that is NOT the identity (0,1,0,0,0,1). That second condition "
            "matters — GDAL hands back the identity transform for plain TIFFs, "
            "and a naive `if gt:` marks every scanned TIFF as georeferenced at "
            "the equator.\n\n"
            "★ SCOPE.md §3: a georeferenced upload short-circuits to exact GCPs "
            "with no matching at all. That path is BUILT."
        )
    )
    gps: GpsMetadata | None = Field(default=None, description="Null when no GPS at all.")
    camera: CameraMetadata
    captured_at: datetime | None
    notes: str | None
    metadata: dict[str, Any] = META_FIELD
    urls: ImageUrls
    variants: list[ImageVariant] = Field(description="★ REQUIRED. See ImageVariant.")
    counts: ImageCounts
    latest_match: LatestMatchRef | None
    warnings: list[WarningItem] = Field(default_factory=list)
    #: ★ Provenance for a CAPTURED FRAME (the VIDEO feature). Both null for a normal
    #: upload; set when this image was captured from a video at a given second.
    source_video_id: UUID | None = Field(
        default=None, description="The video this frame was captured from, or null."
    )
    source_video_time_s: float | None = Field(
        default=None, description="The second within that video, or null."
    )
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ImageSummary(ApiModel):
    """List projection — endpoint 10. Omits ``variants``, ``metadata``, ``exif``."""

    id: UUID
    project_id: UUID
    filename: str
    status: ImageStatus
    width: int
    height: int
    size_bytes: int
    is_geotiff: bool
    thumbnail_url: str | None
    annotation_count: int
    gcp_count: int
    #: ★ Present so a list can badge captured frames without a per-row read. Null for a
    #: normal upload (the VIDEO feature).
    source_video_id: UUID | None = None
    source_video_time_s: float | None = None
    captured_at: datetime | None
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime


class ImageListParams(ListParams):
    """``GET /images`` — endpoint 10."""

    project_id: UUID | None = None
    status: str | None = Field(default=None, description="CSV of ImageStatus.")
    is_geotiff: bool | None = None
    q: str | None = Field(default=None, description="Free-text over filename + notes.")
    include_deleted: bool = False


class ThumbnailParams(ApiModel):
    """``GET /images/{image_id}/thumbnail`` — endpoint 13.

    ★ Serves a **stored variant**, not an on-demand resize. That is what keeps
    this endpoint on the right side of L5: "one thumbnail downsample" is the
    documented ceiling for a request handler, and ingest already materialised
    these.
    """

    size: ThumbnailSize = ThumbnailSize.MEDIUM
    format: ImageFormat = ImageFormat.WEBP


# ── GET /images/{image_id}/metadata — endpoint 14 ─────────────────────────────


class FileMetadata(ApiModel):
    """The bytes as they arrived."""

    filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str


class RasterMetadata(ApiModel):
    """What GDAL says the raster is."""

    width: int
    height: int
    band_count: int
    dtype: str
    color_interpretation: list[str]
    has_alpha: bool


class GeoTiffMetadata(ApiModel):
    """Present iff ``ImageRead.is_geotiff``.

    ★ ``geotransform`` is **GDAL order** ``[c, a, b, f, d, e]``, i.e.
    ``(origin_x, pixel_width, row_rotation, origin_y, col_rotation,
    pixel_height)`` with ``pixel_height`` negative for north-up rasters. Its
    columns are pixel **EDGES** while our pixel coordinates are **CENTRES**; the
    bridge is ``col_gdal = u_cv + 0.5`` and it belongs to ``gis.tiles``, not to a
    consumer of this payload (§6.1).
    """

    crs: str | None
    geotransform: list[float] | None = Field(default=None, min_length=6, max_length=6)
    bounds: list[float] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="[min_lon, min_lat, max_lon, max_lat] in EPSG:4326.",
    )
    gsd_m: float | None = Field(default=None, description="★ TRUE ground metres per pixel.")
    nodata: float | None
    overview_count: int


class CaptureMetadata(ApiModel):
    """When and how it was shot."""

    captured_at: datetime | None
    orientation: int | None = Field(
        default=None, description="★ The ORIGINAL EXIF orientation tag, preserved verbatim."
    )
    orientation_normalized: bool


class DerivedMetadata(ApiModel):
    """What ingest produced."""

    variants: list[ImageVariant]
    histogram_url: str | None


class ImageMetadataRead(ApiModel):
    """``GET /images/{image_id}/metadata`` — endpoint 14."""

    id: UUID
    image_id: UUID
    file: FileMetadata
    raster: RasterMetadata
    camera: CameraMetadata
    gps: GpsMetadata | None
    capture: CaptureMetadata
    geotiff: GeoTiffMetadata | None
    derived: DerivedMetadata
    exif: dict[str, Any] = Field(default_factory=dict, description="The verbatim EXIF block.")
    metadata: dict[str, Any] = META_FIELD
    warnings: list[WarningItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
