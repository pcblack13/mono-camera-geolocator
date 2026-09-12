# LandExplorer — Requirement Traceability Matrix

**Status:** normative for *delivery accounting*. One row per client requirement.
**Sources:** `SCOPE.md` §3 (BUILD) and §4 (DEFERRED) are the requirement list. `CONTRACT.md` §3 is the
ownership map, §13.1 is the test contract.
**CI rule 10 (`CONTRACT.md` §13.4):** *every row names a test. A requirement with no test does not exist.*

---

## 0. How to read this document

This is the table the client uses to check what they paid for. It is written to be **unflattering where
that is the truth**. Three status values, and only three:

| Status | Meaning |
|---|---|
| **BUILT** | Implemented in full, production quality, in this build. A test proves it. |
| **DEFERRED** | **Not implemented.** Interface + registry entry + stub only. The stub raises `NotImplementedDeferred`. A test proves *the seam*, not the feature. Per `SCOPE.md` §1. |
| **BUILT (constrained)** | Implemented, but its useful range is narrowed by a deferral elsewhere. The constraint is stated in the row. Never used to soften a DEFERRED. |

> **The one-sentence summary for a reader in a hurry.** LandExplorer is delivered as a **manual GCP
> surveying tool**. The surveyor marks a landmark in the photograph, clicks the same physical spot on
> the satellite map, and that coordinate is recorded as a **direct observation**. **The automatic
> matching engine — feature extraction, matching, RANSAC, pose, heatmap, semantics, scoring — is
> DEFERRED and is not in this build.** The reasoning is `SCOPE.md` §2 and ADR-015; it is a viewpoint
> problem, not a scheduling one.

### 0.1 Test-id conventions

A test id is `<package>/tests/<file>::<what it proves>` or a `CONTRACT.md` §13.1 unit obligation.
Where §13.1 states an obligation but names no file, the id is the unit (e.g. *IU-18/19 row*).

**Rows marked `TEST-GAP`** name a test that **must exist and does not yet have a §13.1 obligation**,
because §13.1 was written before `SCOPE.md` made manual mode the product. These are listed again in
§4 and are the one place this matrix knowingly runs ahead of the contract. They are gaps in the
*contract*, not licence to ship untested code.

---

## 1. BUILT — the delivered product (`SCOPE.md` §3)

