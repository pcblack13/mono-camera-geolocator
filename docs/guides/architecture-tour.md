# Architecture tour

**A guided read of the system.** Rationale lives in `00-overview.md` and
[`docs/architecture/adr/`](../architecture/adr/); names and laws live in `CONTRACT.md`; **what we are
actually building lives in [`SCOPE.md`](../architecture/SCOPE.md), which overrides the contract.**

---

## 0. The one-page mental model

```
                 SURVEYOR
                    │  marks a landmark on a photo        (a human assertion — ADR-014)
                    │  clicks the same spot on the map    (a DIRECT OBSERVATION — ADR-015)
                    ▼
  ┌────────────────────────────────────────┐
  │ frontend      snake_case wire          │  stageToImage(p) = (p - t)/(s·D)   ← §8.6, ONE site
  │               React Query = server     │  Zustand = browser only            ← L7
  └───────────────┬────────────────────────┘
                  │  POST /api/v1/images/{id}/gcps   →   201 in < 100 ms
                  ▼
  ┌────────────────────────────────────────┐
  │ backend/api    routers → services →    │  ← L6: a select() in a router is a defect
  │                repositories            │  ← L5: no CV in a request handler
  └───────────────┬────────────────────────┘
                  ▼
  ┌────────────────────────────────────────┐
  │ gis            THE ONLY place a CRS    │  ← L3/L4: the georeferencing boundary (ADR-004)
  │                exists. accuracy.py is  │
  │                the only producer of    │
  │                AccuracyEstimate.       │
  └───────────────┬────────────────────────┘
                  ▼
  ┌────────────────────────────────────────┐
  │ PostGIS        geography(Point,4326)   │  ← ADR-008: geom is THE canonical truth
  └────────────────────────────────────────┘

  ┌────────────────────────────────────────┐
  │ ai_engine      ★ DEFERRED (SCOPE.md)   │  ← ABCs + registry + NotImplementedDeferred
  │                pixels in, pixels out   │     ADR-015. Not in this build.
  └────────────────────────────────────────┘
```

★ **`ai_engine` is on the diagram but off the path.** It has ABCs, a registry, a preflight report and
stubs — and **nothing calls into a working body**, because there are none.

---

## 1. Start with three documents, in this order

| # | Document | Why |
|---|---|---|
| **1** | ★ **[`SCOPE.md`](../architecture/SCOPE.md)** | **138 lines. It OVERRIDES the contract.** It tells you the automatic matching engine is **DEFERRED** and that the product is a **manual GCP surveying tool**. Read it before writing a line. |
| **2** | `CONTRACT.md` §0–§3 | How to read it · **the twelve laws** · the canonical folder tree · the file ownership map. Then grep for your section — **do not read all 7339 lines.** |
| **3** | [`adr/ADR-015`](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md) | **Why** the engine is deferred: the oblique-vs-nadir viewpoint problem, and manual mode as **direct observation rather than inference**. |

**Precedence, absolute:**

```
SCOPE.md > CONTRACT.md > 10-database > 20-api > 30-ai-pipeline > 40-imagery > 50-frontend > 00-overview
```

> ★ **`00-overview.md` claims "this document wins conflicts." That claim is VOID.** It was written
> first. It remains authoritative for **rationale** (its ADRs are excellent and binding as *reasoning*)
> and **normative for nothing else.**

---

## 2. The twelve laws, in one table

**A PR violating one is rejected without discussion.**

| | Law | Enforced by |
|---|---|---|
| **L1** | Classical CV is the default and tested path | ★ **SUSPENDED** — `SCOPE.md` §6. The classical path is deferred too. |
| **L2** | The default imagery provider is **keyless** | `esri_world_imagery`; compose with an empty `.env` works |
| **L3** | ★ **`ai_engine` does not know what a CRS is** | CI grep (§10.5) |
| **L4** | ★ **`gis` does not know what a descriptor is** | CI grep (§10.5) |
| **L5** | **The API never performs CV** | A `cv2` import reachable from an `async def` is a defect |
| **L6** | **`backend.api` never touches the DB** | Routers → services → repositories. A `select()` in a router is a defect. |
| **L7** | **The frontend store holds no server data** | API ⇒ React Query. Browser-only ⇒ Zustand. |
| **L8** | **`torch` is imported in exactly one module** | `ai_engine/models/torch_guard.py` |
| **L9** | **snake_case on the wire, in Python AND in TypeScript** | No alias generator, no case-mapping layer |
| **L10** | **Every setting has a working default.** `Settings()` with an empty env **never raises** | `test_settings_zero_env` |
| **L11** | A missing weight/key/optional dep is a **WARNING + fallback** — never a traceback, never silent | Two exceptions, both in §11.0 |
| **L12** | ★ **Refuse rather than answer wrongly** | The gating ladder — and ADR-015 is L12 applied to the roadmap |

**`.importlinter` + `scripts/verify_boundaries.sh` are the gate.** A build failure, not an opinion.

---

## 3. The five places code lives

