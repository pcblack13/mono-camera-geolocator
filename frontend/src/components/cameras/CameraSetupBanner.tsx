/**
 * `cameras/CameraSetupBanner.tsx` — the camera pipeline's strip over the GCP editor.
 *
 * ★ THE EDITOR IS A STEP OF THE CAMERA'S SETTINGS (2026-09-04, owner ask). When
 *   the editor is opened FROM a camera's settings page (`?camera=<id>`), this
 *   strip keeps the operator inside that pipeline: it names the camera, counts the
 *   control points placed against the four the pose solve needs, builds the lookup
 *   table right here once they are placed, and offers the way back — "Back to
 *   camera settings". The bundle jumps back with them: the build hook writes the
 *   site name onto the camera row the moment the build succeeds.
 *
 * ★ Honest about readiness. The build button is enabled only when the frame has
 *   four points and the camera's project has a DEM; otherwise the strip says
 *   which is missing rather than letting the server refuse.
 *
 * ★ A DRAFT camera (`?camera=new`, one not yet added to the server) is served the
 *   same way from `cameraDraftStore`: the strip names the draft, the build hands
 *   the bundle's site name back to the draft, and the way back is `/cameras/new`.
 */

import { type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import GridOnOutlinedIcon from '@mui/icons-material/GridOnOutlined';
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined';

import { useGcps, useProjectDem } from '../../api/hooks';
import { useImageCamera } from '../../api/hooks/useImageCamera';
import { useCameraLutBuild } from '../../hooks/useCameraLutBuild';
import { t } from '../../i18n';
import { useCameraDraftStore } from '../../store/cameraDraftStore';
import { selectCameraById, useCameraRegistryStore } from '../../store/cameraRegistryStore';
import type { Uuid } from '../../types/common';

/** The pose solve needs four located points before a table can be built. */
export const MIN_GCPS_FOR_LUT = 4;

/** The `?camera=` value that means "the draft on /cameras/new". */
export const DRAFT_CAMERA_ID = 'new';

export interface CameraSetupBannerProps {
  /** A registered camera's id, or `DRAFT_CAMERA_ID` for the draft. */
  cameraId: string;
  projectId: Uuid;
  imageId: Uuid;
}

export function CameraSetupBanner({
  cameraId,
  projectId,
  imageId,
}: CameraSetupBannerProps): JSX.Element | null {
  const navigate = useNavigate();
  const isDraft = cameraId === DRAFT_CAMERA_ID;
  const registered = useCameraRegistryStore(selectCameraById(cameraId));
  const draft = useCameraDraftStore((s) => s.draft);
  const patchDraft = useCameraDraftStore((s) => s.patch);
  // ★ The draft counts as "the camera" only while it is the one this editor was
  //   opened for — its frame is this image.
  const camera = isDraft
    ? draft.frame_image_id === imageId
      ? { name: draft.name.trim() || t('New camera'), lut_site: draft.lut_site ?? undefined }
      : undefined
    : registered;
  const gcps = useGcps(imageId);
  const dem = useProjectDem(projectId);
  const station = useImageCamera(imageId);
  const build = useCameraLutBuild({
    cameraId: isDraft ? null : cameraId,
    imageId,
    siteName: camera?.name ?? '',
    onBuilt: (site) => {
      if (isDraft) patchDraft({ lut_site: site });
    },
  });

  if (camera === undefined) return null;

  const placed = gcps.data?.total ?? 0;
  // ★ `GET /projects/{id}/dem` answers for THIS project only — `active` is the fact.
  const hasDem = dem.data?.active === true;
  // ★ GEO-DRIFT C2: a station in no-calibration mode with a field of view has what
  //   the solves need — the focal is recovered from the control points.
  const hasIntrinsics =
    station.data?.configured === true &&
    ((station.data.fx !== null && station.data.fy !== null) ||
      // ★ A blank field of view is fine (2026-09-09): the solve starts from a
      //   default seed. The mode alone is the intrinsics.
      station.data.no_calibration === true);
  const enoughPoints = placed >= MIN_GCPS_FOR_LUT;
  const hasTable = build.builtSite !== null || Boolean(camera.lut_site);
  // ★ FOUR POINTS UNLOCK THE BUILD (owner ask); what else is missing is NAMED, and
  //   the server refuses with the exact reason if it must.
  const ready = enoughPoints && !build.building;
  const missing: string[] = [];
  if (!enoughPoints) {
    missing.push(`${MIN_GCPS_FOR_LUT - placed} ${t('more control point(s)')}`);
  }
  if (dem.isSuccess && !hasDem) missing.push(t('a DEM on the camera'));
  if (station.isSuccess && !hasIntrinsics)
    missing.push(
      t('calibration on the camera (fx, fy — or no-calibration mode)'),
    );

  const backToSettings = (): void =>
    navigate(isDraft ? '/cameras/new' : `/cameras/${cameraId}/settings`);
  const progress = build.status;
  const pct =
    progress !== null && progress.progress_total > 0
      ? Math.round((100 * progress.progress_done) / progress.progress_total)
      : null;

  return (
    <Box
      role="region"
      aria-label={t('Camera setup')}
      sx={{
        flexShrink: 0,
        px: 2,
        py: 1,
        borderBottom: '1px solid var(--hairline)',
        bgcolor: 'var(--accent-quiet)',
      }}
    >
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.5}
        alignItems={{ xs: 'stretch', md: 'center' }}
      >
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          <VideocamOutlinedIcon sx={{ color: 'var(--accent)' }} fontSize="small" />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle2" noWrap sx={{ lineHeight: 1.2 }}>
              {t('Setting up camera')} “{camera.name}”
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              <Box component="span" className="le-mono">
                {placed}/{MIN_GCPS_FOR_LUT}
              </Box>{' '}
              {t('control points placed')}
              {hasTable && (
                <>
                  {' · '}
                  <CheckCircleOutlineIcon sx={{ fontSize: 12, verticalAlign: '-2px' }} />{' '}
                  {t('lookup table')}:{' '}
                  <Box component="span" className="le-mono">
                    {build.builtSite ?? camera.lut_site}
                  </Box>
                </>
              )}
              {!hasTable && missing.length > 0 && !build.building && (
                <>
                  {' · '}
                  {t('still needed')}: {missing.join(', ')}
                </>
              )}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          <Button
            size="small"
            variant={hasTable ? 'outlined' : 'contained'}
            startIcon={
              build.building ? (
                <CircularProgress size={14} color="inherit" />
              ) : (
                <GridOnOutlinedIcon />
              )
            }
            disabled={!ready}
            onClick={build.start}
          >
            {build.building
              ? t('Building…')
              : hasTable
                ? t('Rebuild lookup table')
                : t('Build lookup table')}
          </Button>
          <Button
            size="small"
            variant={hasTable ? 'contained' : 'outlined'}
            startIcon={<ArrowBackIcon />}
            onClick={backToSettings}
          >
            {hasTable ? t('Return with the lookup table') : t('Back to camera settings')}
          </Button>
        </Stack>
      </Stack>
      {build.building && (
        <LinearProgress
          variant={pct === null ? 'indeterminate' : 'determinate'}
          value={pct ?? undefined}
          sx={{ mt: 1, height: 3, borderRadius: 2 }}
          aria-label={t('Building the lookup table')}
        />
      )}
      {build.error !== null && (
        <Alert severity="error" variant="outlined" sx={{ mt: 1, py: 0 }}>
          {build.error}
        </Alert>
      )}
    </Box>
  );
}
