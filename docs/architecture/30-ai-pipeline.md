# 30 — AI Engine Architecture (CV/ML)

**Owner:** CV/ML Architect
**Status:** Design — normative. Implementation agents code *exactly* to these signatures.
**Scope:** `backend/ai_engine/**` only. This package has **no** dependency on FastAPI, Celery, SQLAlchemy, or the `gis` package.

---

## 0. Prime directives

1. **The classical path is the product.** SIFT + FLANN/BF + MAGSAC++ must produce a correct end-to-end answer with zero weights, zero network, zero GPU. Deep models are *accelerators*, never prerequisites.
2. **Points are the universal currency, not descriptors.** The pipeline consumes `Correspondences`. `FeatureSet`/`MatchSet` are an implementation detail of the *detector-based* family. This is what lets LoFTR fit without lying (§3.4).
3. **The engine never imports `gis`.** It depends on the `TileProvider` and `ElevationProvider` *Protocols* it defines itself (§4). The composition root injects the real implementations.
4. **Degeneracy is a first-class output.** A confident wrong GCP is worse than no GCP. The scorer is *gated*, not merely penalized (§10).
5. **Report two accuracies.** Our geometry is often better than the basemap's own georeferencing. Conflating them is a lie (§7.6).

### 0.1 Verified environment facts this design is built on

Measured on the dev machine, not assumed:

| Fact | Value | Design consequence |
|---|---|---|
| `cv2.__version__` | 4.13.0 | — |
| `cv2.USAC_MAGSAC`, `cv2.UsacParams` | present | MAGSAC++ is the default estimator (§6.2) |
| `UsacParams.randomGeneratorState` | present | **RANSAC is seedable ⇒ tests are exactly reproducible** |
| `UsacParams.sampler = SAMPLING_PROSAC` | present | Landmark weights drive sample ordering (§5, step 22) |
| `cv2.SIFT_create`, `cv2.AKAZE_create` | present | Terminal fallbacks are guaranteed constructible |
| `cv2.xfeatures2d` | **absent** | No SURF/VGG/BoostDesc. Do not design around them. |
| `cv2.createLineSegmentDetector` | present | LSD usable, but still `hasattr`-guarded (build-dependent) |
| `torch.cuda.is_available()` | **False** (on a `torch 2.11+cu130` wheel) | **The deep path is CPU-only here.** LoFTR on a 1024² pair ≈ 2–5 s CPU. Deep matchers are therefore *hard-capped* to the top-K rerank stage by code, not convention (§12.2). |
| `osgeo.gdal` | 3.8.4 | Available for the local-GeoTIFF provider; unused by `ai_engine` core |

The CUDA finding is the single most load-bearing environmental fact in this document. Any design that puts a deep matcher in the inner loop is non-viable on the target hardware.

---

## 1. Module file tree

```
backend/ai_engine/
├── __init__.py                  # exports: run_match_job, Registry, version()
├── version.py                   # ENGINE_VERSION, per-component *_VERSION (cache-key inputs)
├── errors.py                    # exception hierarchy (§1.1)
├── config.py                    # AiEngineConfig + sub-configs (pydantic-free; stdlib dataclasses)
│
├── types/
│   ├── __init__.py              # re-exports every dataclass; the ONLY import site downstream uses
│   ├── enums.py                 # DescriptorKind, HomographyMethod, ViewRegime, SemanticClass, Severity, Device
│   ├── features.py              # FeatureSet, ImageRef, ExtractorCapabilities
│   ├── matches.py               # MatchSet, Correspondences, CorrespondenceRequest
│   ├── geometry.py              # HomographyResult, RansacConfig, PoseResult, CameraIntrinsics
│   ├── degeneracy.py            # DegeneracyCheck, DegeneracyReport
│   ├── landmarks.py             # Landmark, LandmarkSet, LandmarkEvidence, LandmarkFix
│   ├── tiles.py                 # TileRef, Tile, CandidateWindow, ProviderCapabilities, BBox
│   ├── semantics.py             # SemanticMap, CropRowField, TreeLattice, RidgeSet
│   ├── scoring.py               # ScoreEvidence, ScoreResult, ScoreTerms
│   ├── heatmap.py               # ConfidenceHeatmap, HeatmapComponent, CredibleRegion
│   └── results.py               # WindowResult, MatchJobResult, GcpFix, AccuracyEstimate
│
├── registry/
│   ├── __init__.py              # Registry singleton + register() decorator
│   ├── spec.py                  # ComponentSpec, ComponentKind, Resolution, ResolutionReport
│   ├── policy.py                # ★ resolve_with_fallback() — the ONLY place fallback policy exists
│   ├── weights.py               # WeightManifest, checksum verify, resolve_weight_path()
│   └── preflight.py             # preflight(config) -> PreflightReport  (boot-time, /health/models)
│
├── extractors/
│   ├── base.py                  # FeatureExtractor ABC
│   ├── sift.py                  # SiftExtractor            [TERMINAL FALLBACK]
│   ├── orb.py                   # OrbExtractor             [TERMINAL FALLBACK, binary]
│   ├── akaze.py                 # AkazeExtractor
│   ├── asift.py                 # AffineSimulatedExtractor (decorator over any extractor) — §9.3
│   ├── superpoint.py            # SuperPointExtractor      [weights, lazy]
│   └── dinov2.py                # Dinov2DenseExtractor     [weights, lazy]
│
├── matchers/
│   ├── base.py                  # Matcher ABC, DetectorFreeMatcher ABC
│   ├── bruteforce.py            # BruteForceMatcher        [TERMINAL FALLBACK]
│   ├── flann.py                 # FlannMatcher             [TERMINAL FALLBACK]
│   ├── superglue.py             # SuperGlueMatcher         [weights, lazy]
│   ├── lightglue.py             # LightGlueMatcher         [weights, lazy]
│   ├── loftr.py                 # LoFTRMatcher(DetectorFreeMatcher) [weights, lazy]
│   ├── filters.py               # lowe_ratio, mutual_nn, spatial_gate, dedupe_many_to_one
│   └── sources.py               # ★ CorrespondenceSource Protocol + the 3 implementations (§3.4)
│
├── geometry/
│   ├── base.py                  # GeometryEstimator ABC
│   ├── homography.py            # OpenCvHomographyEstimator
│   ├── normalize.py             # hartley_normalize(), denormalize_h()
│   ├── refine.py                # refine_symmetric_transfer() -> (H, cov) via scipy LM
│   ├── degeneracy.py            # ★ DegeneracyValidator — the check list (§8)
│   ├── pose.py                  # PoseEstimator: Zhang-plane + decomposeHomographyMat fallback (§9)
│   ├── intrinsics.py            # intrinsics_from_exif(), intrinsics_from_fov(), AgriVanishingPointCalibrator
│   ├── rectify.py               # horizon_to_rectifier(), vanishing_points_from_croprows() (§9.2)
│   └── uncertainty.py           # propagate_point_cov(), unscented_propagate(), error budget (§7.5)
│
├── tiles/
│   ├── protocol.py              # ★ TileProvider Protocol — the seam. No gis import.
│   ├── windows.py               # CandidateWindowBuilder (stitch tiles -> overlapping windows)
│   ├── candidates.py            # QuadtreeBeamSearch — step 3
│   └── testing.py               # SyntheticTileProvider — procedural farmland w/ known ground-truth H
│
├── semantics/
│   ├── base.py                  # SemanticSegmenter ABC
│   ├── classical.py             # ClassicalSemantics [DEFAULT, TERMINAL FALLBACK] — §11
│   ├── indices.py               # exg(), ndwi(), mndwi(), gli()
│   ├── croprows.py              # structure-tensor + FFT row/lattice estimation
│   ├── ridges.py                # multi-scale Hessian vesselness (roads/canals)
│   ├── sam.py                   # SamSegmenter    [weights, lazy]
│   ├── dinov2_seg.py            # Dinov2Semantics [weights, lazy]
│   └── compare.py               # semantic_similarity() -> S_s (§10.5)
│
├── landmarks/
│   ├── patches.py               # LandmarkPatchBank — multi-scale/affine patch extraction
│   ├── priors.py                # landmark_sampling_prior() -> spatial density map
│   ├── guided.py                # guided_rematch() — prior-H constrained second pass
│   ├── topology.py              # hull_order_invariant(), cross_ratio_signature()
│   └── consistency.py           # landmark_consistency() -> S_l (§10.4)
│
├── transform/
│   ├── slippy.py                # ★ exact tile math both directions (§7.1)
│   ├── mercator.py              # EPSG:3857 <-> EPSG:4326, R=6378137.0
│   ├── pixel_to_geo.py          # PixelGeoTransformer — image px -> lat/lon w/ covariance
│   └── dem.py                   # ElevationProvider Protocol, NullElevationProvider, flatness_test()
│
├── scoring/
│   ├── base.py                  # ScoringModel ABC
│   ├── composite.py             # CompositeScoringModel [DEFAULT] — §10
│   ├── calibration.py           # PlattCalibrator, IsotonicCalibrator, load_calibration()
│   └── calibration/
│       └── default-v1.json      # identity/uncalibrated + documented conservative prior
│
├── heatmap/
│   └── posterior.py             # CameraPosterior — GMM over camera locations (§13)
│
├── pipeline/
│   ├── context.py               # MatchContext (immutable per-job bundle)
│   ├── steps.py                 # the 9 steps, each a pure typed function
│   ├── orchestrator.py          # run_match_job(...) — the only public entry point
│   └── ranking.py               # rank_windows(), ambiguity_margin()
│
├── runtime/
│   ├── device.py                # select_device() — honours the CUDA-absent reality
│   ├── cache.py                 # CacheBackend Protocol, DiskCache, NullCache, cache keys (§12.3)
│   ├── parallel.py              # process_map() — sets cv2.setNumThreads(1) in children (§12.4)
│   └── logging.py               # structured events: ComponentFallback, StepTiming, DegeneracyTripped
│
└── py.typed
```

### 1.1 Exception hierarchy (`errors.py`)

```python
class AiEngineError(Exception): ...

class ConfigurationError(AiEngineError): ...
class ComponentUnavailable(ConfigurationError):
    """Fallback chain exhausted. Raised at COMPOSITION time, never per-request."""
class WeightsMissing(ComponentUnavailable): ...
class WeightsCorrupt(ComponentUnavailable): ...

class IncompatibleDescriptors(AiEngineError):
    """e.g. FLANN-KDTree asked to match BINARY descriptors, or D_a != D_b."""
class DetectorFreeRequiresImages(AiEngineError):
    """A detector-free matcher was invoked through the Matcher ABC without a live ImageRef."""

class DegenerateSolve(AiEngineError):
    """Carries the DegeneracyReport. Callers must handle; never swallow."""
    def __init__(self, report: "DegeneracyReport") -> None: ...

class InsufficientCorrespondences(AiEngineError): ...
class NoViableCandidate(AiEngineError):
    """Every window was rejected. This is a legitimate, expected outcome."""
class TileFetchError(AiEngineError): ...
```

---

## 2. The 9-step pipeline

Each step is a **pure typed function** in `pipeline/steps.py`. Purity is what makes the engine testable without FastAPI/Celery: the orchestrator wires them, Celery only wraps the orchestrator.

| # | Step | Function | Signature |
|---|---|---|---|
| 1 | Extract image features | `step1_extract_query_features` | `(ctx: MatchContext) -> FeatureSet` |
| 2 | Extract descriptors | *fused into 1* — see note | `extractor.extract_at(...)` for landmarks |
| 3 | Candidate tiles | `step3_generate_candidates` | `(ctx, seed: SearchSeed) -> list[CandidateWindow]` |
| 4 | Tile descriptors | `step4_extract_window_features` | `(ctx, w: CandidateWindow) -> FeatureSet` |
| 5 | Feature matching | `step5_correspond` | `(ctx, q: FeatureSet, t: FeatureSet, w) -> Correspondences` |
| 6 | Outlier rejection | `step6_estimate_homography` | `(ctx, c: Correspondences) -> HomographyResult` |
| 7 | Similarity score | `step7_score` | `(ctx, ev: ScoreEvidence) -> ScoreResult` |
| 8 | Rank | `step8_rank` | `(ctx, results: Sequence[WindowResult]) -> list[WindowResult]` |
| 9 | Best tile | `step9_finalize` | `(ctx, ranked: Sequence[WindowResult]) -> MatchJobResult` |

**Note on steps 1–2.** The brief separates "extract features" from "extract descriptors". In every modern extractor (SIFT, ORB, SuperPoint) detection and description are one call, and splitting them forces a wasteful re-traversal. They are therefore **one interface method, `extract()`**, and step 2 is realised as the *second* descriptor path that genuinely is separate and genuinely matters: **`extract_at()`**, which computes descriptors at *externally supplied* points — namely the user's landmarks, which no detector proposed. This is not a dodge; it is the honest factoring, and `extract_at` is the hinge the whole landmark algorithm turns on (§5).

```python
# pipeline/context.py
@dataclass(frozen=True, slots=True)
class MatchContext:
    job_id: str
    config: AiEngineConfig
    query_image: np.ndarray                  # (H,W,3) uint8 RGB
    query_image_ref: ImageRef
    landmarks: LandmarkSet
    seed: SearchSeed
    extractor: FeatureExtractor
    source: CorrespondenceSource
    estimator: GeometryEstimator
    segmenter: SemanticSegmenter
    scorer: ScoringModel
    tiles: TileProvider
    elevation: ElevationProvider
    cache: CacheBackend
    validator: DegeneracyValidator
    exif: ExifBundle | None = None

@dataclass(frozen=True, slots=True)
class SearchSeed:
    """Where to look. Exactly one of these is authoritative; precedence as ordered."""
    aoi: BBox | None = None                  # 1. explicit AOI polygon bbox  (radius ignored)
    point: tuple[float, float] | None = None # 2. user map click (lon, lat)  -> radius_m default 2000
    exif_gps: tuple[float, float] | None = None  # 3. EXIF GPS -> radius_m default 500
    radius_m: float = 2000.0
    zoom_levels: tuple[int, ...] = (17, 18, 19)
    def resolve(self) -> BBox: ...
```

---

## 3. The interfaces

### 3.1 `FeatureSet` and `FeatureExtractor`

