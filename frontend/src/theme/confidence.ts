/**
 * ★★ THE CONFIDENCE COLOUR SCALE — 50-frontend.md §9.5 / §8.6, reconciled with
 *    CONTRACT.md §8.7 and SCOPE.md §5.
 *
 * This module is the SINGLE SOURCE OF TRUTH for the thresholds, the bands, the
 * colours and the redundant encodings. `theme.palette.confidence[band]` exposes the
 * colour to `sx` without an import, but the functions here remain authoritative
 * (§9.5).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * THE THREE THINGS THIS MODULE HAD TO RECONCILE, recorded so nobody "fixes" them:
 *
 * 1. ★ THE SCALE IS 0–100, NOT 0–1. 50-frontend's
 *    `CONFIDENCE_THRESHOLDS = {high: 0.85, moderate: 0.65, low: 0.40}` is **VOID**
 *    (§8.5), in favour of §8.7's **80 / 60 / 40**. The old values were a 0–1 scale
 *    compared against a 0–100 field, so `>= 0.40` was true for essentially EVERY
 *    match including rejected ones — silently enabling the compare-mode gate on
 *    results the system does not believe.
 *
 * 2. ★ MANUAL IS A SOURCE, NOT A BAND. 50-frontend §8.6.1 listed `Manual` as a
 *    fifth band meaning "human-placed; confidence not applicable", reasoning that
 *    "a human-placed point is not 'high confidence', it is a different KIND of
 *    claim". That reasoning is correct and is KEPT — but under **SCOPE.md §5 every
 *    GCP in this build is manual and every one carries a surveyor-DECLARED
 *    confidence**. If manual collapsed to one blue swatch, the mandated GCP table's
 *    Confidence column (§8.2) would convey nothing at all.
 *
 *    The resolution is that these are TWO ORTHOGONAL AXES and the theme models both:
 *      · `source`  → the encoding FAMILY. `manual` keeps 50-frontend's blue as a
 *                    PROVENANCE marker (marker outline, table chip): "a human
 *                    asserted this".
 *      · the band  → the STEP within it, carrying the declared judgement.
 *    A human's guess still cannot masquerade as an algorithmic result, because the
 *    blue says who made the claim while the band says how sure they were. Those are
 *    different sentences and the UI says both.
 *
 * 3. ★ COLOUR IS NEVER THE CARRIER. Deuteranopia and protanopia make the
 *    green/orange axis unreadable, and `moderate` (#B45309) vs `low` (#C2410C) is
 *    the weakest pair in this palette under any CVD simulation — they differ by
 *    ~2 L* and a small hue step. **Every band therefore ships a GLYPH and a
 *    PATTERN alongside its colour**, and every confidence surface pairs colour with
 *    the band's TEXT (the table adds bar length too). The text is the actual carrier
 *    of meaning; the colour is the accelerator; the glyph is what survives total
 *    achromatopsia and a greyscale print of the PDF report.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import type { ConfidenceBand, GcpSource, SurveyorConfidence } from '../types/gcp';

export type ThemeMode = 'light' | 'dark';

// ─────────────────────────────────────────────────────────────────────────────
// Thresholds — §8.7, NORMATIVE
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ On the **0–100** `GcpRead.confidence` / `MatchScores.overall_confidence` scale.
 *   `high ≥ 80` · `moderate ≥ 60` · `low ≥ 40` · `unreliable < 40`.
 *
 * ★ `low` (40) is also `LE_AI_MIN_CONFIDENCE` and the compare-mode gate: a
 *   `syncMode` of `linked`/`swipe` requires `overall_confidence >= 40`, otherwise it
 *   is forced to `none` and the control is disabled with the reason shown (§8.5).
 *   *We do not synchronize views using a homography we do not believe.*
 */
export const CONFIDENCE_THRESHOLDS = {
  high: 80,
  moderate: 60,
  low: 40,
} as const;

/** ★ `= LE_AI_MIN_CONFIDENCE`. Below this, a candidate is dropped entirely. */
export const MIN_CONFIDENCE = CONFIDENCE_THRESHOLDS.low;

/** Ordered worst → best. Useful for legends and sorts. */
export const CONFIDENCE_BANDS: readonly ConfidenceBand[] = [
  'unreliable',
  'low',
  'moderate',
  'high',
] as const;

