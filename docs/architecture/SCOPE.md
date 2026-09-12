# LandExplorer — SCOPE OF THE CURRENT BUILD

> **This document overrides `CONTRACT.md` wherever the two disagree.**
> `CONTRACT.md` describes the *complete* system. This document says which parts of it we are
> building *now*. If the contract specifies a module and this document defers it, it is deferred.
> Read this first, then the contract.

---

## 1. The ruling

**The automatic matching engine is DEFERRED. It is not being implemented in this build.**

The product being built is a **manual GCP surveying tool**: the surveyor marks a landmark in the
uploaded photograph, clicks the corresponding spot on the satellite map, and the geographic
coordinate is recorded directly. Everything else in the contract — upload, metadata, viewer,
annotation, imagery, persistence, exports, deployment — is built in full.

## 2. Why (record this, it is not an arbitrary cut)

Automatic geolocation of a **ground-level oblique photograph** against **nadir satellite imagery**
is the highest-risk component in the design. A planar homography is only strictly valid for a planar
scene or pure rotation; ground-level obliques violate both. The automatic path would have been
unreliable exactly where the product is most used, and a confidently-wrong coordinate handed to a
surveyor is this system's worst failure mode.

Manual mode has none of that risk. There is no homography, so there are no degenerate solves, no
viewpoint assumption, and no estimated confidence to calibrate. **The coordinate is a direct
observation, not an inference.** It is as accurate as the surveyor's eye and the imagery's
resolution, and it works on photographs where automatic matching would simply fail.

It is also the correct build order: the manual correspondences this tool produces are exactly the
**ground-truth dataset** needed to evaluate an automatic engine later. Building the automatic path
first would have meant having nothing to measure it against.

## 3. What is BUILT — in full, production quality

| Area | Status |
|---|---|
| Image upload: JPG, PNG, TIFF, GeoTIFF | **BUILD** |
| Stored metadata: filename, upload date, resolution, EXIF, GPS if present | **BUILD** |
| Image viewer: zoom, pan, brightness, contrast, fullscreen | **BUILD** |
| Annotation toolbar: cursor, point, polygon, polyline, undo, redo, delete | **BUILD** |
| Landmark fields: id, pixel_x, pixel_y, description, confidence, timestamp; every point editable | **BUILD** |
| 2D satellite map: satellite / hybrid / terrain, zoom, pan, synced to app state | **BUILD** |
| Imagery provider abstraction + Esri (keyless default), Mapbox, Bing, Sentinel, Google Static, local GeoTIFF | **BUILD** |
| Server-side tile proxy (API keys never reach the browser) | **BUILD** |
| **Manual GCP mode** — photo pixel ↔ map click → lat/lon | **BUILD** (see §5) |
| GeoTIFF short-circuit: a georeferenced upload yields exact GCPs with no matching at all | **BUILD** |
| Tile math: slippy tiles, Web Mercator, metres-per-pixel, bbox | **BUILD** (needed by the map, proxy, and accuracy reporting) |
| Accuracy reporting in metres on the ground | **BUILD** (`gis/accuracy.py` — sourced from imagery GSD + click precision, **not** from a homography) |
| GCP table: Point ID, Image X, Image Y, Latitude, Longitude, Confidence | **BUILD** |
| Exports: CSV, GeoJSON, Shapefile, KML, PDF report | **BUILD** |
| Manual adjustment mode (refine a placed GCP) | **BUILD** |
| Side-by-side synchronized comparison (photo ↔ satellite) | **BUILD** |
| Version history for annotations and project revisions | **BUILD** |
| Batch processing of multiple uploaded images | **BUILD** — batch upload/metadata/export only; no batch matching |
| PostgreSQL + PostGIS, SQLAlchemy, Alembic | **BUILD** |
| FastAPI, Celery, Redis (async upload/metadata/thumbnail/export jobs) | **BUILD** |
| Docker + Docker Compose + nginx | **BUILD** |
| Developer documentation | **BUILD** |

## 4. What is DEFERRED — typed stubs only

Every item below **keeps its interface, its registry entry, and its tests-for-the-seam**, so it can
be implemented later without touching a single caller. None of it gets a working body.

