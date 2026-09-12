# LandExplorer — THE INTERFACE CONTRACT

**Status:** LAW. Supersedes all six specialist documents wherever they differ.
**Owner:** Technical Lead.
**Version:** 2.0 · 2026-07-17 — repair-and-extend pass. Four audits (composability, feasibility, math/geodesy, completeness) raised 105 findings; every one is resolved in-document or explicitly recorded as not-a-defect in **§14 Critic Findings and Resolutions**. §14 is normative: it is the changelog AND the ruling table.

---

## 0. How to read this document

Six specialists designed LandExplorer in parallel. They agreed on the hard things and disagreed at every seam — package roots, table names, provider keys, env prefixes, wire casing, and who owns coordinate reference systems. This document resolves every disagreement and is the only file an implementation agent needs.

**Precedence, absolute:**

```
CONTRACT.md  >  10-database.md  >  20-api.md  >  30-ai-pipeline.md  >  40-imagery.md  >  50-frontend.md  >  00-overview.md
```

`00-overview.md` claims "this document wins conflicts." **That claim is void.** It was written first, before the specialists discovered that its `photos`/`landmarks` vocabulary, its endpoint list, and its `01-ai-engine.md` doc numbering had all been superseded. It remains authoritative for **rationale** (the ADRs are excellent and still binding as *reasoning*), and normative for nothing else. Where §12 of this contract does not name a conflict, the specialist docs stand as elaboration.

**If this contract does not answer your question**, the answer is in the specialist doc for your module — read it for rationale, and follow this contract for names.

**Do not edit the six specialist docs.** They are the design record. Corrections land here.

### 0.1 Verified environment facts (checked on the dev machine, not assumed)

| Fact | Value | Consequence |
|---|---|---|
| Python | 3.12.3 | `X \| None`, `StrEnum`, `Self`. No PEP 695. |
| OpenCV | 4.13.0 | `SIFT_create`, `USAC_MAGSAC`, `FlannBasedMatcher`, `UsacParams.randomGeneratorState` all present. |
| **`cv2.xfeatures2d`** | **ABSENT** | No opencv-contrib. **SURF/BEBLID/VGG/LATCH are unavailable and must not be referenced.** Classical path = SIFT, ORB, AKAZE, BRISK only. |
| NumPy | 2.4.3 | NumPy-2 ABI. |
| torch / torchvision | 2.11.0+cu130 / 0.26.0+cu130 | Importable. |
| **`torch.cuda.is_available()`** | **False** | **No usable GPU despite the cu130 wheel.** `LE_AI_DEVICE=auto` → `cpu`. Never infer CUDA from a build name. |
| GDAL / osgeo | 3.8.4 | Raster IO works today **without** rasterio. |
| SciPy / PIL | 1.17.1 / 12.1.1 | Available. |
| fastapi, sqlalchemy, pydantic, celery, redis, rasterio, geopandas, shapely, pyproj, kornia, reportlab, **httpx**, **fiona**, **ezdxf** | **NOT installed** | Live in `requirements.txt` / package extras. **`ai_engine` and `gis` must IMPORT with zero RUNTIME installs** — see the two rows below for what that does and does not claim. |
| **pytest, pytest-asyncio, hypothesis** | **NOT installed** | ★ The test *runner* is not a runtime dep. **"Zero installs" covers RUNTIME deps only.** Before any suite runs: `pip install -e ./ai_engine[dev] --no-deps && pip install -e ./gis[dev] --no-deps`. `hypothesis` ships in both `[dev]` extras (§2.2/§2.3). Corrects the three places v1.0 claimed "`pytest` is green today with zero installs" (§2.2, §9.13, §10.6) — the *imports* are green with zero installs; the *runner* is one `[dev]` install away. |
| **node / npm / pnpm** | node ✔ · npm ✔ · **pnpm ABSENT** | `corepack enable && corepack prepare pnpm@9 --activate` in `bootstrap_dev.sh` before any frontend work. §2.5 mandates `pnpm-lock.yaml`. `fast-check` (IU-23's property test) ships in `devDependencies`. |
| **cv2, numpy, scipy, torch, osgeo** | **system-site packages** | ★ A plain `python -m venv` **hides all five**, and `osgeo` cannot be pip-installed at all. `scripts/bootstrap_dev.sh` MUST use `python -m venv --system-site-packages .venv` and `pip install -e … --no-deps` (§2.9). The one script whose job is making the repo runnable here is the one most able to break it. |
| Docker | **not installed** | Compose files are authored blind. **No task may be marked "verified" on the basis of a compose file.** |
| Model weights | **will not be downloaded** | Every deep backend is lazy + gracefully degrading. A missing `.pth` is a log line and a fallback. |

> **★ The call-time binding rule (normative, §11.3).** Every one of the NOT-installed rows above is a module that some part of `gis` must nonetheless be able to *import* and *introspect*. Therefore: **any module whose dependency is not in its package's base install binds that dependency INSIDE the function that uses it, never at module scope.** `is_available()` / `is_configured()` / `capabilities()` must be importable and callable with the dependency absent. v1.0 mandated this for exactly one module (`rasterio_shim.py`) and then shipped `gis/imagery/http.py` (httpx), `gis/imagery/cache/redis_cache.py` (redis) and four export writers with module-scope imports — which made `cd gis && pytest` die at **collection**, before a single test ran. The rule is now general and is tested (§13.1 IU-11/IU-13).

---

## 1. The twelve laws

These are not guidelines. A PR violating one is rejected without discussion.

**L1 — Classical CV is the default path and the tested path.** SIFT → FLANN + Lowe ratio → `cv2.USAC_MAGSAC` runs the whole product end to end. Deep models are optional accelerants. If every weight file vanished, the only observable change is accuracy and a set of `INFO` log lines. (`ai_engine/tests/test_registry_fallback.py` is the regression test.)

**L2 — The default imagery provider is keyless.** `docker compose up` with an empty `.env` yields a working satellite search via `esri_world_imagery`. Keyed providers are strictly opt-in.

**L3 — `ai_engine` does not know what a CRS is.** No pyproj, no EPSG, no `lat`, no `lon`, no `z/x/y`. It begins at pixels and ends at pixels. **CI gate: §10.5 is the single normative definition of the grep — this law does not restate it.** (v1.0 stated L3's and L4's patterns *twice*, in §1 and §10.5, with different tokens each time — `orb` vs `orb_create`, and §10.5 adding `quadkey|geodesic`. Two definitions of one gate is two gates.)

**L4 — `gis` does not know what a descriptor is.** No SIFT, no ratio test, no RANSAC, no homography estimation. It ends at pixels + a geotransform. **CI gate: §10.5, normatively and only.**

**L5 — The API never performs CV.** Any OpenCV/Torch operation heavier than EXIF parsing or one thumbnail downsample runs in Celery. A `cv2` import reachable from an `async def` route is a defect. (Tile proxying is IO and is exempt.)

**L6 — `backend.api` never touches the DB.** Routers → services → repositories. A `select()` in a router is a defect.

**L7 — The frontend store holds no server data.** From the API ⇒ React Query. Browser-only ⇒ Zustand.

**L8 — `torch` is imported in exactly one module:** `ai_engine/models/torch_guard.py`.

**L9 — snake_case on the wire, in Python, and in TypeScript.** One name per field, everywhere. No alias generator, no case-mapping layer. (§8.1)

**L10 — Every setting has a working default. `Settings()` with an empty environment never raises.** Zero required env vars.

**L11 — A missing weight, key, or optional dependency is a WARNING and a fallback — never a traceback, and never silent.** It is never a 4xx/5xx **when it affects a DEFAULT**. It has exactly **two** exceptions, both of which are the law working rather than breaking:
> (a) an **explicitly requested** unavailable *provider* → `503 PROVIDER_NOT_CONFIGURED`; (b) any unavailability under `LE_IMAGERY_STRICT=true` / `LE_AI_STRICT_BACKEND=true` → raise. (§11.4)
>
> Note the deliberate asymmetry, made explicit here so nobody "fixes" it: an explicitly requested unconfigured **provider** is a 503, but an explicitly requested missing **weight** (`matcher:"superglue"`) is a `202` + fallback + `WarningItem`. **Imagery changes the answer's provenance; a matcher changes only its accuracy.** Both are reported; only one is refusable. §11.1's Request row and §11.4's last row cross-reference each other saying so. *A law with unstated exceptions gets applied literally by whoever implements it — v1.0's L11 read as an absolute and §11.4 contradicted it twice.*

**L12 — Refuse rather than answer wrongly.** A GCP is a survey coordinate someone may dig, build, or file against. Confidence gating, degeneracy rejection, and honest `degraded` reporting outrank result availability. (§11.4)

---

## 2. The canonical folder tree

Every file that will exist. **This is law.** If you need a file not listed here, add it in the spirit of the tree and flag it in your PR description.

Paths are relative to `/home/yahi/Desktop/landexplorer`.

### 2.1 Repo root

```text
landexplorer/
├── README.md                       # quickstart: clone → compose up → upload → GCPs. States the Esri ToS caveat.
├── LICENSE
├── .gitignore
├── .dockerignore
├── .editorconfig
├── .env.example                    # EVERY var from §9, commented, all defaults. Copying it is OPTIONAL.
├── .importlinter                   # §10 contracts — the CI boundary gate
├── .pre-commit-config.yaml         # ruff · black · mypy · eslint · prettier · import-linter
├── Makefile                        # up down test lint migrate seed fmt check-env verify-boundaries
├── pyproject.toml                  # workspace root: ruff/black/mypy/pytest config. NOT a package.
├── ai_engine/                      # §2.2  installable package
├── gis/                            # §2.3  installable package
├── backend/                        # §2.4  FastAPI + Celery
├── frontend/                       # §2.5  React SPA
├── infra/                          # §2.6  Docker, compose, nginx, postgres
├── docs/                           # §2.7
├── tests/                          # §2.8  cross-package only
├── scripts/                        # §2.9
└── data/                           # §2.10 gitignored runtime artefacts
```

### 2.2 `ai_engine/` — pure CV. numpy + cv2 + scipy only.

**Root-level package, not `backend/ai_engine/`** (§12 C-02). `pip install -e ./ai_engine --no-deps` (deps are system-site here — §0.1). **`import ai_engine` is clean today with zero runtime installs**; `cd ai_engine && pytest` is green after `pip install -e ./ai_engine[dev] --no-deps` (pytest is not installed — §0.1).

```text
ai_engine/
├── pyproject.toml                  # name="landexplorer-ai-engine"
│                                   #   extras: [deep] (torch, torchvision)
│                                   #           [dev]  (pytest, pytest-asyncio, hypothesis, mypy, ruff)
├── README.md                       # "use this without the web app" + weight install guide
└── src/ai_engine/
    ├── __init__.py                 # ★ re-exports ONLY: run_match_job · suggest_landmarks · AiEngineConfig
    │                               #   · Registry · version(). MUST NOT import pipeline/extractors at module
    │                               #   scope — it is __getattr__-LAZY (PEP 562). Rationale in §10.3: if the
    │                               #   package root imported the pipeline, gis's sanctioned
    │                               #   `from ai_engine.types import CandidateWindow` would drag in cv2, scipy
    │                               #   and every extractor, destroying the exact property that permits the
    │                               #   cross-import at all.
    ├── py.typed
    ├── version.py                  # ENGINE_VERSION + per-component *_VERSION (cache-key inputs)
    ├── config.py                   # AiEngineConfig + the 4 sub-configs (§4.15). stdlib dataclasses. NOT pydantic.
    ├── errors.py                   # exception hierarchy (§4.1) — incl. WindowFetchError
    ├── logging.py                  # logging.getLogger("ai_engine.*"). NEVER configures handlers.
    │
    ├── types/                      # ★ ZERO-HEAVY-IMPORT value types. numpy + stdlib ONLY.
    │   │                           #   ★ MUST NOT import ai_engine.models — see provenance.py below.
    │   ├── __init__.py             #   re-exports every dataclass; the ONLY import site downstream uses.
    │   │                           #   Also declares the ProgressCallback type alias (§4.13).
    │   ├── enums.py                #   DescriptorKind · HomographyMethod · ViewRegime · Severity · Device
    │   │                           #   · SemanticClass ★ (parity leg 3 — §5.3)
    │   ├── provenance.py           #   ★ NEW. ComponentKind · ComponentSpec · Resolution · ResolutionReport
    │   │                           #   · PreflightReport. MOVED here from models/spec.py: types/results.py
    │   │                           #   needs ResolutionReport, and types MUST NOT import models (§14 F-01).
    │   ├── cache.py                #   ★ NEW. ImageStore(Protocol) · CacheBackend(Protocol). Declared HERE
    │   │                           #   so types/features.py can name ImageStore without importing runtime/.
    │   ├── features.py             #   FeatureSet · ImageRef · ExtractorCapabilities
    │   ├── matches.py              #   MatchSet · Correspondences · CorrespondenceRequest
    │   ├── geometry.py             #   HomographyResult · RansacConfig · PoseResult · CameraIntrinsics
    │   ├── degeneracy.py           #   DegeneracyCheck · DegeneracyReport
    │   ├── landmarks.py            #   Landmark · LandmarkSet · LandmarkEvidence · LandmarkFix
    │   │                           #   · LandmarkWeightField ★ · LandmarkProposal ★ · SuggestionStrategy ★
    │   ├── windows.py              #   ★ CandidateWindow · WindowSource(Protocol) · WindowRef
    │   ├── semantics.py            #   SemanticMap · SemanticCapabilities ★ · CropRowField · TreeLattice · RidgeSet
    │   ├── scoring.py              #   ScoreEvidence · ScoreResult · ScoreTerms
    │   ├── heatmap.py              #   PixelHeatmap · HeatmapComponent
    │   └── results.py              #   WindowResult · MatchJobResult · GcpPixelFix · PixelAccuracy
    │
    ├── models/                     # backend registry — the graceful-degradation engine
    │   ├── __init__.py             #   Registry singleton + register() decorator + _ensure_registered()
    │   ├── spec.py                 #   ★ RE-EXPORT SHIM ONLY: `from ai_engine.types.provenance import *`.
    │   │                           #   Kept so `from ai_engine.models.spec import ComponentSpec` still reads
    │   │                           #   naturally at the registration sites. Declares nothing of its own.
    │   ├── registration.py         #   ★ NEW (IU-02). Its SOLE job: import every module carrying a
    │   │                           #   @register decorator, so Registry.specs() is non-empty. Mirrors
    │   │                           #   gis/imagery/providers/__init__.py. Imported ONLY by
    │   │                           #   _ensure_registered(), lazily, at first resolve() — never at
    │   │                           #   ai_engine.models import time (that would cycle: models→extractors→models).
    │   ├── policy.py               #   ★ resolve_with_fallback() — THE ONLY place fallback policy exists
    │   ├── weights.py              #   WeightManifest · resolve_weight_path(). NEVER downloads. NEVER raises.
    │   ├── device.py               #   select_device() — "auto" → "cpu" here
    │   ├── torch_guard.py          #   ★ try_import_torch() → module|None. THE ONLY torch import site (L8).
    │   └── preflight.py            #   preflight(config) → PreflightReport. ★ Runs ONCE in main.py's
    │                               #   lifespan; the report is cached on app.state (§11.1). GET /capabilities
    │                               #   READS the cache and never re-resolves — re-sha256'ing a 2.4 GB SAM
    │                               #   checkpoint per request is not a health check, it is an outage.
    │
    ├── extractors/
    │   ├── __init__.py
    │   ├── base.py                 # FeatureExtractor ABC
    │   ├── preprocess.py           # CLAHE · grayscale · resize · gamma. Shared.
    │   ├── sift.py                 # SiftExtractor            ★ DEFAULT · TERMINAL FALLBACK
    │   ├── orb.py                  # OrbExtractor             ★ TERMINAL FALLBACK · binary
    │   ├── akaze.py                # AkazeExtractor           (main-module OpenCV, NOT contrib)
    │   ├── brisk.py                # BriskExtractor           (main-module OpenCV, NOT contrib)
    │   ├── asift.py                # AffineSimulatedExtractor (decorator over any extractor)
    │   ├── superpoint.py           # SuperPointExtractor      [weights, lazy]
    │   └── dinov2.py               # Dinov2DenseExtractor     [weights, lazy]
    │
    ├── matchers/
    │   ├── __init__.py
    │   ├── base.py                 # Matcher ABC · DetectorFreeMatcher ABC
    │   ├── bruteforce.py           # BruteForceMatcher        ★ TERMINAL FALLBACK
    │   ├── flann.py                # FlannMatcher             ★ DEFAULT · TERMINAL FALLBACK
    │   ├── filters.py              # lowe_ratio · mutual_nn · spatial_gate · dedupe_many_to_one
    │   ├── sources.py              # ★ CorrespondenceSource Protocol + Detect/DetectorFree/Ensemble
    │   ├── superglue.py            # SuperGlueMatcher         [weights, lazy]
    │   ├── lightglue.py            # LightGlueMatcher         [weights, lazy]
    │   └── loftr.py                # LoFTRMatcher(DetectorFreeMatcher) + LoFTRAsMatcher (lossy shim)
    │
    ├── geometry/                   # ★ PIXEL SPACE ONLY. NO CRS. EVER. (L3)
    │   ├── __init__.py
    │   ├── base.py                 # GeometryEstimator ABC
    │   ├── homography.py           # OpenCvHomographyEstimator
    │   ├── normalize.py            # hartley_normalize() · denormalize_h()
    │   ├── refine.py               # refine_symmetric_transfer() → (H, cov) via scipy LM
    │   ├── degeneracy.py           # ★ DegeneracyValidator — H1–H13 hard, S1–S8 soft (§4.9)
    │   ├── pose.py                 # PoseEstimator: Zhang-plane primary, decomposeHomographyMat fallback
    │   ├── intrinsics.py           # intrinsics_from_exif() · intrinsics_from_fov() · AgriVanishingPointCalibrator
    │   ├── rectify.py              # horizon_to_rectifier() · vanishing_points_from_croprows()
    │   └── uncertainty.py          # propagate_point_cov() — PIXEL covariance only. Metres are gis's job.
    │
    ├── windows/                    # candidate windows arrive from gis; ai_engine never fetches
    │   ├── __init__.py
    │   └── testing.py              # ★ SyntheticWindowSource — procedural farmland + known ground-truth H
    │
    ├── semantics/
    │   ├── __init__.py
    │   ├── base.py                 # SemanticSegmenter ABC
    │   ├── classical.py            # ClassicalSemantics  ★ DEFAULT · TERMINAL FALLBACK
    │   ├── indices.py              # exg() · gli() · ndwi() · mndwi()
    │   │                           #   ★ ndwi/mndwi require NIR/SWIR: they read
    │   │                           #   CandidateWindow.extra_bands and RAISE ValueError when absent.
    │   │                           #   ClassicalSemantics gates on supports_multispectral and uses the
    │   │                           #   HSV heuristic otherwise, recording provenance="hsv_heuristic".
    │   ├── croprows.py             # structure-tensor + FFT row/lattice estimation
    │   ├── ridges.py               # multi-scale Hessian vesselness (roads/canals)
    │   ├── structures.py           # ★ NEW (IU-06). greenhouse · building · water_body detection:
    │   │                           #   rectangularity + fill + shadow-azimuth per 30-ai-pipeline §11.7.
    │   │                           #   Exists so EVERY mandated class in the client brief has a NAMED
    │   │                           #   producer rather than being implicit inside classical.py (§14 F-100).
    │   ├── compare.py              # semantic_similarity() → S_s
    │   ├── sam.py                  # SamSegmenter        [weights, lazy]
    │   └── dinov2_seg.py           # Dinov2Semantics     [weights, lazy]
    │
    ├── landmarks/
    │   ├── __init__.py
    │   ├── patches.py              # LandmarkPatchBank — multi-scale/affine patch extraction
    │   ├── priors.py               # landmark_sampling_prior() → spatial density map (for MATCHING)
    │   ├── suggest.py              # ★ NEW (IU-06). LandmarkSuggester ABC + ClassicalSuggester (TERMINAL,
    │   │                           #   no weights) + SamSuggester [weights → classical]. §4.23.
    │   │                           #   Backs job_type='suggest_landmarks', endpoints 43–45 and the whole
    │   │                           #   landmark_suggestions table — all of which v1.0 shipped with NO
    │   │                           #   algorithm behind them (§14 F-96).
    │   ├── guided.py               # guided_rematch() — prior-H constrained second pass
    │   ├── topology.py             # cross_ratio_signature()  ★ hull_order_invariant() is DELETED (§14 F-70)
    │   └── consistency.py          # landmark_consistency() → S_l
    │
    ├── scoring/
    │   ├── __init__.py
    │   ├── base.py                 # ScoringModel ABC
    │   ├── composite.py            # CompositeScoringModel ★ DEFAULT
    │   ├── calibration.py          # PlattCalibrator · IsotonicCalibrator · load_calibration()
    │   └── calibration/
    │       └── default-v1.json     # ships as IDENTITY, calibrated=false
    │
    ├── heatmap/
    │   ├── __init__.py
    │   └── posterior.py            # CameraPosterior — GMM over camera locations, in WINDOW PIXELS
    │
    ├── pipeline/
    │   ├── __init__.py
    │   ├── context.py              # MatchContext (immutable per-job bundle) · SearchSeed
    │   ├── compose.py              # ★ NEW (IU-08). build_context(...) -> (MatchContext, ResolutionReport).
    │   │                           #   THE composition root INSIDE ai_engine. It is the only place that
    │   │                           #   may import models + extractors + matchers + geometry + scoring at
    │   │                           #   once, which is exactly why Registry cannot do this itself
    │   │                           #   (§10.2 forbids models→matchers). Replaces v1.0's
    │   │                           #   Registry.build_context_components, which was specified to return an
    │   │                           #   untyped dict and could not construct MatchContext.source at all. §4.14.
    │   ├── steps.py                # the 9 steps, each a pure typed function
    │   ├── orchestrator.py         # ★ run_match_job(ctx) → MatchJobResult — the primary public entry point
    │   └── ranking.py              # rank_windows() · ambiguity_margin()  ★ both operate on ScoreResult.raw
    │
    ├── runtime/
    │   ├── __init__.py
    │   ├── cache.py                # DiskCache · NullCache · DictImageStore — CONCRETE impls.
    │   │                           #   ★ The CacheBackend/ImageStore PROTOCOLS live in types/cache.py (IU-01)
    │   │                           #   so types/features.py can name ImageStore without a forward ref into
    │   │                           #   a module five units later in the build order. Also exposes
    │   │                           #   resolve_ref(ref, store) -> np.ndarray | None.
    │   ├── parallel.py             # process_map() — sets cv2.setNumThreads(1) in children
    │   └── events.py               # structured events: ComponentFallback · StepTiming · DegeneracyTripped
    │
    └── tests/                      # ★ OWNERSHIP IS SPLIT PER UNIT (§3, §14 F-39). v1.0 gave every test
        │                           #   file to IU-08 while §13.1 assigned test obligations to eleven other
        │                           #   units — so with 12 parallel agents either nothing was tested or the
        │                           #   "no two units touch the same file" rule broke on day one.
        ├── conftest.py                     # IU-08 · synthetic_scene() + variants (§13.2)
        ├── fixtures/                       # IU-08 · tiny generated PNGs committed to git (<200 KB total)
        ├── test_types_validate.py          # IU-01
        ├── test_types_import_cheap.py      # IU-01 ★ fresh interpreter: `import ai_engine.types` leaves
        │                                   #   cv2, torch AND ai_engine.models absent from sys.modules
        ├── test_registry_fallback.py       # IU-02 ★ THE L1 REGRESSION TEST
        ├── test_registry_zero_env.py       # IU-02 ★ preflight() on Settings(env={}) raises nothing
        ├── test_extractors_contract.py     # IU-03 ★ parametrised over EVERY registered extractor
        ├── test_matchers_contract.py       # IU-04 ★ parametrised over EVERY registered matcher
        ├── test_geometry_homography.py     # IU-05 · recovers a KNOWN H from a synthetic warp within 1e-3
        ├── test_geometry_covariance.py     # IU-05 ★ the vec()/gauge tests (§4.24) — Monte-Carlo vs A_h Σ_H A_hᵀ
        ├── test_geometry_degeneracy.py     # IU-05 · H1–H12 each tripped by a constructed input
        ├── test_semantics_classical.py     # IU-06
        ├── test_landmarks.py               # IU-06
        ├── test_suggest.py                 # IU-06 ★ ClassicalSuggester with no weights
        ├── test_scoring_bounds.py          # IU-07 · hypothesis: property-based
        ├── test_heatmap_mass.py            # IU-07 ★ background mass == π_bg (§4.25)
        └── test_pipeline_e2e.py            # IU-08 · SyntheticWindowSource, asserts pixel error < 2 px
```

### 2.3 `gis/` — geospatial + imagery. No fastapi. No SQLAlchemy. No CV algorithms.

**Root-level package, not `backend/app/gis/` or `backend/app/imagery/`** (§12 C-02). `pip install -e ./gis`.

```text
gis/
├── pyproject.toml                  # name="landexplorer-gis"
│                                   #   base deps: numpy, PIL, httpx  ★ httpx is BASE (the provider
│                                   #     registry imports every provider eagerly — §11.5 — so it cannot
│                                   #     be an extra; it is nonetheless CALL-TIME bound in http.py so the
│                                   #     suite collects with httpx absent. Both, deliberately.)
│                                   #   extras: [rasterio] · [redis] · [exports] (geopandas, fiona, ezdxf,
│                                   #           reportlab) · [pyproj] · [dev] (pytest, hypothesis, mypy)
├── README.md
└── src/gis/
    ├── __init__.py
    ├── py.typed
    ├── types.py                    # BBox · LonLat · TileRef · TileRange · ZoomDecision · GeoTransform
    │                               #   · RasterMeta · SatelliteChip · BasemapKind ★
    ├── config.py                   # GisConfig dataclass — framework-free
    ├── errors.py                   # GisError + ProviderError hierarchy (§4.17)
    │
    ├── tiles.py                    # ★ §4.18 PURE. numpy + stdlib ONLY. No I/O, no optional deps.
    │                               #   slippy math · quadkeys · 4326↔3857 closed-form · stitching
    │                               #   · geotransforms · pixel↔lonlat. The foundation.
    ├── crs.py                      # ★ THE ONLY MODULE THAT MAY IMPORT pyproj OR osgeo.osr.
    │                               #   always_xy=True always. UTM zone selection · cached Transformers
    │                               #   · pyproj → osr → closed-form-NumPy fallback (§11.3).
    ├── geometry.py                 # BBox ops · UTM-metre distance/area/buffer · antimeridian
    ├── accuracy.py                 # ★ px→metres. THE SINGLE PRODUCER of AccuracyEstimate (§4.20).
    │                               #   CE90 in UTM metres · error propagation · the error ellipse.
    │                               #   The module that must never see a degree or a 3857 metre.
    ├── pose.py                     # ★ NEW (IU-09). window-frame PoseResult → geography:
    │                               #   window_yaw_to_north_deg() (geotransform rotation + GRID CONVERGENCE)
    │                               #   · window_xy_to_lonlat() · pose_footprint() · pose_sigma_to_deg().
    │                               #   v1.0 had ai_engine emitting a window-local yaw and camera_poses
    │                               #   requiring 0=North, with NO module owning the conversion (§14 F-98).
    ├── heatmap.py                  # ★ NEW (IU-09). fuse_pixel_heatmaps() — per-window PixelHeatmaps
    │                               #   (WINDOW PIXELS) → one GeoHeatmap (true-metre grid, 4326 cells)
    │                               #   ready for confidence_heatmaps/_cells. §4.26, §14 F-99.
    ├── exif.py                     # EXIF GPS extraction (PIL) · DOP parsing · radius inflation
    ├── rasterio_shim.py            # ★ rasterio | osgeo.gdal | typed-error. Bound at CALL time (§11.3).
    │                               #   probe() -> str reports which backend bound; surfaced in
    │                               #   /health/ready and GET /capabilities (§14 F-56).
    ├── raster.py                   # windowed reads · overviews · nodata · detect_georeferencing()
    │
    ├── elevation/                  # ★ NEW (IU-09). The FOURTH provider interface. §4.27, §14 F-95.
    │   │                           #   The client brief mandates lat/lon/ELEVATION/confidence, and v1.0
    │   │                           #   plumbed elevation end to end as DATA (gcps.elevation_m,
    │   │                           #   elevation_source enum, CSV column 6) with NO module producing it.
    │   ├── __init__.py             #   ELEVATION_PROVIDERS registry · get_elevation_provider()
    │   ├── base.py                 #   ElevationProvider ABC · ElevationSample
    │   ├── null.py                 #   NullElevationProvider ★★ DEFAULT · KEYLESS · TERMINAL · returns None
    │   ├── local_dem.py            #   LocalDemProvider — DTM GeoTIFF via rasterio_shim, LE_LOCAL_DEM_DIR
    │   └── copernicus_dem.py       #   CopernicusDemProvider — opt-in, keyed
    │
    ├── imagery/                    # ★ THE LEGAL BOUNDARY
    │   ├── __init__.py
    │   ├── base.py                 # ImageryProvider ABC · TileProviderMixin ★ · ProviderCapabilities
    │   │                           #   · ProviderHealth · PROVIDER_NAMES ★ (the canonical name tuple —
    │   │                           #   gis tests against IT, and a BACKEND test asserts it equals the
    │   │                           #   imagery_provider enum. gis may not import sqlalchemy; §14 F-37.)
    │   ├── registry.py             # ProviderRegistry: config string → instance; `auto` resolution;
    │   │                           #   fallback chain (§11.4)
    │   ├── attribution.py          # ★ per-provider attribution text. NOT optional — ToS obligation.
    │   ├── http.py                 # shared session · retry/backoff · User-Agent policy.
    │   │                           #   ★ httpx bound at CALL time, never at module scope (§11.3).
    │   ├── ratelimit.py            # TokenBucket · per-provider budget. ★ redis bound at CALL time.
    │   ├── cache/
    │   │   ├── __init__.py         # ★ imports redis_cache LAZILY (module __getattr__), so importing the
    │   │   │                       #   cache package with redis absent succeeds.
    │   │   ├── base.py             # TileCache ABC · TileCacheKey · CacheStats
    │   │   ├── memory.py           # LRUTileCache  — always available, default in tests
    │   │   ├── disk.py             # DiskTileCache — default in dev
    │   │   └── redis_cache.py      # RedisTileCache — default in prod. ★ redis bound at CALL time.
    │   └── providers/
    │       ├── __init__.py         # ★ EXPLICIT registration. No entry-point autodiscovery (§12 C-49).
    │       ├── esri.py             # EsriWorldImageryProvider  ★★ DEFAULT · KEYLESS (L2)
    │       ├── local_ortho.py      # LocalOrthophotoProvider   ★★ OFFLINE · highest accuracy
    │       ├── fixture.py          # FixtureProvider           ★★ TEST + OFFLINE DEMO · deterministic
    │       │                       #   · NO NETWORK. ★ NOT "test-only": it is the front door of
    │       │                       #   LE_IMAGERY_OFFLINE mode and of `make seed && make up` (§14 F-66).
    │       ├── mapbox.py           # MapboxSatelliteProvider   †LE_MAPBOX_ACCESS_TOKEN
    │       ├── bing.py             # BingAerialProvider        †LE_BING_MAPS_KEY (metadata handshake)
    │       ├── sentinel.py         # SentinelCopernicusProvider †OAuth2 client credentials
    │       └── google_static.py    # GoogleStaticProvider      †key AND LE_GOOGLE_TOS_ACKNOWLEDGED=true
    │                               #   NOTE: Google EARTH is NOT and never will be a provider.
    │
    ├── candidates/
    │   ├── __init__.py
    │   ├── hint.py                 # SearchHint · resolve_hint() — the 5-step precedence (§4.19)
    │   ├── strategy.py             # plan_search() → list[WindowPlan]. Flat enumeration (§12 C-11).
    │   │                           #   ★ CLAMPS zoom_levels into [min_zoom, max_zoom] and reports it.
    │   ├── budget.py               # tile budgeting · AreaTooLargeError guard
    │   └── source.py               # ★ TileWindowSource — structurally satisfies ai_engine WindowSource.
    │                               #   THE SEAM (§4.19). Only place gis imports ai_engine.types.
    │
    ├── exports/
    │   ├── __init__.py             # EXPORT_WRITERS registry · get_writer() · available_formats()
    │   │                           #   ★ THE registry lives HERE, not in a registry.py. §9.9's consumer
    │   │                           #   column reads `gis.exports` (v1.0 said `gis.exports.registry`,
    │   │                           #   a module that appears in no tree).
    │   ├── base.py                 # ExportWriter ABC · ExportContext · ExportBundle · ExportFormatInfo ★
    │   ├── models.py               # GcpRecord — export DTO. NOT the ORM row. NOT the pydantic schema.
    │   ├── fieldmap.py             # FieldNameMapper — the .dbf 10-char problem
    │   ├── csv_writer.py           # stdlib only — ALWAYS available
    │   ├── geojson_writer.py       # stdlib json — ALWAYS available
    │   ├── kml_writer.py           # stdlib xml.etree — ALWAYS available. KmlExportWriter + KmzExportWriter
    │   │                           #   ★ TWO classes: format_id is a single ClassVar and get_writer() keys
    │   │                           #   on it, so one class cannot register under two ids (§14 F-46).
    │   ├── shapefile_writer.py     # geopandas/fiona — DEGRADES ★ call-time bound
    │   ├── gpkg_writer.py          # geopandas/fiona — DEGRADES ★ call-time bound
    │   ├── dxf_writer.py           # ezdxf — DEGRADES         ★ call-time bound
    │   └── pdf_writer.py           # reportlab — DEGRADES     ★ call-time bound
    │
    └── tests/                      # ★ OWNERSHIP SPLIT PER UNIT (§3, §14 F-39).
        │                           #   NO NETWORK: fixture provider + committed 64×64 GeoTIFF
        ├── conftest.py                     # IU-14
        ├── fixtures/                       # IU-14
        │   ├── synthetic_ortho.tif         #   committed, 64×64, EPSG:32633, known geotransform
        │   ├── plain.tif                   #   NO georeferencing — GDAL's identity transform
        │   └── tiles/                      #   committed fixture tiles
        ├── test_tiles_math.py              # IU-09 ★ golden values vs known OSM tile numbers (§13.3)
        ├── test_tiles_stitch.py            # IU-09
        ├── test_crs.py                     # IU-09 · round-trip pixel→lonlat→pixel < 1e-9°
        ├── test_accuracy.py                # IU-09 ★ the CE90 + 1/cos(φ)-direction goldens (§4.20)
        ├── test_pose.py                    # IU-09 ★ grid convergence: 3857 window → 0; UTM ortho → ≠0
        ├── test_heatmap_fuse.py            # IU-09
        ├── test_exif.py                    # IU-09
        ├── test_raster.py                  # IU-10
        ├── test_cache.py                   # IU-11
        ├── test_providers_contract.py      # IU-11 ★ PARAMETRISED OVER EVERY PROVIDER
        ├── test_import_without_deps.py     # IU-11 ★ collect with httpx+redis blocked in sys.modules
        ├── test_candidates.py              # IU-12
        └── test_exports_writers.py         # IU-13 ★ PARAMETRISED OVER EVERY WRITER
```

### 2.4 `backend/` — FastAPI + Celery. The ONLY home of fastapi/sqlalchemy/celery/pydantic.

```text
backend/
├── pyproject.toml                  # name="landexplorer-backend"; path deps on ../ai_engine, ../gis
├── requirements.txt                # pinned runtime (§9.11)
├── requirements-dev.txt            # pytest · pytest-asyncio · httpx · testcontainers · mypy · ruff
├── alembic.ini
├── alembic/
│   ├── env.py                      # async engine; geoalchemy2 alembic_helpers; include_object
│   ├── script.py.mako              # ★ MUST emit `import geoalchemy2`
│   └── versions/
│       ├── 0001_enable_extensions.py       # postgis · btree_gist · pg_trgm · tg_set_updated_at()
│       ├── 0002_create_enums.py            # ★ all SEVENTEEN enum types, create_type=True, ONCE.
│       │                                   #   v1.0 said "13" in three places and defined 17 in the SQL.
│       ├── 0003_core_projects_images.py
│       ├── 0004_annotations_and_versioning.py
│       ├── 0005_jobs_and_matching.py       # match_jobs + batch_job_items mutual FK cycle-break
│       ├── 0006_gcps_pose_heatmap.py
│       ├── 0007_semantic_and_suggestions.py
│       ├── 0008_batch_exports_auxjobs.py   # ★ + the shared-job-column backfill on exports/batch_jobs
│       │                                   #   that makes v_jobs expressible (§5.5)
│       └── 0009_indexes_triggers_views.py  # non-implied indexes · triggers · v_jobs view
└── app/
    ├── __init__.py
    ├── main.py                     # create_app() · lifespan · middleware · router mount · handlers
    │
    ├── api/
    │   ├── __init__.py
    │   ├── deps.py                 # §6.2 shared dependencies
    │   ├── errors.py               # exception handlers → ErrorEnvelope
    │   ├── middleware.py           # RequestId · Timing · BodySizeLimit · RateLimit
    │   └── v1/
    │       ├── __init__.py
    │       ├── router.py           # ★ APIRouter(prefix="/api/v1") — the ONLY place the prefix appears
    │       ├── health.py           # 1, 2
    │       ├── capabilities.py     # 3
    │       ├── projects.py         # 4–8
    │       ├── images.py           # 9–15
    │       ├── annotations.py      # 16–22   (router_nested + router_flat)
    │       ├── revisions.py        # 23–29   (router_project + router_flat + router_versions)
    │       ├── matching.py         # 30, 34–37 (router_image + router_results)
    │       ├── jobs.py             # 31–33
    │       ├── gcps.py             # 38–42   (router_image + router_flat)
    │       ├── suggestions.py      # 43–45
    │       ├── semantics.py        # 46, 47
    │       ├── pose.py             # 48, 49
    │       ├── imagery.py          # 50–53
    │       ├── batch.py            # 54–57
    │       └── exports.py          # 58–63   (router_image + router_project + router_flat)
    │
    ├── core/
    │   ├── __init__.py
    │   ├── config.py               # ★ Settings(BaseSettings) env_prefix="LE_". EVERY field has a default.
    │   ├── logging.py              # structlog JSON; request_id/job_id binding; secret scrubbing
    │   ├── security.py             # Principal; NO-OP when LE_AUTH_MODE=none
    │   ├── exceptions.py           # LandExplorerError hierarchy (§6.3)
    │   ├── pagination.py           # PaginationParams/SortParams helpers
    │   ├── idempotency.py          # Idempotency-Key → Redis SETNX
    │   ├── queue.py                # ★ NEW (IU-15). JobQueue Protocol: submit(spec: JobSpec) -> str.
    │   │                           #   Lets app.services enqueue WITHOUT importing celery, which
    │   │                           #   `services-no-fastapi` forbids and §2.4 v1.0 simultaneously
    │   │                           #   required ("match_service … enqueues"). §14 F-05/F-57.
    │   └── constants.py            # ★ THE SOLE HOME of JobStage, STAGES[JobType], STAGE_WEIGHTS and the
    │                               #   error docs_url map. tasks/progress.py IMPORTS them. v1.0 put
    │                               #   STAGE_WEIGHTS in BOTH core/constants.py (IU-15) and
    │                               #   tasks/progress.py (IU-20) — two units, one symbol.
    │
    ├── db/
    │   ├── __init__.py
    │   ├── session.py              # async_sessionmaker · get_session · sync session for Celery
    │   ├── types.py                # GeoAlchemy2 wrappers · JSONB helpers
    │   └── repositories/           # ★ ALL SQL lives here.
    │       ├── __init__.py
    │       ├── base.py             # generic CRUD repo
    │       ├── projects.py
    │       ├── images.py
    │       ├── annotations.py      # incl. annotation_versions, revisions, replay
    │       ├── jobs.py             # ★ atomic state transitions (compare-and-set); v_jobs reads
    │       ├── matches.py
    │       ├── gcps.py             # ★ PostGIS spatial queries live here
    │       ├── poses.py
    │       ├── heatmaps.py
    │       ├── semantics.py
    │       ├── suggestions.py
    │       ├── batches.py
    │       └── exports.py
    │
    ├── models/                     # SQLAlchemy 2.x, Mapped[] style (§5)
    │   ├── __init__.py             # ★ imports EVERY module so Base.metadata is complete
    │   ├── base.py                 # Base(DeclarativeBase) + NAMING_CONVENTION
    │   ├── mixins.py               # UUIDPkMixin · TimestampMixin · SoftDeleteMixin
    │   ├── enums.py                # Python mirrors of the 13 PG enums
    │   ├── project.py              # Project
    │   ├── revision.py             # ProjectRevision
    │   ├── image.py                # Image
    │   ├── annotation.py           # Annotation · AnnotationVersion
    │   ├── job.py                  # MatchJob · AuxJob · BatchJob · BatchJobItem
    │   ├── match.py                # MatchResult
    │   ├── gcp.py                  # GCP
    │   ├── pose.py                 # CameraPose
    │   ├── heatmap.py              # ConfidenceHeatmap · ConfidenceHeatmapCell
    │   ├── semantic.py             # SemanticFeature
    │   ├── suggestion.py           # LandmarkSuggestion
    │   └── export.py               # Export
    │
    ├── schemas/                    # Pydantic v2 — the WIRE contract (§6)
    │   ├── __init__.py
    │   ├── common.py · enums.py · errors.py · health.py · capabilities.py
    │   ├── project.py · image.py · annotation.py · revision.py
    │   ├── matching.py · job.py · gcp.py · suggestion.py · semantic.py
    │   ├── pose.py · imagery.py · batch.py · export.py
    │
    ├── services/                   # orchestration; the ONLY both-sides layer
    │   ├── __init__.py
    │   ├── project_service.py
    │   ├── image_service.py        # validate · sniff · hash · store · EXIF → prior · thumbnail
    │   ├── annotation_service.py   # bulk upsert · versioning · revision allocation
    │   ├── revision_service.py     # checkpoint · replay · restore
    │   ├── _adapters.py            # ★ NEW (IU-19). §4.22 boundary adapters. The ONLY place a wire type
    │   │                           #   becomes a gis type. Six names exist twice with different shapes
    │   │                           #   (SearchHint, BBox, ProviderCapabilities, ProviderHealth,
    │   │                           #   CameraIntrinsics, LonLat/LatLon) and app.schemas may not import
    │   │                           #   gis — so SOMEBODY must convert, and v1.0 assigned nobody (§14 F-47).
    │   ├── match_service.py        # ★ pre-flight ladder → INSERT match_jobs → build a JSON-SERIALISABLE
    │   │                           #   MatchJobSpec → JobQueue.submit(). NEVER runs CV. NEVER constructs a
    │   │                           #   WindowSource: a TileWindowSource holds an httpx session and is not
    │   │                           #   broker-serialisable, so it CANNOT cross into a Celery task. The
    │   │                           #   composition root is app/tasks/matching.py, inside the worker.
    │   ├── elevation_service.py    # ★ NEW (IU-19). Wraps gis.elevation registry; fills gcps.elevation_m
    │   │                           #   + elevation_source, or emits ELEVATION_UNAVAILABLE. §4.27.
    │   ├── result_service.py       # select · staleness marking
    │   ├── gcp_service.py          # adjust · reset · recompute (incl. sync dry_run)
    │   ├── suggestion_service.py
    │   ├── semantic_service.py
    │   ├── pose_service.py
    │   ├── heatmap_service.py
    │   ├── batch_service.py
    │   ├── export_service.py
    │   ├── imagery_service.py      # wraps gis.imagery.registry; injects keys from Settings
    │   └── capability_service.py   # ★ READS the cached PreflightReport off app.state + probes the gis
    │                               #   registries. NEVER re-runs preflight (§11.1, §14 F-60).
    │
    ├── storage/
    │   ├── __init__.py
    │   ├── base.py                 # ObjectStorage ABC: put · get · open · delete · exists · url_for
    │   ├── local.py                # ★ DEFAULT — LE_STORAGE_LOCAL_ROOT. Zero config.
    │   ├── s3.py                   # boto3/MinIO, opt-in
    │   └── keys.py                 # ★ canonical key layout — single source of truth for paths
    │
    ├── tasks/
    │   ├── __init__.py
    │   ├── celery_app.py           # app · queues (cv/io/export) · routes · beat schedule
    │   ├── base.py                 # ★ BaseJobTask: transitions · retry policy · progress · error map
    │   ├── queue.py                # ★ NEW (IU-20). CeleryJobQueue — the JobQueue impl. Injected at the
    │   │                           #   composition root (main.py / worker bootstrap).
    │   ├── progress.py             # throttled progress writer · cancel polling.
    │   │                           #   ★ IMPORTS STAGE_WEIGHTS from core.constants; does not define it.
    │   ├── ingest.py               # ingest_image_task (thumbnail/overviews for large files)
    │   ├── matching.py             # ★ match_image_task — the big one, AND THE COMPOSITION ROOT:
    │   │                           #   spec(dict) → provider → TileWindowSource → ai_engine.pipeline.
    │   │                           #   compose.build_context() → run_match_job() → persist. It is the only
    │   │                           #   place a live provider session and a MatchContext coexist.
    │   ├── segmentation.py         # segment_image_task · suggest_landmarks_task
    │   ├── gcps.py                 # recompute_gcps_task
    │   ├── exporting.py            # render_export_task
    │   ├── batch.py                # batch_fanout_task · batch_aggregate_task
    │   └── maintenance.py          # beat: tile cache GC · export TTL sweep · stale job reaper
    │
    ├── observability/
    │   ├── __init__.py
    │   ├── metrics.py              # prometheus registry + the §9.10 metric set
    │   └── tracing.py              # optional OTEL; no-op when unset
    │
    └── tests/
        ├── conftest.py             # ★ app factory · Settings overrides · fixture provider · eager Celery
        ├── unit/                   # no DB — services with mocked repos
        ├── api/                    # httpx ASGI transport; no live server
        ├── db/                     # @pytest.mark.db — needs Postgres+PostGIS
        └── tasks/                  # eager Celery
```

### 2.5 `frontend/`

```text
frontend/
├── package.json · pnpm-lock.yaml
├── vite.config.ts                  # /api proxy → localhost:8000 in dev
├── tsconfig.json · tsconfig.node.json
├── vitest.config.ts
├── index.html
├── .eslintrc.cjs · .prettierrc
├── public/
└── src/
    ├── main.tsx                    # QueryClientProvider · ThemeProvider · RouterProvider
    ├── App.tsx · router.tsx · vite-env.d.ts
    │
    ├── api/                        # ★ THE ONLY fetch() in the app
    │   ├── client.ts               # base URL · request id · ErrorEnvelope → ApiError
    │   ├── queryClient.ts          # global defaults (§8.4)
    │   ├── queryKeys.ts            # ★ the key factory — one place, no stringly-typed keys
    │   ├── generated/              # ★ openapi-typescript output. DO NOT EDIT. CI fails on drift.
    │   │   └── schema.ts
    │   ├── projects.ts · images.ts · annotations.ts · revisions.ts
    │   ├── matches.ts · jobs.ts · gcps.ts · suggestions.ts · semantics.ts
    │   ├── pose.ts · heatmap.ts · providers.ts · capabilities.ts
    │   ├── batch.ts · exports.ts
    │   └── hooks/
    │       ├── useProjects.ts · useImages.ts · useImageUpload.ts
    │       ├── useAnnotations.ts · useRevisions.ts
    │       ├── useMatch.ts · useJob.ts        # ★ the poller (§8.4)
    │       ├── useGcps.ts · useAdjustGcp.ts · useRecomputeGcps.ts
    │       ├── useSuggestions.ts · useSemantics.ts · usePose.ts · useHeatmap.ts
    │       ├── useProviders.ts · useCapabilities.ts
    │       └── useBatch.ts · useExport.ts
    │
    ├── store/                      # ★ Zustand — LOCAL UI STATE ONLY (L7)
    │   ├── toolStore.ts · annotationStore.ts · viewerStore.ts
    │   ├── mapStore.ts · selectionStore.ts · workspaceStore.ts
    │   ├── compareStore.ts · uploadStore.ts
    │
    ├── lib/
    │   ├── viewport/transform.ts   # ★ the two-stage transform (§8.6). Pure. Property-tested.
    │   ├── commands/               # undo/redo command pattern
    │   ├── geo/format.ts           # coordinate formatting + ★ precision truncation policy (§8.7)
    │   ├── confidence.ts           # band mapping + colour scale
    │   └── download.ts
    │
    ├── components/                 # §2.5 tree in 50-frontend.md §2 — adopted verbatim
    │   ├── shell/ · workspace/ · image/ · annotation/ · map/
    │   ├── gcp/ · export/ · job/ · upload/ · common/
    │
    ├── pages/
    │   ├── ProjectsPage.tsx · ProjectDetailPage.tsx · WorkspacePage.tsx
    │   ├── SettingsPage.tsx · NotFoundPage.tsx
    │
    ├── types/                      # §8.2 — snake_case, mirrors Pydantic field-for-field. ALL of IU-23.
    │   ├── common.ts · geo.ts · image.ts · annotation.ts · gcp.ts
    │   ├── match.ts · job.ts · export.ts · project.ts · capabilities.ts
    │   ├── pose.ts · heatmap.ts · semantic.ts · suggestion.ts · batch.ts   # ★ NEW (§14 F-31).
    │   │                           #   v1.0 shipped api/{semantics,pose,heatmap,batch,suggestions}.ts and
    │   │                           #   five hooks with NO home for HeatmapRead, CameraPoseRead,
    │   │                           #   SemanticFeatureRead, LandmarkSuggestionRead, BatchRead — so IU-24
    │   │                           #   would have inlined `any`, which is exactly the drift §8.1 exists
    │   │                           #   to prevent.
    │   ├── commands.ts · index.ts
    │
    ├── theme/                      # MUI theme · palette · confidence colour scale
    └── __tests__/                  # vitest + RTL; MSW mocks the API — NO backend needed
```

### 2.6 `infra/`

```text
infra/
├── docker/
│   ├── backend.Dockerfile          # multi-stage; installs ai_engine + gis + backend
│   ├── frontend.Dockerfile         # node build → nginx static
│   └── entrypoints/                # api.sh · worker.sh · beat.sh (wait-for-deps, optional migrate)
├── compose/
│   ├── docker-compose.yml          # ★ BASE — must work with an EMPTY .env (L2)
│   ├── docker-compose.dev.yml      # hot reload, bind mounts, exposed ports, LE_DB_AUTO_MIGRATE=true
│   ├── docker-compose.prod.yml     # replicas, healthchecks, restart policies
│   └── docker-compose.test.yml     # ephemeral pg+redis for CI
├── nginx/
│   ├── nginx.conf
│   ├── conf.d/landexplorer.conf    # SPA fallback · /api proxy · client_max_body_size 500m
│   │                               # · proxy_read_timeout 60s (long-poll needs >30s)
│   └── mime.types
└── postgres/
    └── init/01-postgis.sql         # CREATE EXTENSION postgis, btree_gist, pg_trgm
```

### 2.7 `docs/`

```text
docs/
├── architecture/
│   ├── CONTRACT.md                 # ◀ THIS FILE — law
│   ├── TRACEABILITY.md             # ★ NEW (IU-32). One row per CLIENT requirement → owning file(s) →
│   │                               #   the exact §13.1 test id that proves it → status
│   │                               #   (done | deferred-with-§12.5-row). Seeded from the brief's ten
│   │                               #   deliverables. CI rule 10 (§13.4): a requirement with no test does
│   │                               #   not exist. v1.0 was verifiable per-MODULE and per-UNIT but never
│   │                               #   per-REQUIREMENT — which is why the elevation and landmark-suggester
│   │                               #   holes survived four specialist docs and a full contract (§14 F-101).
│   ├── 00-overview.md              # rationale + ADRs (normative for reasoning only)
│   ├── 10-database.md · 20-api.md · 30-ai-pipeline.md · 40-imagery.md · 50-frontend.md
│   └── adr/                        # ★ ADR-001..014. THE PATH IS `docs/architecture/adr/`.
│                                   #   §3 v1.0 assigned IU-32 `docs/adr/**` — a different directory.
├── api/openapi-notes.md
├── guides/                         # quickstart · adding-a-provider · adding-a-backend · offline-mode
│                                   #   ★ offline-mode.md documents LE_IMAGERY_OFFLINE + `make seed`
└── legal/imagery-terms.md          # ★ per-provider ToS summary; why Google Earth is excluded;
                                    #   the LE_IMAGERY_DIRECT_TILE_URLS consequence (§14 F-105)
```

### 2.8 `tests/` — cross-package only

```text
tests/
├── conftest.py
├── contract/                       # ★ every ImageryProvider and FeatureExtractor obeys its ABC
├── integration/                    # compose-backed: real pg + redis + fixture provider
├── e2e/                            # API-driven: upload → mark → match → export
└── fixtures/                       # shared sample photo + synthetic ortho GeoTIFF
```

### 2.9 `scripts/`

```text
scripts/
├── bootstrap_dev.sh                # ★ EXACT, not left to the implementer (§14 F-63):
│                                   #     scripts/check_env.py                      # print §0.1 first
│                                   #     python -m venv --system-site-packages .venv
│                                   #       ↑ WITHOUT this, the venv hides cv2/numpy/scipy/torch/osgeo —
│                                   #         the entire CV stack — and osgeo cannot be pip-installed back.
│                                   #     pip install -e ./ai_engine[dev] --no-deps
│                                   #     pip install -e ./gis[dev]       --no-deps
│                                   #       ↑ --no-deps or pip downloads opencv/numpy/scipy from PyPI on a
│                                   #         machine the brief gives no network guarantee for.
│                                   #     corepack enable && corepack prepare pnpm@9 --activate
│                                   #   Installs NOTHING from PyPI on this machine. Asserted in §9.13.
├── check_env.py                    # ★ prints the §0.1 capability table for the current machine.
│                                   #   `--emit-example` regenerates .env.example from §9.
│                                   #   Run at Docker BUILD time and its output asserted (§14 F-56).
├── verify_boundaries.sh            # ★ runs import-linter + the §10.5 greps — CI gate
├── download_models.py              # ★ OPT-IN weight fetcher. NOT run at build/boot. Prints licences.
│                                   #   Requires a WORKER RESTART to take effect (preflight is cached).
├── make_fixtures.py                # generates the synthetic ortho + tiles + scene (no network)
└── seed_demo_data.py               # ★ demo project (default_provider='fixture') + image + annotations
                                    #   + the committed fixture tiles, so `make seed && make up`
                                    #   demonstrates upload → mark → match → export WITH THE NIC
                                    #   UNPLUGGED. The offline path needs a front door that is not a
                                    #   test flag (§14 F-66).
```

### 2.10 `data/` — gitignored except `.gitkeep`

```text
data/
├── storage/                        # LE_STORAGE_LOCAL_ROOT (images, derived, exports)
├── tile_cache/                     # LE_IMAGERY_TILE_CACHE_DIR
├── model_weights/                  # LE_AI_MODEL_WEIGHTS_DIR — EMPTY by default and that is FINE
├── orthophotos/                    # LE_LOCAL_ORTHO_DIR — drop GeoTIFFs for offline mode
└── dem/                            # LE_LOCAL_DEM_DIR — drop DTM GeoTIFFs for elevation. Empty ⇒
                                    #   NullElevationProvider ⇒ elevation_m is null AND SAYS SO (§4.27)
```

---

## 3. File ownership map

Disjoint implementation units. **No two units touch the same file.** Each unit is independently testable and lists what it may import.

| Unit | Owns | May import | Blocked by |
|---|---|---|---|
| **IU-01 · ai-types** | `ai_engine/src/ai_engine/{types/**, errors.py, config.py, version.py, logging.py, __init__.py, py.typed}` + `tests/{test_types_validate.py, test_types_import_cheap.py}` | numpy, stdlib | — |
| **IU-02 · ai-registry** | `ai_engine/src/ai_engine/models/**` *(incl. `registration.py`)* + `tests/{test_registry_fallback.py, test_registry_zero_env.py}` | IU-01, stdlib, torch *(only in `torch_guard.py`)* | IU-01 |
| **IU-03 · ai-extract** | `ai_engine/src/ai_engine/extractors/*` + `tests/test_extractors_contract.py` | IU-01, IU-02, cv2, numpy | IU-01, IU-02 |
| **IU-04 · ai-match** | `ai_engine/src/ai_engine/matchers/*` + `tests/test_matchers_contract.py` | IU-01, IU-02, IU-03 *(types only)*, cv2, numpy, scipy | IU-01, IU-02 |
| **IU-05 · ai-geometry** | `ai_engine/src/ai_engine/geometry/*` + `tests/{test_geometry_homography.py, test_geometry_covariance.py, test_geometry_degeneracy.py}` | IU-01, cv2, numpy, scipy | IU-01 |
| **IU-06 · ai-semantics** | `ai_engine/src/ai_engine/{semantics/*, landmarks/*}` *(incl. `suggest.py`, `structures.py`)* + `tests/{test_semantics_classical.py, test_landmarks.py, test_suggest.py}` | IU-01, IU-02, IU-03, cv2, numpy, scipy | IU-01, IU-03 |
| **IU-07 · ai-scoring** | `ai_engine/src/ai_engine/{scoring/*, heatmap/*}` + `tests/{test_scoring_bounds.py, test_heatmap_mass.py}` | IU-01, numpy, scipy | IU-01 |
| **IU-08 · ai-pipeline** | `ai_engine/src/ai_engine/{pipeline/*, runtime/*, windows/*}` + `tests/{conftest.py, fixtures/**, test_pipeline_e2e.py}` | all of `ai_engine.*`, cv2, numpy, scipy | IU-01..IU-07 |
| **IU-09 · gis-math** | `gis/src/gis/{types.py, config.py, errors.py, tiles.py, crs.py, geometry.py, accuracy.py, pose.py, heatmap.py, exif.py, elevation/**, __init__.py, py.typed}` + `tests/{test_tiles_math.py, test_tiles_stitch.py, test_crs.py, test_accuracy.py, test_pose.py, test_heatmap_fuse.py, test_exif.py}` | numpy, stdlib, PIL, **pyproj AND `osgeo`** *(both only in `crs.py`)* | — |
| **IU-10 · gis-raster** | `gis/src/gis/{rasterio_shim.py, raster.py}` + `tests/test_raster.py` | IU-09, osgeo/rasterio *(call-time)*, numpy | IU-09 |
| **IU-11 · gis-imagery** | `gis/src/gis/imagery/**` + `tests/{test_cache.py, test_providers_contract.py, test_import_without_deps.py}` | IU-09, IU-10, httpx *(call-time)*, redis *(call-time)*, PIL, numpy | IU-09, IU-10 |
| **IU-12 · gis-candidates** | `gis/src/gis/candidates/*` + `tests/test_candidates.py` | IU-09, IU-11, **`ai_engine.types` ONLY** | IU-01, IU-09, IU-11 |
| **IU-13 · gis-exports** | `gis/src/gis/exports/*` + `tests/test_exports_writers.py` | IU-09, geopandas, shapely, reportlab, ezdxf *(all call-time)* | IU-09 |
| **IU-14 · gis-tests** | `gis/src/gis/tests/{conftest.py, fixtures/**}` | all of `gis.*` | IU-09..IU-13 |
| **IU-15 · be-core** | `backend/app/{core/*, db/session.py, db/types.py, storage/*, observability/*}` + `backend/{pyproject.toml, requirements*.txt}` | pydantic-settings, structlog, sqlalchemy, boto3, prometheus | — |
| **IU-16 · be-models** | `backend/app/models/**` + `backend/alembic/**` + `backend/alembic.ini` | sqlalchemy, geoalchemy2, alembic, IU-15 *(`core.constants` only)* | IU-15 |
| **IU-17 · be-schemas** | `backend/app/schemas/**` | pydantic, IU-15 *(`core.constants` only)* | IU-15 |
| **IU-18 · be-repos** | `backend/app/db/repositories/**` | sqlalchemy, geoalchemy2, IU-15, IU-16 | IU-16 |
| **IU-19 · be-services** | `backend/app/services/**` *(incl. `_adapters.py`, `elevation_service.py`)* | IU-15..IU-18, `ai_engine`, `gis`. **NOT celery** — enqueues via `core.queue.JobQueue` (IU-15) | IU-16..IU-18, IU-08, IU-12, IU-13 |
| **IU-20 · be-tasks** | `backend/app/tasks/**` *(incl. `queue.py`)* | celery, IU-15, IU-18, IU-19, `ai_engine`, `gis` | IU-19 |
| **IU-21 · be-api** | `backend/app/{main.py, api/**}` | fastapi, IU-15, IU-17, IU-19. ★ **NOT `app.tasks`** — routers delegate to services only; the service owns the INSERT-then-submit ordering as one unit | IU-17, IU-19 |
| **IU-22 · be-tests** | `backend/app/tests/**` | everything | IU-21 |
| **IU-23 · fe-foundation** | `frontend/{package.json, vite.config.ts, tsconfig*.json, vitest.config.ts, index.html, .eslintrc.cjs, .prettierrc, public/**}` + `frontend/src/{main.tsx, App.tsx, router.tsx, vite-env.d.ts, theme/**, types/**}` | — | IU-17 *(schema shapes)* |
| **IU-24 · fe-api** | `frontend/src/api/**` | IU-23 | IU-23, IU-21 |
| **IU-25 · fe-state** | `frontend/src/{store/**, lib/**}` | IU-23 | IU-23 |
| **IU-26 · fe-image** | `frontend/src/components/{image/**, annotation/**}` | IU-23, IU-24, IU-25 | IU-24, IU-25 |
| **IU-27 · fe-map** | `frontend/src/components/{map/**, gcp/**}` | IU-23, IU-24, IU-25 | IU-24, IU-25 |
| **IU-28 · fe-shell** | `frontend/src/components/{shell/**, workspace/**, job/**, upload/**, export/**, common/**}` + `frontend/src/pages/**` | IU-23, IU-24, IU-25 | IU-24, IU-25 |
| **IU-29 · fe-tests** | `frontend/src/__tests__/**` | everything | IU-26..IU-28 |
| **IU-30 · infra** | `infra/**` + repo-root `{Makefile, .env.example, .dockerignore, .editorconfig, .gitignore, .pre-commit-config.yaml, .importlinter, pyproject.toml, README.md, LICENSE}` + `scripts/**` | — | — |
| **IU-31 · x-tests** | `tests/**` | everything | IU-21, IU-30 |
| **IU-32 · docs** | `docs/architecture/{adr/**, TRACEABILITY.md}`, `docs/api/**`, `docs/guides/**`, `docs/legal/**` | — | — |

**Contested files, resolved:**

- `ai_engine/src/ai_engine/types/windows.py` → **IU-01**, not IU-08. `gis.candidates` (IU-12) imports it; it must land in the first wave.
- `ai_engine/src/ai_engine/types/provenance.py` → **IU-01**. It holds `ComponentKind`/`ComponentSpec`/`Resolution`/`ResolutionReport`/`PreflightReport`, which IU-02 *consumes* and re-exports from `models/spec.py`. **The types package may never import the models package** (§10.2, §10.3, and the `gis-purity` contract all depend on it), so the value objects live on the types side and the behaviour lives on the models side. This is the single change that unblocks the IU-01↔IU-02 dependency cycle v1.0 created.
- `ai_engine/src/ai_engine/types/cache.py` → **IU-01**. `ImageStore`/`CacheBackend` are *Protocols* (vocabulary); `runtime/cache.py` (IU-08) holds the *implementations*. Same rule as `WindowSource`: **the side that declares the Protocol owns the Protocol.**
- `ai_engine/src/ai_engine/models/registration.py` → **IU-02**, and it is imported **only** by `_ensure_registered()`, lazily. Mirrors `gis/imagery/providers/__init__.py`.
- `ai_engine/src/ai_engine/pipeline/compose.py` → **IU-08**. It is the one module allowed to see every subpackage at once; that is precisely why the Registry cannot do its job.
- **Test files are owned by the unit whose obligation they discharge** (§13.1), not by IU-08/IU-14. IU-08 keeps only `conftest.py`, `fixtures/` and `test_pipeline_e2e.py`; IU-14 keeps only `conftest.py` and `fixtures/`. Otherwise eleven units could not write a single test without touching another unit's files.
- `backend/app/models/enums.py` → **IU-16**. `backend/app/schemas/enums.py` → **IU-17**. `ai_engine/types/enums.py` → **IU-01**. All **separate files with identical values** for the 17 paired enums; none imports another; `test_enum_parity.py` asserts all three legs agree via the normative `PARITY_MAP` (§5.3).
- `backend/app/core/constants.py` → **IU-15**. **THE SOLE HOME** of `JobStage`, `STAGES`, `STAGE_WEIGHTS` and the docs_url map — **no enums** (those live in IU-16/IU-17). `tasks/progress.py` imports; it does not redeclare.
- `backend/app/core/queue.py` → **IU-15** (the `JobQueue` Protocol). `backend/app/tasks/queue.py` → **IU-20** (the Celery impl). Same Protocol/implementation split as `WindowSource`, for the same reason: it is what keeps `app.services` framework-free while still letting a service enqueue.
- `frontend/src/api/generated/schema.ts` → **IU-24**, but is machine-generated. Never hand-edited.
- `.env.example` → **IU-30**, generated from §9 by `scripts/check_env.py --emit-example`. CI asserts it matches §9.

---

## 4. Exact Python interfaces — `ai_engine` and `gis`

Copy-pasteable, verbatim. Import paths are exact.

### 4.1 `ai_engine.errors`

```python
# ai_engine/src/ai_engine/errors.py

class AiEngineError(Exception):
    """Root of every ai_engine exception. Nothing else escapes the package."""


class ConfigurationError(AiEngineError):
    """Bad config. Raised at composition time, never per-request."""


class ComponentUnavailable(ConfigurationError):
    """Fallback chain exhausted. Raised at COMPOSITION time, never per-request."""


class WeightsMissing(ComponentUnavailable):
    """A required weight file is absent. NOT an error on the default path (L1)."""


class WeightsCorrupt(ComponentUnavailable):
    """Weight file present but sha256 mismatch. Treated exactly like missing."""


class IncompatibleDescriptors(AiEngineError):
    """FLANN-KDTree asked to match BINARY descriptors, or D_a != D_b."""


class DetectorFreeRequiresImages(AiEngineError):
    """A detector-free matcher was invoked through the Matcher ABC without a live ImageRef."""


class DegenerateSolve(AiEngineError):
    """Carries the DegeneracyReport. Callers MUST handle; never swallow."""

    def __init__(self, report: "DegeneracyReport") -> None: ...


class InsufficientCorrespondences(AiEngineError):
    """Fewer than 4 point pairs. A homography is not defined."""


class WindowFetchError(AiEngineError):
    """★ PART OF THE WindowSource PROTOCOL CONTRACT (§4.10).

    A WindowSource MAY raise this for an INDIVIDUAL window; the orchestrator logs it,
    counts it, and continues to the next window.

    It lives HERE, on the ai_engine side, because ai_engine DECLARES WindowSource and
    ai_engine.pipeline MUST NOT import gis (§10.2). An implementation
    (gis.candidates.source.TileWindowSource) MUST wrap gis.errors.ProviderError in this
    before letting it cross the seam.

    ★ v1.0's §4.10 told the orchestrator to catch `TileFetchError` — a class that exists
      in NEITHER ai_engine.errors NOR gis.errors, and which the orchestrator could not
      have named anyway without importing gis. Its only option was `except Exception`,
      which §4.13 calls a defect. The seam's exception type MUST live on the side that
      declares the Protocol.
    """

    window_key: str
    cause_type: str


class NoViableCandidate(AiEngineError):
    """★ NEVER RAISED ACROSS THE PACKAGE BOUNDARY. Retained ONLY as an internal marker
    inside step9_finalize.

    `run_match_job` RETURNS MatchJobResult(status="no_viable_candidate"). See §4.13,
    §11.6 and §12 C-46. Returning is also the internally consistent choice: §4.7 already
    rules that `estimate_homography` RETURNS a sub-threshold result rather than raising,
    because "estimation reports, policy judges" — and a status is data.
    """
```

### 4.2 `ai_engine.types.enums`

```python
# ai_engine/src/ai_engine/types/enums.py
from enum import StrEnum


class DescriptorKind(StrEnum):
    BINARY = "binary"   # Hamming metric; descriptors stored bit-packed uint8
    FLOAT  = "float"    # L2 metric; descriptors L2-normalised float32


class HomographyMethod(StrEnum):
    """★ THIS IS `RansacConfig.method` — a ROBUST-FIT METHOD. It is NOT a component
    registry key. The only registered ESTIMATOR BACKEND is "opencv" (§4.7), and
    AiEngineConfig.estimator_backend selects it.

    v1.0 conflated the two: LE_AI_ESTIMATOR defaulted to `usac_magsac` and was routed
    into AiEngineConfig.estimator, which resolve_with_fallback then looked up as a
    ComponentKind.ESTIMATOR spec — found nothing, found no fallback, and raised
    ComponentUnavailable AT BOOT ON AN EMPTY ENVIRONMENT. That is a traceback with zero
    env vars set, violating L10, L11 and §9.13 simultaneously. §9.8 now ships
    LE_AI_RANSAC_METHOD (the method) and LE_AI_ESTIMATOR_BACKEND (the component).

    ★ Every member is representable in the `robust_estimator` PG enum (§5.3), so a job
      can always record what actually ran. USAC_ACCURATE and LSQ were unrepresentable in
      v1.0's four-label enum.
    """
    USAC_MAGSAC  = "usac_magsac"    # cv2.USAC_MAGSAC          [DEFAULT]
    PROSAC       = "prosac"         # UsacParams(sampler=SAMPLING_PROSAC, score=SCORE_METHOD_MAGSAC)
    RANSAC       = "ransac"         # cv2.RANSAC               [baseline]
    LMEDS        = "lmeds"          # cv2.LMEDS   [available; DISQUALIFIED by default — §12 C-15]
    USAC_ACCURATE= "usac_accurate"
    LSQ          = "lsq"            # no robustification; tests / already-clean inliers only


class SemanticClass(StrEnum):
    """★ PARITY LEG 3. Values are IDENTICAL to the `semantic_class` PG enum (§5.3) and to
    schemas.enums.SemanticClass. SemanticMap.masks is keyed by this.

    v1.0 presented types/enums.py as exhaustively `DescriptorKind · HomographyMethod ·
    ViewRegime · Severity · Device` — no SemanticClass — while types/semantics.py's
    SemanticMap was keyed by one. So ai_engine could emit a mask class the DB could not
    store, or drop one the enum promised, and NOTHING failed: the parity test covered
    only models↔schemas. The triangle is now closed (§13.1 IU-01).
    """
    FIELD_BORDER    = "field_border"
    ROAD            = "road"
    IRRIGATION_CANAL= "irrigation_canal"
    TREE            = "tree"
    TREE_LINE       = "tree_line"
    GREENHOUSE      = "greenhouse"
    BUILDING        = "building"
    WATER_BODY      = "water_body"
    CROP_ROW        = "crop_row"
    BARE_SOIL       = "bare_soil"
    VEGETATION      = "vegetation"
    SHADOW          = "shadow"
    UNKNOWN         = "unknown"


class ViewRegime(StrEnum):
    NADIR               = "nadir"
    OBLIQUE_RECTIFIABLE = "oblique_rectifiable"
    OBLIQUE_RAW         = "oblique_raw"
    GROUND_HORIZON      = "ground_horizon"
    UNKNOWN             = "unknown"


class Severity(StrEnum):
    HARD = "hard"   # gate := 0.0, status := "rejected"
    SOFT = "soft"   # gate *= factor


class Device(StrEnum):
    AUTO = "auto"   # -> CPU on the verified box
    CPU  = "cpu"
    CUDA = "cuda"
```

### 4.3 `ai_engine.types.features`

```python
# ai_engine/src/ai_engine/types/features.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ai_engine.types.cache import ImageStore     # ★ Protocol, declared in types/ (IU-01)
from ai_engine.types.enums import DescriptorKind, Device


@dataclass(frozen=True, slots=True)
class ImageRef:
    """Content-addressed handle. Lets a FeatureSet point back at its image without
    pinning the array in memory."""
    sha256: str
    width: int
    height: int

    def resolve(self, store: ImageStore) -> np.ndarray | None:
        """★ The `store` Protocol is `ai_engine.types.cache.ImageStore` — a REAL import,
        not a forward reference. v1.0 forward-ref'd "ImageStore" while the class lived in
        ai_engine/runtime/cache.py (IU-08), a module IU-01 is FORBIDDEN to import and
        which lands five steps later in the build order: `mypy --strict` (CI gate §13.4
        #3) fails on the unresolved name, and any typing.get_type_hints() call raises
        NameError at runtime. Declaring the Protocol in types/ and implementing it in
        runtime/ is the same pattern §4.10 already uses for WindowSource."""


@dataclass(frozen=True, slots=True)
class FeatureSet:
    # --- required ---
    keypoints: np.ndarray          # (N,2) float32. (x,y) PIXELS. Origin = top-left CORNER;
                                   #   integer coords = pixel CENTRES. Subpixel expected.
    descriptors: np.ndarray        # FLOAT : (N,D) float32, each row L2-normalised (||d||=1)
                                   # BINARY: (N,D//8) uint8, bit-packed, LSB-first per byte
    scores: np.ndarray             # (N,) float32 in [0,1]. RANK-normalised: score_i = 1 - rank_i/N.
                                   #   NEVER raw response — raw scales are not comparable.
    image_size: tuple[int, int]    # (width, height) of the image the keypoints live in
    extractor_name: str            # matches FeatureExtractor.name; used for compat checks
    descriptor_kind: DescriptorKind

    # --- optional geometry ---
    sizes: np.ndarray | None = None    # (N,) float32 keypoint diameter, px
    angles: np.ndarray | None = None   # (N,) float32 radians CCW from +x. NaN = undefined
    affine: np.ndarray | None = None   # (N,2,2) float32 local affine frame (ASIFT/AffNet).
                                       #   None => isotropic (similarity-covariant only)

    # --- provenance / caching ---
    image_ref: ImageRef | None = None  # REQUIRED by detector-free shims (§4.6)
    extractor_version: str = "1"       # bump => cache invalidation
    params_hash: str = ""              # sha256 of the extractor's param dict
    landmark_ids: np.ndarray | None = None
        # (N,) int32. >=0 => this keypoint IS user landmark k (from extract_at). -1 => detected.
        # This is how landmark identity survives all the way into RANSAC weighting.
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_features(self) -> int: ...

    @property
    def descriptor_dim(self) -> int:
        """Logical dim D. For BINARY returns descriptors.shape[1] * 8."""

    def validate(self) -> None:
        """Raise ValueError on: shape mismatch, non-finite kps, kps outside image_size,
        FLOAT rows not unit-norm (atol=1e-3), scores outside [0,1], dtype mismatch,
        and — ★ NEW —

          * `descriptor_dim % 8 != 0` when descriptor_kind is BINARY;
          * duplicate values among `landmark_ids[landmark_ids >= 0]`.

        ★ The landmark_ids uniqueness rule is load-bearing, not hygiene. `cv2.SIFT.compute()`
          can return MORE keypoints than it was given: a patch with two dominant gradient
          orientations emits one keypoint PER ORIENTATION, same (x,y), different angle. So a
          K=8 landmark set can come back as N=14 with landmark_ids many-to-one — and
          EVERYTHING downstream assumes 1:1: the per-landmark fix loop, the PROSAC landmark
          weight (a duplicated landmark silently gets 2–3× the sampling priority it was
          assigned), and S_l's Σ_k. None of it crashes; it quietly reweights the product's
          differentiator. Making it a loud ValueError at the boundary is the whole point of
          having a validate(). See §4.4's extract_at contract for the producer-side rule."""

    def select(self, idx: np.ndarray) -> "FeatureSet": ...

    def concat(self, other: "FeatureSet") -> "FeatureSet":
        """Raises IncompatibleDescriptors if kind/dim/extractor_name differ."""

    def transform(self, T: np.ndarray) -> "FeatureSet":
        """Map keypoints through a 3x3 homography (lifts ASIFT tilt-sim keypoints back
        into the original frame). Descriptors unchanged; affine frames pushed forward
        by the local Jacobian of T."""


@dataclass(frozen=True, slots=True)
class ExtractorCapabilities:
    supports_mask: bool
    supports_extract_at: bool
    supports_batch: bool
    is_affine_covariant: bool
    requires_grayscale: bool
    device: Device
    max_features: int
```

```python
# ai_engine/src/ai_engine/types/cache.py     ★ NEW (IU-01). Protocols only. numpy + stdlib.
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ImageStore(Protocol):
    """Resolves an ImageRef.sha256 back to pixels. Implemented by
    ai_engine.runtime.cache.DictImageStore (IU-08) and by the backend's ObjectStorage
    adapter. Declared here so ai_engine.types.features can NAME it (§4.3)."""

    def get(self, sha256: str) -> np.ndarray | None: ...
    def put(self, sha256: str, image: np.ndarray) -> None: ...


@runtime_checkable
class CacheBackend(Protocol):
    """Feature/descriptor cache. MatchContext.cache is typed on THIS, not on the concrete
    DiskCache — which is what lets a test inject NullCache with nothing installed."""

    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, *, ttl_s: int | None = None) -> None: ...
```

### 4.4 `ai_engine.extractors.base`

```python
# ai_engine/src/ai_engine/extractors/base.py
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from ai_engine.types import DescriptorKind, ExtractorCapabilities, FeatureSet


class FeatureExtractor(ABC):
    name: ClassVar[str]
    descriptor_kind: ClassVar[DescriptorKind]
    descriptor_dim: ClassVar[int]
    version: ClassVar[str]

    @abstractmethod
    def extract(
        self,
        image: np.ndarray,                 # (H,W,3) uint8 RGB  or (H,W) uint8 gray
        mask: np.ndarray | None = None,    # (H,W) uint8; nonzero = allowed region
    ) -> FeatureSet:
        """Detect + describe. MUST return a validate()-clean FeatureSet.
        MUST return an empty (0-length) FeatureSet rather than raise when nothing is found."""

    @abstractmethod
    def extract_at(
        self,
        image: np.ndarray,
        points: np.ndarray,                # (K,2) float32 (x,y) — the USER'S LANDMARKS
        *,
        sizes: np.ndarray | None = None,   # (K,) float32 patch diameter px; None => config default
        angles: np.ndarray | None = None,  # (K,) float32 rad; None => extractor estimates (or 0)
        landmark_ids: np.ndarray | None = None,  # (K,) int32 written into FeatureSet.landmark_ids
    ) -> FeatureSet:
        """★ Describe at CALLER-SUPPLIED points. The user's landmarks were never detected
        by anything, so this is the only way they enter the descriptor space. THIS METHOD
        IS THE HINGE THE ENTIRE LANDMARK ALGORITHM TURNS ON.

        ★ THE CARDINALITY CONTRACT, both directions:

          * The returned set MAY be SHORTER than K — points outside the valid patch margin
            are DROPPED, and `landmark_ids` tells the caller which survived.
          * The returned set MUST NOT be LONGER than K, and `landmark_ids` MUST contain no
            duplicates. Implementations whose backend emits multiple orientations per point
            (`cv2.SIFT.compute` does exactly this for bi-modal gradient patches) MUST
            collapse to the highest-response orientation per input point, or pass an
            explicit `angles` array to suppress the orientation search.

        v1.0 specified only the shrink direction, so a K=8 call could legally return N=14
        with landmark_ids many-to-one and silently distort PROSAC's sampling order and S_l's
        weighted mean. Multiplicity BELONGS in LandmarkPatchBank (best-over-tilt-sims,
        §4.23) — a structure designed for it. extract_at stays 1:1.

        Impl: SIFT/ORB/AKAZE/BRISK -> cv2 .compute(); SuperPoint -> bilinear grid_sample of
        the dense descriptor map; DINOv2 -> bilinear sample of the patch-token grid."""

    def extract_batch(
        self,
        images: Sequence[np.ndarray],
        masks: Sequence[np.ndarray | None] | None = None,
    ) -> list[FeatureSet]:
        """Default: serial loop. Deep extractors override with real tensor batching."""

    def capabilities(self) -> ExtractorCapabilities: ...

    def warmup(self) -> None:
        """Force lazy weight load + one dummy forward. Called by preflight(), never per-request."""

    def params_hash(self) -> str: ...
```

**Registered extractors** (registry name → class → fallback):

| `name` | class | kind | D | weights | fallback |
|---|---|---|---|---|---|
| `sift` | `SiftExtractor` | float | 128 | — | **None (TERMINAL)** |
| `orb` | `OrbExtractor` | binary | 256 | — | **None (TERMINAL)** |
| `akaze` | `AkazeExtractor` | binary | **488** | — | `orb` |
| `brisk` | `BriskExtractor` | binary | 512 | — | `orb` |
| `asift` | `AffineSimulatedExtractor` | float | 128 | — | `sift` |
| `superpoint` | `SuperPointExtractor` | float | 256 | ✔ | `sift` |
| `dinov2` | `Dinov2DenseExtractor` | float | 384 | ✔ | `sift` |

> **★ AKAZE is `D = 488`, not 486.** OpenCV's AKAZE MLDB carries **486 significant bits**, which cv2 returns as **61 bytes**. §4.3 defines BINARY storage as `(N, D//8) uint8` and `FeatureSet.descriptor_dim` as `descriptors.shape[1] * 8`. With `D = 486`: `486 // 8 == 60 ≠ 61`, and `61 * 8 == 488 ≠ 486`. So the ClassVar could **never** equal the computed property, `Matcher.validate_pair` compares exactly that field, and **every AKAZE FeatureSet would raise `IncompatibleDescriptors` at composition time** — on a registered, non-exotic extractor whose fallback is `orb`. `descriptor_dim` declares the **storage width**; the final 2 bits are zero pad. Hamming distance is unaffected (pad bits are zero in both operands). `FeatureSet.validate()` now asserts `descriptor_dim % 8 == 0` for every BINARY extractor, and IU-03 asserts it at registration — so the next extractor with a non-byte-aligned bit count fails loudly instead of at a matcher.

SIFT descriptors are stored **L2-normalised float32** with **RootSIFT** applied by default (L1-normalise → element-wise sqrt → L2-normalise). Normalise at the boundary so `DescriptorKind.FLOAT` means exactly one thing everywhere.

### 4.5 `ai_engine.types.matches` + `ai_engine.matchers.base`

```python
# ai_engine/src/ai_engine/types/matches.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ai_engine.types.features import FeatureSet


@dataclass(frozen=True, slots=True)
class MatchSet:
    indices: np.ndarray            # (M,2) int32. col 0 -> index into a, col 1 -> index into b
    scores: np.ndarray             # (M,) float32 in [0,1], HIGHER = BETTER, matcher-normalised
    matcher_name: str
    distances: np.ndarray | None = None  # (M,) float32 raw descriptor distance (L2 or Hamming)
    ratios: np.ndarray | None = None     # (M,) float32 Lowe ratio d1/d2; NaN where inapplicable
    mutual: np.ndarray | None = None     # (M,) bool — passed cross-check
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_matches(self) -> int: ...

    def validate(self, n_a: int, n_b: int) -> None:
        """Raise on out-of-range indices, duplicate (i,j) pairs, scores outside [0,1]."""

    def select(self, idx: np.ndarray) -> "MatchSet": ...

    def to_correspondences(self, a: FeatureSet, b: FeatureSet) -> "Correspondences":
        """Materialise indices into points. The ONLY bridge from the detector-based
        world into the pipeline's universal currency."""


@dataclass(frozen=True, slots=True)
class Correspondences:
    """★ THE PIPELINE'S UNIVERSAL CURRENCY. Every source produces this; every consumer
    reads this. Neither Matcher nor DetectorFreeMatcher appears in a pipeline signature."""
    pts_a: np.ndarray              # (M,2) float32 — QUERY IMAGE pixels
    pts_b: np.ndarray              # (M,2) float32 — WINDOW pixels
    scores: np.ndarray             # (M,) float32 in [0,1]
    image_size_a: tuple[int, int]
    image_size_b: tuple[int, int]
    source_name: str
    is_dense: bool                 # True => produced detector-free; no stable feature indices exist
    weights: np.ndarray | None = None
        # ★ (M,) float32 > 0. Landmark-derived PRIORITY, not confidence. PROSAC sort key.
    landmark_ids: np.ndarray | None = None   # (M,) int32; >=0 => from user landmark k, -1 otherwise
    prior_free: bool = True
        # ★ NEW. False => these correspondences were produced with a prior_H gate (the guided
        #   pass, or pass 1 seeded from landmark fixes). LOAD-BEARING FOR HONESTY: a gated set's
        #   inlier ratio and RMS are bounded by the gate itself, so S_f/S_g computed on it measure
        #   GATE EFFICACY, not correctness. §4.12 requires S_f and S_g be computed on the
        #   prior_free pass. Without this flag the scorer cannot tell the two apart.
    feature_sets: tuple[FeatureSet, FeatureSet] | None = None  # None when is_dense
    match_set: MatchSet | None = None                          # None when is_dense
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_correspondences(self) -> int: ...

    def select(self, idx: np.ndarray) -> "Correspondences": ...

    def sorted_by_weight(self) -> tuple["Correspondences", np.ndarray]:
        """Descending by (weights if not None else scores). Returns the permutation too.
        PROSAC REQUIRES this ordering; passing unsorted data to SAMPLING_PROSAC silently
        degrades it to uniform sampling."""

    @staticmethod
    def merge(items: Sequence["Correspondences"], *, dedupe_px: float = 2.0) -> "Correspondences":
        """Union of several sources. Two correspondences are duplicates iff BOTH endpoints
        are within dedupe_px; the higher-weight one survives."""


@dataclass(frozen=True, slots=True)
class CorrespondenceRequest:
    image_a: np.ndarray
    image_b: np.ndarray
    features_a: FeatureSet | None = None   # precomputed/cached; ignored by detector-free
    features_b: FeatureSet | None = None
    mask_a: np.ndarray | None = None
    mask_b: np.ndarray | None = None
    prior_H: np.ndarray | None = None      # triggers the guided path when not None
    prior_cov: np.ndarray | None = None
    guided_radius_px: float = 32.0
    landmark_weights: LandmarkWeightField | None = None   # ★ imported from ai_engine.types.landmarks
```

```python
# ai_engine/src/ai_engine/matchers/base.py
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from ai_engine.types import Correspondences, DescriptorKind, FeatureSet, MatchSet


class Matcher(ABC):
    name: ClassVar[str]
    supported_kinds: ClassVar[frozenset[DescriptorKind]]
    requires_images: ClassVar[bool] = False   # True ONLY for detector-free shims
    version: ClassVar[str]

    @abstractmethod
    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Descriptor matching + the matcher's own filtering (ratio test, cross-check,
        or learned assignment). MUST call self.validate_pair(a, b) first.
        MUST return an empty MatchSet rather than raise when nothing matches."""

    def match_guided(
        self,
        a: FeatureSet,
        b: FeatureSet,
        *,
        prior_H: np.ndarray,                  # (3,3) float64 mapping a-frame -> b-frame
        radius_px: float,                     # search disk radius in the b frame
        prior_cov: np.ndarray | None = None,  # (9,9) cov of vec(prior_H); widens radius per-point
    ) -> MatchSet:
        """★ Spatially-constrained matching. Default impl: full match(), then reject any pair
        whose ||p_b - prior_H(p_a)|| > radius_eff. Efficient impls override to build the
        candidate list per-point BEFORE descriptor comparison (KD-tree over b's keypoints) —
        which is where the real accuracy comes from: the ratio test is then computed against
        only the SPATIALLY PLAUSIBLE competitors, so the second-nearest neighbour is no longer
        a random field-texture repeat.
        radius_eff(p_a) = radius_px + k*sqrt(trace(J Sigma_H J^T)), k=2.0, when prior_cov given."""

    def supports(self, a: FeatureSet, b: FeatureSet) -> bool: ...

    def validate_pair(self, a: FeatureSet, b: FeatureSet) -> None:
        """Raise IncompatibleDescriptors if:
           - a.descriptor_kind != b.descriptor_kind
           - a.descriptor_kind not in self.supported_kinds
           - a.descriptor_dim != b.descriptor_dim
           - a.extractor_name != b.extractor_name  (WARN only — ASIFT/SIFT cross is legitimate)"""

    def params_hash(self) -> str: ...


class DetectorFreeMatcher(ABC):
    """For LoFTR and successors. Detection and matching are inseparable, so the
    interface admits it instead of pretending."""
    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def match_images(
        self,
        image_a: np.ndarray,               # (H,W,3) uint8 RGB
        image_b: np.ndarray,
        mask_a: np.ndarray | None = None,
        mask_b: np.ndarray | None = None,
    ) -> Correspondences:
        """Emits Correspondences with is_dense=True, feature_sets=None, match_set=None."""

    def match_images_guided(
        self,
        image_a: np.ndarray,
        image_b: np.ndarray,
        *,
        prior_H: np.ndarray,
        radius_px: float,
        mask_a: np.ndarray | None = None,
        mask_b: np.ndarray | None = None,
    ) -> Correspondences:
        """Default: match_images() then spatial gate. Real impls mask the coarse-level
        attention to the prior-consistent band, which is both faster and more accurate."""

    def match_images_batch(
        self, pairs: Sequence[tuple[np.ndarray, np.ndarray]],
    ) -> list[Correspondences]: ...
```

**Score normalisation contract.** `MatchSet.scores` must be comparable **across matchers**, because `S_f` averages them:
- Ratio-test matchers (FLANN/BF): `score = clip((r_thr - r) / (r_thr - r_min), 0, 1)` with `r_thr = 0.8`, `r_min = 0.3`.
- Learned matchers (SuperGlue/LightGlue/LoFTR): the network's own match confidence, already in `[0,1]`.

**Registered matchers:**

| `name` | class | kinds | family | weights | fallback |
|---|---|---|---|---|---|
| `bf` | `BruteForceMatcher` | float, binary | detector-based | — | **None (TERMINAL)** |
| `flann` | `FlannMatcher` | float, binary | detector-based | — | `bf` |
| `superglue` | `SuperGlueMatcher` | float (D=256) | detector-based | ✔ | `flann` |
| `lightglue` | `LightGlueMatcher` | float | detector-based | ✔ | `flann` |
| `loftr` | `LoFTRMatcher` | — | **detector-free** | ✔ | `flann` (via source swap) |

`FlannMatcher` selects its index from `descriptor_kind` automatically — `KDTreeIndexParams(trees=4)` for FLOAT, `LshIndexParams(table_number=12, key_size=20, multi_probe_level=2)` for BINARY — and raises `IncompatibleDescriptors` on a mixed pair. This is precisely the bug class `descriptor_kind` exists to prevent: FLANN-KDTree on packed ORB bytes returns plausible-looking garbage rather than failing.

### 4.6 `ai_engine.matchers.sources` — the seam

```python
# ai_engine/src/ai_engine/matchers/sources.py
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ai_engine.types import Correspondences, CorrespondenceRequest
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.matchers.base import DetectorFreeMatcher, Matcher


@runtime_checkable
class CorrespondenceSource(Protocol):
    """★ THE seam the pipeline depends on."""
    name: str

    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...
    def params_hash(self) -> str: ...


class DetectBasedSource:
    """extractor + matcher -> Correspondences."""

    def __init__(self, extractor: FeatureExtractor, matcher: Matcher) -> None:
        """★ ASSERTS `not matcher.requires_images`, so LoFTRAsMatcher can never be
        silently wired into the normal path."""

    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...


class DetectorFreeSource:
    """LoFTR -> Correspondences. Natural fit; no adaptation, no loss."""

    def __init__(self, matcher: DetectorFreeMatcher) -> None: ...
    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...


class EnsembleSource:
    """Union of sources. Correspondences.merge() dedupes. THE recommended deep config:
    LoFTR finds correspondence in the low-texture field interior where SIFT finds nothing;
    SIFT nails the high-frequency corners LoFTR's 1/8-resolution coarse stage misses.
    They fail in complementary places — the only good reason to ensemble."""

    def __init__(self, sources: Sequence[CorrespondenceSource], *, dedupe_px: float = 2.0) -> None: ...
    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...
```

`LoFTRAsMatcher` (`ai_engine/matchers/loftr.py`) exists **only** for `Matcher`-typed external plugin sockets, is documented as LOSSY, sets `requires_images = True`, and raises `DetectorFreeRequiresImages` when `image_ref` is unresolvable. The pipeline never uses it.

### 4.7 `ai_engine.types.geometry` + `ai_engine.geometry.base`

```python
# ai_engine/src/ai_engine/types/geometry.py
from dataclasses import dataclass

import numpy as np

from ai_engine.types.enums import HomographyMethod


@dataclass(frozen=True, slots=True)
class RansacConfig:
    method: HomographyMethod = HomographyMethod.USAC_MAGSAC
    threshold_px: float = 3.0      # for MAGSAC this is an UPPER BOUND on noise, not a tuned gate
    confidence: float = 0.999
    max_iters: int = 10_000
    min_inliers: int = 12          # hard floor; 4 is the algebraic minimum, 12 the statistical one
    refine: bool = True            # LM re-fit on inliers (symmetric transfer)
    compute_covariance: bool = True
    lo_method: int = 4             # cv2.LOCAL_OPTIM_SIGMA
    lo_iterations: int = 10
    seed: int = 42                 # -> UsacParams.randomGeneratorState. VERIFIED settable.
    normalize: bool = True         # Hartley pre-conditioning


@dataclass(frozen=True, slots=True)
class HomographyResult:
    H: np.ndarray                  # (3,3) float64, a-frame -> b-frame.
                                   #   Scale-fixed: H /= H[2,2] if |H[2,2]| > 1e-12
                                   #   else H /= ||H||_F  (H[2,2]≈0 is legal: the line at
                                   #   infinity maps through the principal point)
    inlier_mask: np.ndarray        # ★ (M,) bool, ALWAYS aligned to the Correspondences object
                                   #   PASSED IN — never to any internal sort order. See the
                                   #   un-permutation rule below.
    num_inliers: int
    reproj_error: float            # symmetric transfer RMS over INLIERS, px
    method: HomographyMethod
    num_iters: int
    threshold_px: float
    refined: bool
    condition_number: float        # ★ cond_2 on the HARTLEY-NORMALISED H~, not H
    determinant: float             # ★ det(H~)
    covariance: np.ndarray | None = None
        # ★ (9,9) float64. cov of vec_ROW(H), in the SAME GAUGE AS `H` — see cov_gauge.
        #   ROW-MAJOR ordering, normatively and everywhere (§4.24).
    cov_gauge: Literal["h33_1", "unit_norm"] = "h33_1"
        # ★ LOAD-BEARING. Which gauge `covariance` is expressed in, matching how `H` was
        #   scale-fixed. "h33_1" is the normal case; "unit_norm" ONLY in the |H[2,2]|<=1e-12
        #   branch, where the h33=1 Jacobian is undefined. §4.24 defines the conversion and
        #   §7.5's A_h MUST branch on this field.
    normalization: tuple[np.ndarray, np.ndarray] | None = None   # (T_a, T_b)
    residuals: np.ndarray | None = None    # (M,) per-correspondence symmetric transfer error, px,
                                           #   aligned to the INPUT Correspondences (same rule as
                                           #   inlier_mask)
    sigma_r: float | None = None           # ★ recovered per-residual noise sigma, px. Persisted so
                                           #   IU-05 can assert it against known injected noise —
                                           #   the executable pin on §4.24's DOF factor.

    def warp_points(self, pts: np.ndarray) -> np.ndarray: ...

    def warp_points_with_cov(
        self, pts: np.ndarray, pt_cov: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """-> ((N,2) warped, (N,2,2) covariance). PIXEL covariance. Metres are gis's job."""

    @property
    def inlier_ratio(self) -> float: ...


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    K: np.ndarray                  # (3,3) float64
    source: str                    # "exif" | "fov" | "vanishing_points" | "assumed" | "manual"
    focal_px: float
    principal_point: tuple[float, float]
    confidence: float              # [0,1]


@dataclass(frozen=True, slots=True)
class PoseResult:
    """★ THE FRAME CONVENTION, stated once (§4.24 is the master):
       World  = local ENU, metres: X east, Y north, Z up.
       Camera = OpenCV: x right, y down, z forward.
       Relation:  p_cam = R @ p_world + t_cam_from_world.
    """
    R: np.ndarray                  # (3,3) float64, world->camera
    t_cam_from_world: np.ndarray
        # ★ (3,) float64, METRES. The TRANSLATION in `p_cam = R p_world + t`. It is the world
        #   origin expressed in CAMERA coordinates. It is NOT the camera's position.
    camera_position_enu: np.ndarray
        # ★ (3,) float64, METRES, local ENU. = -R.T @ t_cam_from_world. THIS is the camera.
        #   camera_height_m := camera_position_enu[2]; the lon/lat comes from [0:2] via gis.pose.
        #
        #   ★ v1.0 had ONE field, `t`, documented three mutually incompatible ways in two
        #     paragraphs: "camera position of the plane origin", "(3,) camera position, metres,
        #     local ENU", and "(3,) WINDOW PIXEL units". Under the stated p_cam = R p_world + t,
        #     t is the translation, and C = -R.T t is the position. An implementer taking the
        #     docstring literally and setting camera_height_m = t[2] gets an answer that is
        #     EXACTLY RIGHT AT NADIR (where R ≈ diag(1,-1,-1) so t = (0,0,h)) and wrong
        #     everywhere else: t_z is the DEPTH to the plane origin along the optical axis, so
        #     at tau=60 deg it overstates height by 2x and at 80 deg by ~5.8x. Three of the four
        #     supported regimes are oblique. A nadir-only test cannot see this — §13.1 IU-05
        #     therefore tests tau ∈ {0, 45, 80}.
    yaw_deg: float
        # ★ 0 = -y of the WINDOW frame (i.e. UP the raster), clockwise, [0,360).
        #   For a north-up raster this IS north, so PoseResult.yaw_deg == camera_poses.yaw_deg
        #   and the common case needs no conversion.
        #
        #   ★ v1.0 said "0 = +y of the window frame". A north-up raster has NEGATIVE
        #     pixel_height (GDAL order, §4.16), so window +y points SOUTH: PoseResult.yaw_deg==0
        #     meant SOUTH while camera_poses.yaw_deg==0 meant NORTH, with no conversion specified
        #     anywhere in the chain. A silent 180 deg error in the field that aims the Leaflet
        #     view cone — which is precisely the failure §5.6 congratulates itself on preventing
        #     ("yaw conventions are the classic silent-disagreement bug between a CV module and a
        #     map renderer").
        #
        #   NOTE this is still a WINDOW-frame bearing. Converting it to a true North bearing for
        #   camera_poses.yaw_deg requires the geotransform's rotation AND grid convergence, and
        #   is gis.pose.window_yaw_to_north_deg()'s job (§4.28) — ai_engine cannot do it (L3).
    pitch_deg: float               # 0=horizon, + = up, [-90,90]
    roll_deg: float                # + = clockwise, [-180,180]
    intrinsics: CameraIntrinsics
    method: PoseMethod             # ★ an ENUM, and every member is a `pose_method` PG label.
                                   #   v1.0 typed this `str` with values
                                   #   "zhang_plane" | "decompose_homography" | "none", of which
                                   #   `zhang_plane` — the PRIMARY method — had NO enum label, and
                                   #   `decompose_homography` != the enum's `homography_decomposition`.
                                   #   camera_poses.method is NOT NULL: every Zhang-plane pose was
                                   #   literally unwritable. §5.3 adds the label.
    reproj_error_px: float
    inlier_count: int
    ambiguity: tuple["PoseResult", ...] = ()   # alternative solutions, disambiguation failed
    sigma_deg: tuple[float, float, float] | None = None   # (yaw, pitch, roll) 1-sigma


class PoseMethod(StrEnum):
    """Mirrors the `pose_method` PG enum (§5.3) member-for-member. Parity-tested."""
    ZHANG_PLANE              = "zhang_plane"               # ★ PRIMARY (§2.2 pose.py)
    HOMOGRAPHY_DECOMPOSITION = "homography_decomposition"  # decomposeHomographyMat fallback
    PNP                      = "pnp"
    EXIF_GPS_ONLY            = "exif_gps_only"
    MANUAL                   = "manual"
    HEATMAP_ARGMAX           = "heatmap_argmax"
```

```python
# ai_engine/src/ai_engine/geometry/base.py
from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np

from ai_engine.types import HomographyResult, RansacConfig


class GeometryEstimator(ABC):
    name: ClassVar[str]

    @abstractmethod
    def estimate_homography(
        self,
        pts_a: np.ndarray,                  # (M,2) float32/float64
        pts_b: np.ndarray,                  # (M,2)
        config: RansacConfig,
        *,
        weights: np.ndarray | None = None,  # (M,) float32 > 0. PROSAC ordering key.
                                            #   Caller MUST pass pts sorted desc by weight,
                                            #   or use Correspondences.sorted_by_weight().
    ) -> HomographyResult:
        """Raises InsufficientCorrespondences if M < 4.
        Returns a result with num_inliers < config.min_inliers RATHER THAN RAISING —
        the DegeneracyValidator decides what is acceptable, not the estimator.
        Separation of concerns: estimation reports, policy judges.

        ★ THIS METHOD IS SORT-ORDER-IN, SORT-ORDER-OUT. `inlier_mask` and `residuals` are
          aligned to the `pts_a`/`pts_b` HANDED TO IT. Sorting for PROSAC is the CALLER's
          job, and un-permuting is therefore also the caller's job — see
          step6_estimate_homography (§4.13), which is normatively required to do both."""

    @abstractmethod
    def refine_homography(
        self, H0: np.ndarray, pts_a: np.ndarray, pts_b: np.ndarray, *,
        weights: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """LM minimisation of the symmetric transfer error on the given (inlier) set.
        -> (H_refined (3,3), covariance (9,9) | None).
        The covariance is ROW-MAJOR vec(H) in the h33=1 gauge — §4.24, normatively."""
```

**Registered estimator backend:** `opencv` → `OpenCvHomographyEstimator`. **Terminal, no weights, no fallback.** This is the ONLY member of `ComponentKind.ESTIMATOR`, and `AiEngineConfig.estimator_backend` (default `"opencv"`) is the only thing that selects it.

> **★ "estimator" named two different things, and it was a boot crash.** `MatchRequest.estimator`, `match_jobs.estimator`, `projects.default_estimator` and `match_results.estimator_used` all carry the **`robust_estimator` PG enum** (`ransac|usac_magsac|lmeds|prosac|usac_accurate|lsq`) — which is `RansacConfig.method`, a `HomographyMethod`. But `AiEngineConfig.estimator` was a **component registry key**, and `LE_AI_ESTIMATOR` defaulted to `usac_magsac` and was routed into it. On an **empty environment**, `resolve_with_fallback("usac_magsac", ComponentKind.ESTIMATOR)` finds no spec, finds no `spec.fallback`, exhausts the chain, and raises `ComponentUnavailable` **at preflight** — a traceback on zero config, violating L10, L11 and §9.13's "`uvicorn app.main:app` with no env → 200". Worse, it was baked into the DB: `match_service` would read `usac_magsac` off `projects.default_estimator` and hand it to the registry **on every job**.
>
> **The ruling:** two names, two concepts, no overlap.
> - `AiEngineConfig.estimator_backend: str = "opencv"` ← `LE_AI_ESTIMATOR_BACKEND`. A **registry key**.
> - `AiEngineConfig.ransac.method: HomographyMethod = USAC_MAGSAC` ← `LE_AI_RANSAC_METHOD`. A **method**.
> - `MatchRequest.estimator: EstimatorName` maps **1:1** onto `RansacConfig.method` via `HomographyMethod(value)` and **never reaches `Registry.resolve`**. The DB columns keep the name `estimator` (they are on the wire and persisted) but §6.1 now states their meaning explicitly.



### 4.8 `ai_engine.types.landmarks`

```python
# ai_engine/src/ai_engine/types/landmarks.py
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class LandmarkType(StrEnum):
    UNSPECIFIED       = "unspecified"
    FIELD_CORNER      = "field_corner"
    ROAD_INTERSECTION = "road_intersection"
    BUILDING_CORNER   = "building_corner"
    TREE              = "tree"
    POLE_OR_PYLON     = "pole_or_pylon"
    FENCE_POST        = "fence_post"
    OTHER             = "other"


@dataclass(frozen=True, slots=True)
class Landmark:
    id: int                                  # dense 0..K-1 index within the job
    xy: tuple[float, float]                  # QUERY IMAGE pixels, y-down, top-left origin
    type: LandmarkType = LandmarkType.UNSPECIFIED
    label: str | None = None
    radius_px: float = 32.0
    user_weight: float = 1.0                 # from annotations.confidence (0-1), scaled
    sigma_px: float = 3.0                    # ★ human click precision — the DOMINANT query-side error


@dataclass(frozen=True, slots=True)
class LandmarkSet:
    items: tuple[Landmark, ...]
    external_ids: tuple[str, ...] = ()       # opaque; backend puts annotations.id UUIDs here.
                                             #   ai_engine NEVER parses these.

    @property
    def points(self) -> np.ndarray: ...      # (K,2) float32
    @property
    def weights(self) -> np.ndarray: ...     # (K,) float32
    def __len__(self) -> int: ...


@dataclass(frozen=True, slots=True)
class LandmarkFix:
    """A direct correspondence for landmark k, found by patch search in the window."""
    landmark_id: int
    window_xy: tuple[float, float]
    score: float                             # [0,1]
    method: str                              # "patch_ncc" | "descriptor" | "guided"
    used_in_solve: bool = False
        # ★ NEW, and it is what makes the S_l `transfer` term honest.
        #   True => this fix fed the solve: it seeded H_seed, was merged in as a
        #   correspondence, or received PROSAC sampling priority. Such a fix is INELIGIBLE
        #   for transfer_k, because measuring the residual of a fit against the very points
        #   that produced the fit is a FITTING RESIDUAL SOLD AS A SECOND OPINION.
        #   §4.12 makes the consequence normative.


@dataclass(frozen=True, slots=True)
class LandmarkEvidence:
    landmark_id: int
    has_direct_fix: bool
    fix: LandmarkFix | None
    support_count: int                       # inliers within radius_px of the landmark
    patch_score: float | None                # [0,1] NCC of the warped patch
    transfer_error_px: float | None
    transfer_is_holdout: bool = False        # ★ True <=> transfer_error_px was measured against
                                             #   a fix with used_in_solve=False. When False,
                                             #   transfer_k MUST be None (§4.12).
    semantic_agreement: float | None = None  # [0,1]
    score: float = 0.0                       # [0,1] combined — see the S_l formula (§4.12)


@dataclass(frozen=True, slots=True)
class LandmarkWeightField:
    """★ Referenced by CorrespondenceRequest.landmark_weights (§4.5) and by the PROSAC
    weighting of §4.12. v1.0 named it in a copy-pasteable signature and defined it nowhere.

    Evaluates a per-correspondence sampling PRIORITY from proximity to user landmarks:

        g(p) = ( Σ_k w_k · exp(-d_k(p)² / (2·R_L²)) ) / max(Σ_k w_k, eps)      # ★ NORMALISED
        priority(p) = base_score(p) · (1 + lam·g(p)) · (1 + mu·on_landmark(p))

    ★ THE NORMALISATION IS THE FIX. v1.0's g_i was a bare SUM over K landmarks with
      w_k ∈ [0.25, 4.0], and its comment claimed a "~12x" maximum priority. With 12
      landmarks clustered inside R_L at w_k=4, g_i ≈ 48 and the factor is
      (1+2·48)(1+3) = 388x — two orders of magnitude, against a base_score spanning only
      one. PROSAC's ordering would collapse into a pure landmark-DENSITY map, discarding
      descriptor quality entirely, and it would degrade WORST in the exact case the design
      targets: a surveyor who marked many landmarks on one structure. Dividing by Σ w_k
      puts g ∈ [0,1] and makes the stated 12x bound the real bound.
    """
    points: np.ndarray                       # (K,2) float32 — landmark positions, QUERY px
    weights: np.ndarray                      # (K,) float32 — Landmark.user_weight
    radius_px: float = 96.0                  # R_L
    lam: float = 2.0                         # lambda — density boost
    mu: float = 3.0                          # mu — exact-landmark boost

    def evaluate(self, pts: np.ndarray) -> np.ndarray:
        """(M,2) -> (M,) float32 in [0,1]. This is g(p), NOT the final priority."""


@dataclass(frozen=True, slots=True)
class LandmarkProposal:
    """★ The output of a LandmarkSuggester (§4.23). Maps 1:1 onto a `landmark_suggestions`
    row. ai_engine proposes; a human accepts; only then is it an annotation (ADR-014)."""
    xy: tuple[float, float]                  # QUERY IMAGE pixels
    kind: LandmarkType
    score: float                             # [0,1] the detector's own
    rank: int                                # 1 = best
    rationale: str                           # human-readable "why" -> landmark_suggestions.rationale


class SuggestionStrategy(StrEnum):
    CORNERS  = "corners"
    SALIENCY = "saliency"
    SEMANTIC = "semantic"
    HYBRID   = "hybrid"
```

### 4.9 `ai_engine.types.degeneracy` + the check list

```python
# ai_engine/src/ai_engine/types/degeneracy.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai_engine.types.enums import Severity


@dataclass(frozen=True, slots=True)
class DegeneracyCheck:
    code: str                # e.g. "insufficient_inliers"
    severity: Severity
    passed: bool
    factor: float            # SOFT: multiplicative in [0,1]. HARD: 1.0 if passed else 0.0.
    detail: Mapping[str, Any]
    message: str


@dataclass(frozen=True, slots=True)
class DegeneracyReport:
    checks: tuple[DegeneracyCheck, ...]
    gate: float              # 0.0 if ANY hard failure, else prod(soft factors). [0,1].
    hard_failures: tuple[str, ...]
    soft_penalties: Mapping[str, float]

    @property
    def rejected(self) -> bool: ...   # gate == 0.0
```

**`DegeneracyValidator` (`ai_engine/geometry/degeneracy.py`) — normative check list.**

HARD — any failure ⇒ `gate = 0.0` ⇒ `confidence = 0` ⇒ `status = "rejected"`:

| | code | condition |
|---|---|---|
| H1 | `insufficient_inliers` | `n_in < 12` |
| H2 | `determinant_sign` | `det(H̃) ≤ 0` (reflection) |
| H3 | `quad_not_convex` | warped image quad non-convex / self-intersecting |
| H4 | `vanishing_line_crosses_roi` | **(a)** `d = h₃₁u + h₃₂v + h₃₃` **changes sign** over the ROI; **or (b)** `max_ROI ‖J_p‖₂ / median_ROI ‖J_p‖₂ > κ_transfer` (default `1e3`), sampled over the ROI boundary **and** interior |
| H5 | `collinear_inliers` | PCA `λ₂/λ₁ < 0.01` |
| H6 | `inlier_hull_too_small` | `hull_area < 0.05 · image_area` |
| H7 | `reproj_error_too_high` | `> 8.0 px` |
| H8 | `extreme_anisotropy` | `σ₁/σ₂ > 20` at the inlier centroid |
| H9 | `scale_out_of_range` | `log₁₀(area_ratio) ∉ [−5.0, 2.5]` |
| H10 | `landmarks_out_of_bounds` | `> 50%` of landmarks warp outside window + 10% margin |
| H11 | **DELETED** | *(was `landmark_topology` — see below)* |
| H12 | `nan_or_inf` | non-finite in `H` or `Σ_H` |
| H13 | `placeholder_window` | `> 20%` blank/no-imagery tiles in the window |

**H11 is deleted, and the check numbering is NOT renumbered** — H12/H13 keep their codes so persisted `degeneracy_report` JSONB from any earlier build stays readable.

SOFT — multiply the gate: `S1 condition_number` (κ_ok=1e4 → κ_max=1e7, log-interpolated, on `H̃`) · **S2 DELETED** · `S3 anisotropy_soft` · `S4 hull_area_soft` · `S5 many_to_one` · `S6 flatness` (`exp(−(rms/1.0)²)`) · `S7 landmark_coverage` · `S8 covariance_health`.

```
gate = 0.0 if hard_failures else Π(soft factors)
```

> **★ H11 was mathematically vacuous, and it was counted as one of the "three independent layers" defending against a wrong field.** Its justification was: *"A homography is a projectivity: for points on the ground plane in front of the camera it PRESERVES the cyclic order of the convex hull. This catches the classic 'matched a different but visually identical field' error, which no reprojection threshold can catch because it fits beautifully."* **The first sentence is true and it is precisely why the check is useless.** A projective map preserves convexity, hull membership and hull cyclic order for **any** point set whose hull does not intersect the preimage of the line at infinity — **for any H, correct or wrong.** Orientation reversal requires `det(H̃) ≤ 0`. Both preconditions are *already hard-checked*, by **H4** and **H2** respectively. So H11 could only ever fire when H4 or H2 had already fired, and it was **provably incapable** of distinguishing the right field from a visually identical wrong one — the only job it was given. IU-05 now asserts the negative: construct a valid H passing H2 and H4, assert H11's condition never trips. **Topology is H-invariant; a wrong-field discriminator must be METRIC.** The honest replacement is landmark-pair ground **distance ratios** (via `gsd_m`) and `median_k(transfer_residual_px)` from **genuinely held-out** direct fixes (§4.12) — and note that the second only works once `transfer_k`'s independence is real, which is a separate fix. §12.5 now records plainly that **the ambiguity clamp is RELATIVE and cannot detect a globally-wrong-but-unique answer.** We do not claim a wrong-field defence we do not have.

> **★ H4's old threshold self-disabled in exactly the case it existed to catch.** The condition was `min|d| < 1e-6·|h₃₃|` — scaled against `h₃₃`. But §4.7 blesses the branch `H /= ‖H‖_F` when `|H[2,2]| ≤ 1e-12`, explicitly because *"H[2,2]≈0 is legal: the line at infinity maps through the principal point"*. In that branch `h₃₃ ≈ 0`, so the threshold is `≈ 0` and **the test can never fire — in precisely the configuration where the vanishing line most certainly IS inside the ROI.** The check inverted: most permissive exactly where it must be strictest. The sign-change test still fired, so the *tangency* case (line grazing the ROI, no sign change, transferred coordinates blowing up to 10⁶) passed clean. Even in the `h₃₃=1` branch the threshold was far too loose to mean what it claimed: `d = 1e-3` passes by a factor of a thousand while already transferring the point 1000× its numerator — *"the enormous, plausible-looking coordinates"* the check is named after. **The new (b) clause tests the quantity that actually matters — the transferred magnitude — is gauge-free, invariant to both scale-fixing branches, and has a physical reading:** *"part of your marked area is being stretched a thousand times more than the rest."* `J_p` is already computed for the covariance path (§7.5), so this costs nothing new.

> **H4 still earns its place.** It catches `H` being singular *inside the data* — reprojection error cannot see it, because the surviving inliers all sit on the good side of the vanishing line.

> **★ S2 is deleted because spatial entropy was being counted twice.** `S_g = √ρ_in · exp(−(ε_rms/ε₀)²) · **√U**` (§4.12) and soft gate `S2 = **√U**` over the identical 3×3 inlier-count grid. Since `raw = D · Σ w_i S_i / Σ w_i` with `D = Π(soft gates)`, `U` entered **once inside S_g and once through D**: a clustered solve at `U = 0.25` was penalised `0.5 × 0.5 = 0.25×` instead of `0.5×`. Entropy stays in **S_g**, where §4.12's rationale is explicit that it belongs (*"U distinguishes 100 inliers spread across the frame from 100 inliers in one corner"*). Same defect, same ruling for **flatness**: `S6 = exp(−(rms/1.0)²)` **and** an independent post-score downgrade by the identical expression turned an intended `0.368` into `0.135` at `rms = 1.0 m`. **The post-score flatness downgrade is DELETED; S6 carries it.** (`status ← "advisory"` on `flatness_rms > 0.5` survives — §4.12 specifies it independently.) Both double-counts pushed toward rejection, so they were *safe-direction* — but they made the §4.12 weight table **not mean what it says**, and they corrupted the `feature_vector` that §10.7 persists **so calibration can be refit offline**. A Platt fit over a doubly-counted feature learns a curve nobody can reason about. **IU-07 now asserts the structural invariant that prevents the next one: every element of `feature_names()` appears in exactly ONE of {S_f, S_g, S_l, S_s, gate}.**

### 4.10 `ai_engine.types.windows` — ★ THE PACKAGE SEAM

This is the single most important type in the system. It is how `gis` hands pixels to `ai_engine` **without `ai_engine` learning what a CRS is** (L3).

```python
# ai_engine/src/ai_engine/types/windows.py
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True, slots=True)
class WindowRef:
    """Opaque handle. ai_engine treats `key` as a cache key and NEVER parses it."""
    key: str                  # opaque provider-minted string. Structure is gis's business.
    provider: str             # provenance string only — never control flow


@dataclass(frozen=True, slots=True)
class CandidateWindow:
    """One searchable patch of satellite imagery, in PIXELS.

    ★ THE CONTRACT: `geotransform` and `crs` are an OPAQUE PAYLOAD. ai_engine carries
      them through to MatchJobResult and NEVER interprets them. Only gis may.
      This is what makes L3 mechanically true and what makes swapping one provider for
      another unable to change the matching algorithm: the provider changes the pixels
      and six floats; ai_engine cannot tell the difference and does not care.
    """
    ref: WindowRef
    rgb: np.ndarray                  # (H,W,3) uint8 RGB, C-contiguous
    geotransform: tuple[float, float, float, float, float, float]
        # ★ OPAQUE. GDAL order. CARRIED, NEVER READ.
        #   PROHIBITION (not a preference): no module under ai_engine/ may INDEX this tuple.
        #   Its linear coefficients are in the provider's projected units, which for a
        #   Web-Mercator provider are NOT true ground metres — they are inflated by
        #   1/cos(phi), i.e. 74% at 55 deg N, which is serious agricultural country. Anything
        #   metric built from it is wrong by that factor, silently. `gsd_m` below is the ONLY
        #   sanctioned metric scale inside ai_engine. §10.5 greps for indexing of this field
        #   inside ai_engine/geometry/.
    crs: str
        # ★ OPAQUE authority string minted by the provider. NEVER PARSED HERE.
        #   (This comment deliberately names no concrete code — see the L3 note below.)
    gsd_m: float
        # ★ TRUE GROUND METRES PER PIXEL at the window centre, cos(phi)-corrected.
        #   PASSED IN by gis; never derived here (deriving it needs the window's ground
        #   position, which is exactly what ai_engine may not know).
        #   ★ "TRUE" IS LOAD-BEARING AND WAS PREVIOUSLY ONLY IMPLIED: PixelAccuracy.relative_m
        #     and the Zhang-plane pose frame (§4.23) both multiply pixels by this, and both are
        #     correct ONLY because it is cos-corrected. v1.0 never stated that invariant, so an
        #     implementer had no way to know it was load-bearing.
    georef_ce90_m: float             # ★ the PROVIDER's own absolute georeferencing error, CE90 m.
                                     #   Frequently the DOMINANT error term and NOT reducible by
                                     #   anything ai_engine does. Carried into AccuracyEstimate.
    attribution: str
        # ★ REQUIRED. §4.16 argues at length that get_static_bbox returns a SatelliteChip rather
        #   than a bare tuple precisely because "a bare tuple lets pixels travel without their
        #   attribution, which is a licence condition" and "making attribution a required field
        #   means the obligation is unforgeable". v1.0 then converted SatelliteChip ->
        #   CandidateWindow across THIS seam and dropped the field — forging the unforgeable
        #   obligation at the one seam where pixels enter the matching engine and the persisted
        #   match_results row that §11.5 requires serve X-Imagery-Attribution and every PDF.
    terms_url: str                   # ★ same argument; surfaced in UI and PDF exports.
    captured_at: "datetime | None" = None
        # ★ SatelliteChip has it; CandidateWindow dropped it; MatchJobResult never carried it;
        #   and yet §4.21's NORMATIVE CSV column order requires `imagery_captured_at` and
        #   ExportContext requires it of every writer. export_service had nowhere to read it
        #   from. This is also the field ProviderCapabilities.imagery_date_known exists to
        #   answer. Wired end to end: chip -> window -> match_results -> MatchResultRead -> CSV.
    is_authoritative: bool = False   # True => survey-grade georeferencing (local orthophoto)
    placeholder_fraction: float = 0.0  # [0,1] fraction of blank/no-imagery source tiles -> H13
    bands: tuple[str, ...] = ("R", "G", "B")
    supports_multispectral: bool = False   # gates true NDWI vs the HSV heuristic
    extra_bands: Mapping[str, np.ndarray] | None = None
        # ★ (H,W) float32 per band, keys matching bands[3:] (e.g. "NIR", "SWIR16").
        #   Without this, `supports_multispectral=True` — the entire point of the Sentinel
        #   provider — could never be honoured, and semantics/indices.py's ndwi()/mndwi() had
        #   NO NIR/SWIR input to read. SemanticSegmenter.segment(bands=...) is fed from here.
        #   MUST be None when supports_multispectral is False; ndwi/mndwi raise ValueError
        #   rather than silently substituting a green-band proxy.
    meta: Mapping[str, Any] = field(default_factory=dict)
        # ★ NORMATIVE KEYS, set by gis.candidates.source.TileWindowSource. ai_engine writes
        #   none of them and reads only `zoom_clamped`; the backend persists the rest.
        #     "tile_z" | "tile_x" | "tile_y"      : int  — the window's ANCHOR tile (its NW-most
        #                                            source tile). Addressing metadata only; a
        #                                            1024px window at overlap 0.5 is NOT
        #                                            addressable by a single (z,x,y) and the
        #                                            transform is `geotransform`, never these.
        #                                            Nullable at the DB (§5.6) for providers with
        #                                            no tile pyramid.
        #     "mosaic_cols" | "mosaic_rows"       : int
        #     "zoom_clamped"                      : bool — the provider could not serve the
        #                                            requested zoom. Routed to a ZOOM_CLAMPED
        #                                            WarningItem + degraded=true (§4.19).

    @property
    def size(self) -> tuple[int, int]: ...   # (width, height)


@runtime_checkable
class WindowSource(Protocol):
    """★ THE SEAM. `gis.candidates.source.TileWindowSource` satisfies this STRUCTURALLY
    (no inheritance). ai_engine declares the protocol it needs; gis implements it; the
    composition root (backend.services.match_service) injects it.

    SYNCHRONOUS by design: ai_engine runs inside Celery worker processes, and forcing
    an event loop into CPU-bound worker code buys nothing. Implementations may use
    asyncio and thread pools internally behind this sync facade."""
    name: str

    def __len__(self) -> int:
        """Total window count. Known up front — the search plan is computed before
        any fetching (§4.19). This is what makes progress reporting honest."""

    def __iter__(self) -> Iterator[CandidateWindow]:
        """Yield windows lazily.

        ★ MAY raise `ai_engine.errors.WindowFetchError` for an INDIVIDUAL window; the
          orchestrator logs it, counts it, and continues to the next. It may raise no other
          non-programmer exception across this seam: an implementation MUST wrap its own
          transport errors (`gis.errors.ProviderError` and friends) in WindowFetchError,
          because `ai_engine.pipeline` MUST NOT import `gis` (§10.2) and therefore cannot
          name — let alone catch — a gis exception. Its only alternative would be
          `except Exception`, which §4.13 declares a defect."""
```

> **★ The L3 grep and this file.** §10.5's L3 gate is case-insensitive over `ai_engine/src/`, and v1.0's verbatim source for **this very file** contained `crs: str  # OPAQUE. e.g. "EPSG:3857"` and `# never computed here (computing it needs latitude)` — **two hits, on the two comments whose whole purpose is to explain the L3 boundary.** Any agent pasting §4.10 as instructed failed `verify_boundaries.sh` on IU-01's first commit — the first unit in the build order. **Both fixes are applied, and both are stated so all twelve agents write the same thing:** (1) §10.5's grep now strips comment lines and excludes `tests/`; (2) the comments above are reworded to name no concrete authority code and no coordinate word. The second is the better fix independently — **naming a concrete CRS inside the type that exists to be CRS-agnostic invites exactly the parsing L3 forbids.**

### 4.11 `ai_engine` remaining types (`scoring`, `results`, `semantics`, `heatmap`)

```python
# ai_engine/src/ai_engine/types/scoring.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ai_engine.types.degeneracy import DegeneracyReport
from ai_engine.types.enums import ViewRegime
from ai_engine.types.landmarks import LandmarkEvidence, LandmarkSet
from ai_engine.types.matches import Correspondences
from ai_engine.types.geometry import HomographyResult
from ai_engine.types.semantics import SemanticMap
from ai_engine.types.windows import CandidateWindow


@dataclass(frozen=True, slots=True)
class ScoreTerms:
    s_feature: float          # [0,1]
    s_geometry: float         # [0,1]
    s_landmark: float         # [0,1]
    s_semantic: float | None  # [0,1] or None if semantics unavailable -> weights renormalise
    gate: float               # [0,1] degeneracy gate, multiplicative
    weights: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ScoreEvidence:
    correspondences: Correspondences
    homography: HomographyResult
    degeneracy: DegeneracyReport
    landmarks: LandmarkSet
    landmark_evidence: Sequence[LandmarkEvidence]
    query_semantics: SemanticMap | None
    window_semantics: SemanticMap | None
    regime: ViewRegime
    query_image_size: tuple[int, int]
    window: CandidateWindow


@dataclass(frozen=True, slots=True)
class ScoreResult:
    confidence: float           # ★ 0..100 — THE number the product reports
    raw: float                  # [0,1] pre-calibration, pre-clamp weighted sum * gate
    terms: ScoreTerms
    calibrated: bool            # ★ ships FALSE. A fabricated curve is a lie with a probability.
    calibration_id: str         # "identity" | "default-v1" | ...
    clamp_reason: str | None    # e.g. "regime=oblique_raw ceiling 60"
    status: Literal["accepted", "advisory", "rejected"]
    feature_vector: np.ndarray  # (F,) float32 — raw terms, PERSISTED so calibration can be
                                #   refit offline without re-running any CV
```

```python
# ai_engine/src/ai_engine/types/results.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ai_engine.types.degeneracy import DegeneracyReport
from ai_engine.types.enums import ViewRegime
from ai_engine.types.geometry import HomographyResult, PoseResult
from ai_engine.types.heatmap import PixelHeatmap
from ai_engine.types.landmarks import LandmarkEvidence
from ai_engine.types.matches import Correspondences
from ai_engine.types.provenance import ResolutionReport   # ★ types -> types. NEVER types -> models.
from ai_engine.types.scoring import ScoreResult
from ai_engine.types.windows import CandidateWindow


@dataclass(frozen=True, slots=True)
class PixelAccuracy:
    """★ PIXELS ONLY. This type carries our fit's uncertainty IN THE WINDOW FRAME and
    stops there. Metres are gis.accuracy's job — §4.20 is the SINGLE PRODUCER of the
    four survey numbers (relative_m, georef_ce90_m, total_ce90_m, dominant_term).

    ★ v1.0 had the SAME FOUR NUMBERS in THREE places: ai_engine.types.results.PixelAccuracy,
      gis.accuracy.AccuracyEstimate, and schemas.gcp.GcpAccuracy — produced independently by
      IU-08 and IU-09, with nothing stating which one populated `gcps`. Worse, §4.20 declares
      gis.accuracy "the module that must never see a degree or a 3857 metre" and gives it the
      Jacobian + 1/cos(phi) correction — while PixelAccuracy.relative_m was defined as
      `relative_px * window.gsd_m` COMPUTED INSIDE ai_engine: the exact metre-vs-Mercator-metre
      conflation §4.20 exists to prevent. It happened to be right only because gsd_m is
      cos-corrected — an invariant v1.0 stated nowhere as load-bearing (it now is, §4.10).

      Three producers of one number is three chances to disagree. There is now one.
    """
    relative_px: float          # our fit to the provider's pixels, 1-sigma, WINDOW PIXELS
    cov_px: np.ndarray          # (2,2) float64 covariance in WINDOW PIXELS. The full anisotropy —
                                #   gis.accuracy needs it to build the error ellipse, and
                                #   collapsing it to one scalar here would throw away what §7.5
                                #   calls "the most actionable part of the estimate".


@dataclass(frozen=True, slots=True)
class GcpPixelFix:
    """★ ai_engine's DELIVERABLE. Note what is ABSENT: lat, lon, elevation.
    gis.crs turns `window_xy` into a coordinate. That is the boundary (L3)."""
    landmark_id: int
    external_id: str | None      # opaque echo of LandmarkSet.external_ids[k]
    image_xy: tuple[float, float]
    window_xy: tuple[float, float]
    cov_px: np.ndarray           # (2,2) float64 covariance in WINDOW pixels
    residual_px: float | None    # ||H*image_xy - direct_fix|| when a direct fix exists
    confidence: float            # 0..100
    accuracy: PixelAccuracy
    has_direct_fix: bool


@dataclass(frozen=True, slots=True)
class WindowResult:
    window: CandidateWindow
    correspondences: Correspondences
    homography: HomographyResult | None      # None when estimation was not attempted
    degeneracy: DegeneracyReport
    score: ScoreResult
    landmark_evidence: tuple[LandmarkEvidence, ...]
    regime: ViewRegime
    pose: PoseResult | None = None
    timings_ms: Mapping[str, float] = ...


@dataclass(frozen=True, slots=True)
class MatchJobResult:
    """★ The ONLY thing run_match_job returns."""
    job_id: str
    ranked: tuple[WindowResult, ...]         # rank 1 first. EMPTY is a legitimate result.
    best: WindowResult | None                # None <=> no window passed the gates
    gcp_fixes: tuple[GcpPixelFix, ...]       # from `best`; empty when best is None
    heatmaps: tuple[PixelHeatmap, ...] = ()
        # ★ PLURAL, and each carries its own WindowRef. v1.0 had a singular
        #   `heatmap: PixelHeatmap | None` documented as "GMM over camera locations, in WINDOW
        #   PIXELS", while confidence_heatmaps stores an AOI-WIDE grid in TRUE METRES spanning
        #   up to 25 windows across multiple zoom levels. A single window-pixel frame CANNOT
        #   express that, and NO named function converted or fused them: gis had no heatmap
        #   module, §10.2 assigned no owner, and heatmap_service.py was left to improvise a type
        #   mismatch. Fusion is now gis.heatmap.fuse_pixel_heatmaps() (§4.26) — which can do it
        #   because each PixelHeatmap's WindowRef recovers the window and hence its geotransform.
    provenance: ResolutionReport             # ★ WHICH components actually produced this
    ambiguity_margin: float | None
        # ★ computed on ScoreResult.RAW, never on the clamped confidence (§4.12).
    status: str                              # "matched" | "no_viable_candidate" | "ambiguous"
    warnings: tuple[str, ...]
    timings_ms: Mapping[str, float]
    engine_version: str
    seed: int
```

```python
# ai_engine/src/ai_engine/scoring/base.py
from abc import ABC, abstractmethod
from typing import ClassVar

from ai_engine.types import ScoreEvidence, ScoreResult


class ScoringModel(ABC):
    name: ClassVar[str]

    @abstractmethod
    def score(self, evidence: ScoreEvidence) -> ScoreResult: ...

    @abstractmethod
    def feature_names(self) -> tuple[str, ...]:
        """Column names for ScoreResult.feature_vector. Stable across versions, or the
        persisted training data becomes unreadable."""
```

```python
# ai_engine/src/ai_engine/semantics/base.py
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from ai_engine.types import SemanticCapabilities, SemanticMap


class SemanticSegmenter(ABC):
    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def segment(
        self,
        image: np.ndarray,
        *,
        bands: Mapping[str, np.ndarray] | None = None,   # multispectral when available
    ) -> SemanticMap: ...

    def capabilities(self) -> SemanticCapabilities: ...
```

```python
# ai_engine/src/ai_engine/types/semantics.py   (the part v1.0 imported but never defined)

@dataclass(frozen=True, slots=True)
class SemanticCapabilities:
    """★ `semantics/base.py` does `from ai_engine.types import SemanticCapabilities` while
    §2.2 listed types/semantics.py as `SemanticMap · CropRowField · TreeLattice · RidgeSet`
    only — a hard ImportError on IU-06's first line."""
    classes: frozenset[SemanticClass]   # what this segmenter can actually emit
    requires_multispectral: bool        # True => needs CandidateWindow.extra_bands
    requires_weights: bool
    supports_prompts: bool              # SAM point/box prompts
    is_deterministic: bool
    device: Device
```

Registered segmenters: `classical` → `ClassicalSemantics` (**TERMINAL**, default) · `sam` → `SamSegmenter` (weights, → `classical`) · `dinov2_seg` → `Dinov2Semantics` (weights, → `classical`).

### 4.12 `ai_engine` scoring formula (normative)

```
raw_ungated = (w_f·S_f + w_g·S_g + w_l·S_l + w_s·S_s) / (w_f + w_g + w_l + w_s)
raw         = D · raw_ungated                    # persisted as ScoreResult.raw

Confidence  = min( 100 · D · calib(raw_ungated), ceiling(regime), ambiguity_clamp )

★ D == 0  ⇒  Confidence = 0, status = "rejected".  SHORT-CIRCUITED, normatively, BEFORE
             calib() is ever called — logit(0) = -inf and Platt would return NaN, not 0.
             v1.0 left this as an accident of the formula.
```

**Unavailable terms drop from BOTH numerator and denominator.** A neutral 0.5 injects fake evidence; a 0 penalises a config choice as if it were evidence. The renormalisation is recorded in `score_breakdown` as `"renormalized": true`.

> **★ The gate multiplies OUTSIDE the calibrator, not inside it.** v1.0 fitted Platt on `raw` — which already contained `D` — so `σ(a·logit(raw) + b)` with a fitted `a < 1` **flattens the curve and compresses the gates' effect**: a solve whose soft gates halved `raw` from 0.8 to 0.4 might lose only a few points of final confidence. §8.5 presents the gates as a safety mechanism *independent* of the score, but layer 1 (soft gates) sat **inside** the thing layer 4 (calibration) is free to reshape. Fitting on `raw_ungated` and multiplying by `D` afterwards makes that independence **true**. This is latent today (identity calibration ⇒ `a=1, b=0`) and **activates the moment a real curve ships** — which is exactly the kind of bug that lands long after everyone has stopped looking. `ScoreResult.feature_vector` persists **both** `raw_ungated` and `D` so §10.7's offline refit can see them separately.

| term | definition | default weight |
|---|---|---|
| `S_f` | `(n_in²/(n_in²+n₀²)) · q̄`, `n₀=30`, `q̄` = mean inlier match score. ★ **Computed on the PRIOR-FREE pass** — see below. | **0.25** |
| `S_g` | `√ρ_in · exp(−(ε_rms/ε₀)²) · √U`, `ε₀=3px`, `U` = 3×3 inlier-spatial entropy / log 9. ★ **Computed on the PRIOR-FREE pass.** `U` appears **here only** (soft gate S2 is deleted, §4.9). | **0.35** |
| `S_l` | `Σ_k w_k·score_k / Σ_k w_k`; `score_k = 0.30·support + 0.25·patch + 0.30·transfer + 0.15·sem` **only when a HELD-OUT direct fix exists** (`transfer_is_holdout`), else `0.45·support + 0.35·patch + 0.20·sem` | **0.30** |
| `S_s` | `0.40·s_hist + 0.30·s_orient + 0.30·s_mask` (JSD not KL; `cos(2Δθ)` folds the 180° line ambiguity). ★ `s_orient` transport and gating below. | **0.10** |

`D ∈ {0} ∪ (0,1]` is the degeneracy gate.

**Regime ceilings:** `nadir` 100 · `oblique_rectifiable` 85 · `oblique_raw` 60 · `ground_horizon` 35 · `unknown` 50.

**Calibration target:** `Confidence/100 ≈ P(absolute error < 5 m)`. Platt by default, isotonic at n>2000. **Ships as identity with `calibrated=False`.**

#### 4.12.1 `S_f`/`S_g` are computed on the prior-free pass — the guided rematch may not score itself

The pipeline runs an **unguided pass 1** (`c1`, `h1`), then a **guided pass 2** gated to `r_eff = clamp(3·h1.reproj_error, 8, 48)` px around `prior_H = h1.H` (`c2`, `h2`).

> **★ NORMATIVE: `S_f` and `S_g` are computed from `c1`/`h1` — the pass with `Correspondences.prior_free == True`. `c2`/`h2` refine `H` and `Σ_H` ONLY. The geometry gets the benefit of the guided pass; the SCORE does not.**
>
> Every factor in `S_f` and `S_g` is inflated by the gate itself, **for a wrong solve exactly as much as for a right one**: `ρ_in = n_in/n_matches` is computed after the gate has already removed the geometric outliers, so it measures **gate efficacy, not correctness**; `ε_rms` is **bounded above by the gate radius by construction**; and the documented magnitude is not subtle — *"inliers 25 → 120+ on farmland"* drives `S_f` from `25²/(25²+900) = 0.41` to `120²/(120²+900) = 0.94` **with zero new independent evidence**. The weights make it decisive: `w_f + w_g = 0.60` of the numerator. And §10's own rationale claims the exact opposite of what the ordering did — *"S_g and S_l are the terms a wrong field fails"*, *"geometric consistency is the hardest to fake; random matches do not produce a consistent H"*. **Under a guided rematch, a wrong field's H is made consistent BY THE GATE.** Worked: a wrong-but-similar field at `S_f=0.9, S_g=0.9, S_l=0.68, S_s=0.7, D=1` → `raw = 0.814` → **confidence 81, status "accepted"**.
>
> `feature_vector` persists `n_in_unguided`, `rho_in_unguided`, `eps_rms_unguided`, `n_in_guided` so the inflation is visible to offline recalibration.
>
> When pass 1 was **itself** seeded (`H_seed` from ≥4 landmark fixes), `c1.prior_free` is `False` and **no prior-free evidence exists at all**. That is not fatal but it must not be free: a soft penalty applies, and `score_breakdown` records `"prior_free_evidence": false`.

#### 4.12.2 `transfer_k` requires a HELD-OUT fix, or it is `None`

> **★ NORMATIVE: a `LandmarkFix` with `used_in_solve == True` is INELIGIBLE for `transfer_k`.** `LandmarkEvidence.transfer_error_px` may only be measured against a fix that entered the solve in **no** way, and `transfer_is_holdout` records it. Where no held-out fix exists, `transfer_k` is `None` and the `otherwise` branch of `score_k` applies — machinery that already exists.
>
> `transfer_k` was made the **strongest sub-term** (0.30 of `score_k`, with the others redistributing when it is present) on an explicit independence argument: *"a landmark located by its own patch bank, WITHOUT reference to the global H, agreeing with where the global H puts it. Two independent estimators agreeing is worth far more than either alone."* **The pipeline destroyed that independence three times over before `transfer_k` was computed:** the fixes **seed** `H_seed` (`|fixes| ≥ 4` → LSQ fit); `H_seed` then **gates** every pass-1 correspondence at 64 px; the fixes are **merged in** as correspondences; and they receive `μ=3.0` → **~12× PROSAC sampling priority**, so the minimal samples are drawn from them first. Then `transfer_k = exp(−(r_k/ε_L)²)` with `r_k = ‖fix_k − h2.H·l_k‖` measures the residual of that fit **and reports it as corroboration**. It is a **fitting residual sold as a second opinion**, and it was worth 30% of the term carrying `w_l = 0.30` — *"the product's differentiator, and independent evidence from the texture channel"*.
>
> Hold-out sources, in order: structural fixes found *after* `H_seed` was fitted from patch_nn fixes; otherwise a **k-fold hold-out** over the fix set. IU-07 asserts: **a job in which every fix seeded `H_seed` produces `transfer_k = None` for every landmark.** Independence you cannot demonstrate is not independence.

#### 4.12.3 `s_orient` — transport the direction through the full Jacobian, and gate on conditioning

```
d      = (cos θ_rows_q, sin θ_rows_q)                  # query row direction
J      = J_p at the inlier centroid                    # (2,2), ALREADY computed for §7.5
d'     = J @ d                                         # ★ NOT R @ d
θ_warp = atan2(d'_y, d'_x)  folded to [0, π)
s_orient = (1 + cos(2·Δθ)) / 2,   Δθ = θ_warp − θ_rows_w
```

> **★ A homography's local Jacobian is a general 2×2 — rotation, anisotropic scale AND shear.** A line direction transforms as `J·d`; it equals `R·d` **only when J is a similarity**. v1.0 pushed θ through *"H's local rotation"*, but §8.1 states the anisotropy this must survive — *"local anisotropy (σ₁/σ₂) of 5–50×"* — and H8 admits solves up to `σ₁/σ₂ = 20`. At `σ₁/σ₂ = 20` the rotation-only push is off by **tens of degrees**, and via the `(1+cos2Δθ)/2` folding a 45° error drives `s_orient` to 0.5 and a 90° error to **0**. The term §10.5 deliberately weights **highest among the structural cues** was therefore **actively penalising correct oblique matches**. The fix is one line and needs no new machinery — `J_p` is already there for the covariance path.
>
> **Gates (both required):** `s_orient` is weighted **0** when either coherence `< 0.3` (existing rule) **or** `cond(J) > 10` — at that conditioning the pushed orientation is itself ill-posed, and `s_mask`/`s_hist` carry `S_s`.

#### 4.12.4 Ambiguity — the margin is taken on `raw`, never on `confidence`

```
1. cluster windows by centroid distance < window_size/2; keep the best per cluster
   (overlapping windows SHOULD both score high — that is AGREEMENT, not ambiguity)
2. margin = (raw[0] − raw[1]) / max(raw[0], eps)        # ★ on RAW. scale-free.
3. margin < LE_AI_RANK_MARGIN/100  ⇒  status = "advisory", ambiguity_clamp = 40
4. ★ while calibrated == False, the numeric margin is ADVISORY ONLY and the primary
   ambiguity signal is the posterior's entropy_norm > 0.6 (§4.26).
```

> **★ Taking the margin on `confidence` made the clamp fire on saturation, not on evidence.** `Confidence` is already `min(..., ceiling(regime), ...)`, and **`ViewRegime` is a property of the QUERY IMAGE — so every window in a job shares one ceiling.** Whenever two windows exceeded it, both confidences were **exactly the ceiling**, `margin = c[0]/c[1] = 1.000 < 1.05`, and the job was declared ambiguous **by an artefact of the `min()`**, with the ranking signal that would have separated them destroyed before the ratio was taken. For `ground_horizon` (ceiling 35) and `oblique_raw` (ceiling 60) that is the **common case, not a corner**. And the converse: a genuine two-field ambiguity at raw 0.90 vs 0.80 gave `margin = 1.125` and **no clamp at all**. A 5% threshold on an uncalibrated, ceiling-clamped, `min()`-composed score is not measuring ambiguity. The clustering step was right and is kept verbatim. IU-07 asserts: **two windows both above the regime ceiling are NOT flagged advisory on ambiguity grounds alone.**

#### 4.12.5 Per-landmark confidence has no floor

```
conf_k = confidence · clip(score_k / max(S_l, eps), 0.0, 1.0)        # ★ floor 0.0, not 0.5
```

> **★ v1.0's `clip(..., 0.5, 1.0)` capped the penalty at 2× and contradicted its own rationale** — *"a landmark far from every inlier is EXTRAPOLATED by H and deserves less confidence than one sitting in a dense inlier cluster"*. A landmark with `score_k = 0` (no local inlier support, no patch agreement, no semantic agreement) still reported **half the job's confidence**: on an accepted job at 80, a landmark the solve supports **not at all** was exported at 40 — above `min_confidence` (40 by §12 C-14 / 25 in the AI doc), and therefore **shipped as a GCP with no per-GCP indication that it is unsupported**. Meanwhile §7.5's covariance path handles the same case correctly and continuously (*"A_h Σ_H A_hᵀ grows quadratically with distance from the inlier cloud… two landmarks in one solve can differ by 5× in error"*) — so the error ellipse said 5× worse while the confidence said at most 2× worse. **The upper clip at 1.0 stays** (a landmark cannot be more confident than its solve). A landmark whose `conf_k < min_confidence` is emitted with `QualityFlag.unsupported_landmark` rather than a bare number.

### 4.13 `ai_engine.pipeline` — the 9 steps and the entry point

```python
# ai_engine/src/ai_engine/pipeline/context.py
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ai_engine.config import AiEngineConfig
from ai_engine.geometry.base import GeometryEstimator
from ai_engine.geometry.degeneracy import DegeneracyValidator
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.matchers.sources import CorrespondenceSource
from ai_engine.scoring.base import ScoringModel
from ai_engine.semantics.base import SemanticSegmenter
from ai_engine.types import (           # ★ CameraIntrinsics and CacheBackend are REAL imports.
    CacheBackend,                       #   v1.0's import line omitted CameraIntrinsics and then
    CameraIntrinsics,                   #   declared `intrinsics_hint: "CameraIntrinsics | None"`
    ImageRef,                           #   — an unresolved name under `mypy --strict` (CI gate
    LandmarkSet,                        #   §13.4 #3) and a NameError under any get_type_hints()
    ProgressCallback,                   #   introspection. Same class of defect as ImageRef.resolve.
    WindowSource,
)


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Immutable per-job bundle. Every dependency is INJECTED — the engine constructs
    nothing it could be given, which is what makes it testable with no network,
    no GPU, no weights and no DB."""
    job_id: str
    config: AiEngineConfig
    query_image: np.ndarray                  # (H,W,3) uint8 RGB
    query_image_ref: ImageRef
    landmarks: LandmarkSet
    windows: WindowSource                    # ★ injected by backend; implemented by gis
    extractor: FeatureExtractor
    source: CorrespondenceSource
    estimator: GeometryEstimator
    segmenter: SemanticSegmenter
    scorer: ScoringModel
    validator: DegeneracyValidator
    cache: CacheBackend
    intrinsics_hint: CameraIntrinsics | None = None     # from EXIF, resolved by backend
    on_progress: ProgressCallback | None = None
```

```python
# ai_engine/src/ai_engine/types/__init__.py     (the alias v1.0 named and never defined)

MatchStage = Literal[
    "resolving_models", "fetching_tiles", "extracting_query", "extracting_train",
    "matching", "estimating_homography", "scoring", "deriving_gcps",
]
ProgressCallback = Callable[[MatchStage, float, str], None]
```

> **★ `on_progress`'s stage is a CLOSED literal set, and it is identical to the `match` `JobStage` values.** v1.0 typed it `(stage: str, ...)` — a **free-form string** — while `JobProgress.stage: JobStage` is a closed enum the UI switches on, and §4.13 says *"the callback is the entire coupling"*. Nothing mapped whatever IU-08 chose (`step1_extract_query_features`? `extract_query`?) onto `extracting_query`, and **IU-08 and IU-20 are disjoint units that will not agree by luck.** Making the emitted set literally the JobStage values means `tasks/progress.py` needs no translation table at all. IU-08 asserts the emitted set is a subset of `MatchStage`; `core/constants.py` asserts `set(MatchStage) ⊆ set(STAGES[JobType.MATCH])`.

```python
# ai_engine/src/ai_engine/pipeline/orchestrator.py
from ai_engine.pipeline.context import MatchContext
from ai_engine.types import MatchJobResult


def run_match_job(ctx: MatchContext) -> MatchJobResult:
    """★ THE ONLY PUBLIC ENTRY POINT of ai_engine.

    Never raises for a business outcome. `NoViableCandidate` is returned as
    MatchJobResult(status="no_viable_candidate", best=None, gcp_fixes=()), NOT raised —
    "no match found" is a RESULT, not a failure (§11.6).

    Raises ONLY: ConfigurationError (bad config, caught at composition), and
    programmer errors. A caller wrapping this in try/except Exception is a defect.

    Progress: ctx.on_progress is called at every stage boundary. ai_engine knows
    nothing about Redis, Celery, or Postgres — the callback is the entire coupling."""
```

The 9 steps (`ai_engine/pipeline/steps.py`), each a pure typed function:

| # | Step | Function | Signature |
|---|---|---|---|
| 1 | Extract image features | `step1_extract_query_features` | `(ctx: MatchContext) -> FeatureSet` |
| 2 | Describe at landmarks | *fused into 1 via* `extractor.extract_at(...)` | — |
| 3 | Candidate windows | `step3_iter_windows` | `(ctx) -> Iterator[CandidateWindow]` |
| 4 | Window descriptors | `step4_extract_window_features` | `(ctx, w: CandidateWindow) -> FeatureSet` |
| 5 | Feature matching | `step5_correspond` | `(ctx, q: FeatureSet, t: FeatureSet, w: CandidateWindow) -> Correspondences` |
| 6 | Outlier rejection | `step6_estimate_homography` | `(ctx, c: Correspondences) -> HomographyResult` |
| 7 | Similarity score | `step7_score` | `(ctx, ev: ScoreEvidence) -> ScoreResult` |
| 8 | Rank | `step8_rank` | `(ctx, results: Sequence[WindowResult]) -> list[WindowResult]` |
| 9 | Best window → fixes | `step9_finalize` | `(ctx, ranked: Sequence[WindowResult]) -> MatchJobResult` |

> **★ `step6_estimate_homography` MUST sort, estimate, then UN-PERMUTE — and the returned `inlier_mask`/`residuals` are ALWAYS aligned to the `Correspondences` object it was passed.**
>
> ```python
> c_sorted, perm = c.sorted_by_weight()     # PROSAC REQUIRES desc-by-weight ordering
> res = ctx.estimator.estimate_homography(c_sorted.pts_a, c_sorted.pts_b, cfg, weights=...)
> inv = np.empty_like(perm); inv[perm] = np.arange(len(perm))
> res = replace(res, inlier_mask=res.inlier_mask[inv], residuals=res.residuals[inv])
> ```
>
> v1.0 required the sort (correctly — passing unsorted data to `SAMPLING_PROSAC` silently degrades it to uniform sampling) and then declared `inlier_mask` *"aligned to the input Correspondences"* while `residuals` is *"(M,) per-correspondence"*. **After the sort, both align to the SORTED order** — not to `WindowResult.correspondences`, which is the original. `sorted_by_weight()` returns the permutation, but `HomographyResult` had **no field to carry it** and nothing told step 7 or step 9 to invert it. Consequence: **every landmark-support count `S_l`, every `LandmarkEvidence.support_count`, and every `gcps.residual_px` silently indexes the WRONG correspondence.** No crash; entirely plausible numbers. Un-permuting inside step 6 keeps the permutation from ever escaping, which is why it belongs here and not in `HomographyResult`. IU-05 tests it with a deliberately unsorted weighted input.

> **Steps 1–2 are one interface, not two.** Detection and description are a single call in every real extractor; splitting them forces a wasteful re-traversal. Step 2 is realised as the descriptor path that genuinely *is* separate: `extract_at()` — describing at **externally supplied** points, i.e. the user's landmarks, which no detector proposed.

### 4.14 `ai_engine.models` — the registry

```python
# ai_engine/src/ai_engine/types/provenance.py     ★ IU-01. stdlib + typing ONLY.
#
# ★ THESE FOUR TYPES MOVED HERE FROM models/spec.py, AND THE MOVE IS LOAD-BEARING.
#   types/results.py needs ResolutionReport (MatchJobResult.provenance). In v1.0 it got it
#   via `from ai_engine.models.spec import ResolutionReport` — and that ONE import broke
#   FIVE things at once:
#     1. §3 IU-01's "May import: numpy, stdlib" and "Blocked by: —".
#     2. §10.2's "ai_engine.types MUST NOT import everything else — must stay import-cheap
#        forever; gis depends on it".
#     3. The build DAG became CYCLIC: IU-01 needed IU-02, IU-02 is blocked by IU-01.
#     4. A RUNTIME cycle: types/__init__ re-exports every dataclass, so `import
#        ai_engine.types` -> types.results -> ai_engine.models -> ai_engine.config ->
#        ai_engine.types (PARTIALLY INITIALISED) -> ImportError/NameError depending on
#        re-export order.
#     5. The `.importlinter` gis-purity contract, which forbids gis -> ai_engine.models and
#        reports INDIRECT chains: gis.candidates -> ai_engine.types -> ai_engine.types.results
#        -> ai_engine.models.spec is exactly that chain. verify_boundaries.sh went red on the
#        first commit that satisfied §4.11 and §4.19 simultaneously.
#   And worst at runtime: importing ai_engine.models.spec executes models/__init__.py, which
#   constructs the Registry singleton and pulls in policy/weights/device/torch_guard — so
#   `import gis.candidates` would drag in the model registry and the torch guard, destroying
#   the exact "types is cheap and cannot drag in cv2 or torch" property that §10.3 uses to
#   JUSTIFY the one permitted cross-package import.
#
#   Value objects belong to the vocabulary layer; behaviour belongs to models/.
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ai_engine.types.enums import Device


class ComponentKind(StrEnum):
    EXTRACTOR     = "extractor"
    MATCHER       = "matcher"
    DETECTOR_FREE = "detector_free"
    SEGMENTER     = "segmenter"
    ESTIMATOR     = "estimator"
    SCORER        = "scorer"
    SUGGESTER     = "suggester"      # ★ NEW — LandmarkSuggester (§4.23). Without it the
                                     #   registry could not resolve the component behind
                                     #   job_type='suggest_landmarks' and endpoints 43–45.


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    kind: ComponentKind
    factory: Callable[[Mapping[str, Any]], Any]  # ← the Mapping is defined in §4.14.1
    requires_weights: tuple[str, ...] = ()       # WeightManifest KEYS, not paths
    requires_packages: tuple[str, ...] = ()      # importable module names
    device_preference: Device = Device.AUTO
    fallback: str | None = None                  # None => TERMINAL
    is_terminal: bool = False                    # asserted: terminal => no reqs, no fallback


@dataclass(frozen=True, slots=True)
class Resolution:
    requested: str
    resolved: str
    instance: Any
    chain: tuple[str, ...]                       # e.g. ("superpoint", "sift")
    reason: str | None                           # "weights missing: superpoint_v1.pth"
    degraded: bool
    device: Device


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    resolutions: Mapping[ComponentKind, Resolution]
    any_degraded: bool

    def to_dict(self) -> dict: ...               # -> GET /api/v1/capabilities


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """★ Returned by models/preflight.py. Named in §2.2 and defined nowhere in v1.0.
    Built ONCE in main.py's lifespan and cached on app.state (§11.1)."""
    resolutions: ResolutionReport
    weights_dir: str | None
    device_selected: Device
    cuda_available: bool
    missing_weights: tuple[str, ...]
    any_degraded: bool
    checked_at: float
    messages: tuple[str, ...]        # e.g. "Classical CV pipeline is fully operational."
```

```python
# ai_engine/src/ai_engine/models/spec.py     ★ RE-EXPORT SHIM. Declares nothing.
from ai_engine.types.provenance import (          # noqa: F401
    ComponentKind, ComponentSpec, PreflightReport, Resolution, ResolutionReport,
)
```

```python
# ai_engine/src/ai_engine/models/policy.py   ★ THE ONLY PLACE FALLBACK POLICY EXISTS
def resolve_with_fallback(
    registry: "Registry",
    name: str,
    kind: ComponentKind,
    config: Mapping[str, Any],
    *,
    strict: bool = False,
    chain_limit: int = 4,
) -> Resolution:
    """Walk name -> spec.fallback -> ... until something constructs.

    For each candidate, IN ORDER (cheapest and least side-effecting first):
      1. spec exists in the registry for (name, kind)                     -> else next
      2. every requires_packages importable via importlib.util.find_spec()
         ★ find_spec, NOT import: no module side effects, no CUDA init, no
           2-second torch import just to discover we won't use it          -> else next
      3. every requires_weights resolvable AND sha256 matches the WeightManifest.
         ★ A corrupt/truncated download is treated EXACTLY like a missing one —
           a half-downloaded .pth that imports and then produces garbage is far
           worse than one that is simply absent                            -> else next
      4. device_preference satisfiable. ★ Device unavailability is the SAME failure
         class as missing weights and routes through this SAME branch. On the
         verified dev box this is the branch that actually fires.          -> else next
      5. spec.factory(config) inside try/except Exception                  -> else next

    Every fall-through emits a structured ComponentFallback event
    (requested, candidate, reason, exc_type) at WARNING. NEVER SILENT: a user MUST be
    able to discover that they configured SuperPoint and got SIFT.

    Cycle detection via a visited set; chain_limit caps depth.
    Terminal specs (fallback=None) MUST have no requires_weights and no
    requires_packages beyond the base install, so the chain PROVABLY terminates at
    something that always constructs. Asserted at registration time.

    strict=True (LE_AI_STRICT_BACKEND): raise ComponentUnavailable instead of falling
    back. For CI accuracy suites on a GPU box where a silent degradation would mean the
    deep path is untested while the suite goes green. TRUE IN PRODUCTION VIOLATES L1.

    Exhausted chain -> ComponentUnavailable, raised at COMPOSITION time (preflight),
    NEVER mid-request.
    """
```

```python
# ai_engine/src/ai_engine/models/__init__.py
class Registry:
    def register(self, spec: ComponentSpec) -> None: ...

    def resolve(self, name: str, kind: ComponentKind, config: Mapping[str, Any],
                *, strict: bool = False) -> Resolution:
        """Calls _ensure_registered() FIRST, then delegates to resolve_with_fallback()."""

    def specs(self, kind: ComponentKind | None = None) -> tuple[ComponentSpec, ...]:
        """Calls _ensure_registered() first."""

    # ★ build_context_components() is DELETED — see §4.14.2.


def register(kind: ComponentKind, **kw) -> Callable[[type], type]:
    """Class decorator.
    @register(ComponentKind.EXTRACTOR, fallback="sift", requires_weights=("superpoint_v1",))"""


_REGISTERED = False

def _ensure_registered() -> None:
    """★ THE REGISTRATION SITE. Idempotent, lazy, called at the top of resolve()/specs().

    A @register class decorator only fires when its module is IMPORTED, and v1.0 designated
    NO module to import them — so with 12 parallel agents, `Registry.specs()` would have been
    EMPTY at composition time and every resolve would have fallen through to
    ComponentUnavailable.

    Why the obvious placements are all wrong:
      * models/__init__.py importing ai_engine.extractors: §10.2 restricts models to
        torch(guarded) + stdlib + ai_engine.{types,errors}, AND extractors import models —
        a hard cycle.
      * ai_engine/__init__.py importing them: then gis's sanctioned
        `from ai_engine.types import CandidateWindow` executes the package __init__ and drags
        in cv2, scipy and every extractor — destroying §10.3's stated justification and
        breaking `cd gis && pytest`.

    The lazy call inside resolve() is the only placement that is neither cyclic nor eager:
    by the time anyone RESOLVES a component they are already in the pipeline, so importing
    the pipeline's modules costs nothing new. It mirrors §2.3's
    gis/imagery/providers/__init__.py explicit-registration pattern.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True
    from ai_engine.models import registration   # noqa: F401  — imports every @register site
```

**Weight resolution** (`models/weights.py`): `WeightManifest` maps a logical key → `(filename, sha256, size, url, license)`. Search order: `config.weights_dir` → `$LE_AI_MODEL_WEIGHTS_DIR` → `~/.cache/landexplorer/weights`. **NEVER auto-downloads.** `scripts/download_models.py` is the only downloader and is never invoked at build or boot.

#### 4.14.1 The component config mapping — normative key sets

`ComponentSpec.factory` takes a `Mapping[str, Any]`. **v1.0 never said how `AiEngineConfig` — a frozen dataclass with flat fields — becomes that Mapping, nor which keys `SiftExtractor(config)` or `FlannMatcher(config)` read.** IU-02, IU-03 and IU-04 are disjoint units; each would have invented its own key names, and `params_hash()` — **a cache-key input** per §4.3/§4.5 — would then differ per unit for identical configuration. Cache poisoning across a package boundary, from a naming disagreement.

`ai_engine.pipeline.compose.component_config(cfg, kind)` builds it, and these key sets are **exhaustive and normative**:

| `ComponentKind` | keys |
|---|---|
| `EXTRACTOR` | `max_features` · `clahe_enabled` · `weights_dir` · `device` · `asift` *(the AsiftConfig dict)* |
| `MATCHER` | `ratio_test` · `cross_check` · `min_matches` · `weights_dir` · `device` |
| `DETECTOR_FREE` | `weights_dir` · `device` · `deep` *(the DeepConfig dict)* |
| `SEGMENTER` | `weights_dir` · `device` · `semantics_enabled` |
| `ESTIMATOR` | `ransac` *(the RansacConfig dict)* |
| `SCORER` | `scoring` *(the ScoringConfig dict)* · `calibration_id` |
| `SUGGESTER` | `weights_dir` · `device` · `max_results` |

```python
def params_hash(mapping: Mapping[str, Any]) -> str:
    """★ NORMATIVE, and identical in every component:
         sha256(json.dumps(mapping, sort_keys=True, default=str).encode()).hexdigest()
       over EXACTLY the mapping above for that kind. Same config ⇒ same hash ⇒ same cache
       key, in every unit, forever."""
```

#### 4.14.2 `build_context` — the composition root inside `ai_engine`

```python
# ai_engine/src/ai_engine/pipeline/compose.py     ★ IU-08
def build_context(
    cfg: AiEngineConfig,
    *,
    registry: Registry,
    job_id: str,
    query_image: np.ndarray,
    query_image_ref: ImageRef,
    landmarks: LandmarkSet,
    windows: WindowSource,
    cache: CacheBackend | None = None,
    intrinsics_hint: CameraIntrinsics | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[MatchContext, ResolutionReport]:
    """★ Resolves every component, assembles the CorrespondenceSource, and returns a ready
    MatchContext plus the provenance report.

    ★ WHY THIS IS NOT Registry.build_context_components (v1.0's design, now deleted):
      1. ComponentKind has EXTRACTOR/MATCHER/DETECTOR_FREE/SEGMENTER/ESTIMATOR/SCORER/
         SUGGESTER — there is NO "source" kind, no "validator" kind, no "cache" kind. So a
         registry method could not produce MatchContext.source, .validator or .cache at all.
      2. It could not wrap a resolved matcher in DetectBasedSource even in principle,
         because §10.2 FORBIDS ai_engine.models from importing ai_engine.matchers.
      3. Its return type was an untyped `dict`.
      Composition needs to see every subpackage at once. That is a PIPELINE concern (IU-08,
      which may import all of ai_engine), not a REGISTRY concern.

    ★ THE SOURCE-SELECTION TABLE — normative, and stated nowhere in v1.0:

        cfg.detector_free   cfg.matcher   -> MatchContext.source
        ---------------------------------------------------------------------------
        None                set           -> DetectBasedSource(extractor, matcher)
        set                 set           -> EnsembleSource([DetectBasedSource(...),
                                                             DetectorFreeSource(...)])
        set                 None          -> DetectorFreeSource(detector_free)
        None                None          -> ConfigurationError

    Resolution order is EXTRACTOR -> MATCHER/DETECTOR_FREE -> ESTIMATOR -> SEGMENTER ->
    SCORER. The ResolutionReport is emitted BEFORE any window is fetched, which is what lets
    the worker report degradation at stage `resolving_models` — the instant it is known
    (§11.1).
    """
```

### 4.15 `ai_engine.config`

```python
# ai_engine/src/ai_engine/config.py
from dataclasses import dataclass, field
from pathlib import Path

from ai_engine.types import Device, RansacConfig


@dataclass(frozen=True, slots=True)
class DegeneracyConfig:
    min_inliers: int = 12                       # H1
    max_reproj_error_px: float = 8.0            # H7
    max_anisotropy: float = 20.0                # H8
    min_hull_area_frac: float = 0.05            # H6
    collinearity_ratio: float = 0.01            # H5
    scale_log10_range: tuple[float, float] = (-5.0, 2.5)   # H9
    max_landmarks_out_of_bounds_frac: float = 0.50         # H10
    max_placeholder_fraction: float = 0.20      # H13
    kappa_transfer: float = 1e3                 # ★ H4(b) — the gauge-free vanishing-line test
    cond_ok: float = 1e4                        # S1 lower knee
    cond_max: float = 1e7                       # S1 upper knee
    flatness_sigma_m: float = 1.0               # S6


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    w_feature: float = 0.25
    w_geometric: float = 0.35
    w_landmark: float = 0.30
    w_semantic: float = 0.10
    n0_inliers: float = 30.0                    # S_f knee
    eps0_px: float = 3.0                        # S_g RMS scale
    eps_landmark_px: float = 5.0                # transfer_k scale
    orient_coherence_min: float = 0.30          # s_orient gate
    orient_cond_max: float = 10.0               # ★ s_orient gate on cond(J) — §4.12.3


@dataclass(frozen=True, slots=True)
class DeepConfig:
    max_candidates: int = 8                     # ★ CODE-ENFORCED cap (CPU-only reality)
    batch_size: int = 1
    coarse_level: int = 8                       # LoFTR 1/8 resolution stage
    max_side_px: int = 1024


@dataclass(frozen=True, slots=True)
class AsiftConfig:
    tilts: tuple[float, ...] = (1.0, 1.41, 2.0, 2.83, 4.0)
    phi_step_deg: float = 72.0
    base_extractor: str = "sift"


@dataclass(frozen=True, slots=True)
class AiEngineConfig:
    extractor: str = "sift"                     # ★ classical default (L1)
    matcher: str | None = "flann"               # ★ classical default (L1)
    detector_free: str | None = None            # None => no LoFTR
    segmenter: str = "classical"                # ★ classical default
    estimator_backend: str = "opencv"
        # ★ RENAMED from `estimator`. A COMPONENT REGISTRY KEY, and "opencv" is the only
        #   registered one. The ROBUST-FIT METHOD is `ransac.method` — a different concept
        #   with a different vocabulary. Conflating them was a boot crash on zero env (§4.7).
    scorer: str = "composite"
    suggester: str = "classical_suggester"      # ★ NEW — §4.23
    strict_models: bool = False
    weights_dir: Path | None = None
    device: Device = Device.AUTO                # -> CPU on the verified box
    max_features: int = 8000
    clahe_enabled: bool = True
    ratio_test: float = 0.75
    cross_check: bool = True
    min_matches: int = 10
    ransac: RansacConfig = field(default_factory=RansacConfig)
        # ★ ransac.method is the HomographyMethod. LE_AI_RANSAC_METHOD sets it.
    degeneracy: DegeneracyConfig = field(default_factory=DegeneracyConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    deep: DeepConfig = field(default_factory=DeepConfig)
    asift: AsiftConfig = field(default_factory=AsiftConfig)
    semantics_enabled: bool = False
    calibration_id: str = "identity"
    job_seed: int = 42                          # -> deterministic RANSAC
    min_confidence: float = 40.0                # 0..100
    rank_margin: float = 10.0                   # 0..100; below => status="advisory"
    max_results: int = 5

    def validate(self) -> None:
        """Raise ConfigurationError on:
             * any scoring weight <= 0, or all four == 0
             * min_confidence outside [0, 100]; rank_margin outside [0, 100]
             * deep.max_candidates outside [1, 32]
             * matcher is None AND detector_free is None (no correspondence source)
             * estimator_backend not a registered ESTIMATOR name

        WARN (never raise) on:
             * ransac.method == LMEDS — its 50% breakdown point disqualifies it for our
               ~80%-outlier regime (§13.2), but it stays selectable for comparison runs.

        ★ TWO v1.0 clauses are DELETED:
          - "deep.max_candidates > tiles budget" — AiEngineConfig HAS no tiles-budget field.
            LE_MAX_TILES_PER_JOB is consumed by gis.candidates.budget, and ai_engine may not
            import gis. The check belongs there and only there.
          - "lmeds selected (warn+allow)" listed under "Raise ConfigurationError on:" —
            self-contradictory as written. It warns. It does not raise.
        """
```

> **`deep.max_candidates = 8` is CODE-ENFORCED, not advisory.** `torch.cuda.is_available()` is False here; LoFTR/SAM are 2–8 s per 1024² image on CPU. Deep matching runs at stage C (final refinement of the top candidates) only. The classical path is not merely the fallback — **on this hardware it is the faster configuration** (~3.2 s cold, ~1.0 s warm vs +16–40 s deep).

### 4.16 `gis.types` and `gis.imagery.base`

```python
# gis/src/gis/types.py
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True, slots=True)
class TileRef:
    z: int
    x: int
    y: int                 # ★ slippy/XYZ convention: y=0 at NORTH. (TMS flips this — do not.)

    def quadkey(self) -> str: ...                                  # Bing; bit-interleave
    def parent(self) -> "TileRef": ...
    def children(self) -> tuple["TileRef", "TileRef", "TileRef", "TileRef"]: ...


@dataclass(frozen=True, slots=True)
class LonLat:
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class BBox:
    """★ ALWAYS EPSG:4326, ALWAYS (west, south, east, north), ALWAYS degrees."""
    west: float
    south: float
    east: float
    north: float

    def center(self) -> tuple[float, float]: ...          # (lon, lat)
    def contains(self, lon: float, lat: float) -> bool: ...
    def buffered_m(self, meters: float) -> "BBox": ...
    def area_m2(self) -> float: ...                       # equal-area approx, for budget checks


@dataclass(frozen=True, slots=True)
class TileRange:
    z: int
    min_x: int
    min_y: int
    max_x: int
    max_y: int            # inclusive

    def __len__(self) -> int: ...
    def __iter__(self) -> "Iterator[TileRef]": ...


@dataclass(frozen=True, slots=True)
class ZoomDecision:
    zoom: int
    achieved_mpp: float
    requested_mpp: float
    clamped: bool         # ★ load-bearing: True => the provider cannot serve the requested
                          #   resolution and we are about to match against upsampled mush


class BasemapKind(StrEnum):
    """★ NEW. The mandated "2D map with satellite/hybrid/terrain" existed ONLY as frontend
    state with no data path: 50-frontend defined BasemapKind, mapStore held it,
    BasemapSwitcher rendered it, and it "shows only the kinds the active provider supports"
    — but NO `kinds` field existed server-side, get_tile took no layer argument, endpoint 52
    had no kind param, and TileCacheKey.variant is scoped to imagery DATE. Flipping the
    switcher could only ever re-render identical tiles."""
    SATELLITE = "satellite"
    HYBRID    = "hybrid"      # imagery + labels/boundaries reference overlay, composited server-side
    TERRAIN   = "terrain"


@dataclass(frozen=True, slots=True)
class SatelliteChip:
    """The provider's output. `attribution` is REQUIRED, not optional — it makes the
    licence obligation unforgeable rather than reviewer-dependent."""
    image: np.ndarray                  # (H,W,3) uint8, RGB, C-contiguous
    geotransform: tuple[float, float, float, float, float, float]   # GDAL order
    crs: str                           # authority string of `geotransform` — see native_crs below
    provider_name: str                 # provenance only, NEVER control flow
    attribution: str                   # ★ MUST travel with the pixels
    terms_url: str                     # ★ likewise — travels to CandidateWindow and ExportContext
    zoom: int | None
    captured_at: datetime | None
    gsd_m: float                       # ★ TRUE ground metres per pixel at chip centre, cos(phi)-corrected
    georef_ce90_m: float               # ★ the provider's own absolute georeferencing error
    is_authoritative: bool             # True => survey-grade georeferencing
    kind: BasemapKind = BasemapKind.SATELLITE
    placeholder_fraction: float = 0.0
    bands: tuple[str, ...] = ("R", "G", "B")
    extra_bands: Mapping[str, np.ndarray] | None = None   # ★ (H,W) float32 per non-RGB band
```

`geotransform` is the **GDAL 6-tuple** `(origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)`, `pixel_height` negative for north-up rasters. **This is the interchange format for the whole system.** Chosen over rasterio's `Affine` because GDAL is installed and rasterio is not; `Affine` is derivable in one line where wanted.

```python
# gis/src/gis/imagery/base.py
import abc
from dataclasses import dataclass

import numpy as np

from gis.types import BBox, SatelliteChip


PROVIDER_NAMES: Final[tuple[str, ...]] = (
    "esri_world_imagery", "local_orthophoto", "fixture",
    "mapbox_satellite", "bing_aerial", "sentinel_copernicus", "google_maps_static",
)
"""★ THE CANONICAL PROVIDER NAME TUPLE, owned by the layer that owns providers.

v1.0 said `ImageryProvider.name` "MUST be a member of the `imagery_provider` PG enum" and
§13.1 IU-11 mandated a test asserting exactly that — but §10.2 and the `gis-purity`
import-linter contract FORBID gis from importing sqlalchemy or app, so
gis/tests/test_providers_contract.py could not see models.enums.ImageryProvider. The
constraint was unenforceable from the package required to satisfy it.

Now: gis tests against PROVIDER_NAMES, and a BACKEND test asserts
`set(PROVIDER_NAMES) == {e.value for e in models.enums.ImageryProvider}`. The backend may
import gis; gis may not import the backend. The dependency points the way it already points.
"""


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_tiles: bool               # get_tile() is meaningful
    supports_static_bbox: bool         # get_static_bbox() is native, not stitched
    supports_offline: bool             # works with the NIC unplugged
    native_crs: str
        # ★ The authority string of the geotransform this provider returns. "EPSG:3857" for
        #   every slippy provider; PER-FILE (typically a UTM zone) for local_orthophoto.
        #   IT IS NOT FIXED, and match_results.sat_geotransform_srid exists because of that
        #   — see §5.6. v1.0 hardcoded 3857 in the DDL comment, the §6.1 wire table and the
        #   §5.8 chain while simultaneously documenting native_crs as per-file, which made
        #   the contract's own HIGHEST-ACCURACY provider unstorable.
    kinds: tuple[BasemapKind, ...] = (BasemapKind.SATELLITE,)
        # ★ NEW. What the UI's BasemapSwitcher may offer. Surfaced on ProviderInfo.
        #   ★ MATCHING ALWAYS USES kind=SATELLITE, normatively — so this cannot touch the
        #     algorithm (invariant I4). Labels and hillshade are for human eyes only; feeding
        #     a label-burned tile to SIFT would be a genuine accuracy regression.
    tile_size_px: int                  # 256 or 512
    typical_gsd_m: float | None        # best-case GSD at max_zoom, metres
    georef_ce90_m: float               # ★ absolute georeferencing error, CE90 metres
    imagery_date_known: bool           # ★ gates whether SatelliteChip.captured_at is meaningful
    rate_limit_rps: float | None
    requires_attribution: bool
    allows_caching: bool               # ★ per provider TERMS — gates DiskTileCache/RedisTileCache
    allows_derivative_export: bool     # ★ may a rendered chip go into a PDF deliverable?
    max_static_px: tuple[int, int] | None
    supports_multispectral: bool = False
    bands: tuple[str, ...] = ("R", "G", "B")


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    status: str            # "up" | "degraded" | "down"
    configured: bool
    latency_ms: float | None
    message: str | None
    checked_at: float


class ImageryProvider(abc.ABC):
    """One satellite imagery source, normalised to pixels + geotransform.

    Contract for implementors:
      - __init__ MUST NOT perform network I/O and MUST NOT raise on missing credentials.
        Construction ALWAYS succeeds; is_configured() reports readiness. (L11)
      - get_tile / get_static_bbox raise ProviderError subclasses, NEVER bare
        httpx/rasterio/GDAL exceptions. The matcher must not learn our stack.
      - All returned pixels are RGB uint8. No BGR, no alpha, no float.
      - Thread-safe: Celery calls these from a worker pool.
    """

    # ---- identity & static metadata (properties, NO I/O) --------------------
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable registry key. MUST be a member of `gis.imagery.base.PROVIDER_NAMES`,
        which a BACKEND test pins to the `imagery_provider` PG enum (§5.3)."""

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool: ...

    @property
    @abc.abstractmethod
    def min_zoom(self) -> int: ...

    @property
    @abc.abstractmethod
    def max_zoom(self) -> int:
        """Max zoom the provider SERVES. NOT the max zoom with real detail — several
        providers overzoom. See capabilities().typical_gsd_m."""

    @property
    @abc.abstractmethod
    def attribution(self) -> str:
        """Plain-text credit. MUST be rendered wherever pixels are shown."""

    @property
    @abc.abstractmethod
    def terms_url(self) -> str:
        """Canonical ToS URL. Surfaced in UI and PDF exports."""

    # ---- capability & readiness --------------------------------------------
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True if this provider can serve RIGHT NOW (creds present, paths exist).
        PURE LOCAL CHECK. No network. NEVER raises."""

    @abc.abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    # ---- imagery access ----------------------------------------------------
    @abc.abstractmethod
    def get_tile(self, z: int, x: int, y: int, *,
                 kind: BasemapKind = BasemapKind.SATELLITE) -> np.ndarray:
        """Single tile, XYZ scheme (origin NW, y increasing south).
        Returns (S,S,3) uint8 RGB. ★ Decoding is the PROVIDER's job so callers never
        branch on JPEG-vs-PNG-vs-WebP.

        `kind` MUST be in capabilities().kinds, else TileOutOfRangeError. Providers that
        declare only SATELLITE may ignore it. Matching never passes anything else.

        Raises:
            TileOutOfRangeError    z outside [min_zoom, max_zoom], or x/y outside 2^z
            TileNotAvailableError  provider has no imagery here (ocean, gap, cloud)
            ProviderNotConfiguredError
            ProviderRateLimitError (retryable; carries retry_after)
            ProviderTransportError (retryable)
        """

    @abc.abstractmethod
    def get_static_bbox(self, bbox: BBox, zoom: int, *,
                        kind: BasemapKind = BasemapKind.SATELLITE) -> SatelliteChip:
        """Contiguous imagery covering bbox at `zoom`, as one chip.

        Default implementation in `TileProviderMixin` (`gis/imagery/base.py`, IU-11 —
        v1.0 named this class here and put it in NO tree): enumerate covering tiles, fetch
        concurrently, stitch, crop to bbox, compute geotransform, set attribution/terms_url/
        captured_at. Providers with a native bbox endpoint (Google Static, local ortho)
        override and skip stitching.

        ★ The returned chip's geotransform is EXACT for the returned pixels — crop
          offsets are FOLDED INTO THE ORIGIN, never approximated.

        Raises: as get_tile, plus AreaTooLargeError.
        """

    # ---- non-abstract shared behaviour -------------------------------------
    def get_tile_bytes(self, z: int, x: int, y: int) -> tuple[bytes, str]:
        """Raw encoded tile + MIME, for pass-through proxying. Default impl re-encodes
        get_tile() as PNG; network providers override to avoid the decode/encode round trip.
        ★ Exactly ONE legitimate caller: the tile proxy (endpoint 52)."""

    def tile_url(self, z: int, x: int, y: int, *,
                 kind: BasemapKind = BasemapKind.SATELLITE) -> str:
        """Resolved UPSTREAM URL. Network providers override. Used for cache keys, debugging,
        and — for keyless providers with LE_IMAGERY_DIRECT_TILE_URLS=true only — the
        frontend's direct-to-provider tile layer (§7.2)."""
        raise NotImplementedError

    def health(self) -> ProviderHealth:
        """Cheap liveness probe. MAY do one network call. ★ NEVER raises — returns a status.
        ★ The result is CACHED for 30 s by imagery_service and endpoint 51 serves the cache;
        it is not a per-request round trip (§7.2)."""
```

> **★ These methods are synchronous BY DESIGN — and that is exactly why the four `/imagery` routes need a rule.** §4.16 states *"Thread-safe: Celery calls these from a worker pool"*, and endpoints 50–53 then expose them over FastAPI. **Normative (also stated at §7.2):** endpoints 51/52/53 are declared **`def`, not `async def`**, so Starlette runs them in the threadpool. A synchronous `httpx` call, a 64-megapixel NumPy stitch, or a PNG encode inside an `async def` blocks the event loop for the entire worker — **taking `/health` down with it.** L5's parenthetical is amended: *"Tile proxying is IO and is exempt; it must still run off the event loop."*

> **Two deviations from the naive signature, both deliberate.**
> **`get_tile` returns `np.ndarray`, not `bytes | np.ndarray`.** The union forces every call site to type-test and decode — reintroducing exactly the provider-specific branching the ABC exists to remove. Raw bytes have one legitimate caller, so that caller got its own method. Two needs, two methods, no union.
> **`get_static_bbox` returns `SatelliteChip`, not `(ndarray, geotransform)`.** A bare tuple lets pixels travel without their attribution, which is a licence condition. Making `attribution` a required field means the obligation is unforgeable.

### 4.17 `gis.errors`

```python
# gis/src/gis/errors.py

class GisError(Exception): ...


class ProviderError(GisError):
    provider: str
    retryable: bool = False


class UnknownProviderError(ProviderError): ...            # typo'd config — fail loud
class ProviderNotConfiguredError(ProviderError): ...      # missing key/path
class ProviderDisabledError(ProviderError): ...           # not in LE_ALLOWED_PROVIDERS
class TileOutOfRangeError(ProviderError): ...             # caller bug — NEVER retry
class TileNotAvailableError(ProviderError): ...           # legitimate 404 — cache the NEGATIVE
class AreaTooLargeError(ProviderError): ...               # budget guard
class RasterBackendUnavailable(ProviderError): ...        # no rasterio AND no GDAL


class ProviderRateLimitError(ProviderError):
    retryable = True
    retry_after: float | None


class ProviderTransportError(ProviderError):
    retryable = True


class OutOfCoverage(GisError): ...          # provider has no imagery for the AOI at all
class SearchHintRequired(GisError): ...     # no AOI resolvable
class ExportError(GisError): ...
class CrsError(GisError): ...
```

> **`TileNotAvailableError` vs `ProviderTransportError` is the distinction that matters operationally.** A 404 over open ocean is a **permanent** answer worth caching as a negative; a 503 is transient and must be retried with backoff. Collapsing them means either hammering a provider for tiles that will never exist, or permanently caching a blank tile because of one bad minute.

### 4.18 `gis.tiles` — pure math, numpy + stdlib only

```python
# gis/src/gis/tiles.py
# ★ NO I/O. NO optional deps. NO pyproj. The foundation — everything depends on it.

import numpy as np

from gis.types import BBox, TileRange, TileRef, ZoomDecision

# --- Constants (VERIFIED numerically) ---------------------------------------
EARTH_RADIUS_M: float = 6378137.0
EARTH_CIRCUMFERENCE_M: float = 40075016.685578488          # 2*pi*R
ORIGIN_SHIFT_M: float = 20037508.342789244                 # EARTH_CIRCUMFERENCE_M / 2
MAX_LATITUDE: float = 85.0511287798066                     # atan(sinh(pi)) in degrees
RESOLUTION_Z0_256: float = 156543.03392804097              # 2*pi*R / 256


def lonlat_to_tile(lon: float, lat: float, z: int) -> TileRef: ...
def lonlat_to_tile_fractional(lon: float, lat: float, z: int) -> tuple[float, float]: ...
def tile_to_lonlat(z: int, x: int, y: int) -> tuple[float, float]: ...          # NW corner
def tile_to_lonlat_center(z: int, x: int, y: int) -> tuple[float, float]: ...

def lonlat_to_meters(lon: float, lat: float) -> tuple[float, float]: ...        # 4326 -> 3857
def meters_to_lonlat(mx: float, my: float) -> tuple[float, float]: ...          # 3857 -> 4326
def lonlat_to_meters_array(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...
def meters_to_lonlat_array(mx: np.ndarray, my: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...

def resolution_at(z: int, lat: float, tile_size: int = 256) -> float:
    """metres per pixel, cos(phi)-corrected.
        res = (EARTH_CIRCUMFERENCE_M / tile_size) * cos(radians(lat)) / 2**z
    """

def zoom_for_resolution(target_mpp: float, lat: float, tile_size: int = 256,
                        *, round_mode: str = "up") -> int:
    """★ THE EXACT INVERSE of resolution_at, tile_size and all:
           z = log2( (EARTH_CIRCUMFERENCE_M / tile_size) * cos(radians(lat)) / target_mpp )
       then apply round_mode and clamp to [0, 24].

    ★ v1.0 specified `z = log2(156543.033928041 * cos(lat) / target_mpp)` — the S=256
      constant HARDCODED — while taking `tile_size` as a parameter it never used. Its own
      sibling resolution_at got it right. For S=512 the correct solve is exactly ONE LOWER,
      so the function returned z+1 for every 512px provider.

      This is not hypothetical: Mapbox ships `use_2x = True` BY DEFAULT ("a 512 px @2x tile
      is one request covering the same ground — strictly better economics"), so the
      documented default configuration of the best keyed provider hit it. Consequences, all
      silent: 4x the tile count (quadratic in 2**z) against the MAX_TILES budgets; a spurious
      AreaTooLargeError on AOIs that fit; and z pushed past max_zoom so ZoomDecision.clamped —
      the flag §4.18 calls "load-bearing" and "how the caller learns it is about to match
      against upsampled mush" — CRIES WOLF on a provider that could have served the request.
      30-ai-pipeline §7.3 diagnoses this exact bug class one document away: "the code must
      read S from ProviderCapabilities.tile_size, never hardcode 256. A hardcoded 256 against
      a 512 provider yields a 2x error... a silent, plausible, doubly-dangerous bug."

    IU-09 pins it with the round-trip property (for all z, lat, S in {256, 512}:
    zoom_for_resolution(resolution_at(z,lat,S), lat, S, round_mode="nearest") == z), which
    makes the hardcode UNREACHABLE, plus the goldens
    zoom_for_resolution(0.5, 45.0, 512) == 17 vs zoom_for_resolution(0.5, 45.0, 256) == 18.
    """

def choose_zoom(min_zoom: int, max_zoom: int, target_mpp: float, lat: float,
                tile_size: int = 256) -> ZoomDecision:
    """★ THE ONE canonical signature — it carries tile_size and threads it through.
    40-imagery's provider-taking variant `choose_zoom(provider, target_mpp, lat)` is VOID;
    callers read `provider.capabilities().tile_size_px` and call this.

    ★ .clamped is load-bearing — it is how the caller learns it is about to match
    against upsampled mush."""

def tile_bbox_lonlat(z: int, x: int, y: int) -> BBox: ...
def tile_bbox_meters(z: int, x: int, y: int) -> tuple[float, float, float, float]: ...
def bbox_to_tile_range(bbox: BBox, z: int) -> TileRange: ...
def tile_range_count(rng: TileRange) -> int: ...

def tile_to_quadkey(z: int, x: int, y: int) -> str: ...       # Bing; bit-interleave
def quadkey_to_tile(quadkey: str) -> TileRef: ...

def stitch_tiles(
    tiles: "Mapping[TileRef, np.ndarray]",
    rng: TileRange,
    tile_size: int = 256,
    *,
    missing_fill: tuple[int, int, int] = (0, 0, 0),
) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
    """-> (mosaic (H,W,3) uint8, geotransform in EPSG:3857)."""

def crop_to_bbox(
    mosaic: np.ndarray,
    gt: tuple[float, float, float, float, float, float],
    bbox: BBox,
) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
    """★ Returns the array AND the UPDATED geotransform from ONE function. Cropping
    without folding the offset into the origin is the defect that produces coordinates
    wrong by up to one tile (~108 m at z18, 45°N) while crashing nothing."""

def pixel_to_lonlat(gt, crs: str, col: float, row: float) -> tuple[float, float]:
    """★ PIXEL-CENTRE convention, normatively (§6.1's coordinate table is the master):
           X = gt[0] + (col + 0.5)*gt[1] + (row + 0.5)*gt[2]
           Y = gt[3] + (col + 0.5)*gt[4] + (row + 0.5)*gt[5]
       then project to lon/lat.

    The +0.5 is NOT pedantry: omitting it biases EVERY GCP by half a pixel, consistently in
    one direction — ~0.21 m at z18/45 deg N. That is a SYSTEMATIC BIAS, not noise, and it
    does not average out.
    """

def lonlat_to_pixel(gt, crs: str, lon: float, lat: float) -> tuple[float, float]:
    """★ THE EXACT INVERSE of pixel_to_lonlat, INCLUDING the -0.5. Returns pixel CENTRES.
    Asserted by IU-09 to 1e-9 px round-trip — which is what makes the two GCP-adjust chains
    of §7 agree."""

def geotransform_to_affine(gt) -> tuple[float, ...]: ...

def invert_geotransform(gt) -> tuple[float, ...]:
    """★ The plain affine inverse — EDGE convention, no half-pixel. For internal geometry
    only. NEVER use it for GCP work: use lonlat_to_pixel(), which is the true inverse."""
```

> **★ Three documents held three different conventions for the same conversion, and the disagreement reached the API.** 40-imagery §4.6 used pixel **centres** and argued for them; CONTRACT §4.18 echoed *"+0.5 pixel-CENTRE convention"*; but **CONTRACT §5.8 — the canonical pipeline, the chain literally serialised to clients in `transform_note` — omitted the +0.5** (`X = c + a·u + b·v`); and 40-imagery §4.7 asserted a test invariant, *"`pixel_to_lonlat(gt, 0, 0)` equals the NW tile corner"*, **which is FALSE under the +0.5 convention** and, being written to pass, would have forced the +0.5 back out of the code. Compounding it: `lonlat_to_pixel` was specified as *"inverse via the affine inverse"* and `invert_geotransform` returns the plain affine inverse — **neither subtracts 0.5, so `lonlat_to_pixel` was not the inverse of `pixel_to_lonlat`.**
>
> That lands squarely in §7's GCP-adjust endpoint, which forward-projects `satellite_px`, compares to the given `lat/lon`, and **422s beyond `LE_GCP_CONSISTENCY_TOLERANCE_M` (0.5 m)**. A half-pixel round-trip inconsistency is ~0.21 m at z18 and ~0.42 m at z17 — the latter **spuriously rejects a correct edit**, and it would present as an intermittent, zoom-dependent, irreproducible bug.
>
> **Rulings:** (a) §6.1's coordinate table states the convention **once**, normatively; (b) §5.8's chain and its `transform_note` string now carry the `+0.5`; (c) 40-imagery §4.7's NW-corner invariant is **VOID**, replaced by `pixel_to_lonlat(gt, -0.5, -0.5) == tile_to_lonlat(z, x_min, y_min)`; (d) IU-09 asserts the round-trip to 1e-9 px.

> **4326↔3857 is closed-form NumPy with no pyproj.** It is the only transform on the hot path, it is four lines of arithmetic, and pyproj is not installed. `gis/crs.py` remains the only module permitted to import pyproj, for everything else (UTM, GeoTIFF native CRS, export reprojection).

### 4.19 `gis.candidates` — the seam implementation

```python
# gis/src/gis/candidates/hint.py
from dataclasses import dataclass

from gis.types import BBox, LonLat


@dataclass(frozen=True, slots=True)
class SearchHint:
    """★ A hint is a HARD INPUT REQUIREMENT, not an optimisation.

    Hintless global search is ARITHMETICALLY IMPOSSIBLE: 2^18^2 ~= 6.87e10 tiles ~= 1 PB
    per photo, and the query is genuinely ambiguous anyway. This is designed into the UX
    as a blocking wizard step, not discovered at runtime."""
    aoi: BBox | None = None
    center: LonLat | None = None
    radius_m: float = 1000.0
    zoom_levels: tuple[int, ...] = (18,)
    use_image_gps: bool = True


def resolve_hint(
    hint: SearchHint,
    *,
    exif_gps: LonLat | None,
    geotiff_bounds: BBox | None,
    project_aoi: BBox | None,
    exif_hpe_m: float | None = None,
) -> BBox:
    """★ NORMATIVE precedence — first that yields a geometry wins:
      1. hint.aoi                         explicit polygon bbox (radius ignored)
      2. hint.center + radius_m           geodesic buffer
      3. use_image_gps and exif_gps       buffer by radius_m, inflated per EXIF HPE
      4. use_image_gps and geotiff_bounds the footprint (radius_m ignored)
      5. project_aoi
      6. -> raise SearchHintRequired      (API maps to 422 SEARCH_HINT_REQUIRED)
    """
```

```python
# gis/src/gis/candidates/source.py
from collections.abc import Iterator

from ai_engine.types import CandidateWindow, WindowRef      # ★ THE ONE PERMITTED CROSS-IMPORT
from gis.imagery.base import ImageryProvider
from gis.types import BBox


class TileWindowSource:
    """★ THE SEAM. Structurally satisfies ai_engine.types.WindowSource — it does NOT
    inherit from it. The Protocol import exists purely so mypy can verify conformance.

    This class is the ONLY place in the codebase where a provider, a tile pyramid, and
    the matching engine are in the same room. Everything above it sees windows;
    everything below it sees tiles."""

    name: str

    def __init__(
        self,
        provider: ImageryProvider,
        aoi: BBox,
        *,
        zoom_levels: "Sequence[int]",
        window_size_px: int = 1024,
        overlap_ratio: float = 0.5,        # ★ 0.5, NOT 0.25 — see GUARANTEED_FOOTPRINT_PX below
        max_windows: int = 25,
        target_gsd_m: float = 0.5,
    ) -> None: ...

    def __len__(self) -> int:
        """★ Total window count, known UP FRONT. plan_search() runs before any fetching,
        which is what makes progress reporting honest and the tile budget enforceable
        BEFORE a job is accepted."""

    def __iter__(self) -> Iterator[CandidateWindow]:
        """Lazily fetch, stitch, crop, and yield.

        Populates from provider.capabilities() and the chip: gsd_m (TRUE metres),
        georef_ce90_m, is_authoritative, placeholder_fraction, ★ attribution, ★ terms_url,
        ★ captured_at, ★ bands/extra_bands, and ★ meta{tile_z, tile_x, tile_y, mosaic_cols,
        mosaic_rows, zoom_clamped}.

        ★ MUST wrap gis.errors.ProviderError in ai_engine.errors.WindowFetchError before
          raising — see §4.10. TileNotAvailableError is NOT an error here: the window is
          skipped and placeholder_fraction accounts for it (§6.3).
        """
```

```python
# gis/src/gis/candidates/source.py  — module constant
GUARANTEED_FOOTPRINT_PX: Final[int] = 512
"""★ The contract the overlap ratio EXISTS to buy: any query footprint of this size or
smaller lies WHOLLY INSIDE at least one window.

    stride = window_size_px * (1 - overlap_ratio)
    slack  = window_size_px - stride  >=  GUARANTEED_FOOTPRINT_PX      # asserted at import

At window=1024, overlap=0.5: stride 512, slack 512. ✔
At window=1024, overlap=0.25: stride 768, slack 256. ✘ — only a 256px guarantee.

★ v1.0 shipped THREE values for one parameter: 30-ai-pipeline §12.1 and §5 step 11 said
  `overlap = 0.5` and reasoned from a 512px guarantee ("a 256px tile at z18 is ~120 m across
  — smaller than one field"); CONTRACT §4.19 said `overlap_ratio = 0.25`; 40-imagery §5.2
  said `overlap_frac = 0.25` with its own WEAKER guarantee (256px). The arithmetic was right
  in both docs — the GUARANTEES were different, and the DESIGN reasoned from the larger one
  while the CONTRACT shipped the smaller. Any footprint between 256 and 512 px could then
  straddle every window boundary and match nothing, and the failure is SILENT and
  LOCATION-DEPENDENT (it depends where the field falls against the tile grid) — presenting as
  an intermittent, irreproducible "no match" on a correct AOI.

  Ruling: the 512px guarantee is real and is what the design reasons from, so overlap_ratio
  is 0.5 everywhere (§4.19, §6.2 MatchOptions, §9.7 LE_SEARCH_OVERLAP_RATIO), and the tile
  budget is re-costed against it. The assertion above makes the constant and the guarantee
  unable to drift apart again.
"""

```python
# gis/src/gis/candidates/strategy.py
from dataclasses import dataclass

from gis.types import BBox, TileRange


@dataclass(frozen=True, slots=True)
class WindowPlan:
    zoom: int
    tile_range: TileRange
    bbox: BBox
    ordinal: int
    zoom_decision: ZoomDecision     # ★ carries .clamped through to CandidateWindow.meta


def plan_search(
    aoi: BBox,
    *,
    zoom_levels: "Sequence[int]",
    min_zoom: int,
    max_zoom: int,
    window_size_px: int,
    tile_size_px: int,
    overlap_ratio: float,
    max_windows: int,
) -> list[WindowPlan]:
    """★ FLAT ENUMERATION over aoi x zoom_levels with `overlap_ratio` stride, bounded by
    max_windows. Deterministic and fully known before any I/O.

    ★ ZOOM CLAMPING — normative, and undefined in v1.0:
        z_eff = clamp(z, min_zoom, max_zoom) for each requested z; dedupe; preserve order.
        Each resulting plan carries ZoomDecision(clamped = z_eff != z).
        NEVER returns an empty list for a non-empty zoom_levels, and NEVER raises on an
        out-of-range zoom — clamping is the provider's honest best effort, and the CALLER
        is told.

    ★ Why this mattered: LE_SENTINEL_MAX_ZOOM=15 and the provider "REFUSES zoom > 15"
      (correctly — Sentinel-2 is 10 m/px), while LE_SEARCH_DEFAULT_ZOOM=18,
      SearchHint.zoom_levels=(18,), projects.default_search_zoom=18 and
      match_jobs.search_zoom_levels default '{18}'. v1.0's plan_search took BOTH zoom_levels
      AND min_zoom/max_zoom and never specified their interaction — so
      LE_IMAGERY_PROVIDER=sentinel_copernicus with otherwise-default config either yielded
      ZERO windows (every job -> no_viable_candidate, INDISTINGUISHABLE from a genuine
      no-match) or silently clamped to z15 and matched against 10 m imagery while the job row
      recorded search_zoom_levels={18}. Both violate I4's promise that a provider swap changes
      data, not behaviour — and the silent-clamp branch is exactly what ZoomDecision.clamped
      was invented to prevent, yet NOTHING routed `clamped` anywhere.

    ★ THE LOOP IS NOW CLOSED, with §11.8's standard four-surface treatment:
        clamped plan -> CandidateWindow.meta["zoom_clamped"] = True
                     -> app.tasks.matching appends
                        WarningItem{code:"ZOOM_CLAMPED", requested:"18", effective:"15"}
                     -> match_jobs.degraded = true, degradation_reason set
                     -> match_results.quality_flags += "zoom_clamped"

    ★ Adaptive coarse-to-fine beam search is DEFERRED (§12 C-11): it requires ai_engine
      to score a window before gis decides where to descend, which inverts the layer
      dependency. `WindowSource` is exactly the seam where it would slot in later — as a
      source that consumes a scoring callback — without touching ai_engine's interfaces."""
```

### 4.20 `gis.accuracy` — where pixels become metres

```python
# gis/src/gis/accuracy.py
# ★ The module that must never see a degree or a 3857 metre.
#   ai_engine reports pixel covariance; THIS is where it becomes a survey claim.

from dataclasses import dataclass

import numpy as np


# ★ THE CONFIDENCE LEVEL IS CE90 AND ONLY CE90. Stated once, here, normatively.
CE90_FROM_SIGMA_2D: Final[float] = 2.1460   # 2-D circular 90% radius, in units of sigma
CE95_FROM_SIGMA_2D: Final[float] = 2.4477   # (not used; recorded so nobody re-derives 2.0)


@dataclass(frozen=True, slots=True)
class AccuracyEstimate:
    """★ THE SINGLE PRODUCER of the survey numbers. ai_engine reports pixel covariance
    (PixelAccuracy); THIS is where it becomes a claim about the world.

    ★ EVERY FIELD CARRIES CE90. There is no mixing of levels.
    """
    confidence_level: Literal["ce90"] = "ce90"
        # ★ Present so the number can NEVER be read at the wrong level.
    semi_major_ce90_m: float   # = CE90_FROM_SIGMA_2D * sqrt(lambda_max(Sigma_ground))
    semi_minor_ce90_m: float   # = CE90_FROM_SIGMA_2D * sqrt(lambda_min(Sigma_ground))
    azimuth_deg: float         # ★ major-axis bearing, 0=North, clockwise. From the
                               #   eigenvectors of Sigma_ground. THE ANISOTROPY IS KEPT.
    relative_ce90_m: float     # circularised: CE90_FROM_SIGMA_2D * sqrt(lambda_max)
    georef_ce90_m: float       # the provider's own error, CE90, straight from CandidateWindow
    total_ce90_m: float        # = sqrt(relative_ce90_m**2 + georef_ce90_m**2)
    dominant_term: Literal["match", "georeference", "landmark_click", "rectification"]


def pixel_cov_to_metres(
    cov_px: np.ndarray,        # (2,2) in WINDOW pixels
    gsd_m: float,              # ★ TRUE ground metres per pixel (CandidateWindow.gsd_m)
    *,
    gt: tuple[float, float, float, float, float, float] | None = None,
    lat: float | None = None,
) -> np.ndarray:
    """(2,2) covariance in TRUE metres.

    ★ PREFERRED AND DEFAULT PATH — no round trip, no sign to get backwards:

        Sigma_true = gsd_m**2 * cov_px

    ★ The geotransform path (gt + lat given, for rotated/skewed rasters) states the
      OPERATION, not just the factor:

        Sigma_proj = J_gt @ cov_px @ J_gt.T        # J_gt from gt; units: PROJECTED m/px
        Sigma_true = (cos(radians(lat))**2) * Sigma_proj    # for a Web-Mercator gt ONLY
                     ^^^^^^^^^^^^^^^^^^^^^ MULTIPLY BY cos^2. The projected metre is
                     INFLATED by 1/cos(phi), so the correction DIVIDES BY that factor.

    ★ v1.0's docstring read "via the geotransform Jacobian and the Mercator scale factor
      1/cos(phi)" — it NAMED the factor and never named the OPERATION. The naive reading
      (multiply by the quoted 1/cos(phi)) applies the correction BACKWARDS, inflating linear
      error by 1/cos^2(phi) — 3.04x at 55 deg N — and variance by 1/cos^4 (9.2x). BOTH
      directions are plausible: a true +/-0.3 m becomes +/-0.91 m (over-conservative, hides
      the product's real accuracy) or the reverse (over-confident, the dangerous one). There
      was no way to tell from the text which was meant. 30-ai §7.5 gets the equivalent right
      and unambiguously — `Sigma_ground = res(z,phi)**2 * Sigma_win` — precisely BECAUSE it
      works from a true-metre resolution rather than from the geotransform. Hence the
      preferred path above.

    IU-09 pins the direction with a golden: cov_px = I2 at z=18, lat=55 must give
    sqrt(lambda_max(Sigma_true)) == resolution_at(18, 55.0) == 0.34251936163340246 —
    a test that fails under EITHER wrong sign.
    """


def combine_accuracy(
    cov_px: np.ndarray,           # (2,2) WINDOW pixels — from PixelAccuracy.cov_px
    gsd_m: float,
    georef_ce90_m: float,
    click_sigma_px: float,
    *,
    gt=None, lat: float | None = None,
) -> AccuracyEstimate:
    """★ THE ONLY producer of AccuracyEstimate. ai_engine does not compute metres; gis does.

    ★ v1.0 defined the product's HEADLINE ACCURACY NUMBER two different ways, differing by
      a FACTOR OF 2, in two normative documents:
        30-ai §7.6 : relative_accuracy_m = 2 * res(z,phi) * sqrt(lambda_max)   # "~95%"
        CONTRACT   : relative_m = "our fit to the provider's pixels, 1-sigma"
      Same field name, same role, half the value. A surveyor reading "+/-0.3 m" could not
      know whether it meant 68%, 86.5%, or the 95% it was labelled.

      Three further errors compounded it:
        (a) "~95%" was WRONG: 2-sigma on the semi-major of a 2-D error ellipse is ~86.5%.
            The 2-D 95% radius is 2.448 sigma; the 2-D 90% radius is 2.146 sigma.
        (b) 30-ai then combined a 2-sigma ellipse semi-major with a CE90 (a 2-D CIRCULAR
            radius at 90%) IN QUADRATURE — mixing two confidence levels and a 1-D-with-2-D
            quantity, yielding a number at no stated confidence level at all.
        (c) The two AccuracyEstimate dataclasses did not even agree on FIELDS: 30-ai had the
            ellipse (semi_major/semi_minor/azimuth); CONTRACT dropped it entirely — throwing
            away what §7.5 calls "the most actionable part of the estimate" ("an oblique
            solve's error is strongly anisotropic; collapsing it to one number throws away
            the most actionable part").

      RULING: CE90 throughout — georef_ce90_m already forces that level, so everything else
      meets it there. total_ce90_m is now a LEGITIMATE quadrature of two same-level
      quantities. The ellipse is restored. confidence_level makes the level unforgeable.
      30-ai's competing dataclass is VOID under the same precedent as C-09.
    """


def rmse_px_to_ce90_m(rmse_px: float, gsd_m: float) -> float:
    """= CE90_FROM_SIGMA_2D * rmse_px * gsd_m."""
```

### 4.21 `gis.exports`

```python
# gis/src/gis/exports/models.py
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GcpRecord:
    """★ The export-layer DTO. NOT the ORM row. NOT the pydantic schema.
    Writers never touch the DB — this is assembled once by backend.services.export_service."""
    gcp_id: str
    code: str | None
    label: str | None
    lon: float
    lat: float
    elevation_m: float | None
    pixel_col: float
    pixel_row: float
    satellite_pixel_x: float
    satellite_pixel_y: float
    confidence: float                # 0..100
    horizontal_accuracy_m: float | None    # ★ == total_ce90_m. See §5.6 — one number, one name.
    total_ce90_m: float
    relative_ce90_m: float
    georef_ce90_m: float
    accuracy_dominant_term: str
    residual_px: float | None
    manually_adjusted: bool
    adjustment_offset_m: float | None
    landmark_kind: str | None
    elevation_source: str | None     # ★ 'srtm'|'copernicus_dem'|'local_dem'|'exif'|'manual'|None
```

```python
# gis/src/gis/exports/base.py
import abc
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np

from gis.exports.models import GcpRecord
from gis.types import SatelliteChip


@dataclass(frozen=True, slots=True)
class ExportContext:
    """Everything a writer needs. Assembled ONCE; writers never touch the DB or the
    network — which makes every writer trivially unit-testable offline."""
    export_id: uuid.UUID
    job_id: uuid.UUID | None
    project_name: str
    image_filename: str | None
    gcps: list[GcpRecord]
    chip: SatelliteChip | None         # ★ None when allows_derivative_export=False
    provider_name: str
    attribution: str
    terms_url: str
    imagery_captured_at: datetime | None
    retrieved_at: datetime
    method: Literal["direct_georeference", "assisted", "matched"]
    homography: np.ndarray | None
    rmse_m: float | None
    georef_ce90_m: float | None
    target_srid: int = 4326
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    software_version: str = ""


@dataclass(frozen=True, slots=True)
class ExportBundle:
    path: Path
    media_type: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    warnings: list[str]     # ★ e.g. truncated field names, omitted imagery. NOT decoration:
                            #   when Shapefile truncates `confidence_score` -> `confidenc`,
                            #   the user must be TOLD, not left to discover it in their GIS.


class ExportWriter(abc.ABC):
    format_id: str          # "csv" | "geojson" | "shapefile" | "kml" | "kmz" | "pdf" | "gpkg" | "dxf"
    media_type: str
    file_extension: str

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str | None]:
        """(available, reason_if_not). ★ Optional deps are REPORTED, never raised.
        GET /capabilities returns this so the UI greys out Shapefile with 'requires fiona'
        instead of offering a 500."""

    @abc.abstractmethod
    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle: ...
```

```python
# gis/src/gis/exports/base.py    (the type v1.0 returned and never defined)

@dataclass(frozen=True, slots=True)
class ExportFormatInfo:
    """★ The return element of available_formats(). Feeds GET /capabilities' export list
    and ExportCapability on the wire."""
    format_id: str
    label: str                  # "ESRI Shapefile"
    media_type: str
    file_extension: str
    available: bool
    reason: str | None          # "requires fiona" — the tooltip the UI greys the option with
    is_stdlib_only: bool        # True => can NEVER degrade (csv/geojson/kml/kmz)
    supports_target_srid: bool
    supports_imagery: bool      # PDF embeds a map figure; CSV does not


# gis/src/gis/exports/__init__.py
EXPORT_WRITERS: dict[str, Callable[[], ExportWriter]]   # ★ THE registry lives here (§9.9)

def get_writer(format_id: str) -> ExportWriter: ...
def available_formats() -> list[ExportFormatInfo]: ...
```

| format_id | class | file | dependency | degrades? |
|---|---|---|---|---|
| `csv` | `CsvExportWriter` | `csv_writer.py` | **stdlib** | never |
| `geojson` | `GeoJsonExportWriter` | `geojson_writer.py` | **stdlib** | never |
| `kml` | `KmlExportWriter` | `kml_writer.py` | **stdlib** | never |
| `kmz` | **`KmzExportWriter(KmlExportWriter)`** | `kml_writer.py` | **stdlib** | never |
| `shapefile` | `ShapefileExportWriter` | `shapefile_writer.py` | geopandas/fiona | yes |
| `gpkg` | `GpkgExportWriter` | `gpkg_writer.py` | geopandas/fiona | yes |
| `dxf` | `DxfExportWriter` | `dxf_writer.py` | ezdxf | yes |
| `pdf` | `PdfReportWriter` | `pdf_writer.py` | reportlab | yes |

> **★ `kmz` gets its own class.** v1.0 mapped **both** `kml` and `kmz` to `KmlExportWriter`, while `ExportWriter.format_id` is a **single class attribute** and `get_writer(format_id)` is keyed on it — **one class cannot register under two ids.** `KmzExportWriter` subclasses `KmlExportWriter` and overrides `format_id`/`media_type`/`file_extension` plus a zip step. Two ids, two classes, one registry key each.

> **CSV/GeoJSON/KML/KMZ are stdlib-only BY DESIGN**, so the surveyor can always get coordinates out regardless of environment. Only Shapefile, GeoPackage, DXF and PDF can degrade — and each binds its dependency **at call time** (§11.3), so `is_available()` answers rather than crashing.

**CSV column order is normative:**

```
gcp_id, code, label, longitude, latitude, elevation_m, elevation_source,
pixel_col, pixel_row, confidence, horizontal_accuracy_m, total_ce90_m,
relative_ce90_m, georef_ce90_m, accuracy_dominant_term, residual_px,
manually_adjusted, method, rmse_m, provider, attribution, imagery_captured_at,
generated_at, crs
```

UTF-8 **with BOM** (`utf-8-sig`); **longitude before latitude**; provenance as leading `# ` comment lines; lon/lat at 8 dp. `attribution` is a column, not just a comment — several providers' terms require it on derived output, and a comment line is the first thing a spreadsheet import drops.

### 4.22 `app.services._adapters` — the boundary adapters

**Six names exist twice or three times, with incompatible fields, and `app.schemas` may not import `gis`. Somebody must convert. v1.0 assigned nobody.**

| Wire type (`app.schemas`) | Domain type (`gis`) | Adapter (`app/services/_adapters.py`, IU-19) |
|---|---|---|
| `schemas.matching.SearchHint`<br>`aoi: GeoJsonPolygon\|None, center: LatLon\|None, zoom_levels: list[int]\|None` | `gis.candidates.hint.SearchHint`<br>`aoi: BBox\|None, center: LonLat\|None, zoom_levels: tuple[int,...]` | `to_gis_hint(h, *, project_aoi) -> gis…SearchHint` |
| `schemas.common.BBox`<br>`min_lon/min_lat/max_lon/max_lat` | `gis.types.BBox`<br>`west/south/east/north` | `to_gis_bbox(b)` · `to_wire_bbox(b)` |
| `schemas.common.LatLon` (`lat`, `lon`) | `gis.types.LonLat` (`lon`, `lat`) | `to_lonlat(p)` · `to_latlon(p)` — ★ note the **field order flip**, which is exactly why this is a named function and not an inline `**dict` |
| `schemas.imagery.ProviderCapabilities` | `gis.imagery.base.ProviderCapabilities` | `to_provider_capabilities(c)` |
| `schemas.imagery.ProviderHealth` | `gis.imagery.base.ProviderHealth` | `to_provider_health(h)` |
| `schemas.pose.CameraIntrinsics` | `ai_engine.types.geometry.CameraIntrinsics` | `to_engine_intrinsics(k)` · `to_wire_intrinsics(k)` |
| — | `gis.imagery.base.ProviderCapabilities` + health + name | `to_provider_info(p) -> schemas.imagery.ProviderInfo` |

> **Why an adapter module rather than renaming the wire types.** Renaming (`WireSearchHint`, `WireBBox`) was the alternative and it is defensible — a reviewer could then never confuse them. It loses because these names appear in the **OpenAPI schema**, hence in the generated TS, hence in every frontend import: `WireBBox` would leak an internal concern into the client's vocabulary permanently. **The conversion is real work either way; making it a named function in one module means it is reviewable, testable, and greppable.** `_adapters.py` is the only module in `app.services` permitted to import `gis.types` and `ai_engine.types` for this purpose, and IU-19 tests each adapter round-trips.

### 4.23 `ai_engine.landmarks.suggest` — automatic landmark suggestions

**The entire suggestion vertical existed except the algorithm.** v1.0 shipped endpoints 43/44/45, `job_type='suggest_landmarks'`, the `aux_jobs` CHECK, the `landmark_suggestions` table, `suggestion_status`, `suggestion_service.py`, `tasks/segmentation.py::suggest_landmarks_task`, `schemas/suggestion.py`, `SuggestionStrategy` and `useSuggestions.ts` — while `ai_engine` had **no suggester module** (`landmarks/priors.py` returns a sampling density map for *matching*, not ranked proposals), 30-ai-pipeline contained **zero** occurrences of "suggest" or "saliency", `ComponentKind` had no `SUGGESTER` member, and §4.13 declared `run_match_job` *"THE ONLY PUBLIC ENTRY POINT of ai_engine"*. **`suggest_landmarks_task` had nothing to call.**

```python
# ai_engine/src/ai_engine/landmarks/suggest.py     ★ IU-06
from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np

from ai_engine.types import (
    LandmarkProposal, SemanticMap, SuggestionStrategy,
)


class LandmarkSuggester(ABC):
    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def suggest(
        self,
        image: np.ndarray,                      # (H,W,3) uint8 RGB — the QUERY photo
        *,
        strategy: SuggestionStrategy,
        semantics: SemanticMap | None = None,   # reuse a prior segment job's output
        max_results: int = 25,
    ) -> tuple[LandmarkProposal, ...]:
        """Ranked, descending by score. MUST return () rather than raise when it finds
        nothing. Every proposal carries a human-readable `rationale` — a suggestion a
        surveyor cannot interrogate is one they will not accept."""

    def capabilities(self) -> "SuggesterCapabilities": ...
```

**Registered suggesters:**

| `name` | class | strategies | weights | fallback |
|---|---|---|---|---|
| `classical_suggester` | `ClassicalSuggester` | `corners` · `semantic` · `hybrid` | — | **None (TERMINAL)** |
| `sam_suggester` | `SamSuggester` | all four incl. `saliency` | ✔ | `classical_suggester` |

`ClassicalSuggester` — **terminal, no weights, runs today**: `corners` → Shi-Tomasi/Harris, non-max-suppressed, scored by cornerness × distance-from-edge; `semantic` → ridge intersections from `semantics/ridges.py` (road/canal crossings are the highest-value GCPs in farmland) plus contour corners from `semantics/classical.py`; `hybrid` → reciprocal-rank fusion of both. `saliency` is **not** offered by the classical path and `capabilities()` says so — `SuggestionStrategy.SALIENCY` on a weightless box resolves through the normal fallback and reports `effective: "hybrid"` in a `WarningItem`.

**`suggest_landmarks(image, *, cfg, registry, strategy, semantics, max_results) -> tuple[LandmarkProposal, ...]` is ai_engine's SECOND public entry point** (`ai_engine/__init__.py`, lazily). `LandmarkProposal` maps 1:1 onto a `landmark_suggestions` row. §4.13's "only public entry point" claim is amended accordingly.

### 4.24 ★ THE MATH CONVENTIONS — stated ONCE, normatively

**Every implementer reads this section and no other for these five facts.** Each was found stated two or three different ways across the specialist documents, and every one of them is a silent, plausible-looking error.

#### (1) `vec(H)` ordering is ROW-MAJOR, everywhere, forever

```
vec(H) := [h11, h12, h13, h21, h22, h23, h31, h32, h33]        # ROW-MAJOR
```

This is already the DB contract (`match_results.homography`: *"9 elems, ROW-MAJOR"*) and the API contract (§6.1: *"Homography | 9 floats, row-major"*). It is now also the **covariance** contract: `HomographyResult.covariance` is `cov(vec_row(H))`, and §7.5's Jacobian `A_h` is `∂p'/∂h` for that same `h`.

**The de-normalisation identity, corrected:**

```
H = T_b⁻¹ H̃ T_a
vec_row(H) = (T_b⁻¹ ⊗ T_aᵀ) vec_row(H̃)                       # ★ ROW-major
Σ_H        = (T_b⁻¹ ⊗ T_aᵀ) Σ_h̃ (T_b⁻¹ ⊗ T_aᵀ)ᵀ
```

> **★ 30-ai §6.4 had `(T_aᵀ ⊗ T_b⁻¹)` — the COLUMN-major identity `vec(AXB) = (Bᵀ ⊗ A)vec(X)`** — while §7.5's `A_h` is unambiguously row-major (its rows are `[u,v,1,0,0,0,−x'u,−x'v,−x']`), as is the DB and the API. For row-major, `vec_row(H) = vec_col(Hᵀ)` and `Hᵀ = T_aᵀ H̃ᵀ T_b⁻ᵀ`, so the correct factor is `(T_b⁻¹ ⊗ T_aᵀ)`, **which is not equal to `(T_aᵀ ⊗ T_b⁻¹)`**. Composing the two **silently permutes the 9×9 covariance**. §6.4 warns, verbatim, that *"a transposed vec convention here is a silent, plausible-looking error"* — **and then commits it.** Every reported error ellipse, every accuracy figure, and every unscented sigma point over `vec(H)` inherits the permutation, with no crash and no obviously-absurd output.
>
> **IU-05's test is the one that catches it:** build random `H̃, T_a, T_b`; assert `A_h @ Σ_H @ A_h.T` matches a **finite-difference / Monte-Carlo covariance** of the warped point under perturbation of `H`. A Frobenius-norm test on `H` alone **cannot see a permutation of Σ_H**.

#### (2) The gauge: `H` and `Σ_H` live in the SAME gauge, and it is `h₃₃ = 1`

```
Reporting gauge: h33 = 1 (matching HomographyResult.H and the DB).
Estimation gauge: ||h|| = 1 on the unit sphere (8 DOF), with the null direction projected
                  out:  Σ_h <- (I - ĥĥᵀ) Σ_h (I - ĥĥᵀ)

Convert BEFORE returning:
    g(h)  = h / h33
    J_g   = (1/h33) * (I9 - h @ e9ᵀ / h33)          # e9 selects h33
    Σ_H^(h33=1) = J_g @ Σ_h^(sphere) @ J_gᵀ
    cov_gauge = "h33_1"

EXCEPT when |H[2,2]| <= 1e-12 (legal — the line at infinity maps through the principal
point): J_g is undefined. Keep the spherical gauge and set cov_gauge = "unit_norm".
§7.5's A_h MUST branch on cov_gauge.
```

> **★ v1.0 mixed the two gauges and the error bars collapsed to zero.** §3.5 returned `H` scale-fixed to `h₃₃ = 1`, while §6.4 parameterised the estimate **on the unit sphere** and projected the covariance into **that** gauge — and §3.5 documented `covariance` as *"cov of vec(H) under gauge ‖h‖=1"*. Two different gauges, related by `s = H_sphere[2,2]`. §7.5 then computed `A_h` from the `h₃₃=1` `H` and multiplied it against a `Σ_H` on the sphere. **For a pixel-coordinate homography with entries of order 10³, `‖h‖ ≈ 10³`, so `H_sphere[2,2] ≈ 10⁻³` and `Σ_H` is too small by `s² ≈ 10⁻⁶`** relative to the frame `A_h` assumes. Result: `A_h Σ_H A_hᵀ` **vanishes**, the homography term drops out of `Σ_win` entirely, and **every GCP's error bar collapses to the click term** — i.e. **the product reports its most optimistic possible accuracy precisely when the fit is worst.** Nothing crashes; the numbers look beautiful. **IU-05 asserts the property the gauge bug destroys: `trace(A_h Σ_H A_hᵀ)` GROWS as the inlier hull shrinks.**

#### (3) The residual vector, its Jacobian shape, and σ_r²

```
Objective (symmetric transfer error), M correspondences:
    r(h) in R^{4M}     stacking BOTH directions, 2 components each way
    J = dr/dh in R^{4M x 9}                      # ★ 4M, not "2M x 9"
    Σ_h ≈ σ_r² (JᵀJ)⁺                            # Moore-Penrose; rank 8 by gauge freedom
    σ_r² = E(ĥ) / (2M − 8)                       # ★ 2M − 8 is CORRECT — see below
```

> **★ The `2M×9` shape was wrong and the `2M−8` denominator was right — for a reason v1.0 never gave.** The stated `E(h)` sums a forward AND a backward 2-vector residual per correspondence: **4M scalar components**, so `J` is `4M×9`, not `2M×9`. But the naive residual-count denominator `4M−8` is **also** wrong: the forward and backward residuals for correspondence *i* are **two views of one measurement** and are strongly correlated, so the **effective DOF is 2M−8**. So the shape was a typo and the denominator was a correct number with no justification — and the spec as written could not be implemented without guessing, with the two guesses differing by **2×** in the covariance that §7.5, §7.6, §9.6 and §13 all consume. **The one-line justification is now normative alongside the number.** IU-05 pins it executably: on synthetic data with known injected pixel noise σ, assert the recovered `HomographyResult.sigma_r ≈ σ`.

#### (4) The pose frame

```
World  = local ENU, metres: X east, Y north, Z up.
Camera = OpenCV: x right, y down, z forward.
    p_cam = R @ p_world + t_cam_from_world
    camera_position_enu = -R.T @ t_cam_from_world          # ★ THIS is the camera
    camera_height_m     = camera_position_enu[2]
```

**The Zhang-plane metric frame is built from `gsd_m`, NEVER from the geotransform:**

```
X_east  = (u - u_ref) * gsd_m
Y_north = (v_ref - v) * gsd_m          # ★ the y-flip is REQUIRED: window v grows south,
                                       #   ENU Y grows north. Omitting it hands a REFLECTED
                                       #   basis to the SVD, where R = U diag(1,1,det(UVᵀ)) Vᵀ
                                       #   silently absorbs it into a plausible wrong pose.
```

> **★ Why this is a prohibition and not a preference.** §9.3's Zhang-plane solve — *the primary pose path, chosen precisely because "the plane's metric frame is known, so the 4-way `decomposeHomographyMat` ambiguity never arises"* — needs **true ground metres**. But C-09 rules that `ai_engine` may not know `z`, `φ` or EPSG, leaving `PoseEstimator` with only `CandidateWindow`'s opaque `geotransform` + `crs` + `gsd_m`. **The geotransform is the more obvious choice — it carries the origin AND the y-flip** — and its `a`/`e` coefficients for a Web-Mercator provider are **3857 metres per pixel**, which 40-imagery §6.3 is emphatic are not metres: *"At 55°N a distance computed in 3857 metres is 74% too large. A field measured as 174 m is 100 m."* An implementer building the plane frame from the only in-layer source that looks complete inflates every ground distance by `1/cos φ`, so `camera_height_m` and `t` are wrong by **74% at 55°N** — Yorkshire, Denmark, southern Sweden, the Canadian prairie belt. §9.6's honest ±27% height bar is swamped by a systematic bias it does not model, and §13's camera posterior inherits it. **`gsd_m` IS correct and was always available; nothing said it was the only sanctioned source.** Now: §4.10 prohibits indexing `geotransform` inside `ai_engine`, §10.5 greps for it in `ai_engine/geometry/`, and IU-05 tests pose recovery at **φ=55°** — a φ=0 test cannot see this.

#### (5) `H_rect`'s uncertainty is part of the budget

```
horizon_to_rectifier(l_h, sigma_l_h, K, canvas) -> tuple[H_rect (3,3), Σ_Hrect (9,9)]

Σ_win = J_p Σ_p' J_pᵀ  +  A_h Σ_H A_hᵀ  +  A_r Σ_Hrect A_rᵀ  +  σ_mosaic² I₂
        └─ click ─────┘   └─ homography ┘   └─ RECTIFICATION ┘   └─ mosaic ─┘

where Σ_p' = J_rect Σ_p J_rectᵀ    # ★ the click covariance PUSHED INTO the rectified frame:
                                   #   isotropic in the original, strongly ANISOTROPIC after
                                   #   rectification. v1.0 defined Σ_p = σ_click² I₂ in the
                                   #   ORIGINAL frame and then used it against landmarks
                                   #   computed in the RECTIFIED frame.
      A_r = ∂p'/∂vec(H_rect)
```

`Σ_Hrect` is propagated from `sigma_horizon_px` and `CameraIntrinsics.sigma_f_rel` by the **unscented transform** — the same device §9.6 already uses and justifies (*"the UT avoids differentiating an SVD analytically, which is where a Jacobian-based implementation would go wrong subtly"*).

> **★ v1.0 propagated Σ_H THROUGH H_rect and treated H_rect itself as noise-free — and it is not.** The doc quantifies its noise *elsewhere*: `VanishingPointResult.sigma_horizon_px`, and the **default FOV fallback's `sigma_f_rel = 0.25`**. Since `H_rect = K' R_r K⁻¹` is built from exactly those two uncertain inputs, a 25% focal error and a several-pixel horizon error propagate in with a strongly anisotropic Jacobian **that blows up toward the horizon**. The result: **`OBLIQUE_RECTIFIABLE` — the regime the design most recommends** (*"rectification converts an unsolvable problem into SIFT's home ground… not a heuristic improvement but a change of transformation group"*) — **reported the most OPTIMISTIC error bars of any oblique path**, exactly inverting the honesty §7.6 is built on. `AccuracyEstimate.dominant_term` therefore gains a `"rectification"` member: for a no-EXIF `GROUND_HORIZON` photo it will frequently **be** the dominant term, which is precisely the fact the UI needs to surface. IU-05: `Σ_win` at `sigma_f_rel=0.25` is strictly larger than at `sigma_f_rel=0.05`.

### 4.25 `ai_engine.heatmap` — the posterior's background mass

```
# ai_engine/src/ai_engine/heatmap/posterior.py    ★ IU-07
π_w  ∝ exp(c_w / T),   Σ_w π_w = 1                       # component weights, softmax
π_bg  = 1 − max_w(c_w)/100                               # "not here" mass

p(x) = π_bg / A_aoi  +  (1 − π_bg) · Σ_w π_w · N(x; μ_w, Σ_w)      # ★ (1 − π_bg) scaling
                        ^^^^^^^^^^ THE FIX
```

> **★ The background did not have the mass it claimed — and it was worst exactly where it mattered most.** v1.0 rasterised `p(x) = π_bg/A_aoi + Σ_w π_w·N(...)` and then *"normalise[d] to sum 1"*. Total pre-normalisation mass is `π_bg + 1`, so the background's **actual** share was `π_bg/(1+π_bg)`, not `π_bg`. The doc's own worked case — *"even when the best candidate scored 22"* — should yield **78%** "not here" mass; it yielded `0.78/1.78 =` **44%**. At `c_max=50` the intended 50% became 33%. **The stated purpose was:** *"Without it the posterior always sums to 1 over the candidates and therefore ALWAYS claims the camera is in one of them… A posterior that cannot express 'I don't know' is not a posterior."* **It still could not.** It propagated into `entropy_norm` (the `>0.6` ⇒ "we have not localised" flag) and into every `CredibleRegion` — **the 95% HDR rings were drawn from a density whose "not here" mass was roughly half what was specified, so the rings were systematically too tight and too confident.** Scaling the components by `(1 − π_bg)` makes the sum exactly 1 before rasterisation, which demotes the normalise step to a numerical safeguard rather than a semantic change. IU-07 asserts, for `c_max ∈ {22, 50, 90}`, that the rasterised mass outside all component 3σ ellipses matches `π_bg`.

> **★ AND: the heatmap reads confidence as a probability, which §10.7 forbids.** Both `π_bg = 1 − max(c_w)/100` and the softmax temperature treat `confidence` as calibrated — while §10.7 states *"Raw confidence is a SCORE, not a probability… Default calibration is the identity, `calibrated=False`."* **Normative ruling:** while `calibrated == False`, `HeatmapRead` is **ORDINAL ONLY** — `HeatmapRead.calibrated: bool` ships on the wire, the UI renders it as a relative surface with no probability labelling, and `entropy_norm` remains usable as a *comparative* diffuseness signal. We do not print a percentage derived from an uncalibrated quantity.

### 4.26 `gis.heatmap` — window pixels to a geographic grid

```python
# gis/src/gis/heatmap.py     ★ IU-09
@dataclass(frozen=True, slots=True)
class GeoHeatmapCell:
    lon: float
    lat: float
    score: float                 # [0,1]
    sample_count: int            # ★ how many candidates contributed. absent != 0.
    components: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class GeoHeatmap:
    bbox: BBox
    cell_size_m: float           # TRUE metres
    grid_cols: int
    grid_rows: int
    cells: tuple[GeoHeatmapCell, ...]      # SPARSE
    argmax: LonLat | None
    argmax_score: float | None
    entropy_norm: float


def fuse_pixel_heatmaps(
    items: "Sequence[tuple[PixelHeatmap, CandidateWindow]]",
    *,
    cell_size_m: float,
) -> GeoHeatmap:
    """★ THE MISSING CONVERTER. Each PixelHeatmap is in ITS OWN window's pixel frame; the
    grid is built in local UTM (§5.2's rule: never accumulate in 3857) and emitted as 4326
    cell centroids ready for confidence_heatmaps/_cells.

    Overlapping windows contribute to the same cell: sample_count aggregates, and the UI
    dims low-sample cells (§5.6). This is the ONLY function that may see both a
    PixelHeatmap and a geotransform."""
```

### 4.27 `gis.elevation` — the mandated third coordinate

**The client brief mandates `lat/lon/elevation/confidence`.** v1.0 plumbed elevation end to end **as data** — `gcps.elevation_m`, `ck_gcps_elevation_sane`, `elevation_source ∈ {srtm|copernicus_dem|exif|manual}`, `GcpRead.elevation_m`, `GcpRecord.elevation_m`, CSV column 6 — and **no module produced it.** §2.2/§2.3's "every file that will exist" trees had no elevation module; §10.2's responsibility table had no elevation row; there was no ABC, no service, no `LE_ELEVATION_*` var, and no test. The specialist docs deliberately deferred it (*"out of scope here"*, *"out of scope for v1"*), but **CONTRACT.md declares itself "the only file an implementation agent needs" and never recorded the deferral.** An implementer following it ships `elevation_m` always `NULL` **with a populated `elevation_source` enum implying otherwise** — a survey deliverable silently missing its third coordinate.

```python
# gis/src/gis/elevation/base.py     ★ IU-09
@dataclass(frozen=True, slots=True)
class ElevationSample:
    elevation_m: float | None
    source: str                    # 'local_dem' | 'copernicus_dem' | 'srtm' | 'exif' | 'manual' | None
    vertical_ce90_m: float | None  # ★ honest, or None. Never a fabricated 0.


class ElevationProvider(abc.ABC):
    """Same contract as ImageryProvider: __init__ never raises, never touches the network;
    is_configured() is a pure local check; sample() raises no bare library exceptions."""
    name: ClassVar[str]

    @abc.abstractmethod
    def is_configured(self) -> bool: ...

    @abc.abstractmethod
    def sample(self, points: "Sequence[LonLat]") -> list[ElevationSample]:
        """Batch by design — a GCP set is sampled at once, and a per-point HTTP call to a
        DEM service for 40 GCPs is 40 round trips."""
```

**Registered:**

| `name` | class | keyless? | offline? | default |
|---|---|---|---|---|
| `none` | `NullElevationProvider` | ✔ | ✔ | **★★ DEFAULT · TERMINAL** — returns `ElevationSample(None, None, None)` for every point |
| `local_dem` | `LocalDemProvider` | ✔ | ✔ | DTM GeoTIFFs in `LE_LOCAL_DEM_DIR`, via `rasterio_shim` |
| `copernicus_dem` | `CopernicusDemProvider` | ✘ | ✘ | opt-in, keyed |

**The honesty rules, normative:** when the resolved provider yields `None`, `gcps.elevation_m IS NULL` **and `elevation_source IS NULL`** (`ck_gcps_elevation_source_consistent` binds the pair), the job appends `WarningItem{code:"ELEVATION_UNAVAILABLE"}`, and **every export writer emits an explicit empty cell rather than a silent blank.** `GET /capabilities` reports the elevation provider like any other. **`elevation_source` may never name a source that did not run.**

### 4.28 `gis.pose` — window frame to geography

```python
# gis/src/gis/pose.py     ★ IU-09
def window_yaw_to_north_deg(
    yaw_deg: float,                 # PoseResult.yaw_deg — 0 = -y of the window frame
    gt: tuple[float, float, float, float, float, float],
    crs: str,
    lon: float, lat: float,
) -> float:
    """-> camera_poses.yaw_deg: 0 = TRUE North, clockwise, [0, 360).

    Applies (a) the geotransform's rotation terms and (b) GRID CONVERGENCE — the angle
    between projected-grid north and true north at (lon, lat). For a north-up EPSG:3857
    window both are zero and this is the identity, which is why the bug was invisible in
    every plausible test. For a local_orthophoto UTM window convergence is NOT zero and
    grows with distance from the zone's central meridian.

    ★ NOBODY OWNED THIS CONVERSION IN v1.0: ai_engine's PoseResult is window-local and
      cannot do it (L3); gis had no pose module; §10.2 listed no pose responsibility for any
      gis module; gis/accuracy.py is scoped to covariance; and pose_service.py would have had
      to perform frame math in the ORCHESTRATION layer. §13.1 IU-09 now asserts both branches.
    """


def window_xy_to_lonlat(t_px, gt, crs: str) -> LonLat: ...
def pose_footprint(pose, gt, crs: str, *, max_range_m: float) -> list[LonLat]:
    """-> camera_poses.footprint. Drives the Leaflet view cone."""
def pose_sigma_to_deg(sigma_deg, gt, crs: str, lon: float, lat: float
                      ) -> tuple[float, float, float]: ...
```

---

## 5. Exact SQLAlchemy models

**Engine:** PostgreSQL 16 + PostGIS 3.4 (`postgis/postgis:16-3.4`). **ORM:** SQLAlchemy 2.x Declarative, `Mapped[...]`/`mapped_column`, + GeoAlchemy2. **Migrations:** Alembic, single linear head.

### 5.1 The five invariants

**I1 — The database never stores pixels-as-lat/lon or lat/lon-as-pixels.** Pixel space and geographic space are physically different column types (`geometry(...,0)` vs `geography(...,4326)`). A developer *cannot* accidentally join them; PostGIS raises a type error. The single largest bug class in a photogrammetry pipeline is a silent coordinate-space mixup, and we push detection of that class to DDL rather than to code review.

**I2 — Provenance is total.** Every `gcps` row traces to (a) the exact annotation revision the user drew, (b) the exact `match_results` row hence the exact homography, tile and provider, and (c) the exact `match_jobs` row hence the exact parameter set and code version. A GCP with no reproducible lineage is a liability in a surveying deliverable.

**I3 — Deep models are optional at the schema level too.** No column requires a deep model to be populated. Every score sub-component is nullable; `overall_confidence` is computed from whichever sub-scores are non-null, with the weights recorded per-job. A classical-only run produces a complete, valid, exportable row set.

**I4 — Provider swap changes data, not shape.** `imagery_provider` is an enum column, never a table. Adding a provider adds an enum label and zero schema changes.

**I5 — Everything is testable offline.** No column depends on network reachability. All reprojection is between 4326 and 3857, both hardcoded in `spatial_ref_sys`.

### 5.2 SRID policy — three spaces, physically distinct types

| Space | Storage type | Units | Used by |
|---|---|---|---|
| **Geographic (CANONICAL TRUTH)** | `geography(<T>, 4326)` | degrees on the WGS84 ellipsoid | `projects.aoi`, `images.exif_gps`, `images.bounds`, `match_jobs.search_aoi`, `match_results.tile_bounds`, `gcps.geom`, `gcps.original_geom`, `camera_poses.position`, `camera_poses.footprint`, `confidence_heatmaps.bbox`, `confidence_heatmaps.argmax_geom`, `confidence_heatmap_cells.geom`, `semantic_features.geo_geom` |
| **Web-Mercator (tile math only)** | `geometry(Polygon, 3857)` | Mercator metres — **badly distorted with latitude** | Exactly ONE stored column: `match_results.tile_bounds_3857` |
| **Image pixel (local Cartesian)** | `geometry(<T>, 0)` | pixels, **y-axis points DOWN** | `annotations.pixel_geom`, `annotation_versions.pixel_geom_after`, `semantic_features.pixel_geom`, `landmark_suggestions.pixel_geom` |

**Why 4326 `geography` for storage — the deciding argument.** `ST_Distance` on `geography` returns **true metres on the spheroid**. On `geometry(...,3857)` the same call returns Mercator metres, inflated by `1/cos(φ)` — a **60% error at 53°N** (much of European farmland) and ~100% at 60°N. Agricultural survey work happens at exactly the latitudes where Mercator is worst. Our accuracy checks, heatmap radius queries, and duplicate-GCP suppression all want real metres. Additionally: (a) CSV/GeoJSON/KML all deliver WGS84, so export is *serialization*, not reprojection; (b) `geography` GIST indexes as a 3-D geocentric box, so the antimeridian and the poles are correct — a 2-D 4326 `geometry` index gives **wrong answers** across ±180°, and agriculture happens in New Zealand too.

**Why SRID 0 for pixels.** SRID 0 in PostGIS honestly means "unknown CRS" — which is exactly what image pixel space is. **PostGIS *refuses* `ST_Transform` on SRID 0**, which makes I1 mechanical rather than aspirational. `ST_Intersects`, `ST_Area`, `ST_IsValid` and GIST all work fine.

**Axis convention (normative):** `x` = column index increasing rightward, `y` = row index increasing **downward**, origin at the **top-left** of the full-resolution image, in the image's *stored* orientation **after EXIF-orientation normalisation at ingest**. Because y points down, a polygon that looks counter-clockwise on screen is clockwise in the stored ring. **Do not attach meaning to ring winding order in pixel space.** All pixel polygons are normalised with `ST_ForcePolygonCW` at write time (application-side, not a trigger) purely so byte-level equality of two annotations is meaningful for the versioning system.

**No stored UTM.** `projects.working_srid` and `exports.target_srid` are **exporter hints only**; reprojection to UTM happens in GeoPandas in memory. Two stored copies of a geometry are two chances to disagree.

**The database performs NO reprojection on write.** Everything written to a `geography(...,4326)` column has already passed through `gis.crs` in Python. This keeps `ST_Transform` off the hot INSERT path. The one exception is the MVT endpoint's query-time `ST_Transform(g::geometry, 3857)`.

### 5.3 Enum types (17) — normative values

**Seventeen.** v1.0's heading said 13, §2.4 said *"all 13 enum types"*, §5.5 said *"(13 enum mirrors)"* — and the SQL block below defined **17**. Counted: `job_status`, `job_type`, `image_status`, `imagery_provider`, `annotation_geom_type`, `annotation_kind`, `annotation_op`, `semantic_class`, `feature_space`, `feature_detector`, `feature_extractor`, `feature_matcher`, `robust_estimator`, `pose_method`, `export_format`, `gcp_stale_reason`, `suggestion_status`.

Native PostgreSQL `ENUM`s. Created **once** in migration `0002` with `create_type=True`; every table reference uses `create_type=False`. Python mirrors live in `backend/app/models/enums.py` (ORM) and `backend/app/schemas/enums.py` (wire) — **separate files with identical values**; `backend/app/tests/unit/test_enum_parity.py` asserts they agree **via `PARITY_MAP`**.

```sql
CREATE TYPE job_status AS ENUM (
    'pending', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'retrying');

CREATE TYPE job_type AS ENUM (
    'match', 'export', 'batch', 'segment', 'suggest_landmarks', 'gcp_recompute', 'ingest');

CREATE TYPE image_status AS ENUM ('uploaded', 'processing', 'ready', 'failed');

-- Values ARE the registry keys of ImageryProvider implementations.
CREATE TYPE imagery_provider AS ENUM (
    'esri_world_imagery',   -- ★ DEFAULT. KEYLESS. (L2)
    'local_orthophoto',     -- local GeoTIFF directory, keyless, offline, HIGHEST ACCURACY
    'fixture',              -- ★ TEST-ONLY. Deterministic synthetic tiles. NO NETWORK.
    'mapbox_satellite',     -- requires LE_MAPBOX_ACCESS_TOKEN
    'bing_aerial',          -- requires LE_BING_MAPS_KEY
    'sentinel_copernicus',  -- requires LE_COPERNICUS_* creds
    'google_maps_static'    -- requires key AND LE_GOOGLE_TOS_ACKNOWLEDGED=true. Never default.
);
-- ★ There is deliberately NO 'google_earth' label. Google Earth imagery is out of scope by
-- client legal constraint; making it UNREPRESENTABLE IN THE TYPE SYSTEM is the cheapest
-- possible enforcement. Not a disabled flag: an absence.

CREATE TYPE annotation_geom_type AS ENUM ('point', 'polyline', 'polygon');

CREATE TYPE annotation_kind AS ENUM (
    'generic', 'field_corner', 'field_border', 'road', 'road_intersection',
    'irrigation_canal', 'tree', 'tree_line', 'greenhouse', 'building',
    'building_corner', 'water_body', 'pole_or_pylon', 'fence_post', 'crop_row', 'other');

CREATE TYPE annotation_op AS ENUM ('create', 'update', 'delete', 'restore');

CREATE TYPE semantic_class AS ENUM (
    'field_border', 'road', 'irrigation_canal', 'tree', 'tree_line', 'greenhouse',
    'building', 'water_body', 'crop_row', 'bare_soil', 'vegetation', 'shadow', 'unknown');

CREATE TYPE feature_space AS ENUM ('image_pixel', 'satellite_geo');

CREATE TYPE feature_detector AS ENUM ('classical_cv', 'sam', 'dinov2', 'manual', 'other');

CREATE TYPE feature_extractor AS ENUM ('sift', 'orb', 'akaze', 'brisk', 'asift', 'superpoint', 'dinov2');
CREATE TYPE feature_matcher   AS ENUM ('bf', 'flann', 'superglue', 'lightglue', 'loftr');

-- ★ THE ROBUST-FIT METHOD (= RansacConfig.method = HomographyMethod). NOT a registry key.
--   'usac_accurate' and 'lsq' ADDED: both are HomographyMethod members, so without them a
--   job using either could not record what actually ran. ALTER TYPE ADD VALUE is instant
--   (see the note below) — the four-label version was a needless lossy channel.
CREATE TYPE robust_estimator  AS ENUM (
    'ransac', 'usac_magsac', 'lmeds', 'prosac', 'usac_accurate', 'lsq');

-- ★ 'zhang_plane' ADDED. §2.2 names it the PRIMARY pose method ("PoseEstimator: Zhang-plane
--   primary") and camera_poses.method is NOT NULL — so without this label EVERY Zhang-plane
--   pose was literally unwritable.
CREATE TYPE pose_method AS ENUM (
    'zhang_plane', 'homography_decomposition', 'pnp', 'exif_gps_only', 'manual',
    'heatmap_argmax');

CREATE TYPE export_format AS ENUM ('csv', 'geojson', 'shapefile', 'kml', 'kmz', 'pdf', 'gpkg', 'dxf');

CREATE TYPE gcp_stale_reason AS ENUM (
    'landmark_moved', 'landmark_deleted', 'homography_superseded', 'annotations_restored');

CREATE TYPE suggestion_status AS ENUM ('pending', 'accepted', 'rejected');
```

> **Why native enums.** 4 bytes, self-documenting in `\dT+`, and — critically — **`ALTER TYPE ... ADD VALUE` is non-blocking and instant in PG 12+**, which kills the classic "enums are hard to extend" objection. Lookup tables add a join to every read of the hottest tables for data that changes at the rate of *code releases*. `VARCHAR + CHECK` requires a full table rewrite-scan to extend.

#### `PARITY_MAP` — normative (`backend/app/tests/unit/test_enum_parity.py`)

§13.1 mandated *"every `schemas.enums.X` and `models.enums.X` agree member-for-member"* — but **§6.2 lists 30 schema enums under different names**, and 13 of them have **no PG type at all**. The test **could not pair them**. This is the pairing, and it is the whole of it:

| PG type | `models.enums.*` | `schemas.enums.*` | `ai_engine.types.enums.*` |
|---|---|---|---|
| `job_status` | `JobStatus` | `JobStatus` | — |
| `job_type` | `JobType` | `JobType` | — |
| `image_status` | `ImageStatus` | `ImageStatus` | — |
| `imagery_provider` | `ImageryProvider` | **`ProviderName`** | — *(pinned to `gis…PROVIDER_NAMES`)* |
| `annotation_geom_type` | `AnnotationGeomType` | `AnnotationGeomType` | — |
| `annotation_kind` | `AnnotationKind` | `AnnotationKind` | — |
| `annotation_op` | `AnnotationOp` | `AnnotationOp` | — |
| `semantic_class` | `SemanticClass` | `SemanticClass` | **`SemanticClass`** ★ 3-leg |
| `feature_space` | `FeatureSpace` | `FeatureSpace` | — |
| `feature_detector` | `FeatureDetector` | **`FeatureDetectorName`** | — |
| `feature_extractor` | `FeatureExtractor` | **`ExtractorName`** | — |
| `feature_matcher` | `FeatureMatcher` | **`MatcherName`** | — |
| `robust_estimator` | `RobustEstimator` | **`EstimatorName`** | **`HomographyMethod`** ★ 3-leg |
| `pose_method` | `PoseMethod` | `PoseMethod` | **`PoseMethod`** ★ 3-leg |
| `export_format` | `ExportFormat` | `ExportFormat` | — |
| `gcp_stale_reason` | `GcpStaleReason` | `GcpStaleReason` | — |
| `suggestion_status` | `SuggestionStatus` | `SuggestionStatus` | — |

**The 13 wire-only enums are explicitly OUT OF PARITY SCOPE** and the test asserts that too (a new schema enum must be *deliberately* placed in one bucket or the other): `JobStage` · `SegmentBackend` · `SuggestionStrategy` · `BatchOnError` · `HealthStatus` · `ComponentStatus` · `ThumbnailSize` · `ImageFormat` · `HeatmapFormat` · `Colormap` · `ViewRegime` · `QualityFlag` · `CoordinateFormat`.

> `ViewRegime` is wire-only **on purpose**: `match_results.view_regime` is a plain `Text` column (§5.6), because it is diagnostic provenance rather than a queried dimension, and it is the one field most likely to gain members as the regime taxonomy is tuned against real oblique photos.

### 5.4 Global conventions

| Concern | Decision |
|---|---|
| **Primary keys** | `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` everywhere **except** `annotation_versions.id` and `confidence_heatmap_cells.id`, which are `BIGSERIAL`. IDs are minted client-side for optimistic UI and appear in URLs and export filenames. `gen_random_uuid()` is core in PG 13+ — **no `pgcrypto`**. The two exceptions are append-only, high-row-count, never referenced by URL; BIGSERIAL keeps the index tight and inserts sequential. |
| **Timestamps** | `TIMESTAMPTZ NOT NULL DEFAULT now()`. **Never `TIMESTAMP`.** Workers run UTC; surveyors are in arbitrary zones. |
| **`updated_at`** | Maintained by the trigger `tg_set_updated_at()`, attached per table. **Not by the ORM** — a Celery bulk `UPDATE` must not be able to skip it. Models declare `server_default=func.now(), server_onupdate=func.now()`. |
| **Soft delete** | Only `projects.deleted_at` and `images.deleted_at`. Everything below hard-cascades. Nobody asks to restore an orphan heatmap cell. |
| **Measures** | `DOUBLE PRECISION` for every CV scalar. **`NUMERIC` nowhere** — these are IEEE-754 values from NumPy. |
| **Confidence** | **0–100** for user-facing (`*_confidence`, `gcps.confidence`); **0–1** for model sub-scores (`*_score`) and `annotations.confidence`. Both `CHECK`-constrained. **The column NAME carries the unit.** |
| **JSONB not JSON** | Always. |
| **Naming** | `snake_case`; tables plural; FKs `<singular>_id`; `ix_/uq_/ck_/fk_/pk_` prefixes per the Alembic `naming_convention`. |
| **Arrays** | `DOUBLE PRECISION[]` + `CHECK (array_length(col,1) = N)` for fixed-arity bundles. A 3×3 homography is not a relation; nine columns `h00..h22` would be unjoinable anyway. |
| **Spatial columns** | **`spatial_index=False` on EVERY spatial column.** GeoAlchemy2's automatic `idx_<table>_<col>` cannot express *partial* GIST indexes and does not match our naming convention. All GIST indexes are declared explicitly in `__table_args__`. |
| **Enums** | `Enum(PyEnum, name="<pg_type>", create_type=False, values_callable=lambda e: [m.value for m in e])`. ★ `values_callable` is **required** or SQLAlchemy sends enum **names** (`PENDING`) instead of **values** (`pending`). |
| **Relationships** | Explicit `back_populates`, never `backref`. **`lazy="raise"` is the DEFAULT on every relationship** — the API is async; an accidental lazy load is a `MissingGreenlet` at best and an N+1 at worst. |
| **Cascades** | `cascade="all, delete-orphan"` **only** where the DDL says `ON DELETE CASCADE`, always with `passive_deletes=True` so PostgreSQL performs the cascade. **The database is the authority on cascade behaviour, not the ORM.** `GCP.match_result` uses `passive_deletes="all"` to keep SQLAlchemy from nulling the FK behind the `RESTRICT`. |

### 5.5 Class → table map (17 models, 17 tables)

| Class | `__tablename__` | File |
|---|---|---|
| `Base` (DeclarativeBase) | — | `backend/app/models/base.py` |
| `UUIDPkMixin` · `TimestampMixin` · `SoftDeleteMixin` | — | `backend/app/models/mixins.py` |
| *(13 enum mirrors)* | — | `backend/app/models/enums.py` |
| `Project` | `projects` | `backend/app/models/project.py` |
| `ProjectRevision` | `project_revisions` | `backend/app/models/revision.py` |
| `Image` | `images` | `backend/app/models/image.py` |
| `Annotation` | `annotations` | `backend/app/models/annotation.py` |
| `AnnotationVersion` | `annotation_versions` | `backend/app/models/annotation.py` |
| `MatchJob` | `match_jobs` | `backend/app/models/job.py` |
| `AuxJob` | `aux_jobs` | `backend/app/models/job.py` |
| `BatchJob` | `batch_jobs` | `backend/app/models/job.py` |
| `BatchJobItem` | `batch_job_items` | `backend/app/models/job.py` |
| `MatchResult` | `match_results` | `backend/app/models/match.py` |
| `GCP` | `gcps` | `backend/app/models/gcp.py` |
| `CameraPose` | `camera_poses` | `backend/app/models/pose.py` |
| `ConfidenceHeatmap` | `confidence_heatmaps` | `backend/app/models/heatmap.py` |
| `ConfidenceHeatmapCell` | `confidence_heatmap_cells` | `backend/app/models/heatmap.py` |
| `SemanticFeature` | `semantic_features` | `backend/app/models/semantic.py` |
| `LandmarkSuggestion` | `landmark_suggestions` | `backend/app/models/suggestion.py` |
| `Export` | `exports` | `backend/app/models/export.py` |

*(17 enum mirrors — §5.3.)*

#### The `v_jobs` view — exact, per branch

`v_jobs` (migration `0009`) is the `UNION ALL` behind `GET /jobs` and `deps.get_job()`. `backend/app/db/repositories/jobs.py` is its **only** reader.

> **★ v1.0 declared it as "projecting the common `JobRead` columns". There were no common columns.** `exports` had no `progress`, `progress_stage`, `attempt`, `max_attempts`, `degraded`, `degradation_reason`, `queued_at`, `started_at`, `duration_ms`. `batch_jobs` had no `attempt`, `max_attempts`, `degraded`, `degradation_reason`, `warnings`, `queued_at`, `duration_ms`, `progress_stage`, `image_id`. Meanwhile `JobRead` requires `attempt: int`, `max_attempts: int`, `degraded: bool`, `warnings: list[WarningItem]` and `progress: JobProgress` (with a **non-null** `stage: JobStage`) — **all non-nullable.** `JobRead.project_id` had no column on `match_jobs` at all, and `JobRead.batch_id` needed a join through `batch_job_items` (`match_jobs` stores `batch_job_item_id`, not `batch_job_id`). The view was unwritable as specified.
>
> **The ruling takes BOTH halves of the fix**, because each is right for a different reason: **migration `0008` adds the genuinely shared lifecycle columns to `exports` and `batch_jobs`** (they are real facts about those jobs — an export *does* retry, and *does* have a queued_at — and their absence was an oversight, not a design), **and §5.5 writes out the SELECT list per branch** with the literal defaults and joins each branch supplies, because some columns are honestly inapplicable and a literal is clearer than a nullable column nobody writes.

**Migration `0008` adds to BOTH `exports` and `batch_jobs`:** `attempt INT NOT NULL DEFAULT 0` · `max_attempts INT NOT NULL DEFAULT 3` · `progress_stage TEXT NULL` · `progress_message TEXT NULL` · `degraded BOOL NOT NULL DEFAULT FALSE` · `degradation_reason TEXT NULL` · `queued_at TIMESTAMPTZ NULL` · `duration_ms INT NULL`. (`exports` also gains `progress F8 NOT NULL DEFAULT 0.0` and `started_at TIMESTAMPTZ NULL`; `batch_jobs` also gains `warnings JSONB NOT NULL DEFAULT '[]'`.)

```sql
CREATE VIEW v_jobs AS
-- ── match ────────────────────────────────────────────────────────────────────
SELECT j.id, 'match'::job_type AS type, j.status,
       j.image_id, i.project_id,                       -- ★ project_id via images
       bi.batch_job_id AS batch_id,                    -- ★ batch_id via batch_job_items
       j.cancel_requested, j.attempt, j.max_attempts,
       j.progress, COALESCE(j.progress_stage, 'pending') AS progress_stage,
       j.progress_message, j.tiles_fetched, j.tiles_total, j.candidates_evaluated,
       j.degraded, j.degradation_reason, j.warnings,
       j.error_type, j.error_message,
       j.queued_at, j.started_at, j.finished_at, j.duration_ms,
       j.created_at, j.updated_at
  FROM match_jobs j
  JOIN images i ON i.id = j.image_id
  LEFT JOIN batch_job_items bi ON bi.id = j.batch_job_item_id
UNION ALL
-- ── aux: segment | suggest_landmarks | gcp_recompute | ingest ────────────────
SELECT a.id, a.type, a.status,
       a.image_id, i.project_id, NULL::uuid AS batch_id,
       a.cancel_requested, a.attempt, a.max_attempts,
       a.progress, COALESCE(a.progress_stage, 'pending'), a.progress_message,
       NULL::int, NULL::int, NULL::int,
       a.degraded, a.degradation_reason, a.warnings,
       a.error_type, a.error_message,
       a.queued_at, a.started_at, a.finished_at, a.duration_ms,
       a.created_at, a.updated_at
  FROM aux_jobs a
  JOIN images i ON i.id = a.image_id
UNION ALL
-- ── batch ───────────────────────────────────────────────────────────────────
SELECT b.id, 'batch'::job_type, b.status,
       NULL::uuid AS image_id, b.project_id, b.id AS batch_id,
       b.cancel_requested, b.attempt, b.max_attempts,
       b.progress, COALESCE(b.progress_stage, 'pending'), NULL::text,
       NULL::int, NULL::int, b.completed_items AS candidates_evaluated,
       b.degraded, b.degradation_reason, b.warnings,
       NULL::text, b.error_message,
       b.queued_at, b.started_at, b.finished_at, b.duration_ms,
       b.created_at, b.updated_at
  FROM batch_jobs b
UNION ALL
-- ── export ──────────────────────────────────────────────────────────────────
SELECT e.id, 'export'::job_type, e.status,
       e.image_id, e.project_id, NULL::uuid AS batch_id,
       e.cancel_requested, e.attempt, e.max_attempts,
       e.progress, COALESCE(e.progress_stage, 'pending'), e.progress_message,
       NULL::int, NULL::int, e.gcp_count AS candidates_evaluated,
       e.degraded, e.degradation_reason, e.warnings,
       NULL::text, e.error_message,
       e.queued_at, e.started_at, e.finished_at, e.duration_ms,
       e.created_at, e.updated_at
  FROM exports e;
```

```python
# backend/app/db/repositories/jobs.py     ★ the type deps.get_job() returns (§6.4)
@dataclass(frozen=True, slots=True)
class JobView:
    """★ A read-model over v_jobs, NOT an ORM entity — the view is not updatable and no
    row of it is a table row. v1.0 named `JobView` as the return type of deps.get_job()
    and DECLARED IT NOWHERE.

    Field-for-field the v_jobs column list above. `JobRead.model_validate(job_view)`
    succeeds because the names line up by construction; JobProgress is assembled from
    progress/progress_stage/progress_message/tiles_*/candidates_evaluated by the service.
    """
    id: UUID
    type: JobType
    status: JobStatus
    image_id: UUID | None
    project_id: UUID | None
    batch_id: UUID | None
    cancel_requested: bool
    attempt: int
    max_attempts: int
    progress: float                 # 0–1 in the DB; JobProgress.percent is 0–100
    progress_stage: str
    progress_message: str | None
    tiles_fetched: int | None
    tiles_total: int | None
    candidates_evaluated: int | None
    degraded: bool
    degradation_reason: str | None
    warnings: list[dict]
    error_type: str | None
    error_message: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime
```

`backend/app/models/__init__.py` **imports every module and re-exports every class**, so `Base.metadata` is fully populated. Alembic autogenerate silently produces an **empty diff** for any model module it never imported — the second-most-common Alembic footgun after the missing `geoalchemy2` import in `script.py.mako`.

### 5.6 Column reference

Column type notation: `UUID` = `PGUUID(as_uuid=True)`; `TSTZ` = `DateTime(timezone=True)`; `F8` = `Double`; `F8[]` = `PG_ARRAY(Double, dimensions=1)`; `JSONB`; `GEOG(T)` = `Geography(geometry_type=T, srid=4326, spatial_index=False)`; `GEOM0(T)` = `Geometry(geometry_type=T, srid=0, spatial_index=False)`; `GEOM3857(T)` = `Geometry(geometry_type=T, srid=3857, spatial_index=False)`.

#### `projects` — `Project`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | `gen_random_uuid()` | |
| `name` | Text | no | | `ck_projects_name_nonblank`: `length(btrim(name)) > 0` |
| `description` | Text | yes | | |
| `owner_id` | Text | yes | | placeholder until the auth ADR lands |
| `aoi` | GEOG(POLYGON) | yes | | optional AOI; seeds the search hint (precedence 5) |
| `working_srid` | Integer | yes | | ★ exporter HINT ONLY, never storage. `1024..32767` |
| `default_provider` | `imagery_provider` | no | `'esri_world_imagery'` | ★ keyless at the DATA layer — a fresh row is runnable |
| `default_extractor` | `feature_extractor` | no | `'sift'` | §12 C-23 |
| `default_matcher` | `feature_matcher` | no | `'flann'` | |
| `default_estimator` | `robust_estimator` | no | `'usac_magsac'` | ★ the **robust-fit METHOD** (`RansacConfig.method`), never a registry key. §4.7. |
| `default_search_radius_m` | F8 | no | `1000.0` | ★ `ck_projects_search_radius`: **`BETWEEN 50 AND 50000`**. v1.0 said `10..50000` here while `schemas.matching.SearchHint.radius_m` says `50..50000 -> else 422` — so a project legally storing `10` produced a `MatchRequest` the API **rejected with 422 against its own stored default**. 50 m is the floor anyone actually argued for. |
| `default_search_zoom` | SmallInteger | no | `18` | `10..21` |
| `tags` | `PG_ARRAY(Text)` | no | `'{}'` | ≤20, each ≤50 chars |
| `meta` | JSONB | no | `'{}'` | ★ attr `meta`, **column `metadata`** — `metadata` is reserved on `DeclarativeBase` |
| `current_revision_seq` | BigInteger | no | `0` | monotonic per-project revision counter |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |
| `deleted_at` | TSTZ | yes | | soft delete |

Indexes: `ix_projects_owner_active (owner_id, updated_at DESC) WHERE deleted_at IS NULL` · `ix_projects_name_trgm GIN(name gin_trgm_ops)` · `ix_projects_aoi GIST(aoi)` · `ix_projects_tags GIN(tags)`.

`current_revision_seq` is bumped with `UPDATE projects SET current_revision_seq = current_revision_seq + 1 ... RETURNING current_revision_seq` **inside the same transaction** that writes the revision, which serialises concurrent editors on that single row. **That row-level lock is the concurrency control for undo/redo** — deliberately simple, and correct.

#### `images` — `Image`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | `gen_random_uuid()` | |
| `project_id` | UUID FK→`projects` **CASCADE** | no | | |
| `filename` | Text | no | | original client filename, **untrusted** |
| `storage_path` | Text | no | | server-controlled. ★ **NEVER serialised to the wire** |
| `thumbnail_path` | Text | yes | | |
| `mime_type` | Text | no | | `image/jpeg\|png\|tiff\|webp` |
| `size_bytes` | BigInteger | no | | `> 0` |
| `checksum_sha256` | `CHAR(64)` | no | | `ck_images_checksum_hex`: `~ '^[0-9a-f]{64}$'` |
| `status` | `image_status` | no | `'uploaded'` | ★ §12 C-21 |
| `width` / `height` | Integer | no | | ★ **post EXIF-orientation normalisation** |
| `band_count` | SmallInteger | no | `3` | |
| `resolution_dpi` | F8 | yes | | EXIF XResolution, informational |
| `gsd_m` | F8 | yes | | GeoTIFF only |
| `exif` | JSONB | no | `'{}'` | ★ FULL EXIF, **verbatim**. The forensic record. |
| `exif_gps` | GEOG(POINT) | yes | | decoded from GPSLatitude/GPSLongitude |
| `exif_gps_altitude_m` | F8 | yes | | |
| `exif_gps_direction_deg` | F8 | yes | | GPSImgDirection; seeds the pose prior. `[0,360)` |
| `exif_gps_hpe_m` | F8 | yes | | GPSHPositioningError → search radius inflation |
| `gps_source` | Text | yes | | `exif` \| `manual` \| `null` |
| `camera_make` / `camera_model` / `lens_model` | Text | yes | | |
| `focal_length_mm` / `focal_length_35mm` / `sensor_width_mm` / `f_number` | F8 | yes | | ★ `sensor_width_mm` resolved from a bundled camera DB on `(make, model)` — required for `K` |
| `is_geotiff` | Boolean | no | `FALSE` | ★ a property DISCOVERED at ingest, never a declared type |
| `crs_epsg` | Integer | yes | | **NATIVE** CRS of the GeoTIFF |
| `crs_wkt` | Text | yes | | full WKT2 for exotic CRS |
| `bounds` | GEOG(POLYGON) | yes | | footprint, **reprojected at ingest** |
| `geotransform` | F8[] | yes | | 6 elems, GDAL order, in the **NATIVE** CRS |
| `nodata_value` | F8 | yes | | |
| `notes` | Text | yes | | §12 C-22 |
| `meta` | JSONB | no | `'{}'` | column `metadata` |
| `captured_at` | TSTZ | yes | | EXIF DateTimeOriginal |
| `uploaded_at` | TSTZ | no | `now()` | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |
| `deleted_at` | TSTZ | yes | | |

Checks: `ck_images_dims` `width>0 AND height>0` · `ck_images_geotiff_complete` — **a GeoTIFF is only usable if it carries the full georeferencing triple**: `NOT is_geotiff OR (crs_epsg IS NOT NULL AND bounds IS NOT NULL AND geotransform IS NOT NULL AND array_length(geotransform,1)=6)` · `ck_images_geotransform_arity`.

Indexes: `uq_images_storage_path (storage_path)` · `uq_images_project_checksum (project_id, checksum_sha256) WHERE deleted_at IS NULL` · `ix_images_project_uploaded (project_id, uploaded_at DESC) WHERE deleted_at IS NULL` · `ix_images_filename_trgm` · `ix_images_exif_gps GIST(exif_gps) WHERE exif_gps IS NOT NULL` · `ix_images_bounds GIST(bounds) WHERE bounds IS NOT NULL` · `ix_images_exif_gin GIN(exif jsonb_path_ops)` · `ix_images_camera (camera_make, camera_model) WHERE camera_make IS NOT NULL` · `ix_images_status (status) WHERE status <> 'ready'`.

> **Why full EXIF as JSONB *and* promoted columns.** The promoted columns are what the pipeline reads on every job — they belong in fixed columns with real types and real indexes. The `exif` JSONB is the **forensic record**: a surveying deliverable may be challenged years later, and "what did the camera actually report" must be answerable byte-for-byte. Promoted columns are formally a *cache*. **If they ever disagree, `exif` wins and it is an ingest bug.**

#### `annotations` — `Annotation`

**One table for all three geometry types.** Point/polyline/polygon annotations are the same entity with the same lifecycle, versioning, ordering, `kind` vocabulary and consumers. Three tables would triple the versioning machinery, force `UNION ALL` on every canvas load, and make `gcps.landmark_id` inexpressible — a GCP can derive from a polygon's corner as easily as from a point.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | `gen_random_uuid()` | |
| `image_id` | UUID FK→`images` **CASCADE** | no | | |
| `kind` | `annotation_kind` | no | `'generic'` | |
| `geom_type` | `annotation_geom_type` | no | | |
| `pixel_x` / `pixel_y` | F8 | **no** | | ★ the **representative point** for ALL types |
| `pixel_geom` | GEOM0(GEOMETRY) | no | | ★ the authoritative geometry. PIXELS, y-DOWN. |
| `label` / `description` | Text | yes | | |
| `confidence` | F8 | no | `1.0` | ★ **0–1. The SURVEYOR'S OWN CERTAINTY.** Not the algorithm's. |
| `ordering` | Integer | no | `0` | toolbar / export order |
| `style` | JSONB | no | `'{}'` | Konva render hints |
| `attributes` | JSONB | no | `'{}'` | free-form user metadata |
| `is_deleted` | Boolean | no | `FALSE` | ★ tombstone |
| `version_no` | Integer | no | `1` | optimistic-lock counter → `ETag` |
| `revision_seq` | BigInteger | no | | project revision that last touched this |
| `created_by` / `updated_by` | Text | yes | | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |

Checks: `ck_annotations_geom_type_match` — binds `geom_type` ↔ `GeometryType(pixel_geom)` (`point↔POINT`, `polyline↔LINESTRING`, `polygon↔POLYGON`). **This is the guard that makes the single-table design safe.** · `ck_annotations_geom_valid` `ST_IsValid(pixel_geom)` · `ck_annotations_geom_2d` `ST_NDims=2` · `ck_annotations_geom_srid` `ST_SRID=0` · `ck_annotations_polyline_min` `ST_NPoints >= 2` · `ck_annotations_polygon_min` `ST_NPoints(ST_ExteriorRing) >= 4` · `ck_annotations_pixel_nonneg` · `ck_annotations_confidence` `BETWEEN 0 AND 1` · `ck_annotations_version_pos`.

Indexes: `ix_annotations_image_order (image_id, ordering, created_at) WHERE is_deleted = FALSE` · `ix_annotations_pixel_geom GIST(pixel_geom)` · `ix_annotations_kind (image_id, kind) WHERE is_deleted = FALSE` · `ix_annotations_attributes GIN(attributes jsonb_path_ops)` · `ix_annotations_revision (revision_seq)`.

> **Why `pixel_x`/`pixel_y` are NOT NULL even for polygons.** Nullable would mean every consumer — the Konva label renderer, the CSV exporter, the landmark-consistency scorer — writes `COALESCE(pixel_x, ST_X(ST_PointOnSurface(pixel_geom)))`. Instead they are **the representative point of the annotation, whatever its type**, computed server-side at write time: identical to the vertex for points, `ST_PointOnSurface` for polygons, midpoint-along-arc for polylines. **Derived server-side, never accepted from the client** — accepting them would let the column drift from `pixel_geom`, and that column is what the label renderer and the GCP deriver read. The cost is one derived column pair; the benefit is that `gcps.pixel_x/y` can be copied from *any* landmark type uniformly, which is what makes "a polygon corner can be a GCP" work.

> **Bounds are not `CHECK`ed against `images.width/height`** — a `CHECK` cannot reference another table. Validated in the Pydantic layer (`422 ANNOTATION_OUT_OF_BOUNDS`) and by a nightly consistency query.

#### `annotation_versions` — `AnnotationVersion`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | **BigInteger PK, autoincrement** | no | ★ **serialised as a JSON NUMBER**, not a string |
| `annotation_id` | UUID | no | ★ **deliberately NOT an FK** — the log outlives the row |
| `image_id` | UUID FK→`images` **CASCADE** | no | |
| `revision_id` | UUID FK→`project_revisions` **SET NULL** | yes | |
| `op` | `annotation_op` | no | |
| `version_no` | Integer | no | resulting `annotations.version_no` |
| `before` | JSONB | yes | ★ NULL **iff** `op='create'` |
| `after` | JSONB | yes | ★ NULL **iff** `op='delete'` |
| `pixel_geom_after` | GEOM0(GEOMETRY) | yes | denormalised post-state for canvas "ghost" rendering |
| `actor_id` | Text | yes | |
| `client_op_id` | Text | yes | ★ client-minted idempotency key per user gesture |
| `created_at` | TSTZ | no | |

Checks: `ck_annotation_versions_payload` — the biconditional binding `op` to `before`/`after` nullity · `ck_annotation_versions_version_pos`.

Indexes: `uq_annotation_versions_annotation_version (annotation_id, version_no)` · `uq_annotation_versions_client_op (client_op_id) WHERE client_op_id IS NOT NULL` · **`ix_annotation_versions_annotation (annotation_id, version_no DESC)` — ★ this index is what makes undo O(1)** · `ix_annotation_versions_image_time (image_id, id DESC)` · `ix_annotation_versions_revision (revision_id) WHERE revision_id IS NOT NULL` · `ix_annotation_versions_actor (actor_id, id DESC) WHERE actor_id IS NOT NULL` · `ix_annotation_versions_geom GIST(pixel_geom_after) WHERE pixel_geom_after IS NOT NULL` · `ix_annotation_versions_after GIN(after jsonb_path_ops)`.

> **Why `annotation_id` is NOT a foreign key.** The log must outlive the row. Under an FK, a `'create'` event for an annotation that a later hard-delete removed would force us to either cascade-delete the audit trail (destroying history — unacceptable) or block the delete. A plain indexed UUID makes the log a genuine append-only ledger. **Tolerating dangling references is the normal and correct property of an audit log.**

> **Why the hybrid event-log + rolling-snapshot design.** Not pure snapshot: write amplification is O(n) per nudge — 200 landmarks dragged 60 times writes 12 000 rows for 60 tiny changes, cannot attribute changes, and a restore would orphan every GCP. Not pure log: reconstructing revision 47 folds the whole log from zero. **Events carry BOTH `before` and `after`, which is what makes undo O(1)** — a single indexed row read, no fold. Checkpoints every `LE_CHECKPOINT_EVERY_N_EVENTS` bound reconstruction.

#### `project_revisions` — `ProjectRevision`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID PK | no | |
| `project_id` | UUID FK→`projects` **CASCADE** | no | |
| `seq` | BigInteger | no | monotonic within project; from `projects.current_revision_seq` |
| `label` | Text | yes | |
| `actor_id` | Text | yes | |
| `is_checkpoint` | Boolean | no | default `FALSE` |
| `snapshot` | JSONB | yes | ★ populated **iff** `is_checkpoint`. `{"schema_version":1,"images":{"<uuid>":[...]}}` |
| `annotation_count` | Integer | no | default `0` |
| `event_count` | Integer | no | default `0` — events since the previous checkpoint |
| `created_at` | TSTZ | no | |

Checks: `ck_project_revisions_snapshot_iff_checkpoint` (biconditional) · `ck_project_revisions_seq_pos`.
Indexes: `uq_project_revisions_project_seq (project_id, seq)` · `ix_project_revisions_project_seq (project_id, seq DESC)` · **`ix_project_revisions_checkpoints (project_id, seq DESC) WHERE is_checkpoint`** — "nearest preceding checkpoint" in one backward index scan · `ix_project_revisions_snapshot GIN(snapshot jsonb_path_ops) WHERE is_checkpoint`.

#### `match_jobs` — `MatchJob`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | | |
| `image_id` | UUID FK→`images` **CASCADE** | no | | |
| `batch_job_item_id` | UUID FK→`batch_job_items` **SET NULL** | yes | | |
| `celery_task_id` | Text | yes | | NULL between INSERT and `.delay()` |
| `status` | `job_status` | no | `'pending'` | |
| `cancel_requested` | Boolean | no | `FALSE` | ★ §12 C-24. Cooperative cancellation. |
| `attempt` | Integer | no | `0` | |
| `max_attempts` | Integer | no | `3` | |
| `provider` | `imagery_provider` | no | `'esri_world_imagery'` | ★ the reproducibility record |
| `extractor` | `feature_extractor` | no | `'sift'` | |
| `matcher` | `feature_matcher` | no | `'flann'` | |
| `estimator` | `robust_estimator` | no | `'usac_magsac'` | |
| `use_semantic` | Boolean | no | `FALSE` | ★ was SAM/DINOv2 **requested** |
| `semantic_available` | Boolean | no | `FALSE` | ★ was it **actually usable** |
| `search_aoi` | GEOG(POLYGON) | yes | | the RESOLVED hint |
| `search_radius_m` | F8 | yes | | |
| `search_zoom_levels` | `PG_ARRAY(SmallInteger)` | no | `'{18}'` | |
| `max_tiles` | Integer | no | `256` | |
| `max_candidates` | Integer | no | `25` | |
| `params` | JSONB | no | `'{}'` | extractor/matcher/ransac knobs |
| `score_weights` | JSONB | no | `'{"feature":0.25,"geometric":0.35,"landmark":0.30,"semantic":0.10}'` | ★ §12 C-13 |
| `annotation_revision_seq` | BigInteger | yes | | ★ pins the annotation set matched against |
| `seed` | Integer | yes | | pins RANSAC's RNG → bit-reproducible |
| `progress` | F8 | no | `0.0` | **0–1** |
| `progress_stage` | Text | yes | | |
| `progress_message` | Text | yes | | |
| `tiles_fetched` / `tiles_total` | Integer | no/yes | `0`/— | |
| `candidates_evaluated` | Integer | no | `0` | |
| `result_count` | Integer | no | `0` | |
| `best_confidence` | F8 | yes | | 0–100, denorm of the selected result |
| `error_type` / `error_message` | Text | yes | | |
| `error_traceback` | Text | yes | | ★ **stored server-side only. NEVER serialised.** |
| `warnings` | JSONB | no | `'[]'` | `WarningItem[]` |
| `code_version` | Text | yes | | git sha of the worker image |
| `worker_hostname` | Text | yes | | |
| `used_gpu` | Boolean | no | `FALSE` | |
| `degraded` | Boolean | no | `FALSE` | ★ the L1 UX contract |
| `degradation_reason` | Text | yes | | |
| `queued_at` / `started_at` / `finished_at` | TSTZ | yes | | |
| `duration_ms` | Integer | yes | | |
| `timings` | JSONB | no | `'{}'` | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |

Checks: `ck_match_jobs_progress` `BETWEEN 0 AND 1` · `ck_match_jobs_attempt` `>= 0 AND <= max_attempts` · `ck_match_jobs_best_conf` `BETWEEN 0 AND 100` · `ck_match_jobs_failed_has_error` `status <> 'failed' OR error_message IS NOT NULL` · **`ck_match_jobs_finished_iff_terminal`** `(status IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)`.

Indexes: `uq_match_jobs_celery_task_id (celery_task_id) WHERE celery_task_id IS NOT NULL` · **`ix_match_jobs_status_created (status, created_at) WHERE status IN ('pending','queued','running','retrying')`** · `ix_match_jobs_image_created (image_id, created_at DESC)` · `ix_match_jobs_batch_item` · `ix_match_jobs_search_aoi GIST(search_aoi) WHERE search_aoi IS NOT NULL` · `ix_match_jobs_params GIN(params jsonb_path_ops)`.
Storage: `fillfactor = 70` (heavy `progress` UPDATE churn → keep HOT updates on-page and off the indexes).

> **`use_semantic` vs `semantic_available` is the graceful-degradation record.** The user asks for SAM; the worker discovers the weights are absent, logs, and proceeds classically. **The job SUCCEEDS.** But the row must not lie about what produced the numbers: `use_semantic=TRUE, semantic_available=FALSE`, a line in `warnings`, and `match_results.semantic_similarity_score IS NULL`. A reviewer looking at a 92% GCP six months later can see exactly which scorers were live. **This is L1 expressed as data.**

> **`ck_match_jobs_finished_iff_terminal` is a biconditional** — it catches both "marked succeeded but never timestamped" and "timestamped but still shows running": the two states that make a progress UI hang forever.

> **`score_weights` is stored per job, not read from config at display time.** Weights will be retuned. A stored result whose confidence was computed under old weights must remain explicable; recomputing the displayed number from today's config would silently rewrite history.

#### `aux_jobs` — `AuxJob`  ★ NEW (§12 C-19)

Backs the `segment`, `suggest_landmarks`, `gcp_recompute` and `ingest` job types, which the API promises `202 → GET /jobs/{id}` for but which the DB design had no home for.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | | |
| `type` | `job_type` | no | | ★ `CHECK type IN ('segment','suggest_landmarks','gcp_recompute','ingest')` |
| `image_id` | UUID FK→`images` **CASCADE** | no | | |
| `match_result_id` | UUID FK→`match_results` **SET NULL** | yes | | `gcp_recompute` only |
| `celery_task_id` | Text | yes | | |
| `status` | `job_status` | no | `'pending'` | |
| `cancel_requested` | Boolean | no | `FALSE` | |
| `attempt` / `max_attempts` | Integer | no | `0` / `3` | |
| `params` | JSONB | no | `'{}'` | the request body, verbatim |
| `progress` | F8 | no | `0.0` | 0–1 |
| `progress_stage` / `progress_message` | Text | yes | | |
| `result_count` | Integer | no | `0` | |
| `error_type` / `error_message` / `error_traceback` | Text | yes | | |
| `warnings` | JSONB | no | `'[]'` | |
| `degraded` | Boolean | no | `FALSE` | |
| `degradation_reason` | Text | yes | | |
| `code_version` / `worker_hostname` | Text | yes | | |
| `queued_at` / `started_at` / `finished_at` | TSTZ | yes | | |
| `duration_ms` | Integer | yes | | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |

Same `finished_iff_terminal` and `failed_has_error` checks. Indexes: `uq_aux_jobs_celery_task_id` · `ix_aux_jobs_status_created (status, created_at) WHERE status IN ('pending','queued','running','retrying')` · `ix_aux_jobs_image_type (image_id, type, created_at DESC)`.

#### `match_results` — `MatchResult`

One row per **candidate** the matcher scored. The winner is `is_selected = TRUE`. **Losers are kept** — the UI offers "other candidates", and a surveyor overruling the algorithm is a first-class workflow.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | | |
| `match_job_id` | UUID FK→`match_jobs` **CASCADE** | no | | |
| `parent_match_result_id` | UUID FK→`match_results` **SET NULL** | yes | | ★ §12 C-25. Set by `gcps/recompute`. |
| `rank` | Integer | no | | 1 = best. `>= 1` |
| `is_selected` | Boolean | no | `FALSE` | |
| `provider` | `imagery_provider` | no | | denorm from job |
| `tile_z` | SmallInteger | **yes** | | `0..22`. ★ **NULLABLE** — the window's ANCHOR tile. Addressing metadata only. |
| `tile_x` / `tile_y` | Integer | **yes** | | `>= 0 AND < (1 << tile_z)` |
| `mosaic_cols` / `mosaic_rows` | SmallInteger | no | `1` | |
| `tile_bounds` | GEOG(POLYGON) | no | | ★ **CANONICAL** |
| `tile_bounds_3857` | GEOM3857(POLYGON) | yes | | ★ derived, denormalised **on purpose** |
| `satellite_image_path` | Text | **yes** | | cached mosaic on disk/S3. ★ **NULLABLE** — written by `app.tasks.matching` via `ObjectStorage` from `best.window.rgb`. |
| `satellite_checksum` | `CHAR(64)` | yes | | |
| `satellite_width_px` / `satellite_height_px` | Integer | yes | | |
| **`homography`** | **F8[]** | **yes** | | ★ **9 elems, ROW-MAJOR** `[h00,h01,h02,h10,h11,h12,h20,h21,h22]`. Maps **IMAGE PIXEL (x,y,1) → SATELLITE MOSAIC PIXEL (u,v,w)**, i.e. `cv2.findHomography(src=image, dst=mosaic)`. ★ **NULLABLE** — `WindowResult.homography` is `None` when estimation was not attempted, and §11.6 requires rejected candidates be persisted with their `DegeneracyReport`. |
| **`sat_geotransform`** | **F8[]** | **yes** | | ★ **6 elems, GDAL order** `[c,a,b,f,d,e]`: `X = c + a·(u+0.5) + b·(v+0.5)`, `Y = f + d·(u+0.5) + e·(v+0.5)`. Maps **MOSAIC PIXEL → the CRS named by `sat_geotransform_srid`.** |
| **`sat_geotransform_srid`** | **Integer** | **no** | `4326` *(unused sentinel)* | ★ **NEW.** The SRID `sat_geotransform` lands in — `3857` for every slippy provider, **a UTM code for `local_orthophoto`**. `ck_match_results_srid_iff_gt` binds it to `sat_geotransform IS NOT NULL`. |
| `imagery_captured_at` | TSTZ | yes | | ★ **NEW.** From `CandidateWindow.captured_at`. Feeds `ExportContext.imagery_captured_at` and the normative CSV column — which had **no producer** in v1.0. |
| `attribution` | Text | **no** | | ★ **NEW.** From `CandidateWindow.attribution`. Served on `X-Imagery-Attribution` (endpoint 36) and in every PDF **from THIS ROW**, never by re-resolving the provider — which may have been reconfigured since. |
| `terms_url` | Text | yes | | ★ **NEW.** Same argument. |
| `gsd_m` | F8 | yes | | ★ **TRUE ground metres** per mosaic pixel at centre, cos(φ)-corrected |
| `georef_ce90_m` | F8 | yes | | ★ the PROVIDER's own error. Never reducible by us. |
| `is_authoritative` | Boolean | no | `FALSE` | |
| `feature_extractor_used` | `feature_extractor` | **yes** | | ★ what **actually** ran. NULLABLE for the same reason as `homography`. |
| `feature_matcher_used` | `feature_matcher` | **yes** | | |
| `estimator_used` | `robust_estimator` | **yes** | | ★ the **METHOD** that ran (`RansacConfig.method`), not a registry key |
| `keypoints_query` / `keypoints_train` / `raw_matches` / `good_matches` | Integer | yes | | |
| `inlier_count` | Integer | no | | `>= 0` |
| `inlier_ratio` | F8 | yes | | `BETWEEN 0 AND 1` |
| `ransac_reproj_error_px` / `ransac_threshold_px` | F8 | yes | | symmetric transfer RMS over inliers |
| `ransac_iterations` | Integer | yes | | |
| `homography_condition_number` | F8 | yes | | ★ on the **Hartley-normalised** `H̃` |
| `homography_determinant` | F8 | yes | | ★ `det(H̃)`. `<= 0` ⇒ reflection ⇒ reject |
| `view_regime` | Text | yes | | `nadir\|oblique_rectifiable\|oblique_raw\|ground_horizon\|unknown` |
| `degeneracy_gate` | F8 | yes | | `[0,1]`. `0` ⇒ rejected. |
| `degeneracy_report` | JSONB | no | `'{}'` | the full `DegeneracyReport` |
| `feature_similarity_score` | F8 | yes | | **0–1, NULLABLE** |
| `geometric_consistency_score` | F8 | yes | | **0–1, NULLABLE** |
| `landmark_consistency_score` | F8 | yes | | **0–1, NULLABLE** |
| `semantic_similarity_score` | F8 | yes | | **0–1, NULL when no semantics ran** |
| `overall_confidence` | F8 | no | `0.0` | ★ **0–100**. A rejected candidate is legitimately `0`. |
| `score_breakdown` | JSONB | no | `'{}'` | ★ audit of the exact arithmetic incl. `"renormalized": true` |
| `score_feature_vector` | F8[] | yes | | ★ persisted so calibration can be refit offline |
| `calibrated` | Boolean | no | `FALSE` | |
| `calibration_id` | Text | no | `'identity'` | |
| `degraded` | Boolean | no | `FALSE` | ★ result-level, not just job-level |
| `degradation_reason` | Text | yes | | |
| `quality_flags` | `PG_ARRAY(Text)` | no | `'{}'` | advisory badges |
| `created_at` | TSTZ | no | `now()` | |

Checks: `ck_match_results_homography_arity` (`homography IS NULL OR array_length = 9`) · `ck_match_results_geotransform_arity` (`sat_geotransform IS NULL OR array_length = 6`) · `ck_match_results_tile_z` · `ck_match_results_tile_xy` · `ck_match_results_tile_triple` (`(tile_z IS NULL) = (tile_x IS NULL) AND (tile_z IS NULL) = (tile_y IS NULL)`) · `ck_match_results_mosaic` · `ck_match_results_rank` · `ck_match_results_inliers` · `ck_match_results_inlier_ratio` · `ck_match_results_subscores` (all four `IS NULL OR BETWEEN 0 AND 1`) · `ck_match_results_overall` `BETWEEN 0 AND 100` · `ck_match_results_srid_iff_gt` (`(sat_geotransform IS NULL) = (sat_geotransform_srid = 4326 AND sat_geotransform IS NULL)` — i.e. the SRID is meaningful **iff** the geotransform exists) · **★ `ck_match_results_selected_is_complete`**:

```sql
NOT is_selected OR (
    homography             IS NOT NULL AND
    sat_geotransform       IS NOT NULL AND
    sat_geotransform_srid  IS NOT NULL AND
    satellite_image_path   IS NOT NULL AND
    feature_extractor_used IS NOT NULL AND
    feature_matcher_used   IS NOT NULL AND
    estimator_used         IS NOT NULL
)
```

> **★ Why six columns went NULLABLE and one CHECK replaced them.** v1.0 declared `homography`, `sat_geotransform`, `satellite_image_path`, `tile_z/x/y`, `feature_*_used` and `estimator_used` **NOT NULL** — and the pipeline provably cannot always supply them:
> **(a)** `WindowResult.homography` is `HomographyResult | None` — *"None when estimation was not attempted"* — and §11.6 **requires** rejected candidates be persisted **with their DegeneracyReport** so a reviewer can see *why*. A rejected candidate has no homography and no estimator. Under NOT NULL, **the row documenting the rejection cannot be written.**
> **(b)** `CandidateWindow` carries no `z/x/y` — only an opaque `WindowRef.key` that ai_engine *"NEVER parses"* and gis was never told to expose. And a 1024px window cropped at an arbitrary offset with overlap **is not addressable by a single (z,x,y) anyway**; `local_orthophoto` and Sentinel scenes are not tiles at all. §4.10's `meta` keys now carry the anchor tile explicitly, as **addressing metadata** — *the transform is the transform*.
> **(c)** Nothing in the pipeline wrote the mosaic to storage, so `satellite_image_path` had **no producer**. `app.tasks.matching` now persists `best.window.rgb` via `ObjectStorage`.
>
> **The CHECK is the honest expression of the real invariant:** *a **selected** result is complete.* A losing candidate is allowed to be a scored rejection and nothing more. `uq_match_results_job_selected` already guarantees at most one selected row per job, so together they say exactly what we mean and the database still enforces it.

Indexes: `uq_match_results_job_rank (match_job_id, rank)` · **`uq_match_results_job_selected (match_job_id) WHERE is_selected`** — at most ONE selected per job, **enforced by the database, not by hope** · `ix_match_results_job_conf (match_job_id, overall_confidence DESC)` · `ix_match_results_tile (provider, tile_z, tile_x, tile_y)` · `ix_match_results_tile_bounds GIST(tile_bounds)` · `ix_match_results_tile_bounds_3857 GIST(tile_bounds_3857) WHERE tile_bounds_3857 IS NOT NULL` · `ix_match_results_score_breakdown GIN(score_breakdown jsonb_path_ops)` · `ix_match_results_parent (parent_match_result_id) WHERE parent_match_result_id IS NOT NULL`.

> **Why store `sat_geotransform` when `(z,x,y)` determines it?** Because `(z,x,y)` determines it **only for a standard 256px Web-Mercator XYZ pyramid**. `local_orthophoto` candidates are not tiles; Sentinel scenes are not tiles; a 512px retina provider is not that pyramid either. Storing the affine explicitly makes the pixel→world chain **self-contained and provider-independent** — which is exactly I4. For XYZ providers `tile_z/x/y` are still populated because they are how we address the cache and how the UI re-fetches the tile for display, but **they are addressing metadata, not the transform. The transform is the transform.**

> **★ And `sat_geotransform_srid` is the column that argument REQUIRED and v1.0 omitted.** The DDL comment said *"Maps MOSAIC PIXEL → EPSG:3857"*, §6.1's wire table hardcoded *"mosaic pixel → EPSG:3857"*, and §5.8's chain and `transform_note` both assumed 3857 — **while** `ProviderCapabilities.native_crs` is documented *"per-file for local ortho"*, `SatelliteChip.crs` is *"EPSG code of geotransform"*, and `CandidateWindow.crs` is an opaque authority string. **`local_orthophoto` — the provider this contract calls HIGHEST ACCURACY, puts first in the fallback chain, and calls "the only path where total error is knowable" — produces UTM geotransforms that the table could not store.** Two designs were stated at once and only one could be true. Adding the SRID is strictly better than the alternative (mandating every provider reproject its chip to 3857 before returning), because **reprojecting an orthophoto resamples it** — throwing away the accuracy that is the entire reason to mount one.

> **Why `tile_bounds_3857` is denormalised.** The MVT endpoint and the candidate-overlap query both want it, and deriving it costs `ST_Transform` on every read. It is written by the **same transaction** from the **same source arithmetic** as `tile_bounds` — it is **not** a re-projection of the 4326 column, so no round-trip error accumulates. **`tile_bounds` remains canonical: if they ever disagree, `tile_bounds` wins.**

> **Why `homography_condition_number` and `homography_determinant` are stored rather than checked-and-discarded.** "Why did the algorithm reject this obviously-correct-looking tile?" is the single most common support question in this class of product. `det(H) <= 0` (reflection) and `cond(H) > 1e7` (near-degenerate) are the two classic failure modes; persisting them makes the answer a `SELECT`.

#### `gcps` — `GCP`  ★ THE DELIVERABLE

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | | |
| `image_id` | UUID FK→`images` **CASCADE** | no | | |
| `landmark_id` | UUID FK→`annotations` **SET NULL** | yes | | |
| `match_result_id` | UUID FK→`match_results` **RESTRICT** | no | | ★ provenance |
| `code` | Text | yes | | `'GCP01'`. `^[A-Za-z0-9_\-]{1,32}$` |
| `pixel_x` / `pixel_y` | F8 | no | | image pixel space |
| `satellite_pixel_x` / `satellite_pixel_y` | F8 | no | | ★ **the FIX location in mosaic pixels**: the direct patch/descriptor fix when `has_direct_fix`, else `H · [pixel_x, pixel_y, 1]` dehomogenised. |
| `has_direct_fix` | Boolean | no | `FALSE` | ★ **NEW.** Makes `residual_px IS NULL` distinguishable from `residual_px = 0`. |
| `geom` | GEOG(POINT) | no | | ★ **THE CANONICAL TRUTH** |
| `elevation_m` | F8 | yes | | `BETWEEN -500 AND 9000` |
| `elevation_source` | Text | yes | | `local_dem\|copernicus_dem\|srtm\|exif\|manual\|null`. ★ `ck_gcps_elevation_source_consistent`: `(elevation_m IS NULL) = (elevation_source IS NULL)` — **the source may never name a producer that did not run** (§4.27). |
| `elevation_ce90_m` | F8 | yes | | ★ **NEW.** Vertical CE90 from `ElevationSample`. `NULL` is honest; `0` would not be. |
| `confidence` | F8 | no | | ★ **0–100** |
| `accuracy_relative_ce90_m` | F8 | **no** | | ★ **NEW.** Our fit, CE90, TRUE metres. |
| `georef_ce90_m` | F8 | **no** | | ★ **now NOT NULL.** The provider's contribution. It is always knowable — `ProviderCapabilities.georef_ce90_m` is mandatory. |
| `accuracy_total_ce90_m` | F8 | **no** | | ★ **NEW.** `sqrt(relative² + georef²)`. **THE headline number.** |
| `accuracy_semi_major_ce90_m` / `accuracy_semi_minor_ce90_m` | F8 | yes | | ★ **NEW.** The error ellipse. |
| `accuracy_azimuth_deg` | F8 | yes | | ★ **NEW.** Major-axis bearing, 0=North, cw. |
| `accuracy_dominant_term` | Text | **no** | | ★ **NEW.** `match\|georeference\|landmark_click\|rectification`. |
| `residual_px` | F8 | yes | | ★ `‖H·image_px − satellite_px‖` for **this** point. **Non-zero only when `has_direct_fix`**; `NULL` otherwise. |
| `manually_adjusted` | Boolean | no | `FALSE` | |
| `original_geom` | GEOG(POINT) | yes | | ★ the algorithm's answer, **kept forever** |
| `original_satellite_pixel_x` / `_y` | F8 | yes | | |
| `original_confidence` | F8 | yes | | |
| `adjustment_offset_m` | F8 | yes | | `ST_Distance(original_geom, geom)` — **real metres** |
| `adjusted_by` | Text | yes | | |
| `adjusted_at` | TSTZ | yes | | |
| `adjustment_note` | Text | yes | | |
| `is_stale` | Boolean | no | `FALSE` | ★ §12 C-26 — **stored**, set by the writer paths |
| `stale_reason` | `gcp_stale_reason` | yes | | |
| `is_included_in_export` | Boolean | no | `TRUE` | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |

Checks: `ck_gcps_confidence` `BETWEEN 0 AND 100` · `ck_gcps_pixel_nonneg` · `ck_gcps_elevation_sane` · `ck_gcps_elevation_source_consistent` · `ck_gcps_accuracy_nonneg` (all five accuracy columns `>= 0`) · `ck_gcps_accuracy_total_ge_parts` (`accuracy_total_ce90_m >= greatest(accuracy_relative_ce90_m, georef_ce90_m)` — a quadrature can never be smaller than either leg, and this catches a unit or sign slip in `combine_accuracy` at write time) · `ck_gcps_residual_iff_direct_fix` (`has_direct_fix OR residual_px IS NULL`) · **`ck_gcps_adjustment_complete`** `NOT manually_adjusted OR (adjusted_at IS NOT NULL AND original_geom IS NOT NULL)` · `ck_gcps_no_adjustment_metadata_unless_adjusted` · `ck_gcps_stale_reason` `(is_stale) = (stale_reason IS NOT NULL)`.

> **★ `horizontal_accuracy_m` is DROPPED from the table.** `GcpRead.accuracy: GcpAccuracy` is **non-optional** and all four of its fields non-null (`relative_m`, `georef_ce90_m`, `total_ce90_m`, `dominant_term`), while the `gcps` table had **only** `horizontal_accuracy_m` (nullable) and `georef_ce90_m` (nullable) — **no column for `relative_m`, none for `total_ce90_m`, none for `dominant_term`.** The frontend renders `accuracy.dominant_term` (*"your accuracy is limited by the basemap, not the match"*) and `format.ts` keys its **precision-truncation honesty mechanism** off `accuracy.total_ce90_m` — **both from data that was never stored.** Every project and image read would have failed validation.
> The wire keeps `horizontal_accuracy_m` (it is in `GcpRead`, `GcpRecord` and the CSV) but it is now **defined as an alias of `accuracy_total_ce90_m`, serialised, never stored.** Two names for one number is exactly the drift §5.6 warns about elsewhere; keeping the *column* would have been the drift.

> **★ `satellite_pixel_x/y` and `residual_px` contradicted each other one row apart.** The columns were defined as *"`H · [pixel_x, pixel_y, 1]` dehomogenised"* and, three rows later, `residual_px` as *"`‖H·image_px − satellite_px‖` for this point"* — **under the first definition `residual_px` is identically 0.** §4.11 resolves it correctly (`GcpPixelFix.residual_px` is *"`‖H*image_xy − direct_fix‖` when a direct fix exists"`, and `window_xy` **is** the direct fix when `has_direct_fix`) — but **IU-16 and IU-19 read the DDL**, and the DDL said the opposite. The column note now matches §4.11, and `has_direct_fix` makes the two cases distinguishable in SQL.

Indexes: `uq_gcps_landmark_match (landmark_id, match_result_id) WHERE landmark_id IS NOT NULL` · `uq_gcps_image_code (image_id, code) WHERE code IS NOT NULL` · `ix_gcps_image` · `ix_gcps_match_result` · `ix_gcps_landmark WHERE landmark_id IS NOT NULL` · **`ix_gcps_geom GIST(geom)`** — the hottest spatial query in the product · `ix_gcps_export (image_id, confidence DESC) WHERE is_included_in_export` · `ix_gcps_adjusted (adjusted_at DESC) WHERE manually_adjusted` · `ix_gcps_stale (image_id) WHERE is_stale`.
Statistics: `ALTER TABLE gcps ALTER COLUMN geom SET STATISTICS 1000` — PostGIS GIST selectivity depends on the sampled geometry histogram, and the default (100) badly misestimates viewport queries on clustered survey data, producing seq scans on the hottest query in the product.

> **The three FK behaviours are each deliberate and each different.**
> `image_id CASCADE` — deleting the photo deletes everything derived from it; there is no meaning left.
> `landmark_id SET NULL` — the surveyor may tidy up annotations after the fact; **the coordinate they already exported must survive**, orphaned but intact. `pixel_x/pixel_y` are copied onto the GCP precisely so it remains self-describing after the landmark is gone.
> **`match_result_id RESTRICT` — this is the load-bearing one.** A GCP is a *claim about the world*; the homography is the *evidence*. Allowing the evidence to be deleted while the claim persists would let LandExplorer emit a coordinate it cannot justify. `RESTRICT` makes destroying evidence an explicit, deliberate act rather than a cascade side effect. It also means the 30-day retention job that prunes losing candidates **does not need to know about GCPs — the FK protects them.**

#### `camera_poses` — `CameraPose`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID PK | no | |
| `image_id` | UUID FK→`images` **CASCADE** | no | |
| `match_result_id` | UUID FK→`match_results` **CASCADE** | yes | NULL for `exif_gps_only`/`manual` |
| `position` | GEOG(POINT) | no | |
| `altitude_m` | F8 | yes | |
| `yaw_deg` | F8 | yes | ★ **0 = North, clockwise, `[0,360)`** |
| `pitch_deg` | F8 | yes | ★ **0 = horizon, + = up, `[-90,90]`** |
| `roll_deg` | F8 | yes | ★ **+ = clockwise, `[-180,180]`** |
| `hfov_deg` / `vfov_deg` | F8 | yes | `> 0 AND < 180` |
| `footprint` | GEOG(POLYGON) | yes | drives the Leaflet view cone |
| `method` | `pose_method` | no | |
| `confidence` | F8 | no | **0–100** |
| `rotation_matrix` | F8[] | yes | 9, row-major, world→camera |
| `intrinsics_k` | F8[] | yes | 9, row-major |
| `intrinsics_source` | Text | yes | `exif\|fov\|vanishing_points\|assumed\|manual` |
| `reproj_error_px` | F8 | yes | |
| `inlier_count` | Integer | yes | |
| `sigma_yaw_deg` / `sigma_pitch_deg` / `sigma_roll_deg` | F8 | yes | ★ honest error bars |
| `is_selected` | Boolean | no | default `FALSE` |
| `created_at` / `updated_at` | TSTZ | no | |

Checks: the four angle-range checks · `ck_camera_poses_fov` · `ck_camera_poses_confidence` · arity checks · **`ck_camera_poses_decomp_needs_k`** — ★ **extended to** `method NOT IN ('zhang_plane','homography_decomposition') OR intrinsics_k IS NOT NULL` (Zhang-plane needs `K` just as much; v1.0's check keyed only off `homography_decomposition`, so the primary path could have written a pose with no intrinsics) · **`ck_camera_poses_method_needs_match`** `method IN ('exif_gps_only','manual') OR match_result_id IS NOT NULL`.

> **★ `yaw_deg` here is 0 = TRUE North.** `PoseResult.yaw_deg` is 0 = **up the window raster**. For a north-up EPSG:3857 window those coincide; for a rotated or UTM window they do **not**, and `gis.pose.window_yaw_to_north_deg()` (§4.28) is the **only** thing permitted to convert. `pose_service` calls it; it never does frame math itself. §13.1 IU-09 asserts a camera facing image-north lands at `yaw_deg == 0` in the DB for the 3857 case, and at a non-zero convergence for a UTM ortho.
Indexes: `uq_camera_poses_image_selected (image_id) WHERE is_selected` · `ix_camera_poses_image (image_id, confidence DESC)` · `ix_camera_poses_position GIST` · `ix_camera_poses_footprint GIST WHERE footprint IS NOT NULL` · `ix_camera_poses_match_result WHERE match_result_id IS NOT NULL`.

> **The angle conventions are written into `CHECK` comments** because yaw/pitch/roll conventions are the classic silent-disagreement bug between a CV module and a map renderer. **The constraint is the documentation that cannot rot.**

#### `confidence_heatmaps` / `confidence_heatmap_cells`

**Vector, not raster. `postgis_raster` is deliberately NOT installed.** (a) It drags GDAL driver configuration into the *database* container and has a real CVE history around out-db rasters — and Docker is not installed here, so that config would be authored blind. (b) The interaction model is **per-cell-with-attributes** (hover → score breakdown tooltip); rasters store scalars in a band and cannot hold per-cell JSONB. (c) Volume is ~10k cells; raster's advantage begins in the tens of millions. (d) Sparsity is free in vector — **absent ≠ score 0**, and `cell_count` vs `grid_cols*grid_rows` makes sparsity queryable. (e) A raster would force storage in 3857, **reintroducing the Mercator distortion §5.2 exists to avoid**.

`confidence_heatmaps`: `id` UUID PK · `match_job_id` UUID FK→`match_jobs` CASCADE **UNIQUE** · `image_id` UUID FK→`images` CASCADE · `bbox` GEOG(POLYGON) NOT NULL · `cell_size_m` F8 NOT NULL (**true metres**) · `grid_cols`/`grid_rows` Integer NOT NULL · `cell_count` Integer NOT NULL DEFAULT 0 · `min_score`/`max_score`/`mean_score` F8 · `argmax_geom` GEOG(POINT) · `argmax_score` F8 · `colormap` Text NOT NULL DEFAULT `'viridis'` · `render_path` Text · `created_at` TSTZ.
Checks: `ck_confidence_heatmaps_grid` · `ck_confidence_heatmaps_cell_size > 0` · `ck_confidence_heatmaps_cell_count <= grid_cols*grid_rows` · `ck_confidence_heatmaps_scores` (0–1, min ≤ max).
Indexes: `uq_confidence_heatmaps_job` · `ix_confidence_heatmaps_image (image_id, created_at DESC)` · `ix_confidence_heatmaps_bbox GIST` · `ix_confidence_heatmaps_argmax GIST WHERE argmax_geom IS NOT NULL`.

`confidence_heatmap_cells`: `id` **BigInteger PK autoincrement** · `heatmap_id` UUID FK CASCADE · `col`/`row` Integer NOT NULL · `geom` GEOG(POINT) NOT NULL (★ **CENTROID only**) · `score` F8 NOT NULL (0–1) · `sample_count` Integer NOT NULL DEFAULT 1 · `components` JSONB NOT NULL DEFAULT `'{}'`.
Indexes: `uq_confidence_heatmap_cells_grid (heatmap_id, col, row)` · `ix_confidence_heatmap_cells_geom GIST` · `ix_confidence_heatmap_cells_heatmap_score (heatmap_id, score DESC)`.

> **Only the centroid is stored.** The cell polygon is `centroid ± cell_size_m/2`, fully determined by the parent. Storing 10 000 five-vertex polygons is ~5× the bytes and ~5× the GIST index **for zero information**. `sample_count` exists because a cell **aggregates** every candidate whose centre fell in it — a cell with `sample_count = 1` is far less trustworthy than one with 12, and the UI dims it accordingly.

#### `semantic_features` — `SemanticFeature`

`id` UUID PK · `image_id` UUID FK CASCADE · `match_result_id` UUID FK CASCADE (set **iff** `space='satellite_geo'`) · `source_annotation_id` UUID FK→`annotations` SET NULL (set **iff** `detector='manual'`) · `class` `semantic_class` · `space` `feature_space` · `detector` `feature_detector` DEFAULT `'classical_cv'` · `model_version` Text · `pixel_geom` GEOM0(GEOMETRY) · `geo_geom` GEOG(GEOMETRY) · `confidence` F8 NOT NULL (**0–1**) · `area_px` F8 · `area_m2` F8 · `length_m` F8 · `attributes` JSONB · `embedding_meta` JSONB · `created_at` TSTZ.

Checks: **`ck_semantic_features_space_xor`** — `(space='image_pixel' AND pixel_geom IS NOT NULL AND geo_geom IS NULL) OR (space='satellite_geo' AND geo_geom IS NOT NULL AND pixel_geom IS NULL)`. **The constraint that makes I1 mechanical for this table.** · `ck_semantic_features_geo_needs_match` · `ck_semantic_features_manual_has_source` · `ck_semantic_features_pixel_srid` `= 0` · `ck_semantic_features_confidence` · `ck_semantic_features_area`.
Indexes: `ix_semantic_features_image_class (image_id, class)` · `ix_semantic_features_pixel_geom GIST WHERE pixel_geom IS NOT NULL` · `ix_semantic_features_geo_geom GIST WHERE geo_geom IS NOT NULL` · `ix_semantic_features_match_result WHERE match_result_id IS NOT NULL` · `ix_semantic_features_attributes GIN(attributes jsonb_path_ops)` · `ix_semantic_features_class_space_conf (class, space, confidence DESC)`.

> **Embeddings are NOT stored in Postgres.** `pgvector` is not in the mandated stack, and DINOv2 descriptors (768-D float32 × thousands of patches) are a poor fit for a row store. They are written as `.npy`/FAISS artifacts and referenced by path in `embedding_meta`. If a future ADR adds `pgvector`, it adds a `vector(768)` column here and backfills from those paths — **the schema does not need to change shape.**

> **This table is entirely optional.** A classical-only run may populate it via `detector='classical_cv'` (Canny/Hough field borders and roads are perfectly achievable with the installed OpenCV 4.13) or leave it empty. Empty → `semantic_similarity_score IS NULL` → renormalised weights → **the system works.** Nothing downstream requires a row here.

#### `landmark_suggestions` — `LandmarkSuggestion`  ★ NEW (§12 C-20)

The API promises this resource; the DB design had no table for it. Suggestions are **not** `annotations` until accepted.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID PK | no | | |
| `image_id` | UUID FK→`images` **CASCADE** | no | | |
| `aux_job_id` | UUID FK→`aux_jobs` **SET NULL** | yes | | which suggest job produced it |
| `kind` | `annotation_kind` | no | `'generic'` | proposed kind |
| `geom_type` | `annotation_geom_type` | no | `'point'` | |
| `pixel_x` / `pixel_y` | F8 | no | | |
| `pixel_geom` | GEOM0(GEOMETRY) | no | | |
| `score` | F8 | no | | **0–1**, the detector's own |
| `rank` | Integer | no | | |
| `detector` | `feature_detector` | no | `'classical_cv'` | |
| `model_version` | Text | yes | | |
| `rationale` | Text | yes | | human-readable "why" |
| `status` | `suggestion_status` | no | `'pending'` | |
| `accepted_annotation_id` | UUID FK→`annotations` **SET NULL** | yes | | set on accept |
| `decided_by` / `decided_at` | Text / TSTZ | yes | | |
| `created_at` / `updated_at` | TSTZ | no | `now()` | |

Checks: `ck_landmark_suggestions_score` `BETWEEN 0 AND 1` · `ck_landmark_suggestions_accepted` `status <> 'accepted' OR accepted_annotation_id IS NOT NULL` · `ck_landmark_suggestions_geom_type_match`.
Indexes: `ix_landmark_suggestions_image_rank (image_id, rank) WHERE status = 'pending'` · `ix_landmark_suggestions_job` · `ix_landmark_suggestions_geom GIST(pixel_geom)`.

> **Why suggestions are a separate resource.** Writing AI guesses straight into `annotations` would put unreviewed machine output into the surveyor's revision history, the undo stack, and — via `is_gcp_candidate` — the GCP deriver. **A suggestion is a proposal; an annotation is an assertion by a human.** The boundary between them is `POST …/accept`, and it is the only door. (ADR-014.)

#### `batch_jobs` / `batch_job_items`

`batch_jobs`: `id` UUID PK · `project_id` UUID FK CASCADE · `celery_group_id` Text · `name` Text · `status` `job_status` DEFAULT `'pending'` · `cancel_requested` Boolean DEFAULT FALSE · `total_items`/`completed_items`/`failed_items` Integer DEFAULT 0 · `progress` F8 DEFAULT 0.0 (0–1) · `provider` `imagery_provider` DEFAULT `'esri_world_imagery'` · `params` JSONB · `concurrency` SmallInteger DEFAULT 4 (`1..64`) · `continue_on_error` Boolean DEFAULT TRUE · `error_message` Text · `requested_by` Text · `started_at`/`finished_at` TSTZ · `created_at`/`updated_at` TSTZ.
Checks: `ck_batch_jobs_progress` · `ck_batch_jobs_counts` `completed_items + failed_items <= total_items` · `ck_batch_jobs_concurrency`.
Indexes: `uq_batch_jobs_celery_group_id WHERE NOT NULL` · `ix_batch_jobs_project_created` · `ix_batch_jobs_status ... WHERE status IN (live)`.

`batch_job_items`: `id` UUID PK · `batch_job_id` UUID FK CASCADE · `image_id` UUID FK CASCADE · `match_job_id` UUID FK→`match_jobs` **SET NULL** · `ordinal` Integer · `status` `job_status` DEFAULT `'pending'` · `error_message` Text · `created_at`/`updated_at` TSTZ.
Indexes: `uq_batch_job_items_batch_image (batch_job_id, image_id)` — ★ prevents the double-click-submit bug **in the database** · `uq_batch_job_items_batch_ordinal` · `ix_batch_job_items_batch_status` · `ix_batch_job_items_image`.

> **The `match_jobs` ↔ `batch_job_items` cycle is deliberate.** The batch progress view scans items and needs the job (one index hit); a worker holding a `match_job` needs to report up to its item without a scan. **Both sides are `ON DELETE SET NULL`, so neither can create a cascade cycle.** Migration `0005` creates both tables *without* the mutual FKs, then adds them with `op.create_foreign_key()` at the end — the standard cycle-breaking pattern.

#### `exports` — `Export`

`id` UUID PK · `project_id` UUID FK CASCADE · `image_id` UUID FK CASCADE (NULL ⇒ whole-project export) · `format` `export_format` · `status` `job_status` DEFAULT `'pending'` · `cancel_requested` Boolean DEFAULT FALSE · `celery_task_id` Text · `storage_path` Text (NULL until succeeded) · `filename` Text · `size_bytes` BigInteger · `checksum_sha256` CHAR(64) · `gcp_count` Integer · `target_srid` Integer NOT NULL DEFAULT 4326 (`1024..32767`) · `options` JSONB · `filter` JSONB · `warnings` JSONB DEFAULT `'[]'` · `error_message` Text · `requested_by` Text · `expires_at` TSTZ · `created_at`/`updated_at` TSTZ.
Checks: `ck_exports_target_srid` · `ck_exports_succeeded_has_path` `status <> 'succeeded' OR (storage_path IS NOT NULL AND size_bytes IS NOT NULL)` · `ck_exports_failed_has_error` · `ck_exports_size`.
Indexes: `uq_exports_celery_task_id WHERE NOT NULL` · `ix_exports_project_created` · `ix_exports_image WHERE NOT NULL` · `ix_exports_status ... WHERE status IN ('pending','queued','running')` · `ix_exports_expires (expires_at) WHERE expires_at IS NOT NULL AND status = 'succeeded'` · `ix_exports_options GIN(options jsonb_path_ops)`.

> **`filter` is persisted** so "regenerate this export" is reproducible — and so a stale export whose `gcp_count` disagrees with today's GCP count is **detectable**, which is exactly the audit question a surveyor asks: *"is the file I sent the client still current?"*

### 5.7 Alembic

`env.py` must configure: `target_metadata = Base.metadata`; the `NAMING_CONVENTION`; `include_object` excluding `spatial_ref_sys`, `geography_columns`, `geometry_columns`, `raster_columns`, `raster_overviews`, `topology`, `layer`; `geoalchemy2.alembic_helpers.{include_name, render_item, writer}`; `compare_type=True`; `compare_server_default=True`; `transaction_per_migration=True`.

**`script.py.mako` MUST emit `import geoalchemy2`** — autogenerated migrations reference `geoalchemy2.types.Geography` and fail at import without it. **This is the single most common PostGIS+Alembic footgun.**

`postgis` is **never dropped** in a downgrade — it owns `spatial_ref_sys`, and dropping it on a database with any spatial column is destructive. Removing PostGIS is a database-lifecycle decision, not a migration.

Enum-label migrations contain **nothing but `ALTER TYPE ... ADD VALUE IF NOT EXISTS`** and are never downgradable (`downgrade()` is a documented `pass`).

### 5.8 Appendix — the canonical coordinate pipeline

**The chain, and the two rules it exists to make unforgettable.**

```
[1] Surveyor clicks the Konva canvas
      ↓  frontend: stageToImage(p) = (p - t) / (s·D)      ← §8.6, the ONLY conversion site
[2] annotations.pixel_geom : geometry(Geometry, 0)         -- y-DOWN, origin top-left
      ↓  ai_engine: SIFT/ORB keypoints in the photo
      ↓  ai_engine: FLANN/BF match against the window's keypoints
      ↓  ai_engine: cv2.findHomography(src=image_pts, dst=window_pts, USAC_MAGSAC)
[3] match_results.homography : float8[9], ROW-MAJOR         -- image px → mosaic px
      ↓  gcps.satellite_pixel_x/y = the DIRECT FIX when has_direct_fix,
      ↓                             else dehomogenize(H @ [pixel_x, pixel_y, 1])
[4] satellite mosaic pixel (u, v)                           ← ★ ai_engine ENDS HERE (L3)
      ↓  match_results.sat_geotransform : float8[6]         ← ★ gis BEGINS HERE
      ↓  ★ PIXEL-CENTRE CONVENTION — the +0.5 is NOT optional (§4.18, §6.1):
      ↓  X = c + a·(u+0.5) + b·(v+0.5) ;  Y = f + d·(u+0.5) + e·(v+0.5)
[5] (X, Y) in match_results.sat_geotransform_srid
      ↓  ★ 3857 for slippy providers; a UTM code for local_orthophoto. NOT hardcoded.
      ↓  gis.crs: Transformer.from_crs(sat_geotransform_srid, 4326, always_xy=True)
[6] EPSG:4326 (lon, lat)
      ↓  ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
[7] gcps.geom : geography(Point, 4326)                      -- ★ CANONICAL TRUTH
      ↓
      ├─→ CSV       : ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
      ├─→ GeoJSON   : ST_AsGeoJSON(geom)                    -- RFC 7946, no reprojection
      ├─→ KML       : ST_AsKML(geom)                        -- WGS84 by spec
      ├─→ Shapefile : GeoPandas .to_crs(exports.target_srid) -- in memory only
      └─→ PDF       : rendered map + coordinate table
```

1. **Steps [3] and [4] are different spaces.** `homography` ends in mosaic **pixels** — not metres, not degrees. Feeding `H` output directly into a 4326 column is the catastrophic bug this schema is shaped to prevent, **and it is prevented**, because `gcps.geom` is `geography(Point,4326)` and no code path can write a pixel pair into it without first passing through `sat_geotransform` and `gis.crs`.
2. **Step [7] is the only truth.** Everything after it is serialisation. Nothing before it is stored as a coordinate. **If an export disagrees with the map, the exporter is wrong, not the database.**

### 5.9 Retention and operations

| Concern | Policy |
|---|---|
| `annotation_versions` | Fastest-growing table. Keep all events < 90 days; older events compacted (force a checkpoint, then delete pre-checkpoint events). Undo depth beyond 90 days is not a product requirement. Autovacuum: raise `autovacuum_vacuum_scale_factor` to 0.2, lower `autovacuum_analyze_scale_factor` to 0.02 (append-only: stats matter, dead tuples don't). |
| `confidence_heatmap_cells` | ~10k rows/job. Cells for jobs > 30 days old whose heatmap is not referenced by a selected pose are deleted; **the parent row is kept forever**, so the map still shows the answer. |
| `match_results` losers | Non-selected candidates > 30 days old are deleted. `RESTRICT` from `gcps` automatically protects any a GCP cites — **the retention job doesn't need to know about GCPs; the FK does.** |
| `match_jobs.progress` | Ticks throttled to ≥ 250 ms apart, written with a plain `UPDATE`, **never inside the CV transaction**. With `fillfactor=70` and no index on `progress`, these are HOT updates that never touch an index. |
| Connection pooling | PgBouncer in **transaction** mode. Consequence: **no session-level state** — no server-side cursors, no `LISTEN/NOTIFY` from the app. **This is why job progress reaches the UI via polling + Redis pub/sub, not `NOTIFY`.** |
| Backups | `pg_dump -Fc` nightly. The restore runbook **must `CREATE EXTENSION postgis` BEFORE `pg_restore`**, or every spatial column fails to restore. |

---

## 6. Exact Pydantic v2 schemas

All under `backend/app/schemas/`. **Every model inherits `ApiModel`:**

```python
# backend/app/schemas/common.py
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",          # ★ a typo'd field is a 422, never a silent no-op
        str_strip_whitespace=True,
        # ★ NO alias_generator. snake_case end to end (L9, §12 C-08).
    )
```

### 6.1 Wire rules (normative)

| Rule | Value |
|---|---|
| Body format | JSON only, except multipart uploads (`POST /images`, `POST /batch`) and binary responses |
| **Field casing** | **snake_case.** No alias generator. (L9) |
| Timestamps | UTC, RFC 3339, always explicit `Z`: `2026-07-17T09:41:22.481Z` |
| Resource ids | UUIDv4 **strings** — **except** `annotation_versions.id`, which is `BIGSERIAL` and is serialised as a JSON **number**. This asymmetry is called out in every schema that touches it. |
| **Nulls — RESPONSES** | **Never omitted.** A nullable field is always present with value `null`. Clients must not distinguish "absent" from "null" in a response — making them identical removes a whole class of TS `undefined` bugs. |
| **Nulls — REQUESTS** | Non-PATCH request bodies follow the same rule. **PATCH bodies are the ONE exception and DO distinguish absent from null** (`UNSET` semantics): `{"aoi": null}` **clears**, `{}` leaves untouched. ★ v1.0 stated the response rule as absolute (*"Clients must not distinguish absent from null"*) and then specified `ProjectUpdate` with UNSET-sentinel semantics **and an IU-17 test asserting `{}` and `{"aoi": null}` are distinguishable** — a direct contradiction. Both rules are right for their own direction: a response with a hole is a client bug generator; a PATCH without UNSET **cannot clear a nullable field**, which is a real and common bug. Scoping the rule keeps both. TS side: `ProjectUpdate` fields are `T \| null \| undefined`, and the client **omits the key** (via `JSON.stringify`) for "leave untouched" — never sends `null` for it. |
| Collections | **Never a bare list.** Always `Page[T]`. A bare top-level JSON array is a hijacking footgun and makes adding pagination a breaking change. |
| Naming | `XxxCreate` (POST) · `XxxUpdate` (PATCH, all optional) · `XxxRead` (full) · `XxxSummary` (list projection) · `XxxListParams` (query dependency) |
| `operation_id` | `{tag}_{action}` — so the generated TS reads `api.images.upload(...)` not `api.uploadImagesApiV1ImagesPost(...)`. Asserted unique at startup. |
| OpenAPI | 3.1 (Pydantic v2 emits it natively — **do not downgrade to 3.0**, which cannot express `null` unions correctly) |

**Coordinate and unit conventions — load-bearing:**

| Concept | Convention | Field names |
|---|---|---|
| Image pixel space | `(x, y)`, origin **top-left**, y-**down**, floats (sub-pixel), SRID 0 | `pixel_x`, `pixel_y`, `image_px` |
| Satellite mosaic pixel | `(u, v)`, origin top-left of the candidate mosaic, y-down | `satellite_px` |
| **★ Pixel coordinate meaning** | **An integer coordinate is the pixel CENTRE** (the OpenCV/SIFT convention, and what every keypoint we produce means). **GDAL geotransform columns are pixel EDGES.** The bridge is `col_gdal = u_cv + 0.5`, applied in `pixel_to_lonlat` and in §5.8's chain. **Stated here once; §4.18 implements it; nothing else may re-decide it.** | — |
| World | **EPSG:4326** decimal degrees; `lat` then `lon` in objects, but **`[lon, lat]` inside any GeoJSON** (RFC 7946 mandates x,y) | `lat`, `lon` |
| **★ `vec(H)` ordering** | **ROW-MAJOR everywhere — `H`, `Σ_H`, `A_h`, the DB, the API.** §4.24(1). | `homography` |
| Homography | 9 floats, **row-major**, image pixel → satellite mosaic pixel | `homography` |
| Geotransform | 6 floats, **GDAL order** `[c,a,b,f,d,e]`, mosaic pixel → **the CRS named by `sat_geotransform_srid`** (3857 for slippy providers, a UTM code for `local_orthophoto`) | `sat_geotransform`, `sat_geotransform_srid` |
| Distances | metres, suffix `_m`. **★ Always TRUE ground metres, never projected metres.** | `radius_m`, `elevation_m` |
| **★ Accuracy confidence level** | **CE90, always.** Every `*_ce90_m` field is a 2-D 90% radius (`2.146σ`). No field mixes levels; `GcpAccuracy.confidence_level` states it on the wire. §4.20. | `*_ce90_m` |
| Angles | degrees, suffix `_deg`. **★ Orientation angles are 0 = TRUE North, clockwise, at the API and DB.** (`PoseResult.yaw_deg` is window-frame; `gis.pose` converts. §4.28.) | `yaw_deg`, `azimuth_deg` |
| **★ `estimator`** | On the wire and in the DB, `estimator` **always means the robust-fit METHOD** (`RansacConfig.method` / `HomographyMethod`) — `ransac\|usac_magsac\|lmeds\|prosac\|usac_accurate\|lsq`. It is **never** a component registry key and **never** reaches `Registry.resolve`. The registry key is `AiEngineConfig.estimator_backend` and is not exposed. §4.7. | `estimator`, `estimator_used`, `default_estimator` |
| **Match/GCP confidence** | **0–100** float | `confidence`, `overall_confidence` |
| **Annotation confidence** | **0–1** float — the *surveyor's own certainty*, a different quantity | `annotations.confidence` |

> **The two confidence scales are deliberate and MUST NOT be unified.** `gcps.confidence` (0–100) is an algorithmic score the pipeline computes. `annotations.confidence` (0–1) is a human assertion typed into the annotation tool. They mean different things, are produced by different actors, and are **never compared**. The DB enforces both ranges with CHECK constraints. **Any client rendering a "confidence" bar must read the field's scale from this table, not guess.**

### 6.2 Schema catalogue (18 modules)

Import direction is strictly one-way: `common` / `enums` / `errors` ← everything else. **No schema module imports another domain schema module.** This keeps the graph acyclic and lets any schema be imported into a Celery worker without dragging in FastAPI.

#### `common.py`
`ApiModel` · `Page[ItemT]` · `PaginationParams` · `SortParams` · `WarningItem` · `LatLon` · `LatLonAlt` · `PixelXY` · `PixelBox` · `BBox` · `GeoJsonGeometry` · `GeoJsonPoint` · `GeoJsonLineString` · `GeoJsonPolygon` · `GeoJsonFeature` · `GeoJsonFeatureCollection` · `ResultRef` · **`RevisionSummary`** · `Unset` · `UNSET` · `IdResponse` · `DeletedResponse` · `CountResponse`

```python
ItemT = TypeVar("ItemT")


class Page(ApiModel, Generic[ItemT]):
    """★ Inherits ApiModel, not BaseModel. §6 says in bold "Every model inherits ApiModel"
    and v1.0 then defined `Page(BaseModel, Generic[ItemT])` — so Page alone lacked
    extra="forbid", from_attributes=True and str_strip_whitespace, and IU-17's mandated
    introspection sweep ("every model sets extra='forbid'") failed on it. Pydantic v2
    supports generic models on any BaseModel subclass; the ConfigDict is inherited."""
    items: list[ItemT]
    total: int          # exact count matching the filter, ignoring limit/offset
    limit: int
    offset: int
    has_more: bool      # offset + len(items) < total

    @classmethod
    def of(cls, items: Sequence[ItemT], total: int, p: "PaginationParams") -> "Page[ItemT]": ...


class PaginationParams(ApiModel):
    limit: int = 50     # 1..200. Out of range -> 422, NEVER silently clamped:
                        # silent clamping makes clients believe they read everything.
    offset: int = 0     # >= 0


class SortParams(ApiModel):
    raw: str | None = None

    def parse(self, allowed: frozenset[str], default: str) -> list[tuple[str, Literal["asc", "desc"]]]: ...


class WarningItem(ApiModel):
    """★ The NON-ERROR channel. A missing SuperGlue weight is a successful match with a note."""
    code: str            # SCREAMING_SNAKE, e.g. MODEL_WEIGHTS_MISSING
    message: str
    field: str | None = None
    requested: str | None = None
    effective: str | None = None


class LatLon(ApiModel):
    lat: float           # [-90, 90]
    lon: float           # [-180, 180]


class PixelXY(ApiModel):
    x: float
    y: float


class BBox(ApiModel):
    """Wire form is the CSV string "minlon,minlat,maxlon,maxlat"; parsed to this."""
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


class ResultRef(ApiModel):
    kind: str            # "match_result" | "export" | "batch" | "semantic_features" | "suggestions"
    id: str


class RevisionSummary(ApiModel):
    """★ MOVED HERE from revision.py. It is a shared value object: annotation.py's
    AnnotationBulkUpsertResponse.revision needs it, and endpoint 45 (suggestions.py) returns
    that same response.

    §6.2 states "Import direction is strictly one-way: common/enums/errors <- everything
    else. No schema module imports another domain schema module." v1.0 then put
    RevisionSummary in revision.py and referenced it from annotation.py — violating the rule
    on the first cross-reference. (§8.2's TS table independently put RevisionSummary/
    RevisionRead inside annotation.ts, contradicting the Python split — so the frontend had
    already voted for this placement.)

    Moving it to common.py keeps the acyclic rule TRUE rather than exempted. RevisionRead —
    the fat one, with snapshot/events/diff_summary — stays in revision.py; nothing outside
    revisions needs it."""
    id: UUID
    project_id: UUID
    seq: int
    label: str | None
    is_checkpoint: bool
    annotation_count: int
    created_at: datetime


class MetaField(ApiModel):
    """★ NOT a model — a documentation anchor for the `metadata` alias rule below."""
```

> **★ The `metadata` field would have failed validation on every project and image read.** `ApiModel` sets `from_attributes=True`, and `ProjectCreate`/`ProjectRead`/`ImageRead` all declare a field literally named `metadata: dict[str, Any]`. But §5.6 states the ORM **attribute** is `meta` and only the **column** is `metadata` (because `metadata` is reserved on `DeclarativeBase`). So `ProjectRead.model_validate(project_orm)` does `getattr(project, "metadata")` and receives **SQLAlchemy's `MetaData` object**, not the JSONB dict.
>
> **The single, deliberate exemption** — declared on exactly these three schemas and nowhere else:
>
> ```python
> from pydantic import AliasChoices, Field
>
> metadata: dict[str, Any] = Field(
>     default_factory=dict,
>     validation_alias=AliasChoices("meta", "metadata"),   # ORM attr `meta`, wire key `metadata`
>     serialization_alias="metadata",                      # the wire name never changes
> )
> ```
>
> **L9 forbids an alias GENERATOR, not a single deliberate alias** — and the distinction is the point: a generator renames every field invisibly and creates a second source of truth; this names one field, once, at the one place a Python-reserved word forced our hand. IU-17 asserts `ProjectRead.model_validate(project_orm).metadata == project_orm.meta`.

**`Page` is parameterised per route** (`response_model=Page[ImageSummary]`), producing a distinct named OpenAPI component `Page_ImageSummary_` and therefore a clean generated TS type.

> **Offset, not cursor.** Cursor pagination is strictly better for large, hot, append-heavy collections. LandExplorer has none: a project holds tens of images; an image holds tens to low-hundreds of annotations; a match produces ≤ 25 results. The largest realistic collection is `annotation_versions` for a heavily-edited image — low thousands. Offset over a `(image_id, id DESC)` index at those cardinalities is free, and `total` is what the UI actually renders ("1,274 events"). Cursor pagination cannot cheaply produce `total`.
> **The one exception, documented not hidden:** `GET /images/{id}/annotation-versions` also accepts `before_id` (int), switching to keyset mode for the undo stack's infinite scroll where `offset` would skip events as new ones land. `offset` + `before_id` together → `422 PARAM_CONFLICT`.

**Sorting:** `?sort=` is a comma-separated list, leading `-` = descending, max 3 keys, per-endpoint whitelist (`422 INVALID_SORT_FIELD` with the allowed set in `details`). **Every sort is stabilised** — the server silently appends `id ASC` as the final tiebreaker. Without this, offset pagination over equal-valued rows (40 GCPs all at `confidence = 100`) duplicates and drops rows across pages. Invisible to the client and always applied.

**Filtering grammar:** `field=value` (eq) · `field=v1,v2` (IN) · `field__gte`/`__lte`/`__gt`/`__lt` · `q=` (free text) · `bbox=minlon,minlat,maxlon,maxlat` · `include_deleted=`. **Unknown query param → `422 UNKNOWN_QUERY_PARAM`, never ignored** (`extra="forbid"` on `*ListParams`) — *a typo'd filter that silently returns unfiltered data is how a surveyor exports the wrong parcel.* Multiple filters AND. There is no OR. Antimeridian-crossing bboxes → `422 BBOX_CROSSES_ANTIMERIDIAN` rather than silently mishandled.

#### `enums.py` (30)
`JobStatus` · `JobType` · `JobStage` · `ProviderName` · `ExtractorName` · `MatcherName` · `EstimatorName` · `FeatureDetectorName` · `AnnotationKind` · `AnnotationGeomType` · `AnnotationOp` · `SemanticClass` · `FeatureSpace` · `SegmentBackend` · `PoseMethod` · `ExportFormat` · `ImageStatus` · `GcpStaleReason` · `SuggestionStatus` · `SuggestionStrategy` · `BatchOnError` · `HealthStatus` · `ComponentStatus` · `ThumbnailSize` · `ImageFormat` · `HeatmapFormat` · `Colormap` · `ViewRegime` · `QualityFlag` · `CoordinateFormat`

★ Values are **identical** to the PG enums (§5.3). `backend/app/tests/unit/test_enum_parity.py` asserts `schemas.enums.X` and `models.enums.X` agree member-for-member.

#### `errors.py`
`ErrorEnvelope` · `ErrorBody` · `ErrorDetail`

```python
class ErrorDetail(ApiModel):
    loc: list[str | int]
    msg: str
    type: str
    input: Any | None = None


class ErrorBody(ApiModel):
    code: str                          # ★ STABLE, machine-readable, SCREAMING_SNAKE.
                                       #   The client switches on this. Never localise.
    message: str                       # human, English, safe to display. NEVER SQL, stack
                                       #   frames, file paths, or provider keys.
    status: int                        # mirrors HTTP. Duplicated in-body deliberately:
                                       #   it survives logging, proxies, and client libs.
    details: list[ErrorDetail] | None = None
    request_id: str                    # ULID. Also the X-Request-ID header. The string a
                                       #   user pastes into a bug report.
    timestamp: datetime
    docs_url: str | None = None


class ErrorEnvelope(ApiModel):
    error: ErrorBody
```

**Every** non-2xx response has this exact shape, including FastAPI's own `RequestValidationError` and unhandled exceptions. `ErrorEnvelope` is registered via a shared `COMMON_ERROR_RESPONSES` dict on **every** route, so `openapi.json` documents it everywhere rather than on a lucky few. **A missing 404 in the spec becomes an untyped `any` in the generated client.**

**The single explicit exception:** `GET /health/ready` returns `ReadinessResponse` on 503, not `ErrorEnvelope` — a probe wants the check detail, and that response is not an application error.

#### `health.py`
`HealthResponse` · `ReadinessResponse` · `ComponentHealth`

#### `capabilities.py`
`CapabilitiesResponse` · `CapabilityItem` · `ExportCapability` · `ComputeInfo` · `LimitsInfo` · `DefaultsInfo`

```python
class CapabilityItem(ApiModel):
    name: str
    available: bool
    kind: Literal["classical", "deep"]
    requires_weights: bool
    reason: str | None = None      # "Weights not found at /models/superpoint_v1.pth"
    fallback: str | None = None    # what you WILL get if you pick this anyway
```

> `available: false` **never** means "you may not request it". The API accepts `matcher: "superglue"` on a weightless box and returns a job that warns and falls back. It means *"if you pick this, you will get `fallback` instead."* The frontend renders such options disabled with `reason` as the tooltip.

#### `project.py`
`ProjectCreate` · `ProjectUpdate` · `ProjectRead` · `ProjectSummary` · `ProjectCounts` · `ProjectListParams`

`ProjectCreate`: `name: str` (1–200, non-blank after strip) · `description: str | None` (≤4000) · `aoi: GeoJsonPolygon | None` (RFC 7946, 4326, `[lon,lat]`, ≤1000 vertices, `ST_IsValid`, area ≤ 10 000 km²) · `default_provider: ProviderName = esri_world_imagery` · `default_extractor: ExtractorName = sift` · `default_matcher: MatcherName = flann` · `default_estimator: EstimatorName = usac_magsac` · `default_search_radius_m: float = 1000` (10..50000) · `default_search_zoom: int = 18` (10..21) · `tags: list[str] = []` (≤20, each ≤50) · `metadata: dict[str, Any] = {}` (≤16 KB serialised)

`ProjectRead`: all of the above + `id` · `aoi_area_km2: float | None` · `current_revision_seq: int` · `counts: ProjectCounts | None` · `created_at` · `updated_at` · `deleted_at`
`ProjectCounts`: `images: int` · `annotations: int` · `gcps: int` · `match_jobs: int` · `exports: int`
`ProjectSummary`: `id` · `name` · `description` · `tags` · `aoi_area_km2` · `image_count` · `created_at` · `updated_at`

> `ProjectSummary` deliberately **omits `aoi` and `counts`**: a 1000-vertex polygon × 50 rows is a ~2 MB list response for a screen that renders names, and the full rollup costs 5 aggregate subqueries per row. `image_count` alone is kept (one cheap correlated count).

`ProjectUpdate`: every `ProjectCreate` field, all optional, **`UNSET`-sentinel semantics** — `{"aoi": null}` **clears** the AOI, `{}` leaves it untouched and is `400 EMPTY_PATCH`. *Without the sentinel, nullable fields are un-clearable through PATCH — a real, common bug.*

#### `image.py`
`ImageUploadForm` · `ImageUploadAccepted` · `ImageUpdate` · `ImageRead` · `ImageSummary` · `ImageCounts` · `ImageUrls` · `ImageVariant` · `ImageListParams` · `ImageMetadataRead` · `FileMetadata` · `RasterMetadata` · `GpsMetadata` · `CameraMetadata` · `GeoTiffMetadata` · `CaptureMetadata` · `DerivedMetadata` · `LatestMatchRef` · `ThumbnailParams`

```python
class ImageVariant(ApiModel):
    """★ §12 C-36. THE frontend's load-bearing requirement: without original_width the
    client cannot compute D = variant_width/original_width, and the entire coordinate
    model collapses (§8.6). PRESENT ON EVERY VARIANT, NON-NULL, ALWAYS."""
    name: Literal["thumbnail", "preview", "full", "original"]
    url: str
    width: int              # this variant's raster width
    height: int
    original_width: int     # ★ ALWAYS the full-resolution width. Never null.
    original_height: int    # ★ ALWAYS the full-resolution height. Never null.
    display_scale: float    # ★ = width / original_width. Server-computed. THE `D` of §8.6.
    size_bytes: int | None = None


class GpsMetadata(ApiModel):
    lat: float
    lon: float
    altitude_m: float | None
    direction_deg: float | None
    hpe_m: float | None
    source: Literal["exif", "manual"]


class CameraMetadata(ApiModel):
    make: str | None
    model: str | None
    lens_model: str | None
    focal_length_mm: float | None
    focal_length_35mm: float | None
    sensor_width_mm: float | None
    f_number: float | None


class ImageRead(ApiModel):
    id: UUID
    project_id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    width: int                     # ★ POST orientation normalisation
    height: int
    band_count: int
    status: ImageStatus            # uploaded | processing | ready | failed
    is_geotiff: bool
    gps: GpsMetadata | None        # null when no GPS at all
    camera: CameraMetadata
    captured_at: datetime | None
    notes: str | None
    metadata: dict[str, Any]
    urls: ImageUrls
    variants: list[ImageVariant]   # ★ REQUIRED
    counts: ImageCounts
    latest_match: LatestMatchRef | None
    warnings: list[WarningItem]
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
```

- **`storage_path` is NEVER serialised.** It is a server-controlled filesystem/S3 path; exposing it invites path-traversal probing and leaks the storage layout. Clients get `urls.file`.
- **`exif` (the verbatim blob) is NOT in `ImageRead`** — hundreds of tags including embedded thumbnails. It lives at `/metadata`.
- **Upload constraints:** max body **500 MB** (`LE_UPLOAD_MAX_BYTES`, §12 C-06) · max decoded pixels 400 MP · max dimension 65535 px/side · MIME `image/jpeg|png|tiff|webp`.
- **MIME is determined by magic bytes, never by the client.** The part header and the filename extension are both untrusted and recorded only as advisory metadata. Sniff 32 bytes, then confirm by opening with GDAL. `application/octet-stream` is accepted at the header level and resolved by sniffing — browsers and `curl` both send it for `.tif`.
- **GeoTIFF has no distinct MIME.** `image/tiff` covers both. `is_geotiff` is `true` **iff** GDAL reports a non-null projection **and** a geotransform that is **not** the identity `(0,1,0,0,0,1)`. *That second condition matters — GDAL hands back the identity transform for plain TIFFs, and a naive `if gt:` marks every scanned TIFF as georeferenced at the equator.*
- **Streaming, not buffering.** 1 MB chunks with a running SHA-256 and byte count, checked **during** the stream. `await file.read()` into memory lets 8 concurrent 500 MB uploads OOM the container.
- **EXIF orientation is normalised at ingest** and `width`/`height` stored **post-rotation**. If it were not, Konva, OpenCV `imread`, GDAL and the PDF exporter would each independently re-apply the tag — **and they do not agree with each other**, so annotation pixel coordinates would mean different things in different components, corrupting GCP output. The original EXIF block is preserved verbatim in `images.exif` (including the original `Orientation`), so nothing is lost.
- **Async ingest** above `LE_ASYNC_INGEST_THRESHOLD_BYTES` (50 MB): row inserted `status='processing'`, `ingest` aux job enqueued, response `202 ImageUploadAccepted = {image: ImageRead, job: JobRead}`.

#### `annotation.py`
`AnnotationCreate` · `AnnotationUpdate` · `AnnotationRead` · `AnnotationSummary` · `AnnotationListParams` · `AnnotationBulkUpsertRequest` · `AnnotationBulkUpsertItem` · `AnnotationBulkUpsertResponse` · `AnnotationBulkUpsertResultItem` · `AnnotationApplyCounts` · `AnnotationStyle`

```python
class AnnotationRead(ApiModel):
    id: UUID
    image_id: UUID
    kind: AnnotationKind
    geom_type: AnnotationGeomType
    pixel_x: float                 # representative point; == the point for geom_type=point
    pixel_y: float
    geometry: GeoJsonGeometry      # ★ GeoJSON-SHAPED but IMAGE PIXELS, [x, y], y-down, SRID 0
    label: str | None
    description: str | None
    confidence: float              # ★ 0-1, the SURVEYOR'S certainty
    ordering: int
    style: dict[str, Any]
    attributes: dict[str, Any]
    version_no: int                # -> ETag
    revision_seq: int
    is_deleted: bool
    is_gcp_candidate: bool
        # ★ derived: kind in {field_corner, road_intersection, building_corner}.
        #   ★ THE `geom_type == point` CLAUSE IS DELETED. §5.6's entire justification for
        #     NOT NULL pixel_x/pixel_y on polygons is "what makes 'a polygon corner can be a
        #     GCP' work", and gcps.landmark_id -> annotations.id is FK'd to the GENERAL table
        #     for that reason. With `geom_type == point` required, NO polygon could ever be a
        #     GCP candidate and the representative-point columns had NO consumer — two
        #     sections arguing opposite designs. The representative point IS the candidate
        #     location for any geometry type; that is what it is for.
    gcp_ids: list[UUID]
        # ★ WAS `gcp_id: UUID | None` — a SCALAR over a ONE-TO-MANY.
        #   uq_gcps_landmark_match (landmark_id, match_result_id) explicitly permits one GCP
        #   per landmark PER MATCH RESULT, losing candidates are kept, and a recompute writes
        #   a NEW match_results row (parent_match_result_id). So an annotation COMMONLY has
        #   several GCPs, and `gcp_id` had no defined answer: the repository would have picked
        #   arbitrarily and the canvas would have linked to a stale candidate.
        #   Ordered by match_results.rank ASC. Empty list when none.
    gcp_id: UUID | None
        # ★ KEPT, and now DEFINED: the GCP whose match_result has is_selected = TRUE, else
        #   null. It is what the canvas link actually wants. repositories/annotations.py joins
        #   gcps -> match_results ON is_selected. Two fields because there are genuinely two
        #   questions ("which one is live?" and "what else exists?") and v1.0 answered the
        #   first ambiguously and the second not at all.
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime
```

> **`geometry` is GeoJSON-*shaped* but is NOT geographic.** `coordinates` are **image pixels**, `[x, y]`, y-down, SRID 0 — **not `[lon, lat]`**. The shape is already understood by every client library and by Konva's serializer, while the CRS is unambiguously declared by the resource being image-scoped. **To make the trap impossible to fall into, the API REJECTS any `crs` member on input (`422 ANNOTATION_GEOMETRY_INVALID`) and never emits one.** A reader must not feed this into Leaflet expecting degrees.

Validation on every write (mirrors the DDL CHECKs so a violation is a clean 422, not a `23514`): `geom_type` matches `geometry.type` · polyline ≥ 2 pts · polygon exterior ring ≥ 4 pts and closed · `ST_IsValid` · 2D only · all coords within `[0, width] × [0, height]` (`422 ANNOTATION_OUT_OF_BOUNDS`) · `confidence ∈ [0,1]` · ≤ `LE_MAX_ANNOTATIONS_PER_IMAGE` (2000) · ≤ 10 000 vertices.

`AnnotationBulkUpsertRequest`: `mode: Literal["merge","replace"] = "merge"` · `base_revision_seq: int | None` · `revision_label: str | None` · `client_op_id: str | None` · `items: list[AnnotationBulkUpsertItem]` (1–2000).
`AnnotationBulkUpsertItem`: `id: UUID | None` (must be null for `create`) · `op: AnnotationOp` · `version_no: int | None` (required for update/delete/restore) · `client_ref: str | None` (temp id echoed back so the store can swap `tmp-17` → the real UUID) · all `AnnotationCreate` fields optional.
`AnnotationBulkUpsertResponse`: `revision` · `applied: AnnotationApplyCounts` · `items: list[AnnotationBulkUpsertResultItem]` · `annotations: list[AnnotationRead]` (**the full resulting live set**) · `warnings`.

> **`PUT` on the collection is correct here.** The request declares the desired state of the image's annotation set; it is idempotent. Six separate PATCHes would produce six revisions (making undo useless), six round trips, and a partially-saved canvas if the fourth fails.
> **Atomicity: all-or-nothing.** One transaction, `SELECT … FOR UPDATE` on the project row (which also serialises `current_revision_seq` allocation). **A partial save on a survey annotation set is worse than no save: the surveyor believes the canvas matches the database when it does not.**
> **Returning the full resulting set** costs one query and removes an entire class of desync — the client replaces its store wholesale instead of reconciling deltas.
> **`status: "unchanged"`** is returned when an update is byte-identical to current state, and **no revision event is written**. Without this, an idle canvas auto-saving every 30 s inflates the undo stack with thousands of no-op events.

#### `revision.py`
`RevisionCreate` · `RevisionRead` · `RevisionSummary` · `RevisionListParams` · `RevisionSnapshot` · `RevisionDiffSummary` · `RevisionRestoreRequest` · `RevisionRestoreResponse` · `AnnotationVersionRead` · `AnnotationVersionSummary` · `AnnotationVersionChangeSummary` · `AnnotationVersionListParams`

`RevisionRead` adds `snapshot: RevisionSnapshot | None` · `snapshot_source: Literal["stored","replayed"]` · `events: list[AnnotationVersionSummary]` · `diff_summary: RevisionDiffSummary` · `restorable: bool`.

> `snapshot_source` **tells the truth about cost**: `stored` = read straight from `project_revisions.snapshot`; `replayed` = materialised from the nearest preceding checkpoint. Replay is capped at `LE_MAX_REPLAY_EVENTS` (5000) → `422 REVISION_REPLAY_TOO_EXPENSIVE` with `details.nearest_checkpoint_seq`. **A history endpoint that can spin for 40 s is a DoS on your own database.**

`AnnotationVersionSummary`: **`id: int`** (★ a JSON **number**) · `annotation_id: UUID` · `image_id: UUID` · `revision_id: UUID | None` · `op: AnnotationOp` · `version_no: int` · `actor_id: str | None` · `client_op_id: str | None` · `created_at` · `summary: AnnotationVersionChangeSummary` · `before: dict | None` · `after: dict | None` (both null unless `include_payloads=true`).
`AnnotationVersionRead` always includes `before`/`after` in full, plus `diff` (RFC 6902 JSON Patch) and `pixel_geom_after` as GeoJSON. **Per the DDL CHECK: `before` is null iff `op='create'`; `after` is null iff `op='delete'`.** The invariant is stated in the OpenAPI description so client code can rely on it.

> **Restore is forward-only.** It computes the delta from current state to the target and applies it as a **new** revision, emitting normal events. So a restore is itself undoable. Rewinding `current_revision_seq` — the obvious alternative — would orphan every event above it and make the log lie. **An append-only log that gets rewound is not an audit log.**
> **Restore never touches GCPs**, only annotations. It warns `GCPS_NOW_STALE` and leaves them.

#### `matching.py`
`MatchRequest` · `SearchHint` · `MatchOptions` · `ScoreWeights` · `MatchResultRead` · `MatchResultSummary` · `MatchResultListParams` · `MatchTileRef` · `MatchStats` · `MatchScores` · `MatchResultSelectRequest` · `SatelliteImageParams`

```python
class SearchHint(ApiModel):
    center: LatLon | None = None
    radius_m: float = 1000.0        # ★ 50..50000 -> else 422. Above 50 km the tile count is
                                    #   absurd at any useful zoom.
    zoom_levels: list[int] | None = None   # 1-3 entries, each within provider min..max
                                           #   -> else 422 ZOOM_OUT_OF_RANGE. Sorted+deduped.
    use_image_gps: bool = True
    aoi: GeoJsonPolygon | None = None      # valid, <=1000 vertices, area <= 2500 km2


class MatchOptions(ApiModel):
    max_tiles: int = 256            # 1..1024
    max_candidates: int = 25        # ★ §12 C-38
    min_confidence: float = 40.0    # ★ 0..100, §12 C-14. Candidates below are dropped.
    ratio_test: float = 0.75
    cross_check: bool = True
    ransac_threshold_px: float = 3.0    # ★ §12 C-15
    ransac_max_iters: int = 10_000
    ransac_confidence: float = 0.999
    min_inliers: int = 12           # ★ §12 C-16
    max_keypoints: int = 8000
    window_size_px: int = 1024
    overlap_ratio: float = 0.5      # ★ 0.5 — the 512px footprint guarantee (§4.19)
    seed: int | None = 42           # ★ pins RANSAC's RNG -> bit-reproducible
    timeout_s: int = 600
        # ★ 30 .. LE_CELERY_TASK_SOFT_TIME_LIMIT (default 600). Validated in the pre-flight
        #   ladder; over the cap -> 422 with details.max_timeout_s.
        #
        #   ★ v1.0 accepted `timeout_s: int = 900  # 30..3600` against
        #     LE_CELERY_TASK_SOFT_TIME_LIMIT=600 / LE_CELERY_TASK_TIME_LIMIT=900. So a
        #     client's ACCEPTED timeout_s=900 was killed at 600 s with error.code=TIMEOUT,
        #     and timeout_s=3600 validated as legal but was UNREACHABLE — the API accepting
        #     a promise the worker cannot keep. Validating against the real ceiling is the
        #     honest half of the fix; the other half is that the ceiling is now a Settings
        #     value the validator reads, so raising the worker's limit raises the API's in
        #     the same breath.


class ScoreWeights(ApiModel):
    feature: float = 0.25           # ★ §12 C-13
    geometric: float = 0.35
    landmark: float = 0.30
    semantic: float = 0.10
    # keys fixed, values >= 0, MUST sum to 1.0 +/- 1e-6 -> else 422


class MatchRequest(ApiModel):
    search_hint: SearchHint = SearchHint()
    provider: ProviderName | None = None      # project default
    extractor: ExtractorName | None = None    # any enum value accepted, incl. unavailable
    matcher: MatcherName | None = None        #   ones (-> warn + fallback, never an error)
    estimator: EstimatorName | None = None
    use_semantic: bool = False
    annotation_revision_seq: int | None = None   # pins the annotation set matched against
    annotation_ids: list[UUID] | None = None     # subset to match against
    options: MatchOptions = MatchOptions()
    score_weights: ScoreWeights = ScoreWeights()
```

**`SearchHint` resolution order — normative** (first that yields a geometry wins; recorded in `match_jobs.search_aoi` and echoed in the response): `aoi` → `center + radius_m` → `use_image_gps` + `exif_gps` → `use_image_gps` + GeoTIFF `bounds` → project `aoi` → **`422 SEARCH_HINT_REQUIRED`**.

> **Never a global search.** A worldwide SIFT search is not a slow feature; it is a nonexistent one — 2¹⁸² ≈ 6.87×10¹⁰ tiles ≈ 1 PB per photo. There is no budget in which it terminates.

**Pre-flight validation, all synchronous** (a job that dies in 3 s on a checkable condition is a worse UX than a 422 now):

| Check | Failure |
|---|---|
| image exists, not soft-deleted | `404 IMAGE_NOT_FOUND` |
| `image.status == 'ready'` | `409 IMAGE_STILL_PROCESSING` |
| ≥ 1 live annotation (or `annotation_ids` non-empty and resolvable) | `422 NO_ANNOTATIONS` |
| hint resolves | `422 SEARCH_HINT_REQUIRED` |
| provider configured | `503 PROVIDER_NOT_CONFIGURED` |
| provider allowed by ToS policy | `403 PROVIDER_TOS_FORBIDDEN` |
| zooms within provider range | `422 ZOOM_OUT_OF_RANGE` |
| estimated tiles ≤ `max_tiles` | `422 SEARCH_AREA_TOO_LARGE` (`details`: `estimated_tiles`, `max_tiles`, `suggested_zoom`) |
| `options.timeout_s` ≤ `LE_CELERY_TASK_SOFT_TIME_LIMIT` | `422 TIMEOUT_EXCEEDS_LIMIT` (`details.max_timeout_s`) |
| ≥ 1 Celery worker alive (cached 10 s) | `503 WORKER_UNAVAILABLE` |
| no active match for this image unless `force=true` | `409 MATCH_JOB_ALREADY_RUNNING` (`details.job_id`) |

> `NO_ANNOTATIONS` is a 422, **not** a permissive "match on raw features anyway". The product's premise is that the surveyor marks landmarks and the system locates *those*. A match with zero landmarks can estimate a homography but cannot produce a single GCP — the deliverable — so it is **a job whose successful completion is worthless.** Rejecting it up front is honest.

`MatchResultRead`: `id` · `match_job_id` · `image_id` · `rank` · `is_selected` · `parent_match_result_id` · `provider` · `tile: MatchTileRef | None` · `tile_bounds: GeoJsonPolygon` · `center: LatLon` · `satellite_image_url: str | None` · `satellite_checksum` · `satellite_size_px` · `gsd_m` · `georef_ce90_m` · `is_authoritative` · **`homography: list[float] | None`** (9) · **`sat_geotransform: list[float] | None`** (6) · **`sat_geotransform_srid: int`** ★ · **`transform_note: str`** · **`imagery_captured_at: datetime | None`** ★ · **`attribution: str`** ★ · **`terms_url: str | None`** ★ · `stats: MatchStats` · `scores: MatchScores` · `view_regime` · `degeneracy_gate: float` · `degeneracy_report: dict` · `degraded: bool` · `degradation_reason: str | None` · `warnings: list[WarningItem]` · `gcp_count` · `gcps_url` · `quality_flags: list[QualityFlag]` · `created_at`

```
transform_note = "image_px --homography--> mosaic_px --sat_geotransform--> EPSG:{srid} --> EPSG:4326.
                  Row-major H. GDAL-order geotransform. Pixel CENTRES: apply +0.5 to (u,v)
                  before the geotransform. sat_geotransform_srid is authoritative and is NOT
                  always 3857. See CONTRACT.md §5.8."
```

> **`gcps_url`** is defined normatively as **`/api/v1/match-results/{id}/gcps`** — **endpoint 64**. v1.0 declared `gcps_url` and `qk.gcps.forMatch` while the 63-endpoint table had **no such route and no documented `match_result_id` filter on endpoint 38** — leaving IU-27 with a query key pointing at nothing. Adding the endpoint beats overloading endpoint 38 with a filter: a match result's GCP set is a genuine sub-resource with a stable identity, and it is what `qk.gcps.forMatch` already models.

> **`transform_note` ships in the payload.** The image-pixel → world chain is two composed transforms with two different memory-layout conventions, and getting either backwards yields coordinates that look plausible and are wrong by hundreds of metres. **A one-line statement of the chain costs 200 bytes and prevents the single most expensive mistake a consumer of this API can make.**

`MatchScores`: `feature_similarity_score: float | None` · `geometric_consistency_score: float | None` · `landmark_consistency_score: float | None` · `semantic_similarity_score: float | None` · `overall_confidence: float` (0–100) · `weights_used: ScoreWeights` · **`renormalized: bool`** · `renormalization_note: str | None` · `calibrated: bool` · `calibration_id: str`

> **Score renormalisation is explicit.** With no deep models, `semantic_similarity_score` is `null` and its weight is redistributed over the remaining three. **Without `renormalized: true`, an 87.3 on a weightless box and an 87.3 on a GPU box would be quietly incomparable.** Stating it makes the number's meaning inspectable.
> **`degraded`/`warnings` live at the RESULT level, not just the job level.** Results outlive jobs in the UI; a candidate reviewed a week later must still say it came from the fallback path.

`QualityFlag` ∈ `low_inliers` · `low_inlier_ratio` · `degenerate_homography` · `reflected_homography` · `high_reproj_error` · `low_semantic_evidence` · `geotiff_georeference_disagreement` · `few_landmarks` · `zoom_clamped`. Advisory; the UI badges them.

#### `job.py`
`JobRead` · `JobSummary` · `JobProgress` · `JobListParams` · `JobPollParams`

```python
class JobProgress(ApiModel):
    percent: float                 # ★ 0-100, MONOTONIC NON-DECREASING within an attempt
    stage: JobStage
    message: str | None
    current: int | None
    total: int | None
    eta_seconds: int | None        # ★ null until >=3 rate samples. A wrong ETA is worse than none.
    tiles_fetched: int | None
    tiles_total: int | None
    candidates_evaluated: int | None


class JobRead(ApiModel):
    id: UUID
    type: JobType                  # ★ the discriminator over the v_jobs union
    status: JobStatus
    image_id: UUID | None
    project_id: UUID | None
    batch_id: UUID | None
    cancel_requested: bool
    attempt: int
    max_attempts: int
    progress: JobProgress
    degraded: bool
    degradation_reason: str | None
    warnings: list[WarningItem]
    result_ref: ResultRef | None   # null until succeeded
    result_url: str | None
    error: ErrorBody | None        # ★ ErrorBody-shaped: the client renders job failures with
                                   #   the SAME component as HTTP errors.
                                   #   error_traceback is stored but NEVER serialised.
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime
```

**`JobStage` per type — normative, ordered:**

| type | stages |
|---|---|
| `match` | `pending` → **`resolving_models`** → `resolving_aoi` → `fetching_tiles` → `extracting_query` → `extracting_train` → `matching` → `estimating_homography` → `scoring` → `deriving_gcps` → `persisting` → `done` |
| `segment` | `pending` → `loading_model` → `segmenting` → `vectorizing` → `persisting` → `done` |
| `suggest_landmarks` | `pending` → `loading_model` → `detecting` → `ranking` → `persisting` → `done` |
| `export` | `pending` → `collecting_gcps` → `reprojecting` → `rendering` → `writing` → `done` |
| `batch` | `pending` → `fanning_out` → `waiting_children` → `aggregating` → `done` |
| `gcp_recompute` | `pending` → `refitting_homography` → `deriving_gcps` → `persisting` → `done` |
| `ingest` | `pending` → `decoding` → `thumbnailing` → `persisting` → `done` |

> **★ `resolving_models` is why this stage list changed.** §11.1 and §11.8 both mandate that degradation is reported *"At stage `loading_model` — the instant it is known, not at the end"* — but **`loading_model` exists only for `segment` and `suggest_landmarks`.** The `match` list had no such stage, so **the worker had no legal value to write when it discovered SuperGlue's weights were missing** — on the job type where that discovery matters most. `resolving_models` is second (weight **0.0** — `resolve_with_fallback` uses `find_spec` and a sha256, and is milliseconds), and it is exactly where `build_context`'s `ResolutionReport` → `match_jobs.degraded`/`warnings` gets written. §11.1/§11.8 now name it.

**Rules the workers MUST honour, because the UI depends on them:**
- `percent` is **monotonic non-decreasing within an attempt** and resets to `0` on `retrying`. *A progress bar that goes backwards is a bug report.*
- `percent` is a **weighted blend of stages, not `stage_index / n_stages`**, so the bar tracks **wall-clock**, not stage count. **`STAGE_WEIGHTS` lives in `backend/app/core/constants.py` (IU-15) and NOWHERE ELSE**; `tasks/progress.py` imports it.
- Progress writes are **throttled to ≥ 250 ms apart** and use a plain `UPDATE`, **never inside the CV transaction**. Progress is telemetry; it must never hold a lock a matcher needs.
- **Degradation is reported the INSTANT it is known**, at **`resolving_models`**, not at the end. A client watching `warnings` sees "SuperGlue unavailable → FLANN" within a second of the job starting.

**`STAGE_WEIGHTS` — normative, exact, and keyed by JobStage VALUES:**

```python
# backend/app/core/constants.py     ★ IU-15, sole owner
STAGE_WEIGHTS: Final[dict[JobType, dict[JobStage, float]]] = {
    JobType.MATCH: {
        JobStage.PENDING: 0.00, JobStage.RESOLVING_MODELS: 0.00,
        JobStage.RESOLVING_AOI: 0.02, JobStage.FETCHING_TILES: 0.33,
        JobStage.EXTRACTING_QUERY: 0.05, JobStage.EXTRACTING_TRAIN: 0.15,
        JobStage.MATCHING: 0.30, JobStage.ESTIMATING_HOMOGRAPHY: 0.05,
        JobStage.SCORING: 0.04, JobStage.DERIVING_GCPS: 0.03,
        JobStage.PERSISTING: 0.03, JobStage.DONE: 0.00,
    },                                                          # sums to 1.00
    JobType.SEGMENT: {...}, JobType.SUGGEST_LANDMARKS: {...},
    JobType.EXPORT: {...},  JobType.BATCH: {...},
    JobType.GCP_RECOMPUTE: {...}, JobType.INGEST: {...},
}
```

> **★ v1.0's weights were prose, and none of their six keys named a real `JobStage`.** They read *"(match: tile fetch 0.35, extract 0.20, match 0.30, estimate 0.05, score 0.05, persist 0.05)"* — but the stage is `fetching_tiles`, not "tile fetch"; there are **two** extract stages (`extracting_query` + `extracting_train`), not one "extract"; and five stages (`pending`, `resolving_aoi`, `deriving_gcps`, `persisting`, `done`) had **no weight at all**. IU-20 would have had to invent the mapping. **CI test (IU-15):** for every `JobType`, `set(STAGE_WEIGHTS[t]) == set(STAGES[t])` **and** `sum(STAGE_WEIGHTS[t].values()) == 1.0 ± 1e-9`.

**Terminal set = `{succeeded, failed, cancelled}`.** Clients stop polling on exactly these three. There is no `expired` state — retention deletes the row, which surfaces as `404`.

**Polling** (`GET /jobs/{id}`): honour `Retry-After` (`1` running, `2` pending/queued, `5` retrying, **absent when terminal — its absence IS the machine-readable "stop polling"**). `ETag` over status+progress+updated_at; `304` is cheap and common. Optional long-poll `?wait=0..30` subscribes to the Redis pubsub channel `job:{id}:events`, cutting poll traffic ~25×; **falls back transparently** — if Redis pubsub is unavailable, `wait` is ignored and the current state returns immediately. nginx `proxy_read_timeout` must exceed 30 s.

> **WebSockets and SSE are OUT OF SCOPE for v1** (§12 C-07). Polling + long-poll covers a single-user-per-job UI at a fraction of the operational cost.

**Cancellation** (`DELETE /jobs/{id}`): `pending`/`queued` → `cancelled` + `revoke()`, **`200`**. `running` → set `cancel_requested = true`, publish to `job:{id}:control`, **`202`**; the worker polls the flag at every stage boundary and inside the tile-fetch loop and raises `JobCancelled`. Terminal → **`409 JOB_NOT_CANCELLABLE`**.

> **`revoke(terminate=True)` is NEVER used.** A hard kill of a process holding GDAL dataset handles and an open mosaic file orphans `*.part` files and, with torch, can wedge the CUDA context so the worker's *next* task fails too. **A 1-second cooperative window is worth avoiding an entire class of corruption.** The `cancelling` state is exposed so the UI can grey the button instead of lying that it's done.

**Retries:** only **transient** failures retry (`ProviderUpstreamError`, `ProviderRateLimited` honouring upstream `Retry-After`, `RedisUnavailable`, `DatabaseUnavailable`, socket timeouts). Backoff `min(2**attempt * 5s, 120s)` with full jitter. **Never retried:** validation errors, `SearchHintRequired`, `UnsupportedImageFormat`, `JobCancelled`, and any "no match found".

> **"No match found" is `succeeded`, not `failed`.** A match job that fetched tiles, extracted features, and found no candidate above `min_confidence` **did its job correctly**. It ends `succeeded` with `result_count = 0` and `best_confidence = null`. Modelling this as `failed` would trigger pointless retries of a deterministic outcome and would tell the surveyor the system broke when the answer is "not here". **`failed` is reserved for *the pipeline could not run*.**

#### `gcp.py`
`GcpRead` · `GcpSummary` · `GcpUpdate` · `GcpOriginal` · `GcpLandmarkRef` · `GcpAccuracy` · `GcpListParams` · `GcpResetRequest` · `GcpRecomputeRequest` · `GcpRecomputeDryRun` · `GcpRecomputeDelta` · `GcpRecomputeFitStats`

```python
class GcpAccuracy(ApiModel):
    """★ TWO ACCURACIES, ALWAYS. Reporting only the relative figure would tell a surveyor
    they have 0.3 m GCPs when they have 3 m GCPs.

    ★ EVERY NUMBER HERE IS CE90 (§4.20). `confidence_level` ships so it cannot be misread."""
    confidence_level: Literal["ce90"] = "ce90"
    relative_ce90_m: float          # ★ RENAMED from `relative_m` — the name now carries the level
    georef_ce90_m: float
    total_ce90_m: float
    semi_major_ce90_m: float | None # the error ellipse — null only for a legacy row
    semi_minor_ce90_m: float | None
    azimuth_deg: float | None       # major axis, 0=North, clockwise
    dominant_term: Literal["match", "georeference", "landmark_click", "rectification"]


class GcpRead(ApiModel):
    id: UUID
    image_id: UUID
    match_result_id: UUID
    landmark_id: UUID | None
    code: str | None
    image_px: PixelXY
    satellite_px: PixelXY
    lat: float
    lon: float
    crs: Literal["EPSG:4326"]      # ★ always. Present so nobody has to assume.
    elevation_m: float | None
    elevation_source: str | None
    confidence: float              # ★ 0-100
    horizontal_accuracy_m: float | None
    accuracy: GcpAccuracy
    residual_px: float | None      # ★ ||H*image_px - satellite_px|| for THIS point
    manually_adjusted: bool
    original: GcpOriginal | None   # non-null iff manually_adjusted
    adjustment_offset_m: float | None
    adjusted_by: str | None
    adjusted_at: datetime | None
    adjustment_note: str | None
    is_included_in_export: bool
    is_stale: bool
    stale_reason: GcpStaleReason | None
    landmark: GcpLandmarkRef | None
    created_at: datetime
    updated_at: datetime
```

- `lat`/`lon` are serialised from `geom` — **never a raw WKB/GeoJSON blob**. Flat floats are what a CSV exporter, a Leaflet marker, and a surveyor all want.
- `residual_px` is **per-point**. A job-level RMSE hides *the one bad correspondence* in an otherwise good match; this is how a surveyor finds it.

**`PATCH /gcps/{id}` — the two adjustment modes and how the server closes the loop:**

| Client sends | Server does |
|---|---|
| `lat`/`lon` only | Sets `geom`. Derives `satellite_px` by the **inverse** chain: `4326 → 3857 → inv(sat_geotransform) → mosaic_px`. |
| `satellite_px` only | Sets `satellite_pixel_x/y`. Derives `lat`/`lon` by the **forward** chain: `mosaic_px → sat_geotransform → 3857 → 4326`. |
| **both** | Forward-project the given `satellite_px` and compare to the given `lat`/`lon`. Within `LE_GCP_CONSISTENCY_TOLERANCE_M` (0.5 m) → accept, `lat`/`lon` authoritative. Beyond → **`422 GCP_ADJUSTMENT_AMBIGUOUS`** with `details = {"disagreement_m": …, "tolerance_m": 0.5, "hint": "Send lat/lon or satellite_px, not both."}` |
| neither (only `code`/`note`/flags) | Metadata-only edit. **Does not** set `manually_adjusted`. **Renaming a GCP is not adjusting it.** |

> **Why the server derives the other representation instead of storing one.** `satellite_px` and `lat`/`lon` are two views of one fact, and the DDL stores both. If a PATCH updated only what the client sent, the two would diverge — **the map would show the marker in one place and the CSV would export another, with no indication which is right.** Deriving is not redundant work; it is the invariant. It is cheap (two affine ops + one transform) and it happens inside the same transaction.
> **Why `satellite_px` mode exists at all.** Dragging a marker on the satellite tile is the natural gesture and is *more accurate* than typing coordinates: the surveyor is matching what they see. `lat`/`lon` mode exists for the surveyor who has an RTK fix from the field, which is ground truth and outranks the imagery entirely.
> **`image_px` is NOT adjustable here.** Moving the point *on the photograph* is editing the annotation — `PATCH /annotations/{id}` — which marks this GCP stale. **Two endpoints, two meanings:** "the algorithm put the coordinate in the wrong place" vs. "I marked the wrong pixel". Allowing `image_px` here would silently fork `gcps.pixel_x` from `annotations.pixel_x` with no revision record.

**On the first adjustment, in one transaction:** `original_geom := geom` (**kept forever**) → `manually_adjusted := true` → `adjusted_by := principal` → `adjusted_at := now()` → `adjustment_offset_m := ST_Distance(original_geom, geom)` (geodesic, real metres) → **`confidence` is left untouched**. Subsequent adjustments update everything **except `original_geom`, which is written once and never again — it is the algorithm's answer, and there is only one of those.**

> **Why a manual adjustment does NOT set `confidence = 100`.** Tempting, and wrong. `gcps.confidence` is *the pipeline's score for this correspondence* — it feeds `best_confidence`, the ranking, and the export filter. Overwriting it on human edit destroys the only record of how well the algorithm did, makes `?confidence__gte=70` meaningless (every adjusted point passes), and **asserts a certainty the human never claimed** — a surveyor nudging a marker 3 m is *guessing better*, not measuring. Human certainty is carried by `manually_adjusted` + `adjustment_offset_m` + `adjusted_by` + the note. A client that wants "trust human edits absolutely" filters on `manually_adjusted`, which says exactly that and nothing more.

> **Why staleness is a flag and never an auto-recompute.** A GCP is a coordinate that may already be in a survey report, a contract, or a machine-control file. **It changes when a human decides it changes.** Every path that *could* invalidate a GCP — editing the source annotation, restoring a revision, selecting a different match result — marks it stale and says so. Nothing recomputes it implicitly. `POST /images/{id}/gcps/recompute` is the only door, and it is one a person opens.

`GcpRecomputeRequest`: `match_result_id: UUID | None` · `mode: Literal["refit","rederive"] = "refit"` · `anchor_weight: float = 10.0` (1..1000) · `preserve_adjusted: bool = True` · `estimator: EstimatorName | None` · `dry_run: bool = False`.
`dry_run=true` → **synchronous `200 GcpRecomputeDryRun`** (refitting ≤2000 correspondences is milliseconds; only the full pipeline needs a worker). Otherwise **`202 JobRead`**.

> **`dry_run` is not a nicety.** "Recompute" moves coordinates the surveyor may have already reported; they get to see how far, and for which points, **before** committing.

A recompute writes a **new** `match_results` row (`parent_match_result_id` set, `is_selected` moved to it) rather than mutating the old one — keeping the `RESTRICT` provenance chain intact and the original algorithmic answer inspectable forever. Adjusted GCPs are re-parented with their `original_geom` and adjustment metadata carried across.

#### `suggestion.py`
`SuggestLandmarksRequest` · `LandmarkSuggestionRead` · `SuggestionListParams` · `SuggestionAcceptRequest` · `SuggestionAcceptedRef` · `SuggestionRejectRequest` · `SuggestionRejectResponse`

#### `semantic.py`
`SemanticFeatureRead` · `SemanticFeatureSummary` · `SemanticFeatureListParams` · `SegmentRequest` · `SegmentPoint` · `MaskRle` · `SemanticFeatureDeleteParams`

#### `pose.py`
`CameraPoseRead` · `CameraPoseUpdate` · `CameraIntrinsics` · `CameraIntrinsicsInput` · `Orientation` · `OrientationInput` · `PoseUncertainty` · `PoseAmbiguity` · `HeatmapRead` · `HeatmapCell` · `HeatmapGrid` · `HeatmapCandidate` · `HeatmapScoreRange` · `HeatmapSparsity` · `HeatmapParams`

> **Heatmap cells are sparse and say so.** `HeatmapSparsity` carries `cell_count`, `grid_cols*grid_rows`, and a `note` string. **Absent ≠ score 0**, and the payload states it.

#### `imagery.py`
`ProviderInfo` · `ProviderCapabilities` · `ProviderCoverage` · `ProviderAttribution` · `ProviderToS` · `ProviderRateLimit` · `ProviderHealth` · `ProviderListParams` · `TileParams` · `StaticImageParams`

#### `batch.py`
`BatchCreate` · `BatchUploadForm` · `BatchRead` · `BatchSummary` · `BatchItemRead` · `BatchCounts` · `BatchRollup` · `BatchListParams` · `BatchImageFilter`

#### `export.py`
`ExportRequest` · `ExportFilter` · `ExportOptions` · `ExportRead` · `ExportSummary` · `ExportListParams` · `PdfExportOptions` · `CsvExportOptions` · `ShapefileExportOptions` · `KmlExportOptions` · `DxfExportOptions`

### 6.3 Exception hierarchy — `backend/app/core/exceptions.py`

Application code raises **domain** exceptions and **never `HTTPException`** — that keeps the service layer importable and unit-testable without FastAPI, and is what lets the same services run inside Celery workers where `HTTPException` would be nonsense.

```python
class LandExplorerError(Exception):
    code: ClassVar[str]
    status: ClassVar[int]

    def __init__(self, message: str, *, details: list[ErrorDetail] | None = None,
                 headers: dict[str, str] | None = None) -> None: ...
```

```
LandExplorerError
├── NotFoundError            (404)  ProjectNotFound · ImageNotFound · AnnotationNotFound
│                                   · JobNotFound · MatchResultNotFound · GcpNotFound
│                                   · RevisionNotFound · AnnotationVersionNotFound
│                                   · ExportNotFound · BatchNotFound · SuggestionNotFound
│                                   · CameraPoseNotAvailable · HeatmapNotAvailable
│                                   · UnknownProvider
├── ValidationError          (422)  InvalidBBox · BboxCrossesAntimeridian · InvalidSortField
│                                   · UnknownQueryParam · ParamConflict · SearchHintRequired
│                                   · ZoomOutOfRange · SearchAreaTooLarge · NoAnnotations
│                                   · GcpAdjustmentAmbiguous · GcpOutOfBounds
│                                   · AnnotationGeometryInvalid · AnnotationOutOfBounds
│                                   · TooManyAnnotations · GeometryTooComplex
│                                   · StaticImageTooLarge · ImageTooLarge
│                                   · NoAdjustedGcps · InsufficientAnchors
│                                   · RevisionReplayTooExpensive
├── EmptyPatchError          (400)  EmptyPatch
├── ConflictError            (409)  MatchJobAlreadyRunning · ExportNotReady · JobNotCancellable
│                                   · RevisionConflict · RevisionRestoreConflict
│                                   · ImageStillProcessing · ProjectHasActiveJobs
│                                   · GcpCodeConflict · ProjectNameConflict
│                                   · IdempotencyKeyReused · IdempotencyInProgress
│                                   · GcpOriginalUnavailable
├── PreconditionFailedError  (412)  StaleAnnotationVersion · StaleGcpVersion · StaleProjectVersion
├── PreconditionRequiredError(428)  PreconditionRequired · ConfirmationRequired
├── PayloadTooLargeError     (413)  UploadTooLarge · BatchTooLarge
├── UnsupportedMediaTypeError(415)  UnsupportedImageFormat
├── RangeNotSatisfiableError (416)  RangeNotSatisfiable
├── GoneError                (410)  ExportExpired · ImagePurged · RevisionPruned
│                                   · SatelliteImagePurged
├── AuthError                (401)  MissingCredentials · InvalidCredentials
├── ForbiddenError           (403)  ProviderToSForbidden · ReadOnlyMode
├── RateLimitError           (429)  RateLimitExceeded · ProviderRateLimited
├── ProviderError            (502)  ProviderUpstreamError · ProviderInvalidResponse
├── ProviderNotConfigured    (503)  ProviderNotConfigured
├── DependencyUnavailable    (503)  DatabaseUnavailable · RedisUnavailable · WorkerUnavailable
├── StorageError             (500)  ArtifactWriteFailed · ArtifactReadFailed
└── InsufficientStorage      (507)  InsufficientStorage
```

A **single** handler `landexplorer_exception_handler` reads `exc.status` / `exc.code`. **There is no per-exception `if`-ladder.**

**The 500 handler** logs `exc_info=True` with `request_id`, route and principal; increments `unhandled_exceptions_total{route}`; and returns **exactly** `{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred.","status":500,"details":null,"request_id":"…","timestamp":"…","docs_url":null}}`. **Never the exception string** — tracebacks contain storage paths, connection strings, and provider keys. In `LE_DEBUG=true` only, `details` carries `[{"loc":[],"msg":"<repr>","type":"debug.traceback"}]`.

**Mapping from package exceptions** (`backend/app/tasks/base.py` owns this table — it is the single place retry semantics are decided; **neither `ai_engine` nor `gis` imports Celery**):

| Package exception | Task classification | `error.code` | Retry? |
|---|---|---|---|
| `gis.errors.ProviderTransportError` | Transient | `PROVIDER_UPSTREAM_ERROR` | **yes** |
| `gis.errors.ProviderRateLimitError` | Transient | `PROVIDER_RATE_LIMITED` | **yes**, honour `retry_after`, does not count against `max_attempts` |
| `gis.errors.ProviderNotConfiguredError` | Terminal | `PROVIDER_NOT_CONFIGURED` | no — a retry cannot fix a wrong key |
| `gis.errors.TileNotAvailableError` | *not an error* | — | window skipped, `placeholder_fraction` incremented |
| `gis.errors.TileOutOfRangeError` | Terminal | `INTERNAL_ERROR` | no — caller bug |
| `gis.errors.OutOfCoverage` | Terminal | `OUT_OF_COVERAGE` | no |
| `gis.errors.AreaTooLargeError` | Terminal | `SEARCH_AREA_TOO_LARGE` | no (the API should have caught it) |
| `gis.errors.RasterBackendUnavailable` | Terminal | `INTERNAL_ERROR` | no |
| `ai_engine.errors.ComponentUnavailable` | Terminal | `INTERNAL_ERROR` | no — only reachable with `LE_AI_STRICT_BACKEND=true` |
| `ai_engine.errors.WeightsMissing` / `WeightsCorrupt` | **NOT AN ERROR** | — | **`WarningItem` + fallback (L11)** |
| `MatchJobResult(status="no_viable_candidate")` | **NOT AN ERROR** | — | **`succeeded`, `result_count=0` (§11.6)** |
| `MatchJobResult(status="ambiguous")` | **NOT AN ERROR** | — | **`succeeded`**, candidates returned, `AMBIGUOUS_MATCH` warning |
| `JobCancelled` | Terminal | `CANCELLED` | no |
| soft time limit | Terminal | `TIMEOUT` | no — retrying a too-slow job just repeats the timeout |
| anything else | Terminal | `INTERNAL_ERROR` | no — full traceback logged, generic message to the client |

### 6.4 `deps.py` — shared dependencies

> **★ `app.api.deps` is EXPLICITLY EXEMPT from the `api-not-db` import contract, and the exemption is stated here so nobody spends an afternoon on it.**
>
> `[importlinter:contract:api-not-db]` set `source_modules = app.api` and `forbidden_modules = app.db, app.models, ai_engine, gis, cv2`. But `app.api.deps` **is** `app.api`, and §6.4 specifies it as `get_db() -> AsyncIterator[AsyncSession]` (needs `app.db.session`), `get_project/get_image/get_annotation/get_gcp/get_export` (all `app.models`), and `get_provider/get_imagery_registry` (both `gis.imagery`). **Every one of those imports was forbidden. IU-21 could not write §6.4 and pass CI.**
>
> The audit offered two ways out and preferred (a) — deps returns schema DTOs and the session dependency moves to `app.services`. **We take (b), the carve-out, and the reason is worth recording:** option (a) sounds like L6 but is not what L6 protects. **L6's target is `select()` in a router** — a route body doing SQL. FastAPI's dependency system *is* the composition root of the HTTP layer; `Depends(get_db)` is how a session enters a request at all, and pushing it into `app.services` would either give services a FastAPI dependency (which `services-no-fastapi` forbids, and which is the *stronger* rule) or invent a parallel injection mechanism to dodge a lint rule. Option (a) also makes `get_image` return an `ImageRead` that the very next line must re-fetch as an ORM row to mutate — a DTO round trip in service of a contract, not of a design.
>
> **The mechanical resolution:** the contract's `source_modules` becomes **`app.api.v1`** (the routers — where the rule actually bites), `allow_indirect_imports = true` is set (§10.4), and `app.api.deps` is named as the exemption. **Routers still may not import `app.db`, `app.models`, `ai_engine`, `gis` or `cv2`.** They receive already-loaded entities from `deps` and call services. That is L6, enforced where L6 means something.

```python
# backend/app/api/deps.py    ★ EXEMPT from api-not-db (§10.4). Routers are NOT.
async def get_db() -> AsyncIterator[AsyncSession]: ...
def     get_settings() -> Settings: ...
async def get_principal(request: Request) -> Principal: ...          # anonymous when auth off
def     get_pagination(limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0)) -> PaginationParams: ...
def     get_sorting(sort: str | None = Query(None)) -> SortParams: ...
async def get_project(project_id: UUID, db=Depends(get_db)) -> Project: ...     # 404s
async def get_image(image_id: UUID, db=Depends(get_db)) -> Image: ...           # 404s
async def get_annotation(annotation_id: UUID, db=Depends(get_db)) -> Annotation: ...
async def get_gcp(gcp_id: UUID, db=Depends(get_db)) -> GCP: ...
async def get_job(job_id: UUID, db=Depends(get_db)) -> JobView: ...   # ★ JobView: §5.5
async def get_export(export_id: UUID, db=Depends(get_db)) -> Export: ...
async def get_provider(provider: ProviderName) -> ImageryProvider: ...          # 404/503s
def     get_imagery_registry() -> ProviderRegistry: ...
def     get_storage() -> ObjectStorage: ...
def     get_job_queue() -> JobQueue: ...     # ★ core.queue.JobQueue, not Celery directly
async def require_worker() -> None: ...                              # 503 WORKER_UNAVAILABLE
def     require_if_match(request: Request) -> str: ...               # 428 when absent
def     require_confirm_delete(resource_id: UUID, request: Request) -> None: ...  # 428
async def get_idempotency(request: Request) -> IdempotencyContext: ...
def     require_writable() -> None: ...                              # 403 READ_ONLY_MODE
```

`get_image`/`get_project`/etc. **raise `NotFoundError` themselves**, so no route body repeats the existence check and **the 404 is guaranteed to precede any body validation**.

### 6.5 Middleware order (outermost → innermost)

1. `RequestIdMiddleware` — mint/propagate ULID; bind to logging context; emit `X-Request-ID`. **Outermost so *every* response, including rejections below, carries one.**
2. `CORSMiddleware`
3. `TimingMiddleware` — `X-Response-Time-ms`, Prometheus histogram
4. `BodySizeLimitMiddleware` — rejects over-cap bodies before they reach a route
5. `RateLimitMiddleware`
6. `GZipMiddleware(minimum_size=1024)` — JSON only; **excluded for `image/*` and `application/zip`** (re-compressing JPEG burns CPU to add bytes)
7. Router

**CORS `expose_headers` is not optional detail.** Browsers hide all but seven response headers from JS. Without the list the client cannot read `ETag` (so no `If-Match`, so no optimistic locking), cannot read `Location` (so no job polling), cannot read `Retry-After`, and cannot read `Content-Disposition` (so no filename on download). **Every mechanism this API relies on is header-carried; omitting one silently disables a feature in the browser only, and it will pass every curl-based test.** Required: `ETag` · `Location` · `Retry-After` · `X-Request-ID` · `X-API-Version` · `X-RateLimit-*` · `X-Imagery-Attribution` · `X-Imagery-Provider` · `X-Cache` · `X-Heatmap-BBox` · `X-Heatmap-Score-Range` · `X-Checksum-SHA256` · `Content-Disposition` · `Idempotency-Replayed`.
**`allow_origins=["*"]` is never used. Not even in dev** — the wildcard is incompatible with `allow_credentials=True` and the habit ships to production.

**Rate limiting fails OPEN when Redis is unreachable.** The limiter logs, increments `ratelimit_failopen_total`, and allows the request. Rate limiting is a protection mechanism, not a correctness one; failing closed converts a Redis blip into a total outage. Meanwhile `/health/ready` reports `not_ready` for Redis so the instance is pulled from rotation anyway — **the two mechanisms cover each other.** `/health` and `/health/ready` are **exempt** from rate limiting: rate-limiting your own liveness probe causes the orchestrator to kill healthy containers under load, an outage amplifier.

---

## 7. The exact endpoint table

**63 endpoints. Every path is prefixed `/api/v1`, applied ONCE in `backend/app/api/v1/router.py`.**

| # | Method | Path | Request | Response | Router file |
|---|---|---|---|---|---|
| **Health** |
| 1 | `GET` | `/health` | — | `200 HealthResponse` | `health.py` |
| 2 | `GET` | `/health/ready` | `verbose`, `check` (csv) | `200`/`503 ReadinessResponse` | `health.py` |
| **Capabilities** |
| 3 | `GET` | `/capabilities` | — | `200 CapabilitiesResponse` | `capabilities.py` |
| **Projects** |
| 4 | `POST` | `/projects` | `ProjectCreate` | `201 ProjectRead` + `Location` | `projects.py` |
| 5 | `GET` | `/projects` | `ProjectListParams` | `200 Page[ProjectSummary]` | `projects.py` |
| 6 | `GET` | `/projects/{project_id}` | `include_deleted` | `200 ProjectRead` + `ETag` · `304` | `projects.py` |
| 7 | `PATCH` | `/projects/{project_id}` | `ProjectUpdate`, `If-Match?` | `200 ProjectRead` | `projects.py` |
| 8 | `DELETE` | `/projects/{project_id}` | `hard`, `X-Confirm-Delete` if hard | `204` | `projects.py` |
| **Images** |
| 9 | `POST` | `/images` | `ImageUploadForm` (multipart), `Idempotency-Key?` | `201 ImageRead` · `202 ImageUploadAccepted` | `images.py` |
| 10 | `GET` | `/images` | `ImageListParams` | `200 Page[ImageSummary]` | `images.py` |
| 11 | `GET` | `/images/{image_id}` | — | `200 ImageRead` + `ETag` · `304` | `images.py` |
| 12 | `GET` | `/images/{image_id}/file` | `download`, `Range?` | `200`/`206` binary | `images.py` |
| 13 | `GET` | `/images/{image_id}/thumbnail` | `ThumbnailParams` | `200` binary | `images.py` |
| 14 | `GET` | `/images/{image_id}/metadata` | — | `200 ImageMetadataRead` | `images.py` |
| 15 | `DELETE` | `/images/{image_id}` | `hard`, `X-Confirm-Delete` if hard | `204` | `images.py` |
| **Annotations** |
| 16 | `GET` | `/images/{image_id}/annotations` | `AnnotationListParams` | `200 Page[AnnotationRead]` + `ETag` | `annotations.py` (`router_nested`) |
| 17 | `POST` | `/images/{image_id}/annotations` | `AnnotationCreate` | `201 AnnotationRead` + `ETag` | `annotations.py` (`router_nested`) |
| 18 | `PUT` | `/images/{image_id}/annotations` | `AnnotationBulkUpsertRequest` | `200 AnnotationBulkUpsertResponse` | `annotations.py` (`router_nested`) |
| 19 | `DELETE` | `/images/{image_id}/annotations` | `kind?` (csv), `X-Confirm-Delete` **required** | `200 AnnotationBulkUpsertResponse` | `annotations.py` (`router_nested`) |
| 20 | `GET` | `/annotations/{annotation_id}` | — | `200 AnnotationRead` + `ETag` | `annotations.py` (`router_flat`) |
| 21 | `PATCH` | `/annotations/{annotation_id}` | `AnnotationUpdate`, **`If-Match` REQUIRED** | `200 AnnotationRead` · `412` | `annotations.py` (`router_flat`) |
| 22 | `DELETE` | `/annotations/{annotation_id}` | `If-Match?` | `200 AnnotationRead` (`is_deleted: true`) | `annotations.py` (`router_flat`) |
| **Revisions** |
| 23 | `GET` | `/projects/{project_id}/revisions` | `RevisionListParams` | `200 Page[RevisionSummary]` | `revisions.py` (`router_project`) |
| 24 | `POST` | `/projects/{project_id}/revisions` | `RevisionCreate` | `201 RevisionRead` | `revisions.py` (`router_project`) |
| 25 | `GET` | `/revisions/{revision_id}` | `include_snapshot`, `image_id?` | `200 RevisionRead` | `revisions.py` (`router_flat`) |
| 26 | `POST` | `/revisions/{revision_id}/restore` | `RevisionRestoreRequest` | `200 RevisionRestoreResponse` | `revisions.py` (`router_flat`) |
| 27 | `GET` | `/images/{image_id}/annotation-versions` | `AnnotationVersionListParams` (`offset` XOR `before_id`) | `200 Page[AnnotationVersionSummary]` | `revisions.py` (`router_versions`) |
| 28 | `GET` | `/annotations/{annotation_id}/versions` | `AnnotationVersionListParams` | `200 Page[AnnotationVersionSummary]` | `revisions.py` (`router_versions`) |
| 29 | `GET` | `/annotation-versions/{version_id}` | `version_id: int` | `200 AnnotationVersionRead` | `revisions.py` (`router_versions`) |
| **Matching** |
| 30 | `POST` | `/images/{image_id}/match` | `MatchRequest`, `force?`, `Idempotency-Key?` | **`202 JobRead`** + `Location`, `Retry-After: 1` | `matching.py` (`router_image`) |
| 31 | `GET` | `/jobs` | `JobListParams` | `200 Page[JobSummary]` | `jobs.py` |
| 32 | `GET` | `/jobs/{job_id}` | `wait: int = 0` (0..30), `If-None-Match?` | `200 JobRead` + `ETag`, `Retry-After` · `304` | `jobs.py` |
| 33 | `DELETE` | `/jobs/{job_id}` | — | `200 JobRead` · `202 JobRead` · `409` | `jobs.py` |
| 34 | `GET` | `/images/{image_id}/match-results` | `MatchResultListParams` | `200 Page[MatchResultSummary]` | `matching.py` (`router_image`) |
| 35 | `GET` | `/match-results/{match_result_id}` | — | `200 MatchResultRead` | `matching.py` (`router_results`) |
| 36 | `GET` | `/match-results/{match_result_id}/satellite-image` | `overlay`, `format` | `200` binary + `X-Imagery-Attribution` | `matching.py` (`router_results`) |
| 37 | `POST` | `/match-results/{match_result_id}/select` | `MatchResultSelectRequest` | `200 MatchResultRead` | `matching.py` (`router_results`) |
| **GCPs** |
| 38 | `GET` | `/images/{image_id}/gcps` | `GcpListParams`, `format=json\|geojson` | `200 Page[GcpRead]` \| `GeoJsonFeatureCollection` | `gcps.py` (`router_image`) |
| 39 | `GET` | `/gcps/{gcp_id}` | — | `200 GcpRead` + `ETag` | `gcps.py` (`router_flat`) |
| 40 | `PATCH` | `/gcps/{gcp_id}` | `GcpUpdate`, **`If-Match` REQUIRED** | `200 GcpRead` · `412` · `422` | `gcps.py` (`router_flat`) |
| 41 | `POST` | `/gcps/{gcp_id}/reset` | `GcpResetRequest` | `200 GcpRead` (**idempotent**) | `gcps.py` (`router_flat`) |
| 42 | `POST` | `/images/{image_id}/gcps/recompute` | `GcpRecomputeRequest` | **`202 JobRead`** · `200 GcpRecomputeDryRun` | `gcps.py` (`router_image`) |
| **Suggestions** |
| 43 | `POST` | `/images/{image_id}/suggest-landmarks` | `SuggestLandmarksRequest` | **`202 JobRead`** | `suggestions.py` |
| 44 | `GET` | `/images/{image_id}/landmark-suggestions` | `SuggestionListParams` | `200 Page[LandmarkSuggestionRead]` | `suggestions.py` |
| 45 | `POST` | `/images/{image_id}/landmark-suggestions/accept` | `SuggestionAcceptRequest` | `200 AnnotationBulkUpsertResponse` | `suggestions.py` |
| **Semantics** |
| 46 | `GET` | `/images/{image_id}/semantic-features` | `SemanticFeatureListParams` | `200 Page[SemanticFeatureRead]` | `semantics.py` |
| 47 | `POST` | `/images/{image_id}/segment` | `SegmentRequest` | **`202 JobRead`** | `semantics.py` |
| **Pose** |
| 48 | `GET` | `/images/{image_id}/camera-pose` | — | `200 CameraPoseRead` · `404` | `pose.py` |
| **Heatmap** |
| 49 | `GET` | `/images/{image_id}/heatmap` | `HeatmapParams` (`format=json\|geojson\|png`) | `200 HeatmapRead` \| GeoJSON \| PNG · `404` | `pose.py` |
| **Imagery** |
| 50 | `GET` | `/imagery/providers` | `ProviderListParams` | `200 Page[ProviderInfo]` | `imagery.py` |
| 51 | `GET` | `/imagery/providers/{provider}` | — | `200 ProviderInfo` (health from the **30 s cache**) | `imagery.py` |
| 52 | `GET` | `/imagery/tiles/{provider}/{z}/{x}/{y}` | `TileParams` (incl. `kind`) | `200` binary · **`204`** (valid address, no imagery) | `imagery.py` |
| 53 | `GET` | `/imagery/static` | `StaticImageParams` (incl. `kind`) | `200` binary (PNG/JPEG/GeoTIFF) | `imagery.py` |
| **Batch** |
| 54 | `POST` | `/batch` | `BatchCreate` (JSON) \| `BatchUploadForm` (multipart) | **`202 BatchRead`** | `batch.py` |
| 55 | `GET` | `/batch` | `BatchListParams` | `200 Page[BatchSummary]` | `batch.py` |
| 56 | `GET` | `/batch/{batch_id}` | — | `200 BatchRead` | `batch.py` |
| 57 | `DELETE` | `/batch/{batch_id}` | — | `202 BatchRead` · `409` | `batch.py` |
| **Exports** |
| 58 | `POST` | `/images/{image_id}/export` | `ExportRequest`, `format` | **`202 JobRead`** | `exports.py` (`router_image`) |
| 59 | `POST` | `/projects/{project_id}/export` | `ExportRequest`, `format` | **`202 JobRead`** | `exports.py` (`router_project`) |
| 60 | `GET` | `/exports` | `ExportListParams` | `200 Page[ExportSummary]` | `exports.py` (`router_flat`) |
| 61 | `GET` | `/exports/{export_id}` | — | `200 ExportRead` | `exports.py` (`router_flat`) |
| 62 | `GET` | `/exports/{export_id}/download` | `Range?` | `200`/`206` binary · `409` · `410` | `exports.py` (`router_flat`) |
| 63 | `DELETE` | `/exports/{export_id}` | — | `204` | `exports.py` (`router_flat`) |
| **64** | `GET` | `/match-results/{match_result_id}/gcps` | `GcpListParams` | `200 Page[GcpRead]` | `gcps.py` (`router_results`) |

★ **Endpoint 64 is new.** `MatchResultRead.gcps_url` and `qk.gcps.forMatch` both existed in v1.0 with **no route behind them** — IU-27 had a query key pointing at nothing.

Plus, **not under `/api/v1`** and **not part of the public contract**: `GET /metrics` (Prometheus, same port, excluded from OpenAPI — §12 C-42).

**Only seven endpoints initiate async work**: 30, 42, 43, 47, 54, 58, 59. **Everything else answers immediately. That is the shape of a system where CV never touches a request handler (L5).**

**Router registration order matters** — Starlette matches in registration order. `router.py` includes in exactly the §2.4 order, with `gcps.router_image` **before** `gcps.router_flat`. A startup assertion walks `app.routes` and **fails fast on any duplicate `(method, path)`** — a duplicate route silently shadows in FastAPI and is otherwise found in production.

### 7.1 Readiness aggregation — normative

| check | probe | timeout | cache | down ⇒ |
|---|---|---|---|---|
| `postgres` | `SELECT 1` + `postgis_version()` | 2 s | none | **`not_ready` → 503** |
| `redis` | `PING` on broker + result backend | 1 s | none | **`not_ready` → 503** |
| `storage` | write+read+delete a 1-byte probe file | 1 s | 10 s | **`not_ready` → 503** |
| `celery` | `control.inspect(timeout=1).ping()` | 1.5 s | 10 s | `degraded` → **200** |
| `imagery` | default provider `health()` | 2 s | 30 s | `degraded` → **200** |
| `models` | the **cached** `PreflightReport` (§11.1) — never a re-probe | — | process | **never** (informational) |
| **`raster`** | `gis.rasterio_shim.probe()` → which backend bound (`rasterio` \| `gdal` \| `none`) | — | 60 s | `degraded` → **200** |

> **★ The `raster` check is new, and it exists because "degrades gracefully" can degrade to *nothing* silently.** §11.3's whole story rests on GDAL being present: `rasterio_shim` binds *rasterio → GDAL → typed error*, and `crs.py` falls back *pyproj → osgeo.osr → closed-form NumPy*. §0.1 records GDAL 3.8.4 as installed **here** — and §9.14's pinned runtime list carries **neither GDAL nor rasterio nor pyproj** (both are "Optional"). So a container built from §9.14 as written ships with **no raster backend and no pyproj at all**, and then: `RasterBackendUnavailable` on every call ⇒ **`local_orthophoto` is dead in the shipped image**; GeoTIFF ingest cannot populate `crs_epsg`/`bounds`/`geotransform` ⇒ `ck_images_geotiff_complete` **rejects the row**; and `gis/accuracy.py` cannot reach UTM ⇒ `total_ce90_m` — which §11.7 calls **mandatory on every GCP** — is uncomputable. **All of it degrades quietly, which is the exact failure mode §11.8 exists to prevent.** A container missing both backends must be **loud**, not silently accurate-to-nothing. `GET /capabilities` surfaces the same probe. §9.14 additionally promotes `pyproj`/`rasterio` to pinned **for the backend image** and mandates `libgdal-dev` in the Dockerfile — they are only optional on the **dev box**, where system GDAL substitutes.

> **Why `degraded` is 200.** If no Celery worker is running, the API can still serve every read: projects, images, annotations, past results, past exports, downloads. **Returning 503 would take the whole UI offline — including the screens that would tell the operator the workers are down.** Only the three dependencies without which *no request can be served correctly* gate readiness. Meanwhile `POST /images/{id}/match` independently returns `503 WORKER_UNAVAILABLE`, so the failure is reported **precisely at the operation that actually needs a worker**, rather than by blanket-failing the instance.
> **Why `models` NEVER affects readiness.** This is L1 expressed in the health surface. The dev machine has no deep weights and must run end to end. **If missing weights made the app unready it would never start here.** Weight presence is reported so the UI can grey out `superglue` in the dropdown, and that is *all* it does.
> **`/health` touches no dependency.** A liveness probe that checks Postgres restarts every API container when Postgres blips, turning a 30-second hiccup into a full outage. Liveness answers only "is this process wedged?"
> **`/health/ready` NEVER returns 500.** Every check is individually wrapped; an exception inside a check becomes `status: "down"` + `message` for that component. **A readiness endpoint that can itself throw is useless precisely when you need it.**

### 7.2 The tile proxy (endpoint 52) — why it exists

**By default, `ProviderInfo.tile_url_template` is the proxy path `/api/v1/imagery/tiles/{provider}/{z}/{x}/{y}` for EVERY provider, keyed or keyless.** Setting `LE_IMAGERY_DIRECT_TILE_URLS=true` makes **keyless** providers return their upstream URL instead, saving bandwidth at a stated cost.

> **★ v1.0's rule ("upstream URL for keyless, proxy path for keyed") routed the DEFAULT provider around the proxy — and contradicted three of the six reasons the proxy exists.** `esri_world_imagery` is keyless and is the L2 default, so on **every zero-config machine** each browser tile would have bypassed reason **3** (*"Single chokepoint for ToS enforcement"*), reason **4** (*"Quota and cost control — one Redis-backed bucket per provider, counted across all users"*) and reason **5** (*"Worker-and-browser cache identity — the surveyor's browsing warms the cache for their own match job"*), plus `LE_ALLOWED_PROVIDERS`, `LE_IMAGERY_RATE_LIMIT_RPS` and `LE_IMAGERY_USER_AGENT` (which operators are told to set to a real contact). 20-api.md stated the opposite rule outright — *"always our proxy path, never the upstream URL — that is the whole design"* — so the two live documents disagreed **in practice, on the default path**. Making the bypass **opt-in** keeps every stated reason true by default and leaves the bandwidth optimisation available to an operator who has read `docs/legal/imagery-terms.md` and accepted the ToS consequence.

Six reasons, the load-bearing one first:
1. **There is no way to call a keyed tile API from a browser without exposing the key.** Anything in `VITE_*` is compiled into the bundle and is public.
2. **Provider interchangeability** — `local_orthophoto` is *impossible* without it; there is no upstream URL to give a browser.
3. **Single chokepoint for ToS enforcement.**
4. **Quota and cost control** — one Redis-backed bucket per provider, counted across all users.
5. **Worker-and-browser cache identity** — the surveyor's browsing **warms the cache for their own match job**, and it makes `satellite_checksum` meaningful.
6. **An offline `fixture` provider** that lets the whole app be tested with no network, no keys, and no weights.

`204` on a valid tile address with no imagery (ocean, gap) is deliberate — it is not an error, and Leaflet renders nothing.

#### 7.2.1 The `/imagery` routes must not block the event loop — normative

`ImageryProvider` is **synchronous by design** (§4.16: *"Thread-safe: Celery calls these from a worker pool"*), and endpoints 51/52/53 expose it over FastAPI. **v1.0 never said whether those routes were `def` or `async def`, nor whether they went through a threadpool.**

1. **Endpoints 51, 52 and 53 are declared `def`, not `async def`.** Starlette runs sync routes in the threadpool. A synchronous `httpx` call inside an `async def` blocks the event loop for the **entire worker process** — taking `/health` down alongside it, which is the failure mode most likely to be misdiagnosed as "the API is down" when it is one slow tile.
2. **L5's parenthetical is amended:** *"(Tile proxying is IO and is exempt; **it must still run off the event loop**.)"*
3. **Endpoint 53's budget is cut to request scale.** `LE_MAX_STATIC_TILES: 256 → 16` and `LE_MAX_STATIC_PIXELS: 67108864 → 4194304` (4 MP). At the old budget, one GET could trigger **256 tile fetches, a 64-megapixel NumPy stitch, a crop and a PNG encode** — that is not "tile proxying", it is precisely the *"OpenCV/NumPy operation heavier than one thumbnail downsample"* that **L5 forbids**, wearing a GET. It is a job-sized workload; if a client genuinely needs 64 MP, that is the `202 → GET /jobs/{id}` pattern every other heavy operation in §6 already uses, and endpoint 53 returns `422 STATIC_IMAGE_TOO_LARGE` pointing there.
4. **Endpoint 51's "live self-check" is deleted.** It serves `ProviderHealth` from the **same 30 s cache** §7.1 already specifies for the `imagery` readiness check. An endpoint that does a network round trip per call is a denial-of-service amplifier pointed at a provider whose rate limit we are contractually obliged to respect.

---

## 8. Exact TypeScript types

### 8.1 THE CASING LAW

> **snake_case at the API boundary, in the generated types, AND in the hand-written domain types. There is no case-mapping layer anywhere in the frontend.**

`50-frontend.md` used camelCase domain types (`errorRadiusM`, `matchResultId`, `createdAt`). **That is overruled** (§12 C-08). Rationale, in order of weight:

1. **`openapi-typescript` generates the transport types from `openapi.json`, and CI fails the build on any diff.** A camelCase domain layer means every field is renamed by hand, so the generator's guarantee stops at the transport boundary and the domain layer drifts *invisibly* — which is precisely the failure the generator exists to prevent.
2. **A mapping layer is a second source of truth.** `confidence` vs `confidence`, fine — but `satellite_pixel_x` vs `satellitePixelX` vs `satellitePixelX` (typo) is a runtime `undefined` that TypeScript cannot catch across a hand-written mapper, because the mapper's output type is whatever the mapper says it is.
3. **The API doc already decided this and gave the reason:** "two names for every field, and a permanent source of `populate_by_name` bugs."
4. The aesthetic cost is real and is worth paying once. `gcp.satellite_px.x` reads fine.

**Consequence, stated so nobody is surprised:** ESLint's `camelcase` rule is **disabled for `src/types/**` and `src/api/**`** in `.eslintrc.cjs`, with a comment pointing here.

**Branded IDs and discriminated unions are still hand-written.** The generated types are structurally correct but semantically flat (`id: string`). The hand-written layer in `src/types/` **re-exports the generated shapes with branding applied**, adding zero renames:

```ts
// src/types/common.ts
declare const __brand: unique symbol;
type Brand<T, B> = T & { readonly [__brand]: B };

export type Uuid = Brand<string, "Uuid">;
export type IsoDateTime = Brand<string, "IsoDateTime">;

export interface Point2D { x: number; y: number }
export interface Size { width: number; height: number }
export interface Rect { x: number; y: number; width: number; height: number }

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown | null;
}

export interface ErrorBody {
  code: ApiErrorCode;
  message: string;
  status: number;
  details: ErrorDetail[] | null;
  request_id: string;
  timestamp: IsoDateTime;
  docs_url: string | null;
}

export interface ErrorEnvelope { error: ErrorBody }

/** Thrown by src/api/client.ts. Carries the parsed envelope. */
export class ApiError extends Error {
  readonly body: ErrorBody;
  readonly status: number;
}

/**
 * ★ GENERATED, NOT HAND-MAINTAINED. `scripts/gen_error_codes.py` walks the §6.3 hierarchy
 * (every LandExplorerError subclass's `code` ClassVar), adds the two JOB-ONLY codes, and
 * emits this union. CI fails on a diff — the same gate, for the same reason, as
 * openapi-typescript.
 *
 * ★ v1.0 hand-maintained it and it had already drifted: `JobRead.error: ErrorBody` carries
 *   `code: ApiErrorCode`, and §6.3's task-classification table produces `CANCELLED` and
 *   `TIMEOUT` — NEITHER of which was a member. The union was also missing
 *   NO_ADJUSTED_GCPS, INSUFFICIENT_ANCHORS, STATIC_IMAGE_TOO_LARGE,
 *   GCP_ORIGINAL_UNAVAILABLE, PROJECT_NAME_CONFLICT, RANGE_NOT_SATISFIABLE,
 *   PROVIDER_INVALID_RESPONSE, SUGGESTION_NOT_FOUND, ANNOTATION_VERSION_NOT_FOUND and
 *   UNKNOWN_PROVIDER, and carried STORAGE_ERROR where §6.3 names ArtifactWriteFailed /
 *   ArtifactReadFailed. Hand-maintaining a mirror of a Python hierarchy is the drift the
 *   generator gate exists to kill; it had no business being the one exception.
 *
 * CI test: every LandExplorerError.code reachable in the app appears in this union.
 */
export type ApiErrorCode =
  // ── job-only (never an HTTP status; produced by the task classifier, §6.3) ──
  | "CANCELLED" | "TIMEOUT"
  // ── the §6.3 hierarchy ──
  | "VALIDATION_ERROR" | "PROJECT_NOT_FOUND" | "IMAGE_NOT_FOUND"
  | "ANNOTATION_NOT_FOUND" | "JOB_NOT_FOUND" | "MATCH_RESULT_NOT_FOUND"
  | "GCP_NOT_FOUND" | "REVISION_NOT_FOUND" | "EXPORT_NOT_FOUND" | "BATCH_NOT_FOUND"
  | "CAMERA_POSE_NOT_AVAILABLE" | "HEATMAP_NOT_AVAILABLE"
  | "SEARCH_HINT_REQUIRED" | "NO_ANNOTATIONS" | "ZOOM_OUT_OF_RANGE"
  | "SEARCH_AREA_TOO_LARGE" | "INVALID_BBOX" | "BBOX_CROSSES_ANTIMERIDIAN"
  | "INVALID_SORT_FIELD" | "UNKNOWN_QUERY_PARAM" | "PARAM_CONFLICT"
  | "GCP_ADJUSTMENT_AMBIGUOUS" | "GCP_OUT_OF_BOUNDS" | "GCP_CODE_CONFLICT"
  | "ANNOTATION_GEOMETRY_INVALID" | "ANNOTATION_OUT_OF_BOUNDS"
  | "TOO_MANY_ANNOTATIONS" | "GEOMETRY_TOO_COMPLEX"
  | "MATCH_JOB_ALREADY_RUNNING" | "IMAGE_STILL_PROCESSING" | "JOB_NOT_CANCELLABLE"
  | "REVISION_CONFLICT" | "REVISION_RESTORE_CONFLICT" | "REVISION_PRUNED"
  | "REVISION_REPLAY_TOO_EXPENSIVE" | "PROJECT_HAS_ACTIVE_JOBS"
  | "STALE_ANNOTATION_VERSION" | "STALE_GCP_VERSION" | "STALE_PROJECT_VERSION"
  | "PRECONDITION_REQUIRED" | "CONFIRMATION_REQUIRED" | "EMPTY_PATCH"
  | "UPLOAD_TOO_LARGE" | "BATCH_TOO_LARGE" | "UNSUPPORTED_IMAGE_FORMAT"
  | "IMAGE_TOO_LARGE" | "EXPORT_EXPIRED" | "EXPORT_NOT_READY" | "IMAGE_PURGED"
  | "SATELLITE_IMAGE_PURGED" | "IDEMPOTENCY_KEY_REUSED" | "IDEMPOTENCY_IN_PROGRESS"
  | "MISSING_CREDENTIALS" | "INVALID_CREDENTIALS"
  | "PROVIDER_TOS_FORBIDDEN" | "READ_ONLY_MODE"
  | "RATE_LIMIT_EXCEEDED" | "PROVIDER_RATE_LIMITED"
  | "PROVIDER_UPSTREAM_ERROR" | "PROVIDER_NOT_CONFIGURED" | "OUT_OF_COVERAGE"
  | "PROVIDER_INVALID_RESPONSE" | "UNKNOWN_PROVIDER"
  | "DATABASE_UNAVAILABLE" | "REDIS_UNAVAILABLE" | "WORKER_UNAVAILABLE"
  | "ARTIFACT_WRITE_FAILED" | "ARTIFACT_READ_FAILED"
  | "INSUFFICIENT_STORAGE" | "INTERNAL_ERROR"
  // ── present in §6.3, absent from v1.0's union ──
  | "NO_ADJUSTED_GCPS" | "INSUFFICIENT_ANCHORS" | "STATIC_IMAGE_TOO_LARGE"
  | "GCP_ORIGINAL_UNAVAILABLE" | "PROJECT_NAME_CONFLICT" | "RANGE_NOT_SATISFIABLE"
  | "SUGGESTION_NOT_FOUND" | "ANNOTATION_VERSION_NOT_FOUND"
  | "TIMEOUT_EXCEEDS_LIMIT" | "ELEVATION_UNAVAILABLE";

export interface WarningItem {
  code: string;
  message: string;
  field: string | null;
  requested: string | null;
  effective: string | null;
}

export type CoordinateFormat = "dd" | "dms" | "utm";
```

### 8.2 The type modules — field-for-field mirrors of §6

| File | Types |
|---|---|
| `common.ts` | `Uuid` · `IsoDateTime` · `Point2D` · `Size` · `Rect` · `Page<T>` · `ErrorDetail` · `ErrorBody` · `ErrorEnvelope` · `ApiError` · `ApiErrorCode` · `WarningItem` · `CoordinateFormat` · `Result<T,E>` |
| `geo.ts` | `LatLon` · `BBox` · `PixelXY` · `Homography` · `GeoTransform` · `GeoJsonPoint` · `GeoJsonLineString` · `GeoJsonPolygon` · `GeoJsonGeometry` · `GeoJsonFeature` · `GeoJsonFeatureCollection` · `MapViewState` · `ViewOrigin` · `BasemapKind` · `ProviderId` · `ProviderInfo` · `LocationHint` · `Crs` |
| `image.ts` | `ImageStatus` · `VariantName` · `ImageVariant` · `GpsMetadata` · `CameraMetadata` · `ImageUrls` · `ImageCounts` · `ImageRead` · `ImageSummary` · `ImageMetadataRead` |
| `annotation.ts` | `AnnotationKind` · `AnnotationGeomType` · `AnnotationOp` · `AnnotationRead` · `AnnotationCreate` · `AnnotationUpdate` · `AnnotationBulkUpsertRequest` · `AnnotationBulkUpsertItem` · `AnnotationBulkUpsertResponse` · `AnnotationVersionSummary` · `AnnotationVersionRead` · `RevisionRead` — ★ **`RevisionSummary` moved to `common.ts`**, matching the Python move (§6.2) |
| `gcp.ts` | `GcpStaleReason` · `ConfidenceBand` · `GcpAccuracy` · `GcpOriginal` · `GcpLandmarkRef` · `GcpRead` · `GcpUpdate` · `GcpRecomputeRequest` · `GcpRecomputeDryRun` · **`GcpTableRow`** ★ |
| `match.ts` | `ExtractorName` · `MatcherName` · `EstimatorName` · `ViewRegime` · `QualityFlag` · `SearchHint` · `MatchOptions` · `ScoreWeights` · `MatchRequest` · `MatchTileRef` · `MatchStats` · `MatchScores` · `MatchResultRead` · `MatchResultSummary` |
| `job.ts` | `JobStatus` · `JobType` · `JobStage` · `JobProgress` · `JobRead` · `JobSummary` · `isTerminal()` |
| `export.ts` | `ExportFormat` · `ExportOptions` · `ExportFilter` · `ExportRequest` · `ExportRead` · `ExportSummary` |
| `project.ts` | `ProjectRead` · `ProjectSummary` · `ProjectCounts` · `ProjectCreate` · `ProjectUpdate` · `ProjectFilters` · `JobFilters` |
| `capabilities.ts` | `CapabilityItem` · `ExportCapability` · `ComputeInfo` · `LimitsInfo` · `DefaultsInfo` · `CapabilitiesResponse` |
| **`pose.ts`** ★ | `PoseMethod` · `CameraIntrinsics` · `Orientation` · `PoseUncertainty` · `PoseAmbiguity` · `CameraPoseRead` · `CameraPoseUpdate` |
| **`heatmap.ts`** ★ | `HeatmapFormat` · `Colormap` · `HeatmapCell` · `HeatmapGrid` · `HeatmapCandidate` · `HeatmapScoreRange` · `HeatmapSparsity` · `HeatmapRead` · `HeatmapParams` |
| **`semantic.ts`** ★ | `SemanticClass` · `FeatureSpace` · `FeatureDetectorName` · `SegmentBackend` · `MaskRle` · `SemanticFeatureRead` · `SemanticFeatureSummary` · `SegmentRequest` · `SegmentPoint` |
| **`suggestion.ts`** ★ | `SuggestionStatus` · `SuggestionStrategy` · `LandmarkSuggestionRead` · `SuggestLandmarksRequest` · `SuggestionAcceptRequest` · `SuggestionAcceptedRef` · `SuggestionRejectRequest` |
| **`batch.ts`** ★ | `BatchOnError` · `BatchCreate` · `BatchRead` · `BatchSummary` · `BatchItemRead` · `BatchCounts` · `BatchRollup` |
| `commands.ts` | `Command<T>` · `CommandType` · `SerializedCommand` · `AnnotationCommand` + 10 payload interfaces (**client-only — no server mirror**) |
| `index.ts` | barrel |

> **★ The five new modules exist because five API modules had no response types at all.** §2.5 ships `src/api/{semantics,pose,heatmap,batch,suggestions}.ts` and the hooks `useSemantics/usePose/useHeatmap/useBatch/useSuggestions`, and **§8.2's table had no home for `HeatmapRead`, `HeatmapCell`, `CameraPoseRead`, `SemanticFeatureRead`, `LandmarkSuggestionRead`, `BatchRead` or `BatchItemRead`.** IU-23 owns `types/**` and is blocked on IU-17 for shapes; IU-24 owns `api/**`. **Neither was told to declare them** — so IU-24 would have inlined `any` or invented them, which is exactly the drift §8.1 exists to prevent. All five are assigned to **IU-23** and mirror §6.2 field-for-field.

The load-bearing three, verbatim:

```ts
// src/types/image.ts
export type ImageStatus = "uploaded" | "processing" | "ready" | "failed";
export type VariantName = "thumbnail" | "preview" | "full" | "original";

/** ★ §12 C-36. Without original_width the client cannot compute D and the entire
 *  coordinate model of §8.6 collapses. The server ALWAYS sends it, non-null. */
export interface ImageVariant {
  name: VariantName;
  url: string;
  width: number;             // this variant's raster width
  height: number;
  original_width: number;    // ★ ALWAYS the full-resolution width
  original_height: number;
  display_scale: number;     // ★ = width / original_width. THE `D`. Server-computed.
  size_bytes: number | null;
}
```

```ts
// src/types/gcp.ts
export type GcpStaleReason =
  | "landmark_moved" | "landmark_deleted" | "homography_superseded" | "annotations_restored";

export type ConfidenceBand = "high" | "moderate" | "low" | "unreliable";

export interface GcpAccuracy {
  confidence_level: "ce90";
  relative_ce90_m: number;
  georef_ce90_m: number;
  total_ce90_m: number;
  semi_major_ce90_m: number | null;
  semi_minor_ce90_m: number | null;
  azimuth_deg: number | null;
  dominant_term: "match" | "georeference" | "landmark_click" | "rectification";
}

/** ★ The mandated GCP table's view-model. §8.2/§14 F-104.
 *  50-frontend's GcpTableRow was camelCase (void under C-08) AND had `errorRadiusM`, which
 *  corresponds to NOTHING on GcpRead — while §8.7's precision truncation keys off
 *  accuracy.total_ce90_m. Picking the wrong one silently breaks the honesty mechanism.
 *
 *  THE SIX MANDATED COLUMNS, IN ORDER: Point ID · Image X/Y · Latitude · Longitude ·
 *  Confidence · Accuracy (= accuracy.total_ce90_m, NEVER relative_ce90_m) — plus a
 *  trailing action cell. */
export interface GcpTableRow {
  id: Uuid;
  code: string | null;
  image_px: PixelXY;
  lat: number;
  lon: number;
  confidence: number;            // 0–100
  total_ce90_m: number;          // ★ the error-radius column
  manually_adjusted: boolean;
  is_stale: boolean;
  linked_annotation_id: Uuid | null;
  display_decimals: number;      // from lib/geo/format.ts (§8.7)
}

export interface GcpRead {
  id: Uuid;
  image_id: Uuid;
  match_result_id: Uuid;
  landmark_id: Uuid | null;
  code: string | null;
  image_px: PixelXY;
  satellite_px: PixelXY;
  lat: number;
  lon: number;
  crs: "EPSG:4326";
  elevation_m: number | null;
  elevation_source: string | null;
  confidence: number;                 // ★ 0-100
  horizontal_accuracy_m: number | null;
  accuracy: GcpAccuracy;
  residual_px: number | null;
  manually_adjusted: boolean;
  original: GcpOriginal | null;
  adjustment_offset_m: number | null;
  adjusted_by: string | null;
  adjusted_at: IsoDateTime | null;
  adjustment_note: string | null;
  is_included_in_export: boolean;
  is_stale: boolean;
  stale_reason: GcpStaleReason | null;
  landmark: GcpLandmarkRef | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
```

```ts
// src/types/job.ts
export type JobStatus =
  | "pending" | "queued" | "running" | "retrying" | "succeeded" | "failed" | "cancelled";

export type JobType =
  | "match" | "export" | "batch" | "segment" | "suggest_landmarks" | "gcp_recompute" | "ingest";

export interface JobProgress {
  percent: number;                    // 0-100, monotonic within an attempt
  stage: JobStage;
  message: string | null;
  current: number | null;
  total: number | null;
  eta_seconds: number | null;
  tiles_fetched: number | null;
  tiles_total: number | null;
  candidates_evaluated: number | null;
}

export interface JobRead {
  id: Uuid;
  type: JobType;
  status: JobStatus;
  image_id: Uuid | null;
  project_id: Uuid | null;
  batch_id: Uuid | null;
  cancel_requested: boolean;
  attempt: number;
  max_attempts: number;
  progress: JobProgress;
  degraded: boolean;
  degradation_reason: string | null;
  warnings: WarningItem[];
  result_ref: { kind: string; id: Uuid } | null;
  result_url: string | null;
  error: ErrorBody | null;
  queued_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/** ★ EXHAUSTIVE. Adding a JobStatus member is a COMPILE ERROR until the poller is
 *  updated. A bug here means infinite polling on a dead job — this pattern's classic
 *  failure mode. */
export function isTerminal(status: JobStatus): boolean {
  switch (status) {
    case "succeeded":
    case "failed":
    case "cancelled":
      return true;
    case "pending":
    case "queued":
    case "running":
    case "retrying":
      return false;
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}
```

### 8.3 The query key factory — `src/api/queryKeys.ts`

```ts
export const qk = {
  all: ["landexplorer"] as const,
  capabilities: () => [...qk.all, "capabilities"] as const,
  providers:    () => [...qk.all, "providers"] as const,

  projects: {
    all: () => [...qk.all, "projects"] as const,
    lists: () => [...qk.projects.all(), "list"] as const,
    list: (f: ProjectFilters) => [...qk.projects.lists(), f] as const,
    details: () => [...qk.projects.all(), "detail"] as const,
    detail: (id: Uuid) => [...qk.projects.details(), id] as const,
    revisions: (id: Uuid) => [...qk.projects.detail(id), "revisions"] as const,
  },

  images: {
    all: () => [...qk.all, "images"] as const,
    lists: () => [...qk.images.all(), "list"] as const,
    list: (projectId: Uuid) => [...qk.images.lists(), projectId] as const,
    details: () => [...qk.images.all(), "detail"] as const,
    detail: (id: Uuid) => [...qk.images.details(), id] as const,
    metadata: (id: Uuid) => [...qk.images.detail(id), "metadata"] as const,
  },

  annotations: {
    all: () => [...qk.all, "annotations"] as const,
    forImage: (imageId: Uuid) => [...qk.annotations.all(), "image", imageId] as const,
    detail: (id: Uuid) => [...qk.annotations.all(), "detail", id] as const,
    versions: (imageId: Uuid) => [...qk.annotations.forImage(imageId), "versions"] as const,
    atRevision: (imageId: Uuid, seq: number) =>
      [...qk.annotations.forImage(imageId), "revision", seq] as const,
  },

  revisions: {
    all: () => [...qk.all, "revisions"] as const,
    detail: (id: Uuid) => [...qk.revisions.all(), "detail", id] as const,
  },

  suggestions: {
    all: () => [...qk.all, "suggestions"] as const,
    forImage: (imageId: Uuid) => [...qk.suggestions.all(), "image", imageId] as const,
  },

  jobs: {
    all: () => [...qk.all, "jobs"] as const,
    lists: () => [...qk.jobs.all(), "list"] as const,
    list: (f: JobFilters) => [...qk.jobs.lists(), f] as const,
    details: () => [...qk.jobs.all(), "detail"] as const,
    detail: (id: Uuid) => [...qk.jobs.details(), id] as const,
  },

  matches: {
    all: () => [...qk.all, "matches"] as const,
    forImage: (imageId: Uuid) => [...qk.matches.all(), "image", imageId] as const,
    detail: (id: Uuid) => [...qk.matches.all(), "detail", id] as const,
  },

  gcps: {
    all: () => [...qk.all, "gcps"] as const,
    forImage: (imageId: Uuid) => [...qk.gcps.all(), "image", imageId] as const,
    forMatch: (matchId: Uuid) => [...qk.gcps.all(), "match", matchId] as const,
    detail: (id: Uuid) => [...qk.gcps.all(), "detail", id] as const,
  },

  semantics: {
    all: () => [...qk.all, "semantics"] as const,
    forImage: (imageId: Uuid) => [...qk.semantics.all(), "image", imageId] as const,
  },

  pose:    { forImage: (imageId: Uuid) => [...qk.all, "pose", imageId] as const },
  heatmap: { forImage: (imageId: Uuid) => [...qk.all, "heatmap", imageId] as const },

  batches: {
    all: () => [...qk.all, "batches"] as const,
    detail: (id: Uuid) => [...qk.batches.all(), "detail", id] as const,
  },

  exports: {
    all: () => [...qk.all, "exports"] as const,
    lists: () => [...qk.exports.all(), "list"] as const,
    detail: (id: Uuid) => [...qk.exports.all(), "detail", id] as const,
  },
} as const;
```

### 8.4 The job poller — `src/api/hooks/useJob.ts`

**The only polling in the app, and its stop condition is load-bearing.**

```ts
/** ★ src/api/client.ts parses `Retry-After` and surfaces it on the response envelope:
 *     interface Parsed<T> { data: T; retryAfterMs: number | null }
 *  The poller is the only consumer. */
const POLL_FLOOR_MS = Number(import.meta.env.VITE_JOB_POLL_INTERVAL_MS ?? 1500);

export function useJob(jobId: Uuid | null) {
  return useQuery({
    queryKey: qk.jobs.detail(jobId!),
    queryFn: () => jobsApi.get(jobId!),          // -> { data: JobRead, retryAfterMs }
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const res = query.state.data;
      if (!res || isTerminal(res.data.status)) return false;   // ★ stop DEAD on terminal
      const age = Date.now() - new Date(res.data.created_at).getTime();
      const schedule = age < 10_000 ? 1_000 : age < 60_000 ? 2_000 : 5_000;
      // ★ the server's Retry-After WINS when larger; the env floor otherwise applies.
      return Math.max(schedule, POLL_FLOOR_MS, res.retryAfterMs ?? 0);
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 5 * 60_000,
  });
}
```

> **★ v1.0's poller violated two of its own specs and would have shipped verbatim.** §9.11 declares `VITE_JOB_POLL_INTERVAL_MS` default `1500` with consumer `api/hooks/useJob` — *"floor for the adaptive schedule"* — while §8.4's verbatim `useJob` returned **`1_000`** for jobs younger than 10 s (**below its own floor**) and **read no env var at all**. §6.2 separately mandates *"Polling (GET /jobs/{id}): honour `Retry-After` (1 running, 2 pending/queued, 5 retrying…)"* — and **the poller never read it**. `Retry-After`'s absence on a terminal job is described as *"the machine-readable 'stop polling'"*, so ignoring the header discards a signal the server goes out of its way to send. IU-24 implements §8.4 verbatim; either the code honours the config and the header, or the config and the header should not exist. **They exist, so it honours them.**

**Global defaults — `src/api/queryClient.ts`:**

```ts
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500)
        && failureCount < 3,          // ★ NEVER retry a 4xx
      refetchOnWindowFocus: false,    // ★ a surveyor tabbing back must not trigger a
                                      //   tile-fetch storm on cellular
    },
    mutations: { retry: 0 },
  },
});
```

### 8.5 Zustand store shapes — LOCAL UI STATE ONLY (L7)

Eight stores. **None of them holds server data.**

| Store | Owns | Persisted? |
|---|---|---|
| `toolStore` | `activeTool` · `previousTool` · `options` (snap, autoLabel, labelPrefix) | no |
| `annotationStore` | `draft` · `inProgress` · `undoStack` · `redoStack` · `dirty` · `lastSavedAt` · `previewVersionId` | **no** — autosave to the server is the only draft truth |
| `viewerStore` | `transform {scale,x,y}` · `displayScale` (D) · `viewport` · `naturalSize` · `adjustments` · `isFullscreen` · `cursorImagePos` · `minScale`/`maxScale` | no |
| `mapStore` | `view` · `lastOrigin` · `seq` · `basemap` · `providerId` · `heatmapEnabled` · `footprintVisible` · `locationHint` · `isDrawingHint` | no |
| `selectionStore` | `selected: SelectionRef[]` · `hovered` · `anchorId` · `focusOrigin` | no |
| `workspaceStore` | `paneSizes` · `inspectorOpen` · `dockOpen` · `activeTab` · `versionDrawerOpen` · `coordinateFormat` | **yes**, `version: 1` |
| `compareStore` | `active` · `syncMode` · `curtainX` · `syncing` | no |
| `uploadStore` | `items: UploadItem[]` · `concurrency` (3) | no |

> **★ `compareStore.syncMode ∈ {linked, swipe}` requires a selected `MatchResultRead` with `overall_confidence >= 40` (0–100, `= LE_AI_MIN_CONFIDENCE`); otherwise `syncMode` is forced to `none` and the control is disabled with the reason shown.**
>
> 50-frontend gated `linked`/`swipe` on *"a successful match with confidence ≥ 0.40"* — reasoning correctly that *"we do not synchronize views using a homography we do not believe"* — and defined `CONFIDENCE_THRESHOLDS = {high:0.85, moderate:0.65, low:0.40}`, **all on a 0–1 scale**. §12 C-14 and §6.1 make match/GCP confidence **0–100**, and §8.7 restates the bands as **80/60/40**. §12 never named the compare gate as a conflict, and §0 says *"where §12 does not name a conflict, the specialist docs stand as elaboration"* — **so the gate literally stood at `>= 0.40` against a 0–100 value, enabling the verification affordance on essentially EVERY match, including rejected ones.** §8.5 listed only `active/syncMode/curtainX/syncing` and never restated the threshold, so nothing caught it. **50-frontend's `CONFIDENCE_THRESHOLDS` (0.85/0.65/0.40) is VOID** in favour of §8.7's 80/60/40. IU-29 asserts the gate rejects `confidence = 0.4`.

```ts
// selectionStore — the cross-pane sync bus
export interface SelectionRef {
  kind: "annotation" | "gcp";
  id: string;
  linkedId: string | null;
}

export interface SelectionState {
  selected: SelectionRef[];
  hovered: SelectionRef | null;
  anchorId: string | null;
  focusOrigin: "image" | "map" | "table" | null;
  select(ref: SelectionRef, mode: "replace" | "add" | "range", origin: SelectionState["focusOrigin"]): void;
  selectMany(refs: SelectionRef[], origin: SelectionState["focusOrigin"]): void;
  clear(): void;
  setHovered(ref: SelectionRef | null): void;
  isSelected(id: string): boolean;
}
```

> **Reveal is gated on `focusOrigin`:** `if (selected && focusOrigin !== "map") flyToGcp()`. **A pane never auto-scrolls in response to its own action** — which is what prevents "the map fights me when I click it."
> Each pane subscribes with a **narrow boolean selector** (`s => s.selected.some(r => r.id === myId || r.linkedId === myId)`), so selecting P3 does not re-render P1's marker.
> **`inProgress` (a half-drawn polygon) is OUTSIDE the command system** — a half-drawn polygon isn't an edit. Escape cancels without polluting the stack; undo after a completed polygon removes the whole polygon.

> **★ The ManualAdjust design in 50-frontend is VOID, in five specific parts.** It had `ManualAdjust` commit via **`POST /api/v1/gcps/{id}/adjust`** with body `{imagePixel?, latLon?, pinned, note?}` returning `{gcp, recomputed[]}`, display adjusted confidence as **"manual"** rather than a number, and push the edit onto the undo stack via `AdjustGcpCommand`. **Every one of those contradicts the law**, and §12 named none of it — so under §0 it "stood as elaboration":
> - **`/gcps/{id}/adjust` does not exist.** Endpoint 40 is `PATCH /gcps/{gcp_id}` with `If-Match` **REQUIRED**.
> - **`imagePixel` is forbidden there** (§6.2): moving the point *on the photograph* is editing the annotation → `PATCH /annotations/{id}`. Two endpoints, two meanings.
> - **`pinned` exists on neither `GcpUpdate` nor the `gcps` table.**
> - **Rendering adjusted confidence as "manual" overwrites the algorithm's score** — precisely what §6.2 forbids at length. Human certainty is carried by `manually_adjusted` + `adjustment_offset_m` + `adjusted_by` + the note.
> - **`AdjustGcpCommand` is not in the command system**: §8.2's `commands.ts` lists `AnnotationCommand` + 10 payloads only, and §8.5 routes GCP adjustment through `useAdjustGcp`'s optimistic mutation instead.
>
> **Normative:** `ManualAdjust` commits via `useAdjustGcp` → `PATCH /gcps/{gcp_id}` with `If-Match`; image-pixel edits route to `PATCH /annotations/{id}`.

**The sharp edge, resolved:** annotations are edited locally but persisted server-side. Konva drag updates the **transient** `annotationStore` draft; on drop, a React Query mutation `PUT`s the bulk upsert with optimistic update + rollback on error, and **the server response is authoritative**. The draft is cleared on settle. `useAdjustGcp` moves the dragged point optimistically but **dims** its neighbours rather than showing stale-but-confident coordinates — we cannot predict a server-side homography re-estimate.

### 8.6 The viewer transform — `src/lib/viewport/transform.ts`

**★ This is the product's highest-risk client code.** There are **three** coordinate spaces, not two:

```
ORIGINAL px ──×D──▶ DISPLAY raster px ──×s, +(tx,ty)──▶ STAGE px
```
where `D = variant.display_scale = variant.width / variant.original_width`.

> **The naive implementation reads `stage.getPointerPosition()`, divides by scale, subtracts pan, and stores it — yielding DISPLAY pixels.** That silently disagrees with the backend (which computed features on the original) and every annotation jumps by `D₁/D₂` when a variant swaps. **It survives development because `D ≈ 1` on small test images and detonates on the first real 5000px upload.**

```ts
export interface ViewerTransform { scale: number; x: number; y: number }

/** Everything needed for a conversion. Passed explicitly — never read from a store here. */
export interface ViewportContext {
  transform: ViewerTransform;   // s, tx, ty
  displayScale: number;         // D
  naturalSize: Size;            // ORIGINAL dims
  viewport: Size;               // container CSS px
}

// ── Stage/screen -> ORIGINAL image ──────────────────────────────────────────
export function stageToImage(p: Point2D, ctx: ViewportContext): Point2D;
//   image.x = (p.x - tx) / (s * D)
//   image.y = (p.y - ty) / (s * D)

// ── ORIGINAL image -> Stage/screen ──────────────────────────────────────────
export function imageToStage(p: Point2D, ctx: ViewportContext): Point2D;
//   stage.x = p.x * D * s + tx

// ── ORIGINAL image -> DISPLAY raster (what Konva nodes are positioned in) ───
export function imageToDisplay(p: Point2D, D: number): Point2D;   // { x: p.x*D, y: p.y*D }
export function displayToImage(p: Point2D, D: number): Point2D;   // { x: p.x/D, y: p.y/D }

export function effectiveScale(ctx: ViewportContext): number;     // s * D
export function imageRectToStage(r: Rect, ctx: ViewportContext): Rect;
export function stageRectToImage(r: Rect, ctx: ViewportContext): Rect;
export function visibleImageRect(ctx: ViewportContext): Rect;
export function clampToImageBounds(p: Point2D, natural: Size): Point2D;
export function isWithinImage(p: Point2D, natural: Size): boolean;
```

**The rules:**
- **`ImageViewer` is the ONE conversion site.** `onPointerDown/Move/Up` does `stageToImage(stage.getPointerPosition(), ctx)` and the raw stage point is discarded. `ip` is what goes into commands, stores, and the network.
- **`AnnotationLayer` positions Konva nodes in DISPLAY space** (`imageToDisplay`), because they are Stage children and Konva applies `s`/`(tx,ty)` for us. It must **not** use `imageToStage` for node positions — that double-applies the stage transform. `imageToStage` is **only** for DOM overlays outside the Stage (tooltips, the loupe, HTML labels). **Getting this backwards produces annotations that drift at 2× the pan rate** — a distinctive symptom worth naming so a reviewer recognises it instantly.
- **Device pixel ratio never appears in these formulas.** Konva handles DPR internally and `getPointerPosition()` returns CSS-pixel stage coordinates. Introducing DPR here would be a bug.
- **Variant swap compensation:** when `preview` → `full` upgrades `D`, set `s' = s * (D_old / D_new)` to keep the view pinned.
- **Sub-pixel policy: image coordinates are NEVER rounded.** Stored as `number`, sent as JSON floats, displayed to 1 decimal. A homography estimated from integer-rounded correspondences carries needless error. **Round for display, never for storage.**
- **Round-trip invariant, property-tested with fast-check** over `s ∈ [0.01, 40]`, `D ∈ (0,1]`, `tx/ty ∈ [-10⁵,10⁵]`, `p ∈ [0,10⁵]²`: `stageToImage(imageToStage(p)) ≈ p` within `1e-6`.

**Brightness/contrast uses CSS filters, not Konva filters.** `Konva.Node.cache()` rasterises into a buffer with its own origin and pixelRatio — it couples an *appearance* control to the *geometry* pipeline. CSS `filter` is a paint-stage op that **structurally cannot** touch the scene graph, the hit graph, or `getPointerPosition()`. The guarantee is architectural rather than vigilance-based, which is why it is right **before** the performance argument (a re-cache per slider frame is 2.8M pixels of main-thread JS × 60). Applied to `ImageLayer`'s own canvas element — **which is why `ImageLayer` is a dedicated Layer holding exactly one node**: filtering the whole stage would wash out confidence colours and break the legend's promise.

### 8.7 Precision truncation — the honesty mechanism that actually works

**`src/lib/geo/format.ts`** — displayed decimals are a **function of `accuracy.total_ce90_m` (never `relative_ce90_m`) and the confidence band**:

| `total_ce90_m` | band | displayed decimals | example |
|---|---|---|---|
| < 1 m | high | 7 | `41.8721943` |
| 1–5 m | high/moderate | 6 | `41.872194` |
| 5–20 m | moderate | 4 | `41.8722` |
| > 20 m **or** band = `unreliable` | low/unreliable | **2** | `41.87` |

> **A banner can be dismissed; digits cannot.** `41.8721943` on a fix that could be 50 m off is **a fabricated precision claim in the data itself** — and that is the number that gets pasted into a legal document. Full precision stays available on hover and in exports, adjacent to the confidence column.

**Confidence bands** (`src/lib/confidence.ts`), from `GcpRead.confidence` (0–100): `high ≥ 80` · `moderate ≥ 60` · `low ≥ 40` · `unreliable < 40`.

### 8.8 The classical path is framed as the product working

`degraded: true` on a job whose only degradation is "no deep weights present" renders an **informational chip** — *"Matched with SIFT + FLANN"* — **not a warning**. Per the environment constraints this is the *default* state on a fresh machine. **SIFT + RANSAC is a real algorithm with real accuracy; framing it as a degradation would be both wrong and demoralising.** `LandmarkSuggestions` with no SAM weights renders a calm explainer, never an error.

A degradation that *is* worth a warning: the user **explicitly requested** `superglue` and got `flann`. The distinction is `warnings[].requested !== null` — an unrequested fallback is informational; a requested-and-denied one is a warning.

---

## 9. The config / env var table

**Zero required variables. `Settings()` with an empty environment never raises (L10).**

**Prefixes:** `LE_` for everything the backend reads · `VITE_` for the frontend (build-time, **never secret**) · unprefixed only for compose infra vars that upstream images define. § = secret: never logged, never returned by any API, redacted in `/health/ready`.

> **§12 C-05:** `20-api.md` used unprefixed names (`MAX_UPLOAD_BYTES`, `AUTH_MODE`) and `40-imagery.md` used its own (`IMAGERY_PROVIDER`, `ORTHO_DIR`, `TILE_CACHE_TTL_S`). **Both are void. Every backend var is `LE_`-prefixed**, because `core/config.py` declares `env_prefix="LE_"` once and an unprefixed `AUTH_MODE` in a shared shell is a collision waiting to happen.

### 9.1 Core

| Var | Default | Consumer |
|---|---|---|
| `LE_ENV` | `development` | `core.config` — `development\|staging\|production` |
| `LE_DEBUG` | `false` | `core.config`, `main` — forced `false` when `LE_ENV=production` |
| `LE_APP_NAME` | `LandExplorer` | OpenAPI title |
| `LE_API_PREFIX` | `/api/v1` | `api.v1.router`, nginx |
| `LE_API_HOST` | `0.0.0.0` | entrypoint |
| `LE_API_PORT` | `8000` | entrypoint, compose |
| `LE_API_WORKERS` | `2` | entrypoint |
| `LE_CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | `main` (CSV) |
| `LE_LOG_LEVEL` | `INFO` | `core.logging` |
| `LE_LOG_FORMAT` | `json` | `core.logging` — `json\|console` |
| `LE_REQUEST_ID_HEADER` | `X-Request-ID` | `api.middleware` |
| `LE_SECRET_KEY` § | *(ephemeral random per boot)* | `core.security` — safe **because auth is off by default** |
| `LE_TESTING` | `false` | `core.config` — set by conftest; enables fixture provider + eager Celery |
| `LE_ENABLE_DOCS` | `true` | `main` — an internal survey tool benefits more from discoverable docs than it loses to disclosure |
| `LE_READ_ONLY` | `false` | `api.deps` — `403 READ_ONLY_MODE` on every mutating route |

### 9.2 Auth (off by default)

| Var | Default | Consumer |
|---|---|---|
| `LE_AUTH_MODE` | **`none`** | `core.security` — `none\|api_key\|bearer\|cookie` |
| `LE_ACCESS_TOKEN_TTL_SECONDS` | `3600` | `core.security` |
| `LE_API_KEYS` § | *(empty)* | `core.security` — CSV of hashed keys |
| `LE_JWKS_URL` | *(empty)* | `core.security` |
| `LE_RATE_LIMIT_ENABLED` | `false` | `api.middleware` |
| `LE_RATE_LIMIT_PER_MINUTE` | `600` | `api.middleware` |

> **The honest consequence, stated rather than hidden.** With `LE_AUTH_MODE=none`, `gcps.adjusted_by = 'anonymous'` and `ck_gcps_adjustment_complete` is satisfied by a value that attributes nothing. The database can prove *that* a coordinate was adjusted and *when*, but not *by whom*. **That is acceptable for a single-surveyor deployment and NOT acceptable for a multi-user one producing legal survey deliverables.** `PATCH /gcps/{id}` therefore returns `401 MISSING_CREDENTIALS` whenever `LE_AUTH_MODE != none` and no principal resolves — **the audit trail is enforced the moment there is more than one person who could be lying.** `/health/ready` reports `auth_mode` in its detail so a reviewer sees it at a glance.

### 9.3 Database

| Var | Default | Consumer |
|---|---|---|
| `LE_DATABASE_URL` § | `postgresql+psycopg://landexplorer:landexplorer@db:5432/landexplorer` | `db.session`, `alembic/env` |
| `LE_MIGRATION_DATABASE_URL` § | *(= `LE_DATABASE_URL`)* | `alembic/env` — a distinct superuser role in prod |
| `LE_DB_POOL_SIZE` | `5` | `db.session` |
| `LE_DB_MAX_OVERFLOW` | `10` | `db.session` |
| `LE_DB_POOL_TIMEOUT_SECONDS` | `30` | `db.session` |
| `LE_DB_ECHO` | `false` | `db.session` |
| `LE_DB_STATEMENT_TIMEOUT_MS` | `30000` | `db.session` |
| `LE_DB_AUTO_MIGRATE` | **`false`** | `entrypoints/api.sh` — `compose.dev` sets `true`; **prod leaves `false`** |

> `db` resolves inside compose. **On a bare host you must set `LE_DATABASE_URL`.** This is a deliberate trade: optimise the default for the documented happy path (compose), and make the bare-host failure **legible** via `/health/ready`'s per-dependency diagnosis rather than a boot traceback.

### 9.4 Redis / Celery

| Var | Default | Consumer |
|---|---|---|
| `LE_REDIS_URL` § | `redis://redis:6379/0` | `tasks.celery_app`, health, idempotency, pubsub, rate limit |
| `LE_CELERY_BROKER_URL` § | *(= `LE_REDIS_URL`)* | `tasks.celery_app` |
| `LE_CELERY_RESULT_BACKEND` § | `redis://redis:6379/1` | `tasks.celery_app` |
| `LE_CELERY_TASK_ALWAYS_EAGER` | `false` | `tasks.celery_app` — tests set `true` |
| `LE_CELERY_WORKER_CONCURRENCY` | `2` | worker entrypoint — CV queue. **Keep low: SIFT is CPU-hungry.** |
| `LE_CELERY_TASK_SOFT_TIME_LIMIT` | `600` | `tasks.base` — soft ⇒ catchable ⇒ job marked `failed` cleanly |
| `LE_CELERY_TASK_TIME_LIMIT` | `900` | `tasks.celery_app` — hard kill |
| `LE_CELERY_PREFETCH_MULTIPLIER` | `1` | long tasks ⇒ no hoarding |
| `LE_CELERY_ACKS_LATE` | `true` | redelivery on worker crash |
| `LE_JOB_MAX_ATTEMPTS` | `3` | `tasks.base` |
| `LE_JOB_RETRY_BACKOFF_SECONDS` | `5` | `tasks.base` |
| `LE_JOB_RETRY_BACKOFF_MAX_SECONDS` | `120` | `tasks.base` |
| `LE_JOB_RESULT_TTL_SECONDS` | `86400` | `tasks.celery_app` |
| `LE_JOB_STALE_AFTER_SECONDS` | `1800` | `tasks.maintenance` — reaper marks orphaned `running` → `failed` |
| `LE_JOB_PROGRESS_TTL_SECONDS` | `3600` | `tasks.progress` |
| `LE_JOB_RETENTION_DAYS` | `30` | `tasks.maintenance` |

### 9.5 Storage & uploads

| Var | Default | Consumer |
|---|---|---|
| `LE_STORAGE_BACKEND` | `local` | `storage` — `local\|s3` |
| `LE_STORAGE_LOCAL_ROOT` | `./data/storage` | `storage.local` — **must be a shared volume across api + workers** |
| `LE_STORAGE_S3_BUCKET` | *(empty)* | `storage.s3` |
| `LE_STORAGE_S3_ENDPOINT_URL` | *(empty)* | `storage.s3` — set for MinIO |
| `LE_STORAGE_S3_REGION` | `us-east-1` | `storage.s3` |
| `LE_STORAGE_S3_ACCESS_KEY_ID` § | *(empty)* | `storage.s3` |
| `LE_STORAGE_S3_SECRET_ACCESS_KEY` § | *(empty)* | `storage.s3` |
| `LE_STORAGE_SIGNED_URL_TTL_SECONDS` | `900` | `storage.s3` |
| `LE_STORAGE_MIN_FREE_BYTES` | `2147483648` | `image_service` — `507 INSUFFICIENT_STORAGE`, checked **before** streaming |
| `LE_UPLOAD_MAX_BYTES` | **`524288000`** | `api.middleware`, nginx — 500 MB (§12 C-06). Mirror in `client_max_body_size`. |
| `LE_UPLOAD_ALLOWED_MIME` | `image/jpeg,image/png,image/tiff,image/webp` | `image_service` — **sniffed, not trusted from the header** |
| `LE_MAX_IMAGE_PIXELS` | `400000000` | `image_service` — decompression-bomb guard |
| `LE_MAX_IMAGE_DIM` | `65535` | `image_service` |
| `LE_ASYNC_INGEST_THRESHOLD_BYTES` | `52428800` | `image_service` — above this, ingest goes async |
| `LE_USE_SENDFILE` | `false` | `images.py` — `X-Accel-Redirect` in prod |

### 9.6 Imagery

| Var | Default | Consumer |
|---|---|---|
| `LE_IMAGERY_PROVIDER` | **`auto`** | `gis.imagery.registry` — ★ **`auto` walks `LE_IMAGERY_FALLBACK_CHAIN` and takes the first `is_configured()` provider.** An explicit provider name uses that provider, with the chain as **error-recovery only**. See the ruling below. |
| `LE_IMAGERY_FALLBACK_CHAIN` | `local_orthophoto,esri_world_imagery` | `gis.imagery.registry` — **`local_orthophoto` FIRST**: if the operator mounted orthophotos they are definitionally better than any web tile source. It self-skips via `is_configured()` when the dir is empty, so the zero-config machine lands on Esri with no branching. |
| `LE_IMAGERY_DIRECT_TILE_URLS` | **`false`** | `imagery_service` — ★ `false` ⇒ `tile_url_template` is the **proxy path for every provider**, preserving the ToS chokepoint, the shared quota bucket and worker/browser cache identity (§7.2 reasons 3/4/5). `true` ⇒ keyless providers return their upstream URL to save bandwidth; the ToS consequence is documented in `docs/legal/imagery-terms.md`. |
| `LE_IMAGERY_STRICT` | `false` | `gis.imagery.registry` — `true` in prod: no silent fallback |
| `LE_ALLOWED_PROVIDERS` | *(empty = all registered)* | `gis.imagery.registry` — **the operator's hard allow-list** |
| `LE_IMAGERY_OFFLINE` | `false` | registry — `true` ⇒ only `local_orthophoto` + `fixture` |
| `LE_IMAGERY_TILE_CACHE_BACKEND` | `disk` | `gis.imagery.cache` — `memory\|disk\|redis`. **`redis` in prod** — tile fetching happens inside Celery workers and a disk cache in a container is per-replica; four workers searching the same AOI would fetch every tile four times. |
| `LE_IMAGERY_TILE_CACHE_DIR` | `./data/tile_cache` | `cache.disk` |
| `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` | `2592000` | `cache` — 30 d. **Several ToS cap caching — see `docs/legal/imagery-terms.md`.** |
| `LE_IMAGERY_TILE_CACHE_MAX_BYTES` | `21474836480` | `tasks.maintenance` — 20 GB LRU cap |
| `LE_IMAGERY_MAX_CONCURRENT_FETCHES` | `4` | `gis.imagery.http` |
| `LE_IMAGERY_RATE_LIMIT_RPS` | `5` | `gis.imagery.ratelimit` — token bucket per provider |
| `LE_IMAGERY_REQUEST_TIMEOUT_SECONDS` | `15` | `gis.imagery.http` |
| `LE_IMAGERY_MAX_RETRIES` | `3` | `gis.imagery.http` — jittered backoff |
| `LE_IMAGERY_USER_AGENT` | `LandExplorer/1.0 (+https://example.invalid)` | `gis.imagery.http` — **operators should set a real contact** |
| `LE_ESRI_IMAGERY_TILE_URL_TEMPLATE` | `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | `providers.esri` — **note the `{z}/{y}/{x}` order**. ★ Renamed from `LE_ESRI_TILE_URL_TEMPLATE`; `kind=satellite`. |
| `LE_ESRI_REFERENCE_TILE_URL_TEMPLATE` | `…/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}` | `providers.esri` — ★ the overlay composited **over** imagery to serve `kind=hybrid` |
| `LE_ESRI_TERRAIN_TILE_URL_TEMPLATE` | `…/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}` | `providers.esri` — ★ `kind=terrain` |
| `LE_ESRI_MAX_ZOOM` | `19` | `providers.esri` |
| `LE_ESRI_RATE_LIMIT_RPS` | `8.0` | `providers.esri` |
| `LE_LOCAL_ORTHO_DIR` | `./data/orthophotos` | `providers.local_ortho` — empty dir ⇒ provider reports unavailable, **no crash** |
| `LE_LOCAL_ORTHO_ATTRIBUTION` | `Local orthophoto` | `providers.local_ortho` |
| `LE_LOCAL_ORTHO_REINDEX_SECONDS` | `300` | `providers.local_ortho` |
| `LE_LOCAL_ORTHO_ASSUME_BLACK_NODATA` | `false` | **false on purpose** — black is a legitimate pixel value |
| `LE_MAPBOX_ACCESS_TOKEN` § | *(empty)* | `providers.mapbox` — empty ⇒ **not offered**, not a crash |
| `LE_MAPBOX_STYLE_ID` | `mapbox.satellite` | `providers.mapbox` |
| `LE_MAPBOX_CACHE_TTL_SECONDS` | `2592000` | **VERIFY against current ToS** |
| `LE_BING_MAPS_KEY` § | *(empty)* | `providers.bing` |
| `LE_BING_IMAGERY_SET` | `Aerial` | `providers.bing` |
| `LE_COPERNICUS_CLIENT_ID` § | *(empty)* | `providers.sentinel` |
| `LE_COPERNICUS_CLIENT_SECRET` § | *(empty)* | `providers.sentinel` |
| `LE_COPERNICUS_MAX_CLOUD_PCT` | `20` | `providers.sentinel` |
| `LE_SENTINEL_MAX_ZOOM` | **`15`** | `providers.sentinel` — **★ REFUSES `zoom > 15`** rather than serving upsampled mush a matcher would confidently act on |
| `LE_GOOGLE_MAPS_STATIC_KEY` § | *(empty)* | `providers.google_static` |
| `LE_GOOGLE_TOS_ACKNOWLEDGED` | **`false`** | `providers.google_static` — **★ DOUBLE OPT-IN.** The key alone is insufficient; the operator must assert their own ToS coverage. **Google Earth is never a provider.** |

### 9.6a Elevation (§4.27) — ★ NEW

| Var | Default | Consumer |
|---|---|---|
| `LE_ELEVATION_PROVIDER` | **`none`** | `gis.elevation` — `none\|local_dem\|copernicus_dem`. ★ **`none` is KEYLESS, OFFLINE and TERMINAL**: `elevation_m` and `elevation_source` are both `NULL` and the job says `ELEVATION_UNAVAILABLE`. **Honest beats absent.** |
| `LE_LOCAL_DEM_DIR` | `./data/dem` | `elevation.local_dem` — empty dir ⇒ unavailable, **no crash** |
| `LE_COPERNICUS_DEM_URL` | *(empty)* | `elevation.copernicus_dem` |
| `LE_ELEVATION_CACHE_TTL_SECONDS` | `2592000` | `elevation` |

### 9.7 Search

| Var | Default | Consumer |
|---|---|---|
| `LE_SEARCH_DEFAULT_ZOOM` | `18` | `candidates.strategy` |
| `LE_SEARCH_DEFAULT_RADIUS_M` | `1000` | `candidates.hint` |
| `LE_SEARCH_MAX_RADIUS_M` | `50000` | `matching.py` validation |
| `LE_SEARCH_MAX_CANDIDATES` | **`25`** | `candidates.strategy` (§12 C-38) |
| `LE_SEARCH_WINDOW_SIZE_PX` | `1024` | `candidates.strategy` |
| `LE_SEARCH_OVERLAP_RATIO` | **`0.5`** | `candidates.strategy` — ★ buys the **512 px footprint guarantee** (§4.19). At 0.25 the guarantee is only 256 px, and the matching design reasons from 512. |
| `LE_SEARCH_TARGET_GSD_M` | `0.5` | `candidates.strategy` |
| `LE_MAX_TILES_PER_JOB` | **`512`** | `candidates.budget` (§12 C-39) — ★ raised from 256 to absorb the overlap-0.5 stride. The v1.0 budget was sized against a tile table that **omitted the overlap factor from its own formula** (§14 F-80): the published 1 km/z18 figure of ~342 was the disc count with **no overlap and no bbox-over-disc factor**; the real cost at overlap 0.25 is ~775 and at overlap 0.5 is ~1370. **The "at budget" row was already over budget.** |
| `LE_MAX_STATIC_TILES` | **`16`** | `imagery.py` — ★ cut from 256. Endpoint 53 is a request, not a job (§7.2.1). |
| `LE_MAX_STATIC_PIXELS` | **`4194304`** | `imagery.py` — ★ cut from 67108864 (64 MP → 4 MP). A 64-megapixel stitch inside a GET is the workload L5 forbids. |
| `LE_SEARCH_MAX_BBOX_AREA_KM2` | `2500` | `matching.py` validation |
| `LE_EXIF_RADIUS_INFLATION` | `3.0` | `candidates.hint` — multiply EXIF HPE |
| `LE_EXIF_MIN_RADIUS_M` | `250` | `candidates.hint` |

> **`LE_SEARCH_REQUIRE_PRIOR` is DELETED (§12 C-37).** The requirement is **unconditional**: a hint is a hard input requirement, not a toggle. `422 SEARCH_HINT_REQUIRED`, always. A config flag implying global search is possible would be a lie.

### 9.8 AI engine

| Var | Default | Consumer |
|---|---|---|
| `LE_AI_EXTRACTOR` | **`sift`** | `match_service` → `AiEngineConfig` — **L1 default** |
| `LE_AI_MATCHER` | **`flann`** | → `AiEngineConfig` |
| `LE_AI_DETECTOR_FREE` | *(empty)* | → `AiEngineConfig` — empty ⇒ no LoFTR |
| `LE_AI_SEGMENTER` | `classical` | → `AiEngineConfig.segmenter` |
| `LE_AI_SUGGESTER` | `classical_suggester` | → `AiEngineConfig.suggester` (§4.23) |
| **`LE_AI_RANSAC_METHOD`** | **`usac_magsac`** | → **`AiEngineConfig.ransac.method: HomographyMethod`**. ★ A robust-fit METHOD. |
| **`LE_AI_ESTIMATOR_BACKEND`** | **`opencv`** | → **`AiEngineConfig.estimator_backend`**. ★ A component REGISTRY KEY. `opencv` is the only registered one. |

> **★ `LE_AI_ESTIMATOR` is DELETED, and it was a zero-env boot crash.** It defaulted to `usac_magsac` and §9.8 routed it into `AiEngineConfig.estimator` — but `AiEngineConfig.estimator` defaulted to `"opencv"` and §4.7 states the **only** registered estimator is `opencv` ("Terminal, no weights, no fallback"). `usac_magsac` is a `HomographyMethod` value (C-17), i.e. `RansacConfig.method` — **not a registry key.** So with **zero env vars set**, resolving the default against `ComponentKind.ESTIMATOR` finds no spec, finds `spec.fallback = None`, exhausts the chain, and raises **`ComponentUnavailable` at composition/preflight**: a boot-time traceback on an empty environment, violating **L10** (`Settings()` with empty env never raises → working app), **L11** (never a traceback), and §9.13's *"`uvicorn app.main:app` with no env → 200"*. And it was baked into the DB — `projects.default_estimator` / `match_jobs.estimator` are the `robust_estimator` enum, so `match_service` would read `usac_magsac` off the row and hand it to the registry **on every job**. Two env vars, two concepts, no overlap. **IU-02's `test_zero_env_preflight` builds `AiEngineConfig` from `Settings()` with `env={}` and asserts `preflight()` returns a report and raises nothing.**
| `LE_AI_ALLOW_DEEP_MODELS` | `true` | registry — `true` = *attempt* deep backends; unavailability is still graceful. `false` = never even probe. |
| `LE_AI_STRICT_BACKEND` | **`false`** | `models.policy` — `true` ⇒ missing weights **raise** instead of falling back. **CI accuracy suites only. `true` in prod violates L1.** |
| `LE_AI_MODEL_WEIGHTS_DIR` | `./data/model_weights` | `models.weights` — **empty by default and that is the supported state** |
| `LE_AI_DEVICE` | `auto` | `models.device` — **★ `auto` → `cpu` on this machine** (`cuda.is_available()` is `False` despite the cu130 wheel). `cuda` when unavailable ⇒ WARN + `cpu`. |
| `LE_AI_TORCH_THREADS` | `0` | `models.device` — `0` = leave torch's default |
| `LE_AI_DETERMINISTIC_SEED` | `42` | `pipeline` — RANSAC reproducibility |
| `LE_AI_MAX_FEATURES` | `8000` | extractors |
| `LE_AI_CLAHE_ENABLED` | `true` | `extractors.preprocess` — big win on hazy field photos |
| `LE_AI_RATIO_TEST` | `0.75` | `matchers.filters` — Lowe |
| `LE_AI_CROSS_CHECK` | `true` | matchers — mutual NN |
| `LE_AI_MIN_MATCHES` | `10` | matchers — below ⇒ candidate skipped |
| `LE_AI_RANSAC_THRESHOLD_PX` | **`3.0`** | `geometry` (§12 C-15) |
| `LE_AI_RANSAC_MAX_ITERS` | `10000` | `geometry` |
| `LE_AI_RANSAC_CONFIDENCE` | `0.999` | `geometry` |
| `LE_AI_MIN_INLIERS` | **`12`** | `geometry.degeneracy` — H1 (§12 C-16) |
| `LE_AI_MIN_CONFIDENCE` | **`40.0`** | `pipeline.ranking` — **0–100** (§12 C-14). Below ⇒ candidate dropped. **Refusing to answer beats a confident wrong coordinate (L12).** |
| `LE_AI_RANK_MARGIN` | `10.0` | `pipeline.ranking` — 0–100. Winner must beat runner-up by this, else `status="ambiguous"` |
| `LE_AI_MAX_RESULTS` | `5` | `pipeline` — ranked candidates persisted |
| `LE_AI_SCORE_WEIGHT_FEATURE` | `0.25` | `scoring.composite` (§12 C-13) |
| `LE_AI_SCORE_WEIGHT_GEOMETRIC` | `0.35` | `scoring.composite` |
| `LE_AI_SCORE_WEIGHT_LANDMARK` | `0.30` | `scoring.composite` |
| `LE_AI_SCORE_WEIGHT_SEMANTIC` | `0.10` | `scoring.composite` |
| `LE_AI_CALIBRATION_ID` | `identity` | `scoring.calibration` — **ships uncalibrated and says so** |
| `LE_AI_SEMANTICS_ENABLED` | `false` | semantics — off: SAM is heavy and weight-dependent |
| `LE_AI_DEEP_MAX_CANDIDATES` | `8` | **★ CODE-ENFORCED cap.** CPU-only reality. |
| `LE_AI_SAM_CHECKPOINT` | *(empty)* | `semantics.sam` — empty ⇒ classical masks |
| `LE_AI_SUPERPOINT_WEIGHTS` | *(empty)* | `extractors.superpoint` |
| `LE_AI_SUPERGLUE_WEIGHTS` | *(empty)* | `matchers.superglue` |
| `LE_AI_LIGHTGLUE_WEIGHTS` | *(empty)* | `matchers.lightglue` |
| `LE_AI_LOFTR_WEIGHTS` | *(empty)* | `matchers.loftr` |
| `LE_AI_DINOV2_WEIGHTS` | *(empty)* | `extractors.dinov2` |

### 9.9 Limits, exports, misc

| Var | Default | Consumer |
|---|---|---|
| `LE_MAX_ANNOTATIONS_PER_IMAGE` | `2000` | `annotation_service` |
| `LE_MAX_BATCH_FILES` | `100` | `batch_service` |
| `LE_MAX_BATCH_BYTES` | `2147483648` | `batch_service` |
| `LE_MAX_REPLAY_EVENTS` | `5000` | `revision_service` |
| `LE_CHECKPOINT_EVERY_N_EVENTS` | `50` | `revision_service` |
| `LE_GCP_CONSISTENCY_TOLERANCE_M` | `0.5` | `gcp_service` |
| `LE_GCP_BOUNDS_SLACK_M` | `100` | `gcp_service` |
| `LE_GEOTIFF_DISAGREEMENT_M` | `50` | `match_service` — `geotiff_georeference_disagreement` flag |
| `LE_PROJECT_NAMES_UNIQUE` | `false` | `project_service` |
| `LE_EXPORT_DIR` | `./data/storage/exports` | `export_service` |
| `LE_EXPORT_FORMATS` | `csv,geojson,kml,kmz,shapefile,gpkg,dxf,pdf` | **`gis.exports`** — ★ the registry is in `__init__.py`; v1.0 named `gis.exports.registry`, a module in no tree. **Unavailable optional deps are DROPPED from `GET /capabilities`, not crashed on.** |
| `LE_EXPORT_DEFAULT_SRID` | `4326` | `gis.exports` |
| `LE_EXPORT_TTL_SECONDS` | `604800` | `tasks.maintenance` |
| `LE_EXPORT_MAX_ROWS` | `100000` | `export_service` |
| `LE_EXPORT_INCLUDE_ATTRIBUTION` | `true` | `gis.exports.*` — **★ should not be turned off; several providers' ToS require attribution on derived output** |

### 9.10 Observability

| Var | Default | Consumer |
|---|---|---|
| `LE_METRICS_ENABLED` | `true` | `observability.metrics` |
| `LE_METRICS_PATH` | `/metrics` | `main` — **not under `/api/v1`**; not part of the public contract (§12 C-42) |
| `LE_SENTRY_DSN` § | *(empty)* | `main` — empty ⇒ not initialised |
| `LE_OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty)* | `observability.tracing` — empty ⇒ no-op tracer |
| `LE_OTEL_SERVICE_NAME` | `landexplorer-api` | `observability.tracing` |

**Required metric set:** `http_requests_total{route,method,status}` · `http_request_duration_seconds{route}` · `job_duration_seconds{type,status}` · `job_queue_depth{queue}` · `imagery_tile_requests_total{provider,cache}` · `imagery_upstream_errors_total{provider}` · **`model_fallbacks_total{requested,effective,reason}`** · `gcp_adjustments_total` · `ratelimit_rejections_total{scope}` · `ratelimit_failopen_total` · `unhandled_exceptions_total{route}`.

> **`model_fallbacks_total` is deliberately a metric and not just a log line.** A fleet-wide spike in fallbacks means someone's weight volume did not mount — **that should page, not hide in `INFO`.** It is the metric that proves L1 is working in production rather than merely specified here.

**Structured JSON logs**; `request_id`, `principal`, `route`, `status`, `duration_ms`, `job_id` bound via contextvars. **Keys, tokens, and `Authorization` values are scrubbed by a logging filter before emission.**

### 9.11 Frontend (`VITE_` — build-time, **never secret**)

| Var | Default | Consumer |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | `src/api/client.ts` |
| `VITE_APP_NAME` | `LandExplorer` | `shell/TopBar` |
| `VITE_MAP_DEFAULT_CENTER` | `0,0` | `store/mapStore` |
| `VITE_MAP_DEFAULT_ZOOM` | `3` | `store/mapStore` |
| `VITE_JOB_POLL_INTERVAL_MS` | `1500` | `api/hooks/useJob` — floor for the adaptive schedule |
| `VITE_MAX_UPLOAD_MB` | **`500`** | `upload/UploadDropzone` — mirrors `LE_UPLOAD_MAX_BYTES` |
| `VITE_ENABLE_DEVTOOLS` | `false` | `main.tsx` |
| `VITE_MIN_LANDMARKS` | `4` | `annotation/AnnotationToolbar` — a homography needs ≥4 |

> **`VITE_MAP_TILE_URL` and `VITE_MAP_ATTRIBUTION` are DELETED.** The backend is the single source of truth for provider config — the SPA calls `GET /imagery/providers`. An escape hatch that lets the bundle disagree with the server about which provider's ToS applies is exactly the kind of divergence this system cannot afford.
> **`VITE_JOB_SSE_ENABLED` is DELETED** (§12 C-07). SSE is out of scope for v1.

### 9.12 Compose infrastructure (unprefixed — upstream images own these)

| Var | Default | Consumer |
|---|---|---|
| `POSTGRES_USER` | `landexplorer` | `db` service |
| `POSTGRES_PASSWORD` § | `landexplorer` | `db` service (**change in prod**) |
| `POSTGRES_DB` | `landexplorer` | `db` service |
| `POSTGRES_PORT` | `5432` | compose |
| `REDIS_PORT` | `6379` | compose |
| `LE_WEB_PORT` | `8080` | compose (nginx publish) |
| `LE_WORKER_CV_REPLICAS` | `1` | `compose.prod` |
| `LE_WORKER_IO_REPLICAS` | `1` | `compose.prod` |
| `LE_WORKER_EXPORT_REPLICAS` | `1` | `compose.prod` |

### 9.13 What "boots with zero env vars" means precisely

An honest definition, because the sloppy one is untestable:

| Claim | Guarantee |
|---|---|
| `Settings()` with `env={}` | Constructs. Zero required fields. **CI test: `test_settings_zero_env`.** |
| **`AiEngineConfig` from `Settings()` with `env={}` → `preflight()`** | **Returns a `PreflightReport`. Raises NOTHING.** ★ CI test: `test_zero_env_preflight` (IU-02). This is the claim `LE_AI_ESTIMATOR` broke. |
| `uvicorn app.main:app` with no env | Process starts. `GET /api/v1/health` → `200`. OpenAPI serves. |
| `GET /api/v1/health/ready` with no infra | **`503` + a per-dependency diagnosis**, not a stack trace |
| `docker compose up` with **no `.env`** | Full working stack. Compose supplies `db`/`redis` hostnames; `LE_IMAGERY_PROVIDER=auto` resolves to Esri (keyless). **This is L2.** |
| **`make seed && make up` with the NIC UNPLUGGED** | ★ **NEW, and it is the brief's actual requirement.** `seed_demo_data.py` seeds a demo project with `default_provider='fixture'` + committed fixture tiles ⇒ **upload → mark → match → export, offline, no weights, no GPU.** See the note below. |
| `import ai_engine`, `import gis` — zero installs | **Clean on this machine right now.** |
| `scripts/bootstrap_dev.sh` on this machine, **no network** | **Succeeds. Installs NOTHING from PyPI** (`--system-site-packages` + `--no-deps`). |
| `cd ai_engine && pytest` — after `pip install -e ./ai_engine[dev] --no-deps`; no env, no network, no GPU, no weights | Green. |
| `cd gis && pytest` — after `pip install -e ./gis[dev] --no-deps`; no env, no network | Green (fixture provider + committed GeoTIFF; **httpx/redis/geopandas/fiona/reportlab/ezdxf all absent and collection still succeeds** — §11.3). |

> **★ The offline path needed a front door that is not a test flag.** The brief's hard requirement is that the system work end to end **on this machine**, and it gives **no network guarantee**. v1.0's compose row satisfied "works out of the box" **only via Esri, which needs network** — and when Esri is unreachable, `get_tile` raises `ProviderTransportError`, which §11.6 correctly classifies as job **`failed`**. So the disconnected out-of-the-box experience was: *upload, mark landmarks, match, **job fails***. Both offline providers were unreachable by default: `fixture` was labelled **"TEST-ONLY"** and wired to `LE_TESTING` ("set by conftest"), and `local_orthophoto` self-skips because `./data/orthophotos` ships empty. **The capability existed — IU-31's e2e suite uses the fixture provider with no network — it just had no door a human could open.** Now: `LE_IMAGERY_OFFLINE=true` is a first-class supported mode in this table, `seed_demo_data.py` seeds a fixture-provider demo project, `docs/guides/offline-mode.md` documents it, and **`fixture`'s label changes from "TEST-ONLY" to "TEST + OFFLINE DEMO"** in §2.3 and §5.3 — the old comment told implementers to make it unreachable in production, which would have broken the very mode §9.6 promises.

### 9.14 Runtime dependencies — `backend/requirements.txt`

**Pinned (web/infra):** `fastapi` · `uvicorn[standard]` · `sqlalchemy[asyncio]>=2` · `alembic` · `pydantic>=2` · `pydantic-settings` · `psycopg[binary]` · `geoalchemy2` · `celery[redis]` · `redis` · `python-multipart` · `pillow` · `httpx` · `orjson` · `structlog` · `prometheus-client`.

**Pinned (CV — ★ NEW).** `numpy` · `opencv-python-headless` · `scipy`. They arrive transitively via the `ai_engine` path dep, **but §13.4 rule 7 treats `requirements.txt` as the contract**, and an unpinned transitive numpy is how a NumPy-2 ABI break reaches production on a Tuesday. `headless` deliberately: the container has no X11 and `opencv-python` would pull GUI libs into a worker image.

**Pinned (geo — ★ PROMOTED from Optional, for the BACKEND IMAGE ONLY).** `pyproj` · `rasterio`.

> **★ GDAL was a dev-box fact generalised to prod, and it silently killed the accuracy path.** §11.3's entire degradation story rests on GDAL being present, and §0.1 records GDAL 3.8.4 as installed **here** — but the contract never carried that requirement into the image, and §9.14's pinned list had **no GDAL, no rasterio, no pyproj, and not even numpy/opencv/scipy**. GDAL's Python bindings are **not pip-installable from a plain wheel**: they need `libgdal-dev` plus a version-matched `pip install GDAL==<libgdal version>`, or the system `python3-gdal`. So an image built from §9.14 as written shipped with **neither raster backend and no pyproj**, and every consequence was silent (see §7.1's `raster` check for the full chain: dead `local_orthophoto`, rejected GeoTIFF rows, uncomputable `total_ce90_m`). On the **dev box** `pyproj`/`rasterio` are genuinely optional because system GDAL substitutes; **in the image nothing substitutes.** They are pinned there and optional here, and §0.1 is the reason the two differ.

**§2.6 — `infra/docker/backend.Dockerfile` MUST:** `apt-get install -y libgdal-dev gdal-bin`, install a **version-matched** GDAL binding (`pip install GDAL==$(gdal-config --version)`), and **run `scripts/check_env.py` at build time with its output asserted** — so an image that lost its raster backend fails the *build*, not a surveyor's export.

**Optional (degrade gracefully — §11): `geopandas` · `fiona` · `shapely` · `ezdxf` · `reportlab` · `boto3` · `torch` · `kornia`.** Each is bound at **call time** (§11.3) and reported via `is_available()`.

**Not present, deliberately:** `sse-starlette` (§12 C-07) · `opencv-contrib-python` (§0.1 — `cv2.xfeatures2d` is ABSENT and nothing may reference it) · `pgvector`.

---

## 10. Dependency rules

**Enforced by `.importlinter` via `scripts/verify_boundaries.sh` in CI. This is a build failure, not a code-review opinion.**

### 10.1 The layer stack

```
app  →  gis  →  ai_engine
```
**It never inverts.**

### 10.2 Per-module contract

| Module | Single responsibility | MAY import | MUST NOT import |
|---|---|---|---|
| `ai_engine.types` | The shared vocabulary of the CV domain. Value objects only. | `numpy`, stdlib | **everything else** — must stay import-cheap forever; `gis` depends on it |
| `ai_engine.models` | Registry, lazy load, availability, device | `torch` *(guarded, in `torch_guard` only)*, stdlib, `ai_engine.{types,errors}` | `cv2` algorithms, `gis`, `app`, **network** (never downloads) |
| `ai_engine.extractors` | image → keypoints + descriptors | `cv2`, `numpy`, `ai_engine.{types,errors,models,logging}` | `gis`, `app`, direct `torch`, any network/IO |
| `ai_engine.matchers` | descriptors/images → correspondences | `cv2`, `numpy`, `scipy`, `ai_engine.{types,errors,models,extractors}` | `gis`, `app`, direct `torch`, IO |
| `ai_engine.geometry` | correspondences → homography/pose **in pixels** | `cv2`, `numpy`, `scipy`, `ai_engine.{types,errors}` | **anything CRS/geo-aware**, `gis`, `app`, direct `torch` |
| `ai_engine.semantics` | optional masks to gate features | `cv2`, `numpy`, `scipy`, `ai_engine.{types,models}` | `gis`, `app`, direct `torch` |
| `ai_engine.landmarks` | landmark-steered matching mechanisms | `cv2`, `numpy`, `ai_engine.{types,extractors}` | `gis`, `app`, direct `torch` |
| `ai_engine.scoring` | match quality → confidence | `numpy`, `scipy`, `ai_engine.types` | `cv2`, `gis`, `app`; **must not compute GSD** — it is passed in on `CandidateWindow` |
| `ai_engine.pipeline` | orchestrate steps, emit progress | all of `ai_engine.*` | `gis`, `app`, `celery`, DB, network |
| `gis.tiles` | slippy math, mosaicking, geotransforms | `numpy`, stdlib | **everything else** — no I/O, no pyproj, no osgeo, no optional deps |
| `gis.crs` | **THE ONLY `pyproj` AND `osgeo` import site** | `pyproj`, `osgeo`, `numpy`, `gis.{types,tiles}` | `cv2`, `ai_engine`, `app`, network |
| `gis.raster` | raster IO via the shim | `gis.{types,rasterio_shim,tiles}`, `numpy` | `cv2`, `ai_engine`, `app`, network |
| `gis.imagery` | fetch pixels from a provider; carry attribution | `httpx` *(call-time)*, `PIL`, `numpy`, `redis` *(call-time)*, `gis.{types,tiles,crs,raster,errors}` | `ai_engine`, `app`, `sqlalchemy`, **Google Earth in any form** |
| `gis.candidates` | produce candidate windows for a search hint | `gis.{tiles,crs,imagery,geometry,errors}`, **`ai_engine.types` and `ai_engine.errors` ONLY** *(the latter for `WindowFetchError` — §4.10)* | `ai_engine.{extractors,matchers,geometry,scoring,pipeline,models,runtime,heatmap,semantics,landmarks}`, `app`, DB |
| `gis.accuracy` | pixel covariance → **true metres**; the single producer of `AccuracyEstimate` | `numpy`, `gis.{types,tiles,crs}` | `cv2`, `ai_engine`, `app` |
| **`gis.pose`** | window-frame pose → geography (rotation + **grid convergence**) | `numpy`, `gis.{types,tiles,crs}` | `cv2`, `ai_engine`, `app` |
| **`gis.heatmap`** | per-window pixel heatmaps → one true-metre geographic grid | `numpy`, `gis.{types,tiles,crs,geometry}`, **`ai_engine.types` ONLY** | `ai_engine.*` (rest), `app`, DB |
| **`gis.elevation`** | lon/lat → elevation + vertical CE90 | `numpy`, `gis.{types,rasterio_shim,crs,errors}`, `httpx` *(call-time)* | `cv2`, `ai_engine`, `app`, `sqlalchemy` |
| `gis.exports` | GCP records → files | `geopandas`, `shapely`, `reportlab`, `ezdxf` *(all call-time)*, `gis.{types,crs}` | `ai_engine`, `app`, DB, **the ORM** |
| `app.core` | settings, logging, errors, constants | `pydantic-settings`, `structlog`, stdlib | `app.{models,schemas,db,services,tasks,api}`, `ai_engine`, `gis` |
| `app.models` | table definitions | `sqlalchemy`, `geoalchemy2`, `app.{models.base,core.constants}` | `fastapi`, `app.schemas`, `ai_engine`, `gis` |
| `app.schemas` | the wire contract | `pydantic`, `app.core.constants` | `sqlalchemy`, `app.models`, `ai_engine`, `gis`, `cv2` |
| `app.db` | sessions, **all SQL** | `sqlalchemy`, `geoalchemy2`, `app.{models,core}` | `fastapi`, `celery`, `ai_engine`, `gis`, `app.services` |
| `app.storage` | bytes in/out of an object store | `boto3` (opt), stdlib, `app.core.config` | `fastapi`, `sqlalchemy`, `ai_engine`, `gis` |
| `app.services` | orchestration; **the ONLY both-sides layer** | `app.{db,models,schemas,core,storage}`, `ai_engine`, `gis`. Enqueues via **`app.core.queue.JobQueue`** (a Protocol) | `fastapi` (no `Request`/`Depends` in a service), **`celery`** |
| `app.tasks` | Celery tasks, the state machine, retries; **the COMPOSITION ROOT for CV jobs** | `celery`, `app.{services,db,core}`, `ai_engine`, `gis` | `fastapi` |
| `app.api.v1` | HTTP: validate, delegate, serialise | `fastapi`, `app.{schemas,services,core}` | `app.{db,models}`, `app.tasks`, `ai_engine`, `gis`, `cv2` |
| `app.api.deps` | the HTTP composition root — sessions, entity loaders, provider handles | `fastapi`, `app.{db,models,services,core,storage}`, `gis.imagery` | `ai_engine`, `cv2`. **★ EXEMPT from `api-not-db` — §6.4 states why.** |
| `app.observability` | metrics, tracing | `prometheus-client`, `structlog` | domain modules |
| `frontend/src/api` | HTTP transport + error normalisation | `fetch`, generated types | React, MUI, Zustand |
| `frontend/src/api/hooks` | server state via React Query | `@tanstack/react-query`, `src/api` | MUI components, Konva, Leaflet |
| `frontend/src/store` | **local UI state only** | `zustand` | `src/api`, React Query, **any server data** |
| `frontend/src/lib` | pure functions | — | React, stores, `src/api` |
| `frontend/src/components` | presentation | MUI, Leaflet, Konva, `src/api/hooks`, `src/store`, `src/lib` | `src/api` **directly** (must go through a hook) |
| `frontend/src/pages` | routing + composition | components, hooks | `src/api` directly |

> **★ Who enqueues — the contradiction, and the ruling.** §2.4 said `match_service.py` *"builds AiEngineConfig + WindowSource, **enqueues**"* — and `.delay()` requires celery — while §10.2's `app.services` row, §10.4's `services-no-fastapi` contract and §3's IU-19 import column **all forbade celery in services.** The contract said both that services enqueue and that they cannot. Worse, §4.10 named `backend.services.match_service` *"the composition root"* that injects the live `WindowSource` — **and a `TileWindowSource` holds an httpx session, so it is not broker-serialisable and CANNOT cross into a Celery task.**
>
> **The ruling splits the two concerns rather than picking a loser, because both underlying instincts were right:**
> 1. **The service owns job creation** — §13.1 tests the 10-condition pre-flight ladder in the service layer with mocked repos, and the `match_jobs` INSERT and the submit must be **one transaction-ordered unit** (the contract itself notes `celery_task_id` is *"NULL between INSERT and `.delay()`"*, implying one owner does both). So the service submits.
> 2. **Services stay framework-free** — that is the *stronger* rule, and Celery is as much a framework as FastAPI. So the service submits through **`app.core.queue.JobQueue`**, a Protocol (IU-15) whose Celery implementation (IU-20) is injected at the composition root. Same Protocol/impl split as `WindowSource`, for the same reason, and it makes the IU-18/19 mocked-repo tests **honest** rather than mock-the-broker theatre.
> 3. **`match_service` builds a plain JSON-serialisable `MatchJobSpec`** — provider name, resolved AOI, zoom levels, `AiEngineConfig` as a dict — and **never** a `WindowSource`. **`app.tasks.matching.match_image_task` is the composition root**: inside the worker it constructs the provider, the `TileWindowSource` and the `MatchContext`. §2.4 and §4.10 are corrected to say so.
> 4. **`app.api` loses `app.tasks` entirely.** Routers delegate to services; services submit. One path.

### 10.3 The ONE permitted cross-package import

**`gis.candidates` may import `ai_engine.types` and NOTHING ELSE from `ai_engine`** — to construct `CandidateWindow` and to reference the `WindowSource` Protocol.

*(Plus the single narrow addition this pass required: `gis.candidates` and `gis.heatmap` may import **`ai_engine.errors.WindowFetchError`** — the seam's exception type, which §4.10 requires an implementation to raise and which must live on the side that declares the Protocol.)*

Permitted because:
- `ai_engine.types` imports **only numpy and stdlib** — it is cheap and stable and cannot drag in `cv2` or `torch`.
- `WindowSource` is a **structural** `typing.Protocol`. `TileWindowSource` satisfies it **without inheriting from it**; the import exists purely so mypy can verify conformance.
- **The dependency points `gis → ai_engine`, matching the layer contract. It never inverts.**

*Alternative considered and rejected: a fourth `contracts` package holding six dataclasses. Rejected as ceremony that would be imported by everything and owned by no one.*

### 10.4 `.importlinter` — the CI gate

> **★ `allow_indirect_imports = true` on every `forbidden` contract below, and the reason is not a workaround.** These are **direct-import rules expressed with a transitive-import tool.** import-linter's `forbidden` contract flags **indirect chains by default** and prints the full chain — and §10.2 *explicitly permits* `app.api → app.services` and `app.services → app.db/app.models/ai_engine/gis(→cv2)`. So `api-not-db` would fail on `app.api → app.services → app.db` **for every one of its five forbidden modules**, and since §13.4 makes `verify_boundaries.sh` the definition of done for every module, **no module could ever be done.** The same transitive problem hit `gis-purity` (via the `types→models` import, now fixed) and `torch-single-entry` (`ai_engine.pipeline → ai_engine.models → torch_guard → torch` — a chain the design **requires**). **The intent everywhere is "no DIRECT import"; the transitive property is already carried by the `layers` contract**, which is the right tool for it.
>
> Note honestly what this costs: `allow_indirect_imports` makes `cv2` in `api-not-db`'s forbidden list **toothless**. So the L5 guarantee is kept where it actually bites — in §10.5's grep gates.

```ini
[importlinter]
root_packages = ai_engine, gis, app

[importlinter:contract:layers]
name = Package layering
type = layers
layers =
    app
    gis
    ai_engine

[importlinter:contract:ai-engine-purity]
name = ai_engine imports no web/db/geo stack
type = forbidden
source_modules = ai_engine
forbidden_modules =
    fastapi, sqlalchemy, celery, pydantic, redis, httpx,
    pyproj, rasterio, geopandas, shapely, osgeo,
    gis, app
allow_indirect_imports = true

[importlinter:contract:gis-purity]
name = gis imports no web/db stack and no CV algorithms
type = forbidden
source_modules = gis
forbidden_modules =
    fastapi, sqlalchemy, celery, pydantic, app,
    ai_engine.extractors, ai_engine.matchers, ai_engine.geometry,
    ai_engine.scoring, ai_engine.semantics, ai_engine.landmarks,
    ai_engine.pipeline, ai_engine.models, ai_engine.runtime, ai_engine.heatmap
allow_indirect_imports = true

# ★ NEW. The positive statement of §10.3: gis may see ai_engine.types and ai_engine.errors,
#   and nothing else. gis-purity above lists subpackages and would silently miss a new one;
#   this contract fails closed. CI additionally ASSERTS the allowed chain still exists
#   (gis.candidates -> ai_engine.types), so nobody "fixes" the seam by deleting it.
[importlinter:contract:gis-ai-types-only]
name = gis may import only ai_engine.types and ai_engine.errors
type = forbidden
source_modules = gis
forbidden_modules =
    ai_engine.config, ai_engine.version, ai_engine.logging,
    ai_engine.models, ai_engine.extractors, ai_engine.matchers,
    ai_engine.geometry, ai_engine.semantics, ai_engine.landmarks,
    ai_engine.scoring, ai_engine.heatmap, ai_engine.pipeline,
    ai_engine.runtime, ai_engine.windows
allow_indirect_imports = true

[importlinter:contract:gis-tiles-pure]
name = gis.tiles is pure math
type = forbidden
source_modules = gis.tiles
forbidden_modules = pyproj, osgeo, rasterio, httpx, redis, PIL, gis.imagery, gis.crs
allow_indirect_imports = true

# ★ RENAMED (was pyproj-single-entry) and osgeo ADDED. §10.2 grants gis.crs BOTH, and §11.3
#   REQUIRES the osr fallback — so the rule is "these two live in exactly one module", and it
#   now lives in exactly one place too.
[importlinter:contract:crs-single-entry]
name = pyproj and osgeo are imported in exactly one module
type = forbidden
source_modules =
    gis.tiles, gis.geometry, gis.accuracy, gis.pose, gis.heatmap,
    gis.exif, gis.imagery, gis.candidates, gis.exports, gis.elevation
forbidden_modules = pyproj, osgeo
allow_indirect_imports = true
# permitted only in gis.crs (both) and gis.rasterio_shim (osgeo.gdal only)

[importlinter:contract:torch-single-entry]
name = torch is imported in exactly one module
type = forbidden
source_modules =
    ai_engine.extractors, ai_engine.matchers, ai_engine.semantics,
    ai_engine.geometry, ai_engine.scoring, ai_engine.landmarks,
    ai_engine.pipeline, ai_engine.types
forbidden_modules = torch, torchvision, kornia
allow_indirect_imports = true
# permitted only in ai_engine.models.torch_guard

# ★ source_modules is app.api.V1 — the ROUTERS. app.api.deps is deliberately exempt; §6.4
#   states the reasoning at length. Routers still may not reach the DB.
[importlinter:contract:api-not-db]
name = Routers do not touch the DB or the domain packages directly
type = forbidden
source_modules = app.api.v1
forbidden_modules = app.db, app.models, app.tasks, ai_engine, gis, cv2
allow_indirect_imports = true

[importlinter:contract:schemas-not-orm]
name = schemas never import the ORM
type = forbidden
source_modules = app.schemas
forbidden_modules = sqlalchemy, geoalchemy2, app.models, ai_engine, gis
allow_indirect_imports = true

# ★ celery REMAINS forbidden — and is now ACHIEVABLE, because services enqueue through
#   core.queue.JobQueue (a Protocol) rather than .delay(). §10.2's ruling.
[importlinter:contract:services-no-framework]
name = services are framework-free
type = forbidden
source_modules = app.services
forbidden_modules = fastapi, starlette, celery
allow_indirect_imports = true
```

### 10.5 The grep gates (`scripts/verify_boundaries.sh`) — ★ THE SINGLE NORMATIVE DEFINITION

Import-linter cannot catch a string. **§1's L3/L4 reference this section; they do not restate it.** (v1.0 defined each gate twice with different patterns — `orb` vs `orb_create`, `quadkey|geodesic` present in one and absent in the other. Two definitions of one gate is two gates, and the looser one is the one that passes.)

**Two rules apply to every gate below, and both exist because v1.0's gates failed on the contract's own mandated source:**

1. **Code, not prose.** Every gate pipes through `strip_comments` (below). L3's pattern is case-insensitive over the whole subtree, and §4.10's **verbatim, mandated** `windows.py` contained `crs: str  # OPAQUE. e.g. "EPSG:3857"` and `# ... needs latitude` — **two hits, on the two comments explaining the boundary the gate enforces.** IU-01 is the first unit in the build order; it would have gone red on its first commit. (§4.10's comments are *also* reworded — belt and braces, and the rewording is better prose anyway.)
2. **Source, not tests.** §2.2 places `tests/` **inside** `ai_engine/src/ai_engine/`, so the L3 gate scanned the test suite too — and IU-03's mandated test *"Nothing imports `cv2.xfeatures2d`"* **must contain the literal string to assert on it**, so the repo-wide `xfeatures2d` gate failed on the very test that proves the property. `--exclude-dir=tests` throughout.

```bash
# Comment stripper: drop full-line comments and trailing comments, keep code.
strip_comments() { sed -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d'; }
py_src() { grep -rn --include='*.py' --exclude-dir=tests "$@"; }

# ── L3 — ai_engine does not know what a CRS is ──────────────────────────────
py_src -iE 'epsg|pyproj|latitude|longitude|lonlat|lon_lat|mercator|slippy|quadkey|geodesic' \
       ai_engine/src/ai_engine/ | strip_comments | grep -v 'noqa: L3'

# ── L3b — ai_engine never INDEXES the opaque geotransform (§4.24(4)) ────────
#   The 1/cos(phi) pose bug is a READ of a field it is allowed to CARRY, so the
#   type system cannot catch it and only a grep can.
py_src -E 'geotransform\s*\[' ai_engine/src/ai_engine/

# ── L4 — gis does not know what a descriptor is ─────────────────────────────
py_src -iE 'sift|orb_create|akaze|brisk|ransac|magsac|descriptor|findhomography|xfeatures2d' \
       gis/src/gis/ | strip_comments

# ── §0.1 — opencv-contrib is ABSENT on this machine ─────────────────────────
#   Scoped to source. IU-03's runtime assertion is the STRONGER check anyway: it
#   catches getattr(cv2, 'xfeatur' + 'es2d'), which no grep can see.
py_src 'xfeatures2d' ai_engine/src/ai_engine gis/src/gis backend/app

# ── Google Earth is structurally excluded ───────────────────────────────────
py_src -iE 'kh\.google|khms|google.*earth|earth.*google' gis/src/gis/ | strip_comments

# ── Settings is read exactly once ───────────────────────────────────────────
py_src 'os.getenv\|os.environ' backend/app/ | grep -v 'core/config.py'

# ── L5 — the API never performs CV (where allow_indirect_imports made the ────
#        import-linter rule toothless, this is where it bites)
py_src 'import cv2\|import torch' backend/app/api/

# ── no ad-hoc raster/CRS backend fallbacks ──────────────────────────────────
#   ★ crs.py is EXEMPT: §10.2 grants it osgeo and §11.3 REQUIRES the osr fallback.
#   Verified: pyproj is MISSING here and osgeo.osr is present, so osr is the ONLY
#   working path for anything that is not 4326<->3857 — and §13.2 commits
#   synthetic_ortho.tif at EPSG:32633 (UTM 33N) with §13.3 requiring a <1e-6 px
#   round-trip on it, which the closed-form NumPy fallback CANNOT do. Without this
#   exemption either the gate fails or the entire gis CRS suite, GeoTIFF ingest and
#   gis/accuracy.py's UTM math fail with CrsError on the only machine we can test on.
py_src 'import rasterio\|from osgeo' gis/src/gis/ \
  | grep -vE 'rasterio_shim\.py|crs\.py'
```

**All of the above must return EMPTY.** The tighter structural rule these greps approximate — *`osgeo` must not appear in `gis.tiles`, `gis.geometry`, `gis.accuracy`, `gis.pose`, `gis.exif`, `gis.imagery`, `gis.candidates`, `gis.exports`, `gis.elevation`* — now lives in the `crs-single-entry` import-linter contract (§10.4), i.e. **in one place, expressed with the tool that understands imports.**

### 10.6 Why `ai_engine` and `gis` are separate installable packages

The highest-leverage decision in the repo, so the reasoning is spelled out rather than asserted.

1. **They are testable *today*, on this machine, with zero RUNTIME installs.** `fastapi`, `sqlalchemy` and `pydantic` are **not installed here**. If matching lived in `backend/app/services/`, importing that module would transitively pull `fastapi` and **every CV test on this machine would fail at collection time — before a single algorithm ran**. Because `ai_engine` depends only on numpy/opencv/scipy, `cd ai_engine && pytest` runs after one `pip install -e ./ai_engine[dev] --no-deps` (pytest is a dev dep, not a runtime one — §0.1). **The package boundary is not architectural taste; it is the difference between a testable and an untestable repo on the actual hardware.**
2. **The dependency graph is acyclic and points the right way.** `ai_engine` cannot import a SQLAlchemy model, so a schema change cannot break RANSAC. `gis` cannot import a FastAPI dependency, so an auth refactor cannot break tile math.
3. **Different change rates, reviewers, and test rigs.** Feature matching is validated with synthetic homographies and numeric tolerances; HTTP handlers with status codes and JSON shapes. Fusing them produces a suite that needs Postgres running to check a ratio test.
4. **Reuse beyond the web app is a real requirement.** `python -m ai_engine`, a notebook, a QGIS plugin, and a future CLI all need matching without an HTTP server. Air-gapped surveyors are a plausible segment.
5. **Forced interface honesty.** A shared process makes it trivially easy to reach into a DB session from inside a matcher "just for this one lookup". A package boundary makes that require a new dependency in `pyproject.toml` — **a visible, reviewable, refusable act.** The seams stay clean because violating them is *inconvenient*.

**The cost, stated honestly:** three `pyproject.toml` files, editable installs in dev, and path dependencies in the Docker build. A few hours once, versus a permanently untestable core.

---

## 11. The fallback policy

**Stated once, normatively. This section is the definition of L1 and L11.**

### 11.0 The one-sentence rule, and its two exceptions

> **A missing weight, a missing key, a missing optional dependency, or an absent GPU is a `WARNING` log line, a `WarningItem` on the response, a metric increment, and a fallback — never a traceback, and never silent. It is never a 4xx/5xx WHEN IT AFFECTS A DEFAULT.**
>
> **The two exceptions (§11.4), stated here so the law and the table cannot disagree:**
> 1. A client **explicitly requests** an unconfigured **provider** → `503 PROVIDER_NOT_CONFIGURED`. An explicit request is not a default.
> 2. Any unavailability under `LE_IMAGERY_STRICT=true` or `LE_AI_STRICT_BACKEND=true` → raise. *Dev is forgiving; prod is loud.*
>
> **The asymmetry is deliberate, not accidental:** an explicitly requested unconfigured **provider** is a 503, but an explicitly requested missing **weight** (`matcher:"superglue"`) is a `202` + fallback. **Imagery changes the answer's provenance; a matcher changes only its accuracy.** Silently serving 10 m Sentinel when the operator paid for 0.3 m Mapbox is a worse failure than a 503; silently serving SIFT instead of SuperGlue is a reported accuracy trade on a path that is fully operational. Both are reported; only one is refusable.

### 11.1 Deep model weights missing (the default state on this machine)

| Stage | Behaviour |
|---|---|
| **Boot** | `ai_engine.models.preflight()` runs `resolve_with_fallback` for every configured component. It uses `importlib.util.find_spec` (**not import** — no side effects, no CUDA init, no 2-second torch import to discover we won't use it) then checks weight existence **and sha256**. ★ **It runs EXACTLY ONCE, in `main.py`'s lifespan, and the `PreflightReport` is cached on `app.state`.** |
| **Report** | `GET /api/v1/capabilities` **reads the cached report and NEVER re-resolves.** It lists every component with `available` · `reason` · `fallback`. `GET /api/v1/health/ready` reports `models: degraded` with the missing list and the message *"Classical CV pipeline (SIFT/ORB + FLANN/BF + RANSAC) is fully operational."* **`models` NEVER affects readiness.** |
| **Request** | `POST /images/{id}/match` with `matcher: "superglue"` on a weightless box is **accepted**. It returns `202`. *(Contrast §11.4's last row: an explicitly requested unconfigured PROVIDER is a 503. §11.0 explains the asymmetry.)* |
| **Job** | At stage **`resolving_models`** — **the instant it is known, not at the end** — the worker appends `WarningItem{code:"MODEL_WEIGHTS_MISSING", field:"matcher", requested:"superglue", effective:"flann"}`, sets `match_jobs.degraded = true` and `degradation_reason`, increments `model_fallbacks_total{requested="superglue",effective="flann"}`, and **continues on the classical path**. |

> **★ `GET /capabilities` must not re-hash weight files.** §11.1's Boot row defines preflight as `resolve_with_fallback` for every component, which per §4.14 step 3 checks *"every `requires_weights` resolvable **AND sha256 matches**"*. **SAM ViT-H is ~2.4 GB**; DINOv2 and LoFTR are hundreds of MB. Re-running sha256 over those **on every `/capabilities` call** is seconds of blocking disk I/O inside a route — and §8 has the frontend calling it via `useCapabilities`. §7.1 had already noticed the cost for *readiness* and specified the cheap version there (`os.path.exists`, 60 s TTL, never gates readiness) — **but that discipline was never applied to `/capabilities`, which is the endpoint that actually reports the detail.** Cache it once, at boot, where the cost is paid once. `LE_AI_PREFLIGHT_TTL_SECONDS` (default `0` = cache for the process lifetime) exists for operators who mount a weights volume live; otherwise **`scripts/download_models.py` requires a worker restart to take effect**, and that is stated in the script's own output.

> **★ `resolving_models` is a real `JobStage` now.** §11.1 and §11.8 both said *"at stage `loading_model`"* — a stage that **exists only for `segment` and `suggest_landmarks`**. The `match` stage list had no such value, so on the job type where a missing SuperGlue weight matters most, **the worker had no legal stage to write.** §6.2 adds `resolving_models` as `match`'s second stage, weight 0.0.
| **Result** | The job **SUCCEEDS**. `match_results.degraded = true` and `feature_matcher_used = 'flann'` — **the row does not lie about what produced the numbers.** |
| **UI** | An **unrequested** fallback (the fresh-machine default) renders an informational chip: *"Matched with SIFT + FLANN"*. A **requested-and-denied** one renders a warning. The distinction is `warnings[].requested !== null`. |

**A corrupt or truncated weight file is treated EXACTLY like a missing one.** A half-downloaded `.pth` that imports and then produces garbage is far worse than one that is simply absent.

**Weights are NEVER auto-downloaded.** A silent multi-hundred-MB fetch inside a Celery task, on a machine that may be air-gapped, triggered by a user clicking "Match", is an unacceptable failure mode and an unacceptable surprise. `scripts/download_models.py` is opt-in, prints each model's licence, and is never invoked at build or boot.

**Fallback chains are provably terminating.** Terminal specs (`fallback=None`) must have no `requires_weights` and no `requires_packages` beyond the base install — **asserted at registration time**. The chains: `superpoint → sift` · `dinov2 → sift` · `asift → sift` · `akaze → orb` · `brisk → orb` · `sift → ⊥` · `orb → ⊥` · `superglue → flann` · `lightglue → flann` · `loftr → flann` (via source swap) · `flann → bf` · `bf → ⊥` · `sam → classical` · `dinov2_seg → classical` · `classical → ⊥`.

### 11.2 GPU absent (`torch.cuda.is_available() == False`)

**Device unavailability is routed through the SAME registry fallback branch as missing weights** (step 4 of `resolve_with_fallback`). It is the same failure class and gets the same treatment: WARN, fall back, keep serving. **On the verified dev box this is the branch that actually fires.**

`LE_AI_DEVICE=auto` → `cpu`. `LE_AI_DEVICE=cuda` when unavailable → **WARN + `cpu`**, never a crash. **Never infer CUDA from the wheel name** — `torch 2.11.0+cu130` is installed here and there is no GPU.

`LE_AI_DEEP_MAX_CANDIDATES=8` is **code-enforced** (`AiEngineConfig.validate()` asserts it), because LoFTR/SAM are 2–8 s per 1024² image on CPU.

### 11.3 Optional Python dependencies missing — ★ THE CALL-TIME BINDING RULE

> **NORMATIVE, and general: any module whose dependency is not in its package's BASE install binds that dependency INSIDE the function that uses it, never at module scope. `is_available()` / `is_configured()` / `capabilities()` / `probe()` MUST be importable and callable with the dependency absent.**

> **★ v1.0 mandated this for EXACTLY ONE module (`rasterio_shim.py`) and then violated it six times — which made `cd gis && pytest` impossible, not merely red.** Verified absent here: **httpx, redis, geopandas, fiona, reportlab, ezdxf** (and pytest itself — §0.1). Meanwhile §2.3 mandates `gis/imagery/providers/__init__.py` do **EXPLICIT registration of all seven providers**, and esri/mapbox/bing/sentinel/google_static all sit on `gis/imagery/http.py` → `import httpx` **at module scope** → **ImportError at COLLECTION**, before a single test ran. `cache/__init__.py` exposing `redis_cache.py` → `import redis` → same. `exports/__init__.py` holds the `EXPORT_WRITERS` registry, which must import all four degradable writers → geopandas/fiona/ezdxf/reportlab → same. And §13.1's IU-11 is *"PARAMETRISED OVER EVERY PROVIDER"* and IU-13 *"parametrised over every writer"*, so **both suites necessarily import all of them.**
>
> The contradiction was already visible inside §11.3 itself: the table below **promises** `is_available() → (False, "requires fiona")` **rather than a crash** — which is **unimplementable if the import is at module scope.** The rule was right; its scope was one module too narrow.

| Dependency | Absent ⇒ |
|---|---|
| `rasterio` | `gis/rasterio_shim.py` binds **rasterio → GDAL → typed error at CALL time**, never at import. GDAL 3.8 is installed here; rasterio is not. **Without this, `local_orthophoto` — the single highest-accuracy, fully-offline provider — would be dead on the only machine we can test on.** `probe()` reports which backend bound, and `/health/ready` + `/capabilities` surface it (§7.1). |
| `pyproj` | `gis/crs.py` falls back to `osgeo.osr`, then to closed-form NumPy for 4326↔3857 (the only hot-path transform), then to a typed `CrsError` at **call** time for anything else. |
| **`httpx`** ★ | `gis/imagery/http.py` binds it **inside the request function**. `import gis.imagery.providers` **succeeds**; every provider's `__init__`, `is_configured()`, `capabilities()` and `name` work. Only an actual fetch raises `ProviderTransportError`. In `gis`'s **base** deps (the registry imports every provider eagerly, so it cannot be an extra) **and** call-time bound (so the suite collects without it). Both, deliberately. |
| **`redis`** ★ | `gis/imagery/cache/redis_cache.py` binds it inside the method; `cache/__init__.py` exposes it via a **module `__getattr__`**. Absent ⇒ `RedisTileCache.is_available()` → `(False, "requires redis")` and the registry falls back to `DiskTileCache`. `gis[redis]` extra. |
| `geopandas` / `fiona` | `ShapefileExportWriter.is_available()` → `(False, "requires fiona")`. **The format is DROPPED from `GET /capabilities`, not crashed on.** Same for `gpkg`. |
| `reportlab` | `PdfReportWriter.is_available()` → `(False, "requires reportlab")`. Dropped. |
| `ezdxf` | `DxfExportWriter` dropped. |
| `boto3` | Only reachable with `LE_STORAGE_BACKEND=s3`; that is a **configuration error**, not a degradation → `ConfigurationError` at boot. |
| `torch` | Every deep component falls back per §11.1. |

**CSV, GeoJSON, KML and KMZ are stdlib-only and can NEVER degrade** — so the surveyor can always get their coordinates out, regardless of environment.

**The tests that keep this true** (§13.1): IU-11 and IU-13 each import the **full registry** with `httpx`, `redis`, `geopandas`, `fiona`, `reportlab` and `ezdxf` **blocked in `sys.modules`**, and assert **collection succeeds** and every unconfigured component **reports its reason**. IU-11's provider-contract test asserts `__init__`/`is_configured`/`capabilities`/`name` for **unconfigured** providers, and exercises fetching only for the two that are configured offline (`fixture`, `local_ortho`).

### 11.4 Imagery keys missing

**`LE_IMAGERY_PROVIDER` has two modes, and naming them is the fix:**

| `LE_IMAGERY_PROVIDER` | Meaning |
|---|---|
| **`auto`** (default) | **PREFERENCE.** Walk `LE_IMAGERY_FALLBACK_CHAIN` in order; take the first `is_configured()` provider. |
| an explicit name | **That provider.** The chain is **error-recovery only** (and only when `LE_IMAGERY_STRICT=false`). |

> **★ v1.0's chain was unreachable by construction, and its own rationale described a mechanism it did not implement.** `LE_IMAGERY_PROVIDER` defaulted to `esri_world_imagery` and `LE_IMAGERY_FALLBACK_CHAIN` to `local_orthophoto,esri_world_imagery`, justified as *"`local_orthophoto` FIRST: if the operator mounted orthophotos they are definitionally better than any web tile source"* — and §12.5 leaned on it again (*"`local_orthophoto` is the only path where total error is knowable — which is why it heads the default fallback chain"*). **But §11.4 defined the chain as walked ONLY when the NAMED provider is unconfigured.** Esri is keyless, so `is_configured()` is **always True**, so **the chain was never consulted** — and an operator who dropped GeoTIFFs into `./data/orthophotos` still got Esri tiles **and never learned why.** The ordering's rationale describes a **preference** mechanism; §11.4 implemented an **error-recovery** mechanism. Only one could be true.
>
> `auto` makes both true: an empty ortho dir self-skips → Esri (**zero-config preserved, L2 intact**), and a populated one wins (**the rationale becomes real**). IU-11 asserts exactly that: *with a populated ortho dir and zero env vars, which provider does the registry return?*

| Situation | Behaviour |
|---|---|
| A keyed provider's env var is empty | `is_configured()` → `False`. **The provider is REGISTERED but reports unavailable.** `GET /imagery/providers` lists it with `configured: false` and a reason. |
| `LE_IMAGERY_PROVIDER=auto`, ortho dir empty | Chain walks past `local_orthophoto` → **Esri**. No branching, no warning — this is the designed zero-config path. |
| `LE_IMAGERY_PROVIDER=auto`, ortho dir populated | **`local_orthophoto`.** The highest-accuracy path is taken *because it is available*, which is what the chain order always claimed. |
| `LE_IMAGERY_PROVIDER` names a keyed provider with no key, `LE_IMAGERY_STRICT=false` | **WARN + fall back down `LE_IMAGERY_FALLBACK_CHAIN`.** `chip.provider_name` is set to what was **actually** used, so a downstream report can never misattribute imagery. |
| Same, `LE_IMAGERY_STRICT=true` | **`ProviderNotConfiguredError` → `503 PROVIDER_NOT_CONFIGURED`.** *Dev is forgiving; prod is loud.* Silently serving 10 m Sentinel imagery when the operator paid for and expected 0.3 m Mapbox is a **worse** failure than a 503. **(L11 exception 2 — §11.0.)** |
| A client explicitly requests an unconfigured provider on `POST /match` | **`503 PROVIDER_NOT_CONFIGURED`**, always — regardless of `LE_IMAGERY_STRICT`. An explicit request is not a default. **(L11 exception 1 — §11.0. Contrast §11.1's Request row: an explicitly requested missing WEIGHT is a 202 + fallback. The asymmetry is deliberate and §11.0 says why.)** |
| `LE_LOCAL_ORTHO_DIR` empty | `local_orthophoto.is_configured()` → `False`, self-skips the chain. **The zero-config machine lands on Esri with no branching.** |
| `LE_IMAGERY_OFFLINE=true` | Only `local_orthophoto` and `fixture` are resolvable. **Air-gapped mode — a first-class supported mode (§9.13), not a test flag.** |

**`__init__` MUST NOT raise on a missing credential.** Construction always succeeds; `is_configured()` reports readiness. A provider that throws in its constructor takes down the registry, the capabilities endpoint, and the UI that would have told you the key was missing.

### 11.5 Legal constraints are enforced mechanically, not by documentation

| Constraint | Mechanism |
|---|---|
| Google Earth is out of scope | **No provider, no scaffolding, no enum label.** `imagery_provider` has no `google_earth` member — **unrepresentable in the type system**. CI greps for Earth endpoint patterns. **Not a disabled flag: an absence.** |
| Google Maps Static needs an affirmative act | **Double opt-in:** `LE_GOOGLE_MAPS_STATIC_KEY` **and** `LE_GOOGLE_TOS_ACKNOWLEDGED=true`. The key alone is insufficient. |
| Some providers forbid caching | `capabilities().allows_caching = False` makes `DiskTileCache`/`RedisTileCache` **refuse the write** and fall back to `LRUTileCache` (in-process, request-lifetime) with a `WARNING`. **A provider with restrictive terms cannot accidentally accumulate a permanent on-disk copy via a background job.** |
| Some providers forbid derivative export | `capabilities().allows_derivative_export = False` makes `ExportContext.chip = None`, so **`PdfReportWriter` omits the map figure** and records it in `ExportBundle.warnings`. |
| Attribution is a licence condition | `SatelliteChip.attribution` **and `CandidateWindow.attribution` and `match_results.attribution`** are all **required fields** — pixels cannot travel without their credit, **including across the ai_engine seam**, where v1.0 dropped it. Surfaced in the map UI, in `X-Imagery-Attribution` on endpoint 36, in the CSV, and in every PDF — **all served from the `match_results` row**, never by re-resolving the provider (which may have been reconfigured since the pixels were fetched). **`LE_EXPORT_INCLUDE_ATTRIBUTION` should not be turned off.** |
| Tiles reach the browser through us | `LE_IMAGERY_DIRECT_TILE_URLS=false` **by default** ⇒ every provider's `tile_url_template` is the proxy path, so the ToS chokepoint, the shared quota bucket and the `User-Agent` policy apply to browser traffic too (§7.2). |
| The operator's allow-list | `LE_ALLOWED_PROVIDERS` — a hard list; anything outside → `ProviderDisabledError` → `403 PROVIDER_TOS_FORBIDDEN`. |
| The `always_xy` pitfall | CI greps for `from_crs` outside `gis/crs.py` — **the mistake is made unreachable rather than documented.** |
| Provider registration | **Explicit in `gis/imagery/providers/__init__.py`. No entry-point autodiscovery.** For a product whose central legal constraint is *which imagery sources are permitted*, a plugin mechanism that lets an unreviewed provider appear by being pip-installed is a liability. The set of providers is a reviewed, auditable list in version control. |

> **"Keyless Esri" is a BOOTSTRAPPING decision, not a licensing one.** Reachable ≠ licensed, and "derived survey deliverable" is the use most likely to exceed the terms. The default satisfies the zero-config mandate; **this contract refuses to let that read as a recommendation.** The caveat is repeated in the README, the first-run log line, the UI provider picker, and every PDF. `docs/legal/imagery-terms.md` is the record.

### 11.6 "No match" is not a failure

| Outcome | Job status | Response |
|---|---|---|
| Every window rejected by the confidence gate | **`succeeded`** | `result_count = 0`, `best_confidence = null`. `GET /images/{id}/match-results` returns an **empty page**, not a 404. |
| Every window rejected by a **hard degeneracy check** | **`succeeded`** | Same, plus the `DegeneracyReport` on each rejected candidate so a reviewer can see *why*. |
| Winner's margin over runner-up `< LE_AI_RANK_MARGIN` | **`succeeded`** | `AMBIGUOUS_MATCH` warning, **candidates returned and visible**. |
| The pipeline could not run (provider down, DB down, OOM) | **`failed`** | `error` populated. |

> **Modelling "no match" as `failed` would trigger pointless retries of a deterministic outcome** — burning 60 s of CPU to produce the identical answer — **and would tell the surveyor the system broke when in fact the answer is "not here".** `failed` is reserved for *the pipeline could not run*.
> **Ambiguity is shown, not resolved silently.** `AMBIGUOUS_MATCH` with the ranked candidates visible is far more useful to a surveyor who knows the site than a bare "no match" — they can often adjudicate instantly.

### 11.7 The gating ladder (L12)

Multiple independent gates, each of which can veto:

| Gate | Threshold | Failure |
|---|---|---|
| Match count | `LE_AI_MIN_MATCHES = 10` | candidate skipped |
| Inlier count | `LE_AI_MIN_INLIERS = 12` (H1) | **`gate = 0`, rejected** |
| Hard degeneracy H2–H10, H12, H13 | §4.9 *(H11 deleted — it was provably implied by H2+H4)* | **`gate = 0`, rejected** |
| Soft degeneracy S1, S3–S8 | §4.9 *(S2 deleted — it double-counted `U` with `S_g`)* | `gate *= factor` |
| Confidence | `LE_AI_MIN_CONFIDENCE = 40.0` | candidate dropped |
| Rank margin | `LE_AI_RANK_MARGIN = 10.0`, **taken on `raw`** (§4.12.4) | `status = "advisory"`, `ambiguity_clamp = 40` |
| Regime ceiling | nadir 100 / oblique_rectifiable 85 / oblique_raw 60 / ground_horizon 35 / unknown 50 | `confidence` clamped, `clamp_reason` set |

**Every surviving GCP carries `confidence` AND `accuracy.total_ce90_m`** — both now backed by real columns (§5.6). Exports include both. **A GCP without its uncertainty is a lie of omission.**

> **★ What this ladder does NOT do, stated plainly.** It has **no wrong-field defence.** H11 claimed to be one and was mathematically vacuous (§4.9); the ambiguity clamp is **relative** and cannot detect a globally-wrong-but-unique answer. The gates catch *degenerate* solves and *ambiguous* ones. A confident, non-degenerate, unique match against a visually identical field **passes every gate here**, and the honest mitigations are elsewhere and weaker: the landmark evidence terms, held-out `transfer_k` (§4.12.2), and — the real one — a surveyor who knows the site looking at the candidate. §12.5 records this as an open risk rather than a solved problem.

**The system returns "I could not find this" more often than a naive one would. That is the correct trade for a surveying instrument.**

### 11.8 Degradation is never silent — the four surfaces

| Surface | Audience | Content |
|---|---|---|
| `match_jobs.warnings` / `.degraded` / `.degradation_reason` | API/UI | Stable machine code + one human sentence. **Never a traceback.** |
| `JobRead.warnings` / `MatchResultRead.degraded` | SPA | Rendered as a chip or a warning per §8.8 |
| Structured log (`ComponentFallback` event, WARNING) | operator | `job_id`, `image_id`, `stage`, requested, candidate, reason, exc_type, **full traceback** |
| `model_fallbacks_total{requested,effective,reason}` | on-call | A fleet-wide spike means someone's weight volume did not mount |

> **`degraded: true` + `degradation_reason` on every job is the UX contract for L1.** The system does not silently pretend it ran SuperPoint. It succeeds, tells you what it actually used, and the UI renders it. **Silent degradation is how a surveyor ends up trusting a coordinate they should have questioned.**

---

## 12. The conflicts I resolved

Every disagreement found between the six docs, with the ruling and the reason. **The "Loser" column names a design that is now void — if you find it in a specialist doc, this table overrides it.**

### 12.1 Structural

| # | Conflict | Winner | Loser | Ruling and rationale |
|---|---|---|---|---|
| **C-01** | **Doc numbering.** `00-overview` §10 names downstream docs `01-ai-engine.md` / `02-gis-imagery.md` / `03-backend-api.md` / `04-data-model.md` / `05-frontend.md`. The docs that actually exist are `10/20/30/40/50`. | The files on disk | `00-overview` §10 | **`00/10/20/30/40/50` is the scheme.** The overview's ownership table is void; §0 of this contract replaces it. This was the flagged conflict; it is now closed. |
| **C-02** | **Package roots.** Overview: `ai_engine/src/ai_engine/`, `gis/src/gis/` at repo root. AI doc: `backend/ai_engine/`. Imagery doc: `backend/app/imagery/` (§1.1) **and** `backend/app/gis/` (§8, §9) — **self-contradictory within one document**. | **Repo root: `ai_engine/src/ai_engine/`, `gis/src/gis/`** | AI doc §1; imagery doc §1.1/§8/§9 | Three docs, three answers, one of them internally inconsistent. Decided on the **verified environment fact**: `fastapi` is not installed here. A package physically under `backend/` invites a `from app.core.config import Settings` that would be one careless import from making `cd ai_engine && pytest` fail at collection. **Root-level packages make the boundary a filesystem fact, not a discipline.** `import-linter`'s `root_packages = ai_engine, gis, app` is also cleanest this way. Internal module structure is taken from the AI doc (which is far more developed than the overview's). |
| **C-03** | **`photos`/`landmarks` vs `images`/`annotations`.** Overview §3 tree, §8.1 endpoints, §8.2 tables, and the whole sequence diagram use `photos` + `landmarks`. DB doc and API doc use `images` + `annotations`. | **`images` + `annotations`** | Overview | The DB doc is authoritative for tables, the API doc aligned to it deliberately, and the frontend followed. **An annotation is the general thing (a point, polyline, or polygon the surveyor drew); a landmark is the ROLE a point plays when it becomes a GCP candidate.** `gcps.landmark_id → annotations.id` is exactly that relationship. The word "landmark" survives **only** where it names the role: `POST /images/{id}/suggest-landmarks`, `gcps.landmark_id`, `LandmarkSet`. One concept, one name, at each layer. Every `photos`/`landmarks` path in the overview is void. |
| **C-04** | **`gis` vs `imagery` dependency direction.** Overview: `gis.imagery` is a subpackage and `gis.tiles` may import `gis.imagery`. Imagery doc: `gis/` **never** imports `imagery/`; `imagery/providers/* → gis/tiles.py`. | **Imagery doc's direction**, with `gis.imagery` as a subpackage of `gis` | Overview §4 | The imagery doc is right on the substance: **tile math is the foundation and must have zero optional deps and zero I/O.** A tile-math bug fix must not require reasoning about Bing's ToS. So: `gis.tiles` is PURE (numpy + stdlib, no I/O, no pyproj); `gis.imagery` imports `gis.tiles`, never the reverse. The overview is right that they belong in one distribution. Both facts are honoured. Fetching/caching move **out** of `gis.tiles` (overview's `tiles/fetcher.py`, `tiles/cache.py`) and **into** `gis.imagery`. |
| **C-05** | **Env var prefix.** Overview: `LE_` on all 104 vars. API doc Appendix C: unprefixed (`MAX_UPLOAD_BYTES`, `AUTH_MODE`, `CORS_ORIGINS`, `DEBUG`). Imagery doc §10: its own scheme (`IMAGERY_PROVIDER`, `ORTHO_DIR`, `TILE_CACHE_TTL_S`, `GOOGLE_TOS_ACKNOWLEDGED`). | **`LE_` on everything the backend reads** | API doc, imagery doc | `core/config.py` declares `env_prefix="LE_"` **once**; without the prefix every field needs an explicit alias, which is the drift this decision exists to prevent. An unprefixed `AUTH_MODE` or `DEBUG` in a shared shell or a CI runner is a collision waiting to happen. `VITE_` for the frontend; unprefixed **only** for `POSTGRES_*`/`REDIS_PORT`, which upstream images own. §9 is the complete list. |
| **C-06** | **Max upload size.** Overview: `LE_UPLOAD_MAX_BYTES=52428800` (50 MB), `VITE_MAX_UPLOAD_MB=50`. API doc: `MAX_UPLOAD_BYTES=524288000` (500 MB) + `ASYNC_INGEST_THRESHOLD_BYTES=50MB`. | **500 MB**, async ingest above 50 MB | Overview | **`local_orthophoto` is the single highest-accuracy path in the product and orthophoto GeoTIFFs are routinely 100–400 MB.** A 50 MB cap would make the accuracy path un-uploadable. The API doc's two-tier design (500 MB cap, async ingest above 50 MB so a 400 MB ortho does not hold a worker thread for 20 s) is the right shape. `VITE_MAX_UPLOAD_MB=500`; nginx `client_max_body_size 500m`. |
| **C-07** | **SSE.** Overview: `GET /jobs/{id}/events` (SSE, `sse-starlette`), `LE_JOB_SSE_ENABLED`, `VITE_JOB_SSE_ENABLED`, nginx `proxy_buffering off`. API doc: "WebSockets/SSE are explicitly out of scope for v1" — polling + `?wait=` long-poll. Frontend: polling only. | **Polling + `?wait=` long-poll. No SSE.** | Overview | **Two of three docs already built the polling design, and the frontend's poller is fully specified with an exhaustive terminal check.** SSE adds an operational surface (buffering config, proxy compatibility, a second code path that "degrades to polling" — i.e. polling must exist anyway and be correct) for a single-user-per-job UI. Long-poll over Redis pubsub cuts poll traffic ~25× at a fraction of the cost. **Deleted:** `sse-starlette`, `LE_JOB_SSE_ENABLED`, `VITE_JOB_SSE_ENABLED`, the `/events` endpoint, and the `proxy_buffering off` requirement. **Added:** nginx `proxy_read_timeout 60s` (long-poll needs > 30 s). |
| **C-08** | **Wire casing.** API doc: snake_case end to end, no alias generator, explicitly reasoned. Frontend doc: every TS interface in camelCase (`errorRadiusM`, `matchResultId`, `createdAt`, `fellBackToClassical`) — **and never mentions the mapping**. | **snake_case everywhere, including TS** | Frontend doc | The frontend doc's camelCase requires a mapping layer it never specifies — a silent second source of truth sitting exactly where `openapi-typescript` + the CI drift gate were supposed to make drift impossible. **The generator's guarantee would stop at the transport boundary and the domain layer would drift invisibly.** §8.1 is the law. ESLint's `camelcase` rule is disabled for `src/types/**` and `src/api/**`. |

### 12.2 The AI/GIS boundary — the most consequential group

| # | Conflict | Winner | Loser | Ruling and rationale |
|---|---|---|---|---|
| **C-09** | **`ai_engine` owns CRS math.** AI doc ships `ai_engine/transform/{slippy.py, mercator.py, pixel_to_geo.py}` — "image px → lat/lon w/ covariance", EPSG:3857, `R=6378137.0`, `φ_max=85.0511287798066`. This **directly violates ADR-004 and the overview's CI gate** (`grep -ri "epsg\|pyproj\|latitude" ai_engine/src` → empty). The imagery doc independently designed the same math in `gis/tiles.py`. | **`gis` owns ALL tile math and CRS.** `ai_engine/transform/` is **deleted**. | AI doc §1, §7 | Two docs put slippy math in `gis`; one put it in `ai_engine`. **The layering rule and the majority agree.** More importantly, ADR-004 is not stylistic: it is why `ai_engine` needs no pyproj and no PROJ database, which is why it installs from numpy+opencv+scipy alone, **which is why it runs on this machine today**. The AI doc's §7 math is excellent and is **preserved verbatim in `gis/tiles.py`** (§4.18) — the constants, the `res(z,φ)` table, and the round-trip tests all move. `ai_engine/geometry/uncertainty.py` keeps covariance propagation **in pixels**; `gis/accuracy.py` (§4.20) is where a pixel covariance becomes a metre. |
| **C-10** | **Who fetches tiles.** AI doc: `ai_engine/tiles/{protocol,windows,candidates}.py` with a `TileProvider` Protocol carrying `TileRef(z,x,y)` and `Tile.bounds_3857`. Overview: `gis.candidates.TileCandidateSource` satisfying `ai_engine.types.CandidateSource`. Imagery doc: `gis/search_grid.py`. | **`ai_engine.types.WindowSource`** (§4.10); `gis.candidates.TileWindowSource` implements it | AI doc's `TileProvider` | The AI doc's `TileProvider` puts `z/x/y` and `EPSG:3857` **inside `ai_engine`** — the same C-09 violation wearing a Protocol. The overview's `CandidateSource` is the right shape but underspecified. **Ruling:** `ai_engine` declares `WindowSource` — an iterable of `CandidateWindow`, which carries pixels plus an **opaque** `geotransform` + `crs` + `gsd_m` + `georef_ce90_m` that `ai_engine` **carries through and never interprets**. `gis` owns tile addressing, fetching, stitching, and geotransform construction. This preserves L3 mechanically while keeping the AI doc's genuinely valuable fields (`georef_ce90_m`, `is_placeholder` → `placeholder_fraction`, `supports_multispectral`) — they now live on `CandidateWindow`. **This is what makes swapping Esri→Mapbox unable to change the matching algorithm: the provider changes pixels and six floats, and `ai_engine` cannot tell the difference.** |
| **C-11** | **Adaptive candidate search.** AI doc: `QuadtreeBeamSearch` in `ai_engine/tiles/candidates.py` — coarse-to-fine, descend where scores are promising. Imagery doc §5.2: coarse-to-fine staging in `gis/search_grid.py`. Overview: "prior-centred spiral · bbox raster · multi-zoom pyramid" in `gis/candidates/strategy.py`. | **Flat enumeration in `gis.candidates.strategy.plan_search()` for v1. Beam search DEFERRED.** | AI doc's `QuadtreeBeamSearch` | Both beam-search designs need `ai_engine` to **score** a window before `gis` decides where to descend — **which inverts the layer dependency** and is why the two docs each put it on their own side. Neither noticed. Flat enumeration over `aoi × zoom_levels` bounded by `max_candidates` is **deterministic, fully known before any I/O** (which is what makes `len(WindowSource)` honest, progress reporting truthful, and the tile budget enforceable *before* a job is accepted), and adequate at the v1 budget of 25 windows. **`WindowSource` is precisely the seam where beam search slots in later** — as a source that consumes a scoring callback — without touching a single `ai_engine` interface. Recorded as deferred-not-rejected. |
| **C-12** | **`ai_engine` entry point.** Overview: `GcpPipeline.run(photo, landmarks, CandidateSource, cb) → PipelineResult`, config class `PipelineConfig`. AI doc: `run_match_job(ctx) → MatchJobResult`, config class `AiEngineConfig`, `MatchContext` bundle. | **`run_match_job(ctx: MatchContext) -> MatchJobResult`, `AiEngineConfig`** | Overview | The AI doc's design is strictly more developed and the `MatchContext` injection bundle is what makes the engine testable with nothing installed. A class with one method is a function. |
| **C-13** | **Score weights.** DB doc server_default + API doc default: `{feature:0.4, geometric:0.3, landmark:0.2, semantic:0.1}`. AI doc §10.1: `{feature:0.25, geometric:0.35, landmark:0.30, semantic:0.10}`. | **AI doc's `0.25/0.35/0.30/0.10`** | DB + API doc | Two docs agree on `0.4/0.3/0.2/0.1` — but **neither gives a reason for it**, while the AI doc derives its weights from the scoring design: **`S_g` (geometric) is the most trustworthy signal and gets the largest weight; `S_l` (landmark) carries the human's domain knowledge, which is the product's whole differentiator, and 0.2 undersells it.** Agreement without argument loses to argument. The DB `server_default` and the `ScoreWeights` defaults both change to `0.25/0.35/0.30/0.10`. |
| **C-14** | **`min_confidence`.** Overview: `0.35` (0–1 scale). API doc: `40.0` (0–100). AI doc: `25.0` (0–100). | **`40.0` on the 0–100 scale** | Overview, AI doc | First, the **scale**: 0–100, because that is the scale `gcps.confidence` and `overall_confidence` use everywhere else, and a threshold on a different scale from the value it gates is a bug generator. Second, the **value**: the API doc's 40.0 is the one exposed to clients as `MatchOptions.min_confidence`, and **L12 says refusing beats answering wrongly** — so when three docs disagree, take the most conservative that anyone actually argued for. The overview's `0.35` and the AI doc's `25.0` are void. |
| **C-15** | **RANSAC threshold.** Overview + API doc: `3.0 px`. AI doc `RansacConfig`: `5.0 px`, argued as "MAGSAC: an UPPER BOUND on noise, not a tuned inlier gate". | **`3.0 px`** | AI doc | The AI doc's technical point is correct for MAGSAC++ — the threshold *is* a noise upper bound there. But two docs say 3.0, the API **exposes `ransac_threshold_px: float = 3.0` to clients**, and a default the client sees must match the default the engine uses. 3.0 is a defensible upper bound on noise for 0.3–1 m imagery. **Noted for the implementer:** a MAGSAC-specific tuning pass may justify raising this; it is a config change, and `RansacConfig.threshold_px` is where it lives. |
| **C-16** | **`min_inliers`.** Overview: `15`. API doc + AI doc: `12`. AI doc degeneracy check H1: `n_in < 12` → hard reject. | **`12`** | Overview | Two docs agree, **and the number is load-bearing in H1**, which is normative. A `min_inliers` of 15 with an H1 of 12 means the two gates disagree about what "enough" means. |
| **C-17** | **Estimator naming.** DB enum: `usac_magsac`. AI doc `HomographyMethod`: `MAGSAC = "magsac"`. | **`usac_magsac` everywhere** | AI doc | The DB enum is persisted and the API exposes it; the internal enum must not have a private spelling. `HomographyMethod.USAC_MAGSAC = "usac_magsac"`. One string, one meaning, no translation table. |
| **C-18** | **Extractor/matcher enum members.** DB: extractor `sift\|orb\|akaze\|superpoint\|disk\|loftr_dense`, matcher `bf\|flann\|superglue\|lightglue\|loftr`. AI doc registers `sift\|orb\|akaze\|asift\|superpoint\|dinov2` and `bruteforce\|flann\|superglue\|lightglue\|loftr`. | **extractor `sift\|orb\|akaze\|brisk\|asift\|superpoint\|dinov2`; matcher `bf\|flann\|superglue\|lightglue\|loftr`** | both, partially | **`disk` and `loftr_dense` are DELETED from the extractor enum** — nobody designed a DISK extractor, and LoFTR is a *detector-free matcher*, not an extractor; `loftr_dense` as an extractor label is a category error that would have shipped. **`asift` and `dinov2` are ADDED** — the AI doc designed both. **`brisk` is ADDED** — the overview lists it and it is free (main-module OpenCV). The registry key is **`bf`** (DB's), class name `BruteForceMatcher`. |

### 12.3 Schema gaps — things the API promised that the DB could not store

| # | Conflict | Ruling |
|---|---|---|
| **C-19** | **`aux_jobs` did not exist.** The API's `JobRead` unions job types `match\|export\|batch\|segment\|suggest_landmarks\|gcp_recompute\|thumbnail` and promises `202 → GET /jobs/{id}` for all of them. **The DB has tables for only three.** `segment`, `suggest_landmarks`, `gcp_recompute` and ingest jobs had **nowhere to live** — four endpoints returning a job handle to a row that cannot exist. | **ADD the `aux_jobs` table** (§5.6) covering `segment\|suggest_landmarks\|gcp_recompute\|ingest`, plus the `job_type` enum, plus the `v_jobs` view unioning `match_jobs` + `aux_jobs` + `batch_jobs` + `exports`. Renamed `thumbnail` → `ingest` (it also builds overviews and parses EXIF; "thumbnail" undersells it). Minimal and honest: four job types genuinely share one shape, and `match_jobs`' 40 columns of matching-specific reproducibility record do not belong on a segmentation job. |
| **C-20** | **`landmark_suggestions` did not exist.** API §14 references "a `landmark_suggestions` materialization (see `10-database.md`)". **It is not there.** | **ADD the `landmark_suggestions` table** (§5.6) + the `suggestion_status` enum. Suggestions must not be `annotations` (ADR-014: a suggestion is a proposal, an annotation is a human assertion) and must not be `semantic_features` (they have a review lifecycle and an accept target). |
| **C-21** | **`images.status` did not exist.** API's `ImageRead.status ∈ uploaded\|processing\|ready\|failed` gates `409 IMAGE_STILL_PROCESSING` and the `POST /match` pre-flight. **No such column.** | **ADD `images.status image_status NOT NULL DEFAULT 'uploaded'`** + the `image_status` enum + `ix_images_status ... WHERE status <> 'ready'`. |
| **C-22** | **`images.notes`, `images.metadata`** are in `ImageUploadForm` and `ImageRead`; not in the DDL. | **ADD both.** `metadata` maps to attr `meta` (the name is reserved on `DeclarativeBase`). |
| **C-23** | **`projects` flat defaults vs `settings` JSONB.** API exposes `default_extractor`, `default_matcher`, `default_estimator`, `default_search_radius_m`, `default_search_zoom`, `tags`, `metadata` as typed, validated, defaulted fields. DB has a single opaque `settings JSONB`. | **Promote them to real columns** (§5.6). They are validated, defaulted, enum-constrained and read on every `POST /match` — that is a column, not a JSON bag. `settings` is **replaced** by `metadata` JSONB for genuinely free-form data. `tags` becomes `TEXT[]` + a GIN index (the API filters on it). |
| **C-24** | **`match_jobs.cancel_requested`** is the entire mechanism of API §5.6's cooperative cancellation. Not in the DDL. | **ADD** to `match_jobs`, `aux_jobs`, `batch_jobs`, `exports`. |
| **C-25** | **`match_results.parent_match_result_id`** is required by API §13.6 (recompute writes a new row rather than mutating). Not in the DDL. | **ADD**, `ON DELETE SET NULL`, + partial index. |
| **C-26** | **`gcps.is_stale` / `stale_reason`.** API §13.1: "Computed on read by comparing `gcps.updated_at`/`pixel_x`/`pixel_y` against the source annotation's current state." | **STORE them.** Overruled. Computing on read means a correlated subquery against `annotations` for **every row of every GCP list response** — the product's hottest read — and it makes `?is_stale=true` unindexable. More decisively: **staleness is caused by exactly three write paths** (annotation PATCH/bulk-upsert, revision restore, match-result select). A writer that knows it invalidated a GCP should say so once, not force every reader to re-derive it. `ck_gcps_stale_reason` binds the pair; `ix_gcps_stale` makes the filter free. |
| **C-27** | **Idempotency: two mechanisms.** Overview §6.4: a content-derived `match_jobs.idempotency_key` = `sha256(photo ‖ landmarks ‖ params ‖ provider)` with a partial unique index on non-terminal states. API §5.2: an `Idempotency-Key` header in Redis, plus `409 MATCH_JOB_ALREADY_RUNNING` + `?force=true`. | **Redis header + the active-job conflict check. The `idempotency_key` column is DELETED.** The API's two mechanisms already cover both failures the overview's column defends: a double-click (the header) and a redundant in-flight match (`MATCH_JOB_ALREADY_RUNNING`, which is *more* informative because it returns the job id and offers `force`). A third mechanism is a third thing to get wrong. The **task-level guard survives** and is not optional: `match_image_task` re-reads its row on entry and returns immediately if the status is terminal — that is what makes `acks_late` redelivery safe. |
| **C-28** | **`satellite_tiles` table** (overview §8.2). | **VOID.** The tile cache is disk/Redis, content-addressed, with a `variant` in the key. A DB table for it would be a slower cache with a connection pool in front of it. |
| **C-29** | **`users` table** (overview §3, "present but inert"). | **VOID for v1.** `owner_id`/`actor_id`/`adjusted_by`/`requested_by` are nullable `TEXT`. An inert table is a schema liability with no reader. Identity is a later ADR; when it lands it **adds an FK, not a restructure.** |
| **C-30** | **`pgcrypto`.** Overview migration `0001` creates it. DB doc: "not needed — `gen_random_uuid()` is core in PG 13+". | **No `pgcrypto`.** The DB doc is factually right. Extensions: `postgis`, `btree_gist`, `pg_trgm`. |
| **C-31** | **Migration layout.** Overview: `backend/alembic/versions/`, revisions `0001`–`0005`. DB doc: `backend/migrations/`, revisions `0001`–`0009`. | **`backend/alembic/versions/` (overview's path) with the DB doc's nine revisions.** `alembic.ini` conventionally points at `alembic/`, and the DB doc's nine-step ordering is the one that actually handles the enum-creation ordering and the `match_jobs`↔`batch_job_items` FK cycle. |

### 12.4 Naming and defaults

| # | Conflict | Ruling |
|---|---|---|
| **C-32** | **Provider registry keys — THREE schemes.** DB enum: `esri_world_imagery`, `mapbox_satellite`, `bing_aerial`, `sentinel_copernicus`, `google_maps_static`, `local_orthophoto`. Overview: `esri_world_imagery`, `local_geotiff`, `fixture`, `mapbox`, `bing`, `sentinel`, `google_static`. Imagery doc: `esri`, `local_ortho`, `mapbox`, `bing`, `sentinel`, `google_static`. | **The DB enum wins** — it is persisted, it is on the wire, and `ImageryProvider.name` **must** be a member of it. Concretely: `esri_world_imagery` · `local_orthophoto` · `mapbox_satellite` · `bing_aerial` · `sentinel_copernicus` · `google_maps_static`. **`fixture` is ADDED to the enum** — the overview and the API doc both require a deterministic no-network provider for tests, and the DB doc simply forgot it; a test provider whose name cannot be persisted cannot be used in an integration test. Python **class** names keep the imagery doc's readable form (`EsriWorldImageryProvider`, `LocalOrthophotoProvider`) — the class name is not the registry key. |
| **C-33** | **Tile cache location.** Overview: `gis/tiles/cache.py`. Imagery doc: `imagery/cache/{base,memory,disk,redis}.py`. | **`gis/imagery/cache/`** — per C-04, `gis.tiles` is pure math with no I/O. The imagery doc's three-backend design + the licence gate (`allows_caching`) + the `variant` cache-key field are all adopted. `redis.py` → **`redis_cache.py`** (a module named `redis.py` inside a package that imports `redis` is a shadowing bug waiting for its first `import redis`). |
| **C-34** | **Export DTO.** Overview: `gis/exports/models.py::GcpRecord`. Imagery doc: `ExportContext` in `base.py`, referencing an undefined `GcpRecord`. | **Both.** `gis/exports/models.py::GcpRecord` (the row) + `gis/exports/base.py::{ExportContext, ExportBundle, ExportWriter}` (the bundle). The imagery doc's `ExportContext` is the right shape and its `warnings` list is not decoration. |
| **C-35** | **Strictness flags.** `LE_AI_STRICT_BACKEND` (overview) vs `strict_models` (AI config) vs `IMAGERY_STRICT` (imagery doc). | **Two flags, both `LE_`-prefixed:** `LE_AI_STRICT_BACKEND` → `AiEngineConfig.strict_models`; `LE_IMAGERY_STRICT` → the provider registry. They gate different subsystems and must be independently settable (CI wants AI-strict but imagery-lenient). |
| **C-36** | **`ImageDisplayVariant.originalWidth/Height`** — the frontend's flagged load-bearing open question. No other doc provides it. | **RESOLVED: `ImageVariant` is a required field of `ImageRead`**, with `original_width`, `original_height` and a **server-computed `display_scale`** on **every** variant, non-null, always (§6.2, §8.2). Without it the client cannot compute `D` and the entire coordinate model of §8.6 collapses. The server computes `display_scale` rather than making the client divide — one fewer place to get it wrong, and it makes the invariant `display_scale == width / original_width` server-testable. |
| **C-37** | **`LE_SEARCH_REQUIRE_PRIOR=true`** (overview) vs the imagery doc's "a hint is a **hard input requirement**". | **DELETE the var.** The requirement is unconditional. A config flag implying global search is available at `false` is a lie — hintless search is *arithmetically impossible* (~10¹¹ tiles, ~1 PB per photo), not merely disabled. `422 SEARCH_HINT_REQUIRED`, always, designed into the UX as a blocking step. |
| **C-38** | **`max_candidates`.** Overview: `LE_SEARCH_MAX_CANDIDATES=64`. API: `options.max_candidates = 25`. | **`25`** — the API's, because it is the number clients see. 64 windows × ~3 s each on CPU is a 3-minute job on the verified hardware. |
| **C-39** | **Tile budget.** Overview: none. API: `MAX_TILES_PER_JOB=256`, `max_tiles=256`. Imagery doc: `MAX_TILES_PER_REQUEST=400`, `MAX_TILES_PER_JOB=2000`. | **`LE_MAX_TILES_PER_JOB=256`**, matching `match_jobs.max_tiles`' default and the API's validated ceiling. 2000 tiles is ~4 minutes of fetching before any CV runs. |
| **C-40** | **Job progress stages.** Overview §6.2: one 12-stage list with fixed percentages. API §5.5: per-type stage lists + weighted `STAGE_WEIGHTS`. | **API's per-type lists + `STAGE_WEIGHTS`** (§6.2 `JobStage` table). Percent must track **wall-clock**, not stage count, and an export job does not have a `photo_features` stage. |
| **C-41** | **Health endpoints.** Overview: `/healthz`, `/readyz`, `/version` (unprefixed). API: `/api/v1/health`, `/api/v1/health/ready`. | **API's.** One scheme. `/version` is folded into `HealthResponse.version` + `git_sha`. |
| **C-42** | **`/metrics` port.** Overview: `LE_METRICS_PATH=/metrics` on the app port. API §23.6: "separate port `9090`". | **Same port, path `/metrics`, excluded from OpenAPI.** A second uvicorn listener means a second port mapping in four compose files, a second nginx block, and a second thing to forget. Not under `/api/v1` — it is not part of the public contract. Operators who need isolation put it behind the proxy. |
| **C-43** | **`ProviderInfo` shape.** Overview `schemas/imagery.py::ProviderInfoRead` with `tile_url_template`. API `schemas/imagery.py::ProviderInfo`. Imagery doc `ProviderCapabilities`. | **`ProviderInfo`** (API's name) carries `name`, `configured`, `allowed`, `min_zoom`, `max_zoom`, `attribution`, `terms_url`, `tile_url_template` (**upstream URL for keyless, the proxy path for keyed** — ADR-010), `capabilities: ProviderCapabilities` (the imagery doc's field set, plus `georef_ce90_m`), `health: ProviderHealth`. |
| **C-44** | **`gis.exports` file names.** Overview: `csv.py`, `geojson.py`, `kml.py`, `pdf.py`, `shapefile.py`. Imagery doc: `csv_writer.py`, `geojson_writer.py`, … | **The imagery doc's `*_writer.py`.** `gis/exports/csv.py` shadows the **stdlib `csv` module** on any `import csv` inside the package. That is a real bug, not a style preference. |
| **C-45** | **`Tile.is_placeholder`** (AI doc) vs nothing elsewhere; degeneracy check H13 needs `> 20%` blank tiles. | **`CandidateWindow.placeholder_fraction: float`** (§4.10). `gis` computes it while stitching (it knows which tiles 404'd); `ai_engine`'s H13 reads it. The AI doc's per-tile boolean cannot survive stitching — a fraction can. |
| **C-46** | **`ai_engine` `errors.NoViableCandidate` is raised** (AI doc §1.1) vs the API's "no match found is `succeeded`". | **`run_match_job` RETURNS `MatchJobResult(status="no_viable_candidate")`. It does not raise** (§4.13). The exception class survives for internal use inside `step9_finalize`, but it must not cross the package boundary — a caller wrapping `run_match_job` in `try/except` to turn a business outcome back into a success is exactly the coupling this avoids. |
| **C-47** | **`ExportContext.crs` vs `exports.target_srid`.** Imagery doc: `ExportContext.crs: str = "EPSG:4326"`. DB: `exports.target_srid INTEGER DEFAULT 4326`. | **`ExportContext.target_srid: int`.** One representation. The DB stores an int; pyproj takes an int; a string `"EPSG:4326"` is a parse away from an int and a typo away from a crash. `GcpRead.crs` stays the literal string `"EPSG:4326"` because it is a wire-level assertion for humans, not a parameter. |
| **C-48** | **`ImageryProvider` method names.** Overview: `fetch_tile` / `fetch_bbox` / `info` / `is_available`. Imagery doc: `get_tile` / `get_static_bbox` / `capabilities` / `is_configured`. | **The imagery doc's**, verbatim (§4.16). It is the only version with argued signatures (the `bytes | np.ndarray` union rejection, the `SatelliteChip`-over-tuple rejection), and `is_configured` says something `is_available` does not: *this is a pure local check that never touches the network.* |
| **C-49** | **Provider discovery.** Overview implies a registry keyed by name. Imagery doc: "explicit registration, **not** entry-point autodiscovery". | **Explicit.** The imagery doc's reason is decisive: for a product whose central legal constraint is *which imagery sources are permitted*, a plugin mechanism that lets an unreviewed provider appear by being pip-installed is a liability. |

### 12.6 Conflicts found by the v2.0 audits — the math and scale rulings

**These were not visible to the six specialists because each is a disagreement BETWEEN documents, or between a document and its own worked example.** Full disposition in §14; the rulings are law.

| # | Conflict | Ruling |
|---|---|---|
| **C-50** | **`vec(H)` ordering.** 30-ai §6.4 derives Σ_H with `(T_aᵀ ⊗ T_b⁻¹)` — the **column-major** identity. §7.5's `A_h`, `match_results.homography` and §6.1 are all **row-major**. | **ROW-MAJOR everywhere.** §6.4's factor is `(T_b⁻¹ ⊗ T_aᵀ)`. §4.24(1). Composing the two silently **permutes** the 9×9 covariance — and §6.4 warns against exactly this defect one line before committing it. |
| **C-51** | **The homography gauge.** §3.5 returns `H` at `h₃₃=1`; §6.4 estimates and reports Σ_H on the **unit sphere**. | **`h₃₃=1` is the reporting gauge**, with the `J_g` conversion applied before returning and `cov_gauge` recording the exception branch. §4.24(2). Mixing them made **every error bar collapse to the click term** — most optimistic exactly when the fit is worst. |
| **C-52** | **Pixel centre vs corner.** 40-imagery §4.6 uses `+0.5` and argues for it; CONTRACT §5.8's canonical chain **omits it**; 40-imagery §4.7's test invariant **contradicts** §4.6. | **Pixel CENTRE**, stated once in §6.1's table. §5.8 gains the `+0.5`; §4.7's NW-corner invariant is **VOID**. A half-pixel round-trip error **spuriously 422s a correct GCP edit** at z17. |
| **C-53** | **`relative_m`: 1σ or 2σ?** CONTRACT §4.20 says 1-sigma; 30-ai §7.6 says `2·res·√λ_max` labelled "~95%". | **CE90 throughout** (`2.146σ`), the ellipse restored, `confidence_level` on the wire. §4.20. The two docs defined the **headline accuracy number** with a factor-of-2 difference; the "~95%" label was itself wrong (2σ on a 2-D semi-major is ~86.5%); and the quadrature mixed confidence levels. 30-ai's competing `AccuracyEstimate` is **VOID** under the C-09 precedent. |
| **C-54** | **Window overlap.** 30-ai §12.1/§5-step-11: `0.5`, reasoning from a **512 px** footprint guarantee. CONTRACT §4.19 and 40-imagery §5.2: `0.25` (a **256 px** guarantee). | **`0.5`**, and `GUARANTEED_FOOTPRINT_PX = 512` asserted at import (§4.19). The design reasons from 512; shipping 0.25 meant footprints in (256, 512] px could straddle every boundary and match nothing — **silently and location-dependently**. Tile budget re-costed: `LE_MAX_TILES_PER_JOB` 256 → 512. |
| **C-55** | **`zoom_for_resolution`.** 40-imagery §4.4 hardcodes the S=256 constant while **taking `tile_size` as an unused parameter**; `resolution_at` next to it is correct. | **Read `tile_size`.** §4.18. Off by one zoom for **every 512 px provider** — including Mapbox's **documented `use_2x=True` default** — causing 4× the tiles, spurious `AreaTooLargeError`, and a false `ZoomDecision.clamped`. 40-imagery's `choose_zoom(provider, …)` signature is **VOID** in favour of CONTRACT's, which carries `tile_size`. |
| **C-56** | **`utm_epsg_for` at the antimeridian.** 40-imagery §6.4's `zone = floor((lon+180)/6)+1` returns **61** at `lon = 180.0` → **EPSG:32661 = UPS North**, a polar stereographic CRS, not a UTM zone. | **Wrap and clamp:** `zone = min(int(floor(((lon + 180) % 360) / 6)) + 1, 60)`, matching §4.2's stated `[-180, 180)` convention. §6.1 routes **every metric computation** through this function, so the failure is not an exception — it is **plausible distances in the wrong system**. Goldens: `utm_epsg_for(180.0, 45.0) == "EPSG:32660"`, `utm_epsg_for(-180.0, 45.0) == "EPSG:32601"`. |
| **C-57** | **The §12.1 cheap screen compares oblique image-space crop-row orientation against nadir ground-space orientation.** | **Gate the orientation term on comparability.** Drop θ and spacing from the 64-D screen vector unless `regime == NADIR` or the query has been rectified; for `OBLIQUE_RAW`/`GROUND_HORIZON` screen on rotation-invariant quantities only (ExG + semantic histograms), or push θ through the recovered VP first. Record `screen_regime_degraded` and **widen the beam** when set — a weak screen must cost tiles, not correctness. This is a **hard prune before any H exists**: eliminating the true location there has **no recovery path**, and it presents as `NoViableCandidate` or as confident selection of the best surviving wrong window. |
| **C-58** | **The §5.3 tile-budget table omits the overlap factor from its own stated formula** (and the bbox-over-disc factor its caption calls "slightly"). | **Recompute with both**, and split the table into "tiles (disc, no overlap)" and "tiles (as fetched)". The real factor is ~2.26×, not "slightly": the 1 km/z18 row annotated *"at budget"* at ~342 is really ~775 against `MAX_TILES_PER_REQUEST=400` — i.e. **the documented fine case raises `AreaTooLargeError`**. The budget constants were sized against the wrong table. Made executable: a unit test asserts `tile_range_count(...)` at φ=45 matches the published figure. |

### 12.5 Conflicts I deliberately did NOT resolve

Three disagreements are **real open questions, not design defects.** Recording them honestly is the resolution.

| Question | Status |
|---|---|
| **Esri's terms for commercial survey deliverables.** The zero-config keyless default is the right *engineering* call under the brief's explicit constraint. Whether it is a defensible *product* default for paid deliverables is a question for the client and their counsel. If the answer is no, the honest move is a first-run interstitial forcing an explicit provider choice — **which trades away the zero-config promise.** | **Escalate to the client.** The default stands; §11.5's caveat propagation (README, first-run log, UI picker, every PDF) is the mitigation. Not a decision an architect gets to make alone. |
| **Reported accuracy excludes provider georegistration error.** We report our fit to *the provider's pixels*. Esri/Mapbox/Bing do not publish their own georegistration error; Sentinel-2 L1C is ~8–12 m CE95. **Reported accuracy is therefore optimistic for every web provider.** | **Structurally acknowledged, not resolved.** `georef_ce90_m` is **mandatory** on `ProviderCapabilities` and flows into `CandidateWindow` → `PixelAccuracy` → `GcpAccuracy.total_ce90_m`, and `dominant_term` lets the UI say the useful thing: *"your accuracy is limited by the basemap, not the match."* The **numbers** for keyed providers are estimates until the client tells us their tolerance. `local_orthophoto` is the only path where total error is knowable — **which is why it heads the default fallback chain.** |
| **Ground-photo ↔ satellite matching is a genuine research risk.** A ~90° viewpoint change means a fence from the side and from above share almost no SIFT structure. **No architecture removes this.** | **Not resolvable by design and must not be presented as if it were.** The architecture's job is to (a) fail honestly via the §11.7 gating ladder, (b) keep backends swappable so LoFTR/SuperGlue can be evaluated the moment weights exist, (c) support `local_orthophoto` where the viewpoint gap is smaller. **The classical path proves the pipeline end to end; accuracy on real oblique photos is an open empirical question and must be framed that way to the client.** The product should be *sold* on the near-nadir drone case and *tolerate* the ground-oblique case. |
| **★ NEW — We have no defence against a visually identical WRONG field.** v1.0 claimed one: H11 (`landmark_topology`) was described as catching *"matched a different but visually identical field, which no reprojection threshold can catch because it fits beautifully"*, and §8.5 counted it among *"three independent layers, so no single bug can leak a confident wrong answer."* **The audit proved it vacuous** (§4.9): a projectivity preserves hull cyclic order for **any** H whose ROI avoids the vanishing line and has positive determinant — both already hard-checked by H4 and H2 — so H11 could only fire when another check had already fired, and was **provably incapable** of the one job it was given. | **Deleted, and the claim withdrawn rather than replaced with a weaker one.** §4.9, §8.5 and §11.7 now state plainly that the ambiguity clamp is **relative** and cannot detect a globally-wrong-but-unique answer. The honest partial mitigations — metric landmark-pair distance ratios, held-out `transfer_k` (§4.12.2), and the ranked candidates being **visible to a surveyor who knows the site** — are what we actually have. **A stated non-defence is worth more than a check that makes a reviewer feel defended.** Escalate to the client alongside the row above: both bear on the same question, which is what the product may be *sold* as doing. |

---

## 13. The test contract

**No test may require network, a GPU, model weights, Docker, or a database** — except the explicitly marked tiers below.

### 13.1 What each unit must prove

| Unit | Must prove |
|---|---|
| **IU-01 ai-types** | `FeatureSet.validate()` rejects: shape mismatch, non-finite kps, kps outside `image_size`, FLOAT rows not unit-norm (atol 1e-3), scores outside [0,1], dtype mismatch, **`descriptor_dim % 8 != 0` for BINARY**, and **duplicate `landmark_ids >= 0`**. `MatchSet.validate()` rejects out-of-range indices and duplicate pairs. `Correspondences.merge()` dedupes iff **both** endpoints are within `dedupe_px`, higher weight surviving. `sorted_by_weight()` returns a permutation that actually sorts. `FeatureSet.concat()` raises `IncompatibleDescriptors` on kind/dim/name mismatch. **`CandidateWindow` round-trips its opaque `geotransform` unchanged.** **★ `LandmarkWeightField`: with K=12 landmarks at `w_k=4` all inside `R_L`, `max(g) <= 1.0` and the priority ratio is bounded by 12 — pinning the bound the comment asserts.** **★ `test_types_import_cheap`: on a FRESH interpreter, `import ai_engine.types` leaves `cv2`, `torch` AND `ai_engine.models` absent from `sys.modules`** (the property §10.3 uses to justify the one cross-package import, and which v1.0 asserted nowhere). **★ Enum parity leg 3: `ai_engine.types.enums.SemanticClass` / `PoseMethod` / `HomographyMethod` values match `PARITY_MAP`.** |
| **IU-02 ai-registry** | **★ THE L1 REGRESSION TEST.** Point `weights_dir` at an empty dir → `resolve("superpoint", EXTRACTOR)` returns `Resolution(requested="superpoint", resolved="sift", chain=("superpoint","sift"), degraded=True)` **and a `ComponentFallback` event is emitted at WARNING**. A **truncated** weight file (right name, wrong sha256) resolves identically to a missing one. `find_spec` is used, **not `import`** (assert via a `sys.modules` probe that torch is not imported when the chain falls back before reaching it). Every terminal spec has no `requires_weights` and no `requires_packages` (assert at registration). Cycle detection terminates. `strict=True` raises `ComponentUnavailable` instead. **`Device.CUDA` requested + `cuda.is_available()` False routes through the SAME fallback branch as missing weights.** **★ `Registry.specs()` is NON-EMPTY after `_ensure_registered()` and empty-registry resolution never happens** (the 12-parallel-agent failure mode). **★ `test_zero_env_preflight`: build `AiEngineConfig` from `Settings()` with `env={}`, call `preflight()`, assert it returns a `PreflightReport` and raises NOTHING** — the `LE_AI_ESTIMATOR` boot crash, pinned. |
| **IU-03 ai-extract** | **Parametrised over EVERY registered extractor** (`sift`, `orb`, `akaze`, `brisk`, `asift`): `extract()` on the synthetic scene returns a `validate()`-clean `FeatureSet`; `extract()` on a blank image returns an **empty** FeatureSet and **does not raise**; `extract_at()` at K supplied points returns `landmark_ids` identifying exactly the survivors, and drops points inside the patch margin; FLOAT descriptors are unit-norm; BINARY descriptors are bit-packed to `D//8`. **★ `extract(img).descriptor_dim == cls.descriptor_dim` for EVERY registered extractor** — the assertion AKAZE's `D=486` could never have passed. **★ `descriptor_dim % 8 == 0` for every BINARY extractor, asserted AT REGISTRATION.** **★ `extract_at()` on a deliberately bi-modal-orientation patch returns `len(...) <= K` with NO duplicate `landmark_ids`** (the `cv2.SIFT.compute` multi-orientation trap). RootSIFT is applied. **Nothing imports `cv2.xfeatures2d`** — a runtime assertion, which is stronger than the grep and catches dynamic access. |
| **IU-04 ai-match** | **Parametrised over `bf` and `flann`:** `match()` on identical FeatureSets yields ~N mutual matches; on unrelated images yields few; scores are in [0,1] and higher-is-better. **`FlannMatcher` + an ORB (BINARY) FeatureSet raises `IncompatibleDescriptors`** — not garbage. `match_guided(prior_H=identity, radius_px=2)` rejects everything outside the radius. `DetectBasedSource(matcher=LoFTRAsMatcher(...))` **is rejected at construction**. `LoFTRAsMatcher.match()` with a dead `image_ref` raises `DetectorFreeRequiresImages`. |
| **IU-05 ai-geometry** | **★ Recovers a KNOWN `H` from a synthetic warp within `1e-3`** (Frobenius, after scale-fixing). `estimate_homography` with M<4 raises `InsufficientCorrespondences`; with M≥4 but few inliers **returns a result rather than raising** (estimation reports, policy judges). **Determinism: same `seed` twice → bit-identical `H`** (`UsacParams.randomGeneratorState` is verified settable). `condition_number` and `determinant` are computed on the **Hartley-normalised** `H̃` — assert they are invariant to an input rescale, which is the whole point. **Each of H1–H10, H12, H13 is tripped by a purpose-built input** (collinear inliers → H5; a tiny hull → H6; a horizon-crossing quad → H4(a); a mirrored H → H2; NaN in H → H12) **and `gate == 0` with exactly the expected `hard_failures`**. Soft checks multiply, never zero. **★ H4(b): an `H` with `h₃₃ ≈ 0` whose vanishing line GRAZES the ROI without crossing it MUST trip** — the tangency case v1.0's `1e-6·|h₃₃|` threshold could never catch. **★ H11 is dead: construct a valid `H` passing H2 and H4 and assert the hull-order condition never fires** — if this passes, H11 is provably redundant and the docs say so. **★ THE MATH TESTS (§4.24):** (1) **vec convention** — random `H̃, T_a, T_b`; `A_h @ Σ_H @ A_h.T` matches a Monte-Carlo covariance of the warped point (a Frobenius test on `H` alone **cannot see a permutation**); (2) **gauge** — `trace(A_h Σ_H A_hᵀ)` **grows as the inlier hull shrinks** (the property the gauge bug destroys); (3) **σ_r** — with known injected pixel noise σ, recovered `HomographyResult.sigma_r ≈ σ` (pins the 2× DOF factor); (4) **rectification** — `Σ_win` at `sigma_f_rel=0.25` is **strictly larger** than at `0.05`; (5) **pose** — recovered `camera_height_m` matches ground truth at `τ ∈ {0°, 45°, 80°}` **and at φ=55°** (a nadir-only or equatorial test sees neither the `t`-vs-`C` bug nor the 1/cos φ bug); (6) **mask alignment** — a deliberately unsorted weighted input to `step6_estimate_homography` returns `inlier_mask` aligned to the INPUT. |
| **IU-06 ai-semantics** | `ClassicalSemantics.segment()` on the synthetic farmland finds crop rows at the seeded orientation ±5° and spacing ±10%. Contour-ploughed / centre-pivot input **fails the row-curvature check and declines** rather than returning a fictional orientation. `exg`/`ndwi` bounds. `AgriVanishingPointCalibrator`: **when `f² ≤ 0` it DECLINES rather than clamping** — the assumed orthogonality was wrong and every downstream angle would inherit the fiction. `landmark_consistency` ∈ [0,1]; `hull_order_invariant` detects a permuted-landmark match (H11). |
| **IU-07 ai-scoring** | **Property-based (hypothesis):** all `S_• ∈ [0,1]`; `confidence ∈ [0,100]`; **`gate == 0 ⇒ confidence == 0 and status == "rejected"` — asserted WITH A NON-IDENTITY PLATT CURVE**, since the identity-only test cannot catch the calibrator-swallows-the-gate bug and `logit(0)` is `NaN`, not 0. A `None` term drops from **both** numerator and denominator (assert a semantic-less score equals the same evidence scored with `w_s = 0` renormalised — **not** the same evidence with `s_s = 0.5`). Regime ceilings clamp and set `clamp_reason`. **`calibrated == False` and `calibration_id == "identity"` out of the box.** `feature_names()` length == `feature_vector` length. **★ THE ANTI-DOUBLE-COUNT INVARIANT: every element of `feature_names()` appears in EXACTLY ONE of {S_f, S_g, S_l, S_s, gate}** — a structural test that catches the next double-count too. **★ Two windows both above the regime ceiling are NOT flagged advisory on ambiguity grounds alone** (the saturation bug). **★ A job in which every fix seeded `H_seed` produces `transfer_k = None` for every landmark** (the independence claim, made testable). **★ A landmark with `score_k = 0` in an otherwise-accepted job produces `conf_k` below `min_confidence`** (the floor bug). **★ Heatmap: for `c_max ∈ {22, 50, 90}`, rasterised mass outside all component 3σ ellipses ≈ `π_bg`.** |
| **IU-08 ai-pipeline** | **★ FULL END-TO-END on `SyntheticWindowSource` with no network, no weights, no GPU: pixel error < 2 px against the known ground-truth `H`.** `run_match_job` **returns** `status="no_viable_candidate"` (never raises) when every window is gated out. `MatchJobResult.provenance` records the actual resolved components. `on_progress` fires at every stage boundary, monotonically. Same `job_seed` twice → identical `MatchJobResult.best.homography`. |
| **IU-09 gis-math** | **★ Golden slippy values vs known OSM tile numbers** (§13.3). Round-trip `lonlat → tile → lonlat` at `z ∈ [0,22]`, `φ ∈ [-85, 85]` → `< 1e-9°`. `resolution_at(z, φ)` matches the published `res(z,φ)` table. Constants exact. **Quadkey goldens** both directions. **`crop_to_bbox` folds the offset into the origin** — **this is the test that catches the ~108 m error that crashes nothing.** Antimeridian: a bbox crossing ±180 is rejected, not silently wrapped. `gis/tiles.py` imports **nothing but numpy and stdlib** (assert via `find_spec` on a fresh interpreter). **★ `zoom_for_resolution` ↔ `resolution_at` round-trip for all `z, lat, S ∈ {256,512}`** — the property that makes the hardcoded-256 unreachable — plus goldens `zoom_for_resolution(0.5, 45.0, 512) == 17` vs `(0.5, 45.0, 256) == 18`. **★ `lonlat_to_pixel(pixel_to_lonlat(gt, crs, u, v)) == (u, v)` to 1e-9 px** — what makes the two GCP-adjust chains agree. **★ `utm_epsg_for(180.0, 45.0) == "EPSG:32660"` and `(-180.0, 45.0) == "EPSG:32601"`** — the UPS-North off-by-one. **★ ACCURACY DIRECTION GOLDEN: `cov_px = I₂` at z=18, φ=55 ⇒ `sqrt(λ_max(Σ_true)) == 0.34251936163340246`** — fails under EITHER wrong sign of the cos correction. **★ `plan_search(zoom_levels=(18,), max_zoom=15)` returns plans at z15 with `clamped=True`, NEVER an empty list.** **★ POSE: a north-up EPSG:3857 window yields grid convergence 0; a UTM ortho window does not.** |
| **IU-10 gis-raster** | `rasterio_shim` binds at **call** time, not import: with rasterio absent, `import gis.raster` **succeeds** and the GDAL path is used. With **both** absent, the call raises `RasterBackendUnavailable` — a typed error, not `ImportError`. `detect_georeferencing()` returns `False` for a plain TIFF carrying GDAL's identity transform **and `True` for the committed synthetic GeoTIFF** — the exact distinction that decides `images.is_geotiff`. Windowed reads honour nodata. |
| **IU-11 gis-imagery** | **★ PARAMETRISED OVER EVERY PROVIDER — the interchangeability proof.** For **UNCONFIGURED** providers the suite asserts `__init__`/`is_configured`/`capabilities`/`name` **only** — it does not fetch. For each: `__init__` **never** raises and **never** touches the network (assert with a socket-blocking fixture); `is_configured()` never raises; **`name` is a member of `gis.imagery.base.PROVIDER_NAMES`** (gis cannot see the PG enum — a **backend** test pins `PROVIDER_NAMES` to it); `capabilities()` is total. **★ `test_import_without_deps`: import the FULL provider + cache registry with `httpx` and `redis` BLOCKED in `sys.modules` and assert collection succeeds and every unconfigured component reports its reason.** **★ `LE_IMAGERY_PROVIDER=auto` with a POPULATED ortho dir and zero other env vars returns `local_orthophoto`; with an empty one, `esri_world_imagery`.** For **configured** providers (`fixture`, `local_ortho` with the committed GeoTIFF): `get_tile` returns `(S,S,3) uint8` **RGB** (not BGR, no alpha, C-contiguous); `get_static_bbox` returns a `SatelliteChip` whose **`attribution` is non-empty**; the chip's geotransform is exact for the returned pixels. Out-of-range z → `TileOutOfRangeError`. A provider with `allows_caching=False` **causes `DiskTileCache` to refuse the write** and fall back to LRU with a warning. `TileCacheKey.variant` distinguishes two seasons of the same `(z,x,y)`. |
| **IU-12 gis-candidates** | `TileWindowSource` **structurally satisfies `ai_engine.types.WindowSource`** (`isinstance(src, WindowSource)` via `runtime_checkable`, **and** a mypy assertion). `len()` is exact and known **before** any fetch. `resolve_hint` honours the 5-step precedence exactly; all five empty → `SearchHintRequired`. `plan_search` respects `max_windows` and `overlap_ratio` and is deterministic. Budget guard raises `AreaTooLargeError` before any I/O. **`gis.candidates` imports nothing from `ai_engine` except `ai_engine.types`** (AST assertion). |
| **IU-13 gis-exports** | **Parametrised over every writer:** `is_available()` **never raises** with the dependency absent. **CSV/GeoJSON/KML/KMZ are available with ONLY the stdlib** — assert by blocking `geopandas`, `fiona`, `reportlab`, `ezdxf` in `sys.modules` **and importing the full `EXPORT_WRITERS` registry**, which is the collection path that v1.0's module-scope imports broke. CSV column order matches §4.21 exactly; UTF-8 **BOM** present; **longitude before latitude**; 8 dp. GeoJSON is RFC 7946: `[lon, lat]`, **no `crs` member**. Shapefile field truncation lands in `ExportBundle.warnings`. **`ExportContext.chip = None` ⇒ the PDF omits the map figure and says so in `warnings`.** **★ `kml` and `kmz` resolve to DIFFERENT classes** with distinct `format_id`. **★ A GCP with `elevation_m = None` exports an EXPLICIT empty cell, never a silent blank.** Every writer's `ExportBundle.checksum_sha256` matches the file. **No writer imports the ORM or touches the DB** (AST assertion). |
| **IU-15/16 be-core/models** | **★ `test_settings_zero_env`: `Settings()` with `env={}` constructs and raises nothing.** No `os.getenv` outside `core/config.py` (grep). **★ `test_enum_parity`: for every row of `PARITY_MAP` (§5.3), the `models.enums` / `schemas.enums` / (where present) `ai_engine.types.enums` members agree VALUE-for-VALUE — 17 pairs, three of them triples — and the 13 wire-only enums are asserted to be OUT of scope, so a new schema enum must be deliberately bucketed.** **★ `set(PROVIDER_NAMES) == {e.value for e in models.enums.ImageryProvider}`** — the constraint gis cannot enforce on itself. **★ `set(STAGE_WEIGHTS[t]) == set(STAGES[t])` and `sum(STAGE_WEIGHTS[t].values()) == 1.0 ± 1e-9` for EVERY `JobType`.** **★ `set(MatchStage) ⊆ set(STAGES[JobType.MATCH])`.** **★ Tier-1 migration test (always runs, offline, NO DB):** `alembic upgrade head --sql` against an offline context renders the full DDL; assert it is non-empty, contains `CREATE EXTENSION postgis`, and contains a `CREATE TABLE` for **every** table in §5.5. **This catches import errors, a missing `import geoalchemy2`, broken revision chains, and multiple heads — the majority of real migration breakage — with zero infrastructure.** `alembic heads \| wc -l == 1`. `Base.metadata.tables` contains all 17 (proves `models/__init__.py` imports every module — the silent-empty-diff footgun). Every spatial column declares `spatial_index=False`. Every native enum passes `values_callable`. |
| **IU-17 be-schemas** | Every model sets `extra="forbid"` (introspection sweep) — **including `Page`**, which v1.0 defined on `BaseModel` and which therefore failed this very sweep. Every `*Read` sets `from_attributes=True`. `Page[T]` generates a distinct named component. Round-trip: a sample of each `*Read` from a hand-built ORM-shaped object. **★ `ProjectRead.model_validate(project_orm).metadata == project_orm.meta`** — the `AliasChoices('meta','metadata')` exemption, without which every project and image read returns SQLAlchemy's `MetaData` object. **`AnnotationCreate` REJECTS a `crs` member in `geometry`.** `ScoreWeights` rejects a set not summing to 1.0 ± 1e-6. `GcpUpdate` rejects `lat` without `lon`. **`MatchOptions.timeout_s > LE_CELERY_TASK_SOFT_TIME_LIMIT` → 422.** `UNSET` sentinel: `{}` and `{"aoi": null}` are **distinguishable** *(PATCH bodies only — §6.1)*. |
| **IU-18/19 be-repos/services** | Repos: **@pytest.mark.db.** Job transitions are compare-and-set (a concurrent double-transition leaves exactly one winner and the loser no-ops). Services (**no DB, mocked repos**): the `POST /match` pre-flight ladder returns the right error for each of the 10 conditions; `gcp_service` adjustment derives the *other* representation and **leaves `confidence` untouched**; **`original_geom` is written once and never rewritten on a second adjustment**; `reset` is idempotent; staleness is set by exactly the three writer paths. |
| **IU-21 be-api** | httpx ASGI transport, **no live server**. Every route returns `ErrorEnvelope` on 4xx/5xx (sweep over `app.routes`). **`operation_id` is unique across the app** (startup assertion). **No duplicate `(method, path)`** (startup assertion). `/health` touches no dependency (assert with everything mocked to raise). `/health/ready` **never 500s** — inject a check that throws, assert `200`/`503` with `status: "down"` for that component. `models: degraded` **never** affects the aggregate. |
| **IU-23..28 frontend** | **★ `transform.ts` round-trip property test (fast-check):** `stageToImage(imageToStage(p)) ≈ p` within 1e-6 over `s ∈ [0.01,40]`, `D ∈ (0,1]`, `tx/ty ∈ [-10⁵,10⁵]`. **`isTerminal` is exhaustive** — a compile-time test adds a fake `JobStatus` member and asserts a type error. **The poller stops on every terminal status** and does not stop on any non-terminal one (table-driven). `AnnotationLayer` positions in **display** space (assert a node's `x` equals `p.x * D`, **not** `p.x * D * s + tx`). Precision truncation: a GCP with `total_ce90_m = 50` renders `41.87`, **not** `41.8721943`. MSW mocks every endpoint — **no backend runs.** |
| **IU-31 x-tests** | `tests/contract/` — the ABC conformance suites, parametrised, importable by both packages. `tests/e2e/` — **upload → annotate → match → export using the `fixture` provider, with no network, no weights and no GPU.** `tests/integration/` — **@pytest.mark.db**, compose-backed. **Tier-2 migration test:** `upgrade head` against real PostGIS, `alembic check` reports no drift vs the models, then `downgrade base` + `upgrade head` proves reversibility. **Skipped automatically when `LE_DATABASE_URL` is unset, so `pytest` on the dev machine is green.** |

### 13.2 The fixtures that MUST exist

**Committed to git. Total < 500 KB. Generated by `scripts/make_fixtures.py` with a fixed seed, no network.**

#### The synthetic scene — `ai_engine/tests/conftest.py`

**The single most important fixture in the repo.** It is what makes coordinate math verifiable without network, weights, or a GPU.

```python
@dataclass(frozen=True)
class SyntheticScene:
    """A pair of images related by a KNOWN homography, plus the landmarks whose
    ground-truth correspondence is therefore also known. THE ground truth."""
    image_a: np.ndarray            # (H,W,3) uint8 — the "photo"
    image_b: np.ndarray            # (H,W,3) uint8 — image_a warped by H_true
    H_true: np.ndarray             # (3,3) float64 — a-frame -> b-frame. THE ANSWER.
    landmarks_a: np.ndarray        # (K,2) float32 — points in a
    landmarks_b: np.ndarray        # (K,2) float32 — == dehomogenize(H_true @ landmarks_a)
    noise_px: float                # the injected correspondence noise, for tolerance assertions
    outlier_fraction: float


@pytest.fixture
def synthetic_scene() -> SyntheticScene:
    """Default: mild projective warp (rotation 12°, scale 0.85, tilt), noise_px=0.5,
    outlier_fraction=0.0. Textured enough that SIFT finds >500 keypoints."""


@pytest.fixture
def synthetic_scene_hard() -> SyntheticScene:
    """noise_px=2.0, outlier_fraction=0.80 — the realistic ground-to-satellite
    putative-set regime. This is the fixture that justifies PROSAC+MAGSAC and
    DISQUALIFIES LMEDS (50% breakdown point)."""
```

**Required scene variants**, each existing to trip one specific check:

| Fixture | Purpose |
|---|---|
| `synthetic_scene` | The happy path. `test_geometry_homography` recovers `H_true` within 1e-3. |
| `synthetic_scene_hard` | 80% outliers. Proves MAGSAC survives and **LMEDS confidently fits the outlier majority** (an explicit, asserted, documented failure). |
| `scene_collinear` | All correspondences on a line → **H5**. |
| `scene_tiny_hull` | Inliers in < 5% of the frame → **H6**. |
| `scene_horizon_crossing` | The vanishing line crosses the ROI → **H4**. *Reprojection error cannot see this — the surviving inliers all sit on the good side of the line. This fixture is the only thing that catches it.* |
| `scene_mirrored` | `det(H̃) ≤ 0` → **H2**. |
| `scene_permuted_landmarks` | **A different but visually identical field.** Fits beautifully by every metric that only inspects surviving matches → caught **only** by **H11** (landmark hull cyclic order). |
| `scene_blank` | A featureless window → empty FeatureSet, no raise. |

#### `SyntheticWindowSource` — `ai_engine/windows/testing.py`

Procedural farmland from a `(key, seed)` hash: crop rows at a seeded orientation and spacing, field-border polygons, a canal ribbon, a tree lattice. **Plus `ground_truth_homography(window_ref, camera_pose) -> np.ndarray`.**

**This is what makes the *entire engine* testable with no network and no fixtures on disk, and it lets us measure end-to-end error against a known answer.** It ships in the package (not in `tests/`) because `tests/e2e/` uses it too.

#### `gis/tests/fixtures/`

| Fixture | Purpose |
|---|---|
| `synthetic_ortho.tif` | **64×64 GeoTIFF, committed**, known CRS (EPSG:32633) + known geotransform. Backs `LocalOrthophotoProvider` tests, `detect_georeferencing()`, and the whole offline `gis` suite. |
| `plain.tif` | **A TIFF with NO georeferencing** — GDAL hands back the identity transform for it. **This fixture is the difference between `is_geotiff` meaning something and marking every scanned TIFF as georeferenced at the equator.** |
| `tiles/{z}/{x}/{y}.png` | A handful of committed 256×256 tiles backing `FixtureProvider`. |
| `slippy_goldens.json` | §13.3. |

#### `tests/fixtures/`

| Fixture | Purpose |
|---|---|
| `field_photo.jpg` | A small (≤ 200 KB) ground-level field photo **with EXIF GPS** — exercises the ingest → prior → search path end to end. |
| `field_photo_no_gps.jpg` | The same, EXIF stripped — exercises `422 SEARCH_HINT_REQUIRED` and the map-click hint path. |
| `field_photo_rotated.jpg` | **EXIF `Orientation = 6`** — proves ingest normalises it and that `width`/`height` are stored post-rotation. |

### 13.3 The golden-value tests

Numbers, not tolerances. **These are checked against published references, not against our own implementation.**

| Test | Assertion |
|---|---|
| `test_tiles_math::test_osm_goldens` | `lonlat_to_tile(-0.1278, 51.5074, 12) == TileRef(12, 2047, 1362)` (London) and a table of ≥ 10 further published OSM tile numbers spanning both hemispheres and both sides of the prime meridian. |
| `test_tiles_math::test_constants` | `EARTH_CIRCUMFERENCE_M == 40075016.685578488` · `ORIGIN_SHIFT_M == 20037508.342789244` · `MAX_LATITUDE == 85.0511287798066` · `RESOLUTION_Z0_256 == 156543.03392804097`. Exact float equality — **these are definitions, not measurements.** |
| `test_tiles_math::test_resolution_table` | `resolution_at(z, φ)` matches the published `res(z,φ)` table for `z ∈ [0,22]` × `φ ∈ {0, 30, 45, 53, 60, 85}` within 1e-6 relative. |
| `test_tiles_math::test_roundtrip` | `lonlat → tile_fractional → lonlat` at `z ∈ [0,22]`, `φ ∈ [-85, 85]` → `< 1e-9°`. |
| `test_tiles_math::test_quadkey_goldens` | Published Bing quadkeys, both directions. |
| `test_geometry::test_known_homography` | `‖H_est − H_true‖_F / ‖H_true‖_F < 1e-3` on `synthetic_scene`. |
| `test_pipeline_e2e::test_pixel_error` | End-to-end on `SyntheticWindowSource`: **max landmark pixel error < 2 px**. |
| `test_crs::test_pixel_roundtrip` | `pixel_to_lonlat → lonlat_to_pixel` → `< 1e-6 px` on `synthetic_ortho.tif`. |

### 13.4 The CI gate — definition of done for any module

1. Unit tests pass **without network, GPU, model weights, Docker, or a DB** (DB tests are `@pytest.mark.db` and run separately).
2. `scripts/verify_boundaries.sh` passes — import-linter (§10.4) **and** the grep gates (§10.5).
3. `mypy --strict` passes on `ai_engine` and `gis`; `mypy` passes on `backend`.
4. `ruff` + `black` clean; `eslint` + `prettier` clean; `tsc --noEmit` clean.
5. `openapi-typescript` output is **byte-identical** to the committed `frontend/src/api/generated/schema.ts` — **a diff fails the build.** The API cannot change shape without the change being visible in a reviewed PR.
6. Public functions carry type hints and docstrings **stating units and coordinate frames** (`px` vs `m` vs `deg`; image frame vs window frame vs EPSG:4326). **Most bugs in this system will be a frame confusion; naming is the cheapest defence.**
7. New env vars appear in `.env.example` **and** in §9 of this contract, and have a default. CI asserts `.env.example` matches §9.
8. New backends/providers/exporters/**elevation providers/suggesters** are **registered and appear in the parametrised contract test.** A component that is not in the contract test does not exist.
9. **Compose files are NOT marked verified.** Docker is absent on this machine. The first CI run with Docker is the gate. No task may claim otherwise.
10. **★ NEW — every row of `docs/architecture/TRACEABILITY.md` names a test. A requirement with no test does not exist.** Same rule as #8, applied to the client's deliverables rather than to our components. **This is the rule whose absence let `elevation` ship as a fully-plumbed enum with no producer and `suggest_landmarks` ship as four endpoints with no algorithm** — both invisible to a definition-of-done that was per-module and per-unit but never per-requirement.
11. **★ NEW — `ApiErrorCode` and `.env.example` are GENERATED and byte-compared in CI**, exactly as `schema.ts` is (rule 5). Anything that mirrors a Python source of truth is generated or it drifts.

---

## Appendix A — the one-page mental model

```
                 SURVEYOR
                    │  marks landmarks on a photo (a human assertion, ADR-014)
                    ▼
  ┌──────────────────────────────────┐
  │ frontend   snake_case wire        │  stageToImage(p) = (p - t)/(s·D)   ← §8.6, ONE site
  │            React Query = server   │  Zustand = browser only            ← L7
  └──────────────┬───────────────────┘
                 │ POST /api/v1/images/{id}/match  →  202 in < 100 ms
                 ▼
  ┌──────────────────────────────────┐
  │ app.api  →  app.services  →  app.db │   ★ the API NEVER does CV (L5)
  └──────────────┬───────────────────┘
                 │ .delay()   →  Redis  →  Celery worker-cv
                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ gis.candidates.TileWindowSource                              │
  │   provider → tiles → stitch → crop → CandidateWindow          │
  │   (pixels + OPAQUE geotransform + gsd_m + georef_ce90_m)      │
  └──────────────┬───────────────────────────────────────────────┘
                 │  ★ THE SEAM: ai_engine.types.WindowSource (structural Protocol)
                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ ai_engine.run_match_job(ctx) -> MatchJobResult                │
  │   SIFT → FLANN → USAC_MAGSAC → degeneracy → score → rank      │
  │   ★ ENDS AT WINDOW PIXELS. Knows no CRS. (L3)                 │
  └──────────────┬───────────────────────────────────────────────┘
                 │  GcpPixelFix(window_xy, cov_px)
                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ gis.crs + gis.accuracy + gis.pose + gis.elevation             │
  │   window_px --(+0.5)--> sat_geotransform --> srid --> 4326     │
  │   cov_px --× gsd_m²--> TRUE metres --> CE90 + ellipse          │
  │   yaw_window --+ grid convergence--> yaw_true_north            │
  │   ★ THE ONLY BIRTHPLACE OF lat/lon, metres, and North         │
  └──────────────┬───────────────────────────────────────────────┘
                 ▼
        gcps.geom :: geography(Point, 4326)     ← ★ THE CANONICAL TRUTH
                 │
     everything after this is serialisation; nothing before it is a coordinate
```

**The four sentences that matter most:**

1. **`ai_engine` ends at pixels; `gis.crs` is the only birthplace of lat/lon.** This is why swapping Esri for Mapbox cannot change the matching algorithm, and why `cd ai_engine && pytest` runs on this machine today.
2. **The classical path is the default path and the tested path.** SIFT + FLANN + MAGSAC is a real algorithm with real accuracy. On this hardware it is also the *faster* configuration.
3. **A missing weight is a warning and a fallback, never an error — and never silent.**
4. **A GCP is a claim about the world and the homography is the evidence.** Refuse rather than answer wrongly; report two accuracies, always; and never change a delivered coordinate unless a human asks.
