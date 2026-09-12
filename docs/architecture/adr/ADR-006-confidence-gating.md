# ADR-006 — Refuse rather than answer wrongly; and confidence is never invented

**Status:** Accepted · **amended 2026-07-17 by [ADR-015](ADR-015-defer-the-automatic-matching-engine.md)**
**Normative record:** `CONTRACT.md` L12, §11.6, §11.7 · `SCOPE.md` §5

---

## Context

**A GCP is a survey coordinate someone may dig, build, or file against.** That single sentence sets
the error budget for the entire product. The asymmetry is total:

- A **missing** coordinate costs a surveyor ten minutes and some annoyance.
- A **wrong** coordinate costs a trench in the wrong place, a boundary dispute, or a filed document
  that is false.

A system that answers 95% of the time with 5% silent errors is **worse than useless** for this job,
because the surveyor cannot tell which 5%. A system that answers 70% of the time and says "I could not
find this" for the rest is a usable instrument.

## Decision

**L12 — refuse rather than answer wrongly.** Confidence gating, degeneracy rejection and honest
`degraded` reporting **outrank result availability**.

### 1. "No match" is not a failure (§11.6)

| Outcome | Job status | Response |
|---|---|---|
| Every window rejected by the confidence gate | **`succeeded`** | `result_count = 0`, `best_confidence = null`, an **empty page** — not a 404 |
| Every window rejected by a hard degeneracy check | **`succeeded`** | Same, plus the `DegeneracyReport` on each rejected candidate so a reviewer can see *why* |
| Winner's margin < `LE_AI_RANK_MARGIN` | **`succeeded`** | `AMBIGUOUS_MATCH` warning, **candidates returned and visible** |
| The pipeline could not run (provider down, DB down, OOM) | **`failed`** | `error` populated |

Modelling "no match" as `failed` would trigger **pointless retries of a deterministic outcome** —
burning 60 s of CPU to produce the identical answer — and would tell the surveyor the system broke when
in fact the answer is *"not here"*. **`failed` is reserved for: the pipeline could not run.**

### 2. Multiple independent gates, each of which can veto (§11.7)

Match count (10) · inlier count (12) · hard degeneracy H2–H10/H12/H13 · soft degeneracy (multiplies,
never zeroes) · confidence (`LE_AI_MIN_CONFIDENCE = 40`) · rank margin (10, taken on `raw`) · regime
ceiling (nadir 100 / oblique_rectifiable 85 / oblique_raw 60 / ground_horizon 35 / unknown 50).

**Every surviving GCP carries `confidence` AND `accuracy.total_ce90_m`.** Exports include both.
**A GCP without its uncertainty is a lie of omission.**

### 3. ★ What the ladder does NOT do — stated plainly

**It has no wrong-field defence.** H11 claimed to be one and the v2.0 audit proved it **vacuous**: a
projectivity preserves hull cyclic order for *any* `H` whose ROI avoids the vanishing line and has
positive determinant — both already hard-checked by H4 and H2. It could only fire when another check
had already fired. **It is deleted, and the claim is withdrawn rather than replaced with a weaker
one.** The ambiguity clamp is **relative** and cannot detect a globally-wrong-but-unique answer.

**A stated non-defence is worth more than a check that makes a reviewer feel defended.**

### 4. ★ AMENDMENT (ADR-015) — manual confidence is *declared*, not computed

With the automatic engine deferred, **this build has no computed confidence at all.**

> **`confidence` in manual mode is a surveyor-declared value — a deliberate 1–5 / low-med-high
> judgement — NEVER a computed number.** (`SCOPE.md` §5)

Consequences that follow, and that no unit may quietly "improve":

- **No server path may compute, infer, adjust or overwrite a manual GCP's `confidence`.** It is
  whatever the surveyor sent. `PATCH /gcps/{id}` adjustment **leaves it untouched** — which was
  already the rule for a different reason (see below), and is now the rule for the strongest one.
- **Every GCP records `source = "manual"`**, so an automatic GCP can never be confused with an
  observed one downstream or in an export.
