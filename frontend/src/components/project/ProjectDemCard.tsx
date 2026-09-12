/**
 * `project/ProjectDemCard.tsx` — the project's elevation source (Z), as one card.
 *
 * ★ EXTRACTED from `WorkspaceSetupPanel` when project setup moved to its own page:
 *   the DEM belongs with the other project-wide settings (camera intrinsics, position,
 *   tilt), entered once at `/projects/{id}/setup` — not re-asked on the way into every
 *   workspace. The panel now points here instead of carrying its own uploader.
 *
 * ★ The upload path is unchanged: `POST /projects/{id}/dem` with `reproject=false` —
 *   the file is expected to be preprocessed (cropped + projected); the server skips
 *   the warp when the raster is already in ground metres.
 */

import { useCallback, useEffect, useRef, useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import CardContent from '@mui/material/CardContent';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import HeightOutlinedIcon from '@mui/icons-material/HeightOutlined';
import CollectionsOutlinedIcon from '@mui/icons-material/CollectionsOutlined';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';

import { DemLibraryPanel } from '../dem/DemLibraryPanel';
import { demApi } from '../../api/dem';
import { useRequestSequence } from '../../lib/async';
import { classifyDemWarnings } from '../../lib/demWarnings';
import { useNotify } from '../common/Notifications';
import { ApiError, type Uuid } from '../../types/common';
import type { DemActiveResponse } from '../../types/dem';
import {
  browseNativeOrInput,
  filtersFromAccept,
  hasNativePathPicker,
  pickFilePathsNative,
} from '../../lib/nativeFilePicker';
import { t } from '../../i18n';

const DEM_ACCEPT = '.tif,.tiff,.asc,.dem,.img,.hgt,.xyz,.vrt,.bil,.dt2';

export interface ProjectDemCardProps {
  projectId: Uuid;
  /** Optional heading override; the default names the concept, not the page. */
  title?: string;
  /**
   * ★ Notified whenever the card learns whether the project has its OWN DEM (on load
   *   and after every upload/adopt/remove). Lets a host page react — e.g. Project
   *   settings hides its skip affordance once a DEM exists.
   */
  onDemChange?: (hasDem: boolean) => void;
  /**
   * ★ When given AND the project has no DEM yet, a "Skip for now" renders beside the
   *   pickers — the skip belongs to the DEM step itself, not to the page's footer,
   *   and it disappears the moment a DEM is attached (nothing left to skip).
   */
  onSkip?: () => void;
}

export function ProjectDemCard({
  projectId,
  title = 'Elevation source (Z)',
  onDemChange,
  onSkip,
}: ProjectDemCardProps): JSX.Element {
  const navigate = useNavigate();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const notify = useNotify();
  const fileRef = useRef<HTMLInputElement>(null);

  const [dem, setDem] = useState<DemActiveResponse | null>(null);
  const [demLoading, setDemLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // ★ Imperative refreshes (mount, upload, adopt, remove) can resolve out of order:
  //   a slow mount fetch landing after a fast Remove resurrected the deleted DEM.
  //   Only the newest call may write.
  const seq = useRequestSequence();
  const refreshDem = useCallback(() => {
    let cancelled = false;
    const ticket = seq.next();
    const stale = (): boolean => cancelled || !seq.isCurrent(ticket);
    setDemLoading(true);
    // ★ THE CALL IS WRAPPED, NOT JUST THE PROMISE — a synchronous throw must degrade
    //   to "elevation source unknown", not a crashed page (see WorkspaceSetupPanel's
    //   history of this exact line).
    Promise.resolve()
      .then(() => demApi.projectDem(projectId))
      .then((d) => {
        if (stale()) return;
        setDem(d ?? null);
        onDemChange?.(d?.project_id === projectId);
      })
      .catch(() => {
        if (stale()) return;
        setDem(null);
        onDemChange?.(false);
      })
      .finally(() => {
        if (!stale()) setDemLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, onDemChange, seq]);

  useEffect(refreshDem, [refreshDem]);

  const onPickDem = useCallback(
    async (file: File | { path: string; name: string } | undefined) => {
      if (!file) return;
      setUploading(true);
      setError(null);
      // ★ Path picks (desktop) have no upload phase — the local API reads the file
      //   in place; 100% flips the bar to its indeterminate "Reading the DEM…" state.
      setUploadPct(file instanceof File ? 0 : 100);
      try {
        const result = await demApi.uploadProjectDem(projectId, file, {
          onProgress: (sent, total) => {
            if (total > 0) setUploadPct(Math.round((sent / total) * 100));
          },
        });
        notify(`Elevation source set — ${result.output_crs}`, { severity: 'success' });
        // ★ THIS IS THE PREPROCESSED-DEM PATH: it deliberately does no crop and no
        //   reproject (the file is already cropped + projected). So "No AOI given" and
        //   "Reprojection was skipped" are DEFINITIONAL narration here, not problems —
        //   they used to stack into a 15-second yellow-toast stream that followed the
        //   surveyor into GCP picking. Drop them entirely; toast ONLY warnings that
        //   need attention (a clamped AOI, a nodata DEM, an adoption failure).
        const { actionable } = classifyDemWarnings(result.warnings);
        actionable.forEach((w) => notify(w, { severity: 'warning' }));
        refreshDem();
      } catch (err) {
        setError(
          err instanceof ApiError || err instanceof Error
            ? err.message
            : 'The DEM could not be read.',
        );
      } finally {
        setUploading(false);
      }
    },
    [notify, projectId, refreshDem],
  );

  const onDetach = useCallback(async () => {
    try {
      await demApi.deleteProjectDem(projectId);
      notify('Elevation source removed. Heights already recorded are unchanged.', {
        severity: 'info',
      });
      refreshDem();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Could not remove it.', { severity: 'error' });
    }
  }, [notify, projectId, refreshDem]);

  const isProjectOwned = dem?.project_id === projectId;

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
          <HeightOutlinedIcon fontSize="small" color="action" />
          <Typography variant="subtitle2">{title}</Typography>
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          {t(
            'Your own preprocessed DEM — already cropped and projected. Every GCP in this project reads its height from it, and ONLY from it: there is no shared or server-wide fallback. No DEM here means every point records no elevation. A point outside the DEM’s extent records none either — never a guess.',
          )}
        </Typography>

        {demLoading ? (
          <LinearProgress />
        ) : isProjectOwned ? (
          <Alert
            severity="success"
            icon={<CheckCircleOutlineIcon fontSize="inherit" />}
            action={
              <Button size="small" color="inherit" onClick={onDetach}>
                {t('Remove')}
              </Button>
            }
          >
            <strong>{dem?.source_name}</strong>
            {dem?.output_crs && <> · {dem.output_crs}</>}
            {dem?.output_pixel_size_m?.[0] !== undefined && (
              <> · {dem.output_pixel_size_m[0].toFixed(2)} m/px</>
            )}
          </Alert>
        ) : (
          <Alert severity="warning">
            <AlertTitle>{t('No elevation source')}</AlertTitle>
            {t('Control points in this project will record')} <strong>{t('no elevation')}</strong>.
          </Alert>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 1.5 }}>
            {error}
          </Alert>
        )}

        {uploading && (
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              {uploadPct < 100 ? `Uploading… ${uploadPct}%` : 'Reading the DEM…'}
            </Typography>
            {uploadPct < 100 ? (
              <LinearProgress variant="determinate" value={uploadPct} sx={{ mt: 0.5 }} />
            ) : (
              <LinearProgress sx={{ mt: 0.5 }} />
            )}
          </Box>
        )}

        <Stack direction="row" spacing={1.5} sx={{ mt: 2 }}>
          <Button
            variant="outlined"
            size="small"
            disabled={uploading}
            onClick={() => {
              // ★ PATH-first on desktop: DEMs are the multi-GB case, and the bytes
              //   route fails outright above 2 GiB — the path goes to the local API.
              if (hasNativePathPicker()) {
                void pickFilePathsNative(filtersFromAccept(DEM_ACCEPT, 'DEM rasters'), false).then(
                  (picked) => {
                    if (picked && picked.length > 0) void onPickDem(picked[0]);
                  },
                );
                return;
              }
              browseNativeOrInput(
                fileRef.current,
                filtersFromAccept(DEM_ACCEPT, 'DEM rasters'),
                (files) => {
                  void onPickDem(files[0]);
                },
                false,
                (skipped) => setError(skipped.map((s) => `${s.name}: ${s.reason}`).join('; ')),
              );
            }}
          >
            {isProjectOwned ? 'Replace DEM…' : 'Upload DEM…'}
          </Button>
          {/* ★ The OTHER path: a raw tile that still needs cropping/reprojection goes
              through the full pipeline, which adopts its output for this project. */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<TerrainOutlinedIcon />}
            disabled={uploading}
            onClick={() => navigate(`/projects?tab=dem&project=${projectId}`)}
          >
            {t('Process new DEM…')}
          </Button>
          {/* ★ And the THIRD: a tile processed before — for any project — adopted
              straight from the library, no re-processing. */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<CollectionsOutlinedIcon />}
            disabled={uploading}
            onClick={() => setLibraryOpen(true)}
          >
            {t('From DEM library…')}
          </Button>
          {/* ★ The skip lives WITH the choice it skips, and only while there is
              something to skip — a project that already has its DEM sees no skip
              (and none flashes while the probe is still loading). */}
          {onSkip && !demLoading && !isProjectOwned && (
            <Button size="small" color="inherit" disabled={uploading} onClick={onSkip}>
              {t('Skip for now')}
            </Button>
          )}
        </Stack>

        <Dialog open={libraryOpen} onClose={() => setLibraryOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>{t('Use a processed DEM')}</DialogTitle>
          <DialogContent>
            <DemLibraryPanel
              projectId={projectId}
              onAdopted={() => {
                setLibraryOpen(false);
                refreshDem();
              }}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setLibraryOpen(false)}>{t('Close')}</Button>
          </DialogActions>
        </Dialog>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept={DEM_ACCEPT}
          onChange={(e) => {
            void onPickDem(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </CardContent>
    </Card>
  );
}

export default ProjectDemCard;
