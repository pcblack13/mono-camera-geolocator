"""The ``/api/v1`` aggregator — ★ **the ONLY place the prefix appears** (§7).

Sub-routers are included in exactly the §2.4 order, with ``gcps.router_image`` **before**
``gcps.router_flat``: Starlette matches in registration order, and the image-scoped GCP routes
(``/images/{image_id}/gcps``) must be registered before the flat ones so neither shadows the
other. :func:`assert_no_duplicate_routes` walks ``app.routes`` at startup and **fails fast on
any duplicate ``(method, path)``** — a duplicate silently shadows in FastAPI and is otherwise
found only in production.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.api.errors import COMMON_ERROR_RESPONSES
from app.api.v1 import (
    accuracy,
    detection,
    drift,
    capture_library,
    dem_library,
    albums,
    annotations,
    batch,
    camera,
    cameras,
    capabilities,
    dem,
    exports,
    gcps,
    health,
    images,
    imagery,
    imports,
    jobs,
    live,
    lut,
    matching,
    offline,
    pose,
    projects,
    revisions,
    semantics,
    suggestions,
    videos,
)

__all__ = ["api_router", "assert_no_duplicate_routes"]

#: ★ The prefix, applied ONCE. Not read from Settings: a router mounted at a configurable path
#: is a router whose OpenAPI ``servers`` and whose generated client would drift from the code.
API_V1_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_V1_PREFIX, responses=COMMON_ERROR_RESPONSES)

# ── §2.4 registration order ─────────────────────────────────────────────────────
api_router.include_router(health.router, tags=["health"])
api_router.include_router(capabilities.router, tags=["capabilities"])
api_router.include_router(projects.router, tags=["projects"])
# ★ After ``projects``: albums are a collection OF projects, and ``/albums/{id}/projects``
#   returns ``Page[ProjectSummary]``. No path here can shadow one there —
#   ``assert_no_duplicate_routes`` proves it at startup rather than in production.
api_router.include_router(albums.router, tags=["albums"])
# ★ The entered camera is image-scoped (``/images/{id}/camera``) — a literal segment
#   no image route uses (``camera-pose`` is a different literal), so nothing can
#   shadow; ``assert_no_duplicate_routes`` proves it at startup.
api_router.include_router(camera.router, tags=["camera"])
api_router.include_router(images.router, tags=["images"])
# ★ After ``images``: a video is a FRAME SOURCE and ``POST /videos/{id}/frames`` mints an
#   ``images`` row. Its routes are all under ``/videos/*`` so none can shadow an image
#   route — ``assert_no_duplicate_routes`` proves it at startup.
api_router.include_router(videos.router, tags=["videos"])
api_router.include_router(capture_library.router, tags=["capture-library"])
api_router.include_router(dem_library.router, tags=["dem-library"])
api_router.include_router(annotations.router_nested, tags=["annotations"])
api_router.include_router(annotations.router_flat, tags=["annotations"])
api_router.include_router(revisions.router_project, tags=["revisions"])
api_router.include_router(revisions.router_flat, tags=["revisions"])
api_router.include_router(revisions.router_versions, tags=["revisions"])
api_router.include_router(matching.router_image, tags=["matching"])
api_router.include_router(matching.router_results, tags=["matching"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(gcps.router_image, tags=["gcps"])  # ★ before router_flat
api_router.include_router(gcps.router_flat, tags=["gcps"])
api_router.include_router(gcps.router_results, tags=["gcps"])
api_router.include_router(suggestions.router, tags=["suggestions"])
api_router.include_router(semantics.router, tags=["semantics"])
api_router.include_router(pose.router, tags=["pose"])
api_router.include_router(imagery.router, tags=["imagery"])
api_router.include_router(offline.router, tags=["imagery-offline"])
# ★ DEM processing (``gis.dem``) — stateless file transformation: no project, no
#   image, no row. Nothing here can shadow another route; every path is under /dem/*.
api_router.include_router(dem.router, tags=["dem"])
api_router.include_router(lut.router, tags=["lut"])
# ★ After `lut`: both hang off a photograph's solved pose, and this one grades it.
api_router.include_router(accuracy.router, tags=["accuracy"])
# ★ The camera REGISTRY (2026-09-02) — server-side cameras and their desired state.
#   Under /cameras/*; the entered-camera routes are /images/{id}/camera, a different
#   literal, so nothing shadows — ``assert_no_duplicate_routes`` proves it at startup.
api_router.include_router(cameras.router, tags=["cameras"])
api_router.include_router(live.router, tags=["live"])
# ★ After `live`: detection consumes the same sources the live panel plays.
api_router.include_router(detection.router, tags=["detection"])
api_router.include_router(drift.router, tags=["drift"])
# ★ After ``gcps``: the import routes are project-scoped (``/projects/{id}/gcps/import/…``)
#   and so cannot collide with the image- or flat-scoped GCP paths above.
#   ``assert_no_duplicate_routes`` proves it at startup.
api_router.include_router(imports.router, tags=["imports"])
api_router.include_router(batch.router, tags=["batch"])
api_router.include_router(exports.router_image, tags=["exports"])
api_router.include_router(exports.router_project, tags=["exports"])
api_router.include_router(exports.router_flat, tags=["exports"])


def assert_no_duplicate_routes(app: FastAPI) -> None:
    """Fail fast if any ``(method, path)`` is registered twice (§7). Called at startup."""
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or ():
                seen[(method, route.path)] += 1
    duplicates = {key: n for key, n in seen.items() if n > 1}
    if duplicates:
        pretty = ", ".join(f"{method} {path}" for (method, path) in sorted(duplicates))
        raise RuntimeError(
            f"Duplicate route registration would silently shadow in FastAPI: {pretty}. "
            "Check the §2.4 include order in app.api.v1.router."
        )
