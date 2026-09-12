# LandExplorer REST API — endpoint reference

**Derived from `CONTRACT.md` §7 (the endpoint table) as amended by [`SCOPE.md`](../architecture/SCOPE.md) §4.**
**Base path:** `/api/v1` — applied **once**, in `backend/app/api/v1/router.py`.
**Casing:** ★ **snake_case on the wire, in Python, and in TypeScript** (L9). No alias generator, no
case-mapping layer, anywhere.

---

## ★ Deferred endpoints — read this before anything else

**The automatic matching engine is DEFERRED in this build** ([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)).

**Five endpoints are registered, documented, and return `501 Not Implemented`:**

| # | Endpoint | This build |
|---|---|---|
| **30** | `POST /images/{image_id}/match` | ★ **501 DEFERRED** |
| **43** | `POST /images/{image_id}/suggest-landmarks` | ★ **501 DEFERRED** |
| **47** | `POST /images/{image_id}/segment` | ★ **501 DEFERRED** |
| **48** | `GET /images/{image_id}/camera-pose` | ★ **501 DEFERRED** |
| **49** | `GET /images/{image_id}/heatmap` | ★ **501 DEFERRED** |

**They do not 404** — the feature is *planned*, not *absent*. **They never fake a result.** They return
the uniform `ErrorEnvelope` with a **`feature: "deferred"`** marker:

```json
{
  "error": {
    "code": "NOT_IMPLEMENTED",
    "message": "Automatic matching is not enabled in this build. Place GCPs manually: POST /api/v1/images/{image_id}/gcps. See docs/architecture/SCOPE.md.",
    "status": 501,
    "feature": "deferred",
    "details": null,
    "request_id": "01J5X8QKZ3P7VN2M4RB9TCWDFA",
    "timestamp": "2026-07-17T10:31:02.481Z",
    "docs_url": "https://docs.landexplorer.local/scope#deferred"
  }
}
```

**Switch on `error.code === "NOT_IMPLEMENTED"`, or on `error.feature === "deferred"`.** Both are
stable. `feature` is `null` on every other response.

