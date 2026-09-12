"""Settings — the single source of truth for configuration (CONTRACT.md §9).

**L10: every field has a working default. ``Settings()`` with a totally empty
environment NEVER raises.** There are zero required environment variables. That is
not a convenience; it is what makes ``docker compose up`` with no ``.env`` yield a
working satellite search via the keyless Esri provider (L2), and it is asserted by
``test_settings_zero_env``.

Every backend variable is ``LE_``-prefixed, because ``env_prefix`` is declared here
once and an unprefixed ``AUTH_MODE`` in a shared shell is a collision waiting to
happen (§12 C-05). ``20-api.md``'s unprefixed names and ``40-imagery.md``'s
``IMAGERY_PROVIDER`` are void.

★ **This is the only module in the backend permitted to read the environment.**
CI greps for ``os.getenv`` outside it (§13.1). Everything else takes a ``Settings``.
"""

from __future__ import annotations

import re
import secrets
from functools import lru_cache
import os
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = [
    "AuthMode",
    "CacheBackendName",
    "ElevationProviderName",
    "Environment",
    "LogFormat",
    "LogLevel",
    "Settings",
    "StorageBackend",
    "get_settings",
    "redact_url",
]

# ── Value-space aliases ────────────────────────────────────────────────────────
# Literals, not enums: core/constants.py is the sole home of JobStage, and the
# paired DB/wire enums live in IU-16/IU-17 (§3). A config field's value space is
# neither of those things.

Environment = Literal["development", "staging", "production"]
LogFormat = Literal["json", "console"]
LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]
AuthMode = Literal["none", "api_key", "bearer", "cookie"]
StorageBackend = Literal["local", "s3"]
CacheBackendName = Literal["memory", "disk", "redis"]
ElevationProviderName = Literal["none", "dem_run", "local_dem", "copernicus_dem"]

# ★ A CSV env var, not a JSON one.
#
# pydantic-settings decodes any "complex" field (list, dict, ...) by running
# json.loads over the raw environment string BEFORE validators run, and raises
# SettingsError when that fails. §9 spells these defaults as CSV
# ("http://localhost:5173,http://localhost:8080"), and an operator will type CSV.
# NoDecode suppresses the JSON step so the before-validator below sees the raw
# string. Without it, LE_CORS_ORIGINS=http://a,http://b is a boot crash.
CsvList = Annotated[list[str], NoDecode]

# ★ Two details here are load-bearing; both were bugs before they were comments.
#
# 1. The username is `*`, not `+`. A Redis URL carrying a password has NO username:
#    `redis://:hunter2@redis:6379/0` is the standard form, and it is exactly the
#    shape §9.4's LE_REDIS_URL (a § secret) takes with an authenticated Redis. `+`
#    matches the postgres form and silently misses the redis one — i.e. the password
#    survives into the logs of the one dependency whose URL is most often pasted
#    into a compose file.
#
# 2. The password is `[^/\s]*` (greedy), not `[^/@\s]*`. A password containing an
#    unencoded `@` — which RFC 3986 forbids and operators produce anyway — otherwise
#    matches only up to the FIRST `@`, redacting `p@ss` to `***@ss` and leaving a
#    fragment of the secret in the line. Greedy backtracks to the LAST `@`, which is
#    the host delimiter.
_URL_CREDENTIALS_RE: Final = re.compile(r"(?<=://)([^/@\s:]*):([^/\s]*)@")

_ESRI_BASE: Final = "https://services.arcgisonline.com/ArcGIS/rest/services"


def redact_url(url: str) -> str:
    """Strip the password out of a URL so it is safe to log or return.

    ``postgresql+psycopg://le:hunter2@db:5432/le`` -> ``postgresql+psycopg://le:***@db:5432/le``

    Used by ``core.logging``'s scrubber and by ``/health/ready``'s per-dependency
    diagnosis, which names the database it could not reach — and must not name the
    password it used to try.
    """
    return _URL_CREDENTIALS_RE.sub(r"\1:***@", url)


