# Adding a CV backend (extractor · matcher · estimator · segmenter · suggester)

**Owner:** IU-02 (registry) + the relevant IU-03..07 · **Normative:** `CONTRACT.md` §4, §11.1–§11.3 ·
[ADR-003](../architecture/adr/ADR-003-classical-cv-default.md)

---

## 0. ★ Read this before you write anything

**The automatic matching engine is DEFERRED** ([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)).

**In this build, every extractor, matcher, estimator, segmenter and suggester body raises
`NotImplementedDeferred`** — including SIFT, ORB and FLANN. **The classical path is deferred too**, so
`models/policy.py` resolves every path to *deferred*, not to a classical fallback (`SCOPE.md` §6).

**So there are two reasons to be here:**

| You are… | Read |
|---|---|
| **Adding a deferred stub** (the normal case now) | §1 |
| **Implementing a real backend** (when the engine is re-enabled) | §2 onward |

> ★ **Do not "helpfully" implement a deferred component.** It is not a TODO left by an oversight. It is
> a ruling, and **shipping a confidently-wrong coordinate is this system's worst failure mode.**

---

## 1. A deferred stub — the whole pattern

```python
# ai_engine/src/ai_engine/extractors/acme.py
from ai_engine.errors import NotImplementedDeferred
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import register
from ai_engine.models.spec import ComponentKind, ComponentSpec
from ai_engine.types import FeatureSet


@register(ComponentSpec(
    name="acme",
    kind=ComponentKind.EXTRACTOR,
    fallback="sift",                    # ★ chains must be PROVABLY TERMINATING
    requires_weights=("acme.pth",),
    requires_packages=("torch",),
))
class AcmeExtractor(FeatureExtractor):
    """Acme feature extractor. ★ DEFERRED in this build — see SCOPE.md §4."""

    descriptor_dim = 256
    descriptor_kind = DescriptorKind.FLOAT

    def extract(self, image: np.ndarray) -> FeatureSet:
        raise NotImplementedDeferred(module=__name__, doc="docs/architecture/SCOPE.md")
```

**The four rules (`SCOPE.md` §4):**

1. ★ **The seam is real, not decorative.** The ABC is the full `CONTRACT.md` §4 interface. **Callers
   depend on the ABC, never on a concrete class.**
2. ★ **`raise NotImplementedDeferred`**, carrying the module name + a pointer to `SCOPE.md`.
   **Never `pass`. Never a silent `None`. Never fabricated values.**
3. ★ **The registry entry stays.** `Registry.specs()` must be non-empty; preflight must report it.
4. ★ **Re-enabling must touch nothing outside `ai_engine/`.** If your stub makes that untrue, **your
   stub is wrong** (`SCOPE.md` §7).

---

## 2. A real backend — the registry contract

```python
@register(ComponentSpec(
    name="acme",
    kind=ComponentKind.MATCHER,
    fallback="flann",                   # ★ or None for a TERMINAL spec
    requires_weights=("acme.pth",),
    requires_packages=("torch",),
    sha256={"acme.pth": "abc123…"},     # ★ a truncated weight is treated EXACTLY like a missing one
))
```

### The rules the registry enforces at registration time

- ★ **Terminal specs (`fallback=None`) must have NO `requires_weights` and NO `requires_packages`
  beyond the base install** — **asserted at registration.** That is what makes chains **provably
  terminating** rather than hopefully terminating.
- ★ **Cycle detection terminates.**
- ★ **`descriptor_dim % 8 == 0` for every BINARY extractor** — asserted at registration.
- The existing chains: `superpoint → sift` · `dinov2 → sift` · `asift → sift` · `akaze → orb` ·
  `brisk → orb` · `sift → ⊥` · `orb → ⊥` · `superglue → flann` · `lightglue → flann` ·
  `loftr → flann` · `flann → bf` · `bf → ⊥` · `sam → classical` · `classical → ⊥`.

### Import it for registration

```python
# ai_engine/src/ai_engine/models/registration.py — its SOLE job
from ai_engine.extractors import acme  # noqa: F401
```

★ Imported **only** by `_ensure_registered()`, **lazily, at first `resolve()`** — never at
`ai_engine.models` import time (**that would cycle**: models → extractors → models).

---

## 3. The laws you will trip over

| Law | What it means for you |
|---|---|
| **L8** | ★ **`torch` is imported in exactly ONE module: `models/torch_guard.py`.** Your backend calls `try_import_torch()` → `module \| None`. **A module-scope `import torch` in your file is a defect.** |
| **L3** | ★ **`ai_engine` does not know what a CRS is.** No pyproj, no EPSG, no `lat`/`lon`, no `z/x/y`. **Pixels in, pixels out.** CI greps for it. |
| **§11.3** | Bind optional deps **inside the function**, never at module scope. |
| **§11.1** | ★ Preflight uses **`importlib.util.find_spec`, not `import`** — no side effects, no CUDA init, **no 2-second torch import to discover we will not use it**. |
| **§11.2** | ★ **Device unavailability routes through the SAME fallback branch as missing weights.** `LE_AI_DEVICE=cuda` with no GPU ⇒ **WARN + `cpu`**, never a crash. **Never infer CUDA from the wheel name** — `torch 2.11.0+cu130` is installed here and **there is no GPU**. |

