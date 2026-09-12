# ADR-003 — Classical CV is the default path; deep models are optional plugins that degrade gracefully

**Status:** Accepted — **but its subject is DEFERRED in this build. See the banner below.**
**Normative record:** `CONTRACT.md` L1, L11, §11.1, §11.2, §11.3 · `SCOPE.md` §1, §6

---

## ★ Status banner — read before relying on anything here

**The automatic matching engine is DEFERRED ([ADR-015](ADR-015-defer-the-automatic-matching-engine.md),
`SCOPE.md` §1). Classical CV is deferred with it.** This ADR describes a decision that is **accepted
and unimplemented**.

**L1 is therefore suspended for this build.** L1 reads *"Classical CV is the default path and the
tested path… SIFT → FLANN + Lowe ratio → `cv2.USAC_MAGSAC` runs the whole product end to end."*
**It does not.** `SCOPE.md` §6 anticipates exactly this: *"The twelve laws stand, **except** any law
that presumes a working matching pipeline."*

**Anyone reading L1 as a description of what runs today will be wrong.** What survives and is real
today is the *degradation machinery* — the registry, the fallback policy, `torch_guard`, the weight
manifest, `find_spec` probing, the preflight report — because that machinery is what `GET
/capabilities` and `/health/ready` report on, and because `SCOPE.md` §6 requires
`models/policy.py` to express *deferred* **without special-casing callers**.

## Context

Deep matchers (SuperGlue, LightGlue, LoFTR) and deep features (SuperPoint, DINOv2) are the state of
the art. They also require **weight files that will not be downloaded** on this machine, a **GPU that
does not exist here** (`torch.cuda.is_available()` is `False` despite the `cu130` wheel), and a network
the brief gives no guarantee of.

A design that needs weights to work is a design that does not work here.

## Decision

**Classical CV is the default and the terminal fallback.** Deep backends are **optional accelerants**,
resolved through one registry with a **provably terminating** fallback chain:

```
superpoint → sift    dinov2 → sift     asift → sift
akaze → orb          brisk → orb       sift → ⊥      orb → ⊥
superglue → flann    lightglue → flann  loftr → flann (via source swap)
flann → bf           bf → ⊥
sam → classical      dinov2_seg → classical          classical → ⊥
```

**Terminal specs (`fallback=None`) must have no `requires_weights` and no `requires_packages` beyond
the base install — asserted at registration time.** That is what makes the chain provably terminating
rather than hopefully terminating.

**A missing weight, key, optional dependency or GPU is a `WARNING` + a `WarningItem` + a metric
increment + a fallback — never a traceback, never silent** (L11). **A corrupt or truncated weight file
is treated exactly like a missing one**: a half-downloaded `.pth` that imports and then produces
garbage is far worse than one that is simply absent.

**Weights are NEVER auto-downloaded.** A silent multi-hundred-MB fetch inside a Celery task, on a
machine that may be air-gapped, triggered by a user clicking "Match", is an unacceptable failure mode
and an unacceptable surprise. `scripts/download_models.py` is opt-in, prints each model's licence, and
is never invoked at build or boot.

**`torch` is imported in exactly one module** (L8): `ai_engine/models/torch_guard.py`. Preflight uses
`importlib.util.find_spec` — **not `import`** — so probing costs no CUDA init and no 2-second torch
import to discover we will not use it.

**Device unavailability routes through the SAME fallback branch as missing weights** (§11.2). It is
the same failure class and gets the same treatment. **Never infer CUDA from the wheel name.**

**`model_fallbacks_total{requested,effective,reason}` is a metric, not just a log line.** A fleet-wide
spike means someone's weight volume did not mount — **that should page, not hide in `INFO`.**

## Rationale

**The asymmetry with imagery is deliberate and is stated so nobody "fixes" it** (§11.0): an explicitly
requested unconfigured **provider** is a `503`; an explicitly requested missing **weight**
(`matcher: "superglue"`) is a `202` + fallback + `WarningItem`.

> **Imagery changes the answer's *provenance*; a matcher changes only its *accuracy*.**

Silently serving 10 m Sentinel when the operator paid for 0.3 m Mapbox is worse than a 503. Silently
serving SIFT instead of SuperGlue is a **reported** accuracy trade on a fully operational path. Both
are reported; **only one is refusable.**

**`models` never affects readiness.** This is L1 expressed in the health surface: the dev machine has
no weights and must run end to end. **If missing weights made the app unready, it would never start
here.** Weight presence is reported so the UI can grey out `superglue` in the dropdown — and that is
*all* it does.

## Consequences

**In this build (`SCOPE.md`).**
- Every deep-model path resolves to **deferred**, not to a classical fallback — **because the classical
  fallback is deferred too.** `models/policy.py` expresses this without special-casing callers.
- The registry, the specs, the chains and the preflight report are all real and tested. The bodies
  raise `NotImplementedDeferred`.
- `test_registry_fallback.py` — *"THE L1 REGRESSION TEST"* — proves the **seam**, not the pipeline.

**If/when the engine is enabled.**
- **If every weight file vanished, the only observable change is accuracy and a set of log lines.**
- The fresh-machine default (SIFT + FLANN) renders an **informational** chip — *"Matched with SIFT +
  FLANN"*. A **requested-and-denied** backend renders a **warning**. The distinction is
  `warnings[].requested !== null`, and it matters: one is the designed path, the other is a
  disappointment the user asked for.
- `LE_AI_STRICT_BACKEND=true` makes missing weights **raise**. **CI accuracy suites only — `true` in
  prod violates L1.**
- `LE_AI_DEEP_MAX_CANDIDATES=8` is **code-enforced**, because LoFTR/SAM are 2–8 s per 1024² image on CPU.

**Negative, stated honestly.**
- Graceful degradation means the system can be **quietly mediocre**: it works, and nobody notices the
  accuracy left on the table. That is what the `WarningItem`, the `degraded` flag on the row, and the
  `model_fallbacks_total` metric are for — and why the metric exists rather than only a log line.
- A registry with fallback chains is genuinely more machinery than `import cv2; sift = cv2.SIFT_create()`.
  It earns its keep the first time a weight volume fails to mount in production.
- **`cv2.xfeatures2d` is ABSENT** (no opencv-contrib): SURF/BEBLID/VGG/LATCH are unavailable and
  **must not be referenced**. The classical path is SIFT, ORB, AKAZE, BRISK only. A runtime assertion
  enforces it — stronger than the grep, and it catches dynamic access.

## Alternatives considered

**Rejected — deep models as the default.** Weights are unavailable and undownloadable here; there is no
GPU. The product would not run on the only machine we can test on.

**Rejected — classical only, no deep seam.** Forecloses the one class of matcher (detector-free, e.g.
LoFTR) with a plausible claim on the ~90° viewpoint problem — which, per ADR-015, is the problem that
matters most. The seam costs a registry and buys the ability to evaluate LoFTR the moment weights
exist, **without touching a caller**.

**Rejected — auto-download weights on first use.** See the decision. Air-gapped machines, surprise
multi-hundred-MB fetches inside a task, and a licence the user never saw.

**Rejected — fail loudly when a requested backend is unavailable (the general case).** That is
`LE_AI_STRICT_BACKEND`, and it is correct for CI and wrong for production: it converts an accuracy
trade into an outage. See the §11.0 asymmetry.

## Related

- [ADR-015](ADR-015-defer-the-automatic-matching-engine.md) — **why this ADR's subject is not in this build.**
- [ADR-006](ADR-006-confidence-gating.md) — the gating ladder this path would feed.
- `CONTRACT.md` §11.0–§11.3, §9.8 · `SCOPE.md` §6.
