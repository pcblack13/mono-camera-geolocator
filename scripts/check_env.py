#!/usr/bin/env python3
"""Report this machine's capabilities, and generate/verify ``.env.example``.

Three jobs, one file, because they share one source of truth:

1. **Default** — print the ``CONTRACT.md`` §0.1 capability table *for the machine
   it is running on*, rather than for the machine the contract was written on.
   Nothing is assumed; every row is probed.
2. ``--emit-example`` — regenerate ``.env.example`` from :data:`ENV_SECTIONS`,
   which mirrors ``CONTRACT.md`` §9. CI asserts the two agree (§13.4 rules 7, 11):
   anything that mirrors a source of truth is generated or it drifts.
3. ``--require`` — assert named capabilities are present and exit non-zero if not.
   Run at Docker **build** time (§9.14, §14 F-56) so that an image which lost its
   raster backend fails the *build*, not a surveyor's export six weeks later.

**Stdlib only, and importable with every optional dependency absent.** This is the
one script whose job is to tell you what is missing; it must not need the thing it
is looking for. Probing is done with :func:`importlib.util.find_spec` first, so a
missing package costs nothing and an absent ``torch`` is never imported.

Run with no arguments for the table::

    python3 scripts/check_env.py
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import io
import os
import platform
import shutil
import subprocess
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT.md §9 — the env var table.
#
# ★ THIS IS THE GENERATOR INPUT FOR .env.example. If you add a variable to §9,
#   add it here and run `make check-env`. CI compares the emitted bytes against
#   the committed file (§13.4 rule 11).
#
# ★ EVERY VARIABLE HAS A WORKING DEFAULT AND EVERY LINE IS EMITTED COMMENTED OUT.
#   That is L10 made physical: `cp .env.example .env` is byte-equivalent to an
#   EMPTY .env, so copying the example can never break the zero-config boot and
#   can never pin a weak secret. §2.1: "Copying it is OPTIONAL."
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EnvVar:
    """One row of ``CONTRACT.md`` §9.

    Attributes:
        name: The variable name, exactly as §9 spells it.
        default: The literal default value. ``""`` means "empty is the default".
        consumer: The §9 "Consumer" column — who reads it, and any constraint.
        secret: §9's ``§`` marker. Never logged, never returned by an API,
            redacted in ``/health/ready``. Emitted with an empty value regardless
            of what §9 shows, so the example file can never leak a live default.
        default_note: Set when §9's default is not a literal value
            (e.g. "ephemeral random per boot"). Rendered instead of a value.
    """

    name: str
    default: str
    consumer: str
    secret: bool = False
    default_note: str = ""


@dataclass(frozen=True)
class EnvSection:
    """A §9 subsection, e.g. "9.6 Imagery"."""

    title: str
    vars: tuple[EnvVar, ...]
    note: str = ""


ENV_SECTIONS: tuple[EnvSection, ...] = (
    EnvSection(
        title="9.1 Core",
        vars=(
            EnvVar("LE_ENV", "development", "core.config — development|staging|production"),
            EnvVar("LE_DEBUG", "false", "core.config, main — forced false when LE_ENV=production"),
            EnvVar("LE_APP_NAME", "LandExplorer", "OpenAPI title"),
            EnvVar("LE_API_PREFIX", "/api/v1", "api.v1.router, nginx"),
            EnvVar("LE_API_HOST", "0.0.0.0", "entrypoint"),
            EnvVar("LE_API_PORT", "8000", "entrypoint, compose"),
            EnvVar("LE_API_WORKERS", "2", "entrypoint"),
            EnvVar(
                "LE_CORS_ORIGINS",
                "http://localhost:5173,http://localhost:8080",
                "main (CSV)",
            ),
            EnvVar("LE_LOG_LEVEL", "INFO", "core.logging"),
            EnvVar("LE_LOG_FORMAT", "json", "core.logging — json|console"),
            EnvVar("LE_REQUEST_ID_HEADER", "X-Request-ID", "api.middleware"),
            EnvVar(
                "LE_SECRET_KEY",
                "",
                "core.security — safe to leave unset BECAUSE AUTH IS OFF BY DEFAULT",
                secret=True,
                default_note="ephemeral random per boot",
            ),
            EnvVar(
                "LE_TESTING",
                "false",
                "core.config — set by conftest; enables fixture provider + eager Celery",
            ),
            EnvVar(
                "LE_ENABLE_DOCS",
                "true",
                "main — an internal survey tool benefits more from discoverable docs "
                "than it loses to disclosure",
            ),
            EnvVar("LE_READ_ONLY", "false", "api.deps — 403 READ_ONLY_MODE on every mutating route"),
        ),
    ),
    EnvSection(
        title="9.2 Auth (OFF by default)",
        note=(
            "The honest consequence: with LE_AUTH_MODE=none, gcps.adjusted_by = 'anonymous'.\n"
            "The database can prove THAT a coordinate was adjusted and WHEN, but not BY WHOM.\n"
            "Acceptable for a single-surveyor deployment; NOT acceptable for a multi-user one\n"
            "producing legal survey deliverables. PATCH /gcps/{id} returns 401 the moment\n"
            "LE_AUTH_MODE != none and no principal resolves — the audit trail is enforced as\n"
            "soon as there is more than one person who could be lying."
        ),
        vars=(
            EnvVar("LE_AUTH_MODE", "none", "core.security — none|api_key|bearer|cookie"),
            EnvVar("LE_ACCESS_TOKEN_TTL_SECONDS", "3600", "core.security"),
            EnvVar("LE_API_KEYS", "", "core.security — CSV of hashed keys", secret=True),
            EnvVar("LE_JWKS_URL", "", "core.security"),
            EnvVar("LE_RATE_LIMIT_ENABLED", "false", "api.middleware"),
            EnvVar("LE_RATE_LIMIT_PER_MINUTE", "600", "api.middleware"),
        ),
    ),
    EnvSection(
        title="9.3 Database",
        note=(
            "'db' resolves INSIDE compose. ON A BARE HOST YOU MUST SET LE_DATABASE_URL.\n"
            "Deliberate trade: optimise the default for the documented happy path (compose)\n"
            "and make the bare-host failure legible via /health/ready's per-dependency\n"
            "diagnosis rather than a boot traceback."
        ),
        vars=(
            EnvVar(
                "LE_DATABASE_URL",
                "postgresql+psycopg://landexplorer:landexplorer@db:5432/landexplorer",
                "db.session, alembic/env",
                secret=True,
            ),
            EnvVar(
                "LE_MIGRATION_DATABASE_URL",
                "",
                "alembic/env — a distinct superuser role in prod",
                secret=True,
                default_note="= LE_DATABASE_URL",
            ),
            EnvVar("LE_DB_POOL_SIZE", "5", "db.session"),
            EnvVar("LE_DB_MAX_OVERFLOW", "10", "db.session"),
            EnvVar("LE_DB_POOL_TIMEOUT_SECONDS", "30", "db.session"),
            EnvVar("LE_DB_ECHO", "false", "db.session"),
            EnvVar("LE_DB_STATEMENT_TIMEOUT_MS", "30000", "db.session"),
            EnvVar(
                "LE_DB_AUTO_MIGRATE",
                "false",
                "entrypoints/api.sh — compose.dev sets true; PROD LEAVES IT false",
            ),
        ),
    ),
    EnvSection(
        title="9.4 Redis / Celery",
        vars=(
            EnvVar(
                "LE_REDIS_URL",
                "redis://redis:6379/0",
                "tasks.celery_app, health, idempotency, pubsub, rate limit",
                secret=True,
            ),
            EnvVar(
                "LE_CELERY_BROKER_URL",
                "",
                "tasks.celery_app",
                secret=True,
                default_note="= LE_REDIS_URL",
            ),
            EnvVar(
                "LE_CELERY_RESULT_BACKEND",
                "redis://redis:6379/1",
                "tasks.celery_app",
                secret=True,
            ),
            EnvVar("LE_CELERY_TASK_ALWAYS_EAGER", "false", "tasks.celery_app — tests set true"),
            EnvVar(
                "LE_CELERY_WORKER_CONCURRENCY",
                "2",
                "worker entrypoint — CV queue. Keep low: SIFT is CPU-hungry.",
            ),
            EnvVar(
                "LE_CELERY_TASK_SOFT_TIME_LIMIT",
                "600",
                "tasks.base — soft => catchable => job marked failed cleanly",
            ),
            EnvVar("LE_CELERY_TASK_TIME_LIMIT", "900", "tasks.celery_app — hard kill"),
            EnvVar("LE_CELERY_PREFETCH_MULTIPLIER", "1", "long tasks => no hoarding"),
            EnvVar("LE_CELERY_ACKS_LATE", "true", "redelivery on worker crash"),
            EnvVar("LE_JOB_MAX_ATTEMPTS", "3", "tasks.base"),
            EnvVar("LE_JOB_RETRY_BACKOFF_SECONDS", "5", "tasks.base"),
            EnvVar("LE_JOB_RETRY_BACKOFF_MAX_SECONDS", "120", "tasks.base"),
            EnvVar("LE_JOB_RESULT_TTL_SECONDS", "86400", "tasks.celery_app"),
            EnvVar(
                "LE_JOB_STALE_AFTER_SECONDS",
                "1800",
                "tasks.maintenance — reaper marks orphaned running => failed",
            ),
            EnvVar("LE_JOB_PROGRESS_TTL_SECONDS", "3600", "tasks.progress"),
            EnvVar("LE_JOB_RETENTION_DAYS", "30", "tasks.maintenance"),
        ),
    ),
    EnvSection(
        title="9.5 Storage & uploads",
        vars=(
            EnvVar("LE_STORAGE_BACKEND", "local", "storage — local|s3"),
            EnvVar(
                "LE_STORAGE_LOCAL_ROOT",
                "./data/storage",
                "storage.local — MUST BE A SHARED VOLUME ACROSS api + workers",
            ),
            EnvVar("LE_STORAGE_S3_BUCKET", "", "storage.s3"),
            EnvVar("LE_STORAGE_S3_ENDPOINT_URL", "", "storage.s3 — set for MinIO"),
            EnvVar("LE_STORAGE_S3_REGION", "us-east-1", "storage.s3"),
            EnvVar("LE_STORAGE_S3_ACCESS_KEY_ID", "", "storage.s3", secret=True),
            EnvVar("LE_STORAGE_S3_SECRET_ACCESS_KEY", "", "storage.s3", secret=True),
            EnvVar("LE_STORAGE_SIGNED_URL_TTL_SECONDS", "900", "storage.s3"),
            EnvVar(
                "LE_STORAGE_MIN_FREE_BYTES",
                "2147483648",
                "image_service — 507 INSUFFICIENT_STORAGE, checked BEFORE streaming",
            ),
            EnvVar(
                "LE_UPLOAD_MAX_BYTES",
                "524288000",
                "api.middleware, nginx — 500 MB. MIRROR IN nginx client_max_body_size.",
            ),
            EnvVar(
                "LE_UPLOAD_ALLOWED_MIME",
                "image/jpeg,image/png,image/tiff,image/webp",
                "image_service — SNIFFED, not trusted from the header",
            ),
            EnvVar(
                "LE_MAX_IMAGE_PIXELS", "400000000", "image_service — decompression-bomb guard"
            ),
            EnvVar("LE_MAX_IMAGE_DIM", "65535", "image_service"),
            EnvVar(
                "LE_ASYNC_INGEST_THRESHOLD_BYTES",
                "52428800",
                "image_service — above this, ingest goes async",
            ),
            EnvVar("LE_USE_SENDFILE", "false", "images.py — X-Accel-Redirect in prod"),
        ),
    ),
    EnvSection(
        title="9.6 Imagery",
        note=(
            "L2: THE DEFAULT PROVIDER IS KEYLESS. Everything in this section is opt-in\n"
            "EXCEPT esri_world_imagery, which needs no key and is what `docker compose up`\n"
            "with an empty .env resolves to.\n"
            "\n"
            "ESRI ToS: the World Imagery basemap is served by Esri under the ArcGIS Online\n"
            "terms. ATTRIBUTION IS MANDATORY on screen and on derived output\n"
            "(LE_EXPORT_INCLUDE_ATTRIBUTION — leave it true). Review the terms for your\n"
            "own use case before deploying; see docs/legal/imagery-terms.md.\n"
            "\n"
            "GOOGLE EARTH IS NOT A PROVIDER AND NEVER WILL BE. Not a disabled flag: an\n"
            "absence. There is no enum label for it, no scaffolding, and CI greps for Earth\n"
            "endpoint patterns. LE_GOOGLE_MAPS_STATIC_KEY below is the Maps *Static API*,\n"
            "a different product with different terms, and it is double-opt-in."
        ),
        vars=(
            EnvVar(
                "LE_IMAGERY_PROVIDER",
                "auto",
                "gis.imagery.registry — 'auto' walks LE_IMAGERY_FALLBACK_CHAIN and takes "
                "the first is_configured() provider. An explicit name uses that provider, "
                "with the chain as error-recovery only.",
            ),
            EnvVar(
                "LE_IMAGERY_FALLBACK_CHAIN",
                "local_orthophoto,esri_world_imagery",
                "gis.imagery.registry — local_orthophoto FIRST: if the operator mounted "
                "orthophotos they are definitionally better than any web tile source. It "
                "self-skips via is_configured() when the dir is empty, so the zero-config "
                "machine lands on Esri with no branching.",
            ),
            EnvVar(
                "LE_IMAGERY_DIRECT_TILE_URLS",
                "false",
                "imagery_service — false => tile_url_template is the PROXY PATH for every "
                "provider, preserving the ToS chokepoint, the shared quota bucket and "
                "worker/browser cache identity. true => keyless providers return their "
                "upstream URL; the ToS consequence is in docs/legal/imagery-terms.md.",
            ),
            EnvVar(
                "LE_IMAGERY_STRICT", "false", "gis.imagery.registry — true in prod: no silent fallback"
            ),
            EnvVar(
                "LE_ALLOWED_PROVIDERS",
                "",
                "gis.imagery.registry — the operator's hard allow-list. Empty = all registered.",
            ),
            EnvVar(
                "LE_IMAGERY_OFFLINE",
                "false",
                "registry — true => only local_orthophoto + fixture. See "
                "docs/guides/offline-mode.md and `make seed`.",
            ),
            EnvVar(
                "LE_IMAGERY_TILE_CACHE_BACKEND",
                "disk",
                "gis.imagery.cache — memory|disk|redis. REDIS IN PROD: tile fetching happens "
                "inside Celery workers and a disk cache in a container is per-replica; four "
                "workers searching the same AOI would fetch every tile four times.",
            ),
            EnvVar("LE_IMAGERY_TILE_CACHE_DIR", "./data/tile_cache", "cache.disk"),
            EnvVar(
                "LE_IMAGERY_TILE_CACHE_TTL_SECONDS",
                "2592000",
                "cache — 30 d. SEVERAL ToS CAP CACHING; see docs/legal/imagery-terms.md.",
            ),
            EnvVar(
                "LE_IMAGERY_TILE_CACHE_MAX_BYTES",
                "21474836480",
                "tasks.maintenance — 20 GB LRU cap",
            ),
            EnvVar("LE_IMAGERY_MAX_CONCURRENT_FETCHES", "4", "gis.imagery.http"),
            EnvVar(
                "LE_IMAGERY_RATE_LIMIT_RPS", "5", "gis.imagery.ratelimit — token bucket per provider"
            ),
            EnvVar("LE_IMAGERY_REQUEST_TIMEOUT_SECONDS", "15", "gis.imagery.http"),
            EnvVar("LE_IMAGERY_MAX_RETRIES", "3", "gis.imagery.http — jittered backoff"),
            EnvVar(
                "LE_IMAGERY_USER_AGENT",
                "LandExplorer/1.0 (+https://example.invalid)",
                "gis.imagery.http — OPERATORS SHOULD SET A REAL CONTACT",
            ),
            EnvVar(
                "LE_ESRI_IMAGERY_TILE_URL_TEMPLATE",
                "https://services.arcgisonline.com/ArcGIS/rest/services"
                "/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "providers.esri — NOTE THE {z}/{y}/{x} ORDER. kind=satellite.",
            ),
            EnvVar(
                "LE_ESRI_REFERENCE_TILE_URL_TEMPLATE",
                "https://services.arcgisonline.com/ArcGIS/rest/services"
                "/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                "providers.esri — the overlay composited OVER imagery to serve kind=hybrid",
            ),
            EnvVar(
                "LE_ESRI_TERRAIN_TILE_URL_TEMPLATE",
                "https://services.arcgisonline.com/ArcGIS/rest/services"
                "/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}",
                "providers.esri — kind=terrain",
            ),
            EnvVar("LE_ESRI_MAX_ZOOM", "19", "providers.esri"),
            EnvVar("LE_ESRI_RATE_LIMIT_RPS", "8.0", "providers.esri"),
            EnvVar(
                "LE_LOCAL_ORTHO_DIR",
                "./data/orthophotos",
                "providers.local_ortho — empty dir => provider reports unavailable, NO CRASH",
            ),
            EnvVar("LE_LOCAL_ORTHO_ATTRIBUTION", "Local orthophoto", "providers.local_ortho"),
            EnvVar("LE_LOCAL_ORTHO_REINDEX_SECONDS", "300", "providers.local_ortho"),
            EnvVar(
                "LE_LOCAL_ORTHO_ASSUME_BLACK_NODATA",
                "false",
                "FALSE ON PURPOSE — black is a legitimate pixel value",
            ),
            EnvVar(
                "LE_MAPBOX_ACCESS_TOKEN",
                "",
                "providers.mapbox — empty => NOT OFFERED, not a crash",
                secret=True,
            ),
            EnvVar("LE_MAPBOX_STYLE_ID", "mapbox.satellite", "providers.mapbox"),
            EnvVar("LE_MAPBOX_CACHE_TTL_SECONDS", "2592000", "VERIFY AGAINST CURRENT ToS"),
            EnvVar("LE_BING_MAPS_KEY", "", "providers.bing", secret=True),
            EnvVar("LE_BING_IMAGERY_SET", "Aerial", "providers.bing"),
            EnvVar("LE_COPERNICUS_CLIENT_ID", "", "providers.sentinel", secret=True),
            EnvVar("LE_COPERNICUS_CLIENT_SECRET", "", "providers.sentinel", secret=True),
            EnvVar("LE_COPERNICUS_MAX_CLOUD_PCT", "20", "providers.sentinel"),
            EnvVar(
                "LE_SENTINEL_MAX_ZOOM",
                "15",
                "providers.sentinel — REFUSES zoom > 15 rather than serving upsampled mush "
                "a matcher would confidently act on",
            ),
            EnvVar("LE_GOOGLE_MAPS_STATIC_KEY", "", "providers.google_static", secret=True),
            EnvVar(
                "LE_GOOGLE_TOS_ACKNOWLEDGED",
                "false",
                "providers.google_static — DOUBLE OPT-IN. The key alone is insufficient; the "
                "operator must assert their own ToS coverage. Google EARTH is never a provider.",
            ),
        ),
    ),
    EnvSection(
        title="9.6a Elevation",
        vars=(
            EnvVar(
                "LE_ELEVATION_PROVIDER",
                "none",
                "gis.elevation — none|local_dem|copernicus_dem. 'none' is KEYLESS, OFFLINE "
                "and TERMINAL: elevation_m and elevation_source are both NULL and the job "
                "says ELEVATION_UNAVAILABLE. Honest beats absent.",
            ),
            EnvVar(
                "LE_LOCAL_DEM_DIR",
                "./data/dem",
                "elevation.local_dem — empty dir => unavailable, NO CRASH",
            ),
            EnvVar("LE_COPERNICUS_DEM_URL", "", "elevation.copernicus_dem"),
            EnvVar("LE_ELEVATION_CACHE_TTL_SECONDS", "2592000", "elevation"),
        ),
    ),
    EnvSection(
        title="9.7 Search",
        note=(
            "LE_SEARCH_REQUIRE_PRIOR IS DELETED. The requirement is unconditional: a hint is\n"
            "a hard input requirement, not a toggle. 422 SEARCH_HINT_REQUIRED, always. A config\n"
            "flag implying global search is possible would be a lie."
        ),
        vars=(
            EnvVar("LE_SEARCH_DEFAULT_ZOOM", "18", "candidates.strategy"),
            EnvVar("LE_SEARCH_DEFAULT_RADIUS_M", "1000", "candidates.hint"),
            EnvVar("LE_SEARCH_MAX_RADIUS_M", "50000", "matching.py validation"),
            EnvVar("LE_SEARCH_MAX_CANDIDATES", "25", "candidates.strategy"),
            EnvVar("LE_SEARCH_WINDOW_SIZE_PX", "1024", "candidates.strategy"),
            EnvVar(
                "LE_SEARCH_OVERLAP_RATIO",
                "0.5",
                "candidates.strategy — buys the 512 px footprint guarantee. At 0.25 the "
                "guarantee is only 256 px, and the matching design reasons from 512.",
            ),
            EnvVar("LE_SEARCH_TARGET_GSD_M", "0.5", "candidates.strategy"),
            EnvVar("LE_MAX_TILES_PER_JOB", "512", "candidates.budget"),
            EnvVar("LE_MAX_STATIC_TILES", "16", "imagery.py — endpoint 53 is a request, not a job"),
            EnvVar(
                "LE_MAX_STATIC_PIXELS",
                "4194304",
                "imagery.py — 4 MP. A 64-megapixel stitch inside a GET is the workload L5 forbids.",
            ),
            EnvVar("LE_SEARCH_MAX_BBOX_AREA_KM2", "2500", "matching.py validation"),
            EnvVar("LE_EXIF_RADIUS_INFLATION", "3.0", "candidates.hint — multiply EXIF HPE"),
            EnvVar("LE_EXIF_MIN_RADIUS_M", "250", "candidates.hint"),
        ),
    ),
    EnvSection(
        title="9.8 AI engine",
        note=(
            "★ READ docs/architecture/SCOPE.md BEFORE TUNING ANYTHING IN THIS SECTION.\n"
            "  THE AUTOMATIC MATCHING ENGINE IS DEFERRED IN THIS BUILD. Feature extraction,\n"
            "  matching, RANSAC, homography, pose, heatmap, semantics and scoring exist as\n"
            "  typed stubs that raise NotImplementedDeferred; the endpoints that would drive\n"
            "  them return 501. THESE VARIABLES ARE THE CONFIG SURFACE OF A DEFERRED ENGINE.\n"
            "  Setting them changes nothing observable today. They are kept — with their\n"
            "  contract defaults — so that re-enabling the engine requires zero changes\n"
            "  outside ai_engine/ (SCOPE.md §7).\n"
            "\n"
            "  GCPs in this build are placed MANUALLY: the surveyor marks a landmark in the\n"
            "  photo and clicks the same spot on the map. The coordinate is a DIRECT\n"
            "  OBSERVATION, and `confidence` is SURVEYOR-DECLARED — never computed. No value\n"
            "  below can change that, including LE_AI_MIN_CONFIDENCE."
        ),
        vars=(
            EnvVar("LE_AI_EXTRACTOR", "sift", "match_service -> AiEngineConfig — L1 default"),
            EnvVar("LE_AI_MATCHER", "flann", "-> AiEngineConfig"),
            EnvVar("LE_AI_DETECTOR_FREE", "", "-> AiEngineConfig — empty => no LoFTR"),
            EnvVar("LE_AI_SEGMENTER", "classical", "-> AiEngineConfig.segmenter"),
            EnvVar("LE_AI_SUGGESTER", "classical_suggester", "-> AiEngineConfig.suggester"),
            EnvVar(
                "LE_AI_RANSAC_METHOD",
                "usac_magsac",
                "-> AiEngineConfig.ransac.method: HomographyMethod. A ROBUST-FIT METHOD.",
            ),
            EnvVar(
                "LE_AI_ESTIMATOR_BACKEND",
                "opencv",
                "-> AiEngineConfig.estimator_backend. A COMPONENT REGISTRY KEY. 'opencv' is "
                "the only registered one. (LE_AI_ESTIMATOR is DELETED — it conflated the two "
                "and was a zero-env boot crash.)",
            ),
            EnvVar(
                "LE_AI_ALLOW_DEEP_MODELS",
                "true",
                "registry — true = ATTEMPT deep backends; unavailability is still graceful. "
                "false = never even probe.",
            ),
            EnvVar(
                "LE_AI_STRICT_BACKEND",
                "false",
                "models.policy — true => missing weights RAISE instead of falling back. "
                "CI accuracy suites only. true IN PROD VIOLATES L1.",
            ),
            EnvVar(
                "LE_AI_MODEL_WEIGHTS_DIR",
                "./data/model_weights",
                "models.weights — EMPTY BY DEFAULT AND THAT IS THE SUPPORTED STATE",
            ),
            EnvVar(
                "LE_AI_DEVICE",
                "auto",
                "models.device — 'auto' -> cpu on this machine (cuda.is_available() is False "
                "despite the cu130 wheel). 'cuda' when unavailable => WARN + cpu.",
            ),
            EnvVar("LE_AI_TORCH_THREADS", "0", "models.device — 0 = leave torch's default"),
            EnvVar("LE_AI_DETERMINISTIC_SEED", "42", "pipeline — RANSAC reproducibility"),
            EnvVar("LE_AI_MAX_FEATURES", "8000", "extractors"),
            EnvVar(
                "LE_AI_CLAHE_ENABLED",
                "true",
                "extractors.preprocess — big win on hazy field photos",
            ),
            EnvVar("LE_AI_RATIO_TEST", "0.75", "matchers.filters — Lowe"),
            EnvVar("LE_AI_CROSS_CHECK", "true", "matchers — mutual NN"),
            EnvVar("LE_AI_MIN_MATCHES", "10", "matchers — below => candidate skipped"),
            EnvVar("LE_AI_RANSAC_THRESHOLD_PX", "3.0", "geometry"),
            EnvVar("LE_AI_RANSAC_MAX_ITERS", "10000", "geometry"),
            EnvVar("LE_AI_RANSAC_CONFIDENCE", "0.999", "geometry"),
            EnvVar("LE_AI_MIN_INLIERS", "12", "geometry.degeneracy — H1"),
            EnvVar(
                "LE_AI_MIN_CONFIDENCE",
                "40.0",
                "pipeline.ranking — 0-100. Below => candidate dropped. REFUSING TO ANSWER "
                "BEATS A CONFIDENT WRONG COORDINATE (L12).",
            ),
            EnvVar(
                "LE_AI_RANK_MARGIN",
                "10.0",
                "pipeline.ranking — 0-100. Winner must beat runner-up by this, else "
                'status="ambiguous"',
            ),
            EnvVar("LE_AI_MAX_RESULTS", "5", "pipeline — ranked candidates persisted"),
            EnvVar("LE_AI_SCORE_WEIGHT_FEATURE", "0.25", "scoring.composite"),
            EnvVar("LE_AI_SCORE_WEIGHT_GEOMETRIC", "0.35", "scoring.composite"),
            EnvVar("LE_AI_SCORE_WEIGHT_LANDMARK", "0.30", "scoring.composite"),
            EnvVar("LE_AI_SCORE_WEIGHT_SEMANTIC", "0.10", "scoring.composite"),
            EnvVar(
                "LE_AI_CALIBRATION_ID",
                "identity",
                "scoring.calibration — SHIPS UNCALIBRATED AND SAYS SO",
            ),
            EnvVar(
                "LE_AI_SEMANTICS_ENABLED",
                "false",
                "semantics — off: SAM is heavy and weight-dependent",
            ),
            EnvVar("LE_AI_DEEP_MAX_CANDIDATES", "8", "CODE-ENFORCED cap. CPU-only reality."),
            EnvVar("LE_AI_SAM_CHECKPOINT", "", "semantics.sam — empty => classical masks"),
            EnvVar("LE_AI_SUPERPOINT_WEIGHTS", "", "extractors.superpoint"),
            EnvVar("LE_AI_SUPERGLUE_WEIGHTS", "", "matchers.superglue"),
            EnvVar("LE_AI_LIGHTGLUE_WEIGHTS", "", "matchers.lightglue"),
            EnvVar("LE_AI_LOFTR_WEIGHTS", "", "matchers.loftr"),
            EnvVar("LE_AI_DINOV2_WEIGHTS", "", "extractors.dinov2"),
        ),
    ),
    EnvSection(
        title="9.9 Limits, exports, misc",
        vars=(
            EnvVar("LE_MAX_ANNOTATIONS_PER_IMAGE", "2000", "annotation_service"),
            EnvVar("LE_MAX_BATCH_FILES", "100", "batch_service"),
            EnvVar("LE_MAX_BATCH_BYTES", "2147483648", "batch_service"),
            EnvVar("LE_MAX_REPLAY_EVENTS", "5000", "revision_service"),
            EnvVar("LE_CHECKPOINT_EVERY_N_EVENTS", "50", "revision_service"),
            EnvVar("LE_GCP_CONSISTENCY_TOLERANCE_M", "0.5", "gcp_service"),
            EnvVar("LE_GCP_BOUNDS_SLACK_M", "100", "gcp_service"),
            EnvVar(
                "LE_GEOTIFF_DISAGREEMENT_M",
                "50",
                "match_service — geotiff_georeference_disagreement flag",
            ),
            EnvVar("LE_PROJECT_NAMES_UNIQUE", "false", "project_service"),
            EnvVar("LE_EXPORT_DIR", "./data/storage/exports", "export_service"),
            EnvVar(
                "LE_EXPORT_FORMATS",
                "csv,geojson,kml,kmz,shapefile,gpkg,dxf,pdf",
                "gis.exports — unavailable optional deps are DROPPED from GET /capabilities, "
                "not crashed on",
            ),
            EnvVar("LE_EXPORT_DEFAULT_SRID", "4326", "gis.exports"),
            EnvVar("LE_EXPORT_TTL_SECONDS", "604800", "tasks.maintenance"),
            EnvVar("LE_EXPORT_MAX_ROWS", "100000", "export_service"),
            EnvVar(
                "LE_EXPORT_INCLUDE_ATTRIBUTION",
                "true",
                "gis.exports.* — SHOULD NOT BE TURNED OFF; several providers' ToS require "
                "attribution on derived output",
            ),
        ),
    ),
    EnvSection(
        title="9.10 Observability",
        vars=(
            EnvVar("LE_METRICS_ENABLED", "true", "observability.metrics"),
            EnvVar(
                "LE_METRICS_PATH",
                "/metrics",
                "main — NOT under /api/v1; not part of the public contract",
            ),
            EnvVar("LE_SENTRY_DSN", "", "main — empty => not initialised", secret=True),
            EnvVar(
                "LE_OTEL_EXPORTER_OTLP_ENDPOINT",
                "",
                "observability.tracing — empty => no-op tracer",
            ),
            EnvVar("LE_OTEL_SERVICE_NAME", "landexplorer-api", "observability.tracing"),
        ),
    ),
    EnvSection(
        title="9.11 Frontend (VITE_ — BUILD-TIME, NEVER SECRET)",
        note=(
            "VITE_MAP_TILE_URL and VITE_MAP_ATTRIBUTION are DELETED. The backend is the single\n"
            "source of truth for provider config — the SPA calls GET /imagery/providers. An\n"
            "escape hatch that lets the bundle disagree with the server about which provider's\n"
            "ToS applies is exactly the kind of divergence this system cannot afford.\n"
            "\n"
            "These are baked into the JS bundle at BUILD time. Anything secret put here is\n"
            "public. Changing one requires rebuilding the frontend image, not restarting it."
        ),
        vars=(
            EnvVar("VITE_API_BASE_URL", "/api/v1", "src/api/client.ts"),
            EnvVar("VITE_APP_NAME", "LandExplorer", "shell/TopBar"),
            EnvVar("VITE_MAP_DEFAULT_CENTER", "0,0", "store/mapStore"),
            EnvVar("VITE_MAP_DEFAULT_ZOOM", "3", "store/mapStore"),
            EnvVar(
                "VITE_JOB_POLL_INTERVAL_MS",
                "1500",
                "api/hooks/useJob — floor for the adaptive schedule",
            ),
            EnvVar(
                "VITE_MAX_UPLOAD_MB",
                "500",
                "upload/UploadDropzone — mirrors LE_UPLOAD_MAX_BYTES",
            ),
            EnvVar("VITE_ENABLE_DEVTOOLS", "false", "main.tsx"),
            EnvVar(
                "VITE_MIN_LANDMARKS",
                "4",
                "annotation/AnnotationToolbar — a homography needs >= 4",
            ),
        ),
    ),
    EnvSection(
        title="9.12 Compose infrastructure (UNPREFIXED — upstream images own these)",
        note=(
            "These are the only unprefixed variables in the system. They are read by the\n"
            "postgres/redis images and by the compose files themselves, not by our code."
        ),
        vars=(
            EnvVar("POSTGRES_USER", "landexplorer", "db service"),
            EnvVar("POSTGRES_PASSWORD", "landexplorer", "db service — CHANGE IN PROD", secret=True),
            EnvVar("POSTGRES_DB", "landexplorer", "db service"),
            EnvVar("POSTGRES_PORT", "5432", "compose"),
            EnvVar("REDIS_PORT", "6379", "compose"),
            EnvVar("LE_WEB_PORT", "8080", "compose (nginx publish)"),
            EnvVar("LE_WORKER_CV_REPLICAS", "1", "compose.prod"),
            EnvVar("LE_WORKER_IO_REPLICAS", "1", "compose.prod"),
            EnvVar("LE_WORKER_EXPORT_REPLICAS", "1", "compose.prod"),
        ),
    ),
)

_HEADER = """\
# ═══════════════════════════════════════════════════════════════════════════════
#  LandExplorer — example environment
#
#  ★ GENERATED FILE. DO NOT EDIT BY HAND.
#      regenerate:  make check-env      (scripts/check_env.py --emit-example)
#      CI compares the generated bytes against this file (CONTRACT.md §13.4 r11).
#      Its source of truth is CONTRACT.md §9.
#
#  ★ COPYING THIS FILE IS OPTIONAL. Every line is commented out, so
#         cp .env.example .env
#    is byte-equivalent to an EMPTY .env. That is not laziness — it is L10 made
#    physical: EVERY SETTING HAS A WORKING DEFAULT, and `Settings()` with an empty
#    environment never raises. Uncomment only what you actually want to change.
#
#  ★ `docker compose up` WITH NO .env AT ALL YIELDS A WORKING APP. It resolves to
#    the KEYLESS Esri World Imagery provider (L2). No account, no key, no card.
#
#  ★ Lines marked  [secret]  are never logged, never returned by any API, and are
#    redacted in /health/ready. They are emitted here with EMPTY values on purpose:
#    a generated example file must never be able to leak or pin a live credential.
#
#  ★ ON A BARE HOST (no compose) the one variable you are most likely to need is
#    LE_DATABASE_URL — its default hostname `db` only resolves inside compose.
# ═══════════════════════════════════════════════════════════════════════════════
"""


def _wrap(text: str, width: int, prefix: str) -> list[str]:
    """Wrap ``text`` to ``width`` columns, prefixing each line with ``prefix``."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = prefix.rstrip()
    for word in words:
        candidate = f"{current} {word}" if current.strip() != prefix.strip() else f"{prefix}{word}"
        if len(candidate) > width and current.strip() != prefix.strip():
            lines.append(current)
            current = f"{prefix}{word}"
        else:
            current = candidate
    lines.append(current)
    return lines


