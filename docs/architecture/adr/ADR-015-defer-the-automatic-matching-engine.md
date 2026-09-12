# ADR-015 — Defer the automatic matching engine; ship manual GCP surveying

**Status:** Accepted · 2026-07-17 · **supersedes the delivery assumptions of ADR-003, ADR-006 and ADR-012**
**Source of record:** [`SCOPE.md`](../SCOPE.md) §1, §2 — which **overrides `CONTRACT.md` wherever the two disagree**
**Deciders:** Technical Lead
**Consequence class:** scope ruling. This is the decision that defines what this build *is*.

---

## Context

`CONTRACT.md` specifies, in loving and correct detail, an automatic geolocation pipeline: SIFT/ORB/
SuperPoint extraction → FLANN/SuperGlue/LightGlue/LoFTR matching → `cv2.USAC_MAGSAC` homography →
degeneracy gating → composite scoring → ranked candidates → GCPs. Nine pipeline steps, thirteen hard
degeneracy checks, a calibration harness, a camera-pose estimator and a confidence heatmap.

The pipeline's job is to locate a **ground-level oblique photograph** of a field against **nadir
satellite imagery**.

Three facts about that job, all of which were known and recorded before this decision:

1. **A planar homography is strictly valid only for a planar scene or a pure rotation.** A
   ground-level oblique photograph of farmland is neither. It is a perspective view of a scene with
   real depth, taken from roughly a metre and a half above the ground.
2. **The viewpoint change is ~90°.** `CONTRACT.md` §12.5 states it without flinching: *"a fence from
   the side and from above share almost no SIFT structure. **No architecture removes this.**"*
3. **The gating ladder has no wrong-field defence.** §11.7 says so explicitly, after the v2.0 audit
   proved H11 (`landmark_topology`) mathematically vacuous — it could only fire when H2 or H4 had
   already fired. A confident, non-degenerate, unique match against a **visually identical wrong
   field** passes every gate we have. §12.5 records this as an open risk, not a solved problem.

So the automatic path was the highest-risk component in the design, and it was unreliable **exactly
where the product is most used**: a surveyor standing in a field with a phone.

Meanwhile the brief's actual requirement is a coordinate a surveyor can dig, build, or file against.

## Decision

**The automatic matching engine is DEFERRED. It is not implemented in this build.**

**The product is a manual GCP surveying tool.** The surveyor marks a landmark in the uploaded
photograph, clicks the same physical spot on the satellite map, and the geographic coordinate is
recorded directly.

Everything else in `CONTRACT.md` — upload, metadata, viewer, annotation, imagery, the provider
abstraction, the tile proxy, persistence, accuracy reporting, exports, versioning, batch, deployment
— **is built in full, at production quality.**

### The deferred surface, precisely

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
| Semantic detection (field borders, roads, canals, trees, greenhouses, buildings, water, crop rows) | ABC only |
| Composite score (feature + geometric + landmark + semantic) | ABC only |
| DINOv2, SAM | registry entry only |

### The five rules that keep the deferral honest

1. **The seam is real, not decorative.** `ai_engine` exposes the full ABCs from `CONTRACT.md` §4.
   Callers depend on the ABC, never on a concrete class.
2. **Deferred bodies raise `NotImplementedDeferred`** (`ai_engine/errors.py`) — a *distinct* exception
   carrying the module name and a pointer to `SCOPE.md`. **Never `pass`. Never a silent `None`. Never
   a fabricated coordinate or confidence.**
3. **The API surface stays honest.** Endpoints 30, 43, 47, 48, 49 are **registered and documented**
   and return **`501 Not Implemented`** with the uniform error envelope and a `feature: "deferred"`
   marker. **They must not 404** — the feature is planned, not absent — **and must not fake a result.**
4. **The UI states it plainly.** Deferred controls are disabled with an honest tooltip: *"Automatic
   matching is not enabled in this build — place GCPs manually."* **No spinner that never resolves.**
5. **The DB schema is NOT cut.** `match_jobs`, `match_results`, `camera_poses`,
   `confidence_heatmaps`, `semantic_features` and their migrations are created as specified. They hold
   no rows. **Schema churn later is far more expensive than unused tables now.**

## Rationale — why this is not an arbitrary cut

**Manual mode has none of the automatic path's risk.** There is no homography, so there are no
degenerate solves, no viewpoint assumption, and no estimated confidence to calibrate.

> **The coordinate is a direct observation, not an inference.**

That sentence is the whole ADR. An automatic GCP is the pipeline's *hypothesis* about where a pixel
is; it needs a confidence, a covariance, a degeneracy report and a gating ladder because it might be
wrong in ways nobody can see. A manual GCP is a surveyor asserting *"that fence corner, there, is at
this spot on the map"*. It is as accurate as the surveyor's eye and the imagery's resolution — and it
**works on photographs where automatic matching would simply fail**.

**A confidently-wrong coordinate handed to a surveyor is this system's worst failure mode.** L12 says
*refuse rather than answer wrongly*. Deferring the engine is L12 applied to the roadmap instead of to
a single request: we decline to ship the component we cannot yet make honest.