### `ai_engine/` — pure CV. numpy + cv2 + scipy. ★ DEFERRED.

A **root-level installable package**, not `backend/ai_engine/`. **`import ai_engine` is clean today
with zero installs.**

```
types/       ★ ZERO-HEAVY-IMPORT value types. numpy + stdlib ONLY. Must NOT import ai_engine.models.
models/      the registry — Registry · policy.py (THE only fallback site) · torch_guard.py (L8) · preflight
extractors/  matchers/  geometry/  semantics/  landmarks/  scoring/  heatmap/  pipeline/   ← ★ all DEFERRED
runtime/     cache · parallel · events
windows/     SyntheticWindowSource — procedural farmland + a known ground-truth H
```

★ **`ai_engine/__init__.py` is `__getattr__`-LAZY (PEP 562).** If the package root imported the
pipeline, `gis`'s sanctioned `from ai_engine.types import CandidateWindow` would drag in cv2, scipy and
every extractor — **destroying the exact property that permits the cross-import at all.**
`test_types_import_cheap` asserts it on a fresh interpreter.

★ **In this build every body raises `NotImplementedDeferred`** carrying the module name and a pointer
to `SCOPE.md`. **Never `pass`, never a silent `None`, never a fabricated coordinate.**

### `gis/` — geospatial + imagery. ★ Where the real work happens now.

```
tiles.py       ★ PURE. numpy + stdlib ONLY. Slippy math · quadkeys · 4326↔3857 · geotransforms. The foundation.
crs.py         ★ THE ONLY MODULE THAT MAY IMPORT pyproj OR osgeo.osr. always_xy=True, always.
accuracy.py    ★ px → metres. THE SINGLE PRODUCER of AccuracyEstimate. Never sees a degree or a 3857 metre.
imagery/       ★ THE LEGAL BOUNDARY — base · registry · attribution · cache/ · providers/
elevation/     the fourth provider interface. Default `none` = keyless, offline, TERMINAL.
exports/       csv/geojson/kml/kmz = stdlib, NEVER degrade. shapefile/gpkg/dxf/pdf degrade.
candidates/    ★ THE SEAM — the only place gis imports ai_engine.types
raster.py · rasterio_shim.py     rasterio → GDAL → typed error, bound at CALL time
```

### `backend/` — FastAPI + Celery. The **only** home of fastapi/sqlalchemy/celery/pydantic.

```
api/v1/        routers only. ★ L6: no DB. L5: no CV.
core/          config (env_prefix="LE_") · constants (THE sole home of STAGE_WEIGHTS) · queue.py (the JobQueue Protocol)
db/repositories/  ★ ALL SQL lives here
models/        SQLAlchemy 2.x, Mapped[] style
schemas/       Pydantic v2 — the WIRE contract
services/      orchestration; the ONLY both-sides layer. ★ NOT celery — enqueues via core.queue.JobQueue
tasks/         Celery. ★ tasks/matching.py is the composition root — the only place a live provider
               session and a MatchContext coexist.
```

### `frontend/` — React SPA

```
api/           ★ THE ONLY fetch() in the app. generated/schema.ts is machine-generated; CI byte-compares.
store/         ★ Zustand — LOCAL UI STATE ONLY (L7)
lib/viewport/transform.ts   ★ the two-stage transform (§8.6). Pure. Property-tested.
components/    shell · workspace · image · annotation · map · gcp · export · job · upload · common
```

### `infra/` · `docs/` · `tests/` · `scripts/` · `data/`

★ **Docker is not installed here. Compose files are authored blind and NOT verified** (§13.4 rule 9).

---

## 4. The three boundaries that matter most

### 4.1 The georeferencing boundary (L3/L4 — ADR-004)

> **`ai_engine` begins at pixels and ends at pixels. `gis` is the only module that knows what a CRS is.**

`00-overview.md` calls this *"the most important line in the system"*, and the reason is the bug class:
**a frame confusion does not crash. It produces a coordinate wrong by 108 m that looks plausible in a
CSV.** §13.1 names the test that sits on it: *"`crop_to_bbox` folds the offset into the origin — **this
is the test that catches the ~108 m error that crashes nothing**."*

★ **§13.4 rule 6:** public functions state **units and frames** in their docstrings — `px` vs `m` vs
`deg`; image frame vs window frame vs EPSG:4326. **Most bugs in this system will be a frame confusion;
naming is the cheapest defence.**

### 4.2 The legal boundary (ADR-002)

`gis/imagery/` is where somebody else's pixels enter. **Google Earth is not a provider — it is an
absence**: no module, no registry entry, **no `google_earth` member in the `imagery_provider` PG
enum**. Unrepresentable in the type system.

★ **Legal constraints are enforced mechanically, not by documentation** (§11.5): `allows_caching=False`
makes the cache **refuse the write**; `allows_derivative_export=False` makes the **PDF omit the map
figure**; attribution is a **required field** — *pixels cannot travel without their credit*.

