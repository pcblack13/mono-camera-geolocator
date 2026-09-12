/**
 * `job/JobErrorPanel.tsx` — the honest failure surface (50-frontend §8.5).
 *
 * ★ "Every failure renders through `JobErrorPanel` with a CAUSE, a CONSEQUENCE, and a
 *   specific NEXT ACTION. No bare 'Error' toasts on the critical path." This maps the
 *   typed `ErrorBody.code` to that triple; unknown codes fall back to the server's
 *   own message, which is always English and safe to display (§6.2).
 *
 * ★ SCOPE.md §4 rule 3 — a DEFERRED failure (501 / `FEATURE_DEFERRED`) is NOT an
 *   error. The feature is planned, not broken. It renders as a calm `info` explainer
 *   pointing at manual mode, never red, never a stack of retry buttons.
 *
 * ★ The `request_id` is always shown for a real error: it is the one string that
 *   connects a screenshot to a log line (§6.2).
 *
 * ★ (pure).
 */

import type { JSX, ReactNode } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { ApiErrorCode, ErrorBody } from '../../types/common';
import { t } from '../../i18n';

export interface JobErrorAction {
  label: string;
  onClick: () => void;
}

export interface JobErrorPanelProps {
  error: ErrorBody;
  onRetry?: () => void;
  /** Extra context-specific remedies (e.g. "Use Esri instead") appended after Retry. */
  actions?: JobErrorAction[];
  compact?: boolean;
}

interface Remedy {
  title: string;
  cause: string;
  consequence?: string;
  severity: 'error' | 'warning' | 'info';
}

/** The §8.5 remedy table, keyed by the stable machine code. */
const REMEDIES: Partial<Record<ApiErrorCode, Remedy>> = {
  FEATURE_DEFERRED: {
    title: 'Not enabled in this build',
    cause:
      'Automatic matching is not part of this build. Place GCPs manually — mark a landmark in the photo, then click the same spot on the map. The coordinate is a direct observation, not an inference.',
    severity: 'info',
  },
  SEARCH_HINT_REQUIRED: {
    title: 'Where should we search?',
    cause:
      'A starting area is needed before a search can run — a photo GPS tag, a box drawn on the map, or typed coordinates. A tighter area is faster and more accurate.',
    severity: 'info',
  },
  NO_ANNOTATIONS: {
    title: 'No landmarks to work with',
    cause: 'Mark at least a few landmarks in the photo first.',
    severity: 'warning',
  },
  INSUFFICIENT_ANCHORS: {
    title: 'Not enough anchor points',
    cause: 'More placed GCPs are needed for this operation.',
    severity: 'warning',
  },
  PROVIDER_NOT_CONFIGURED: {
    title: 'Provider unavailable',
    cause:
      'This imagery provider needs credentials that are not set. The keyless Esri World Imagery default always works.',
    severity: 'warning',
  },
  PROVIDER_RATE_LIMITED: {
    title: 'Provider is rate-limited',
    cause:
      'The imagery provider is throttling requests. Wait a moment, or switch to the keyless default.',
    severity: 'warning',
  },
  PROVIDER_UPSTREAM_ERROR: {
    title: 'Provider did not respond',
    cause: 'The imagery provider returned an error. Retry, or switch to the keyless Esri default.',
    severity: 'warning',
  },
  OUT_OF_COVERAGE: {
    title: 'Outside imagery coverage',
    cause:
      'The search area falls outside this provider’s coverage. Try another provider or a different area.',
    severity: 'warning',
  },
  UPLOAD_TOO_LARGE: {
    title: 'File too large',
    cause: 'This image exceeds the upload size limit. Downsample it or split the survey.',
    severity: 'error',
  },
  UNSUPPORTED_IMAGE_FORMAT: {
    title: 'Unsupported format',
    cause: 'Only JPEG, PNG, TIFF and GeoTIFF are supported.',
    severity: 'error',
  },
  EXPORT_EXPIRED: {
    title: 'Export expired',
    cause: 'This download is no longer available. Generate the export again.',
    severity: 'warning',
  },
  EXPORT_NOT_READY: {
    title: 'Export not ready',
    cause: 'The export is still being generated. It will download when it finishes.',
    severity: 'info',
  },
  TIMEOUT: {
    title: 'Timed out',
    cause: 'The job ran longer than allowed. A narrower search area or a lower zoom speeds it up.',
    severity: 'warning',
  },
  CANCELLED: {
    title: 'Cancelled',
    cause: 'This job was cancelled. No result was produced.',
    severity: 'info',
  },
  DATABASE_UNAVAILABLE: {
    title: 'Service temporarily unavailable',
    cause: 'The server could not reach its database. This is transient — retry shortly.',
    severity: 'error',
  },
  INTERNAL_ERROR: {
    title: 'Something went wrong',
    cause:
      'An unexpected error occurred on the server. If it persists, share the request ID below.',
    severity: 'error',
  },
};

export function JobErrorPanel({
  error,
  onRetry,
  actions,
  compact = false,
}: JobErrorPanelProps): JSX.Element {
  const remedy = REMEDIES[error.code];
  const severity = remedy?.severity ?? 'error';
  const isDeferred = error.code === 'FEATURE_DEFERRED' || error.status === 501;

  const title = remedy?.title ?? error.code.replace(/_/g, ' ');
  const cause = remedy?.cause ?? error.message;

  const body: ReactNode = (
    <Stack spacing={compact ? 0.75 : 1.25}>
      <Typography variant="body2">{cause}</Typography>
      {remedy?.consequence != null && (
        <Typography variant="body2" fontWeight={600}>
          {remedy.consequence}
        </Typography>
      )}
      {/* ★ A deferred feature never offers a retry — the same call would 501 again. */}
      {!isDeferred && (onRetry || (actions && actions.length > 0)) && (
        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
          {onRetry && (
            <Button size="small" variant="outlined" onClick={onRetry}>
              {t('Retry')}
            </Button>
          )}
          {actions?.map((a) => (
            <Button key={a.label} size="small" variant="text" onClick={a.onClick}>
              {a.label}
            </Button>
          ))}
        </Stack>
      )}
      {!isDeferred && (
        <Box>
          <Typography variant="mono" color="text.secondary" sx={{ fontSize: 12 }}>
            Request ID: {error.request_id}
          </Typography>
        </Box>
      )}
    </Stack>
  );

  return (
    <Alert severity={severity} sx={{ width: '100%' }}>
      <AlertTitle>{title}</AlertTitle>
      {body}
    </Alert>
  );
}

export default JobErrorPanel;