| Deferred | Disposition |
|---|---|
| Feature extraction: SIFT, ORB, SuperPoint | ABC + registry entry; `raise NotImplementedDeferred` |
| Matching: FLANN, BruteForce, SuperGlue, LightGlue, LoFTR | ABC + registry entry; `raise NotImplementedDeferred` |
| RANSAC homography estimation | ABC only |
| Candidate tile generation + ranking | ABC only |
| Automatic geolocation pipeline / orchestrator | ABC only |
| Camera pose (yaw/pitch/roll) estimation | ABC only |
| Confidence heatmap over candidate camera locations | ABC only |
| Automatic landmark suggestions | ABC only |
| Semantic detection: field borders, roads, canals, trees, greenhouses, buildings, water, crop rows | ABC only |
| Composite score (feature + geometric + landmark + semantic) | ABC only |
| DINOv2, SAM | registry entry only |

### Rules for the deferred surface

1. **The seam is real, not decorative.** `ai_engine` exposes the full ABCs from `CONTRACT.md §4`.
   Callers depend on the ABC, never on a concrete class.
2. **Deferred bodies raise `NotImplementedDeferred`** (in `ai_engine/errors.py`), a *distinct*
   exception carrying the module name and a pointer to this document. Never `pass`, never a silent
   `None`, never fabricated values.
3. **The API surface stays honest.** Endpoints for deferred features (`POST /images/{id}/match`,
   `/suggest-landmarks`, `/segment`, `/camera-pose`, `/heatmap`) are **registered and documented**,
   and return **`501 Not Implemented`** with the uniform error envelope and a `feature: "deferred"`
   marker. They must not 404 (the feature is planned, not absent) and must not fake a result.
4. **The UI states it plainly.** Deferred features appear disabled with an honest tooltip
   ("Automatic matching is not enabled in this build — place GCPs manually"). No spinner that never
   resolves, no fake confidence, no placeholder coordinates.
5. **The DB schema is NOT cut.** `match_jobs`, `match_results`, `camera_pose`, `confidence_heatmap`,
   `semantic_features` tables and their migrations are created as specified. Schema churn later is
   far more expensive than unused tables now. They simply hold no rows in this build.
6. **No weight files. No model downloads. No network at import time.** Unconditionally.

## 5. Manual GCP mode — the feature that replaces matching

This is now the product's core interaction and gets first-class quality.

**Flow.** The surveyor selects a landmark in the photo (an existing annotation point, or clicks a new
one) → the app enters *correspondence* mode → they pan/zoom the satellite map and click the same
physical spot → a GCP is created linking `(pixel_x, pixel_y)` to `(lat, lon)`.

**Requirements.**
- The photo pixel coordinate is stored in **original image pixel space**, independent of viewer zoom
  or brightness/contrast (per `CONTRACT.md`, this conversion is normative and correctness-critical).
- The map click is captured in **EPSG:4326**, stored as `geography(Point, 4326)`.
- Both panes show a live linked marker with a matching colour/ID while the correspondence is open.
- The pairing is **editable and re-openable**: either endpoint can be dragged and re-committed.
- `confidence` in manual mode is a **surveyor-declared** value (a deliberate 1–5 / low-med-high
  judgement), **never** a computed number. The GCP records `source = "manual"` so an automatic GCP
  can never be confused with an observed one downstream or in an export.
- Reported positional accuracy comes from imagery ground-sample-distance and click precision at the
  map's zoom level — a real, defensible number — not from a match score.

**Uncommitted correspondences must never appear in the GCP table or an export.**

## 6. Consequences for the contract

- `CONTRACT.md §2` canonical folder tree stands. Deferred modules exist as files with ABCs and stubs.
- `CONTRACT.md §3` file ownership map stands, minus the deferred implementation units.
- The twelve laws stand, **except** any law that presumes a working matching pipeline.
- `models/policy.py` (the single fallback-policy site) stands, but in this build every deep-model
  path resolves to *deferred*, not to a classical fallback — because the classical path is deferred
  too. The policy module must express that without special-casing callers.
- The test contract stands for everything built. The synthetic known-homography fixtures are still
  created — they are the future engine's acceptance harness, and they cost nothing now.

## 7. Re-enabling later

Implementing the engine must require **zero changes outside `ai_engine/`**, plus flipping the
deferred endpoints from `501` to live and enabling the UI controls. If any implementation in this
build makes that untrue, that implementation is wrong.
