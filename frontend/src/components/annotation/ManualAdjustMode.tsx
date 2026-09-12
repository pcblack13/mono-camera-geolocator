/**
 * `annotation/ManualAdjustMode.tsx` — refine a placed GCP. 50-frontend.md §2.14 /
 * SCOPE.md §5.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THIS COMPONENT IS THE MANUAL-MODE READING OF §2.14, AND §8.5 VOIDS THE
 *    AUTOMATIC ONE. 50-frontend's ManualAdjustMode showed a live residual against the
 *    homography and committed to `POST /gcps/{id}/adjust` with `{imagePixel, latLon,
 *    pinned}`. In this build:
 *      - There is **no homography**, so there is **no residual** to show (`GcpRead.
 *        residual_px` is `null` in manual mode) — a residual readout would be a
 *        fabricated number, exactly what SCOPE.md forbids.
 *      - `POST /gcps/{id}/adjust`, `pinned`, and `GcpAdjustment` **do not exist**.
 *        Adjustment is `PATCH /gcps/{id}` (`useAdjustGcp`), and moving the point on
 *        the PHOTO is an annotation edit, not a GCP edit (`gcps.ts`).
 *
 *    So "adjust" here means: **re-open the correspondence** (SCOPE.md §5 — *"either
 *    endpoint can be dragged and re-committed"*). The re-opened pairing is edited on
 *    the live panes and re-committed through the same `AnnotationInspector`
 *    correspondence editor, which routes an edit to `useAdjustGcp`. This component is
 *    the entry point plus the two metadata-only actions that need no re-observation:
 *    the export-inclusion toggle and the reset-to-original.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Typography from '@mui/material/Typography';
import EditLocationAltIcon from '@mui/icons-material/EditLocationAlt';
import RestartAltIcon from '@mui/icons-material/RestartAlt';

import type { Uuid } from '../../types/common';
import { useGcp } from '../../api/hooks/useGcps';
import { useAdjustGcp, useResetGcp } from '../../api/hooks/useAdjustGcp';
import { useCorrespondenceStore } from '../../store/correspondenceStore';
import { t } from '../../i18n';

export interface ManualAdjustModeProps {
  gcpId: Uuid;
  imageId: Uuid;
  /** The annotation this GCP links to, if any — carried into the re-opened pairing. */
  landmarkClientId?: string | null;
  onClose: () => void;
}

export function ManualAdjustMode({
  gcpId,
  imageId,
  landmarkClientId = null,
  onClose,
}: ManualAdjustModeProps): JSX.Element {
  // Reading the GCP registers its ETag — required by the `If-Match` on adjust/reset.
  const { data: gcp, isLoading } = useGcp(gcpId);
  const reopen = useCorrespondenceStore((s) => s.reopen);
  const adjust = useAdjustGcp(imageId);
  const reset = useResetGcp(imageId);

  if (isLoading || !gcp) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t('Loading ground control point…')}
      </Typography>
    );
  }

  const reopenForAdjust = (): void => {
    reopen({
      image_id: imageId,
      gcp_id: gcpId,
      image_px: gcp.image_px,
      lat_lon: { lat: gcp.lat, lon: gcp.lon },
      declared_confidence: gcp.declared_confidence,
      landmark_client_id: landmarkClientId,
      note: gcp.adjustment_note,
    });
    onClose();
  };

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2">{gcp.code ?? 'Ground control point'}</Typography>

      <Alert severity="info" variant="outlined" sx={{ py: 0.5 }}>
        {t(
          'This is a direct observation — there is no match to re-fit. To move it, re-open the pairing and drag either endpoint.',
        )}
      </Alert>

      <Button variant="contained" startIcon={<EditLocationAltIcon />} onClick={reopenForAdjust}>
        {t('Re-open to adjust')}
      </Button>

      <FormControlLabel
        control={
          <Switch
            checked={gcp.is_included_in_export}
            onChange={(e) =>
              adjust.mutate({ gcpId, body: { is_included_in_export: e.target.checked } })
            }
          />
        }
        label={t('Include in export')}
      />

      {gcp.manually_adjusted && (
        <Button
          variant="text"
          color="inherit"
          startIcon={<RestartAltIcon />}
          onClick={() => reset.mutate({ gcpId })}
        >
          {t('Reset to original')}
        </Button>
      )}
    </Stack>
  );
}