/**
 * THE only implementation of the thresholds (§8.6.1). `score` is 0–100.
 *
 * ★ Four bands, not a continuous ramp, for the table and the markers: a continuous
 *   colour cannot be read categorically, and the surveyor's actual decision IS
 *   categorical — "do I trust this point?". The continuous ramp is reserved for the
 *   heatmap, where the *field* is the message.
 */
export function confidenceBand(score: number): ConfidenceBand {
  if (!Number.isFinite(score)) return 'unreliable';
  if (score >= CONFIDENCE_THRESHOLDS.high) return 'high';
  if (score >= CONFIDENCE_THRESHOLDS.moderate) return 'moderate';
  if (score >= CONFIDENCE_THRESHOLDS.low) return 'low';
  return 'unreliable';
}

// ─────────────────────────────────────────────────────────────────────────────
// ★ The surveyor-declared scale — SCOPE.md §5
// ─────────────────────────────────────────────────────────────────────────────

export interface SurveyorConfidenceStep {
  level: SurveyorConfidence;
  /** The radio-button label. Plain words, not numbers — this is a judgement. */
  label: string;
  /** What the surveyor is actually asserting. Rendered as the option's helper text. */
  description: string;
  /** The band this level renders as, so the table's Confidence column reads categorically. */
  band: ConfidenceBand;
  /**
   * ★ The numeric REPRESENTATIVE written to `gcps.confidence` (0–100).
   *
   *   The DB column is `F8 NOT NULL` with `ck_gcps_confidence BETWEEN 0 AND 100`,
   *   the CSV/GeoJSON/PDF exports all carry a Confidence column, and
   *   `?confidence__gte=` is a real filter — so a manual GCP must produce a number.
   *   These are the chosen representatives, each landing squarely inside its band
   *   rather than on a boundary, so a rounding change can never silently reband a
   *   surveyor's declaration.
   *
   *   ★ THIS NUMBER IS NOT A MEASUREMENT and nothing may treat it as one.
   *     `declared_confidence` is the field to read and to edit;
   *     `confidence` exists so the schema, the sort and the export keep working.
   */
  numeric: number;
}

/**
 * ★ SCOPE.md §5: "`confidence` in manual mode is a **surveyor-declared** value (a
 *   deliberate 1–5 / low-med-high judgement), **never** a computed number."
 *
 * Five steps rather than three: three collapses "I'm fairly sure" and "I'm certain"
 * into one, and that is precisely the distinction a reviewer needs when deciding
 * which points to re-verify in the field. Five is still small enough to be a
 * genuinely categorical choice rather than a disguised slider.
 */
export const SURVEYOR_CONFIDENCE_SCALE: readonly SurveyorConfidenceStep[] = [
  {
    level: 5,
    label: 'Certain',
    description: 'Unambiguous landmark, clearly resolved in both the photo and the imagery.',
    band: 'high',
    numeric: 95,
  },
  {
    level: 4,
    label: 'Confident',
    description: 'Clear correspondence; minor ambiguity about the exact pixel.',
    band: 'high',
    numeric: 85,
  },
  {
    level: 3,
    label: 'Probable',
    description: 'The landmark is identifiable, but the imagery is coarse or dated.',
    band: 'moderate',
    numeric: 70,
  },
  {
    level: 2,
    label: 'Uncertain',
    description: 'Plausible match; the surrounding features do not fully corroborate it.',
    band: 'low',
    numeric: 50,
  },
  {
    level: 1,
    label: 'Best guess',
    description: 'Placed for completeness. Not survey-grade. Verify before any use.',
    band: 'unreliable',
    numeric: 20,
  },
] as const;

const STEP_BY_LEVEL: ReadonlyMap<SurveyorConfidence, SurveyorConfidenceStep> = new Map(
  SURVEYOR_CONFIDENCE_SCALE.map((s) => [s.level, s]),
);

export function surveyorStep(level: SurveyorConfidence): SurveyorConfidenceStep {
  const step = STEP_BY_LEVEL.get(level);
  /* istanbul ignore next — unreachable while SurveyorConfidence is 1|2|3|4|5. */
  if (!step) throw new Error(`Unknown surveyor confidence level: ${String(level)}`);
  return step;
}

/** The 0–100 representative for a declared level. See `SurveyorConfidenceStep.numeric`. */
export function surveyorConfidenceToNumeric(level: SurveyorConfidence): number {
  return surveyorStep(level).numeric;
}

export function surveyorConfidenceBand(level: SurveyorConfidence): ConfidenceBand {
  return surveyorStep(level).band;
}