- **Reported accuracy is not confidence and never was.** It comes from imagery ground-sample-distance
  and click precision at the map's zoom level (`gis/accuracy.py`) — **a real, defensible number, not a
  match score.** `accuracy_dominant_term` on a manual GCP is `landmark_click` or `georeference`, never
  `match`.
- **Uncommitted correspondences must never appear in the GCP table or an export.**

### 5. Why a manual adjustment does NOT set `confidence = 100`

Tempting, and wrong — under both regimes.

Under the automatic engine, `gcps.confidence` is *the pipeline's score for this correspondence*.
Overwriting it on a human edit destroys the only record of how well the algorithm did, makes
`?confidence__gte=70` meaningless (every adjusted point passes), and **asserts a certainty the human
never claimed** — a surveyor nudging a marker 3 m is *guessing better*, not measuring.

Under manual mode the reasoning lands in the same place from the other side: the surveyor **already
declared** their confidence when they committed the correspondence. Silently promoting it to 100
because they later dragged the marker would be the system inventing a human judgement.

Human certainty is carried by `manually_adjusted` + `adjustment_offset_m` + `adjusted_by` + the note.
**A client that wants "trust human edits absolutely" filters on `manually_adjusted`, which says
exactly that and nothing more.**

## Consequences

**Positive.**
- The system returns "I could not find this" more often than a naive one would. **That is the correct
  trade for a surveying instrument.**
- Under `SCOPE.md`, the hardest part of this ADR — calibrating an estimated confidence nobody can
  validate — **does not arise**. There is no estimate to calibrate. `CONTRACT.md` ships its
  calibration as identity with `calibrated=false` precisely because the validation dataset does not
  exist; manual mode is how that dataset gets built.
- Ambiguity is **shown, not resolved silently**: `AMBIGUOUS_MATCH` with ranked candidates visible is
  far more useful to a surveyor who knows the site than a bare "no match".

**Negative, stated honestly.**
- A surveyor-declared confidence is only as honest as the surveyor. **We have traded a number we could
  not validate for a number we do not validate** — but the provenance is unambiguous (`source =
  "manual"`, a human, a timestamp, an optional note), which the estimated number never was.
- Seven gates mean seven thresholds an operator can misconfigure. All have working defaults (L10) and
  every clamp records a `clamp_reason`.
- **The wrong-field non-defence is a real, open, un-mitigated risk for the future engine** — recorded
  in `CONTRACT.md` §12.5 and `TRACEABILITY.md` §5, to be re-escalated the moment matching is enabled.
  It does not arise in this build: a surveyor clicking a spot they can see is not choosing between
  candidate fields.

## Alternatives considered

**Rejected — always return the best candidate and let the user judge.** The user cannot judge. That is
what they are paying us for, and a ranked list of confidently-scored wrong answers is worse than
silence because it looks like diligence.

**Rejected — a single scalar threshold instead of a ladder.** One number cannot express "too few
inliers", "collinear inliers", "the vanishing line crosses the ROI" and "two candidates are tied".
Collapsing them loses the `DegeneracyReport`, which is the artefact that answers *"why did it reject
this obviously-correct-looking tile?"* — the most common support question in this class of product.

**Rejected — set `confidence = 100` on manual adjustment.** See §5.

**Rejected — compute a confidence for manual GCPs from click precision and GSD.** Superficially
attractive: we *have* those numbers. But they are already reported, correctly, as **accuracy in
metres**. Re-expressing them as a 0–100 "confidence" would manufacture a second number with no
independent meaning, invite comparison with future *automatic* confidences that mean something
entirely different, and **overwrite the one thing manual mode uniquely provides: the surveyor's own
judgement.**

## Related

- [ADR-015](ADR-015-defer-the-automatic-matching-engine.md) — the deferral, and the amendment above.
- [ADR-014](ADR-014-landmarks-are-user-marked.md) — provenance: every exported GCP traces to a human click.
- `CONTRACT.md` §11.6, §11.7, §12.5 · `SCOPE.md` §5.