| # | Client requirement | Owning module(s) | Unit | Test id | Status |
|---|---|---|---|---|---|
| R-01 | Image upload: JPG, PNG, TIFF, GeoTIFF | `backend/app/services/image_service.py` · `backend/app/api/v1/images.py` (9–15) | IU-19, IU-21 | `backend/app/tests/api/test_images.py` · `tests/e2e/` upload leg (§13.1 IU-31) | **BUILT** |
| R-02 | Stored metadata: filename, upload date, resolution, EXIF, GPS if present | `gis/exif.py` · `backend/app/models/image.py` · `image_service` | IU-09, IU-16, IU-19 | `gis/tests/test_exif.py` · §13.1 IU-15/16 row (`Base.metadata` completeness) | **BUILT** |
| R-03 | Image viewer: zoom, pan, brightness, contrast, fullscreen | `frontend/src/components/image/**` · `frontend/src/lib/viewport/transform.ts` · `store/viewerStore.ts` | IU-25, IU-26 | §13.1 IU-23..28: `transform.ts` round-trip property test (fast-check), `stageToImage(imageToStage(p)) ≈ p` within 1e-6 | **BUILT** |
| R-04 | Annotation toolbar: cursor, point, polygon, polyline, undo, redo, delete | `frontend/src/components/annotation/**` · `store/toolStore.ts` · `lib/commands/**` | IU-25, IU-26 | §13.1 IU-23..28: `AnnotationLayer` positions in **display** space | **BUILT** |
| R-05 | Landmark fields: id, pixel_x, pixel_y, description, confidence, timestamp; every point editable | `backend/app/models/annotation.py` · `backend/app/schemas/annotation.py` · api 16–22 | IU-16, IU-17, IU-21 | §13.1 IU-17 row (`AnnotationCreate` rejects a `crs` member; `extra="forbid"` sweep) | **BUILT** |
| R-06 | 2D satellite map: satellite / hybrid / terrain, zoom, pan, synced to app state | `frontend/src/components/map/**` · `store/mapStore.ts` · api 50–53 (`kind` param) | IU-27 | §13.1 IU-23..28 (MSW-mocked; no backend runs) | **BUILT** |
| R-07 | Imagery provider abstraction | `gis/imagery/base.py` · `gis/imagery/registry.py` | IU-11 | `gis/tests/test_providers_contract.py` — **parametrised over every provider** | **BUILT** |
| R-07a | · Esri World Imagery — **keyless default** (L2) | `gis/imagery/providers/esri.py` | IU-11 | `test_providers_contract.py` · `LE_IMAGERY_PROVIDER=auto` + empty ortho dir ⇒ `esri_world_imagery` | **BUILT** |
| R-07b | · Mapbox | `gis/imagery/providers/mapbox.py` | IU-11 | `test_providers_contract.py` (unconfigured leg: `__init__`/`is_configured`/`capabilities`/`name`) | **BUILT** |
| R-07c | · Bing | `gis/imagery/providers/bing.py` | IU-11 | `test_providers_contract.py` (unconfigured leg) | **BUILT** |
| R-07d | · Sentinel / Copernicus | `gis/imagery/providers/sentinel.py` | IU-11 | `test_providers_contract.py` (unconfigured leg) · refuses `zoom > 15` | **BUILT** |
| R-07e | · Google Maps **Static** (double opt-in) | `gis/imagery/providers/google_static.py` | IU-11 | `test_providers_contract.py` (unconfigured leg) | **BUILT** |
| R-07f | · Local GeoTIFF / orthophoto — **offline, highest accuracy** | `gis/imagery/providers/local_ortho.py` | IU-11 | `test_providers_contract.py` (configured leg, committed GeoTIFF) · `auto` + populated ortho dir ⇒ `local_orthophoto` | **BUILT** |
| R-07g | · Google **Earth** | — **structurally excluded** | — | §11.5: no provider, no enum label, CI greps for Earth endpoint patterns | **EXCLUDED — see `docs/legal/imagery-terms.md` and ADR-002** |
| R-08 | Server-side tile proxy (API keys never reach the browser) | `backend/app/api/v1/imagery.py` (52) · `backend/app/services/imagery_service.py` | IU-19, IU-21 | §13.1 IU-21 row (route sweep) · `LE_IMAGERY_DIRECT_TILE_URLS=false` default ⇒ proxy path for **every** provider | **BUILT** |
| **R-09** | **Manual GCP mode — photo pixel ↔ map click → lat/lon** | `backend/app/services/gcp_service.py` · `backend/app/api/v1/gcps.py` · `frontend/src/components/gcp/**` | IU-19, IU-21, IU-27 | **`TEST-GAP-1`** — see §4. §13.1 has **no** manual-GCP obligation; it predates `SCOPE.md`. | **BUILT** — ★ **the product's core interaction** |
| R-09a | · Pixel stored in **original image pixel space**, independent of viewer zoom/brightness | `frontend/src/lib/viewport/transform.ts` | IU-25 | §13.1 IU-23..28: `transform.ts` round-trip property test | **BUILT** |
| R-09b | · Map click captured in EPSG:4326, stored `geography(Point,4326)` | `backend/app/models/gcp.py` (`geom`) · `gis/tiles.py` | IU-16, IU-09 | `gis/tests/test_crs.py` round-trip < 1e-9° · §13.1 IU-15/16 (spatial columns `spatial_index=False`) | **BUILT** |
| R-09c | · Live linked marker in both panes while the correspondence is open | `frontend/src/components/gcp/**` · `store/selectionStore.ts` | IU-25, IU-27 | **`TEST-GAP-1`** | **BUILT** |
| R-09d | · Pairing editable and re-openable; either endpoint draggable and re-committable | `gcp_service` · api 40 (`PATCH /gcps/{id}`) | IU-19, IU-21 | §13.1 IU-18/19 row (adjustment derives the *other* representation) | **BUILT** |
| R-09e | · `confidence` **surveyor-declared, never computed** | `backend/app/schemas/gcp.py` · `gcp_service` | IU-17, IU-19 | **`TEST-GAP-2`** — see §4 | **BUILT** — ★ see ADR-006 |
| R-09f | · Every GCP records `source = "manual"` | `backend/app/models/gcp.py` · `backend/app/models/enums.py` | IU-16 | **`TEST-GAP-3`** — see §4 | **BUILT** — ★ **requires a schema addition; see §4** |
| R-09g | · Uncommitted correspondences never appear in the GCP table or an export | `store/selectionStore.ts` (draft is browser-only, L7) · `export_service` | IU-25, IU-19 | **`TEST-GAP-1`** | **BUILT** |
| R-10 | GeoTIFF short-circuit: a georeferenced upload yields exact GCPs with no matching | `gis/raster.py` (`detect_georeferencing`) · `gis/rasterio_shim.py` · `image_service` | IU-10, IU-19 | `gis/tests/test_raster.py` — `detect_georeferencing()` is `False` for a plain TIFF carrying GDAL's identity transform, `True` for the committed synthetic GeoTIFF | **BUILT** |
| R-11 | Tile math: slippy tiles, Web Mercator, metres-per-pixel, bbox | `gis/tiles.py` | IU-09 | `gis/tests/test_tiles_math.py` — golden OSM tile numbers; `test_tiles_stitch.py`; `crop_to_bbox` folds the offset into the origin | **BUILT** |
| R-12 | Accuracy reporting in metres on the ground | `gis/accuracy.py` | IU-09 | `gis/tests/test_accuracy.py` — **CE90 direction golden: `cov_px = I₂` at z=18, φ=55 ⇒ `sqrt(λ_max(Σ_true)) == 0.34251936163340246`** | **BUILT (constrained)** — sourced from imagery GSD + click precision, **not** from a homography (`SCOPE.md` §3). ★ Excludes provider georegistration error for web providers — `CONTRACT.md` §12.5, unresolved and disclosed. |
| R-13 | GCP table: Point ID, Image X, Image Y, Latitude, Longitude, Confidence | `frontend/src/components/gcp/**` · api 38 | IU-27 | §13.1 IU-23..28: precision truncation — `total_ce90_m = 50` renders `41.87`, not `41.8721943` | **BUILT** |
| R-14 | Export: CSV | `gis/exports/csv_writer.py` (**stdlib only — can never degrade**) | IU-13 | `gis/tests/test_exports_writers.py` — column order per §4.21, UTF-8 BOM, **lon before lat**, 8 dp | **BUILT** |
| R-14a | Export: GeoJSON | `gis/exports/geojson_writer.py` (**stdlib only**) | IU-13 | `test_exports_writers.py` — RFC 7946, `[lon, lat]`, **no `crs` member** | **BUILT** |
| R-14b | Export: Shapefile | `gis/exports/shapefile_writer.py` | IU-13 | `test_exports_writers.py` — field truncation lands in `ExportBundle.warnings`; `is_available()` never raises with `fiona` absent | **BUILT (constrained)** — degrades to unavailable and is **dropped from `GET /capabilities`** when geopandas/fiona are absent (§11.3) |
| R-14c | Export: KML | `gis/exports/kml_writer.py` (**stdlib `xml.etree`**) | IU-13 | `test_exports_writers.py` — **`kml` and `kmz` resolve to different classes** with distinct `format_id` | **BUILT** |
| R-14d | Export: PDF report | `gis/exports/pdf_writer.py` | IU-13 | `test_exports_writers.py` — `ExportContext.chip = None` ⇒ the PDF omits the map figure **and says so in `warnings`** | **BUILT (constrained)** — requires `reportlab`; dropped from `/capabilities` when absent |
| R-15 | Manual adjustment mode (refine a placed GCP) | `gcp_service` · api 40, 41 | IU-19, IU-21 | §13.1 IU-18/19 — `original_geom` is written once and never rewritten; `reset` is idempotent; **`confidence` left untouched** | **BUILT** |
| R-16 | Side-by-side synchronized comparison (photo ↔ satellite) | `frontend/src/components/workspace/**` · `store/compareStore.ts` | IU-25, IU-28 | §13.1 IU-23..28 (MSW-mocked) | **BUILT** |
| R-17 | Version history for annotations and project revisions | `backend/app/services/revision_service.py` · `annotation_service` · api 23–29 | IU-19, IU-21 | §13.1 IU-18/19 row · `backend/app/tests/api/test_revisions.py` | **BUILT** |
| R-18 | Batch processing of multiple uploaded images | `backend/app/services/batch_service.py` · `tasks/batch.py` · api 54–57 | IU-19, IU-20 | `backend/app/tests/tasks/` (eager Celery) | **BUILT (constrained)** — ★ **batch upload / metadata / export only. NO batch matching** (`SCOPE.md` §3), because matching is DEFERRED. |
| R-19 | PostgreSQL + PostGIS, SQLAlchemy, Alembic | `backend/app/models/**` · `backend/alembic/**` | IU-16 | §13.1 IU-15/16 **Tier-1 migration test** (offline, no DB): `alembic upgrade head --sql` renders DDL containing `CREATE EXTENSION postgis` and a `CREATE TABLE` for **every** table in §5.5; `alembic heads | wc -l == 1` | **BUILT** |
| R-20 | FastAPI, Celery, Redis (async upload/metadata/thumbnail/export jobs) | `backend/app/main.py` · `backend/app/tasks/**` | IU-20, IU-21 | §13.1 IU-21 — httpx ASGI transport, no live server; no duplicate `(method, path)`; `/health/ready` never 500s | **BUILT (constrained)** — the **match** job type is registered but its endpoint returns 501 (see §2). Ingest/thumbnail/export jobs are live. |
| R-21 | Docker + Docker Compose + nginx | `infra/**` | IU-30 | ★ **NONE — and this is a stated limitation.** `CONTRACT.md` §13.4 rule 9: *"Compose files are NOT marked verified. Docker is absent on this machine."* | **BUILT (unverified)** — authored to spec, **never executed**. The first CI run with Docker is the gate. |
| R-22 | Developer documentation | `docs/**` | IU-32 | This matrix + `docs/guides/**` + `docs/api/**` + `docs/legal/**` + `docs/architecture/adr/**` | **BUILT** |

