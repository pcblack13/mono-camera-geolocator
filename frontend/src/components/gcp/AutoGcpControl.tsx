/**
 * `gcp/AutoGcpControl.tsx` — Manual ⇄ Auto picking, decided where the picking happens.
 *
 * ★ THE MODE LIVES HERE NOW, not on the image-setup page. Setup describes the
 *   camera (a fact about hardware); HOW the surveyor picks points is a working
 *   decision made while looking at the photo — so it is a two-way switch in the
 *   GCP panel, flippable at any moment, in either direction.
 *
 * ★ THE AUTO SIDE STAYS LOCKED until four points are located: the solver needs
 *   four correspondences before it can estimate anything, so offering "auto" any
 *   earlier would be a lie. The tooltip counts progress (`2/4`) instead of nagging.
 *
 * ★ The flag lives on the photo's camera row and PUT is FULL-REPLACE, so flipping
 *   reads the saved camera and writes it back verbatim plus the flag (`toPutBody`).
 */

import { useCallback, type JSX } from 'react';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import AutoFixHighOutlinedIcon from '@mui/icons-material/AutoFixHighOutlined';
import PanToolAltOutlinedIcon from '@mui/icons-material/PanToolAltOutlined';

import { toPutBody } from '../../api/imageCamera';
import { useImageCamera, useSaveImageCamera } from '../../api/hooks/useImageCamera';
import { useNotify } from '../common/Notifications';
import type { Uuid } from '../../types/common';
import { t } from '../../i18n';

/** The activation threshold — the solver needs four correspondences. */
export const AUTO_GCP_REQUIRED = 4;

export interface AutoGcpControlProps {
  imageId: Uuid;
  /** Live GCP count for this image — the toolbar already has it. */
  gcpCount: number;
}

export function AutoGcpControl({ imageId, gcpCount }: AutoGcpControlProps): JSX.Element | null {
  const notify = useNotify();
  const cameraQuery = useImageCamera(imageId);
  const saveCamera = useSaveImageCamera();

  const camera = cameraQuery.data;

  const setMode = useCallback(
    (auto: boolean): void => {
      if (camera === undefined || auto === camera.auto_gcp_enabled) return;
      saveCamera.mutate(
        { imageId, body: { ...toPutBody(camera), auto_gcp_enabled: auto } },
        {
          onSuccess: () => {
            notify(
              auto
                ? 'Auto GCP picking is on — click the photo and the map point is estimated.'
                : 'Back to manual picking.',
              { severity: 'success' },
            );
          },
          onError: () => notify('Could not switch the picking mode.', { severity: 'error' }),
        },
      );
    },
    [camera, imageId, notify, saveCamera],
  );

  // Unresolved (loading or failed probe): claim nothing rather than a wrong state.
  if (camera === undefined) return null;

  const auto = camera.auto_gcp_enabled;
  const remaining = Math.max(0, AUTO_GCP_REQUIRED - gcpCount);
  const locked = !auto && remaining > 0;

  const autoTooltip = auto
    ? remaining > 0
      ? `Auto picking is on — locate ${remaining} more point${remaining === 1 ? '' : 's'} to activate the solver.`
      : 'The camera is solved from your located points; new photo clicks are estimated automatically.'
    : locked
      ? `Locate ${AUTO_GCP_REQUIRED} points manually first — ${gcpCount}/${AUTO_GCP_REQUIRED} placed.`
      : 'Solve the camera from your four points and estimate new ones automatically.';

  return (
    <ToggleButtonGroup
      exclusive
      size="small"
      value={auto ? 'auto' : 'manual'}
      onChange={(_e, mode: 'manual' | 'auto' | null) => {
        if (mode !== null) setMode(mode === 'auto');
      }}
      disabled={saveCamera.isPending}
      aria-label={t('GCP picking mode')}
    >
      <ToggleButton value="manual" aria-label={t('Manual GCP picking')} sx={{ px: 1.25 }}>
        <Tooltip title="Pick each point yourself: click the photo, then the map.">
          <PanToolAltOutlinedIcon fontSize="small" sx={{ mr: 0.5 }} />
        </Tooltip>
        {t('Manual')}
      </ToggleButton>
      {/* span: a disabled button fires no pointer events, and the tooltip must. */}
      <ToggleButton
        value="auto"
        aria-label={t('Auto GCP picking')}
        disabled={locked}
        sx={{ px: 1.25 }}
      >
        <Tooltip title={autoTooltip}>
          <AutoFixHighOutlinedIcon fontSize="small" sx={{ mr: 0.5 }} />
        </Tooltip>
        {auto || remaining === 0 ? t('Auto') : `${t('Auto')} ${gcpCount}/${AUTO_GCP_REQUIRED}`}
      </ToggleButton>
    </ToggleButtonGroup>
  );
}

export default AutoGcpControl;