/**
 * ★ THE ONE FUNCTION EVERY GCP SURFACE SHOULD CALL.
 *
 * It routes on `source` so no caller has to remember the rule:
 *   - `manual`    → the surveyor's DECLARED band. Never recomputed from `confidence`
 *                   — round-tripping a judgement through a number and back is how a
 *                   declaration silently becomes a measurement.
 *   - `automatic` → the COMPUTED band from the 0–100 score.
 *
 * The `declared_confidence`-is-null-on-a-manual-GCP case cannot occur per §6, but if
 * it ever did we fall back to the numeric band rather than throwing: a GCP table
 * that refuses to render is worse than one that renders conservatively.
 */
export function gcpConfidenceBand(gcp: {
  source: GcpSource;
  confidence: number;
  declared_confidence: SurveyorConfidence | null;
}): ConfidenceBand {
  if (gcp.source === 'manual' && gcp.declared_confidence !== null) {
    return surveyorConfidenceBand(gcp.declared_confidence);
  }
  return confidenceBand(gcp.confidence);
}

// ─────────────────────────────────────────────────────────────────────────────
// The palette — 50-frontend §8.6.1, adopted verbatim
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Every token below clears **4.5:1** against its own surface (white `#FFFFFF` in
 *   light; `#1A1E25` paper in dark) — WCAG 2.2 AA 1.4.3 for the band TEXT, and
 *   comfortably past 3:1 for the graphical objects (1.4.11). Measured, not assumed:
 *
 *     light  high 5.02  ·  moderate 5.02  ·  low 5.18  ·  unreliable 6.47  ·  manual 6.70
 *     dark   high 9.59  ·  moderate ~11   ·  low 7.39  ·  unreliable 6.04  ·  manual 6.57
 *
 * ★ DESIGN NOTES, all load-bearing (§8.6.1):
 *   - **Green is never the default.** Absence of a match is GREY, not green. Green
 *     must be earned. There is deliberately no "neutral" green in this map.
 *   - **Manual is BLUE, not green.** A human-placed point is a different *kind* of
 *     claim, and conflating them would let a guess masquerade as a result.
 */
export const CONFIDENCE_COLORS: Record<ConfidenceBand, Record<ThemeMode, string>> = {
  high: { light: '#1B7F4B', dark: '#4ADE80' },
  moderate: { light: '#B45309', dark: '#FBBF24' },
  low: { light: '#C2410C', dark: '#FB923C' },
  unreliable: { light: '#B91C1C', dark: '#F87171' },
};

/** ★ The PROVENANCE accent — `source === 'manual'`. Not a band. See note 2 above. */
export const MANUAL_SOURCE_COLOR: Record<ThemeMode, string> = {
  light: '#1D4ED8',
  dark: '#60A5FA',
};

/** ★ Absence of a result. Grey, never green. */
export const NO_RESULT_COLOR: Record<ThemeMode, string> = {
  light: '#5F6672',
  dark: '#9AA3B0',
};

/**
 * ★ The contrasting outline every marker carries. Colour on imagery cannot be
 *   assumed to have a background, so the outline is what makes the contrast claim
 *   actually TRUE (§8.8 item 6).
 */
export const MARKER_OUTLINE: Record<ThemeMode, string> = {
  light: '#FFFFFF',
  dark: '#000000',
};

export function confidenceColor(band: ConfidenceBand, mode: ThemeMode): string {
  return CONFIDENCE_COLORS[band][mode];
}

// ─────────────────────────────────────────────────────────────────────────────
// ★ The redundant encodings — what makes the scale colour-blind-SAFE
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ NEVER COLOUR ALONE (§8.6.1, §8.8 item 6).
 *
 * The band's TEXT is the carrier of meaning; the colour is only an accelerator. But
 * a marker on a canvas has no room for text, so it carries a GLYPH instead — and a
 * glyph is what survives deuteranopia, protanopia, achromatopsia, a greyscale print
 * of the PDF report, and a sun-washed tablet screen in a field, which is the actual
 * operating environment.
 *
 * The shapes are chosen to be distinguishable at 12px and to encode the ordinal:
 * a circle is calm, a diamond is a caution shape, a triangle is a warning shape,
 * and a filled square with a bang reads as a stop.
 */