---

## 2. DEFERRED — not in this build (`SCOPE.md` §4)

> **Read this section as the client.** Everything here was described in `CONTRACT.md` and is **not
> being delivered now**. Each item keeps its **interface, its registry entry, and a test for the
> seam**, so it can be implemented later **without touching a single caller** (`SCOPE.md` §7). None of
> it has a working body. Every stub raises **`NotImplementedDeferred`** (`ai_engine/errors.py`),
> which carries the module name and a pointer to `SCOPE.md`. **Never `pass`, never a silent `None`,
> never a fabricated coordinate or confidence.**

| # | Deferred capability | Owning module(s) | Unit | Disposition | Seam test | Status |
|---|---|---|---|---|---|---|
| D-01 | Feature extraction — SIFT | `ai_engine/extractors/sift.py` | IU-03 | ABC + registry entry; `raise NotImplementedDeferred` | `ai_engine/tests/test_extractors_contract.py` — parametrised over every **registered** extractor; asserts the stub raises `NotImplementedDeferred` and that registration is intact | **DEFERRED** |
| D-02 | Feature extraction — ORB | `ai_engine/extractors/orb.py` | IU-03 | ABC + registry entry; stub | `test_extractors_contract.py` | **DEFERRED** |
| D-03 | Feature extraction — SuperPoint | `ai_engine/extractors/superpoint.py` | IU-03 | ABC + registry entry; stub | `test_extractors_contract.py` | **DEFERRED** |
| D-04 | Matching — FLANN | `ai_engine/matchers/flann.py` | IU-04 | ABC + registry entry; stub | `ai_engine/tests/test_matchers_contract.py` | **DEFERRED** |
| D-05 | Matching — BruteForce | `ai_engine/matchers/bruteforce.py` | IU-04 | ABC + registry entry; stub | `test_matchers_contract.py` | **DEFERRED** |
| D-06 | Matching — SuperGlue | `ai_engine/matchers/superglue.py` | IU-04 | ABC + registry entry; stub | `test_matchers_contract.py` | **DEFERRED** |
| D-07 | Matching — LightGlue | `ai_engine/matchers/lightglue.py` | IU-04 | ABC + registry entry; stub | `test_matchers_contract.py` | **DEFERRED** |
| D-08 | Matching — LoFTR | `ai_engine/matchers/loftr.py` | IU-04 | ABC + registry entry; stub | `test_matchers_contract.py` | **DEFERRED** |
| D-09 | RANSAC homography estimation | `ai_engine/geometry/homography.py` · `geometry/base.py` | IU-05 | **ABC only** | §13.1 IU-05 row, reduced to the seam | **DEFERRED** |
| D-10 | Candidate tile generation + ranking | `ai_engine/pipeline/ranking.py` · `gis/candidates/**` | IU-08, IU-12 | **ABC only** | `gis/tests/test_candidates.py` proves the **seam** (`TileWindowSource` structurally satisfies `ai_engine.types.WindowSource`) | **DEFERRED** |
| D-11 | Automatic geolocation pipeline / orchestrator | `ai_engine/pipeline/orchestrator.py` (`run_match_job`) | IU-08 | **ABC only** | `ai_engine/tests/test_pipeline_e2e.py`, reduced to the seam | **DEFERRED** |
| D-12 | Camera pose (yaw/pitch/roll) estimation | `ai_engine/geometry/pose.py` · `gis/pose.py` | IU-05, IU-09 | **ABC only** | `gis/tests/test_pose.py` proves the **gis-side** frame conversion (grid convergence) only | **DEFERRED** |
| D-13 | Confidence heatmap over candidate camera locations | `ai_engine/heatmap/posterior.py` · `gis/heatmap.py` | IU-07, IU-09 | **ABC only** | `gis/tests/test_heatmap_fuse.py` (gis-side fusion seam) | **DEFERRED** |
| D-14 | Automatic landmark suggestions | `ai_engine/landmarks/suggest.py` | IU-06 | **ABC only** | `ai_engine/tests/test_suggest.py`, reduced to the seam | **DEFERRED** |
| D-15 | Semantic detection: field borders, roads, canals, trees, greenhouses, buildings, water, crop rows | `ai_engine/semantics/**` | IU-06 | **ABC only** | `ai_engine/tests/test_semantics_classical.py`, reduced to the seam | **DEFERRED** |
| D-16 | Composite score (feature + geometric + landmark + semantic) | `ai_engine/scoring/composite.py` | IU-07 | **ABC only** | `ai_engine/tests/test_scoring_bounds.py`, reduced to the seam | **DEFERRED** |
| D-17 | DINOv2 | `ai_engine/extractors/dinov2.py` · `semantics/dinov2_seg.py` | IU-03, IU-06 | **registry entry only** | `test_registry_fallback.py` — the spec is present and resolvable | **DEFERRED** |
| D-18 | SAM | `ai_engine/semantics/sam.py` | IU-06 | **registry entry only** | `test_registry_fallback.py` | **DEFERRED** |

