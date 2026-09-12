# ADR-014 — Landmarks are user-marked; automatic detection is at most a hint layer

**Status:** Accepted · **elevated in scope by [ADR-015](ADR-015-defer-the-automatic-matching-engine.md)**
**Normative record:** `CONTRACT.md` §5.4, §6.1 (`AnnotationRead.confidence` — *the surveyor's certainty*) · `SCOPE.md` §5

---

## Context

The brief says the surveyor marks landmarks manually. It is tempting to auto-detect them: we have SIFT
keypoints at ingest, we could have SAM regions, and "the app finds the landmarks for you" demos
beautifully.

The temptation is worth naming precisely, because it is the same temptation ADR-015 later resolves at
a larger scale.

## Decision

**`annotations` rows are always user-authored** — `pixel_x`, `pixel_y`, `label`, `description`,
`confidence`, `kind`. **`AnnotationRead.confidence` is 0–1 and is the SURVEYOR'S certainty**, never a
detector's score.

Automatic keypoints and user landmarks are **never confused**:

> **Keypoints drive the *homography*. Landmarks are what the homography is *applied to*.**

Any automatic detection is a **non-binding hint layer** — snapping assistance, never a source of GCPs.

**★ Under `SCOPE.md`, the hint layer does not exist in this build.** Automatic landmark suggestion is
DEFERRED (`SCOPE.md` §4; `TRACEABILITY.md` D-14): `ai_engine/landmarks/suggest.py` is an ABC,
`POST /images/{id}/suggest-landmarks` returns **501**, and the UI control is **disabled with an honest
tooltip**. Every landmark in this build is a human click, without qualification.

## Rationale

**SIFT keypoints are wherever gradients are interesting: leaf texture, shadow edges, image noise.**
They are not survey landmarks. **A corner-of-a-shadow GCP exported to a Shapefile is worse than no
GCP** — it is a coordinate with a provenance that looks identical to a good one.

**The surveyor's domain knowledge is the product's actual input.** *Which* fence corner is the real
control point is a judgement about the site, the survey, and what the client asked for. No detector
has that context, and a detector that guesses confidently is competing with the one thing we cannot
replace.

**Provenance is the deliverable.** Every exported GCP traces to a human click, a human label, a human
timestamp and a human-declared certainty. **That is defensible in a way an auto-detected point is
not** — and "defensible" is the requirement, since the output may be filed.

**ADR-015 is this ADR, applied one level up.** ADR-014 says *the human chooses which point matters*;
ADR-015 says *the human also asserts where that point is on the map*. Same reasoning — human judgement
outranks a confident guess wherever the guess cannot be validated — applied to the coordinate rather
than to the landmark. Under `SCOPE.md` the two collapse into a single flow: **mark it, then place it.**

## Consequences

**Positive.**
- Unambiguous provenance, end to end. `source = "manual"` on every GCP in this build.
- No detector to calibrate, no false-positive rate to explain to a surveyor, no "why did it mark the
  shadow?" support ticket.
- The seam survives: `LandmarkSuggester` is an ABC with a registry entry, so the hint layer can be
  implemented later **without touching a caller** (`SCOPE.md` §7).

**Negative, stated honestly.**
- **Marking landmarks by hand is work**, and this build gives the surveyor no assistance with it —
  no suggestions, no snapping. On a photograph with forty control points that is forty deliberate
  clicks. This is the cost of the decision and it is paid by the user, every time.
- `VITE_MIN_LANDMARKS=4` exists because a homography needs ≥4 — a constraint inherited from the
  deferred engine. In manual mode a single correspondence is already a valid GCP, and the UI must not
  imply otherwise.

## Alternatives considered

**Rejected — auto-detecting GCPs from keypoints.** SIFT keypoints are not survey landmarks; see the
rationale. This is the decision, restated.

**Rejected — SAM-proposed landmark regions as the primary flow.** Needs weights (unavailable here, and
never auto-downloaded), and it changes the product from **"mark what you know"** to **"confirm what
the model guessed"** — a different, and less trustworthy, tool. A surveyor confirming forty plausible
suggestions is doing a worse job than one marking eight points they chose, and will do it faster,
which is the trap.

**Rejected — auto-detect and flag for review.** The flag is read as modesty, not as a warning; see
ADR-015's parallel rejection. Review of confident output converges on rubber-stamping.

## Related

- [ADR-015](ADR-015-defer-the-automatic-matching-engine.md) — the same principle, applied to the coordinate.
- [ADR-006](ADR-006-confidence-gating.md) — declared vs computed confidence.
- `CONTRACT.md` §6.1 (`AnnotationRead`), §4.23 (`LandmarkSuggester`, deferred) · `SCOPE.md` §5.