**Read [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) before enabling any keyed provider.**

### 4.3 The layering boundary (L5/L6)

**Routers → services → repositories.** A `select()` in a router is a defect. A `cv2` import reachable
from an `async def` is a defect.

★ **`core/queue.py` (the `JobQueue` Protocol, IU-15) vs `tasks/queue.py` (the Celery impl, IU-20)** is
the pattern that makes this work: **`app.services` never imports celery**, yet a service can enqueue.
Same Protocol/implementation split as `WindowSource` and `ImageStore` — **the side that declares the
Protocol owns the Protocol.**

---

## 5. Follow one request: a manual GCP

```
1. Surveyor clicks the photo.
   frontend/lib/viewport/transform.ts  →  stageToImage(p) = (p - t)/(s·D)
   ★ ORIGINAL image pixel space. Independent of viewer zoom, brightness, contrast.
   D = variant_width / original_width, served on EVERY ImageVariant, non-null, always.
   Without it the entire coordinate model collapses (§12 C-36).

2. Surveyor clicks the satellite map. → EPSG:4326 lat/lon.
   The open correspondence is ZUSTAND (browser-only, L7) — ★ so an uncommitted pair can
   never appear in the GCP table or an export (SCOPE.md §5).

3. On commit:  POST /api/v1/images/{id}/gcps  (React Query mutation)

4. api/v1/gcps.py  → validates, delegates. ★ No SQL here (L6).

5. services/gcp_service.py
   → _adapters.py converts the wire type to a gis type. ★ The ONLY place that happens.
   → gis/accuracy.py computes AccuracyEstimate from imagery GSD + click precision.
     ★ NOT from a homography. dominant_term = "landmark_click" | "georeference".
   → elevation_service: a provider resolves, or BOTH elevation_m and elevation_source stay NULL
     and the response says ELEVATION_UNAVAILABLE. ★ The source may never name a producer that did not run.
   → confidence: stored EXACTLY as sent. ★ Never computed. Never adjusted.

6. db/repositories/gcps.py  → INSERT. geom = geography(Point,4326). source='manual'.
   ★ The CHECK constraints refuse to store a lie:
     ck_gcps_accuracy_total_ge_parts — a quadrature can never be smaller than either leg
     ck_gcps_elevation_source_consistent — (elevation_m IS NULL) = (elevation_source IS NULL)

7. 201 GcpRead. ★ Synchronous — there is nothing to compute. A 202 here would be absurd.
```

**Compare the deferred path:** `POST /images/{id}/match` → **501**, `feature: "deferred"`. Steps 1–7
above are the whole product.

---

## 6. Where the honesty lives

This system's design is unusually preoccupied with **not lying**. The places that matter:

| Mechanism | What it refuses to fake |
|---|---|
| `NotImplementedDeferred` | ★ A deferred body **never** returns a plausible `None` or a fabricated coordinate. |
| **501 + `feature: "deferred"`** | ★ A deferred endpoint is **not a 404** and **never fakes a result**. |
| `elevation_source` consistency | **The source may never name a producer that did not run.** |
| `residual_px = null` on a manual GCP | There is no homography. **`null` is honest; `0` would not be.** |
| `has_direct_fix` | Makes `residual_px IS NULL` **distinguishable** from `residual_px = 0`. |
| `degraded` + `feature_matcher_used` on the row | **The row does not lie about what produced the numbers.** |
| `calibration_id = "identity"`, `calibrated = false` | ★ **Ships uncalibrated and says so.** |
| `accuracy.dominant_term` | *"Your accuracy is limited by the basemap, not the match."* |
| Attribution from the **stored row** | Never re-resolved — the provider may have been reconfigured since. |
| §12.5 "conflicts I deliberately did NOT resolve" | ★ **Four open risks, recorded rather than papered over.** |
| §11.7's *"what this ladder does NOT do"* | ★ **The wrong-field non-defence, stated plainly** after H11 was proved vacuous. |
| `TRACEABILITY.md` | ★ Every deferred capability says **DEFERRED**, loudly. |

> **A stated non-defence is worth more than a check that makes a reviewer feel defended.**

---

## 7. Where to go next

| I want to… | Read |
|---|---|
| Run it | [running-locally.md](running-locally.md) — **no Docker on this machine; that guide is honest about it** |
| Configure it | [configuration.md](configuration.md) — every env var |
| Call it | [api-usage.md](api-usage.md) · [`docs/api/endpoints.md`](../api/endpoints.md) |
| Know what is real | ★ [`TRACEABILITY.md`](../architecture/TRACEABILITY.md) — **every requirement → BUILT or DEFERRED** |
| Understand a decision | [`adr/`](../architecture/adr/) — start with **ADR-015** |
| Add a provider | [adding-a-provider.md](adding-a-provider.md) — **and the legal doc first** |
| Add a CV backend | [adding-a-backend.md](adding-a-backend.md) |
| Contribute | [contributing.md](contributing.md) |
| Work offline | [offline-mode.md](offline-mode.md) |