**It is also the correct build order.** The manual correspondences this tool produces are exactly the
**ground-truth dataset** needed to evaluate an automatic engine. Building the automatic path first
would have meant having nothing to measure it against — and `CONTRACT.md` ships its calibration as
identity, `calibrated=false`, precisely because that dataset does not exist yet.

**Accuracy remains real and defensible.** Reported positional accuracy comes from imagery
ground-sample-distance and click precision at the map's zoom level (`gis/accuracy.py`) — **not from a
match score**. `accuracy_dominant_term` on a manual GCP is `landmark_click` or `georeference`, never
`match`. This is a *better*-founded number than the automatic path's, not a worse one.

## Consequences

**Positive.**
- The product's core interaction has **no research risk**. It works on day one, on this machine, with
  no network, no weights and no GPU.
- Two of the four `CONTRACT.md` §12.5 open risks (the viewpoint risk; the identical-wrong-field risk)
  **do not arise in this build**. They return the moment the engine is enabled — and must be
  re-escalated then, not silently inherited.
- `LE_AI_*` tuning knobs, the calibration harness and the fallback ladder are all still specified and
  still correct. They are simply not exercised.

**Negative, stated plainly.**
- **The client does not get automatic matching.** This is the headline. `TRACEABILITY.md` §2 lists all
  eighteen deferred capabilities and says **DEFERRED** in bold next to each.
- **L1 is suspended for this build.** L1 says *"Classical CV is the default path and the tested
  path… SIFT → FLANN → USAC_MAGSAC runs the whole product end to end."* It does not, because the
  classical path is deferred too. `SCOPE.md` §6 anticipates this: *"The twelve laws stand, **except**
  any law that presumes a working matching pipeline."* **L1 and its regression test are a promise
  about the future engine, not a description of this build.** Anyone reading L1 as current fact will
  be wrong.
- **`models/policy.py` resolves every deep-model path to *deferred*, not to a classical fallback** —
  because the classical fallback is deferred. The policy module must express that **without
  special-casing callers** (`SCOPE.md` §6).
- Unused tables and an unused registry carry a maintenance cost. Accepted deliberately: see rule 5.

**Neutral.**
- The synthetic known-homography fixtures are **still created**. They are the future engine's
  acceptance harness and they cost nothing now.

## Re-enabling later — the acceptance test for this ADR

> **Implementing the engine must require ZERO changes outside `ai_engine/`**, plus flipping the
> deferred endpoints from `501` to live and enabling the UI controls.
> **If any implementation in this build makes that untrue, that implementation is wrong.**

That is `SCOPE.md` §7, and it is the standard every unit in this build is held to. It is why the ABCs,
the registry entries, the DB schema, the job types, the `WindowSource` seam and the fixtures all exist
today with nothing behind them.

## Alternatives considered

**Rejected — ship the automatic engine anyway and let the gates catch bad matches.** The gates do not
catch the failure that matters. §11.7 is explicit: the ladder catches *degenerate* and *ambiguous*
solves; a unique, non-degenerate, confident match against the wrong-but-identical field passes all of
them. We would be shipping a component whose worst failure mode is invisible to its own defences, into
a product whose output someone may file against a legal boundary.

**Rejected — ship it behind a "beta / do not trust" flag.** A surveyor with a deadline will use it,
and the flag will be read as modesty rather than as a warning. If we cannot defend the output we
should not compute it. This is L12 as a product decision.

**Rejected — ship the classical path only (SIFT + FLANN + MAGSAC), defer only the deep models.** This
is the tempting one, because it is exactly what L1 and ADR-003 describe, and the code would have been
written anyway. It fails for the same reason: the classical path is *precisely* the path with the
~90° viewpoint problem. Deep detector-free matchers (LoFTR) are the ones with a plausible claim on
this regime — and their weights are unavailable and cannot be downloaded here. **The available path is
the untrustworthy one; the trustworthy-in-principle path is unavailable.** Shipping the available one
because it is available is how the confidently-wrong coordinate reaches the surveyor.

**Rejected — delete the deferred code, the ABCs, the registry entries and the tables; re-add later.**
Saves the maintenance cost of unused scaffolding and loses far more. Re-adding means a schema
migration against production data, re-deriving every seam, and discovering which caller assumptions
hardened while the seam was absent. `SCOPE.md` §4 rule 5 states the trade: *"Schema churn later is far
more expensive than unused tables now."* The seam is the deliverable; the body is the increment.

**Rejected — keep matching and drop manual mode as redundant.** Inverts the risk. Manual mode is the
only path that produces a defensible coordinate today, and it is the only path that produces the
ground truth the engine will eventually need.

## Related

- [`SCOPE.md`](../SCOPE.md) — the ruling of record. Overrides `CONTRACT.md`.
- [ADR-006](ADR-006-confidence-gating.md) — confidence gating; **amended**: manual confidence is
  surveyor-declared, never computed.
- [ADR-014](ADR-014-landmarks-are-user-marked.md) — landmarks are user-marked. **This ADR extends
  ADR-014's principle from landmarks to the coordinate itself.**
- [ADR-003](ADR-003-classical-cv-default.md) — classical CV as default; **its subject is deferred.**
- [`TRACEABILITY.md`](../TRACEABILITY.md) §2 — every deferred capability, named.
- [`docs/api/endpoints.md`](../../api/endpoints.md) — the five 501 endpoints.