★ **`cv2.xfeatures2d` is ABSENT** (no opencv-contrib). **SURF/BEBLID/VGG/LATCH are unavailable and must
not be referenced** — a runtime assertion enforces it, which is stronger than the grep and **catches
dynamic access**.

---

## 4. Weights

```python
# ai_engine/src/ai_engine/models/weights.py — resolve_weight_path()
# ★ NEVER downloads. NEVER raises.
```

- ★ **Weights are NEVER auto-downloaded.** *A silent multi-hundred-MB fetch inside a Celery task, on a
  machine that may be air-gapped, triggered by a user clicking "Match", is an unacceptable failure
  mode and an unacceptable surprise.*
- `scripts/download_models.py` is **opt-in**, **prints each model's licence**, and is **never invoked at
  build or boot**. ★ **It requires a worker RESTART to take effect** — preflight is cached, and the
  script says so in its own output.
- ★ **A corrupt or truncated weight file is treated EXACTLY like a missing one.** *A half-downloaded
  `.pth` that imports and then produces garbage is far worse than one that is simply absent.*
- `LE_AI_MODEL_WEIGHTS_DIR` is ★ **empty by default, and that is the supported state.**

---

## 5. What the parametrised contract test will assert

★ **A component that is not in the contract test does not exist** (§13.4 rule 8). It picks you up
automatically from the registry.

**Extractors** (`test_extractors_contract.py`):
- `extract()` returns a `validate()`-clean `FeatureSet`
- ★ `extract()` on a **blank image returns an EMPTY FeatureSet and does not raise**
- ★ `extract(img).descriptor_dim == cls.descriptor_dim` — *the assertion AKAZE's `D=486` could never
  have passed*
- FLOAT descriptors are **unit-norm**; BINARY are **bit-packed to `D//8`**
- ★ `extract_at()` on a **bi-modal-orientation patch** returns `len(...) <= K` with **no duplicate
  `landmark_ids`** — *the `cv2.SIFT.compute` multi-orientation trap*

**Matchers** (`test_matchers_contract.py`):
- identical FeatureSets ⇒ ~N mutual matches; unrelated ⇒ few
- scores in `[0,1]`, **higher-is-better**
- ★ **`FlannMatcher` + an ORB (BINARY) FeatureSet raises `IncompatibleDescriptors`** — **not garbage**

★ **In this build these suites assert the stub raises `NotImplementedDeferred` and that registration is
intact.**

---

## 6. Behaviour you inherit

| Situation | What happens |
|---|---|
| Weight missing | ★ **WARN + `WarningItem` + `model_fallbacks_total{}` + fall back.** The job **succeeds**. |
| Weight **corrupt** | ★ Identical to missing. |
| Explicitly requested, weight missing | ★ **`202` + fallback + `WarningItem`** — **not a 503** |
| `LE_AI_STRICT_BACKEND=true` | **Raise `ComponentUnavailable`.** ★ **CI accuracy suites only — `true` in prod violates L1.** |
| No GPU | `auto` → `cpu`. `cuda` → **WARN + `cpu`**. |
| Result | ★ `match_results.degraded = true` and `feature_matcher_used = 'flann'` — **the row does not lie about what produced the numbers.** |
| UI | An **unrequested** fallback ⇒ an informational chip. A **requested-and-denied** one ⇒ a warning. The distinction is `warnings[].requested !== null`. |

> ★ **`model_fallbacks_total` is deliberately a metric, not just a log line.** A fleet-wide spike means
> **someone's weight volume did not mount** — *that should page, not hide in `INFO`.* **It is the metric
> that proves L1 is working in production rather than merely specified.**

---

## 7. Checklist

- [ ] ★ **In this build: the body raises `NotImplementedDeferred`** with the module name + `SCOPE.md`
- [ ] ABC implemented in full; **callers depend on the ABC**
- [ ] `@register(ComponentSpec(...))` with a **terminating** fallback
- [ ] Imported in `models/registration.py`
- [ ] ★ **No module-scope `torch`** (L8) · **no CRS** (L3) · **no `cv2.xfeatures2d`**
- [ ] Optional deps **bound at call time**
- [ ] `LE_AI_ACME_WEIGHTS` in §9.8 + `.env.example`, **defaulting to empty**
- [ ] `cd ai_engine && pytest` green ★ **with no weights, no GPU, no network**
- [ ] ★ **Re-enabling the engine still requires zero changes outside `ai_engine/`**
