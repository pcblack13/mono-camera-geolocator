/**
 * `common/ConfidenceChip.tsx` — the categorical confidence badge (50-frontend §8.6).
 *
 * ★ Colour + TEXT, never colour alone (§8.8 item 6): the band label is the actual
 *   carrier of meaning and the colour is the accelerator. Deuteranopia makes the
 *   green/orange axis unreadable, so the label must stand on its own.
 *
 * ★ MANUAL IS A DIFFERENT KIND OF CLAIM, not a band. SCOPE.md §5 / §8.6: a
 *   human-placed point is not "high confidence" — it is a direct observation, and
 *   conflating them would let a guess masquerade as an algorithmic result. When
 *   `source === 'manual'` this renders the surveyor-declared judgement in the manual
 *   (blue) accent, NOT a computed band.
 *
 * ★ (pure). The single source of truth for chip rendering — no confidence colour is
 *   computed inline anywhere else.
 */

import type { JSX } from 'react';
import Chip from '@mui/material/Chip';
import { alpha, useTheme } from '@mui/material/styles';

import {
  confidenceBand,
  confidenceLabel,
  surveyorConfidenceBand,
  surveyorStep,
} from '../../lib/confidence';
import type { ConfidenceBand, GcpSource, SurveyorConfidence } from '../../types/gcp';

export interface ConfidenceChipProps {
  /** 0–100. Used when `source !== 'manual'` (or when no declared judgement is given). */
  value?: number;
  /** Overrides `value`'s derived band. */
  band?: ConfidenceBand;
  /** ★ SCOPE.md §5. `manual` swaps the whole rendering to the declared-judgement form. */
  source?: GcpSource;
  /** The surveyor's 1–5 judgement — the field to read when `source === 'manual'`. */
  declaredConfidence?: SurveyorConfidence | null;
  size?: 'small' | 'medium';
}

export function ConfidenceChip({
  value,
  band,
  source = 'automatic',
  declaredConfidence = null,
  size = 'small',
}: ConfidenceChipProps): JSX.Element {
  const theme = useTheme();

  // ── Manual: the declared judgement, in the provenance accent ────────────────
  if (source === 'manual' && declaredConfidence !== null) {
    const step = surveyorStep(declaredConfidence);
    const color = theme.palette.confidence.manual;
    return (
      <Chip
        size={size}
        label={step.label}
        variant="outlined"
        sx={{
          color,
          borderColor: alpha(color, 0.5),
          bgcolor: alpha(color, 0.1),
          fontWeight: 600,
        }}
        title={`Surveyor-declared confidence: ${step.label}. Human judgement, not a measurement.`}
      />
    );
  }

  // ── Computed band (automatic result, or a manual GCP without a declared level) ─
  const resolvedBand: ConfidenceBand =
    band ??
    (source === 'manual' && declaredConfidence !== null
      ? surveyorConfidenceBand(declaredConfidence)
      : confidenceBand(Number.isFinite(value ?? NaN) ? (value as number) : 0));
  const color = theme.palette.confidence[resolvedBand];

  return (
    <Chip
      size={size}
      label={confidenceLabel(resolvedBand)}
      variant="outlined"
      sx={{
        color,
        borderColor: alpha(color, 0.5),
        bgcolor: alpha(color, 0.1),
        fontWeight: 600,
      }}
    />
  );
}

export default ConfidenceChip;
