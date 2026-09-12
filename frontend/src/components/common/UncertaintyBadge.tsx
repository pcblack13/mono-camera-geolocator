/**
 * `common/UncertaintyBadge.tsx` — the honest "do not trust this yet" marker
 * (50-frontend §8.6 / P1).
 *
 * ★ A low-confidence fix must never be rendered in the same visual language as a
 *   high-confidence one — that is a DEFECT, not a cosmetic issue (P1). This badge is
 *   the explicit uncertainty flag that rides alongside a coordinate wherever it can
 *   be shown small: table rows, card headers, the dock summary.
 *
 * ★ It appears only for `low` / `unreliable` bands (and for stale GCPs); a `high` or
 *   `moderate` fix does not get a warning, because crying wolf on a good point is its
 *   own failure. `null` render for those cases.
 *
 * ★ (pure).
 */

import type { JSX } from 'react';
import Tooltip from '@mui/material/Tooltip';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import HistoryToggleOffRoundedIcon from '@mui/icons-material/HistoryToggleOffRounded';
import { useTheme } from '@mui/material/styles';

import type { ConfidenceBand } from '../../types/gcp';
import { t } from '../../i18n';

export interface UncertaintyBadgeProps {
  band: ConfidenceBand;
  /** The point's total CE90 error radius, metres — surfaced in the tooltip. */
  errorRadiusM?: number | null;
  /** A stale GCP is uncertain for a different reason — the underlying data moved. */
  stale?: boolean;
  fontSize?: 'inherit' | 'small' | 'medium';
}

const UNRELIABLE_MESSAGE =
  'Unreliable — treat this coordinate as a guess. Not survey-grade; verify independently.';
const LOW_MESSAGE = 'Low confidence — not survey-grade. Verify this point before use.';
const STALE_MESSAGE =
  'Stale — the landmark or fit this coordinate depends on has changed. Review before use.';

export function UncertaintyBadge({
  band,
  errorRadiusM = null,
  stale = false,
  fontSize = 'small',
}: UncertaintyBadgeProps): JSX.Element | null {
  const theme = useTheme();

  if (stale) {
    return (
      <Tooltip title={STALE_MESSAGE}>
        <HistoryToggleOffRoundedIcon
          fontSize={fontSize}
          aria-label={t('Stale coordinate')}
          sx={{ color: 'text.secondary' }}
        />
      </Tooltip>
    );
  }

  if (band !== 'low' && band !== 'unreliable') return null;

  const base = band === 'unreliable' ? UNRELIABLE_MESSAGE : LOW_MESSAGE;
  const radius =
    errorRadiusM != null && Number.isFinite(errorRadiusM)
      ? ` Estimated error ±${Math.round(errorRadiusM)} m.`
      : '';

  return (
    <Tooltip title={`${base}${radius}`}>
      <WarningAmberRoundedIcon
        fontSize={fontSize}
        aria-label={band === 'unreliable' ? 'Unreliable coordinate' : 'Low-confidence coordinate'}
        sx={{ color: theme.palette.confidence[band] }}
      />
    </Tooltip>
  );
}

export default UncertaintyBadge;
