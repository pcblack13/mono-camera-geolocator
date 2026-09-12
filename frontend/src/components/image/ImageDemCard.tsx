/**
 * `image/ImageDemCard.tsx` — ONE photograph's own elevation source (Z).
 *
 * ★ THE PER-IMAGE OVERRIDE (1.2.6). A survey can span terrain no single DEM tile covers
 *   well, so a photograph may need a DEM the rest of the project does not use. This card
 *   is that choice, entered on the image-setup page beside the project DEM:
 *
 *     · by default the image simply uses the PROJECT DEM (nothing to do here);
 *     · attach a DEM here and THIS image overrides it — its GCPs and its auto-GCP
 *       raycast read this raster instead, while every other image keeps the project's.
 *
 * ★ The resolution rule lives on the backend (`DemService.elevation_dem_path`): image
 *   DEM if present, else project DEM. This card only sets or clears the image's own
 *   file — it never has to reason about the fallback.
 *
 * ★ Same three ways in as the project card: upload a preprocessed tile, process a raw
 *   one through the DEM page (which adopts its output for this image), or adopt one
 *   already in the library. Modeled on `ProjectDemCard` deliberately — one mental model
 *   for "set an elevation source", whether the scope is a project or a photo.
 */

import { useCallback, useEffect, useRef, useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
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
import { cameraRefForProject, cameraSettingsPath } from '../../lib/cameras/projectCamera';
import { t } from '../../i18n';

const DEM_ACCEPT = '.tif,.tiff,.asc,.dem,.img,.hgt,.xyz,.vrt,.bil,.dt2';

export interface ImageDemCardProps {
  projectId: Uuid;
  imageId: Uuid;
  /** Optional heading override; the default names the concept, not the page. */
  title?: string;
}

export function ImageDemCard({
  projectId,
  imageId,
  title = 'This image’s own elevation source (Z)',
}: ImageDemCardProps): JSX.Element {
  const navigate = useNavigate();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const notify = useNotify();
  const fileRef = useRef<HTMLInputElement>(null);

  const [dem, setDem] = useState<DemActiveResponse | null>(null);
  const [demLoading, setDemLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const refreshDem = useCallback(() => {
    let cancelled = false;
    setDemLoading(true);
    // ★ Wrapped like ProjectDemCard: a synchronous throw degrades to "no override",
    //   never a crashed setup page.
    Promise.resolve()
      .then(() => demApi.imageDem(projectId, imageId))
      .then((d) => {
        if (!cancelled) setDem(d ?? null);
      })
      .catch(() => {
        if (!cancelled) setDem(null);
      })
      .finally(() => {
        if (!cancelled) setDemLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, imageId]);

  useEffect(refreshDem, [refreshDem]);

  const onPickDem = useCallback(
    async (file: File | { path: string; name: string } | undefined) => {
      if (!file) return;
      setUploading(true);
      setError(null);
      // ★ Path picks (desktop) have no upload phase — the local API reads in place.
      setUploadPct(file instanceof File ? 0 : 100);
      try {
        const result = await demApi.uploadImageDem(projectId, imageId, file, {
          onProgress: (sent, total) => {
            if (total > 0) setUploadPct(Math.round((sent / total) * 100));
          },
        });
        notify(`This image’s elevation source set — ${result.output_crs}`, {
          severity: 'success',
        });
        // ★ Preprocessed path: definitional "no AOI / already metric" narration is
        //   dropped; only warnings that need attention are toasted.
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
    [notify, projectId, imageId, refreshDem],
  );

  const onDetach = useCallback(async () => {
    try {
      await demApi.deleteImageDem(projectId, imageId);
      notify('This image now uses the project DEM. Heights already recorded are unchanged.', {
        severity: 'info',
      });
      refreshDem();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Could not remove it.', { severity: 'error' });
    }
  }, [notify, projectId, imageId, refreshDem]);

  const hasOwnDem = dem?.active === true && dem?.image_id === imageId;

  const browseForDem = useCallback(() => {
    // ★ PATH-first on desktop: DEMs are the multi-GB case, and the bytes route fails
    //   outright above 2 GiB — the path goes to the local API.
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
  }, [onPickDem]);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
          <HeightOutlinedIcon fontSize="small" color="action" />
          <Typography variant="subtitle2">{title}</Typography>
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          Optional. Leave this alone and the photo uses the project DEM (managed in Project
          settings). Attach a DEM here only when THIS photograph needs a different surface — its
          GCPs and its Auto&nbsp;GCP raycast then read this one instead, while every other image
          keeps the project DEM.
        </Typography>

        {demLoading ? (
          <LinearProgress />
        ) : hasOwnDem ? (
          <Alert
            severity="success"
            icon={<CheckCircleOutlineIcon fontSize="inherit" />}
            action={
              <Button size="small" color="inherit" onClick={onDetach}>
                {t('Use project DEM')}
              </Button>
            }
          >
            <strong>{dem?.source_name}</strong>
            {dem?.output_crs && <> · {dem.output_crs}</>}
            {dem?.output_pixel_size_m?.[0] !== undefined && (
              <> · {dem.output_pixel_size_m[0].toFixed(2)} m/px</>
            )}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              {t('This image overrides the project DEM.')}
            </Typography>
          </Alert>
        ) : (
          <Alert severity="info">
            {t('Using the')} <strong>{t('project DEM')}</strong>
            {t('. Attach a DEM below to override it for this photo only.')}
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

        <Stack direction="row" spacing={1.5} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
          <Button variant="outlined" size="small" disabled={uploading} onClick={browseForDem}>
            {hasOwnDem ? 'Replace DEM…' : 'Upload DEM for this image…'}
          </Button>
          {/* ★ Raw tile that still needs cropping/reprojection → the full pipeline,
              which adopts its output for THIS image (via ?image=). */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<TerrainOutlinedIcon />}
            disabled={uploading}
            onClick={() => navigate(`/projects?tab=dem&project=${projectId}&image=${imageId}`)}
          >
            {t('Process new DEM…')}
          </Button>
          {/* ★ A tile processed before — adopt it straight from the library, for this
              image. */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<CollectionsOutlinedIcon />}
            disabled={uploading}
            onClick={() => setLibraryOpen(true)}
          >
            {t('From DEM library…')}
          </Button>
        </Stack>

        {/* ★ The shared DEM is the CAMERA's (2026-09-04): its settings page holds it. A
            frame with no camera behind it is sent to the server of cameras. */}
        <Button
          size="small"
          color="inherit"
          onClick={() => {
            const ref = cameraRefForProject(projectId);
            navigate(ref !== null ? cameraSettingsPath(ref) : '/cameras');
          }}
          sx={{ mt: 1, textTransform: 'none' }}
        >
          {t('Manage the camera’s DEM →')}
        </Button>

        <Dialog open={libraryOpen} onClose={() => setLibraryOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>{t('Use a processed DEM for this image')}</DialogTitle>
          <DialogContent>
            <DemLibraryPanel
              projectId={projectId}
              imageId={imageId}
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

export default ImageDemCard;