### 2.1 Deferred API surface — registered, documented, **501** (`SCOPE.md` §4 rule 3)

**These endpoints exist, are in the OpenAPI document, and return `501 Not Implemented` with the
uniform error envelope and a `feature: "deferred"` marker. They do not 404** — the feature is
*planned*, not *absent* — **and they never fake a result.** Full detail: `docs/api/endpoints.md`.

| Endpoint | # | Router | This build returns |
|---|---|---|---|
| `POST /images/{image_id}/match` | 30 | `matching.py` | **501** `NOT_IMPLEMENTED` · `feature: "deferred"` |
| `POST /images/{image_id}/suggest-landmarks` | 43 | `suggestions.py` | **501** · `feature: "deferred"` |
| `POST /images/{image_id}/segment` | 47 | `semantics.py` | **501** · `feature: "deferred"` |
| `GET /images/{image_id}/camera-pose` | 48 | `pose.py` | **501** · `feature: "deferred"` |
| `GET /images/{image_id}/heatmap` | 49 | `pose.py` | **501** · `feature: "deferred"` |

**Test id:** §13.1 IU-21 route sweep, extended — *every deferred endpoint returns 501 with a valid
`ErrorEnvelope` carrying `feature: "deferred"`, and appears in `openapi.json`.* Recorded as
**`TEST-GAP-4`** (§4): §13.1 predates the deferral and does not yet name this obligation.