```python
# types/enums.py
class DescriptorKind(StrEnum):
    BINARY = "binary"   # Hamming metric; descriptors stored bit-packed uint8
    FLOAT  = "float"    # L2 metric; descriptors L2-normalised float32

# types/features.py
@dataclass(frozen=True, slots=True)
class ImageRef:
    """Content-addressed handle. Lets a FeatureSet point back at its image without
    pinning the array in memory. Resolved via runtime.cache.ImageStore."""
    sha256: str
    width: int
    height: int
    def resolve(self, store: "ImageStore") -> np.ndarray | None: ...

@dataclass(frozen=True, slots=True)
class FeatureSet:
    # --- required ---
    keypoints: np.ndarray          # (N,2) float32. (x,y) pixels. Origin = top-left CORNER;
                                   #   integer coords = pixel CENTRES. Subpixel expected.
    descriptors: np.ndarray        # FLOAT : (N,D) float32, each row L2-normalised (||d||=1)
                                   # BINARY: (N,D//8) uint8, bit-packed, LSB-first per byte
    scores: np.ndarray             # (N,) float32 in [0,1]. Detector response, per-extractor
                                   #   normalised to [0,1] by rank: score_i = 1 - rank_i/N.
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
    image_ref: ImageRef | None = None  # REQUIRED by detector-free shims (§3.4)
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
        FLOAT rows not unit-norm (atol=1e-3), scores outside [0,1], dtype mismatch."""
    def select(self, idx: np.ndarray) -> "FeatureSet": ...
    def concat(self, other: "FeatureSet") -> "FeatureSet":
        """Raises IncompatibleDescriptors if kind/dim/extractor_name differ."""
    def transform(self, T: np.ndarray) -> "FeatureSet":
        """Map keypoints through a 3x3 homography (used to lift ASIFT tilt-sim
        keypoints back into the original frame). Descriptors unchanged; affine
        frames pushed forward by the local Jacobian of T."""

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
# extractors/base.py
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
        points: np.ndarray,                # (K,2) float32 (x,y) — user landmarks
        *,
        sizes: np.ndarray | None = None,   # (K,) float32 patch diameter px; None => config default
        angles: np.ndarray | None = None,  # (K,) float32 rad; None => extractor estimates (or 0)
        landmark_ids: np.ndarray | None = None,  # (K,) int32 written into FeatureSet.landmark_ids
    ) -> FeatureSet:
        """★ Describe at CALLER-SUPPLIED points. The user's landmarks were never detected
        by anything, so this is the only way they enter the descriptor space.
        Points falling outside the valid patch margin are DROPPED (returned set may be
        shorter than K); landmark_ids tells the caller which survived.
        Impl notes: SIFT/ORB/AKAZE -> cv2 .compute(); SuperPoint -> bilinear grid_sample
        of the dense descriptor map; DINOv2 -> bilinear sample of the patch-token grid."""

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

**Registered extractors**

| name | kind | D | weights | fallback |
|---|---|---|---|---|
| `sift` | float | 128 | — | **None (terminal)** |
| `orb` | binary | 256 | — | **None (terminal)** |
| `akaze` | binary | 486 | — | `orb` |
| `asift` | float | 128 | — | `sift` (decorator; degrades to 1 tilt) |
| `superpoint` | float | 256 | ✔ | `sift` |
| `dinov2` | float | 384 | ✔ | `sift` |

SIFT descriptors are stored **L2-normalised float32**, not the OpenCV uint8-ish 0–512 convention — normalise at the boundary so `DescriptorKind.FLOAT` means exactly one thing everywhere. Apply RootSIFT (L1-normalise, then element-wise sqrt, then L2-normalise) by default: it is free, strictly better, and keeps the L2 metric valid.

### 3.2 `MatchSet` and `Matcher`

```python
# types/matches.py
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
```

**Score normalisation contract.** `scores` must be comparable *across matchers*, because `S_f` (§10.2) averages them. Definition:
- Ratio-test matchers (FLANN/BF): `score = clip((r_thr - r) / (r_thr - r_min), 0, 1)` with `r_thr = 0.8`, `r_min = 0.3`.
- Learned matchers (SuperGlue/LightGlue/LoFTR): the network's own match confidence, already in `[0,1]`.

```python
# matchers/base.py
class Matcher(ABC):
    name: ClassVar[str]
    supported_kinds: ClassVar[frozenset[DescriptorKind]]
    requires_images: ClassVar[bool] = False   # True only for detector-free shims (§3.4)
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
        prior_H: np.ndarray,               # (3,3) float64 mapping a-frame -> b-frame
        radius_px: float,                  # search disk radius in the b frame
        prior_cov: np.ndarray | None = None,  # (9,9) cov of vec(prior_H); widens radius per-point
    ) -> MatchSet:
        """★ Spatially-constrained matching. Default impl: full match(), then reject any
        pair whose ||p_b - prior_H(p_a)|| > radius_eff. Efficient impls override to build
        the candidate list per-point BEFORE descriptor comparison (a KD-tree over b's
        keypoints), which is where the real speed and the real accuracy come from:
        the ratio test is computed against only the SPATIALLY PLAUSIBLE competitors, so
        the second-nearest neighbour is no longer a random field-texture repeat.
        radius_eff(p_a) = radius_px + k * sqrt(trace(J Sigma_H J^T)), k = 2.0, when prior_cov given."""

    def supports(self, a: FeatureSet, b: FeatureSet) -> bool: ...
    def validate_pair(self, a: FeatureSet, b: FeatureSet) -> None:
        """Raise IncompatibleDescriptors if:
           - a.descriptor_kind != b.descriptor_kind
           - a.descriptor_kind not in self.supported_kinds
           - a.descriptor_dim != b.descriptor_dim
           - a.extractor_name != b.extractor_name  (WARN only — ASIFT/SIFT cross is legitimate)"""
    def params_hash(self) -> str: ...
```

`FlannMatcher` selects its index from `descriptor_kind` automatically — `KDTreeIndexParams(trees=4)` for FLOAT, `LshIndexParams(table_number=12, key_size=20, multi_probe_level=2)` for BINARY — and raises `IncompatibleDescriptors` on a mixed pair. This is precisely the bug class the `descriptor_kind` field exists to prevent: FLANN-KDTree on packed ORB bytes returns plausible-looking garbage rather than failing.

Matcher table:

| name | kinds | family | weights | fallback |
|---|---|---|---|---|
| `bruteforce` | float, binary | detector-based | — | **None (terminal)** |
| `flann` | float, binary | detector-based | — | `bruteforce` |
| `superglue` | float (D=256) | detector-based | ✔ | `flann` |
| `lightglue` | float | detector-based | ✔ | `flann` |
| `loftr` | — | **detector-free** | ✔ | `flann` (via source swap, §3.4) |

### 3.3 `Correspondences` — the universal currency

```python
@dataclass(frozen=True, slots=True)
class Correspondences:
    pts_a: np.ndarray              # (M,2) float32 — query-image pixels
    pts_b: np.ndarray              # (M,2) float32 — window pixels
    scores: np.ndarray             # (M,) float32 in [0,1]
    image_size_a: tuple[int, int]
    image_size_b: tuple[int, int]
    source_name: str
    is_dense: bool                 # True => produced detector-free; no stable feature indices exist
    weights: np.ndarray | None = None
        # ★ (M,) float32 > 0. Landmark-derived PRIORITY, not confidence.
        # Sort key for PROSAC sampling. See §5 step 22.
    landmark_ids: np.ndarray | None = None   # (M,) int32; >=0 => derived from user landmark k, -1 otherwise
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
        """Union of several sources (e.g. SIFT + LoFTR + landmark fixes).
        Two correspondences are duplicates iff both endpoints are within dedupe_px;
        the higher-weight one survives."""
```

### 3.4 The detector-free problem, solved honestly

LoFTR does not have detections. It consumes **two images** and emits **point pairs** directly. `match(a: FeatureSet, b: FeatureSet) -> MatchSet` is therefore *structurally wrong* for it:

- There are no keypoints to put in `a.keypoints` before matching — LoFTR's points are an *output*.
- `MatchSet.indices` presuppose stable per-image feature arrays that exist independently of the pair. LoFTR's points are **pair-dependent**: match image A against B and against C and you get two *different* point sets in A. There is no "A's features".

Three ways to respond. Two are dishonest:

- ❌ **Fabricate FeatureSets** — run a detector purely to have something to put in `a`, then ignore it and return LoFTR's points reindexed. The returned `MatchSet.indices` would point at keypoints that had nothing to do with the match. Silent corruption of every downstream consumer that trusts `indices`.
- ❌ **Widen `Matcher.match()` to take images** — every matcher now accepts two params it must ignore, and `FeatureSet` stops being sufficient. The abstraction leaks into all five detector-based matchers to serve one.

✅ **Chosen: two ABCs behind one Protocol.** The pipeline never depends on `Matcher`. It depends on `CorrespondenceSource`, which both families satisfy natively.

```python
# matchers/base.py
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
        self, image_a, image_b, *, prior_H: np.ndarray, radius_px: float,
        mask_a=None, mask_b=None,
    ) -> Correspondences:
        """Default: match_images() then spatial gate. Real impls mask the coarse-level
        attention to the prior-consistent band, which is both faster and more accurate."""

    def match_images_batch(
        self, pairs: Sequence[tuple[np.ndarray, np.ndarray]],
    ) -> list[Correspondences]: ...
```

```python
# matchers/sources.py
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
    landmark_weights: "LandmarkWeightField | None" = None   # §5 step 21

@runtime_checkable
class CorrespondenceSource(Protocol):
    """★ THE seam the pipeline depends on. Neither Matcher nor DetectorFreeMatcher
    appears in any pipeline signature."""
    name: str
    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...
    def params_hash(self) -> str: ...


class DetectBasedSource:
    """extractor + matcher -> Correspondences."""
    def __init__(self, extractor: FeatureExtractor, matcher: Matcher) -> None: ...
    def correspond(self, req: CorrespondenceRequest) -> Correspondences:
        # 1. a = req.features_a or extractor.extract(req.image_a, req.mask_a)
        # 2. b = req.features_b or extractor.extract(req.image_b, req.mask_b)
        # 3. ms = matcher.match_guided(a, b, prior_H=..., radius_px=...) if req.prior_H
        #         else matcher.match(a, b)
        # 4. c = ms.to_correspondences(a, b)
        # 5. c = attach_landmark_weights(c, req.landmark_weights)
        ...

class DetectorFreeSource:
    """LoFTR -> Correspondences. Natural fit; no adaptation, no loss."""
    def __init__(self, matcher: DetectorFreeMatcher) -> None: ...
    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...

class EnsembleSource:
    """Union of sources, e.g. ['asift','loftr']. Correspondences.merge() dedupes.
    THE recommended deep configuration: LoFTR finds correspondence in the
    low-texture field interior where SIFT finds nothing; SIFT nails the
    high-frequency corners LoFTR's 1/8-resolution coarse stage misses.
    They fail in complementary places, which is the only good reason to ensemble."""
    def __init__(self, sources: Sequence[CorrespondenceSource], *, dedupe_px: float = 2.0) -> None: ...
    def correspond(self, req: CorrespondenceRequest) -> Correspondences: ...