def render_env_example() -> str:
    """Render the full ``.env.example`` text from :data:`ENV_SECTIONS`.

    Returns:
        The complete file content, newline-terminated. Every variable line is
        emitted commented out (see the module docstring for why).
    """
    out: list[str] = [_HEADER]
    for section in ENV_SECTIONS:
        out.append("")
        out.append("# " + "─" * 77)
        out.append(f"# {section.title}")
        out.append("# " + "─" * 77)
        if section.note:
            out.append("#")
            for note_line in section.note.split("\n"):
                out.append(f"# {note_line}".rstrip())
            out.append("#")
        out.append("")
        for var in section.vars:
            out.extend(_wrap(var.consumer, 79, "#   "))
            if var.secret:
                # ★ The § marker governs HANDLING, not existence. A secret with a
                #   real §9 default still shows it: the default is public (it is
                #   printed in the contract), and hiding it would make this file
                #   lie about what the system does when you change nothing.
                out.append("#   [secret] never logged · never returned by any API · redacted in")
                out.append("#            /health/ready. Set this via a real secret store in prod.")
            if var.default_note:
                out.append(f"#   default: {var.default_note}")
                out.append(f"# {var.name}=")
            else:
                out.append(f"# {var.name}={var.default}")
            out.append("")
    # Collapse the trailing blank line into a single terminator.
    text = "\n".join(out).rstrip("\n") + "\n"
    return text