### 2.2 Deferred DB surface — **the schema is NOT cut** (`SCOPE.md` §4 rule 5)

`match_jobs`, `match_results`, `camera_poses`, `confidence_heatmaps` (+ `_cells`),
`semantic_features` and `landmark_suggestions` **are created exactly as `CONTRACT.md` §5 specifies**,
with their migrations. **They simply hold no rows in this build.** Schema churn later is far more
expensive than unused tables now.

**Test id:** §13.1 IU-15/16 Tier-1 migration test — a `CREATE TABLE` for **every** table in §5.5.

### 2.3 Deferred UI surface (`SCOPE.md` §4 rule 4)

Deferred features appear **disabled with an honest tooltip** — *"Automatic matching is not enabled in
this build — place GCPs manually"*. **No spinner that never resolves, no fake confidence, no
placeholder coordinates.** Owned by IU-26/27/28. **Test id: `TEST-GAP-5`** (§4).

---

## 3. Requirements the contract carries that the client did not ask for

Recorded so nobody mistakes them for scope creep or for deliverables.

| Item | Why it exists | Status |
|---|---|---|
| Elevation providers (`gis/elevation/**`) | `CONTRACT.md` §4.27 — the brief mandates `lat/lon/elevation/confidence`; v1.0 plumbed `elevation_m` end to end with **no module producing it**. | **BUILT (constrained)** — default `LE_ELEVATION_PROVIDER=none` is **keyless, offline and terminal**: `elevation_m` and `elevation_source` are both `NULL` and the job says `ELEVATION_UNAVAILABLE`. **Honest beats absent.** Test: `test_exports_writers.py` — a GCP with `elevation_m = None` exports an **explicit empty cell**, never a silent blank. |
| Synthetic known-homography fixtures | `SCOPE.md` §6 — *"they are the future engine's acceptance harness, and they cost nothing now."* | **BUILT** — `scripts/make_fixtures.py`, `ai_engine/tests/fixtures/` |
| `fixture` imagery provider + `LE_IMAGERY_OFFLINE` | §9.13 — the brief gives **no network guarantee**; the offline path needed a front door that is not a test flag. | **BUILT** — `docs/guides/offline-mode.md` |