```

**The residual honesty problem.** Some external plugin socket may be typed `Matcher` and be handed `"loftr"` by config. For exactly that case, and *only* that case:

```python
# matchers/loftr.py
class LoFTRAsMatcher(Matcher):
    """LOSSY SHIM. Provided for Matcher-typed plugin sockets only. The pipeline
    does NOT use this — it uses DetectorFreeSource.

    Honest statement of what is given up:
      * a.descriptors / b.descriptors are IGNORED. Only a.image_ref / b.image_ref are read.
      * The returned MatchSet.indices do NOT index a.keypoints / b.keypoints. They index
        the AUGMENTED FeatureSets returned by `last_augmented()`. A caller that uses
        `indices` against the ORIGINAL FeatureSets gets WRONG POINTS.
      * Therefore match() sets meta['indices_refer_to'] = 'augmented' and
        meta['augmented_token'] = <uuid>; MatchSet.validate() is not sufficient to
        catch misuse, so DetectBasedSource asserts `not matcher.requires_images`.
    Prefer DetectorFreeSource. This class exists so that the failure is LOUD and
    DOCUMENTED rather than silent."""
    requires_images: ClassVar[bool] = True

    def __init__(self, inner: DetectorFreeMatcher, store: "ImageStore") -> None: ...
    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Raises DetectorFreeRequiresImages if a.image_ref/b.image_ref is None or
        unresolvable in the store."""
    def last_augmented(self) -> tuple[FeatureSet, FeatureSet]:
        """The FeatureSets that match()'s indices actually refer to. Not thread-safe by
        construction — another reason to prefer DetectorFreeSource."""
```

`DetectBasedSource.__init__` asserts `not matcher.requires_images`, so the shim can never be silently wired into the normal path.

### 3.5 `GeometryEstimator`

```python
# types/geometry.py
class HomographyMethod(StrEnum):
    MAGSAC   = "magsac"     # cv2.USAC_MAGSAC          [DEFAULT]
    PROSAC   = "prosac"     # UsacParams(sampler=SAMPLING_PROSAC, score=SCORE_METHOD_MAGSAC)
    RANSAC   = "ransac"     # cv2.RANSAC               [baseline]
    LMEDS    = "lmeds"      # cv2.LMEDS                [available; NOT recommended — §6.1]
    USAC_ACC = "usac_accurate"
    LSQ      = "lsq"        # no robustification; tests / already-clean inliers only

@dataclass(frozen=True, slots=True)
class RansacConfig:
    method: HomographyMethod = HomographyMethod.MAGSAC
    threshold_px: float = 5.0      # MAGSAC: an UPPER BOUND on noise, not a tuned inlier gate
    confidence: float = 0.9999
    max_iters: int = 10_000
    min_inliers: int = 12          # hard floor; 4 is the algebraic minimum, 12 the statistical one
    refine: bool = True            # LM re-fit on inliers (symmetric transfer)
    compute_covariance: bool = True
    lo_method: int = 4             # cv2.LOCAL_OPTIM_SIGMA
    lo_iterations: int = 10
    seed: int = 0                  # -> UsacParams.randomGeneratorState. VERIFIED settable.
    normalize: bool = True         # Hartley pre-conditioning

@dataclass(frozen=True, slots=True)
class HomographyResult:
    H: np.ndarray                  # (3,3) float64, a-frame -> b-frame.
                                   #   Scale-fixed: H /= H[2,2] if |H[2,2]| > 1e-12
                                   #   else H /= ||H||_F  (H[2,2]≈0 is legal: the line at
                                   #   infinity maps through the principal point)
    inlier_mask: np.ndarray        # (M,) bool, aligned to the input Correspondences
    num_inliers: int
    reproj_error: float            # symmetric transfer RMS over INLIERS, px
    method: HomographyMethod
    num_iters: int
    threshold_px: float
    refined: bool
    condition_number: float        # cond_2(H~) on the HARTLEY-NORMALISED H — see §6.3
    determinant: float             # det(H~)
    covariance: np.ndarray | None = None   # (9,9) float64, cov of vec(H) under gauge ||h||=1
    normalization: tuple[np.ndarray, np.ndarray] | None = None   # (T_a, T_b)
    residuals: np.ndarray | None = None    # (M,) per-correspondence symmetric transfer error, px

    def warp_points(self, pts: np.ndarray) -> np.ndarray: ...
    def warp_points_with_cov(
        self, pts: np.ndarray, pt_cov: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """-> ((N,2) warped, (N,2,2) covariance). §7.5."""
    @property
    def inlier_ratio(self) -> float: ...

# geometry/base.py
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
        Returns a result with num_inliers < config.min_inliers rather than raising —
        the DEGENERACY VALIDATOR decides what is acceptable, not the estimator.
        Separation of concerns: estimation reports, policy judges."""

    @abstractmethod
    def refine_homography(
        self, H0: np.ndarray, pts_a: np.ndarray, pts_b: np.ndarray, *,
        weights: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """LM minimisation of the symmetric transfer error on the given (inlier) set.
        -> (H_refined (3,3), covariance (9,9) | None). §6.4."""
```

### 3.6 `ScoringModel`

```python
# types/scoring.py
@dataclass(frozen=True, slots=True)
class ScoreTerms:
    s_feature: float          # [0,1]  §10.2
    s_geometry: float         # [0,1]  §10.3
    s_landmark: float         # [0,1]  §10.4
    s_semantic: float | None  # [0,1] or None if semantics disabled -> weights renormalise
    gate: float               # [0,1]  degeneracy gate, multiplicative
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
    confidence: float           # 0..100 — THE number the product reports
    raw: float                  # [0,1] pre-calibration, pre-clamp weighted sum * gate
    terms: ScoreTerms
    calibrated: bool
    calibration_id: str         # e.g. "default-v1" / "identity"
    clamp_reason: str | None    # e.g. "regime=OBLIQUE_RAW ceiling 60"
    status: Literal["accepted", "advisory", "rejected"]
    feature_vector: np.ndarray  # (F,) float32 — the raw terms, PERSISTED so calibration
                                #   can be refit offline without re-running any CV. §10.7

# scoring/base.py
class ScoringModel(ABC):
    name: ClassVar[str]
    @abstractmethod
    def score(self, evidence: ScoreEvidence) -> ScoreResult: ...
    @abstractmethod
    def feature_names(self) -> tuple[str, ...]:
        """Column names for ScoreResult.feature_vector. Stable across versions or the
        persisted training data becomes unreadable."""
```

---

## 4. The `TileProvider` seam

`ai_engine` must never `import gis`. It declares the Protocol it needs; `gis` implements it; the composition root injects it. Dependency inversion: both packages depend on `ai_engine.tiles.protocol`, which depends on nothing.

```python
# tiles/protocol.py   — imports: numpy, typing, dataclasses. NOTHING ELSE.
@dataclass(frozen=True, slots=True)
class TileRef:
    z: int
    x: int
    y: int                 # slippy / XYZ convention: y=0 at NORTH. (TMS flips this — do not.)
    provider: str
    layer: str = "satellite"
    def key(self) -> str: ...          # "{provider}/{layer}/{z}/{x}/{y}"
    def parent(self) -> "TileRef": ...
    def children(self) -> tuple["TileRef", ...]: ...

@dataclass(frozen=True, slots=True)
class Tile:
    ref: TileRef
    rgb: np.ndarray                    # (S,S,3) uint8 RGB. S == ProviderCapabilities.tile_size
    bounds_3857: tuple[float, float, float, float]   # (minx, miny, maxx, maxy) metres
    fetched_at: float                  # unix ts
    etag: str | None = None
    is_placeholder: bool = False       # ★ provider returned "no imagery"/blank. MUST be
                                       #   excluded from candidate windows — a blank tile
                                       #   matches everything and nothing.

@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    name: str
    min_zoom: int
    max_zoom: int
    tile_size: int                     # 256 or 512
    crs: str                           # "EPSG:3857"
    requires_key: bool
    georef_ce90_m: float               # ★ the provider's OWN absolute georeferencing error,
                                       #   CE90 metres. Flows straight into §7.6. This is
                                       #   frequently the DOMINANT error term and it is not
                                       #   reducible by anything the AI engine does.
    max_concurrent: int
    attribution: str
    supports_multispectral: bool = False   # gates true NDWI vs the HSV heuristic (§11.4)
    bands: tuple[str, ...] = ("R", "G", "B")

@runtime_checkable
class TileProvider(Protocol):
    name: str
    def capabilities(self) -> ProviderCapabilities: ...
    def get_tile(self, ref: TileRef) -> Tile: ...
    def get_tiles(self, refs: Sequence[TileRef]) -> list[Tile]:
        """Batch fetch. Implementations parallelise internally up to max_concurrent.
        SYNCHRONOUS by design: ai_engine runs inside Celery worker processes, and
        forcing an event loop into CPU-bound worker code buys nothing. The provider
        may use asyncio internally behind this sync facade."""
    def covers(self, bbox: BBox, z: int) -> bool: ...
```

`SyntheticTileProvider` (`tiles/testing.py`) generates deterministic procedural farmland — crop rows at a seeded orientation/spacing, field-border polygons, a canal ribbon, a tree lattice — from a `(z,x,y,seed)` hash, plus `ground_truth_homography(ref, camera_pose) -> np.ndarray`. This is what makes the *entire engine* testable with no network and no fixtures, and it lets us measure end-to-end geo error against a known answer.

```python
# transform/dem.py
@runtime_checkable
class ElevationProvider(Protocol):
    name: str
    vertical_datum: Literal["ellipsoidal", "egm96", "egm2008", "unknown"]
    def sample(self, lonlat: np.ndarray) -> np.ndarray:
        """(N,2) lon/lat deg -> (N,) metres. NaN where unavailable — NEVER 0.0."""
    def resolution_m(self) -> float: ...

class NullElevationProvider:
    """DEFAULT. sample() -> all-NaN. Downstream sets elevation_source='none' and
    emits altitude=None. Emitting 0.0 would be a lie that a surveyor might act on."""
```

---

## 5. The landmark matching algorithm

**The differentiator.** Naively, user landmarks are decoration: you match the whole image and read off where the marks land. That wastes the single highest-value signal in the system — a human has told us *exactly where the semantically meaningful, temporally stable, cross-view-recognisable structure is*. Those marks should steer detection, matching, sampling, scoring, and rejection.

Seven mechanisms, in the order they fire:

| # | Mechanism | Effect |
|---|---|---|
| M1 | Landmark-anchored affine patch bank | Landmarks get descriptors no detector would have produced |
| M2 | Landmark-biased detection budget | More keypoints where the user says it matters |
| M3 | Semantic typing gate | A "tree" landmark only matches tree-like sat regions — prunes the search hard |
| M4 | Landmark-seeded minimal solve | ≥4 landmark fixes ⇒ an H hypothesis with no RANSAC at all |
| M5 | PROSAC weight injection | Landmark correspondences are sampled first |
| M6 | Guided rematch under a prior H | The ratio test competes only against spatially plausible rivals |
| M7 | Landmark-consistency scoring + topology veto | Landmarks judge the answer, not just decorate it |

```python
# types/landmarks.py
class LandmarkType(StrEnum):
    UNSPECIFIED = "unspecified"
    TREE = "tree"; POLE = "pole"; FIELD_CORNER = "field_corner"
    BUILDING = "building"; GREENHOUSE = "greenhouse"
    CANAL_JUNCTION = "canal_junction"; ROAD_JUNCTION = "road_junction"
    WATER_EDGE = "water_edge"; ROCK = "rock"; GATE = "gate"

@dataclass(frozen=True, slots=True)
class Landmark:
    id: int
    xy: tuple[float, float]        # query-image px, subpixel, user-placed
    type: LandmarkType = LandmarkType.UNSPECIFIED
    label: str | None = None
    radius_px: float = 32.0        # user-adjustable; the patch scale
    user_weight: float = 1.0       # [0.25, 4.0]; UI "how sure are you"
    sigma_px: float = 3.0          # ★ HUMAN CLICK PRECISION. Propagated in §7.5.
                                   #   A user cannot click a tree trunk to 0.5 px.
                                   #   Default 3.0 px; 8.0 for diffuse types (WATER_EDGE, TREE).

@dataclass(frozen=True, slots=True)
class LandmarkSet:
    items: tuple[Landmark, ...]
    image_size: tuple[int, int]
    def points(self) -> np.ndarray: ...      # (K,2) float32
    def weights(self) -> np.ndarray: ...     # (K,) float32
    def sigmas(self) -> np.ndarray: ...      # (K,) float32
    def hull_order(self) -> np.ndarray: ...  # (J,) int32, CCW convex-hull cyclic order (§5, M7)

@dataclass(frozen=True, slots=True)
class LandmarkFix:
    """A putative sat-window location for one landmark, BEFORE any global H exists."""
    landmark_id: int
    xy_window: tuple[float, float]
    score: float                   # [0,1]
    method: Literal["patch_nn", "semantic_centroid", "ridge_junction", "lattice_node"]
    ambiguity: float               # best/second-best ratio; > 0.9 => unreliable, weight down

@dataclass(frozen=True, slots=True)
class LandmarkEvidence:
    """Post-H, per-landmark verification. Feeds S_l."""
    landmark_id: int
    predicted_window_xy: tuple[float, float]   # H @ landmark
    in_bounds: bool
    local_inliers: int                          # inliers within R_L px of the landmark
    zncc: float                                 # [-1,1] warped-patch vs window patch
    semantic_agree: float                       # [0,1] predicted class vs landmark type
    direct_fix: LandmarkFix | None
    transfer_residual_px: float | None          # ||fix - H@landmark||, if direct_fix
    predicted_cov: np.ndarray                   # (2,2) px^2 in window frame
```

### 5.1 Pseudocode

**Inputs:** `I_q` (H×W×3 uint8), `L = {(x_k, y_k, type_k, r_k, w_k, σ_k)}`, `seed`, `config`.
**Output:** `MatchJobResult`.

```
PHASE A — QUERY ANALYSIS (once per job)

 1. I_g   <- grayscale(I_q);  V <- exg(I_q)                       # Excess Green, §11.1
 2. Sem_q <- segmenter.segment(I_q)                               # SemanticMap, §11
 3. VP    <- AgriVanishingPointCalibrator.estimate(Sem_q, I_q)    # §9.2
       # crop rows -> VP1; field borders ⟂ rows -> VP2; horizon = VP1 × VP2
       # if VP1 ⟂ VP2 on the ground: solve f from the orthogonality constraint
 4. K     <- intrinsics_from_exif(exif)                           # §9.1
             ?? VP.focal_px  (if VP.orthogonal_pair and VP.f_sq > 0)
             ?? intrinsics_from_fov(W, hfov=60°)                  # documented last resort
 5. regime, tilt0 <- classify_regime(VP.horizon, K, exif)         # §8.3
             # NADIR | OBLIQUE_RECTIFIABLE | OBLIQUE_RAW | GROUND_HORIZON

 6. IF regime in {OBLIQUE_RECTIFIABLE} AND VP.horizon is not None:
        R_rect, H_rect <- horizon_to_rectifier(VP.horizon, K, canvas)   # §9.2
        I_w  <- warp(I_q, H_rect);   L_w <- H_rect @ L                  # landmarks warp too
        # ★ mask out everything ABOVE the horizon (+ 5% margin). Sky and the far
        #   ground beyond the useful depth contribute only outliers and, worse,
        #   pull the RANSAC toward the vanishing line.
        M_w  <- ground_mask(H_rect, VP.horizon, margin=0.05)
    ELSE:
        H_rect <- I(3);  I_w <- I_q;  L_w <- L;  M_w <- ground_mask_or_none()

 7. # ---- M2: landmark-biased detection budget ----
    P <- landmark_sampling_prior(L_w, image_size, sigma=2*r_k)
         # P(x) = clip(β + (1-β) * Σ_k w_k·N(x; l_k, (2 r_k)² I) / Zmax, 0, 1),  β = 0.35
         # Guarantees a floor of 35% detection density everywhere (we still need global
         # structure for the homography — starving the periphery would concentrate the
         # inliers and trip the hull-area degeneracy check by our own hand).
    mask_det <- M_w * quantize(P)
    F_q      <- extractor.extract(I_w, mask=mask_det)
    F_q      <- retain_top_n_with_prior(F_q, P, n=config.max_features)
         # rank by scores * P(kp) rather than scores alone

 8. # ---- M1: landmark-anchored affine patch bank ----
    F_L <- extractor.extract_at(I_w, points=L_w.points(),
                                sizes=2*L_w.radii(), landmark_ids=L_w.ids())
    Bank <- LandmarkPatchBank.build(I_w, L_w, tilts=T, rots=R)
         # T = {1, √2, 2, 2√2} (tilt), R = {0, 60/t, 120/t, ...} deg (longitude)
         # ★ WHY: a similarity-covariant descriptor (SIFT) cannot survive a 60° viewpoint
         #   change. Simulating the tilt is the only classical answer that works. We pay
         #   the ~8x cost ONLY on the K landmark patches (K ≈ 4-12, 64px each) — NOT on
         #   the whole image. That is the trick: ASIFT cost, landmark-sized bill.
    F_q <- F_q.concat(F_L)


PHASE B — CANDIDATE GENERATION (step 3)

 9. bbox <- seed.resolve()
10. windows <- QuadtreeBeamSearch.run(                                   # §12.1
        tiles=provider, bbox=bbox, z_coarse=15, z_fine=max(seed.zoom_levels),
        beam=32, screen=cheap_global_screen, budget=config.max_tile_fetches)
        # coarse->fine beam over the quadtree; a level's survivors expand into children
11. windows <- CandidateWindowBuilder.build(
        tiles, refs=windows, window_px=1024, overlap=0.5, drop_placeholders=True)
        # ★ WINDOWS, NOT TILES. A homography needs global context and the true footprint
        #   almost never respects tile borders. A 256px tile at z=18 is ~120 m across —
        #   smaller than one field. 50% overlap guarantees any 512px footprint lies
        #   wholly inside at least one window.


PHASE C — PER-WINDOW (parallel; steps 4-7)

12. FOR each window w:  # process pool, cv2.setNumThreads(1) in children
13.     F_w   <- cache.get_or_compute(key(w.ref, extractor), lambda: extractor.extract(w.rgb))
14.     Sem_w <- cache.get_or_compute(key(w.ref, segmenter), lambda: segmenter.segment(w.rgb))

15.     # ---- M3: semantic typing gate ----
        FOR each landmark k with type_k != UNSPECIFIED:
            Reg_k <- Sem_w.regions_of(compatible_classes(type_k))
            IF Reg_k is empty:  fixes_k <- []   # this window CANNOT host landmark k
            ELSE:               gate_k  <- dilate(Reg_k, r=48px)
        # ★ A "greenhouse" landmark restricts matching to greenhouse-like blobs. On a
        #   1024² window that is typically <3% of the pixels — a ~30x reduction in the
        #   candidate set AND a large drop in the ratio-test's second-nearest distractor
        #   density, which is what actually kills wide-baseline matching.
        # If a window has NO region compatible with a HIGH-weight landmark, and
        # config.semantic_veto is on, SKIP the window entirely.

16.     # ---- M4: landmark-seeded minimal solve ----
        fixes <- []
        FOR each landmark k:
            cand <- Bank[k].match_into(F_w restricted to gate_k)   # best over tilt sims
            IF cand.ratio < 0.85: fixes.append(LandmarkFix(k, cand.xy, cand.score, "patch_nn", cand.ratio))
        FOR each landmark k with a structural type (FIELD_CORNER/CANAL_JUNCTION/ROAD_JUNCTION):
            fixes += structural_fix(k, Sem_w)   # ridge junctions, contour corners, lattice nodes
        H_seed <- None
        IF |fixes| >= 4:
            H_seed, ok <- estimate_homography(L_w[fixes], fixes.xy, RansacConfig(method=LSQ))
            IF NOT validator.quick_check(H_seed): H_seed <- None
        # ★ 4 good landmark fixes fully determine H. When the user marks 4 field
        #   corners this path alone can solve the job before a single SIFT match.

17.     # ---- global correspondence, pass 1 ----
        c1 <- source.correspond(CorrespondenceRequest(
                  image_a=I_w, image_b=w.rgb, features_a=F_q, features_b=F_w,
                  mask_a=M_w, prior_H=H_seed, guided_radius_px=64.0 if H_seed else None,
                  landmark_weights=LandmarkWeightField(L_w, R_L=96.0)))
18.     c1 <- filters.mutual_nn(c1);  c1 <- filters.dedupe_many_to_one(c1)
        # ★ many-to-one dedupe is NOT optional here. Crop rows are a periodic texture;
        #   without it, dozens of query points map to one sat point and RANSAC happily
        #   fits a rank-deficient H through the pile.

19.     c1 <- Correspondences.merge([c1, fixes_as_correspondences(fixes)], dedupe_px=2.0)
20.     IF c1.num_correspondences < 4: RETURN WindowResult(rejected="insufficient")

21.     # ---- M5: landmark weight injection ----
        FOR i in c1:
            d_i  <- min_k ||pts_a[i] - l_k||                    # dist to nearest landmark
            g_i  <- Σ_k w_k · exp(-d_ik² / (2·R_L²)),  R_L = 96 px
            lm_i <- 1.0 if c1.landmark_ids[i] >= 0 else 0.0
            weights[i] <- scores[i] · (1 + λ·g_i) · (1 + μ·lm_i),   λ = 2.0, μ = 3.0
        # A correspondence ON a user landmark gets up to 4x(1+2)=~12x the sampling
        # priority of a generic one far from any mark.

22.     # ---- M5 cont: PROSAC ----
        c1s, perm <- c1.sorted_by_weight()
        h1 <- estimator.estimate_homography(c1s.pts_a, c1s.pts_b,
                  RansacConfig(method=PROSAC, threshold_px=5.0, seed=job_seed),
                  weights=c1s.weights)
        # PROSAC draws minimal samples from the top of the sorted list first, so the
        # FIRST hypotheses are built from landmark correspondences. On 90%-outlier data
        # this is the difference between converging in 10^2 and 10^5 iterations.
        # NOTE: PROSAC is a SAMPLING order; passing unsorted input silently degrades it
        # to uniform RANSAC. sorted_by_weight() is mandatory, not advisory.

23.     rep1 <- validator.validate(h1, c1s, L_w, w, regime)
        IF rep1.gate == 0: RETURN WindowResult(rejected=rep1.hard_failures)

24.     # ---- M6: guided rematch, pass 2 ----
        r_eff <- clamp(3 · h1.reproj_error, 8.0, 48.0)
        c2 <- source.correspond(CorrespondenceRequest(
                  ..., prior_H=h1.H, prior_cov=h1.covariance, guided_radius_px=r_eff))
        c2 <- Correspondences.merge([c1s, c2, fixes_as_correspondences(fixes)])
        # ★ THE BIGGEST SINGLE WIN. Pass 1's ratio test compared each query descriptor
        #   against the WHOLE window, where a wheat-row patch has ~10^3 near-identical
        #   rivals, so the ratio test discards nearly every TRUE match as ambiguous.
        #   Under a prior H the disk of radius r_eff holds ~1 plausible rival, so the
        #   ratio test recovers matches it was structurally unable to accept before.
        #   Typical: inliers 25 -> 120+ on farmland.
25.     re-weight c2 as in step 21
26.     c2s, _ <- c2.sorted_by_weight()
        h2 <- estimator.estimate_homography(c2s.pts_a, c2s.pts_b,
                  RansacConfig(method=MAGSAC, threshold_px=4.0, seed=job_seed),
                  weights=c2s.weights)
        h2 <- estimator.refine_homography(h2.H, inliers(c2s), weights=inlier_weights)
              # -> covariance for §7.5

27.     # ---- M7: landmark consistency + topology veto ----
        ev_k <- [] ; FOR each landmark k:
            q_k   <- h2.H @ l_k
            Σ_k   <- J Σ_l J^T + A Σ_H A^T                       # §7.5, includes σ_k click noise
            n_k   <- #inliers with ||pts_a - l_k|| < R_L
            z_k   <- ZNCC(warp(patch(I_w, l_k, r_k), h2.H), patch(w.rgb, q_k, r_k·s_k))
            sem_k <- semantic_agreement(type_k, Sem_w at q_k)
            r_k   <- ||fixes[k].xy - q_k|| if fixes[k] else None
            ev_k.append(LandmarkEvidence(...))
        IF NOT hull_order_invariant(L_w.hull_order(), (h2.H @ L_w).hull_order()):
            RETURN WindowResult(rejected="landmark_topology")
        # ★ A homography is a projectivity: for points on the ground plane in front of
        #   the camera it PRESERVES the cyclic order of the convex hull. If the user's
        #   marks come out reshuffled, H is not a plausible ground-plane map of THIS
        #   landmark configuration — no matter how many texture inliers it found. This
        #   catches the classic "matched a different but visually identical field" error,
        #   which no reprojection threshold can catch because it fits beautifully.

28.     Sem_qw <- warp(Sem_q, h2.H)
        ev <- ScoreEvidence(c2s, h2, rep2, L_w, ev_k, Sem_qw, Sem_w, regime, ...)
        res_w <- scorer.score(ev)                                 # §10
29.     RETURN WindowResult(window=w, homography=h2, score=res_w, evidence=ev_k, ...)


PHASE D — RANK & FINALISE (steps 8-9)

30. ranked <- sort(results, by=score.confidence, desc)
31. margin <- ambiguity_margin(ranked)
        # margin = c[0] / max(c[1], ε), computed over NON-ADJACENT windows only:
        # overlapping windows SHOULD both score high (they see the same ground) — that
        # is agreement, not ambiguity. Cluster windows by centroid distance < window/2
        # and take the best per cluster BEFORE computing the margin.
32. IF margin < 1.05: clamp every confidence to <= 40; status <- "advisory"
        # two DIFFERENT places in the AOI look equally good -> we have not localised.
33. best <- ranked[0]
34. IF best.score.status == "rejected" OR best.score.confidence < config.min_confidence:
        RAISE NoViableCandidate(ranked)      # a legitimate outcome, not a failure

35. # ---- back out of the rectification ----
    H_total <- best.homography.H @ H_rect        # ORIGINAL query px -> window px
    Σ_total <- propagate(H_rect, best.homography.covariance)
    # ★ every reported GCP must be in the ORIGINAL image's pixel frame; the user marked
    #   points on the photo they uploaded, not on our rectified intermediate.

36. FOR each landmark k (original, unrectified xy):
        p_win        <- H_total @ l_k
        Σ_win        <- J Σ_l J^T + A Σ_H A^T                    # §7.5
        p_px_global  <- window_to_global_px(p_win, best.window)  # §7.2
        lon, lat     <- global_px_to_lonlat(p_px_global, z)      # §7.1
        Σ_geo        <- G Σ_win G^T                              # §7.4
        alt          <- elevation.sample([[lon,lat]])[0]         # NaN -> None
        rel_m        <- 2·sqrt(max eig Σ_win) · res(z, lat)      # §7.6
        abs_m        <- sqrt(rel_m² + provider.georef_ce90_m²)
        emit GcpFix(k, lon, lat, alt, AccuracyEstimate(rel_m, abs_m, ...), conf_k)
        # per-landmark confidence conf_k = job confidence · landmark_local_factor(ev_k)
        # ★ a landmark far from every inlier is EXTRAPOLATED by H and deserves less
        #   confidence than one sitting in a dense inlier cluster, even in the same solve.

37. pose  <- PoseEstimator.estimate(H_total, K, best.window, regime)     # §9
38. heat  <- CameraPosterior.build(ranked, bbox, grid=256)               # §13
39. flat  <- flatness_test(elevation, best.window)                        # §7.7
        IF flat.rms_m > 0.5: downgrade confidence by factor exp(-(rms/1.0)²), note it
40. RETURN MatchJobResult(best, ranked[:k], gcps, pose, heat, provenance, timings)
```

### 5.2 Why these mechanisms and not others

- **M6 (guided rematch) is the highest-leverage single step.** Wide-baseline matching on farmland fails less because descriptors are wrong than because the *ratio test* is a poor discriminator in a periodic texture: every wheat patch has a thousand near-twins, so `d1/d2 → 1` and the true match is thrown away. The ratio test's premise — that the second-nearest neighbour is a random distractor — is *false* on crop rows. Conditioning on a prior H repairs the premise rather than tuning around it.
- **M3 (semantic typing) prunes multiplicatively, not additively.** It shrinks the candidate set *and* the distractor density, so it improves both speed and the ratio test at once.
- **M7 (hull topology) catches the error class thresholds cannot.** Reprojection error is measured against the matches that *survived*; a confident match onto the wrong-but-identical field has a beautiful reprojection error. The user's landmark configuration is a global, human-supplied constraint that the wrong field will generally violate.
- **`sigma_px` on `Landmark` is not decoration.** Treating human clicks as exact makes every downstream error bar optimistic by roughly 3–8 px × ~0.5 m/px ≈ 1.5–4 m — which is the entire accuracy claim of the product.

---

## 6. Geometry estimation

### 6.1 MAGSAC++ vs RANSAC vs LMEDS

| | LMEDS | RANSAC | MAGSAC++ (`USAC_MAGSAC`) |
|---|---|---|---|
| Threshold | none needed | hard, must be tuned | **loose upper bound only** |
| Outlier breakdown | **50%** | ~90% w/ enough iters | ~90%+ |
| Local optimisation | no | limited in OpenCV's plain path | LO + SPRT |
| Threshold sensitivity | n/a | high | **low** (marginalises over σ) |
| Cost | low | low | ~1.5–3× RANSAC |
| Seedable | yes | yes | **yes** (`UsacParams.randomGeneratorState`) |

**LMEDS is disqualified, not merely dispreferred.** Its 50% breakdown point is a hard mathematical limit, and ground↔satellite putative sets routinely run **80–95% outliers**. LMEDS will not merely degrade — it will confidently return a homography fitted to the outlier majority. It stays in the enum for completeness and for LSQ-adjacent test scenarios; it must never be the default and the config validator should warn when it is selected.

**Recommendation:**
- **Pass 1 (landmark-seeded): `HomographyMethod.PROSAC`** — `UsacParams(sampler=SAMPLING_PROSAC, score=SCORE_METHOD_MAGSAC, loMethod=LOCAL_OPTIM_SIGMA)`. MAGSAC's σ-marginalised scoring *plus* PROSAC's quality-ordered sampling. This is where landmark weights pay off.
- **Pass 2 (guided rematch): `HomographyMethod.MAGSAC`** — after the guided pass the inlier ratio is high and correspondences are dense; uniform sampling is fine and MAGSAC's scoring is the best available.
- **Tests: `RANSAC` or `MAGSAC` with an explicit `seed`.** Since `randomGeneratorState` is settable, exact-reproducibility tests are legitimate. Still assert on tolerances (`||H - H_gt||` under a norm, inlier count ≥ N) rather than exact float equality — reproducible ≠ bit-stable across OpenCV builds.

`threshold_px = 5.0` for MAGSAC is deliberately *not* tuned. Under MAGSAC++ the threshold is an upper bound on the noise scale being marginalised over; tuning it defeats the point of using MAGSAC. Tune `min_inliers` and the degeneracy gates instead.

### 6.2 Concrete call

```python
p = cv2.UsacParams()
p.threshold            = cfg.threshold_px
p.confidence           = cfg.confidence
p.maxIterations        = cfg.max_iters
p.sampler              = cv2.SAMPLING_PROSAC if cfg.method is PROSAC else cv2.SAMPLING_UNIFORM
p.score                = cv2.SCORE_METHOD_MAGSAC
p.loMethod             = cfg.lo_method            # cv2.LOCAL_OPTIM_SIGMA
p.loIterations         = cfg.lo_iterations
p.final_polisher       = cv2.LSQ_POLISHER
p.randomGeneratorState = cfg.seed                 # VERIFIED present -> determinism
p.isParallel           = False                    # we parallelise ACROSS windows (§12.4)
H, mask = cv2.findHomography(pts_a, pts_b, params=p)
```

`isParallel=False` is deliberate: the process pool already saturates the cores across windows, and nested parallelism produces thread thrash that measurably *slows* the job.

### 6.3 Hartley normalisation

Always condition before estimating and before computing any condition number.

For point set `{p_i}`: translate the centroid to the origin, scale isotropically so the mean distance to the origin is `√2`:

```
T = [[s, 0, -s·x̄],
     [0, s, -s·ȳ],
     [0, 0,    1]],    s = √2 / mean_i ||p_i - p̄||
```

Estimate `H̃` on `(T_a p_a, T_b p_b)`, then `H = T_b⁻¹ H̃ T_a`.

**`condition_number` and `determinant` in `HomographyResult` are computed on `H̃`, not `H`.** `cond(H)` on raw pixel coordinates is dominated by the ~10³ coordinate magnitudes and is meaningless as a degeneracy signal — it will read ~10⁶ for a perfectly healthy homography. This distinction is why the field is documented on the dataclass; getting it wrong makes the degeneracy check either always-fire or never-fire.

### 6.4 Refinement and covariance

OpenCV refines internally but exposes **no covariance**. We need `Σ_H` for every error bar in §7.5, so we always re-fit:

Minimise the **symmetric transfer error** over inliers, with weights:

```
E(h) = Σ_i w_i · ( ||p_b_i - π(H p_a_i)||² + ||p_a_i - π(H⁻¹ p_b_i)||² )
```

`π` = homogeneous → Euclidean. Parameterise `h ∈ ℝ⁹` on the unit sphere (`||h|| = 1`, 8 DOF), solve with `scipy.optimize.least_squares(method="lm")` on the normalised coordinates, seeded from `H̃_ransac`.

Covariance at the optimum:

```
Σ_h ≈ σ_r² · (Jᵀ J)⁺        (Moore–Penrose; J is 2M×9 and rank-8 by the gauge freedom)
σ_r² = E(ĥ) / (2M − 8)
```

The pseudo-inverse is mandatory: `JᵀJ` is *exactly* singular along the scale direction `h`, so a plain inverse either raises or returns garbage. Project out the null direction (`Σ_h ← (I − ĥĥᵀ) Σ_h (I − ĥĥᵀ)`) before returning. Finally de-normalise the covariance through the Kronecker Jacobian of `H = T_b⁻¹ H̃ T_a`:

```
vec(H) = (T_aᵀ ⊗ T_b⁻¹) vec(H̃)   ⇒   Σ_H = (T_aᵀ ⊗ T_b⁻¹) Σ_h̃ (T_aᵀ ⊗ T_b⁻¹)ᵀ
```

(with `vec` column-major; the implementer must keep the ordering consistent with the Jacobians in §7.5 — a transposed `vec` convention here is a silent, plausible-looking error).

---

## 7. Coordinate transformation — the full math

Chain: **query px → `H_rect` → rectified px → `H_win` → window px → window→global px → Web Mercator (EPSG:3857) → lon/lat (EPSG:4326)**.

Constants: `R = 6378137.0` m (WGS84 semi-major; Web Mercator is spherical *by definition* and uses `a` for both axes). `S` = tile size (256 or 512). World extent `± πR = ±20037508.342789244` m.

### 7.1 Slippy tile ↔ lon/lat, both directions

`n = 2^z`, `λ` = longitude (deg), `φ` = latitude (deg), `φ_r = φ·π/180`.

**Forward (lon/lat → fractional tile):**
```
x_tile = (λ + 180) / 360 · n
y_tile = (1 − asinh(tan φ_r) / π) / 2 · n
```
`asinh(tan φ)` is the isometric latitude `ψ`. Use `asinh(tan φ)` — **not** `ln(tan φ + sec φ)`, which loses precision near the equator and overflows near the poles.

**Inverse (fractional tile → lon/lat):**
```
λ = x_tile / n · 360 − 180
φ = atan(sinh(π · (1 − 2 · y_tile / n))) · 180/π
```

**Latitude clamp.** Web Mercator is undefined at the poles; the standard extent stops at `φ = ±85.0511287798066°` (the latitude where `y` spans exactly `[0, n]`, i.e. `φ_max = atan(sinh π)`). Clamp on input and raise on out-of-range rather than silently wrapping.

**Global pixel coordinates at zoom z** (the frame all window math lives in):
```
W_px = S · 2^z                          # world width in pixels
px   = (λ + 180) / 360 · W_px
py   = (1 − asinh(tan φ_r) / π) / 2 · W_px

λ = px / W_px · 360 − 180
φ = atan(sinh(π · (1 − 2 · py / W_px))) · 180/π
```

**Tile ↔ global px:** `px = (x_tile_int + u) · S`, `py = (y_tile_int + v) · S` for intra-tile `(u,v) ∈ [0,S)²`. y increases **southward** (XYZ/slippy). TMS flips y (`y_tms = n − 1 − y_xyz`) — `TileRef` is XYZ, and any provider speaking TMS converts in its adapter, never in `ai_engine`.

### 7.2 Web Mercator (EPSG:3857)

```
X = R · λ_r                             λ_r in radians
Y = R · ln(tan(π/4 + φ_r/2)) = R · asinh(tan φ_r)

λ_r = X / R
φ_r = 2·atan(exp(Y / R)) − π/2 = atan(sinh(Y / R))
```

Global px ↔ 3857 at zoom z:
```
X = px / W_px · (2πR) − πR
Y = πR − py / W_px · (2πR)              # y flips: px is southward, Y is northward
```

**Window px → global px.** A `CandidateWindow` is a mosaic anchored at `(x0_tile, y0_tile)` at zoom `z`, so:
```
px_global = (x0_tile · S) + u_window
py_global = (y0_tile · S) + v_window
```
Exact, integer-anchored, no resampling — which is exactly why windows are built by *stitching whole tiles* rather than by cropping around an arbitrary centre. Sub-pixel-offset mosaics would inject a resampling bias into every GCP.

### 7.3 Ground resolution and scale

Mercator is conformal: locally an isotropic scaling, no shear. The point scale factor is `k(φ) = 1/cos φ`, so distances *on the map* are inflated by `1/cos φ`. Ground resolution:

```
res(z, φ) = (2πR · cos φ) / (S · 2^z)  [m/px]
```

For `S = 256`: `2πR/256 = 156543.03392804097`, hence the familiar

```
res(z, φ) = 156543.03392804097 · cos φ / 2^z   [m/px]
```

For `S = 512` (Mapbox `@2x`, Bing 512 variants) it is **half** that — the code must read `S` from `ProviderCapabilities.tile_size`, never hardcode 256. A hardcoded 256 against a 512 provider yields a 2× error in every reported accuracy while the lat/lon stay correct — a silent, plausible, doubly-dangerous bug.

| z | res @ φ=0 | res @ φ=40° | res @ φ=60° | tile span @ 40° |
|---|---|---|---|---|
| 15 | 4.777 | 3.660 | 2.389 | 937 m |
| 16 | 2.389 | 1.830 | 1.194 | 468 m |
| 17 | 1.194 | 0.915 | 0.597 | 234 m |
| 18 | 0.597 | 0.457 | 0.299 | 117 m |
| 19 | 0.299 | 0.229 | 0.149 | 59 m |

### 7.4 Pixel → lon/lat Jacobian

Let `W_px = S·2^z`, `t = π(1 − 2·py/W_px)`, so `φ = atan(sinh t)`.

```
∂λ/∂px = 360 / W_px                                    [deg/px]
∂λ/∂py = 0
∂φ/∂py = ∂φ/∂t · ∂t/∂py = sech(t) · (−2π/W_px)
```
and since `sinh t = tan φ` ⇒ `cosh t = sec φ` ⇒ `sech t = cos φ`:
```
∂φ/∂py = −2π · cos φ / W_px                            [rad/px]
∂φ/∂px = 0
```

So `G = ∂(λ,φ)/∂(px,py) = diag(360/W_px, −(360/W_px)·cos φ)` in **degrees**. The off-diagonals are exactly zero (conformality). In **metres** the Jacobian is isotropic and equals `res(z,φ)` on both axes — which is why the metric error budget below needs only a scalar, and why `res` is legitimate as a single number rather than a 2×2.

### 7.5 Error propagation, end to end

**Uncertainty sources**, in the query-image pixel frame:
```
Σ_p = σ_click² I₂        user landmark: σ_click = Landmark.sigma_px (default 3.0 px)
                         — the DOMINANT query-side term. SIFT localises to ~0.5 px;
                           a human clicks a tree to ~3 px. Do not model the human as a detector.
```

**Through H.** With `p = (u,v,1)`, `d = h₃₁u + h₃₂v + h₃₃`, `x' = n_x/d`, `y' = n_y/d`:

```
      1  ⎡ h₁₁ − x'·h₃₁    h₁₂ − x'·h₃₂ ⎤
J_p = ─  ⎢                              ⎥          (2×2, ∂p'/∂p)
      d  ⎣ h₂₁ − y'·h₃₁    h₂₂ − y'·h₃₂ ⎦
```

**Through H's own uncertainty.** With `h = vec(H) ∈ ℝ⁹`:

```
      1  ⎡ u  v  1  0  0  0  −x'u  −x'v  −x' ⎤
A_h = ─  ⎢                                   ⎥      (2×9, ∂p'/∂h)
      d  ⎣ 0  0  0  u  v  1  −y'u  −y'v  −y' ⎦
```

**Combined, in window pixels:**
```
Σ_win = J_p Σ_p J_pᵀ  +  A_h Σ_H A_hᵀ  +  σ_mosaic² I₂        σ_mosaic ≈ 0.2 px
```

The two terms have very different spatial behaviour and this is the crux of §5 step 36: `A_h Σ_H A_hᵀ` **grows quadratically with distance from the inlier cloud**, because an H constrained only in region Ω is extrapolating outside Ω. A landmark in the middle of a dense inlier cluster and one 800 px away can share a solve and differ by 5× in error. Per-landmark covariance is therefore mandatory; a single job-level accuracy number would be a fiction.

**To ground metres:**
```
Σ_ground = res(z,φ)² · Σ_win               [m²]     (isotropy of the conformal map)
σ_1σ      = res(z,φ) · sqrt(λ_max(Σ_win))  [m]      semi-major of the 1σ ellipse
```

**To lon/lat:** `Σ_geo = G Σ_win Gᵀ`, `G` from §7.4 (degrees²). Report the **error ellipse** (`semi_major_m`, `semi_minor_m`, `azimuth_deg` from the eigenvectors of `Σ_ground`), not a scalar — an oblique solve's error is strongly anisotropic (large along the viewing direction, small across it), and collapsing it to one number throws away the most actionable part of the estimate.

### 7.6 The two accuracies

```
relative_accuracy_m = 2 · res(z,φ) · sqrt(λ_max(Σ_win))              # ~95%, our geometry
absolute_accuracy_m = sqrt(relative_accuracy_m² + georef_ce90_m²)    # what a surveyor gets
```

```python
@dataclass(frozen=True, slots=True)
class AccuracyEstimate:
    relative_m: float            # our math, vs the basemap's own pixels
    absolute_m: float            # incl. the provider's georeferencing error
    semi_major_m: float
    semi_minor_m: float
    azimuth_deg: float           # of the semi-major axis, from North
    georef_ce90_m: float
    provider: str
    elevation_source: Literal["none", "dem", "exif"]
    vertical_datum: Literal["ellipsoidal", "egm96", "egm2008", "unknown"]
    dominant_term: Literal["click", "homography", "georef", "resolution"]
```

**This is the most important honesty in the document.** Our pipeline can genuinely land a GCP to sub-pixel accuracy on the basemap — ~0.3 m at z=19. But consumer basemaps carry **1–5 m absolute georeferencing error** (Sentinel-2 L1C ~8–10 m CE95), and *nothing the AI engine does can reduce it*: we are perfectly matching an imperfectly-placed picture. Reporting only `relative_m` would tell a surveyor they have 0.3 m GCPs when they have 3 m GCPs. `georef_ce90_m` is therefore a mandatory field on `ProviderCapabilities`, and `dominant_term` exists so the UI can say the useful thing — *"your accuracy is limited by the basemap, not by the match; switch to a local orthophoto"*.

### 7.7 Elevation and where a DEM plugs in

The tile **is** the ground, so the px→lon/lat chain needs no elevation. Elevation matters in exactly three places:

1. **Output altitude.** `alt = elevation.sample([[lon, lat]])`. `NaN → None`, never `0.0`.
2. **Flatness test — the planar assumption's audit.** Sample the DEM on a grid over the warped quad, fit a plane by least squares, take the RMS residual:
   ```
   flatness_rms_m = sqrt( mean_i (h_i − (a·X_i + b·Y_i + c))² )
   ```
   `> 0.5 m` over a ~200 m field ⇒ the scene is not planar ⇒ the homography is *structurally* wrong, however well it fits. Multiply confidence by `exp(−(rms/1.0)²)` and record it. This converts an unverifiable assumption into a measured quantity — the single best use of a DEM here.
3. **Plane + parallax.** For genuinely non-flat terrain the correct model is `p' ≈ H p + ρ·e'`, where `ρ` is the parallax proportional to height above the reference plane and `e'` the epipole. With a DEM, `ρ_i` is computable rather than free, so the residual height field can be corrected instead of absorbed into the error budget. **Out of scope for v1** — documented as the extension point, with `ElevationProvider` positioned so it is additive.

**Datum trap:** DEMs are usually **orthometric** (EGM96/EGM2008 geoid); GPS/EXIF altitudes are usually **ellipsoidal**. They differ by up to ±107 m globally. `vertical_datum` is carried explicitly on both the provider and the estimate; mixing them silently is a 30 m error that looks like nothing.

---

## 8. The hard problem: oblique ground photo vs nadir satellite

### 8.1 State it plainly

A homography is exact **iff** one of:
1. the scene is a **plane**, or
2. the camera motion is a **pure rotation** about the optical centre (no translation).

Neither holds in general between a surveyor standing in a field and a satellite 700 km up. Two independent difficulties:

**(a) Geometric.** Between an oblique ground view and a nadir view, the ground plane undergoes an extreme projective transform: local anisotropy (`σ₁/σ₂`) of 5–50×, and scale varying by orders of magnitude across the image (near foreground ~1 cm/px, distant ground ~1 m/px). SIFT is *similarity*-covariant only. Standard result: SIFT's repeatability collapses beyond roughly **40–50° of viewpoint change**; a ground↔nadir pair is effectively 60–90°. **This is why raw SIFT/SuperPoint matching largely fails, and no amount of tuning fixes it** — the descriptor is invariant to the wrong group.

**(b) Appearance.** A tree from the side is a green trunk-and-canopy silhouette; from above it is a green disc with a shadow. A ground photo sees vertical structure (fences, stalks, buildings' walls); nadir sees roofs and their shadows. Even a perfect geometric rectification leaves genuinely different *content*. Rectification addresses (a); it cannot fully address (b).

### 8.2 When the homography *is* valid — and why agriculture is the favourable case

1. **Near-nadir aerial/drone imagery** (tilt < ~20°): planar-ish and near-parallel. **This is the strong case and should be the primary supported workflow.** The product should say so.
2. **Flat farmland.** A ploughed field is planar to a few cm over hundreds of metres. Condition (1) holds *to the accuracy we care about*, and the flatness test (§7.7) makes that a measured claim rather than a hope.
3. **Distant ground plane.** For ground far from the camera relative to the baseline, the depth variation of the *ground* is small compared to its range; the ground-plane homography is a good local model even though vertical structures (trees, poles, buildings) violate it and become outliers. **This is fine and expected** — RANSAC's job is exactly to discard the off-plane minority. It also means: for GROUND_HORIZON regime, the *trees the user marked as landmarks are precisely the points the homography is least able to place*, since a tree's canopy is 5–15 m off the ground plane. A tree landmark's ground position is its **trunk base**, not its canopy centre — the UI must say so and `LandmarkType.TREE` must carry an elevated `sigma_px`.
4. **Pure rotation** (panoramas from a tripod): condition (2), rare here.

**Why agricultural fields are the favourable case — four independent reasons:**
- **Planarity.** Fields are engineered flat (for irrigation and machinery). The ground-plane assumption is nearly exact.
- **Texture.** Crop rows give a strong, oriented, *periodic* signal that survives viewpoint change as an *orientation and spacing* measurement even when individual features do not. This is our single most robust cross-view invariant.
- **Free calibration.** Crop rows are parallel lines on the ground ⇒ a vanishing point. Field borders are usually perpendicular to them ⇒ a second, orthogonal vanishing point. **Together they give the horizon *and* the focal length with no EXIF** (§9.2). Agriculture literally hands us the calibration.
- **Stable structure.** Field borders, canals, roads and tree lattices are temporally stable across the months or years separating the photo and the basemap — unlike the crop itself, which changes weekly. The scoring must lean on *structure* over *appearance* for exactly this reason (§10.5's weight on orientation and mask IoU over colour histograms).

**The honest counter-case:** crop rows are also *periodic and self-similar*, so they simultaneously provide the strongest global signal and the worst local ambiguity (§5.2). Hence: use rows for **orientation/spacing/rectification** (global, robust), and never rely on them for **local correspondence** (ambiguous). That split is a design rule, not an implementation detail.

### 8.3 View regimes

```python
class ViewRegime(StrEnum):
    NADIR                = "nadir"                 # tilt < 20°
    OBLIQUE_RECTIFIABLE  = "oblique_rectifiable"   # 20-70°, horizon recovered
    OBLIQUE_RAW          = "oblique_raw"           # 20-70°, no horizon
    GROUND_HORIZON       = "ground_horizon"        # tilt > 70° / horizon in frame
    UNKNOWN              = "unknown"
```

Regime is decided from: the horizon line's position (via §9.2), EXIF pitch when present, and the estimated tilt. It drives a **hard confidence ceiling** (§10.6). A `GROUND_HORIZON` photo of a distant field may still be matchable — but never at 90 confidence, because the assumptions the 90 would be built on are not in force.

### 8.4 Oblique → nadir rectification

**Method B (preferred, no user input): `AgriVanishingPointCalibrator`** — §9.2. Crop rows → VP1; field borders → VP2; horizon = `VP1 × VP2`; orthogonality → `f`.

**Method A (fallback): user-assisted horizon.** The UI lets the surveyor drag a horizon line — a 3-second action a human does far better than any algorithm. The horizon **is** the ground plane's vanishing line `l_h`. Given `K`, the ground normal in camera coordinates is
```
n_c = normalize(Kᵀ l_h)
```
(sign chosen so the plane is in front of and below the camera, `n_c·e₃ < 0`). Build the rotation `R_r` taking `n_c → −e₃` via axis-angle (`axis = normalize(n_c × (−e₃))`, `angle = arccos(−n_c·e₃)`), then
```
H_rect = K' R_r K⁻¹
```
with `K'` a fresh intrinsic chosen to fit the output canvas (focal + principal point + a fitted scale/translate over the warped ROI corners).

**What Method A/B can and cannot do — stated precisely:** the vanishing line determines the plane's **normal**, hence the **tilt and roll**, and nothing else. In-plane rotation and scale remain free. That is *fine*: after rectification the residual query↔nadir transform is a **similarity**, which is exactly the group plain SIFT is covariant to. Rectification converts an unsolvable problem into SIFT's home ground. This is the whole argument for it, and it is worth stating that it is not a heuristic improvement but a change of transformation group.

**Method C (fallback of last resort): `AffineSimulatedExtractor` (ASIFT).** No horizon needed. Simulate tilts `t ∈ {1, √2, 2, 2√2, 4}` and longitudes `φ ∈ {0, 72°/t, 144°/t, …}`, extract on each warp, map keypoints back with `FeatureSet.transform(T⁻¹)`, pool. Affine-covariant by simulation rather than by design. Costs ~8–15× a single extraction — which is why §5 applies it **only to landmark patches** by default (`asift.scope = "landmarks"`), and full-image ASIFT is opt-in (`asift.scope = "full"`) on a downscaled query.

**Policy (`config.rectification.strategy = "auto"`):**
```
if regime == NADIR:                       plain extraction, no rectification
elif VP.horizon is not None:              rectify (Method B), then plain SIFT
elif user_horizon is not None:            rectify (Method A), then plain SIFT
elif regime in {OBLIQUE_RAW}:             ASIFT on landmarks + downscaled full image
else (GROUND_HORIZON, no horizon):        ASIFT + confidence ceiling 35, status advisory
```

### 8.5 Honest confidence when the assumptions break

The engine must **refuse** to emit high confidence on a degenerate or out-of-regime solve. Enforced in three independent layers, so no single bug can leak a confident wrong answer:
1. **Hard degeneracy gate** → `gate = 0.0` → confidence `0` → `status = "rejected"` (§8.6).
2. **Regime ceiling** → `min(confidence, ceiling[regime])` (§10.6).
3. **Ambiguity clamp** → `margin < 1.05` ⇒ confidence ≤ 40, `status = "advisory"` (§5 step 32).

### 8.6 Degeneracy check list

```python
# geometry/degeneracy.py
class Severity(StrEnum):
    HARD = "hard"    # gate := 0.0, status := "rejected". No override, ever.
    SOFT = "soft"    # gate *= g in [0,1]

@dataclass(frozen=True, slots=True)
class DegeneracyCheck:
    name: str
    severity: Severity
    passed: bool
    value: float
    threshold: float
    gate: float             # [0,1]; HARD failure => 0.0
    message: str            # human-readable, surfaced in the UI

@dataclass(frozen=True, slots=True)
class DegeneracyReport:
    checks: tuple[DegeneracyCheck, ...]
    gate: float             # Π(soft gates), or exactly 0.0 if any HARD failed
    hard_failures: tuple[str, ...]
    regime: ViewRegime
    @property
    def is_degenerate(self) -> bool: return self.gate == 0.0

class DegeneracyValidator:
    def __init__(self, config: DegeneracyConfig) -> None: ...
    def validate(
        self, h: HomographyResult, c: Correspondences,
        landmarks: LandmarkSet, window: CandidateWindow, regime: ViewRegime,
    ) -> DegeneracyReport: ...
    def quick_check(self, H: np.ndarray) -> bool:
        """Cheap subset (det sign, cond, convexity) for hypothesis pre-screening."""
```

**HARD checks — any failure ⇒ confidence 0, `status="rejected"`:**

| # | Name | Condition | Why |
|---|---|---|---|
| H1 | `insufficient_inliers` | `num_inliers < 12` | 4 is the algebraic minimum; below ~12 the fit has no statistical strength and `Σ_H` is meaningless |
| H2 | `determinant_sign` | `det(H̃) ≤ 0` | Orientation flip — a mirrored ground plane is physically impossible for a camera above it |
| H3 | `quad_not_convex` | warped image quad non-convex or self-intersecting | Projectivities preserve convexity for points in front of the camera; failure ⇒ part of the quad is behind it |
| H4 | `vanishing_line_crosses_roi` | `d = h₃₁u + h₃₂v + h₃₃` changes sign, or `min\|d\|` over the ROI `< 1e-6·\|h₃₃\|` | **The subtlest and most important.** `d=0` is the vanishing line *in the query image*. If it crosses the region we are mapping, points there map to infinity: H is singular *inside the data*. Numerically it produces enormous, plausible-looking coordinates. A reprojection-error check cannot catch this — the inliers can all sit on the good side. |
| H5 | `collinear_inliers` | PCA on inlier `pts_a`: `λ₂/λ₁ < 0.01` | Collinear points do not constrain a homography; the solve is a 1-parameter family and RANSAC will return an arbitrary member |
| H6 | `inlier_hull_too_small` | `hull_area(inliers) < 0.05 · image_area` | H is unconstrained outside the inlier support; everything else is extrapolation |
| H7 | `reproj_error_too_high` | `reproj_error > 8.0 px` | Even with many inliers, this is not a fit |
| H8 | `extreme_anisotropy` | `σ₁/σ₂ > 20` for the local affine `J` at the inlier centroid | Beyond this the ground is compressed to a sliver; the cross-axis error is unusable |
| H9 | `scale_out_of_range` | `log₁₀(area_ratio) ∉ [−5.0, 2.5]` | Sanity bound on the query↔window scale ratio; outside it the "match" is not physical |
| H10 | `landmarks_out_of_bounds` | `> 50%` of landmarks warp outside the window + 10% margin | H is not mapping the marked scene into this window |
| H11 | `landmark_topology` | hull cyclic order of landmarks not preserved (§5, M7) | The user's marks are not in a projectively consistent configuration under H |
| H12 | `nan_or_inf` | any non-finite in `H`, `Σ_H` | Numerical failure |
| H13 | `placeholder_window` | window contains `is_placeholder` tiles over `>20%` of area | A blank tile matches everything; a "match" against it is meaningless |

**SOFT checks — multiply the gate:**

| # | Name | Gate | Rationale |
|---|---|---|---|
| S1 | `condition_number` | `clip((log₁₀κ_max − log₁₀κ(H̃)) / (log₁₀κ_max − log₁₀κ_ok), 0, 1)`, `κ_ok=1e4`, `κ_max=1e7` | On the **normalised** `H̃` (§6.3). Near-singularity |
| S2 | `inlier_spatial_entropy` | `sqrt(U)`, `U = H(p)/log 9` over a 3×3 grid of inlier counts | Clustered inliers ⇒ poor global constraint |
| S3 | `anisotropy_soft` | `clip((20 − σ₁/σ₂) / (20 − 4), 0, 1)` | Graded penalty below the H8 cliff |
| S4 | `hull_area_soft` | `clip((A_hull/A_img − 0.05)/(0.30 − 0.05), 0, 1)` | Graded above the H6 cliff |
| S5 | `many_to_one` | `1 − clip((frac_non_mutual − 0.2)/0.4, 0, 1)` | Periodic-texture pileup |
| S6 | `flatness` | `exp(−(flatness_rms_m/1.0)²)`, `1.0` if no DEM | Measured violation of planarity (§7.7) |
| S7 | `landmark_coverage` | `frac of landmarks in-bounds` | Partial mapping |
| S8 | `covariance_health` | `clip((log₁₀ tr_max − log₁₀ tr(Σ_H))/2, 0, 1)` | An enormous `Σ_H` means the fit is unconstrained even if it interpolates |

`gate = 0.0 if hard_failures else Π(soft gates)`, and `gate` multiplies the entire weighted sum (§10.1). Every check returns its `value` and `threshold` so the UI can explain *which assumption broke* — "rejected: the horizon line crosses your marked area" is actionable; "confidence: 12" is not.

---

## 9. Camera orientation (yaw / pitch / roll)

### 9.1 Intrinsics `K`, with a documented fallback chain

```python
@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    fx: float; fy: float; cx: float; cy: float
    skew: float = 0.0
    source: Literal["exif_focal_35mm", "exif_focal_sensor", "vanishing_points",
                    "fov_default", "user"] = "fov_default"
    sigma_f_rel: float = 0.25       # ★ RELATIVE 1σ on focal. Drives the pose error bars.
    def matrix(self) -> np.ndarray: ...   # (3,3) float64

def intrinsics_from_exif(exif: ExifBundle, size: tuple[int,int]) -> CameraIntrinsics | None: ...
def intrinsics_from_fov(size: tuple[int,int], hfov_deg: float = 60.0) -> CameraIntrinsics: ...
```

Precedence:
1. **EXIF `FocalLengthIn35mmFilm`** → `f_px = f₃₅ · W / 36.0`. `sigma_f_rel = 0.05`.
2. **EXIF `FocalLength` + sensor width** (from `FocalPlaneXResolution`/`FocalPlaneResolutionUnit`, or a maker/model lookup table) → `f_px = f_mm · W / sensor_w_mm`. `sigma_f_rel = 0.08`.
3. **Vanishing points** (§9.2), when an orthogonal VP pair exists. `sigma_f_rel ≈ 0.10–0.20`, from the VP scatter.
4. **Default FOV fallback:** `hfov = 60°` ⇒ `f_px = W / (2·tan(30°)) = 0.866·W`. `sigma_f_rel = 0.25`.

`cx, cy = W/2, H/2`; `fy = fx` (square pixels); `skew = 0`. Honour EXIF `Orientation` **before** anything else — a rotated-but-untransposed image silently invalidates every geometric assumption downstream and is a classic source of "the code is right but the answers are wrong".

The `60°` default is a genuine guess: it is roughly a smartphone main camera (~65–70°) and a mid-zoom compact, and it is wrong for ultrawide (~110°) and telephoto (~25°). `sigma_f_rel = 0.25` is not decoration — it propagates into an honest ±15° tilt bar (§9.5).

### 9.2 `AgriVanishingPointCalibrator` — the agricultural shortcut

```python
@dataclass(frozen=True, slots=True)
class VanishingPointResult:
    vp_rows: np.ndarray | None          # (3,) homogeneous, from crop rows
    vp_cross: np.ndarray | None         # (3,) from field borders ⟂ to rows
    horizon: np.ndarray | None          # (3,) l_h = vp_rows × vp_cross
    orthogonal_pair: bool
    focal_px: float | None              # from the orthogonality constraint
    f_sq: float                         # the raw f² solve; <= 0 => geometry inconsistent
    inlier_lines: np.ndarray            # (L,4)
    sigma_horizon_px: float
    confidence: float                   # [0,1]

class AgriVanishingPointCalibrator:
    def estimate(self, sem: SemanticMap, image: np.ndarray) -> VanishingPointResult: ...
```

1. Crop-row line segments (§11.2) → VP1 by RANSAC on line intersections (minimal sample = 2 lines; score = Σ of angular consistency; robust to the ~30% of segments that are not rows).
2. Field-border segments approximately perpendicular to the rows on the ground → VP2, same way.
3. `l_h = vp₁ × vp₂` (normalised).
4. **Focal from orthogonality.** With square pixels, zero skew, principal point at `(u₀,v₀)`, two orthogonal directions satisfy `v₁ᵀ ω v₂ = 0` with `ω = (KKᵀ)⁻¹`. Expanding gives the classical single-equation solve:
   ```
   f² = −[ (u₁−u₀)(u₂−u₀) + (v₁−v₀)(v₂−v₀) ]
   ```
   Valid **iff `f² > 0`**, i.e. the two VPs lie on opposite sides of the principal point in the relevant sense. If `f² ≤ 0` the assumed orthogonality (or the VP estimate) is wrong — **report `orthogonal_pair=False` and fall back; do not clamp `f²` to a positive number.** Clamping here fabricates a calibration out of an inconsistency and is exactly the kind of quiet lie this document exists to prevent.
5. Degenerate when a VP is near-infinite (rows parallel in the image ⇒ near-nadir ⇒ we do not need it anyway) or when the two VPs nearly coincide (rows and borders not actually perpendicular — common with contour ploughing and centre-pivot circular fields, which must be detected via the crop-row *curvature* residual and excluded).

This is the design's best idea: **the crop the surveyor is standing in calibrates the camera that photographed it.**

### 9.3 Pose: Zhang-plane (primary) — no 4-way ambiguity

The window is an **orthographic nadir view of the ground plane**, so window pixels convert *exactly* to metric ground coordinates in a local ENU tangent frame:
```
X_east  = (px_global − px_ref) · res(z, φ)
Y_north = (py_ref − py_global) · res(z, φ)
```
This is the key structural insight. Because the plane's **metric frame is known**, we are in Zhang's plane-calibration setting, which has a **unique** solution — the 4-way `decomposeHomographyMat` ambiguity **never arises**. Do not reach for `decomposeHomographyMat` first; it solves a harder problem than the one we have.

Let `P` = plane→image homography = `(H_img→ground)⁻¹`, columns `p₁,p₂,p₃`:
```
λ  = 1 / ||K⁻¹ p₁||
r₁ = λ · K⁻¹ p₁
r₂ = λ · K⁻¹ p₂
r₃ = r₁ × r₂
t  = λ · K⁻¹ p₃                          # camera position of the plane origin, metres
```
`[r₁ r₂ r₃]` is only approximately orthonormal (noise); project to `SO(3)`:
```
U, _, Vᵀ = svd([r₁ r₂ r₃]);   R = U · diag(1, 1, det(U Vᵀ)) · Vᵀ
```
The `diag(1,1,det)` guarantees `det R = +1` — a plain `R = UVᵀ` can yield a reflection and produce a mirrored, physically impossible pose that otherwise looks fine.

**Sign fix:** require `t_z > 0` (the plane in front of the camera). If `t_z < 0`, negate `λ` and recompute. Use `λ = 2/(||K⁻¹p₁|| + ||K⁻¹p₂||)` — averaging both columns is better conditioned than trusting `p₁` alone.

### 9.4 Angles — exact convention

World frame **ENU**: `X` = East, `Y` = North, `Z` = Up. Camera frame: `x` right, `y` **down**, `z` forward (OpenCV). `p_cam = R p_world + t`.

The optical axis in world coordinates is `c = R[2,:]` (third **row** of `R`, since `Rᵀe₃` = row 3). Then:

```
tilt_from_nadir  τ = arccos(−c_z)          τ=0 => straight down; τ=90° => horizontal
yaw (azimuth)    ψ = atan2(c_E, c_N)       clockwise from North, in [0,360)
```

Roll — the rotation about the optical axis, defined unambiguously by comparing image-up to world-up projected into the image plane:
```
u_ref  = normalize(Ẑ − (Ẑ·c)·c)           # world up, projected ⟂ to the optical axis
u_img  = −R[1,:]                           # image "up" in world (camera y points down)
roll φ = atan2( (u_ref × u_img)·c , u_ref·u_img )
```

**Gimbal lock is real and must be handled:** at exact nadir (`c ∥ Ẑ`), `u_ref` is undefined and yaw/roll degenerate into one angle. When `τ < 2°`, report `yaw = NaN`, set `roll` relative to North, and flag `pose.gimbal_locked = True`. Silently returning a number here produces a yaw that spins randomly with noise.

### 9.5 `decomposeHomographyMat` — the fallback, and disambiguation

Used only when the plane's metric frame is unavailable (e.g. an image↔image homography with no georeferenced side).

`cv2.decomposeHomographyMat(H, K)` → **4** `(R, t, n)` solutions. Disambiguate in order:

1. **Cheirality.** All inliers must have positive depth in both views. Typically eliminates 2. `cv2.filterHomographyDecompByVisibleRefpoints(rots, normals, pts_a, pts_b, mask)` implements exactly this — verified present.
2. **Plane normal prior.** The ground faces up: reject solutions whose `n`, rotated to world, has `n·Ẑ < 0`. Usually eliminates 1 more.
3. **EXIF priors.** `GPSImgDirection` (yaw), and Apple/Android maker-note gravity vectors when present, pick the remaining pair directly.
4. **Physical plausibility.** `τ ∈ [0°, 95°]` and camera height `∈ [0.5, 400] m`. A solution implying a 3 km-high handheld photo is not a solution.
5. **Residual tie.** Pick lower reprojection error; if still within noise, **report both**, set `pose.ambiguous = True`, and clamp `pose_confidence ≤ 50`. Two geometrically valid answers is a fact about the data, not a bug to be tie-broken away.

```python
@dataclass(frozen=True, slots=True)
class PoseResult:
    R: np.ndarray                      # (3,3) world(ENU) -> camera
    t: np.ndarray                      # (3,) camera position, metres, local ENU
    camera_lonlat: tuple[float, float]
    camera_height_m: float
    tilt_from_nadir_deg: float
    yaw_deg: float                     # clockwise from North; NaN if gimbal_locked
    roll_deg: float
    sigma_tilt_deg: float
    sigma_yaw_deg: float
    sigma_roll_deg: float
    sigma_height_m: float
    position_cov_m2: np.ndarray        # (2,2) camera ground position covariance
    intrinsics: CameraIntrinsics
    method: Literal["zhang_plane", "decompose_homography"]
    ambiguous: bool = False
    gimbal_locked: bool = False
    alternatives: tuple["PoseResult", ...] = ()

class PoseEstimator:
    def estimate(self, H: np.ndarray, K: CameraIntrinsics,
                 window: CandidateWindow, regime: ViewRegime) -> PoseResult: ...
```

### 9.6 Honest error bars

Propagate `Σ_H` (§6.4) **and** the focal uncertainty through the decomposition by the **unscented transform**: build `2·10+1 = 21` sigma points over the joint `(vec(H), f)` (9 + 1 dims), run each through the full Zhang pipeline, take the sample mean/covariance of `(τ, ψ, φ, height)`. Angles are averaged **circularly** (mean of unit vectors, then `atan2`) — a naive mean of yaws straddling 0°/360° returns 180°, which is not merely inaccurate but maximally wrong. The UT avoids differentiating an SVD analytically, which is where a Jacobian-based implementation would go wrong subtly.

**The key asymmetry, and it must be reported:**

```
δτ ≈ tan(τ) · (δf/f)          # tilt trades against focal, ~linearly
δψ ≈ weakly dependent on f     # yaw is azimuthal
δφ ≈ weakly dependent on f     # roll is in-plane
```

Focal error is **absorbed almost entirely by tilt and height**, because a longer lens looking more steeply down produces nearly the same image as a shorter lens looking less steeply. **Yaw and roll are well-determined even with a badly guessed focal length; tilt and height are not.** Typical honest bars:

| `K` source | `σ_f/f` | `σ_tilt` @ τ=45° | `σ_yaw` | `σ_roll` | `σ_height` |
|---|---|---|---|---|---|
| EXIF 35mm-equiv | 0.05 | ±3° | ±2° | ±1.5° | ±6% |
| EXIF focal+sensor | 0.08 | ±5° | ±2.5° | ±2° | ±9% |
| Vanishing points | 0.15 | ±9° | ±3° | ±2.5° | ±16% |
| **FOV default (60°)** | **0.25** | **±15°** | **±5°** | **±3°** | **±27%** |

The UI must render a `±15°` tilt as a **cone**, not a number. And the product implication is concrete and worth surfacing to the user: **camera *height* and *tilt* from a no-EXIF photo are barely more than an order-of-magnitude estimate, while the *bearing* is genuinely useful.** Presenting all three with equal visual authority would misrepresent the mathematics.

---

## 10. The matching score

### 10.1 The formula

```
                 ⎛  w_f·S_f + w_g·S_g + w_l·S_l + w_s·S_s  ⎞
  raw    =  D ·  ⎜  ─────────────────────────────────────  ⎟
                 ⎝           w_f + w_g + w_l + w_s          ⎠

  Confidence = min( 100 · calib(raw),  ceiling(regime),  ambiguity_clamp )
```

- `D ∈ {0} ∪ (0,1]` — the degeneracy gate (§8.6). `D = 0` ⇒ **`Confidence = 0`, `status="rejected"`**.
- Each `S_• ∈ [0,1]`.
- If a term is unavailable (`S_s = None` when semantics are off), it is **dropped from both numerator and denominator** — hence the explicit renormalisation. Substituting a neutral 0.5 would inject fake evidence; substituting 0 would penalise a configuration choice as if it were evidence of a bad match. Both are common and both are wrong.

**Weights** (`scoring/composite.py`, config-overridable):

| Term | Weight | Rationale |
|---|---|---|
| `w_g` geometric | **0.35** | Highest: geometric consistency is the hardest to fake. Random matches do not produce a consistent H. |
| `w_l` landmark | **0.30** | The human-supplied prior — the product's differentiator, and independent evidence from the texture channel |
| `w_f` feature | **0.25** | Necessary but the most spoofable: periodic crop texture yields many high-quality matches to the *wrong* field |
| `w_s` semantic | **0.10** | Coarse; a tie-breaker. Low weight because the classical fallback is genuinely noisy |

Rationale for the ordering: `S_f` is the term a self-similar field can most easily satisfy by accident, so it must not dominate. `S_g` and `S_l` are the terms that a *wrong* field fails.

### 10.2 `S_f` — feature similarity

```
S_f = ( n_in² / (n_in² + n₀²) ) · q̄            n₀ = 30
q̄   = mean over inliers of MatchSet.scores (normalised per §3.2)
```
The soft saturation `n²/(n²+n₀²)` is preferred to a hard cap: it is smooth (so calibration behaves), ≈0.5 at `n_in = 30`, ≈0.9 at `n_in = 90`, and it never *fully* saturates, so 300 inliers still beats 100. `S_f ∈ [0,1]`.

### 10.3 `S_g` — geometric consistency

```
S_g = sqrt(ρ_in) · exp(−(ε_rms/ε₀)²) · sqrt(U)          ε₀ = 3.0 px

ρ_in = n_in / n_matches                  inlier ratio ∈ [0,1]
ε_rms = HomographyResult.reproj_error    symmetric transfer RMS over inliers, px
U     = H(p)/log 9                       normalised entropy of inlier counts over a 3×3 grid
```
`sqrt(ρ_in)` rather than `ρ_in`: a 10% inlier ratio on a hard wide-baseline pair is a *good* result, and a linear term would crush it to near-zero. `U` is the spatial-spread term: it distinguishes 100 inliers spread across the frame (`U ≈ 1`) from 100 inliers in one corner (`U ≈ 0.3`) — the same `n_in` and `ε_rms`, radically different trustworthiness of the extrapolated H.

### 10.4 `S_l` — landmark consistency

Per landmark `k`, from `LandmarkEvidence`:
```
support_k  = n_k / (n_k + k₀)                          k₀ = 5   # local inlier density
patch_k    = max(0, zncc_k)                                     # appearance verification
transfer_k = exp(−(r_k/ε_L)²) if direct_fix else NULL   ε_L = 5 px
sem_k      = semantic_agree_k                                   # type vs predicted class

           ⎧ 0.30·support + 0.25·patch + 0.30·transfer + 0.15·sem   if direct_fix
score_k =  ⎨
           ⎩ 0.45·support + 0.35·patch + 0.20·sem                   otherwise
score_k *= 1 if in_bounds_k else 0

S_l = Σ_k (w_k · score_k) / Σ_k w_k                     w_k = Landmark.user_weight
```
`transfer_k` is the strongest sub-term when available: it is an **independent** check — a landmark located by its own patch bank, *without* reference to the global H, agreeing with where the global H puts it. Two independent estimators agreeing is worth far more than either alone, which is why the weights redistribute rather than the term simply vanishing.

`S_l ∈ [0,1]`. If `LandmarkSet` is empty, `S_l = None` and drops out of the renormalisation (the system still works with zero landmarks — it just loses its best signal).

### 10.5 `S_s` — semantic similarity

```
S_s = 0.40·s_hist + 0.30·s_orient + 0.30·s_mask
```
```
s_hist   = 1 − JSD(p_q, p_w)/ln 2
             JSD in nats over the SemanticClass histogram; normalised, ∈[0,1].
             JSD (not KL): symmetric, bounded, and finite on disjoint support — KL
             returns ∞ the moment a class is present in one image and absent in the other,
             which is routine.

s_orient = (1 + cos(2·Δθ)) / 2
             Δθ = θ_rows^q_warped − θ_rows^w, where θ_rows^q is pushed through H's local
             rotation at the inlier centroid. The 2Δθ folds the 180° ambiguity: crop rows
             are undirected lines — 10° and 190° are the SAME orientation.
             ∈[0,1]. Weighted 0 if either coherence < 0.3.

s_mask   = mean over classes present in BOTH of IoU(warp(M_q^c, H), M_w^c)
             ∈[0,1]. Classes present in only one contribute nothing rather than 0 —
             a greenhouse cropped out of frame is not evidence of a mismatch.
```
The weighting deliberately favours **structure** (`s_orient`, `s_mask`) over **appearance** (`s_hist`): the photo and the basemap may be months or years apart, so the crop's colour is nearly uninformative while the row *orientation* and the field *shape* persist (§8.2).

### 10.6 Regime ceilings

```python
CEILING: Mapping[ViewRegime, float] = {
    ViewRegime.NADIR:               100.0,
    ViewRegime.OBLIQUE_RECTIFIABLE:  85.0,
    ViewRegime.OBLIQUE_RAW:          60.0,
    ViewRegime.GROUND_HORIZON:       35.0,   # status forced to "advisory"
    ViewRegime.UNKNOWN:              50.0,
}
```
These are **not** tuning knobs — they encode how far the planar assumption is from being in force. A `GROUND_HORIZON` match can be *useful* (an advisory location), but it can never be *survey-grade*, and the number must say so. `status`:
- `rejected` — `D = 0`, or `confidence < config.min_confidence` (default 25)
- `advisory` — `GROUND_HORIZON`, or ambiguity clamp, or `flatness_rms > 0.5 m`
- `accepted` — otherwise

### 10.7 Calibration

Raw `confidence` is a *score*, not a probability. Target semantics: **`Confidence/100 ≈ P(absolute geo error < τ)` with `τ = 5 m`** (config: `calibration.tau_m`).

- **Method:** Platt scaling (`σ(a·logit(raw) + b)`) as default — 2 parameters, works with the few hundred labelled examples realistically obtainable. Isotonic regression once `n > 2000` (it is non-parametric and needs the data to not overfit).
- **Ground truth:** (a) `SyntheticTileProvider` pairs with an exactly known `H` and known geo answer — available at CI time, unlimited, free, and the only source available *today*; (b) real surveyed GCPs supplied by the client; (c) held-out drone orthophotos with known EXIF GPS.
- **`ScoreResult.feature_vector` is persisted on every job.** This is deliberate: it means calibration can be re-fit offline from production data **without re-running a single CV operation**. Without it, every recalibration is a full re-processing of the archive. `feature_names()` must stay stable across versions or the stored vectors become unreadable.
- **Default `calibration/default-v1.json` is the identity**, `calibrated=False`, `calibration_id="identity"`. Shipping a fabricated calibration curve would be worse than shipping none: an uncalibrated score honestly labelled is a score; a made-up curve is a lie with a probability attached. The UI must render uncalibrated confidence as a **relative ranking**, not a probability.
- Report reliability diagrams + ECE per calibration release.
- **Per-landmark confidence** (§5 step 36): `conf_k = confidence · clip(score_k / max(S_l, ε), 0.5, 1.0)` — landmarks the solve supports poorly get less confidence than the job as a whole, even within an accepted match.

---

## 11. Agricultural semantics

**The classical path is the DEFAULT and the terminal fallback.** `ClassicalSemantics` requires no weights, no GPU, no network, and runs in ~15–40 ms on a 1024² window. `SamSegmenter`/`Dinov2Semantics` are opt-in accelerators — and on the verified CPU-only dev box, SAM on a 1024² image is ~2–8 s, which is **100–200× slower** than the classical path and non-viable at the tile-scanning scale regardless of quality.

```python
class SemanticClass(StrEnum):
    UNKNOWN = "unknown"; FIELD = "field"; FIELD_BORDER = "field_border"
    CROP_ROWS = "crop_rows"; ROAD = "road"; TRACK = "track"; CANAL = "canal"
    WATER = "water"; TREE = "tree"; TREE_LATTICE = "tree_lattice"
    GREENHOUSE = "greenhouse"; BUILDING = "building"; BARE_SOIL = "bare_soil"
    SHADOW = "shadow"; SKY = "sky"

@dataclass(frozen=True, slots=True)
class CropRowField:
    theta_rad: float          # dominant orientation, folded to [0, π) — rows are UNDIRECTED
    spacing_px: float
    strength: float           # [0,1] FFT peak power / annulus median
    coherence: float          # [0,1] structure-tensor coherence
    curvature: float          # [0,1] 0=straight, >0.3 => contour/pivot ploughing -> no VP
    orientation_map: np.ndarray | None   # (H,W) float32 rad, per-pixel

@dataclass(frozen=True, slots=True)
class TreeLattice:
    theta1_rad: float; theta2_rad: float
    spacing1_px: float; spacing2_px: float
    nodes: np.ndarray          # (N,2) float32 — orchard tree positions = EXCELLENT landmarks
    strength: float

@dataclass(frozen=True, slots=True)
class SemanticMap:
    masks: Mapping[SemanticClass, np.ndarray]     # bool (H,W); stored np.packbits in cache
    histogram: np.ndarray                          # (C,) float32, area fractions, sums to 1
    crop_rows: CropRowField | None
    lattice: TreeLattice | None
    lines: np.ndarray                              # (L,4) float32 x1,y1,x2,y2
    ridges: RidgeSet | None
    provenance: Mapping[SemanticClass, str]        # class -> "classical"|"sam"|"dinov2"
    image_size: tuple[int, int]
    version: str
    def regions_of(self, classes: Collection[SemanticClass]) -> np.ndarray: ...
    def class_at(self, xy: np.ndarray) -> np.ndarray: ...   # (N,2) -> (N,) SemanticClass

# semantics/base.py
class SemanticSegmenter(ABC):
    name: ClassVar[str]
    version: ClassVar[str]
    @abstractmethod
    def segment(self, image: np.ndarray, *, bands: Mapping[str, np.ndarray] | None = None) -> SemanticMap:
        """`bands` carries extra spectral bands (NIR, SWIR) when the provider has them
        (ProviderCapabilities.supports_multispectral). RGB-only => heuristics (§11.4)."""
    def capabilities(self) -> SemanticCapabilities: ...
```

### 11.1 Vegetation indices (`semantics/indices.py`)

```
ExG  = 2·g − r − b,          r,g,b = R/(R+G+B) etc.  (chromatic coordinates)
                             ∈[−2,2]; scale to [0,1]. THE workhorse — illumination-robust
                             because the chromatic normalisation divides out intensity.
GLI  = (2G − R − B) / (2G + R + B)
NDWI = (G − NIR) / (G + NIR)            # true water index; needs NIR
MNDWI= (G − SWIR) / (G + SWIR)          # better with built-up; needs SWIR
NDVI = (NIR − R) / (NIR + R)            # only with NIR
```

### 11.2 Crop rows — **default: classical**

Three estimators, fused:

1. **Structure tensor (per-pixel orientation).** `J = G_σ ∗ (∇V ∇Vᵀ)` on `V = ExG`, `σ = 4 px`:
   ```
   θ(x) = 0.5·atan2(2·J_xy, J_xx − J_yy) + π/2        # +π/2: rows run ⟂ to the gradient
   coherence = sqrt((J_xx − J_yy)² + 4·J_xy²) / (J_xx + J_yy + ε)   ∈[0,1]
   ```
   Gives a **dense** orientation map. Global `θ` = coherence-weighted **circular** mean of `2θ` (double-angle handles the 180° ambiguity — the *only* correct way to average undirected line orientations), then halve.
2. **FFT (spacing + confirmation).** 2D FFT of the Hann-windowed `ExG`; the dominant off-DC peak at `(f, θ_f)` gives `spacing = N/|f|` and `θ_f ⟂ θ_rows`. `strength = peak / median(annulus)`. The Hann window is mandatory — without it, spectral leakage from the image edges produces a cross-shaped artifact that reads as a strong axis-aligned "row" signal in *every* image.
3. **Hough (line segments for VPs).** Canny on `ExG` with auto thresholds from the median (`lo = 0.66·med`, `hi = 1.33·med`), then `cv2.HoughLinesP(rho=1, theta=π/360, threshold=80, minLineLength=W/12, maxLineGap=W/60)`. Fold angles to `[0,π)`; keep segments within ±15° of the structure-tensor `θ`. **These segments feed the VP calibrator (§9.2).** `cv2.createLineSegmentDetector` is verified present and gives better segments — use it behind a `hasattr` guard, since it is build-dependent and has been absent from some OpenCV releases.

**Curvature check:** fit the row segments to a pencil of lines; if the intersection scatter exceeds `0.3·image_diagonal`, the rows are **curved** (contour ploughing / centre-pivot irrigation) ⇒ `curvature > 0.3` ⇒ **no vanishing point** ⇒ `AgriVanishingPointCalibrator` must decline. Circular pivot fields would otherwise produce a confident, meaningless VP — the resulting horizon would be pure fiction and every downstream angle would inherit it.

### 11.3 Field borders — **default: classical**

`ExG` → bilateral filter (`d=9, σ_color=75, σ_space=75`; preserves the border while killing crop texture) → Canny (auto thresholds) → morphological close (5×5 ellipse) → `cv2.findContours(RETR_LIST, CHAIN_APPROX_SIMPLE)` → filter `area > 0.005·img_area` → `cv2.approxPolyDP(ε = 0.01·perimeter)` → keep 3–12 vertices. Vertices are **`FIELD_CORNER` candidates** and therefore structural landmark fixes (§5, step 16). Border segments ⟂ to the crop rows feed VP2 (§9.2).

### 11.4 Water — **default: classical, with an honest caveat**

- **Multispectral** (`supports_multispectral`, e.g. Sentinel-2): `NDWI > 0.2` (or `MNDWI` with SWIR). Reliable.
- **RGB-only** (Mapbox/Bing/Esri): a 3-term **AND**, never a single test:
  ```
  1. Hue ∈ [90, 130] in OpenCV units (H is 0-179 = degrees/2, so this is 180°-260°: cyan→blue)
     AND S > 40 AND V < 200
  2. Low texture:  std(Laplacian) over a 9×9 window < θ_tex   # water is SMOOTH
  3. Low vegetation: ExG < 0.35
  ```
  then connected components with `area > 0.002·img_area`.
  **Honest caveat, and it is a serious one:** the dominant false positives are **dark soil, shadow, and asphalt**, all of which pass the hue test under an overcast sky. The **low-texture term is what carries this test** — the hue term alone is near-worthless on RGB basemaps. Where the provider has NIR, use NDWI and do not use this at all. `provenance[WATER] = "classical_rgb_heuristic"` so downstream consumers (and the UI) know the mask is weak; `S_s` weights water mask IoU accordingly.

### 11.5 Roads and canals — **default: classical (Hessian ridges)**

Both are elongated ribbons ⇒ multi-scale **vesselness** (Frangi/Sato), implementable with `scipy.ndimage` alone (no skimage dependency). For `σ ∈ {2, 4, 8}` px, compute the Hessian by Gaussian derivatives, take eigenvalues `|λ₁| ≤ |λ₂|`:
```
R_b = |λ₁| / |λ₂|                       blobness
S   = sqrt(λ₁² + λ₂²)                   structureness
V(σ) = exp(−R_b²/(2β²)) · (1 − exp(−S²/(2c²))),   β = 0.5, c = 0.5·max(S)
V    = max over σ,  scale-normalised by σ²
```
- `λ₂ < 0` ⇒ **bright** ridge → road / dry track.
- `λ₂ > 0` ⇒ **dark** ridge → canal / shadowed ditch.

Disambiguate road vs canal by running the §11.4 water test **inside** the ribbon. Ridge **junctions** (skeletonise the thresholded ridge mask, find pixels with ≥3 neighbours) are `CANAL_JUNCTION` / `ROAD_JUNCTION` structural fixes — and they are **outstanding landmarks**: high-curvature, temporally stable for years, and unambiguous from both viewpoints. Exactly the structure §8.2 argues to lean on.

### 11.6 Trees and orchards — **default: classical**

Multi-scale LoG blobs on `ExG` (`scipy.ndimage.gaussian_laplace`, `σ ∈ {3,…,12}`), scale-normalised by `σ²`, local maxima + NMS (IoU 0.3), then a texture gate (local variance above the field median — a tree canopy is rougher than a crop). **Orchards:** the FFT of the tree-centre point set shows **two** peaks ⇒ a lattice ⇒ emit `TreeLattice` with the node grid. **Orchard lattice nodes are the single best agricultural landmark available**: precisely localisable, dense, geometrically rigid, and *visible from both viewpoints* — a nadir view sees the canopy discs, a ground view sees the trunks in rows. (Register the *trunk base*, not the canopy centroid — see §8.2 point 3.)

### 11.7 Greenhouses and buildings — **default: classical**

Greenhouse: `S` low **and** `V` high (specular plastic/glass) + a rectangular contour with high fill (`contour_area / minAreaRect_area > 0.85`) + area above a config threshold in **m²** (converted via `res(z,φ)`, not px — the same structure must be found at every zoom).
Building: rectangular, high fill, low `ExG`, plus adjacent shadow (a dark region offset consistently across the image — the offset direction is itself estimable as the modal shadow azimuth over all buildings, which then *validates* the individual detections).

### 11.8 Deep path (opt-in)

- **SAM** (`sam.py`): `SamAutomaticMaskGenerator` → class-agnostic masks → classify each by the *same* classical features (ExG, hue, fill, elongation, ridge response). SAM contributes **boundaries**, not labels — that is what it is good at, and it means the class taxonomy stays under our control and identical across both paths.
- **DINOv2** (`dinov2_seg.py`): patch tokens → a small linear probe over `SemanticClass`, or k-NN against a small prototype bank. Also supplies dense descriptors for `Dinov2DenseExtractor`.
- Both **must** produce the identical `SemanticMap` schema with `provenance` marked, so `S_s` is computed identically regardless of path — a config change must never change the *meaning* of the score.

---

## 12. Performance

### 12.1 Tile budget

| Knob | Default | Note |
|---|---|---|
| `max_tile_fetches` | 512 | hard ceiling per job; provider ToS + latency |
| `beam_width` | 32 | quadtree beam survivors per level |
| `z_coarse → z_fine` | 15 → 19 | 4 levels |
| `windows_screened` (A) | 96 | cheap global screen |
| `windows_matched` (B) | 24 | SIFT + FLANN + MAGSAC |
| `windows_full` (C) | 8 | guided rematch + landmarks + pose |
| `deep.max_candidates` | **8** | **enforced in code**, stage C only |
| `window_px` | 1024 | 4×4 tiles @ S=256 |
| `window_overlap` | 0.5 | any 512px footprint lies wholly inside ≥1 window |

`QuadtreeBeamSearch`: score all tiles at `z=15` with the cheap screen → keep top 32 → expand each into 4 children at `z=16` → rescore → … → at `z_fine` build windows from the survivors. Cost is `O(beam · 4 · levels)` = ~512 tiles, not `O(4^z)`.

**Cheap global screen (stage A), ~1–2 ms/window:** 32-bin ExG histogram + crop-row `(θ, spacing, coherence)` + a 16-bin hue histogram + the semantic histogram → a 64-D vector; cosine similarity against the query's, with `θ` compared through the double-angle trick. **This is where the crop-row orientation earns its keep**: a field whose rows run 40° off the query's is almost certainly the wrong field, and rejecting it costs microseconds instead of the 150 ms a SIFT pass would.

### 12.2 GPU vs CPU — the governing constraint

**Verified: `torch.cuda.is_available() == False` on this machine**, on a `torch 2.11+cu130` wheel. The CUDA build is present; the runtime/driver is not. Consequences, and they are not negotiable:

- `select_device()` returns `cpu`. **Any component whose spec declares `device_preference=CUDA` falls back** through the registry (§14), exactly as a missing weight file does. Device unavailability and weight absence are the *same failure class* and share one policy.
- CPU timings for the deep path on a 1024² pair: LoFTR ~2–5 s, SuperPoint ~0.3–0.8 s, SuperGlue ~0.5–1.5 s, SAM ~2–8 s.
- Therefore `deep.max_candidates = 8` is a **hard, code-enforced cap**, asserted in the orchestrator. LoFTR × 96 windows on CPU = **~5 minutes**, past the Celery soft limit, for a rerank that a 64-D cosine screen does in 0.2 s. The architecture must make the wrong choice *impossible*, not merely discouraged.
- With a real GPU, raise `deep.max_candidates` to ~32 and enable `EnsembleSource(['asift','loftr'])` at stage B. Config change only — no code change. That is the payoff for the seam.

### 12.3 Caching — three tiers

| Tier | Key | Store | TTL |
|---|---|---|---|
| Tile bytes | `sha256(provider|layer|z|x|y)` | Redis + disk | per provider ToS |
| **`FeatureSet` per tile** | `sha256(tile_key|extractor_name|extractor_version|params_hash)` | disk `.npz` | 30 d |
| `SemanticMap` per tile | `sha256(tile_key|segmenter_name|version)` | disk, masks `np.packbits` | 30 d |
| Query `FeatureSet` | `sha256(image_sha256|extractor|params_hash)` | disk | job TTL |

**Tier 2 is the big win.** Satellite descriptors are *static*: the imagery does not change between jobs. A second job anywhere in the same AOI **skips step 4 entirely** — typically 60–70% of the CPU. Cache hit rates on a real deployment (surveyors work the same regions repeatedly) should exceed 80% after warm-up. `extractor_version` in the key is what makes invalidation automatic rather than a manual purge — bump the version, the old entries are simply never read again.

`np.packbits` on the semantic masks is an 8× reduction and matters: 15 bool masks at 1024² is 15 MB/window uncached, 1.9 MB packed.

```python
@runtime_checkable
class CacheBackend(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, *, ttl_s: int | None = None) -> None: ...
    def get_or_compute(self, key: str, fn: Callable[[], T], *,
                       codec: Codec[T], ttl_s: int | None = None) -> T: ...
class NullCache:  """DEFAULT in tests. Correctness must never depend on the cache."""
```

### 12.4 Parallelism

| ID | Where | Mechanism | Degree |
|---|---|---|---|
| P1 | Tile fetch | provider-internal (async behind the sync facade) | 16 |
| P2 | Stage A screen | vectorised numpy over the stacked window batch | — |
| P3 | Stage B per window | `ProcessPoolExecutor` | `min(8, cpu−1)` |
| P4 | Stage C per window | `ProcessPoolExecutor` | `min(4, cpu−1)` |
| P5 | ASIFT tilt sims | `ProcessPoolExecutor` (only when `scope="full"`) | 4 |
| P6 | Landmark patch verify | vectorised; **no pool** (K ≈ 4–12; pool overhead dominates) | — |

**`cv2.setNumThreads(1)` in every worker process** (`runtime/parallel.py` sets it in the pool initialiser). OpenCV defaults to one thread per core; combined with an 8-way process pool that is 64 threads on 8 cores. The measured effect of *not* doing this is a **1.5–3× slowdown** from context-switch thrash, plus wildly nondeterministic timings that make profiling useless. Same for `p.isParallel = False` on `UsacParams` (§6.2), and `OMP_NUM_THREADS=1` / `torch.set_num_threads(1)` in the workers.

**Barriers:** the quadtree beam-search levels are sequential (level `n+1` needs level `n`'s survivors); stages A→B→C are sequential (each selects the next's input). Everything within a stage is embarrassingly parallel.

### 12.5 Expected timings (CPU-only, 8 cores, 1024² windows, classical path)

| Stage | Op | Per unit | Count | Wall (8-way) |
|---|---|---|---|---|
| A | query SIFT + semantics + VP | 250 ms | 1 | 0.25 s |
| A | landmark ASIFT patch bank | 20 ms | 8 | 0.16 s |
| — | tile fetch (cold) | 60 ms | 512 | 2.0 s |
| — | tile fetch (warm) | 1 ms | 512 | 0.05 s |
| A | cheap screen | 1.5 ms | 96 | 0.02 s |
| B | window SIFT (cold) | 110 ms | 24 | 0.33 s |
| B | window SIFT (**cached**) | 4 ms | 24 | **0.01 s** |
| B | FLANN + PROSAC | 45 ms | 24 | 0.14 s |
| C | guided rematch + MAGSAC + refine | 180 ms | 8 | 0.18 s |
| C | landmark verify + semantics cmp | 60 ms | 8 | 0.06 s |
| D | rank + pose + heatmap | 90 ms | 1 | 0.09 s |
| | **Total (cold)** | | | **~3.2 s** |
| | **Total (warm cache)** | | | **~1.0 s** |

Deep path on this CPU box, stage C only, 8 windows: **+16–40 s** — a 5–12× slowdown for a rerank of 8 candidates. **On the verified hardware, the classical path is not merely the fallback: it is the faster and the recommended configuration.** Celery limits: soft 120 s, hard 180 s.

### 12.6 Celery shape

```
chain(
  group(fetch_tiles.s(chunk) for chunk in chunks),      # P1
  screen_windows.s(),                                   # stage A
  chord([score_window.s(w) for w in top24],             # stages B+C, P3/P4
        rank_and_finalize.s()),                         # stage D
)
```
One `MatchJob` = one chain. `ai_engine` exposes only `run_match_job(ctx) -> MatchJobResult` plus the per-step pure functions; the Celery task module (another agent's file) wires them. **No Celery import exists anywhere under `ai_engine/`** — that is what makes every step unit-testable by direct call.

---

## 13. The confidence heatmap over candidate camera locations

**Not** a heatmap of tile scores. Each window's pose solve (§9) yields an actual **camera ground position** — so the heatmap is a genuine posterior over *where the photographer stood*, which is both more useful and more honest than colouring in tiles.

```python
@dataclass(frozen=True, slots=True)
class HeatmapComponent:
    mu_lonlat: tuple[float, float]     # camera position from THIS window's pose solve
    cov_m2: np.ndarray                 # (2,2) metres², from §9.6 unscented propagation
    weight: float                      # π_w, softmax over confidence
    window_id: str
    confidence: float

@dataclass(frozen=True, slots=True)
class ConfidenceHeatmap:
    grid: np.ndarray                   # (N,N) float32, normalised to sum 1 (a DENSITY)
    bounds_4326: BBox
    grid_size: int                     # 256
    cell_size_m: float
    components: tuple[HeatmapComponent, ...]
    background_weight: float           # ★ P(none of these) — the "not here" mass
    entropy_norm: float                # H(p)/log(N²) ∈[0,1] — localisation ambiguity
    credible_regions: tuple[CredibleRegion, ...]   # 50 / 80 / 95% HDR
    def to_png(self, colormap: str = "viridis") -> bytes: ...   # Leaflet ImageOverlay
    def to_geojson(self) -> dict: ...                            # HDR contours

@dataclass(frozen=True, slots=True)
class CredibleRegion:
    level: float                       # 0.50 / 0.80 / 0.95
    polygons: list[list[tuple[float,float]]]   # lon/lat rings
    area_m2: float

class CameraPosterior:
    @staticmethod
    def build(results: Sequence[WindowResult], bbox: BBox, *,
              grid: int = 256, temperature: float = 8.0,
              min_confidence: float = 20.0) -> ConfidenceHeatmap: ...
```

**Construction:**
1. Keep windows with `status != "rejected"` and `confidence ≥ 20`, each contributing `μ_w` (camera lon/lat) and `Σ_w` (position covariance) from its pose solve.
2. **Mixture weights** by softmax over confidence: `π_w ∝ exp(c_w / T)`, `T = 8`. `T` controls peakiness: `T→0` collapses to a winner-take-all point mass (overconfident); `T→∞` flattens to uniform (useless). `T = 8` on a 0–100 scale means a 16-point confidence lead gives ~7× the weight — decisive but not absolute.
3. **Background term — mandatory.** `π_bg = 1 − max_w(c_w)/100`, spread **uniformly over the AOI**. This is the "the true location is none of these" mass. Without it the posterior always sums to 1 over the candidates and therefore *always* claims the camera is in one of them — even when the best candidate scored 22. A posterior that cannot express "I don't know" is not a posterior.
4. **Rasterise** onto an `N×N` grid over `bbox` (an equal-area local ENU grid, not raw lon/lat — a lon/lat grid has cells that shrink with `cos φ`, so a density on it is biased poleward):
   ```
   p(x) = π_bg / A_aoi + Σ_w π_w · N(x; μ_w, Σ_w)
   ```
   evaluate at cell centres, multiply by cell area, normalise to sum 1.
5. **Credible regions by HDR** (highest-density region), *not* by iso-value on the raw density: sort cells descending, cumulative-sum, threshold at 0.50/0.80/0.95, take the mask, `cv2.findContours`, `approxPolyDP(ε = 0.5·cell)`, convert grid→lon/lat. **HDR is the correct construction**: it yields the *smallest* region containing the stated probability mass, and unlike an iso-contour it correctly produces **disconnected** regions when the posterior is multimodal — which is exactly the situation the surveyor most needs to see ("it's one of these two fields").
6. **`entropy_norm = H(p)/log(N²)`.** A scalar ambiguity summary. `> 0.6` ⇒ the posterior is diffuse ⇒ we have not localised, regardless of the best window's confidence. Surfaced as a distinct flag, because "the best candidate scored 78" and "the posterior is a smear over 4 km²" can both be true — and reporting only the first would be exactly the kind of confident-but-wrong output §0 forbids.

**Representation to the frontend:** a PNG + `bounds_4326` for a Leaflet `ImageOverlay` (cheap, smooth), **plus** GeoJSON HDR contours for the 50/80/95 rings (crisp, clickable, exportable). The rings are the honest artifact — a smooth heatmap invites the eye to read a peak that may not be significant; a labelled "95% region: 2.3 km²" cannot be misread.

---

## 14. The registry / factory

**One config string → one class, and one place where fallback policy lives.**

```python
# registry/spec.py
class ComponentKind(StrEnum):
    EXTRACTOR = "extractor"; MATCHER = "matcher"; DETECTOR_FREE = "detector_free"
    SEGMENTER = "segmenter"; ESTIMATOR = "estimator"; SCORER = "scorer"

@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    kind: ComponentKind
    factory: Callable[[Mapping[str, Any]], Any]
    requires_weights: tuple[str, ...] = ()       # WeightManifest keys, NOT paths
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
    def to_dict(self) -> dict: ...               # -> GET /api/v1/health/models
```

```python
# registry/policy.py   ★ THE ONLY PLACE FALLBACK POLICY EXISTS
def resolve_with_fallback(
    registry: "Registry", name: str, kind: ComponentKind,
    config: Mapping[str, Any], *, strict: bool = False, chain_limit: int = 4,
) -> Resolution:
    """
    Walk name -> spec.fallback -> ... until something constructs.

    For each candidate, IN ORDER (cheapest and least side-effecting first):
      1. spec exists in the registry for (name, kind)                -> else next
      2. every requires_packages importable via importlib.util.find_spec()
         (★ find_spec, NOT import: no module side effects, no CUDA init,
            no 2-second torch import just to discover we won't use it)   -> else next
      3. every requires_weights resolvable AND sha256 matches the
         WeightManifest (a corrupt/truncated download is treated exactly
         like a missing one — a half-downloaded .pth that imports and then
         produces garbage is far worse than one that is simply absent)   -> else next
      4. device_preference satisfiable (CUDA requested but
         torch.cuda.is_available() False -> either accept CPU if the spec
         allows, or fall through). ★ Device unavailability is the SAME
         failure class as missing weights. On the verified dev box this is
         the branch that actually fires.                                 -> else next
      5. spec.factory(config) inside try/except Exception               -> else next

    Every fall-through emits a structured ComponentFallback event
    (requested, candidate, reason, exc_type) at WARNING. Never silent:
    a user MUST be able to discover that they configured SuperPoint and got SIFT.

    Cycle detection via a visited set; chain_limit caps depth.
    Terminal specs (fallback=None) MUST have no requires_weights and no
    requires_packages beyond the base install, so the chain is PROVABLY
    terminating at something that always constructs. Asserted at registration.

    strict=True (config.strict_models): raise ComponentUnavailable instead of
    falling back. For CI on a GPU box where a silent degradation would mean
    the deep path is untested while the suite goes green.

    Exhausted chain -> ComponentUnavailable. Raised at COMPOSITION time
    (preflight), never mid-request.
    """
```

```python
# registry/__init__.py
class Registry:
    def register(self, spec: ComponentSpec) -> None: ...
    def resolve(self, name: str, kind: ComponentKind,
                config: Mapping[str, Any], *, strict: bool = False) -> Resolution: ...
    def build_context_components(self, cfg: AiEngineConfig) -> tuple[dict, ResolutionReport]: ...
    def specs(self, kind: ComponentKind | None = None) -> tuple[ComponentSpec, ...]: ...

def register(kind: ComponentKind, **kw) -> Callable[[type], type]:
    """Class decorator. @register(ComponentKind.EXTRACTOR, fallback="sift",
                                  requires_weights=("superpoint_v1",))"""
```

**Worked example — `"superpoint"` with no weights on the verified box:**
```
resolve("superpoint", EXTRACTOR, cfg)
 ├─ spec("superpoint")            ✓
 ├─ find_spec("torch")            ✓
 ├─ weights "superpoint_v1"       ✗  not at $LANDEXPLORER_WEIGHTS_DIR/superpoint_v1.pth
 │     log ComponentFallback(requested="superpoint", candidate="superpoint",
 │                           reason="weights missing: superpoint_v1")
 ├─ spec.fallback = "sift"
 ├─ spec("sift")                  ✓  terminal, no reqs
 └─ SiftExtractor(cfg)            ✓
 -> Resolution(requested="superpoint", resolved="sift", chain=("superpoint","sift"),
               reason="weights missing: superpoint_v1", degraded=True, device=CPU)
```
`preflight()` runs this for every configured component **at boot**, logs a table, and exposes it at `/api/v1/health/models` so the UI can render *"SuperPoint unavailable (weights missing) — using SIFT"*. `MatchJobResult.provenance` carries the same `ResolutionReport`, so **every result records which components actually produced it** — without which a degraded run is indistinguishable from a full one in the archive, and the calibration data (§10.7) would silently pool two different systems.

**Weights** (`registry/weights.py`): `WeightManifest` maps a logical key → `(filename, sha256, size, url, license)`. Search order: `config.weights_dir` → `$LANDEXPLORER_WEIGHTS_DIR` → `~/.cache/landexplorer/weights`. **Never auto-downloads** — a hidden 2 GB fetch inside a Celery task is a production incident, not a feature. A separate `scripts/fetch_weights.py` (another agent's file) is the only downloader.

---

## 15. Configuration

```python
@dataclass(frozen=True, slots=True)
class AiEngineConfig:
    extractor: str = "sift"                     # ★ classical default
    matcher: str = "flann"                      # ★ classical default
    detector_free: str | None = None            # None => no LoFTR
    segmenter: str = "classical"                # ★ classical default
    estimator: str = "opencv"
    scorer: str = "composite"
    strict_models: bool = False
    weights_dir: Path | None = None
    device: Device = Device.AUTO                # -> CPU on the verified box
    max_features: int = 8192
    ransac: RansacConfig = RansacConfig()
    degeneracy: DegeneracyConfig = DegeneracyConfig()
    scoring: ScoringConfig = ScoringConfig()
    tiles: TileBudgetConfig = TileBudgetConfig()
    rectification: RectificationConfig = RectificationConfig()
    deep: DeepConfig = DeepConfig()             # max_candidates=8, HARD-ENFORCED
    asift: AsiftConfig = AsiftConfig()          # scope="landmarks"
    calibration_id: str = "identity"
    job_seed: int = 0                           # -> deterministic RANSAC
    min_confidence: float = 25.0
    def validate(self) -> None:
        """Warn on lmeds. Assert deep.max_candidates <= tiles.windows_full.
        Assert scoring weights > 0."""
```

**The zero-config default is the fully classical path**, and per §12.5 it is also the *fastest* path on the verified hardware. Every deep component is opt-in and degrades to exactly this.

---

## 16. Testing

| Test | Mechanism |
|---|---|
| End-to-end, no network | `SyntheticTileProvider` + known ground-truth `H` → assert geo error < 1 m |
| Degeneracy | Construct collinear / tiny-hull / horizon-crossing correspondence sets → assert `gate == 0` and the exact `hard_failures` |
| Fallback | Point `weights_dir` at an empty dir → assert `Resolution(requested="superpoint", resolved="sift", degraded=True)` and that the job still completes |
| Determinism | Same `job_seed` twice → identical `H` (`randomGeneratorState` verified settable) |
| Slippy math | Round-trip `lonlat → px → lonlat` at z∈[0,22], φ∈[−85,85] → < 1e-9°; cross-check the known `res(z,φ)` table |
| Coordinate chain | Synthetic pose → known lon/lat → assert < 0.1 m |
| Descriptor compat | FLANN-KDTree + ORB `FeatureSet` → assert `IncompatibleDescriptors` raised |
| Detector-free | `LoFTRAsMatcher` with a dead `image_ref` → assert `DetectorFreeRequiresImages`; `DetectBasedSource(matcher=LoFTRAsMatcher)` → assert rejected at construction |
| Uncertainty | Monte-Carlo over `Σ_p`, `Σ_H` → compare the empirical vs analytic `Σ_win` (χ² test) |
| Score bounds | Property-based (hypothesis): all `S_• ∈ [0,1]`, `confidence ∈ [0,100]`, `gate==0 ⇒ confidence==0` |
| Pose | Synthetic `R,t` → `H` → decompose → assert angle error < `σ`; assert circular-mean correctness across the 0°/360° seam |

No test may require: network, GPU, weights, or Docker.

---

## 17. Open questions for the client

1. **Primary workflow: near-nadir drone, or ground-level oblique?** The honest accuracy differs by an order of magnitude (§8.2). The product should be *sold* on the drone case and *tolerate* the ground case.
2. **Acceptable `georef_ce90_m`?** If the answer is "sub-metre", consumer basemaps are disqualified and the local-orthophoto provider becomes the primary, not a fallback (§7.6).
3. **Labelled GCPs for calibration?** Without them the confidence stays an honestly-labelled uncalibrated ranking (§10.7).
4. **Is a GPU available in production?** It changes `deep.max_candidates` and whether LoFTR is viable at all (§12.2) — a config change, by design, not a rewrite.