def _split_csv(value: Any) -> Any:
    """Parse a CSV env var into a list, tolerating whitespace and empties."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Every backend setting, with a working default for every one of them.

    Fields are grouped and ordered to mirror §9's tables so the two can be diffed by
    eye. ``.env.example`` (IU-30) is generated from §9 and CI asserts it matches.
    """

    model_config = SettingsConfigDict(
        env_prefix="LE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # ★ MUST be "ignore", not "forbid".
        # §9.12's compose vars are LE_-prefixed but are NOT Settings fields:
        # LE_WEB_PORT, LE_WORKER_CV_REPLICAS, LE_WORKER_IO_REPLICAS,
        # LE_WORKER_EXPORT_REPLICAS. They are read by compose, and compose exports
        # them into the API container's environment. With extra="forbid", the
        # documented `docker compose up` path would raise on boot — L10's exact
        # failure, triggered by the contract's own compose file.
        extra="ignore",
        validate_default=True,
    )

    # ── 9.1 Core ───────────────────────────────────────────────────────────────
    env: Environment = "development"
    debug: bool = False
    app_name: str = "LandExplorer"
    api_prefix: str = "/api/v1"
    api_host: str = "0.0.0.0"  # noqa: S104 — binding a container to loopback serves nobody.
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_workers: int = Field(default=2, ge=1)
    cors_origins: CsvList = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"
    request_id_header: str = "X-Request-ID"
    # § secret. Ephemeral per boot, which is SAFE ONLY BECAUSE AUTH IS OFF BY
    # DEFAULT. With LE_AUTH_MODE != none and multiple replicas, an unset key means
    # each replica mints a different one — set it explicitly in that deployment.
    secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(48)))
    testing: bool = False
    enable_docs: bool = True
    read_only: bool = False

    # ── 9.2 Auth (off by default) ──────────────────────────────────────────────
    auth_mode: AuthMode = "none"
    access_token_ttl_seconds: int = Field(default=3600, ge=1)
    # § secret. CSV of HASHED keys (sha256 hex) — never plaintext. See core.security.
    api_keys: CsvList = Field(default_factory=list)
    jwks_url: str = ""
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = Field(default=600, ge=1)

    # ── 9.3 Database ───────────────────────────────────────────────────────────
    # § secret (the password is embedded). `db` resolves inside compose; on a bare
    # host you must set this. Deliberate trade: optimise for the documented happy
    # path and make the bare-host failure legible via /health/ready rather than a
    # boot traceback.
    database_url: str = "postgresql+psycopg://landexplorer:landexplorer@db:5432/landexplorer"
    # § secret. Empty => same as database_url (resolved in _resolve_derived_urls).
    # A distinct superuser role in prod: migrations need CREATE EXTENSION; the app
    # does not, and should not have it.
    migration_database_url: str = ""
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: int = Field(default=30, ge=1)
    db_echo: bool = False
    db_statement_timeout_ms: int = Field(default=30_000, ge=0)
    db_auto_migrate: bool = False

    # ── 9.4 Redis / Celery ─────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"  # § secret
    celery_broker_url: str = ""  # § secret. Empty => redis_url.
    celery_result_backend: str = ""  # § secret. Empty => redis_url on logical db 1.
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = Field(default=2, ge=1)
    # Soft => catchable => the job is marked `failed` cleanly rather than vanishing.
    celery_task_soft_time_limit: int = Field(default=600, ge=1)
    celery_task_time_limit: int = Field(default=900, ge=1)
    celery_prefetch_multiplier: int = Field(default=1, ge=1)
    celery_acks_late: bool = True
    job_max_attempts: int = Field(default=3, ge=1)
    job_retry_backoff_seconds: int = Field(default=5, ge=0)
    job_retry_backoff_max_seconds: int = Field(default=120, ge=0)
    job_result_ttl_seconds: int = Field(default=86_400, ge=0)
    job_stale_after_seconds: int = Field(default=1_800, ge=1)
    job_progress_ttl_seconds: int = Field(default=3_600, ge=0)
    job_retention_days: int = Field(default=30, ge=1)

    # ── 9.5 Storage & uploads ──────────────────────────────────────────────────
    storage_backend: StorageBackend = "local"
    # ★ Must be a volume SHARED across api + workers. The API writes the upload; a
    # worker reads it back to thumbnail it. Two separate container filesystems here
    # is the classic "works on my machine, FileNotFoundError in compose".
    storage_local_root: Path = Path("./data/storage")
    storage_s3_bucket: str = ""
    storage_s3_endpoint_url: str = ""  # set for MinIO
    storage_s3_region: str = "us-east-1"
    storage_s3_access_key_id: SecretStr = SecretStr("")  # § secret
    storage_s3_secret_access_key: SecretStr = SecretStr("")  # § secret
    storage_signed_url_ttl_seconds: int = Field(default=900, ge=1)
    # Checked BEFORE streaming an upload, not after: discovering you are out of disk
    # having already written 400 MB helps nobody. -> 507 INSUFFICIENT_STORAGE.
    storage_min_free_bytes: int = Field(default=2_147_483_648, ge=0)
    #: ★ 4 GB. Raised from 500 MB because DEMs are the outlier: a photograph is
    #: tens of megabytes, but one FABDEM/Copernicus tile at 1 m over a survey area
    #: is routinely 600 MB-2 GB, and refusing it with "request failed" made the DEM
    #: page unusable for exactly the data it exists to process. The upload is
    #: STREAMED to disk in 1 MB chunks (`DemService._spool`), never buffered whole,
    #: so the ceiling costs disk, not RAM. Matches the nginx `client_max_body_size
    #: 4g` the deployment config already sets.
    #: ★ Where captured video frames are ALSO written as plain files, so the same
    #: photograph can be reused across projects (or any other tool) without digging
    #: in the app's storage tree. `~` expands to the user running the API — in the
    #: desktop app, that is the surveyor's own laptop. Empty/unset disables the copy.
    #: The write is BEST-EFFORT: a full disk or missing permission must never fail
    #: the capture itself (the project row is the work product; this is a courtesy).
    capture_export_dir: Path | None = Path("~/Pictures/LandExplorer")

    #: ★ The processed-DEM twin of `capture_export_dir`: every successful DEM
    #: pipeline run also drops its output GeoTIFF (plus a small metadata sidecar)
    #: here, so a cropped+reprojected tile can be reused across projects without
    #: re-processing. Same contract: user-owned folder, best-effort writes, empty
    #: disables.
    dem_library_dir: Path | None = Path("~/Documents/LandExplorer/DEMs")

    upload_max_bytes: int = Field(default=4_294_967_296, ge=1)  # 4 GB
    # ★ SNIFFED, never trusted from the Content-Type header.
    upload_allowed_mime: CsvList = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/tiff", "image/webp"]
    )
    # ★ VIDEO upload allow-list, mirroring ``upload_allowed_mime``. A field VIDEO is a
    # FRAME SOURCE: the surveyor scrubs it in the browser and captures a second as a
    # normal photo (server-side OpenCV decode). mp4/mov/avi/mkv are exactly the
    # containers cv2's FFMPEG backend decodes and that browsers often cannot.
    upload_allowed_video_mime: CsvList = Field(
        default_factory=lambda: [
            "video/mp4",
            "video/quicktime",
            "video/x-msvideo",
            "video/x-matroska",
            # ★ Broadened (1.2.6): more of the containers cv2's FFMPEG backend
            #   decodes, so a drone / action-cam file is not rejected before OpenCV —
            #   the authoritative gate — even gets to look at it.
            "video/webm",
            "video/mpeg",
            "video/mp2t",
            "video/x-ms-wmv",
            "video/x-flv",
            "video/3gpp",
        ]
    )
    max_image_pixels: int = Field(default=400_000_000, ge=1)  # decompression-bomb guard
    max_image_dim: int = Field(default=65_535, ge=1)
    async_ingest_threshold_bytes: int = Field(default=52_428_800, ge=0)
    use_sendfile: bool = False  # X-Accel-Redirect in prod

    # ── 9.6 Imagery ────────────────────────────────────────────────────────────
    # `auto` = PREFERENCE: walk the chain, take the first is_configured() provider.
    # An explicit name = THAT provider, with the chain as error-recovery only.
    imagery_provider: str = "auto"
    # local_orthophoto FIRST: mounted orthophotos are definitionally better than any
    # web tile source. It self-skips via is_configured() when the dir is empty.
    # ★ mapbox_satellite SECOND: the provider carries the product's built-in public
    #   token (gis mapbox provider), so a zero-config machine lands on Mapbox — the
    #   product's chosen imagery — not on the retired Esri. Esri stays LAST as the
    #   keyless imagery of last resort (L2's spirit: a bare machine still draws a map
    #   even if the built-in token is ever revoked).
    imagery_fallback_chain: CsvList = Field(
        default_factory=lambda: ["local_orthophoto", "mapbox_satellite", "esri_world_imagery"]
    )
    # false => tile_url_template is the proxy path for EVERY provider, preserving the
    # ToS chokepoint, the shared quota bucket, and worker/browser cache identity.
    imagery_direct_tile_urls: bool = False
    imagery_strict: bool = False  # true in prod: no silent fallback
    allowed_providers: CsvList = Field(default_factory=list)  # empty = all registered
    imagery_offline: bool = False  # true => only local_orthophoto + fixture
    # redis in prod: tile fetching happens inside Celery workers and a disk cache in
    # a container is per-replica — four workers on one AOI would fetch every tile
    # four times.
    imagery_tile_cache_backend: CacheBackendName = "disk"
    imagery_tile_cache_dir: Path = Path("./data/tile_cache")
    # 30 d. ★ Several providers' ToS cap caching — see docs/legal/imagery-terms.md.
    imagery_tile_cache_ttl_seconds: int = Field(default=2_592_000, ge=0)
    imagery_tile_cache_max_bytes: int = Field(default=21_474_836_480, ge=0)  # 20 GB LRU
    # ★ How long "the provider has no imagery here" (ocean, coverage gap) is remembered.
    #   Short on purpose: gaps get filled, and a permanent negative hides new imagery.
    imagery_negative_tile_cache_ttl_seconds: int = Field(default=86_400, ge=0)
    # ★ DESKTOP-FRIENDLY MAINTENANCE. The packaged app has no Celery beat, so the API
    #   process itself sweeps the disk cache: once at startup and then periodically.
    #   0 disables the periodic sweep (server deployments where beat owns it).
    imagery_tile_cache_sweep_on_startup: bool = True
    imagery_tile_cache_sweep_interval_seconds: int = Field(default=3_600, ge=0)
    # ── Automatic viewport caching ─────────────────────────────────────────────
    # ★ Continuously caches the area the surveyor is actively working in — DISTINCT
    #   from the manual Offline Area Manager (deliberate AOI preparation). Both feed
    #   the SAME tile cache; these knobs only govern the automatic feeder, which is
    #   deliberately capped far tighter than a manual download.
    imagery_auto_cache_enabled: bool = True
    imagery_auto_cache_prefetch_viewports: int = Field(default=1, ge=0, le=3)
    # current_only | current_plus_one | current_plus_minus_one | full_detail.
    # ★ full_detail: once zoomed to FULL_DETAIL_MIN_ZOOM or deeper, ALSO cache every
    #   deeper zoom of the visible area up to AUTO_CACHE_MAX_ZOOM — filled
    #   PROGRESSIVELY in per-viewport chunks (visible zoom first, then shallow→deep),
    #   bounded by the session caps. Below the gate it behaves as current_only,
    #   because a wide viewport × every zoom is millions of tiles.
    imagery_auto_cache_zoom_range: str = "full_detail"
    imagery_auto_cache_full_detail_min_zoom: int = Field(default=15, ge=0, le=24)
    # ★ z19 = where Mapbox's NATIVE detail ends. z20–22 are served but upsampled —
    #   ~21× the tiles for zero new information (the operator chose this ceiling
    #   deliberately; raise it only if you truly want interpolated deep tiles).
    imagery_auto_cache_max_zoom: int = Field(default=19, ge=0, le=24)
    imagery_auto_cache_concurrency: int = Field(default=4, ge=1, le=16)
    # ★ The CHUNK size per settled viewport — full-detail areas fill in these chunks.
    imagery_auto_cache_max_tiles_per_viewport: int = Field(default=500, ge=0)
    imagery_auto_cache_max_tiles_per_session: int = Field(default=20_000, ge=0)
    # 0 = no per-session byte cap (the global cache size/TTL still applies).
    imagery_auto_cache_max_session_bytes: int = Field(default=2_147_483_648, ge=0)  # 2 GB
    imagery_max_concurrent_fetches: int = Field(default=4, ge=1)
    imagery_rate_limit_rps: float = Field(default=5.0, gt=0)
    imagery_request_timeout_seconds: float = Field(default=15.0, gt=0)
    imagery_max_retries: int = Field(default=3, ge=0)
    # ★ Operators should set a real contact address. An anonymous scraper is how a
    # keyless provider decides to block the whole user agent.
    imagery_user_agent: str = "LandExplorer/1.0 (+https://example.invalid)"

    # Esri — the keyless default (L2). ★ Note the {z}/{y}/{x} order: Esri is NOT
    # {z}/{x}/{y}, and the transposition yields plausible-looking wrong tiles.
    esri_imagery_tile_url_template: str = f"{_ESRI_BASE}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}"
    esri_reference_tile_url_template: str = (
        f"{_ESRI_BASE}/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}"
    )
    esri_terrain_tile_url_template: str = f"{_ESRI_BASE}/World_Terrain_Base/MapServer/tile/{{z}}/{{y}}/{{x}}"
    esri_max_zoom: int = Field(default=19, ge=0, le=24)
    esri_rate_limit_rps: float = Field(default=8.0, gt=0)

    local_ortho_dir: Path = Path("./data/orthophotos")  # empty dir => unavailable, no crash
    local_ortho_attribution: str = "Local orthophoto"
    local_ortho_reindex_seconds: int = Field(default=300, ge=0)
    # false ON PURPOSE: black is a legitimate pixel value, and guessing it is nodata
    # silently punches holes in a real orthophoto.
    local_ortho_assume_black_nodata: bool = False

    mapbox_access_token: SecretStr = SecretStr("")  # § secret; empty => not offered
    mapbox_style_id: str = "mapbox.satellite"
    # ★ Read at RUNTIME by MapboxSatelliteProvider (via the LE_ env var this field mirrors)
    #   and consulted on every cache write — the global 30-day TTL is never assumed
    #   compliant for Mapbox. VERIFY against the current ToS.
    mapbox_cache_ttl_seconds: int = Field(default=2_592_000, ge=0)
    mapbox_negative_cache_ttl_seconds: int = Field(default=86_400, ge=0)
    mapbox_rate_limit_rps: float = Field(default=10.0, gt=0)
    # ★ PRE-CACHE BUDGETS. Per-operation caps are enforced by OfflineCacheService before
    #   a download starts; the per-day cap is enforced against the persisted upstream
    #   counter as the download runs. 0 = unlimited.
    mapbox_max_tile_requests_per_operation: int = Field(default=20_000, ge=0)
    mapbox_max_prefetch_tiles: int = Field(default=50_000, ge=0)
    mapbox_max_tile_requests_per_day: int = Field(default=0, ge=0)
    bing_maps_key: SecretStr = SecretStr("")  # § secret
    bing_imagery_set: str = "Aerial"
    copernicus_client_id: SecretStr = SecretStr("")  # § secret
    copernicus_client_secret: SecretStr = SecretStr("")  # § secret
    copernicus_max_cloud_pct: int = Field(default=20, ge=0, le=100)
    # ★ REFUSES zoom > 15 rather than serving upsampled mush that a matcher would
    # confidently act on (L12).
    sentinel_max_zoom: int = Field(default=15, ge=0, le=24)
    google_maps_static_key: SecretStr = SecretStr("")  # § secret
    # ★ DOUBLE OPT-IN: the key alone is insufficient. The operator must assert their
    # own ToS coverage. Google EARTH is never a provider.
    google_tos_acknowledged: bool = False

    # ── 9.6a Elevation ─────────────────────────────────────────────────────────
    # `none` is KEYLESS, OFFLINE and TERMINAL: elevation_m and elevation_source are
    # both NULL and the job says ELEVATION_UNAVAILABLE. Honest beats absent.
    elevation_provider: ElevationProviderName = "none"
    local_dem_dir: Path = Path("./data/dem")
    # ★ `dem_run` — the DEM processed on the DEM page. The surface the surveyor cropped,
    #   reprojected and inspected is the surface their control points are measured
    #   against. Written by `dem_service` on an adopted run; sampled by `gis.elevation`.
    active_dem_path: Path = Path("./data/dem/active_dem.tif")
    # ★ PER-PROJECT DEMs, which take precedence over the global one. A survey is an area,
    #   and the right elevation surface for it is a property OF that area — two projects
    #   on two sites have no business sharing one DEM. Named `{project_id}.tif`.
    project_dem_dir: Path = Path("./data/dem/projects")
    # ★ LUT bundles (`app.vendor.lut_generator`): one folder per built site —
    #   `<site>_lut/` with lat.npy + lon.npy + manifest + pi_lookup, plus the .zip.
    lut_output_dir: Path = Path("./data/lut")
    # ★ ACCURACY CHECKS (`app.vendor.geo_accuracy`): one folder per photograph,
    #   `<image_id>/` holding the Stage D measurement, the satellite mosaic it matched
    #   against, the correction JSON and the offline HTML report. Like the LUT bundles,
    #   the FOLDER is the durable record — runs are tracked in memory and a restart
    #   loses only the progress bar, never the result.
    accuracy_output_dir: Path = Path("./data/accuracy")
    # ★ OBJECT DETECTION over live streams (`app.services.detection`): where the
    #   YOLO weights live. LOCAL FILES ONLY — a missing file is refused with its path
    #   named, never fetched from the network: this is an offline product, and a model
    #   that downloads itself mid-survey is a hang on a field laptop with no uplink.
    detection_model_dir: Path = Path("./data/models")
    # ★ CAMERA DESIRED STATE (2026-09-02): a few seconds after boot the API walks the
    #   `cameras` table and restarts every drift watch, detection run and data feed
    #   the operator left running (`camera_service.reconcile_at_boot`). Off = the
    #   registry is still served, nothing is auto-started (a bench machine that
    #   shares a database with the field unit, say).
    cameras_reconcile_at_boot: bool = True
    # ★ CAMERA DRIFT references (`app.vendor.drift_monitor`): one folder per frozen
    #   reference — `<ref_id>/` holding landmarks.npz (the templates + trusted pose)
    #   and reference.json (what the UI lists). Like the LUT bundles, the FOLDER is
    #   the durable record; monitoring state is in memory and a restart loses only
    #   the current verdict, never the reference.
    drift_output_dir: Path = Path("./data/drift")

    #: ★ DESKTOP / SINGLE-ORIGIN MODE. When set (LE_SERVE_FRONTEND_DIR), the API also
    #: serves the built SPA from this directory: `/` and every non-API path fall back
    #: to its `index.html`, hashed assets are served as files. None (the default)
    #: keeps the API pure — the dev flow (vite on :5173) is untouched.
    serve_frontend_dir: Path | None = None
    #   The vertical CE90 to report for it. An ASSUMPTION and a claim, not a label: it
    #   lands in every GCP's `elevation_ce90_m`. Default is Copernicus GLO-30's figure;
    #   a drone DTM is ~0.1 m and an operator who knows theirs should set it.
    active_dem_ce90_m: float = Field(default=6.6, ge=0.0)
    copernicus_dem_url: str = ""
    elevation_cache_ttl_seconds: int = Field(default=2_592_000, ge=0)

    # ── 9.7 Search ─────────────────────────────────────────────────────────────
    search_default_zoom: int = Field(default=18, ge=0, le=24)
    search_default_radius_m: float = Field(default=1_000.0, gt=0)
    # ★ Place-name geocoder (endpoint: GET /imagery/geocode). Keyless OpenStreetMap
    #   Nominatim by default — the same "online to prepare, offline to survey" posture as
    #   the satellite tiles. Needs the internet; when `imagery_offline` it is refused.
    geocode_url: str = "https://nominatim.openstreetmap.org/search"
    geocode_max_results: int = Field(default=8, ge=1, le=25)
    search_max_radius_m: float = Field(default=50_000.0, gt=0)
    search_max_candidates: int = Field(default=25, ge=1)
    search_window_size_px: int = Field(default=1_024, ge=64)
    # ★ 0.5 buys the 512 px footprint guarantee (§4.19). At 0.25 the guarantee is
    # only 256 px, and the matching design reasons from 512.
    search_overlap_ratio: float = Field(default=0.5, ge=0.0, lt=1.0)
    search_target_gsd_m: float = Field(default=0.5, gt=0)
    max_tiles_per_job: int = Field(default=512, ge=1)
    max_static_tiles: int = Field(default=16, ge=1)  # endpoint 53 is a request, not a job
    max_static_pixels: int = Field(default=4_194_304, ge=1)  # 4 MP; a 64 MP stitch in a GET is L5's forbidden workload
    search_max_bbox_area_km2: float = Field(default=2_500.0, gt=0)
    exif_radius_inflation: float = Field(default=3.0, gt=0)
    exif_min_radius_m: float = Field(default=250.0, ge=0)

    # ── 9.8 AI engine ──────────────────────────────────────────────────────────
    # ★ SCOPE.md: the automatic matching engine is DEFERRED in this build. These
    # settings are still declared and still plumbed into AiEngineConfig exactly as
    # §9.8 specifies — the seam is real, not decorative, and re-enabling the engine
    # must require zero changes outside ai_engine/ (SCOPE.md §7). They select which
    # component would be resolved; in this build every deep path resolves to
    # deferred. Deleting them now is the change that would make SCOPE.md §7 false.
    ai_extractor: str = "sift"  # L1 default
    ai_matcher: str = "flann"
    ai_detector_free: str = ""  # empty => no LoFTR
    ai_segmenter: str = "classical"
    ai_suggester: str = "classical_suggester"
    # ★ Two env vars, two concepts, no overlap. `ransac_method` is a robust-fit
    # METHOD (a HomographyMethod value); `estimator_backend` is a component REGISTRY
    # KEY. LE_AI_ESTIMATOR is DELETED: it conflated them and was a zero-env boot
    # crash (it fed `usac_magsac` — not a registry key — to ComponentKind.ESTIMATOR,
    # which found no spec, found no fallback, and raised ComponentUnavailable at
    # preflight on an empty environment).
    ai_ransac_method: str = "usac_magsac"
    ai_estimator_backend: str = "opencv"  # the only registered one
    ai_allow_deep_models: bool = True
    # ★ true => missing weights RAISE instead of falling back. CI accuracy suites
    # only. true in prod violates L1.
    ai_strict_backend: bool = False
    # Empty by default AND THAT IS THE SUPPORTED STATE.
    ai_model_weights_dir: Path = Path("./data/model_weights")
    # ★ `auto` takes the NVIDIA GPU whenever torch.cuda.is_available() — which needs
    # a CUDA torch wheel (build-runtime.sh installs cu130 when the driver is ≥ 580)
    # AND a driver that serves it. NEVER infer CUDA from a build name: check at run
    # time, as `detection.detector.resolve_device` does.
    ai_device: str = "auto"
    ai_torch_threads: int = Field(default=0, ge=0)  # 0 = leave torch's default
    ai_deterministic_seed: int = 42  # RANSAC reproducibility
    ai_max_features: int = Field(default=8_000, ge=1)
    ai_clahe_enabled: bool = True  # big win on hazy field photos
    ai_ratio_test: float = Field(default=0.75, gt=0, le=1.0)  # Lowe
    ai_cross_check: bool = True
    ai_min_matches: int = Field(default=10, ge=0)
    ai_ransac_threshold_px: float = Field(default=3.0, gt=0)
    ai_ransac_max_iters: int = Field(default=10_000, ge=1)
    ai_ransac_confidence: float = Field(default=0.999, gt=0, lt=1.0)
    ai_min_inliers: int = Field(default=12, ge=4)  # H1. A homography needs >= 4.
    # 0-100. Below => candidate dropped. Refusing to answer beats a confident wrong
    # coordinate (L12).
    ai_min_confidence: float = Field(default=40.0, ge=0.0, le=100.0)
    ai_rank_margin: float = Field(default=10.0, ge=0.0, le=100.0)
    ai_max_results: int = Field(default=5, ge=1)
    ai_score_weight_feature: float = Field(default=0.25, ge=0.0, le=1.0)
    ai_score_weight_geometric: float = Field(default=0.35, ge=0.0, le=1.0)
    ai_score_weight_landmark: float = Field(default=0.30, ge=0.0, le=1.0)
    ai_score_weight_semantic: float = Field(default=0.10, ge=0.0, le=1.0)
    ai_calibration_id: str = "identity"  # ships uncalibrated and says so
    ai_semantics_enabled: bool = False  # off: SAM is heavy and weight-dependent
    ai_deep_max_candidates: int = Field(default=8, ge=1)  # code-enforced; CPU-only reality
    ai_sam_checkpoint: str = ""
    ai_superpoint_weights: str = ""
    ai_superglue_weights: str = ""
    ai_lightglue_weights: str = ""
    ai_loftr_weights: str = ""
    ai_dinov2_weights: str = ""
    # ★ NOT in §9.8's table, but MANDATED by §11.1's ruling: preflight runs exactly
    # once and the PreflightReport is cached on app.state, because re-sha256'ing a
    # 2.4 GB SAM checkpoint per /capabilities call is not a health check, it is an
    # outage. 0 = cache for the process lifetime. Non-zero exists for operators who
    # mount a weights volume live; otherwise download_models.py needs a restart.
    ai_preflight_ttl_seconds: int = Field(default=0, ge=0)

    # ── 9.9 Limits, exports, misc ──────────────────────────────────────────────
    max_annotations_per_image: int = Field(default=2_000, ge=1)
    max_batch_files: int = Field(default=100, ge=1)
    max_batch_bytes: int = Field(default=2_147_483_648, ge=1)
    max_replay_events: int = Field(default=5_000, ge=1)
    checkpoint_every_n_events: int = Field(default=50, ge=1)
    gcp_consistency_tolerance_m: float = Field(default=0.5, ge=0)
    gcp_bounds_slack_m: float = Field(default=100.0, ge=0)
    geotiff_disagreement_m: float = Field(default=50.0, ge=0)
    project_names_unique: bool = False
    export_dir: Path = Path("./data/storage/exports")
    export_formats: CsvList = Field(
        default_factory=lambda: ["csv", "geojson", "kml", "kmz", "shapefile", "gpkg", "dxf", "pdf"]
    )
    export_default_srid: int = Field(default=4326, ge=1024, le=32767)
    export_ttl_seconds: int = Field(default=604_800, ge=0)
    export_max_rows: int = Field(default=100_000, ge=1)
    # ★ Should not be turned off: several providers' ToS REQUIRE attribution on
    # derived output. This is a legal obligation, not a display preference.
    export_include_attribution: bool = True

    # ── 9.10 Observability ─────────────────────────────────────────────────────
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"  # NOT under /api/v1; not part of the public contract
    sentry_dsn: SecretStr = SecretStr("")  # § secret; empty => not initialised
    otel_exporter_otlp_endpoint: str = ""  # empty => no-op tracer
    otel_service_name: str = "landexplorer-api"

    # ── Validators ─────────────────────────────────────────────────────────────

    @field_validator(
        "cors_origins",
        "api_keys",
        "upload_allowed_mime",
        "upload_allowed_video_mime",
        "imagery_fallback_chain",
        "allowed_providers",
        "export_formats",
        mode="before",
    )
    @classmethod
    def _parse_csv(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: Any) -> Any:
        """Accept `debug`, `Debug`, `DEBUG`. Nobody should lose an evening to a case."""
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("env", "log_format", "auth_mode", "storage_backend", mode="before")
    @classmethod
    def _normalise_lower(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("api_prefix", "metrics_path", mode="before")
    @classmethod
    def _normalise_path(cls, value: Any) -> Any:
        """Guarantee a leading slash and no trailing one, so callers can concatenate."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return value
        if not value.startswith("/"):
            value = "/" + value
        return value.rstrip("/") or "/"

    @model_validator(mode="after")
    def _resolve_derived_urls(self) -> Settings:
        """Fill the two vars whose documented default is 'the value of another var'.

        §9.3/§9.4 spell these as *(= LE_DATABASE_URL)* / *(= LE_REDIS_URL)*. Resolving
        them here rather than at each read site means ``settings.celery_broker_url`` is
        always the effective value, and IU-16's alembic/env.py and IU-20's celery_app
        cannot disagree about what the fallback was.
        """
        if not self.migration_database_url:
            # object.__setattr__ is not needed (the model is mutable), but assigning
            # inside an `after` validator does not re-trigger validation, which is
            # what we want: these are already-validated strings.
            self.migration_database_url = self.database_url
        if not self.celery_broker_url:
            self.celery_broker_url = self.redis_url
        if not self.celery_result_backend:
            # Derive from redis_url on logical db 1, so results never share the broker's db
            # and a bare-metal operator who set only LE_REDIS_URL is not left pointing at the
            # compose-only `redis` hostname.
            base = self.redis_url.rsplit("/", 1)[0] if "/" in self.redis_url.split("://", 1)[-1] else self.redis_url
            self.celery_result_backend = f"{base}/1"
        return self

    @model_validator(mode="after")
    def _production_forces_debug_off(self) -> Settings:
        """LE_DEBUG is forced false when LE_ENV=production (§9.1).

        Silently, and without complaint. Debug mode puts exception reprs into the
        error envelope's ``details``, and a traceback carries storage paths,
        connection strings and provider keys (§6.3). An operator who sets
        LE_DEBUG=true in production has made a mistake; honouring it would be ours.
        """
        if self.env == "production":
            self.debug = False
        return self

    # ── Derived, read-only helpers ─────────────────────────────────────────────
    # Small and boring on purpose: every one of these is a question more than one
    # unit will ask, and the alternative is each of them re-deriving it slightly
    # differently.

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def auth_enabled(self) -> bool:
        """False on the default single-surveyor deployment.

        ★ The honest consequence (§9.2): with auth off, ``gcps.adjusted_by`` is
        `'anonymous'` and the DB can prove THAT a coordinate was adjusted and WHEN,
        but not BY WHOM. Acceptable for one surveyor; not acceptable for a
        multi-user deployment producing legal survey deliverables — which is why
        PATCH /gcps/{id} returns 401 the moment auth_mode != none and no principal
        resolves.
        """
        return self.auth_mode != "none"

    @property
    def docs_enabled(self) -> bool:
        """An internal survey tool benefits more from discoverable docs than it loses."""
        return self.enable_docs

    def redacted_database_url(self) -> str:
        """The database URL with its password removed — safe for logs and /health/ready."""
        return redact_url(self.database_url)

    def redacted_redis_url(self) -> str:
        """The Redis URL with its password removed — safe for logs and /health/ready."""
        return redact_url(self.redis_url)


def _mirror_env_file_into_environ(
    *, cwd_env: Path | None = None, backend_env: Path | None = None
) -> None:
    """Export ``.env``'s ``LE_*`` lines into ``os.environ`` (never overwriting real ones).

    ★ THE GAP THIS CLOSES. pydantic-settings reads ``.env`` into the ``Settings``
    OBJECT only — it never touches ``os.environ``. But the ``gis`` imagery providers
    read their credentials from ``os.environ`` directly (their constructors' documented
    fallback), because ``GisConfig`` deliberately carries no secrets and the registry
    constructs providers bare. Net effect before this fix: a key placed in
    ``backend/.env`` — exactly where README/RUNNING say to put it — reached ``Settings``
    and STOPPED, and every keyed provider (Google, Mapbox, Bing, Sentinel) reported
    ``configured: False`` while the operator stared at a key that was plainly set.

    ★ TWO files, because the API does not always run from ``backend/``. pydantic's
    ``env_file=".env"`` resolves against the CURRENT WORKING DIRECTORY, and the packaged
    desktop app runs the API from its writable app-data ``work/`` dir — ``backend/`` is
    inside a read-only installer image there, so ``work/.env`` is the only place a
    desktop user CAN put a key (installation.md §8 says exactly that). Mirroring only
    the source-anchored file reopened the original gap for that deployment: the key
    reached ``Settings`` and stopped. The cwd file is mirrored FIRST so that on a
    conflict ``os.environ`` agrees with what ``Settings`` itself loaded.

    Real environment variables win: ``setdefault`` only fills what the process was not
    already given, so container/systemd deployments that pass real env are untouched.

    Args:
        cwd_env: Overrides the cwd-anchored file. For tests.
        backend_env: Overrides the source-anchored file. For tests.
    """
    if backend_env is None:
        backend_env = Path(__file__).resolve().parents[2] / ".env"
    if cwd_env is None:
        cwd_env = Path.cwd() / ".env"
    seen: set[Path] = set()
    for env_file in (cwd_env, backend_env):
        resolved = env_file.resolve()
        if resolved in seen:  # dev runs from backend/, where the two are one file
            continue
        seen.add(resolved)
        try:
            text = env_file.read_text(encoding="utf-8")
        except OSError:
            continue  # no .env is a supported state (L10: every field has a default)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key.startswith("LE_"):
                continue
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide Settings singleton.

    Cached because reading and validating ~150 fields per request is pure waste, and
    because a Settings that could differ between two reads in one request is a bug
    farm. ``api.deps.get_settings`` depends on this; tests override it with
    ``get_settings.cache_clear()`` or by depending on their own instance.
    """
    _mirror_env_file_into_environ()
    return Settings()