def all_env_vars() -> list[EnvVar]:
    """Return every §9 variable, in document order."""
    return [var for section in ENV_SECTIONS for var in section.vars]


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT.md §0.1 — capability probes.
#
# ★ NOTHING HERE IS ASSUMED. Every row is probed on the machine the script runs
#   on. find_spec() first, so an absent package costs nothing and a present-but-
#   heavy one (torch) is only imported when it is actually there.
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class Probe:
    """One capability row.

    Attributes:
        key: The ``--require`` name.
        label: Human label for the table.
        check: Callable returning ``(present, detail)``.
        consequence: What is lost when absent. Printed only when absent.
        expected: What §0.1 recorded on the reference dev machine.
    """

    key: str
    label: str
    check: Callable[[], tuple[bool, str]]
    consequence: str = ""
    expected: str = ""
    result: tuple[bool, str] = field(default=(False, ""), init=False)


def _module_probe(module: str, attr: str = "__version__") -> Callable[[], tuple[bool, str]]:
    """Build a probe that reports a module's version without importing it blindly."""

    def _check() -> tuple[bool, str]:
        try:
            if importlib.util.find_spec(module) is None:
                return (False, "not installed")
        except (ImportError, ValueError):
            return (False, "not installed")
        try:
            mod = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 — a broken install is "absent", not a crash
            return (False, f"present but unimportable: {type(exc).__name__}: {exc}")
        return (True, str(getattr(mod, attr, "unknown")))

    return _check