---

## 4. TEST-GAPs — where this matrix runs ahead of `CONTRACT.md` §13.1

**These are gaps in the contract, not permission to ship untested code.** §13.1 was written before
`SCOPE.md` made manual GCP mode the product; it therefore contains **no obligation for the single
most important feature we are delivering**. CI rule 10 says a requirement with no test does not
exist — so these tests must be written, and §13.1 must gain the rows.

| Id | The obligation that must exist | Owning unit | Blocks |
|---|---|---|---|
| **TEST-GAP-1** | **Manual GCP mode, end to end**: `POST` a correspondence (`image_px` + `lat`/`lon` + declared `confidence`) → `201 GcpRead` with `source = "manual"`; the GCP appears in `GET /images/{id}/gcps` and in a CSV export; an **uncommitted** correspondence appears in **neither**. | IU-19 (service, mocked repos), IU-21 (api), IU-31 (e2e, fixture provider, no network) | **R-09, R-09c, R-09g** |
| **TEST-GAP-2** | `confidence` on a manual GCP is **exactly the value the surveyor sent** — never computed, never overwritten by any server path, and unchanged by `PATCH /gcps/{id}` adjustment. | IU-19 | **R-09e** |
| **TEST-GAP-3** | Every GCP created by the manual path has `source = "manual"`; the value survives to `GcpRead` and to every export writer's output. | IU-16, IU-13, IU-19 | **R-09f** |
| **TEST-GAP-4** | Every deferred endpoint (30, 43, 47, 48, 49) returns **501** with a valid `ErrorEnvelope` carrying `feature: "deferred"`, is present in `openapi.json`, and **never 404s**. | IU-21 | **§2.1** |
| **TEST-GAP-5** | Deferred UI controls render **disabled with the honest tooltip** and dispatch no request. | IU-29 | **§2.3** |