export interface ConfidenceEncoding {
  band: ConfidenceBand;
  /** Human label. THE carrier of meaning. Rendered next to every swatch. */
  label: string;
  /** Marker shape for the canvas + map layers. */
  glyph: 'circle' | 'diamond' | 'triangle' | 'square';
  /** A single character for dense contexts (table chip, legend key, PDF). */
  symbol: string;
  /** SVG stroke-dasharray for the marker/ring. `null` = solid. */
  dash: string | null;
  /** What this band means TO A SURVEYOR — the tooltip, verbatim from §8.6.1. */
  meaning: string;
}

export const CONFIDENCE_ENCODING: Record<ConfidenceBand, ConfidenceEncoding> = {
  high: {
    band: 'high',
    label: 'High',
    glyph: 'circle',
    symbol: '●',
    dash: null,
    meaning: 'Usable; verify by sampling.',
  },
  moderate: {
    band: 'moderate',
    label: 'Moderate',
    glyph: 'diamond',
    symbol: '◆',
    dash: null,
    meaning: 'Usable with verification.',
  },
  low: {
    band: 'low',
    label: 'Low',
    glyph: 'triangle',
    symbol: '▲',
    dash: '4 3',
    meaning: 'Not survey-grade; verify every point.',
  },
  unreliable: {
    band: 'unreliable',
    label: 'Unreliable',
    glyph: 'square',
    symbol: '■',
    // ★ Dashed by default — §8.5.3 requires low-confidence markers to be visually
    //   distinct without the user opting in.
    dash: '2 3',
    meaning: 'Treat as a guess.',
  },
};

export function confidenceLabel(band: ConfidenceBand): string {
  return CONFIDENCE_ENCODING[band].label;
}

export function confidenceMeaning(band: ConfidenceBand): string {
  return CONFIDENCE_ENCODING[band].meaning;
}

// ─────────────────────────────────────────────────────────────────────────────
// The heatmap ramp — §8.6.2 (DEFERRED surface; the ramp is theme, not engine)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Viridis-derived and **REVERSED**, so low confidence is the ATTENTION-GETTING end
 *   (yellow) rather than the pleasant end. This inversion is deliberate: a heatmap
 *   where the GOOD regions glow brightly trains the eye to look at exactly the wrong
 *   places.
 *
 * ★ Viridis is perceptually uniform AND colour-blind-safe by construction — it is
 *   monotonic in lightness, so it reads as a ramp under every CVD and in greyscale.
 *   That is why the continuous scale can be colour-only where the categorical one
 *   cannot.
 *
 * ★ A legend with numeric stops is MANDATORY and always rendered with the layer.
 *   An unlabelled heatmap is decoration.
 */
const VIRIDIS_R_STOPS: readonly [number, [number, number, number]][] = [
  [0.0, [253, 231, 37]], // #FDE725 — alarming in context
  [0.25, [94, 201, 98]], // #5EC962
  [0.5, [33, 145, 140]], // #21918C
  [0.75, [59, 82, 139]], // #3B528B
  [1.0, [68, 1, 84]], // #440154 — "nothing to see here"
];

/** Opacity over imagery (§8.6.2). */
export const HEATMAP_OPACITY = 0.55;

/**
 * `v` ∈ [0, 1] → RGBA. Linear interpolation between the viridis-reversed stops.
 *
 * ★ Out-of-range and non-finite inputs clamp rather than throw: this runs per-cell
 *   inside a canvas paint, and a throw there unmounts the map layer mid-render.
 */
export function heatmapColor(v: number): [number, number, number, number] {
  const t = Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;

  let lo = VIRIDIS_R_STOPS[0]!;
  let hi = VIRIDIS_R_STOPS[VIRIDIS_R_STOPS.length - 1]!;
  for (let i = 0; i < VIRIDIS_R_STOPS.length - 1; i += 1) {
    const a = VIRIDIS_R_STOPS[i]!;
    const b = VIRIDIS_R_STOPS[i + 1]!;
    if (t >= a[0] && t <= b[0]) {
      lo = a;
      hi = b;
      break;
    }
  }

  const span = hi[0] - lo[0];
  const f = span === 0 ? 0 : (t - lo[0]) / span;
  const mix = (i: 0 | 1 | 2): number => Math.round(lo[1][i] + (hi[1][i] - lo[1][i]) * f);

  return [mix(0), mix(1), mix(2), Math.round(HEATMAP_OPACITY * 255)];
}

export function heatmapCssColor(v: number): string {
  const [r, g, b, a] = heatmapColor(v);
  return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
}
