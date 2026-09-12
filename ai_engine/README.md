# `landexplorer-ai-engine`

Pixels in, pixels out.

This package is LandExplorer's computer-vision core, and it is deliberately usable
**without the web app**. It has no opinion about HTTP, it cannot reach a database, and it
does not know what a coordinate reference system is. You hand it an image and some
candidate patches of imagery; it hands you back pixel-space fixes and an honest score.
Turning a pixel into a coordinate is [`gis`](../gis)'s job — and the fact that nothing in
here *can* do that is what keeps the boundary real rather than aspirational.

> ### ⚠️ Scope of this build — read this first
>
> **The automatic matching engine is DEFERRED.** See
> [`docs/architecture/SCOPE.md`](../docs/architecture/SCOPE.md).
>
> LandExplorer currently ships as a **manual GCP surveying tool**: the surveyor marks a
> landmark in the photo, clicks the same spot on the satellite map, and the coordinate is
> recorded as a **direct observation** — not an inference.
>
> Everything under `extractors/`, `matchers/`, `geometry/`, `semantics/`, `landmarks/`,
> `scoring/`, `heatmap/` and `pipeline/` therefore exists as **ABCs, registry entries and
> typed stubs**. Their bodies raise
> [`NotImplementedDeferred`](src/ai_engine/errors.py) — never `pass`, never a silent
> `None`, and never a fabricated coordinate or confidence.
>
> **Why:** automatic geolocation of a *ground-level oblique* photograph against *nadir*
> satellite imagery is the highest-risk component in the design. A planar homography is
> strictly valid only for a planar scene or a pure rotation, and a ground-level oblique
> violates both. The automatic path would have been least reliable exactly where the
> product is most used — and a confidently-wrong coordinate handed to a surveyor is this
> system's worst failure mode.
>
> The seam is real, not decorative: implementing the engine later must require **zero
> changes outside `ai_engine/`**. The types, the ABCs and the tests-for-the-seam in this
> package are what make that true.

---

## Install

Every runtime dependency (`numpy`, `cv2`, `scipy`) is a **system-site package** on the
verified dev box, and `osgeo` cannot be pip-installed at all. A plain `python -m venv`
hides all of them, so:

```bash
python -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ./ai_engine --no-deps          # runtime
pip install -e ./ai_engine[dev] --no-deps     # + pytest, hypothesis, mypy, ruff
```

`--no-deps` is not a shortcut. It is what stops pip shadowing the system OpenCV with a
wheel.

```bash
cd ai_engine && pytest        # green after the [dev] install; no network, no GPU, no weights
```

**`import ai_engine` is clean today with zero runtime installs.** The test *runner* is a
dev dependency, not a runtime one — that is the only thing the `[dev]` extra buys you.

## Use it without the web app

```python
from ai_engine import AiEngineConfig, run_match_job, version

print(version())                 # "2.0.0"
cfg = AiEngineConfig()           # a complete, working classical configuration
cfg.validate()
```

`AiEngineConfig()` with no arguments is a valid, fully-operational configuration: `sift`
→ `flann` → `usac_magsac`, CPU, no weights. **Zero required settings** — every field has
a working default (L10), and nothing here reads the environment. The backend reads the
environment once, in `app.core.config`, and constructs one of these.

The public surface is five names, and they bind lazily (PEP 562):

| Name | What it is |
|---|---|
| `run_match_job(ctx) -> MatchJobResult` | the primary entry point |
| `suggest_landmarks(image, ...)` | the second entry point |
| `AiEngineConfig` | what you configure it with |
| `Registry` | what resolves the backends |
| `version()` | what produced your result |

## Layout