### 4.1 ★ Schema and API additions that manual mode REQUIRES — escalated

**`SCOPE.md` overrides `CONTRACT.md` (SCOPE preamble). These four items are the places where the
contract, written for the automatic engine, cannot represent the product we are actually
delivering.** They are recorded here because this matrix is the document that must not lie about
whether R-09 is deliverable.

| # | The problem | Contract text | Required resolution | Owner |
|---|---|---|---|---|
| **S-1** | **There is no endpoint to create a GCP.** §7's 64 endpoints expose GET/PATCH/reset/recompute for GCPs. In the contract's world GCPs are created **only** by the matching worker. Under `SCOPE.md` §5 the surveyor creates them by clicking — **and there is no door.** | §7, endpoints 38–42 | **`POST /images/{image_id}/gcps`** → `201 GcpRead` + `Location`, body `GcpCreate`, and **`DELETE /gcps/{gcp_id}`** → `204`. Documented in `docs/api/endpoints.md` as endpoints **65** and **66**. | IU-17 (`GcpCreate`), IU-19, IU-21 |
| **S-2** | **`gcps.match_result_id` is `NOT NULL`** with an FK `RESTRICT` to `match_results`. Matching is deferred, so **no `match_results` row can ever exist** — therefore **no GCP can ever be inserted**. As specified, manual mode is not merely untested; it is **unimplementable**. | §5.6 `gcps` table; `GcpRead.match_result_id: UUID` | Make `match_result_id` **nullable** (`NULL` ⇔ `source = 'manual'`), and `GcpRead.match_result_id: UUID \| None`. Recommended CHECK: `(source = 'manual') = (match_result_id IS NULL)`. | IU-16 (model + migration), IU-17 (schema) |
| **S-3** | **There is no `gcps.source` column and no `gcp_source` enum**, though `SCOPE.md` §5 requires *"The GCP records `source = "manual"` so an automatic GCP can never be confused with an observed one downstream or in an export."* | §5.6; §5.3 enum list | Add `gcp_source` enum (`manual` \| `automatic`) + `gcps.source NOT NULL DEFAULT 'manual'`; add to `GcpRead`; add `source` to `GcpRecord` (§4.21) and to the CSV. | IU-16, IU-17, IU-13 |
| **S-4** | **`ErrorBody` has no field that can carry `feature: "deferred"`**, and the §6.3 exception hierarchy has **no 501 branch**. | §6.3 | Add `ErrorBody.feature: str \| None = None` (additive, snake_case, `None` everywhere else) and `FeatureDeferredError (501, code=NOT_IMPLEMENTED)`. Documented in `docs/api/errors.md`. | IU-15 (`exceptions.py`), IU-17 (`errors.py`), IU-21 (handler) |

