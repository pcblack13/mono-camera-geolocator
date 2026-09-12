/**
 * Confidence band mapping + colour scale — CONTRACT.md §2.5 / §8.7.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ **THIS MODULE IS A FACADE. `theme/confidence.ts` (IU-23) IS THE SOURCE OF
 *   TRUTH, and this file deliberately re-exports rather than re-implements.**
 *
 *   CONTRACT.md §2.5 lists BOTH `src/lib/confidence.ts` ("band mapping + colour
 *   scale") and `src/theme/confidence.ts` ("MUI theme · palette · confidence colour
 *   scale"), and 50-frontend.md §9.5 says the theme module "remains authoritative".
 *   Implementing the thresholds in both places would be **two sources of truth for
 *   the number that decides whether a surveyor trusts a coordinate** — the exact
 *   class of drift §8.1 deletes the case-mapping layer to prevent, and the exact
 *   way `CONFIDENCE_THRESHOLDS` came to be stated on two different scales in the
 *   first place (§8.5: 50-frontend's `{high: 0.85, ...}` against a 0–100 field,
 *   VOID).
 *
 *   So: one implementation (`theme/`), one import path for non-theme code (`lib/`).
 *   Nothing below computes anything the theme does not already own.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * ★ THE THREE CONFIDENCE SCALES, which are deliberate and MUST NOT be unified (§6.1):
 *   - `AnnotationRead.confidence`  — **0–1**, the surveyor's certainty about the
 *                                    ANNOTATION (did I mark the right pixel?).
 *   - `GcpRead.confidence`         — **0–100**, what the bands here are computed on.
 *   - `GcpRead.declared_confidence` — **1–5**, the surveyor's judgement about the
 *                                    CORRESPONDENCE (SCOPE.md §5). In this build
 *                                    every GCP has one, and it is the field to read.
 */

export type { ThemeMode, ConfidenceEncoding, SurveyorConfidenceStep } from '../theme/confidence';

export {
  // ── thresholds (§8.7: 80 / 60 / 40, on the 0–100 scale) ──
  CONFIDENCE_THRESHOLDS,
  MIN_CONFIDENCE,
  CONFIDENCE_BANDS,
  // ── band mapping ──
  confidenceBand,
  gcpConfidenceBand,
  // ── ★ SCOPE.md §5 — the surveyor-declared scale ──
  SURVEYOR_CONFIDENCE_SCALE,
  surveyorStep,
  surveyorConfidenceToNumeric,
  surveyorConfidenceBand,
  // ── colour scale ──
  CONFIDENCE_COLORS,
  MANUAL_SOURCE_COLOR,
  NO_RESULT_COLOR,
  MARKER_OUTLINE,
  confidenceColor,
  // ── the redundant encodings — NEVER colour alone (§8.8 item 6) ──
  CONFIDENCE_ENCODING,
  confidenceLabel,
  confidenceMeaning,
  // ── heatmap ramp (DEFERRED surface; the ramp is theme, not engine) ──
  HEATMAP_OPACITY,
  heatmapColor,
  heatmapCssColor,
} from '../theme/confidence';

import { MIN_CONFIDENCE } from '../theme/confidence';

/**
 * ★ §8.5 — **the compare-mode gate.** `syncMode ∈ {linked, swipe}` requires a
 *   selected match with `overall_confidence >= 40` (0–100, `= LE_AI_MIN_CONFIDENCE`);
 *   otherwise `syncMode` is forced to `none` and the control is disabled with the
 *   reason shown.
 *
 *   *We do not synchronize views using a homography we do not believe.*
 *
 * ★ The threshold is **40 on a 0–100 scale**. 50-frontend gated on `>= 0.40`, which
 *   against a 0–100 value is true for essentially EVERY match including rejected
 *   ones — silently enabling the verification affordance on results the system does
 *   not believe. IU-29 asserts this rejects `0.4`.
 *
 * ★ SCOPE.md §1: matching is DEFERRED, so in this build no `MatchResultRead` exists
 *   and this returns `false` for the only argument it can be given (`null`).
 *   `compareStore` therefore settles on `syncMode: 'none'`. The gate is kept live
 *   and honest rather than stubbed out, because re-enabling the engine must cost no
 *   caller a change (SCOPE.md §7).
 */
export function isSyncGateOpen(overall_confidence: number | null): boolean {
  if (overall_confidence === null || !Number.isFinite(overall_confidence)) return false;
  return overall_confidence >= MIN_CONFIDENCE;
}