def _probe_python() -> tuple[bool, str]:
    return (sys.version_info >= (3, 12), platform.python_version())


def _probe_torch_cuda() -> tuple[bool, str]:
    """Report whether a USABLE GPU exists — never inferred from a build name."""
    try:
        if importlib.util.find_spec("torch") is None:
            return (False, "torch not installed")
        import torch  # noqa: PLC0415 — call-time bound on purpose (§11.3)

        available = bool(torch.cuda.is_available())
        build = getattr(torch.version, "cuda", None)
        detail = f"cuda.is_available()={available} (wheel built for cuda {build})"
        return (available, detail)
    except Exception as exc:  # noqa: BLE001
        return (False, f"probe failed: {type(exc).__name__}: {exc}")


def _probe_gdal() -> tuple[bool, str]:
    try:
        if importlib.util.find_spec("osgeo") is None:
            return (False, "not installed")
        from osgeo import gdal  # noqa: PLC0415

        return (True, str(gdal.__version__))
    except Exception as exc:  # noqa: BLE001
        return (False, f"present but unimportable: {type(exc).__name__}: {exc}")


def _probe_gdal_array() -> tuple[bool, str]:
    """Probe GDAL's **NumPy bridge** separately from GDAL's core.

    ★ These are two different capabilities and on this machine they DISAGREE.
    ``osgeo.gdal_array`` is a compiled extension built against NumPy 1.x; under
    the NumPy 2.4.3 installed here it fails with ``numpy.core.multiarray failed
    to import``. Consequences, all silent until they are not:

    * ``band.ReadAsArray()`` / ``band.WriteArray()`` — the idiomatic way to move
      raster pixels into NumPy — **raise**.
    * ``gdal.UseExceptions()`` **itself raises**, because it imports gdal_array
      internally. That is the call GDAL's own docs tell you to make first.

    GDAL's core is unaffected: ``Create``/``Open``, ``SetGeoTransform``,
    ``SetProjection`` and the raw-byte ``ReadRaster``/``WriteRaster`` interface
    all work and round-trip exactly. **The raw-byte path is the only working way
    to do raster IO on this machine** (``np.frombuffer(band.ReadRaster(...))``).

    Probed rather than assumed, because §0.1's "Raster IO works today without
    rasterio" is true only via that path, and a module that reaches for
    ``ReadAsArray`` will fail at runtime with an error that looks like a NumPy
    problem rather than a GDAL packaging problem.
    """
    try:
        if importlib.util.find_spec("osgeo") is None:
            return (False, "osgeo not installed")
    except (ImportError, ValueError):
        return (False, "osgeo not installed")
    # ★ The failing import prints NumPy's multi-paragraph "compiled using NumPy
    #   1.x" banner straight to stderr. We are DELIBERATELY provoking that failure
    #   to report it as one tidy line, so the banner is captured rather than
    #   dumped over the table. Suppressing it here is not hiding it — reporting it
    #   accurately is this probe's entire job.
    sink = io.StringIO()
    try:
        with warnings.catch_warnings(), contextlib.redirect_stderr(sink):
            warnings.simplefilter("ignore")
            from osgeo import gdal_array  # noqa: PLC0415, F401
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            f"BROKEN ({type(exc).__name__}: {exc}) — ReadAsArray/WriteArray and "
            "gdal.UseExceptions() all fail. Use the raw-byte path: "
            "np.frombuffer(band.ReadRaster(...), dtype=...)",
        )
    return (True, "ok — ReadAsArray/WriteArray usable")