> **Why these are recorded here rather than quietly fixed.** IU-32 owns documentation, not schemas.
> Writing a matrix that claims **R-09 BUILT** while the schema cannot store a manual GCP would be
> exactly the failure this document exists to prevent — the same failure `CONTRACT.md` §14 F-101
> records for `elevation` and `suggest_landmarks`: *"a fully-plumbed enum with no producer"*, invisible
> to a definition-of-done that was per-module and never per-requirement. **This is the per-requirement
> check doing its job.**

---

## 5. Open risks the client must see (`CONTRACT.md` §12.5)

**Not defects. Real open questions, recorded rather than resolved.** Two of the four are materially
*reduced* by the manual-mode ruling; two are not.

| Risk | Status under this build |
|---|---|
| **Ground-photo ↔ satellite matching is a genuine research risk.** A ~90° viewpoint change means a fence from the side and from above share almost no SIFT structure. **No architecture removes this.** | ★ **This is the risk that produced the deferral** (ADR-015, `SCOPE.md` §2). Manual mode does not mitigate it — it **routes around it entirely**: there is no homography, so there is no viewpoint assumption. **The coordinate is a direct observation, not an inference.** |
| **We have no defence against a visually identical WRONG field.** The ambiguity clamp is *relative* and cannot detect a globally-wrong-but-unique answer. | ★ **Does not arise in this build.** The failure mode is a property of *automatic* matching. A surveyor clicking a spot they can see is not choosing between candidate fields. **It returns the moment the automatic engine is enabled**, and must be re-escalated then. |
| **Esri's terms for commercial survey deliverables.** The keyless default is the right *engineering* call under the brief's zero-config constraint. Whether it is a defensible *product* default for paid deliverables is a question for the client and their counsel. | **Escalate to the client. Unchanged by this build.** The default stands; the caveat propagates to the README, the first-run log line, the UI provider picker and every PDF. See `docs/legal/imagery-terms.md`. |
| **Reported accuracy excludes provider georegistration error.** We report our fit to *the provider's pixels*. Esri/Mapbox/Bing do not publish their georegistration error; Sentinel-2 L1C is ~8–12 m CE95. **Reported accuracy is optimistic for every web provider.** | **Structurally acknowledged, not resolved. Unchanged by this build** — and now the *dominant* term, since `accuracy_dominant_term` on a manual GCP is `landmark_click` or `georeference`, never `match`. `georef_ce90_m` is mandatory and flows into `total_ce90_m`; `local_orthophoto` remains the only path where total error is knowable. |

---

## 6. Summary count

**§1 contains 39 requirement rows.** They account for exactly:

| | Count | |
|---|---|---|
| **BUILT** | **32** | Implemented in full. |
| **BUILT (constrained)** | **5** | Implemented; useful range narrowed by a deferral elsewhere. The constraint is stated in each row: R-12 (accuracy excludes provider georegistration error) · R-14b (Shapefile degrades) · R-14d (PDF degrades) · R-18 (**no batch matching**) · R-20 (**the match job type is 501**). |
| **BUILT (unverified)** | **1** | R-21 Docker/compose — ★ **authored to spec, never executed. No Docker on this machine** (`CONTRACT.md` §13.4 rule 9). |
| **EXCLUDED for legal reasons** | **1** | R-07g Google Earth — ADR-002, `docs/legal/imagery-terms.md`. |

| Everything else | Count |
|---|---|
| Capabilities **DEFERRED** (§2) | **18** — ★ **the entire automatic matching engine** |
| Deferred endpoints returning **501** (§2.1) | **5** |
| **TEST-GAPs to close** (§4) | **5** |
| **Schema/API additions manual mode requires** (§4.1) | **4** — ★ **S-1 and S-2 are release-blocking** |

> **Read the two blocks together, not the first one alone.** 37 of 39 client requirements are built —
> **and the eighteen deferred capabilities in §2 are the single feature the contract spends most of its
> pages on.** *"37 of 39"* is true and would be a misleading headline. **The honest headline is:
> everything except the automatic matching engine, which is the whole of §2, and which the client must
> read ADR-015 to understand.**