> **What replaces matching:** endpoint **65** — `POST /images/{image_id}/gcps` — the manual
> correspondence. See [§7](#7-gcps) and [`docs/guides/api-usage.md`](../guides/api-usage.md).

---

## 0. Conventions

| | |
|---|---|
| **Auth** | `LE_AUTH_MODE=none` by default — **no credentials needed**. When set, `PATCH /gcps/{id}` returns `401 MISSING_CREDENTIALS` without a principal (§9.2: *the audit trail is enforced the moment there is more than one person who could be lying*). |
| **Errors** | **Every** non-2xx is an `ErrorEnvelope` — including FastAPI's own validation errors and unhandled exceptions. See [`errors.md`](errors.md). **The single exception:** `GET /health/ready` returns `ReadinessResponse` on 503. |
| **Request id** | Every response carries `X-Request-ID` (ULID), echoed in `error.request_id`. **The string a user pastes into a bug report.** |
| **Async** | ★ **Only seven endpoints initiate async work**: 30, 42, 43, 47, 54, 58, 59. They return **`202 JobRead`** + `Location` + `Retry-After: 1`. **Everything else answers immediately** — *that is the shape of a system where CV never touches a request handler* (L5). |
| **ETags** | `GET` returns `ETag`; `PATCH /annotations/{id}` and `PATCH /gcps/{id}` **require `If-Match`** → `412` on staleness. |
| **Pagination** | `Page[T]`: `items` · `total` · `limit` · `offset`. |
| **Deletes** | Soft by default. `?hard=true` requires the `X-Confirm-Delete` header. |
| **Not under `/api/v1`** | `GET /metrics` (Prometheus, same port, **excluded from OpenAPI** — §12 C-42). |

**Status legend used below:** **LIVE** = fully implemented · ★ **501 DEFERRED** = registered, returns
501 · **LIVE (empty)** = implemented and correct, but returns an empty page in this build because the
table holds no rows.

---

## 1. Health · 2. Capabilities

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 1 | `GET` | `/health` | — | `200 HealthResponse` | **LIVE** |
| 2 | `GET` | `/health/ready` | `verbose`, `check` (csv) | `200`/`503 ReadinessResponse` | **LIVE** |
| 3 | `GET` | `/capabilities` | — | `200 CapabilitiesResponse` | **LIVE** |

**`/health` touches no dependency.** A liveness probe that checks Postgres restarts every API container
when Postgres blips, turning a 30-second hiccup into a full outage.

**`/health/ready` never returns 500.** Every check is individually wrapped; an exception inside a check
becomes `status: "down"` + a message for that component. *A readiness endpoint that can itself throw is
useless precisely when you need it.*

| check | down ⇒ |
|---|---|
| `postgres` (`SELECT 1` + `postgis_version()`) · `redis` (PING) · `storage` (write+read+delete probe) | **`not_ready` → 503** |
| `celery` · `imagery` · `raster` (`rasterio_shim.probe()` → `rasterio`\|`gdal`\|`none`) | `degraded` → **200** |
| `models` (the **cached** `PreflightReport`) | ★ **never** — informational only |

> **Why `degraded` is 200.** With no worker, the API can still serve every read. **Returning 503 would
> take the whole UI offline — including the screens that would tell the operator the workers are
> down.** Only the three dependencies without which *no request can be served correctly* gate readiness.

> **`/capabilities` reads the cached `PreflightReport` and never re-resolves.** Re-sha256'ing a 2.4 GB
> SAM checkpoint per request *is not a health check, it is an outage.* ★ In this build it reports every
> matching component as **deferred**.

---

## 3. Projects

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 4 | `POST` | `/projects` | `ProjectCreate` | `201 ProjectRead` + `Location` | **LIVE** |
| 5 | `GET` | `/projects` | `ProjectListParams` | `200 Page[ProjectSummary]` | **LIVE** |
| 6 | `GET` | `/projects/{project_id}` | `include_deleted` | `200 ProjectRead` + `ETag` · `304` | **LIVE** |
| 7 | `PATCH` | `/projects/{project_id}` | `ProjectUpdate`, `If-Match?` | `200 ProjectRead` | **LIVE** |
| 8 | `DELETE` | `/projects/{project_id}` | `hard`, `X-Confirm-Delete` if hard | `204` | **LIVE** |

`ProjectCreate`: `name` (1–200) · `description?` · `aoi?` (GeoJSON Polygon, 4326, `[lon,lat]`, ≤1000
vertices, ≤10 000 km²) · `default_provider = esri_world_imagery` · `default_extractor = sift` ·
`default_matcher = flann` · `default_estimator = usac_magsac` · `default_search_radius_m = 1000` ·
`default_search_zoom = 18` · `tags = []` · `metadata = {}`.

> ★ `default_extractor` / `default_matcher` / `default_estimator` are **stored and honoured by the
> schema, and unused in this build** — the pipeline that would read them is deferred. They are not
> removed: `SCOPE.md` §4 rule 5 keeps the schema whole so re-enabling touches nothing outside
> `ai_engine/`.

**PATCH uses `UNSET` sentinel semantics:** `{"aoi": null}` **clears** the AOI; `{}` leaves it untouched
and is `400 EMPTY_PATCH`. *Without the sentinel, nullable fields are un-clearable through PATCH.*

---

## 4. Images

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 9 | `POST` | `/images` | `ImageUploadForm` (multipart), `Idempotency-Key?` | `201 ImageRead` · `202 ImageUploadAccepted` | **LIVE** |
| 10 | `GET` | `/images` | `ImageListParams` | `200 Page[ImageSummary]` | **LIVE** |
| 11 | `GET` | `/images/{image_id}` | — | `200 ImageRead` + `ETag` · `304` | **LIVE** |
| 12 | `GET` | `/images/{image_id}/file` | `download`, `Range?` | `200`/`206` binary | **LIVE** |
| 13 | `GET` | `/images/{image_id}/thumbnail` | `ThumbnailParams` | `200` binary | **LIVE** |
| 14 | `GET` | `/images/{image_id}/metadata` | — | `200 ImageMetadataRead` | **LIVE** |
| 15 | `DELETE` | `/images/{image_id}` | `hard`, `X-Confirm-Delete` if hard | `204` | **LIVE** |

**Accepts JPG, PNG, TIFF, GeoTIFF, WebP** — MIME is **sniffed, not trusted from the header**.
`LE_UPLOAD_MAX_BYTES` = 500 MB. Above `LE_ASYNC_INGEST_THRESHOLD_BYTES` (50 MB) ingest goes async and
you get **`202 ImageUploadAccepted`** with a job to poll.

**`201` vs `202` is the whole upload contract:** small file ⇒ processed inline, `201 ImageRead`, ready
to annotate. Large file ⇒ `202`, poll the job, then `GET /images/{id}` for `status: "ready"`.

★ **`ImageVariant` carries `original_width`/`original_height`/`display_scale` on EVERY variant,
non-null, always.** Without `original_width` the client cannot compute `D = variant_width /
original_width`, **and the entire coordinate model collapses** (§8.6, §12 C-36). This is the
frontend's load-bearing field, and it is why a manual GCP's pixel coordinate is in **original image
pixel space** regardless of the variant on screen.

★ **GeoTIFF short-circuit:** a georeferenced upload sets `is_geotiff: true` and its geotransform is
read at ingest, so **exact GCPs are derivable with no matching at all**. `detect_georeferencing()`
distinguishes a real geotransform from **GDAL's identity transform on a plain TIFF** — the exact
distinction that decides `is_geotiff`, and one of the few things in this build that produces a
coordinate without a human click.

---

## 5. Annotations

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 16 | `GET` | `/images/{image_id}/annotations` | `AnnotationListParams` | `200 Page[AnnotationRead]` + `ETag` | **LIVE** |
| 17 | `POST` | `/images/{image_id}/annotations` | `AnnotationCreate` | `201 AnnotationRead` + `ETag` | **LIVE** |
| 18 | `PUT` | `/images/{image_id}/annotations` | `AnnotationBulkUpsertRequest` | `200 AnnotationBulkUpsertResponse` | **LIVE** |
| 19 | `DELETE` | `/images/{image_id}/annotations` | `kind?` (csv), **`X-Confirm-Delete` required** | `200 AnnotationBulkUpsertResponse` | **LIVE** |
| 20 | `GET` | `/annotations/{annotation_id}` | — | `200 AnnotationRead` + `ETag` | **LIVE** |
| 21 | `PATCH` | `/annotations/{annotation_id}` | `AnnotationUpdate`, **`If-Match` REQUIRED** | `200 AnnotationRead` · `412` | **LIVE** |
| 22 | `DELETE` | `/annotations/{annotation_id}` | `If-Match?` | `200 AnnotationRead` (`is_deleted: true`) | **LIVE** |

**`geometry` is GeoJSON-*shaped* but carries IMAGE PIXELS** — `[x, y]`, **y-down**, SRID 0.
★ **`AnnotationCreate` REJECTS a `crs` member.** It is not a geographic geometry and must never be
mistaken for one.

**`confidence` is 0–1 and is the SURVEYOR'S certainty** — never a detector's score
([ADR-014](../architecture/adr/ADR-014-landmarks-are-user-marked.md)). *(Note the deliberate
difference: `GcpRead.confidence` is **0–100**. Two scales, two meanings, both documented.)*

**Endpoint 18 (bulk upsert) is the drag-and-drop path.** `client_ref` echoes your temp id (`tmp-17`)
back with the real UUID so the store can swap it.

---

## 6. Revisions and version history

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 23 | `GET` | `/projects/{project_id}/revisions` | `RevisionListParams` | `200 Page[RevisionSummary]` | **LIVE** |
| 24 | `POST` | `/projects/{project_id}/revisions` | `RevisionCreate` | `201 RevisionRead` | **LIVE** |
| 25 | `GET` | `/revisions/{revision_id}` | `include_snapshot`, `image_id?` | `200 RevisionRead` | **LIVE** |
| 26 | `POST` | `/revisions/{revision_id}/restore` | `RevisionRestoreRequest` | `200 RevisionRestoreResponse` | **LIVE** |
| 27 | `GET` | `/images/{image_id}/annotation-versions` | `AnnotationVersionListParams` (`offset` XOR `before_id`) | `200 Page[AnnotationVersionSummary]` | **LIVE** |
| 28 | `GET` | `/annotations/{annotation_id}/versions` | `AnnotationVersionListParams` | `200 Page[AnnotationVersionSummary]` | **LIVE** |
| 29 | `GET` | `/annotation-versions/{version_id}` | `version_id: int` | `200 AnnotationVersionRead` | **LIVE** |

**Restoring a revision marks affected GCPs stale** — it never recomputes them. See §7.

---

## 7. Matching · Jobs — ★ mostly DEFERRED

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| **30** | `POST` | `/images/{image_id}/match` | `MatchRequest`, `force?`, `Idempotency-Key?` | ~~`202 JobRead`~~ | ★ **501 DEFERRED** |
| 31 | `GET` | `/jobs` | `JobListParams` | `200 Page[JobSummary]` | **LIVE** |
| 32 | `GET` | `/jobs/{job_id}` | `wait: int = 0` (0..30), `If-None-Match?` | `200 JobRead` + `ETag`, `Retry-After` · `304` | **LIVE** |
| 33 | `DELETE` | `/jobs/{job_id}` | — | `200 JobRead` · `202 JobRead` · `409` | **LIVE** |
| 34 | `GET` | `/images/{image_id}/match-results` | `MatchResultListParams` | `200 Page[MatchResultSummary]` | **LIVE (empty)** |
| 35 | `GET` | `/match-results/{match_result_id}` | — | `200 MatchResultRead` | **LIVE** → `404` in practice |
| 36 | `GET` | `/match-results/{match_result_id}/satellite-image` | `overlay`, `format` | `200` binary + `X-Imagery-Attribution` | **LIVE** → `404` in practice |
| 37 | `POST` | `/match-results/{match_result_id}/select` | `MatchResultSelectRequest` | `200 MatchResultRead` | **LIVE** → `404` in practice |
| 64 | `GET` | `/match-results/{match_result_id}/gcps` | `GcpListParams` | `200 Page[GcpRead]` | **LIVE** → `404` in practice |

**Jobs (31–33) are LIVE and matter** — ingest, export and batch all produce jobs. Only the **match**
job type is unreachable.

> ★ **Why 34 returns an empty page rather than 501.** `SCOPE.md` §4 rule 3 names exactly five
> endpoints as 501. Endpoint 34 is a **list of rows in a table that exists and holds nothing**
> (`SCOPE.md` §4 rule 5), and §11.6 is explicit that an empty result set is *"an **empty page**, not a
> 404"*. **An empty page is the honest answer: there are no match results, and the query worked.**
>
> ★ **Why 35/36/37/64 return 404 rather than 501.** These address **a specific row by id**. Since no
> `match_results` row can exist, every id is genuinely not found. **A 404 here is a statement about a
> row, not about a feature** — and the *feature*'s deferral is already stated, loudly, at endpoint 30,
> which is the only way a client could have obtained such an id.

**Job polling** (`useJob`'s contract): `GET /jobs/{id}?wait=5` long-polls up to 5 s; `Retry-After`
tells you when to come back; `If-None-Match` gives you `304` and costs nothing.

---

## 7. GCPs — ★ THE DELIVERABLE

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| **★ 65** | `POST` | `/images/{image_id}/gcps` | **`GcpCreate`** | **`201 GcpRead`** + `Location` | ★ **REQUIRED BY `SCOPE.md` §5 — see the box below** |
| 38 | `GET` | `/images/{image_id}/gcps` | `GcpListParams`, `format=json\|geojson` | `200 Page[GcpRead]` \| `GeoJsonFeatureCollection` | **LIVE** |
| 39 | `GET` | `/gcps/{gcp_id}` | — | `200 GcpRead` + `ETag` | **LIVE** |
| 40 | `PATCH` | `/gcps/{gcp_id}` | `GcpUpdate`, **`If-Match` REQUIRED** | `200 GcpRead` · `412` · `422` | **LIVE** |
| 41 | `POST` | `/gcps/{gcp_id}/reset` | `GcpResetRequest` | `200 GcpRead` (**idempotent**) | **LIVE (constrained)** — resets to `original_geom`, which only an automatic GCP has |
| **★ 66** | `DELETE` | `/gcps/{gcp_id}` | — | `204` | ★ **REQUIRED BY `SCOPE.md` §5** |
| 42 | `POST` | `/images/{image_id}/gcps/recompute` | `GcpRecomputeRequest` | `202 JobRead` · `200 GcpRecomputeDryRun` | **LIVE (constrained)** — refits against a match result; **unreachable in this build** |

> ### ★★ Endpoints 65 and 66 are additions that `SCOPE.md` requires and `CONTRACT.md` §7 does not contain
>
> **`CONTRACT.md` §7 has no endpoint that creates a GCP.** In the contract's world, GCPs are created
> **only by the matching worker**. `SCOPE.md` §5 makes the surveyor's click the product's core
> interaction — **and there is no door for it.**
>
> **`SCOPE.md` overrides `CONTRACT.md`** (SCOPE preamble), so the door must exist. It is documented
> here as endpoints **65** and **66**, and the schema work it depends on is escalated in
> [`TRACEABILITY.md` §4.1](../architecture/TRACEABILITY.md#41--schema-and-api-additions-that-manual-mode-requires--escalated)
> as **S-1 … S-4, release-blocking**:
>
> - **S-1** — `POST /images/{image_id}/gcps` + `DELETE /gcps/{gcp_id}` (IU-17/19/21)
> - **S-2** — ★ **`gcps.match_result_id` is `NOT NULL` with an FK `RESTRICT` to a table that can hold
>   no rows.** As specified, **no GCP can be inserted at all** and manual mode is *unimplementable*.
>   Must become nullable, `NULL` ⇔ `source = 'manual'`. (IU-16/17)
> - **S-3** — `gcps.source` (`gcp_source` enum: `manual` | `automatic`) does not exist, though
>   `SCOPE.md` §5 requires it. Must reach `GcpRead`, `GcpRecord` and the CSV. (IU-16/17/13)
> - **S-4** — `ErrorBody` has no field that can carry `feature: "deferred"`. (IU-15/17/21)

### `GcpCreate` (endpoint 65) — the manual correspondence

```jsonc
{
  "image_px":     { "x": 2113.5, "y": 1204.0 },  // ★ ORIGINAL image pixel space, not viewer space
  "lat":          52.377341,                      // ★ EPSG:4326, from the map click
  "lon":          4.897076,
  "confidence":   80.0,                           // ★ 0-100, SURVEYOR-DECLARED. Never computed.
  "landmark_id":  "0e4d…",                        // optional: the annotation this GCP realises
  "code":         "GCP01",                        // optional: ^[A-Za-z0-9_\-]{1,32}$
  "elevation_m":  null                            // optional; null unless a DEM provider resolves it
}
```

**Server behaviour, normative:**

- **`source = "manual"`** — always. **`match_result_id = null`.** So an automatic GCP can never be
  confused with an observed one, downstream or in an export.
- **`confidence` is stored exactly as sent.** ★ **No server path computes, infers, or adjusts it**
  ([ADR-006](../architecture/adr/ADR-006-confidence-gating.md)). A 1–5 or low/med/high UI maps to
  0–100 **in the client**, deliberately and visibly.
- **`geom` is set from `lat`/`lon`** as `geography(Point, 4326)` — the canonical truth.
- **`accuracy` is computed by `gis/accuracy.py`** from **imagery GSD + click precision at the map's
  zoom level** — a real, defensible number, **not a match score**. `accuracy_dominant_term` is
  `landmark_click` or `georeference`, **never `match`**. `total_ce90_m = sqrt(relative² + georef²)`.
- **`has_direct_fix = true`** — the surveyor's click *is* a direct fix. **`residual_px = null`**:
  there is no homography, so there is no residual. ★ `null` is the honest value; `0` would not be.
- **`elevation_m`/`elevation_source`** are filled by `elevation_service` if a provider resolves,
  else **both `NULL`** and the response carries `ELEVATION_UNAVAILABLE`. ★ **The source may never name
  a producer that did not run.**

**Uncommitted correspondences must never appear in the GCP table or an export** (`SCOPE.md` §5). An
open correspondence is **browser state** (Zustand, L7) until this endpoint is called.

### `PATCH /gcps/{id}` (40) — the two adjustment modes

| Client sends | Server does |
|---|---|
| `lat`/`lon` only | Sets `geom`. Derives `satellite_px` by the **inverse** chain. |
| `satellite_px` only | Sets `satellite_pixel_x/y`. Derives `lat`/`lon` by the **forward** chain. |
| **both** | Forward-projects `satellite_px`, compares to `lat`/`lon`. Within `LE_GCP_CONSISTENCY_TOLERANCE_M` (0.5 m) → accept, `lat`/`lon` authoritative. Beyond → **`422 GCP_ADJUSTMENT_AMBIGUOUS`**. |
| neither (only `code`/`note`/flags) | Metadata-only. **Does not** set `manually_adjusted`. **Renaming a GCP is not adjusting it.** |

★ **`image_px` is NOT adjustable here.** Moving the point *on the photograph* is editing the
annotation (`PATCH /annotations/{id}`), which marks this GCP **stale**. **Two endpoints, two meanings:**
*"the coordinate is in the wrong place"* vs *"I marked the wrong pixel"*.

★ **`confidence` is left untouched by every adjustment.** See
[ADR-006 §5](../architecture/adr/ADR-006-confidence-gating.md).

★ **Staleness is a flag and never an auto-recompute.** A GCP is a coordinate that may already be in a
survey report, a contract, or a machine-control file. **It changes when a human decides it changes.**

---

## 8. Suggestions · Semantics · Pose · Heatmap — ★ DEFERRED

| # | Method | Path | Response | Status |
|---|---|---|---|---|
| **43** | `POST` | `/images/{image_id}/suggest-landmarks` | ~~`202 JobRead`~~ | ★ **501 DEFERRED** |
| 44 | `GET` | `/images/{image_id}/landmark-suggestions` | `200 Page[LandmarkSuggestionRead]` | **LIVE (empty)** |
| 45 | `POST` | `/images/{image_id}/landmark-suggestions/accept` | `200 AnnotationBulkUpsertResponse` | **LIVE** → `404`/empty in practice |
| 46 | `GET` | `/images/{image_id}/semantic-features` | `200 Page[SemanticFeatureRead]` | **LIVE (empty)** |
| **47** | `POST` | `/images/{image_id}/segment` | ~~`202 JobRead`~~ | ★ **501 DEFERRED** |
| **48** | `GET` | `/images/{image_id}/camera-pose` | ~~`200 CameraPoseRead`~~ | ★ **501 DEFERRED** |
| **49** | `GET` | `/images/{image_id}/heatmap` | ~~`200 HeatmapRead`~~ | ★ **501 DEFERRED** |

★ **Note 48 and 49 return 501, not 404**, even though `CameraPoseNotAvailable` / `HeatmapNotAvailable`
(404) exist in the exception hierarchy. **`SCOPE.md` §4 rule 3 names them explicitly**: *"They must not
404 (the feature is planned, not absent)."* A 404 would tell a client *"this image has no pose"* — a
statement about data. The truth is *"nothing in this build computes a pose"* — a statement about the
build. **The distinction is the whole point of the rule.**

**In the UI**, all of these appear **disabled with an honest tooltip** — *"Automatic matching is not
enabled in this build — place GCPs manually"* — **not as a spinner that never resolves**
(`SCOPE.md` §4 rule 4).

---

## 9. Imagery

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 50 | `GET` | `/imagery/providers` | `ProviderListParams` | `200 Page[ProviderInfo]` | **LIVE** |
| 51 | `GET` | `/imagery/providers/{provider}` | — | `200 ProviderInfo` | **LIVE** |
| 52 | `GET` | `/imagery/tiles/{provider}/{z}/{x}/{y}` | `TileParams` (incl. `kind`) | `200` binary · **`204`** | **LIVE** |
| 53 | `GET` | `/imagery/static` | `StaticImageParams` (incl. `kind`) | `200` binary (PNG/JPEG/GeoTIFF) | **LIVE** |

**`kind` = `satellite` | `hybrid` | `terrain`.**

★ **`ProviderInfo.tile_url_template` is the proxy path for EVERY provider by default** — keyed or
keyless (`LE_IMAGERY_DIRECT_TILE_URLS=false`). This preserves the ToS chokepoint, the shared quota
bucket and worker/browser cache identity. See
[ADR-010](../architecture/adr/ADR-010-tile-proxy.md) and
[`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) §3.3.

★ **`204` on a valid tile address with no imagery** (ocean, gap) is deliberate — **not an error**;
Leaflet renders nothing.

**51 serves health from the 30 s cache, never a live probe.** *An endpoint that does a network round
trip per call is a denial-of-service amplifier pointed at a provider whose rate limit we are
contractually obliged to respect.*

**53 is request-scale:** `LE_MAX_STATIC_TILES=16`, `LE_MAX_STATIC_PIXELS=4194304` (4 MP). Beyond ⇒
`422 STATIC_IMAGE_TOO_LARGE`. *A 64-megapixel stitch inside a GET is the workload L5 forbids.*

**51, 52 and 53 are declared `def`, not `async def`** — a synchronous `httpx` call inside an
`async def` blocks the event loop **for the entire worker process**, taking `/health` down with it
(§7.2.1).

---

## 10. Batch

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 54 | `POST` | `/batch` | `BatchCreate` (JSON) \| `BatchUploadForm` (multipart) | `202 BatchRead` | **LIVE (constrained)** |
| 55 | `GET` | `/batch` | `BatchListParams` | `200 Page[BatchSummary]` | **LIVE** |
| 56 | `GET` | `/batch/{batch_id}` | — | `200 BatchRead` | **LIVE** |
| 57 | `DELETE` | `/batch/{batch_id}` | — | `202 BatchRead` · `409` | **LIVE** |

★ **Batch upload / metadata / export only. NO batch matching** (`SCOPE.md` §3) — because matching is
deferred. A batch that requests matching gets the same **501** as endpoint 30.

---

## 11. Exports

| # | Method | Path | Request | Response | Status |
|---|---|---|---|---|---|
| 58 | `POST` | `/images/{image_id}/export` | `ExportRequest`, `format` | `202 JobRead` | **LIVE** |
| 59 | `POST` | `/projects/{project_id}/export` | `ExportRequest`, `format` | `202 JobRead` | **LIVE** |
| 60 | `GET` | `/exports` | `ExportListParams` | `200 Page[ExportSummary]` | **LIVE** |
| 61 | `GET` | `/exports/{export_id}` | — | `200 ExportRead` | **LIVE** |
| 62 | `GET` | `/exports/{export_id}/download` | `Range?` | `200`/`206` binary · `409` · `410` | **LIVE** |
| 63 | `DELETE` | `/exports/{export_id}` | — | `204` | **LIVE** |

**`format`** ∈ `csv,geojson,kml,kmz,shapefile,gpkg,dxf,pdf` (`LE_EXPORT_FORMATS`).

★ **CSV, GeoJSON, KML and KMZ are stdlib-only and can NEVER degrade** — *so the surveyor can always get
their coordinates out, regardless of environment.* Shapefile/GPKG (geopandas/fiona), DXF (ezdxf) and
PDF (reportlab) **degrade to unavailable and are DROPPED from `GET /capabilities`, not crashed on.**
Query `/capabilities` for the live list rather than assuming.

**Export guarantees:** CSV — column order per §4.21, **UTF-8 BOM**, ★ **longitude before latitude**,
8 dp. GeoJSON — RFC 7946, `[lon, lat]`, ★ **no `crs` member**. ★ **A GCP with `elevation_m = null`
exports an EXPLICIT empty cell, never a silent blank.** Every bundle carries `checksum_sha256`.

**`62` returns `409` while the export is still rendering and `410` once it has expired**
(`LE_EXPORT_TTL_SECONDS`, 7 d) — **not a 404**. The distinction between *"not yet"*, *"gone"* and
*"never existed"* is one a client can act on.

★ **Attribution is included by default** (`LE_EXPORT_INCLUDE_ATTRIBUTION=true`) and **should not be
turned off** — several providers' ToS require attribution on derived output. It is served **from the
stored row**, never by re-resolving a provider that may have been reconfigured since.

---

## Related

- [`errors.md`](errors.md) — the error envelope, every code, and the 501 contract.
- [`openapi-notes.md`](openapi-notes.md) — how `openapi.json` is generated and why CI byte-compares it.
- [`docs/guides/api-usage.md`](../guides/api-usage.md) — the same flows as runnable `curl`.
- [`TRACEABILITY.md`](../architecture/TRACEABILITY.md) — every requirement → module → BUILT/DEFERRED.