```text
src/ai_engine/
├── types/          ★ the shared vocabulary. numpy + stdlib ONLY. Import-cheap forever.
├── errors.py         the exception hierarchy — incl. NotImplementedDeferred
├── config.py         AiEngineConfig + sub-configs. stdlib dataclasses, NOT pydantic.
├── version.py        ENGINE_VERSION + per-component versions (cache-key inputs)
├── logging.py        getLogger("ai_engine.*"). NEVER configures handlers.
├── models/           the registry — the graceful-degradation engine
├── extractors/       image -> keypoints + descriptors          [DEFERRED]
├── matchers/         descriptors -> correspondences            [DEFERRED]
├── geometry/         correspondences -> homography/pose        [DEFERRED] ★ PIXELS ONLY
├── semantics/        optional masks to gate features           [DEFERRED]
├── landmarks/        landmark-steered mechanisms + suggestion  [DEFERRED]
├── scoring/          match quality -> confidence               [DEFERRED]
├── heatmap/          posterior over camera location            [DEFERRED]
├── pipeline/         orchestration                             [DEFERRED]
├── runtime/          caches, parallelism, structured events
└── windows/          SyntheticWindowSource (test scenes with a known ground-truth H)
```

### `types/` is cheap, and that is load-bearing

`gis.candidates` is permitted **exactly one** cross-package import — `ai_engine.types` —
and the whole justification is that this package costs only numpy + stdlib and *cannot*
drag in `cv2` or `torch`. Two rules follow, and
[`tests/test_types_import_cheap.py`](src/ai_engine/tests/test_types_import_cheap.py)
enforces both on a **fresh interpreter**:

1. **`ai_engine.types` never imports `ai_engine.models`.** That is why `provenance.py`
   lives in `types/`: `types/results.py` needs `ResolutionReport`, and the dependency may
   only point one way. `models/spec.py` re-exports *from* `types/`.
2. **`ai_engine/__init__.py` never imports the pipeline at module scope.** A package
   `__init__` runs before any submodule import, so `from ai_engine.types import
   CandidateWindow` would otherwise execute the pipeline and pull in every extractor —
   destroying the exact property that permits the import at all. The root is
   `__getattr__`-lazy.

## Weights

**None are required. None are downloaded — ever, by anything, at any time.**

An empty weights directory is the *supported* configuration, not a degraded one: the
classical path runs the whole product end to end, and on this hardware
(`torch.cuda.is_available()` is `False` despite a cu130 wheel) it is also the **faster**
one — ~3.2 s cold and ~1.0 s warm, versus +16–40 s for the deep path.

A missing, or *corrupt*, weight file is a **`WARNING` and a fallback** — never a
traceback, and never silent (L11). A truncated checkpoint is treated exactly like an
absent one: a half-downloaded file that imports and then produces garbage is far worse
than one that simply is not there.

```bash
export LE_AI_MODEL_WEIGHTS_DIR=./data/model_weights   # default; empty is fine
python scripts/download_models.py                     # the ONLY downloader. Opt-in. Never at boot.
```

If you configured SuperPoint and got SIFT, you will find out: `Resolution.chain`,
`Resolution.reason` and a `ComponentFallback` event at `WARNING` all say so. That is a
requirement, not a nicety.

## The rules this package is held to

- **L1** — classical CV is the default *and* the tested path. If every weight file
  vanished, the only observable change is accuracy and some log lines.
- **L3** — `ai_engine` does not know what a CRS is. It begins at pixels and ends at
  pixels. `CandidateWindow.geotransform` and `.crs` are an **opaque payload**: carried,
  never read. Enforced by a CI grep, not by good intentions.
- **L8** — `torch` is imported in exactly one module: `models/torch_guard.py`.
- **L11** — a missing weight, key or optional dependency is a warning and a fallback.
- **L12** — refuse rather than answer wrongly. A GCP is a survey coordinate someone may
  dig, build, or file against. Confidence gating, degeneracy rejection and honest
  `degraded` reporting outrank result availability.

### One thing worth knowing about `confidence`

It ships **uncalibrated** (`calibrated=False`, `calibration_id="identity"`), and that is
deliberate. A fabricated calibration curve is a lie with a probability attached to it.
Until a curve is fitted against real ground truth, `confidence` is an **ordinal score** —
useful for ranking, not to be printed as a percentage.

The manual GCP correspondences this product collects *are* that ground-truth dataset.
Building the manual path first is what makes the automatic path evaluable later; building
it the other way round would have meant having nothing to measure against.