def _probe_cv2_contrib() -> tuple[bool, str]:
    """Probe for opencv-contrib. §0.1 records it ABSENT; nothing may reference it.

    Returns ``present=False`` when contrib is absent, which is the EXPECTED and
    SUPPORTED state. It is listed so the table is honest, not so it can be required.
    """
    try:
        if importlib.util.find_spec("cv2") is None:
            return (False, "cv2 not installed")
        import cv2  # noqa: PLC0415

        has = hasattr(cv2, "xfeatures2d")
        return (has, "present" if has else "ABSENT (expected — classical path is SIFT/ORB/AKAZE/BRISK)")
    except Exception as exc:  # noqa: BLE001
        return (False, f"probe failed: {type(exc).__name__}: {exc}")


def _binary_probe(name: str, *version_args: str) -> Callable[[], tuple[bool, str]]:
    """Build a probe for an executable on PATH."""

    def _check() -> tuple[bool, str]:
        path = shutil.which(name)
        if path is None:
            return (False, "not on PATH")
        if not version_args:
            return (True, path)
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [path, *version_args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return (True, f"present, version probe failed: {exc}")
        out = (proc.stdout or proc.stderr).strip().splitlines()
        return (True, out[0] if out else "unknown version")

    return _check


def build_probes() -> list[Probe]:
    """Construct the §0.1 probe list. Order matches the contract's table."""
    return [
        Probe("python", "Python", _probe_python, expected=">= 3.12"),
        Probe(
            "numpy",
            "NumPy",
            _module_probe("numpy"),
            consequence="ai_engine and gis cannot import at all.",
            expected="2.4.x (NumPy-2 ABI)",
        ),
        Probe(
            "cv2",
            "OpenCV",
            _module_probe("cv2"),
            consequence="No feature extraction. In THIS build the CV path is deferred anyway "
            "(SCOPE.md), but thumbnails and ingest use it.",
            expected="4.13.x",
        ),
        Probe(
            "cv2_contrib",
            "cv2.xfeatures2d",
            _probe_cv2_contrib,
            expected="ABSENT — SURF/BEBLID/VGG/LATCH must not be referenced",
        ),
        Probe("scipy", "SciPy", _module_probe("scipy"), expected="1.17.x"),
        Probe("PIL", "Pillow", _module_probe("PIL"), expected="12.x"),
        Probe(
            "torch",
            "torch",
            _module_probe("torch"),
            consequence="Deep backends unavailable => classical fallback. A WARNING, not an error (L11).",
            expected="2.11.x — optional",
        ),
        Probe(
            "cuda",
            "usable GPU",
            _probe_torch_cuda,
            consequence="LE_AI_DEVICE=auto resolves to cpu. Expected on this machine.",
            expected="False — no usable GPU despite the cu130 wheel",
        ),
        Probe(
            "gdal",
            "GDAL / osgeo",
            _probe_gdal,
            consequence="★ NO RASTER BACKEND. local_orthophoto dies, GeoTIFF ingest is rejected, "
            "total_ce90_m becomes uncomputable. In an IMAGE this is a BUILD FAILURE (§9.14).",
            expected="3.8.x — the raster backend on the dev box",
        ),
        Probe(
            "gdal_array",
            "GDAL numpy bridge",
            _probe_gdal_array,
            consequence="★ band.ReadAsArray()/WriteArray() AND gdal.UseExceptions() all raise. "
            "GDAL's CORE still works — read/write pixels via the RAW BYTE path "
            "(np.frombuffer(band.ReadRaster(...))). gis.raster / rasterio_shim MUST use it.",
            expected="BROKEN here — osgeo is built against NumPy 1.x, NumPy 2.4.3 is installed",
        ),
        Probe(
            "rasterio",
            "rasterio",
            _module_probe("rasterio"),
            consequence="rasterio_shim falls back to osgeo.gdal. Fine on the dev box; PINNED in the image.",
            expected="absent on the dev box, pinned in the backend image",
        ),
        Probe(
            "pyproj",
            "pyproj",
            _module_probe("pyproj"),
            consequence="gis.crs falls back to osgeo.osr, then to closed-form NumPy (4326<->3857 only).",
            expected="absent on the dev box, pinned in the backend image",
        ),
        Probe("fastapi", "fastapi", _module_probe("fastapi"), expected="absent on the dev box"),
        Probe("pydantic", "pydantic", _module_probe("pydantic"), expected="absent on the dev box"),
        Probe(
            "sqlalchemy", "sqlalchemy", _module_probe("sqlalchemy"), expected="absent on the dev box"
        ),
        Probe("celery", "celery", _module_probe("celery"), expected="absent on the dev box"),
        Probe("redis", "redis", _module_probe("redis"), expected="absent on the dev box"),
        Probe("httpx", "httpx", _module_probe("httpx"), expected="absent on the dev box"),
        Probe(
            "geopandas",
            "geopandas",
            _module_probe("geopandas"),
            consequence="shapefile + gpkg exports are DROPPED from GET /capabilities, not crashed on.",
            expected="optional",
        ),
        Probe("shapely", "shapely", _module_probe("shapely"), expected="optional"),
        Probe("fiona", "fiona", _module_probe("fiona"), expected="optional"),
        Probe(
            "ezdxf",
            "ezdxf",
            _module_probe("ezdxf"),
            consequence="dxf export dropped from /capabilities.",
            expected="optional",
        ),
        Probe(
            "reportlab",
            "reportlab",
            _module_probe("reportlab"),
            consequence="PDF report export dropped from /capabilities.",
            expected="optional",
        ),
        Probe(
            "pytest",
            "pytest",
            _module_probe("pytest"),
            consequence="No test RUNNER. 'Zero installs' covers RUNTIME deps only — run "
            "scripts/bootstrap_dev.sh.",
            expected="absent until bootstrap_dev.sh installs the [dev] extras",
        ),
        Probe("hypothesis", "hypothesis", _module_probe("hypothesis"), expected="[dev] extra"),
        Probe("node", "node", _binary_probe("node", "--version"), expected="20.x"),
        Probe("npm", "npm", _binary_probe("npm", "--version"), expected="10.x"),
        Probe(
            "pnpm",
            "pnpm",
            _binary_probe("pnpm", "--version"),
            consequence="§2.5 mandates pnpm-lock.yaml. Run: corepack enable && corepack prepare "
            "pnpm@9 --activate",
            expected="ABSENT until corepack activates it",
        ),
        Probe(
            "docker",
            "docker",
            _binary_probe("docker", "--version"),
            consequence="★ Compose files CANNOT BE VERIFIED here. §13.4 rule 9: no task may be "
            "marked verified on the basis of a compose file. The first CI run with Docker is the gate.",
            expected="ABSENT on this machine",
        ),
    ]


_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _colour(enabled: bool) -> Callable[[str, str], str]:
    if not enabled:
        return lambda _code, text: text
    return lambda code, text: f"{code}{text}{_RESET}"


def print_capability_table(*, use_colour: bool = True) -> list[Probe]:
    """Probe this machine and print the §0.1 capability table.

    Returns:
        The probes, each carrying its result.
    """
    c = _colour(use_colour)
    probes = build_probes()
    for probe in probes:
        probe.result = probe.check()

    print(c(_BOLD, "LandExplorer — machine capabilities (CONTRACT.md §0.1, probed not assumed)"))
    print(c(_DIM, f"  {platform.platform()} · python {platform.python_version()} · {sys.executable}"))
    print(c(_DIM, f"  repo: {REPO_ROOT}"))
    print()
    width = max(len(p.label) for p in probes) + 2
    for probe in probes:
        present, detail = probe.result
        mark = c(_GREEN, "✔") if present else c(_YELLOW, "•")
        print(f"  {mark} {probe.label:<{width}} {detail}")
        if probe.expected:
            print(f"    {c(_DIM, '│ expected: ' + probe.expected)}")
        if not present and probe.consequence:
            print(f"    {c(_DIM, '└ consequence: ' + probe.consequence)}")
    print()
    print(c(_DIM, "  '•' is not an error. Most absences here are the SUPPORTED state:"))
    print(c(_DIM, "  a missing weight, key or optional dep is a warning and a fallback (L11)."))
    print()
    print(c(_BOLD, "  This build: AUTOMATIC MATCHING IS DEFERRED — see docs/architecture/SCOPE.md."))
    print(c(_DIM, "  GCPs are placed manually; confidence is surveyor-declared, never computed."))
    return probes


def cmd_require(required: list[str], *, use_colour: bool = True) -> int:
    """Assert the named capabilities are present. Returns a process exit code.

    This is the Docker **build-time** gate (§9.14, §14 F-56): an image that lost
    its raster backend must fail the build, not a surveyor's export.
    """
    c = _colour(use_colour)
    probes = {p.key: p for p in build_probes()}
    unknown = [name for name in required if name not in probes]
    if unknown:
        print(c(_RED, f"check_env: unknown capability name(s): {', '.join(unknown)}"), file=sys.stderr)
        print(f"  known: {', '.join(sorted(probes))}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for name in required:
        probe = probes[name]
        present, detail = probe.check()
        mark = c(_GREEN, "✔") if present else c(_RED, "✘")
        print(f"  {mark} {probe.label}: {detail}")
        if not present:
            failures.append(f"{probe.label} — {detail}. {probe.consequence}".strip())

    if failures:
        print(file=sys.stderr)
        print(c(_RED, "check_env: REQUIRED CAPABILITIES ARE MISSING:"), file=sys.stderr)
        for line in failures:
            print(f"  ✘ {line}", file=sys.stderr)
        return 1
    print(c(_GREEN, "check_env: all required capabilities present."))
    return 0


def cmd_emit_example(path: Path) -> int:
    """Write ``.env.example``. Returns a process exit code."""
    text = render_env_example()
    path.write_text(text, encoding="utf-8")
    print(f"check_env: wrote {path} ({len(all_env_vars())} variables from CONTRACT.md §9)")
    return 0


def cmd_check_example(path: Path, *, use_colour: bool = True) -> int:
    """Assert the committed ``.env.example`` matches §9 byte for byte (§13.4 r11)."""
    c = _colour(use_colour)
    expected = render_env_example()
    if not path.exists():
        print(c(_RED, f"check_env: {path} is missing. Run: make check-env"), file=sys.stderr)
        return 1
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        print(c(_GREEN, f"check_env: {path.name} matches CONTRACT.md §9 ({len(all_env_vars())} vars)."))
        return 0
    print(c(_RED, f"check_env: {path.name} IS STALE — it does not match CONTRACT.md §9."), file=sys.stderr)
    print("  Anything that mirrors a source of truth is generated or it drifts (§13.4 r11).", file=sys.stderr)
    print("  Fix with: make check-env", file=sys.stderr)
    import difflib  # noqa: PLC0415 — only needed on the failure path

    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=f"{path.name} (committed)",
        tofile="generated from §9",
        n=2,
    )
    sys.stderr.writelines(diff)
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="check_env.py",
        description=(
            "Probe this machine against CONTRACT.md §0.1, and generate/verify .env.example "
            "from CONTRACT.md §9."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--emit-example",
        action="store_true",
        help="regenerate .env.example from §9 (the ONLY way that file is written)",
    )
    group.add_argument(
        "--check-example",
        action="store_true",
        help="assert the committed .env.example matches §9; non-zero exit if it drifted",
    )
    group.add_argument(
        "--require",
        metavar="NAMES",
        help=(
            "comma-separated capability names that MUST be present; non-zero exit if any is "
            "missing. The Docker build-time gate. e.g. --require gdal,numpy,cv2"
        ),
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=ENV_EXAMPLE_PATH,
        help="location of .env.example (default: repo root)",
    )
    parser.add_argument("--no-colour", action="store_true", help="disable ANSI colour")
    args = parser.parse_args(argv)

    use_colour = (
        not args.no_colour
        and sys.stdout.isatty()
        and os.environ.get("TERM", "") != "dumb"
        and "NO_COLOR" not in os.environ
    )

    if args.emit_example:
        return cmd_emit_example(args.path)
    if args.check_example:
        return cmd_check_example(args.path, use_colour=use_colour)
    if args.require:
        names = [n.strip() for n in args.require.split(",") if n.strip()]
        return cmd_require(names, use_colour=use_colour)

    print_capability_table(use_colour=use_colour)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
