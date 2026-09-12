/**
 * `pages/DemPage.tsx` — Digital Elevation Model processing.
 *
 * A linear workflow: UPLOAD a DEM → CONFIGURE the crop and projection → PROCESS →
 * EXPORT a GeoTIFF (.tif), wired to `gis.dem` through `/api/v1/dem/*`.
 *
 * ★ THE PAGE SHOWS WHERE YOU ARE. A stage strip across the top — Upload · Configure
 *   · Process · Export — is DERIVED from the real state (a file chosen, a run in
 *   flight, a result in hand), never from a click counter; pressing a stage scrolls
 *   to its card. The target project sits in the header as a compact card that turns
 *   amber when no project is chosen, instead of a banner that shouted at every visit.
 *
 * ★ THE PARAMETERS ARE THE ALGORITHM'S, NOT A GUESS. The scaffold this replaces offered
 *   `cellSize`, `fillSinks` and a `smoothing` level; the pipeline implements none of
 *   those, so none of them are here. What the pipeline DOES implement is exactly what is
 *   exposed: an AOI with a tolerance (stage 1), and a metric reprojection with a
 *   resampling kernel (stage 2). A control that quietly does nothing is the same class
 *   of dishonesty as a fabricated confidence score.
 *
 * ★ WHY THE AOI IS OPTIONAL AND THE REPROJECTION IS ON BY DEFAULT. Cropping is a
 *   convenience — a DEM already clipped to the survey area needs none. Reprojection is
 *   the point: `(λ, φ, H) → (E, N, H)`. A DEM left in degrees cannot be measured on,
 *   because a degree of longitude is 111 km at the equator and 64 km at 55°N. The
 *   pipeline skips the stage by itself when the input is already in ground metres,
 *   rather than resampling a raster into the CRS it is already in.
 */

import {
  useCallback,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type JSX,
  type ReactNode,
} from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArrowBackOutlinedIcon from '@mui/icons-material/ArrowBackOutlined';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import CropFreeOutlinedIcon from '@mui/icons-material/CropFreeOutlined';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined';
import MyLocationOutlinedIcon from '@mui/icons-material/MyLocationOutlined';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined';
import RestartAltOutlinedIcon from '@mui/icons-material/RestartAltOutlined';
import SkipNextOutlinedIcon from '@mui/icons-material/SkipNextOutlined';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';

import { demApi } from '../api/dem';
import { downloadBlob } from '../lib/download';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { useProject, useProjects } from '../api/hooks/useProjects';
import { useImages } from '../api/hooks/useImages';
import {
  DEFAULT_PARAMS,
  EMPTY_CORNERS,
  useDemFormStore,
  type AoiMode,
  type CornerInput,
  type DemParams,
} from '../store/demFormStore';
import { parseDemParams, DemParamsParseError } from '../lib/demParamsImport';
import { classifyDemWarnings } from '../lib/demWarnings';
import { DemLibraryPanel } from '../components/dem/DemLibraryPanel';
import { useNavHistoryStore } from '../store/navHistoryStore';
import { useNotify } from '../components/common/Notifications';
import { asUuid } from '../types/common';
import { ApiError } from '../types/common';
import type { DemPoint, DemProcessResponse } from '../types/dem';
import {
  browseNativeOrInput,
  filtersFromAccept,
  hasNativePathPicker,
  pickFilePathsNative,
} from '../lib/nativeFilePicker';
import { cameraRefForProject, cameraSettingsPath } from '../lib/cameras/projectCamera';
import { t } from '../i18n';
import { ErrorState, ProgressStage } from '../components/ui';

/** DEM raster formats the backend accepts. Kept in step with `_ACCEPTED_SUFFIXES`. */
const ACCEPTED_EXTENSIONS = [
  '.tif',
  '.tiff',
  '.asc',
  '.dem',
  '.img',
  '.hgt',
  '.xyz',
  '.vrt',
  '.bil',
  '.dt2',
] as const;
const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(',');

/**
 * ★ Output CRS choices. EPSG:3857 is deliberately ABSENT and EPSG:4326 is absent too —
 *   the backend refuses both for this stage, and offering a choice the server rejects is
 *   a trap. Web Mercator's "metres" are inflated by 1/cos(latitude) (41% at 45°N, 74% at
 *   55°N), so a DEM reprojected into it yields wrong slopes, wrong distances and wrong
 *   volumes while looking entirely normal. `null` = let the server pick the UTM zone.
 */
const SRID_OPTIONS: { value: number | null; label: string; hint: string }[] = [
  {
    value: null,
    label: 'Automatic (UTM zone under the DEM)',
    hint: 'Recommended — picks the correct zone from the data',
  },
  { value: 32636, label: 'UTM 36N (EPSG:32636)', hint: 'WGS 84 / UTM zone 36N' },
  { value: 32637, label: 'UTM 37N (EPSG:32637)', hint: 'WGS 84 / UTM zone 37N' },
  { value: 32638, label: 'UTM 38N (EPSG:32638)', hint: 'WGS 84 / UTM zone 38N' },
];

/**
 * ★ Resampling and output cell size are NOT surfaced. The server uses `bilinear` — the
 *   right kernel for a continuous elevation surface — and preserves the source
 *   resolution. Both remain in the API because they are part of the algorithm; neither
 *   is a decision this workflow needs a surveyor to make.
 */

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/**
 * ★ The UTM zone a camera station falls in — the reason the position is asked for.
 *
 *   Mirrors `gis.crs.utm_epsg_for`, INCLUDING its two guards, because a zone shown here
 *   that disagrees with the one the server uses is worse than showing nothing:
 *     · clamped to 60, so lon 180 does not overflow to zone 61 (EPSG:32661 is UPS
 *       North, a polar stereographic CRS, not a UTM zone at all);
 *     · null beyond |lat| 84, where UTM is simply undefined.
 *   Returned as a display string; the server still derives the authoritative value.
 */
function utmEpsgFor(lat: number, lon: number): string | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 84) return null;
  const wrapped = lon >= -180 && lon <= 180 ? lon : ((lon + 180) % 360) - 180;
  const zone = Math.max(1, Math.min(Math.floor((wrapped + 180) / 6) + 1, 60));
  return `EPSG:${(lat >= 0 ? 32600 : 32700) + zone}`;
}

function hasAcceptedExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export interface DemPageProps {
  /** Rendered inside the Workspace rail (no page chrome of its own). */
  embedded?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// The stage strip — derived from the real state
// ─────────────────────────────────────────────────────────────────────────────

type StripState = 'done' | 'current' | 'running' | 'failed' | 'waiting';

interface StripStage {
  id: string;
  label: string;
  state: StripState;
}

/** Which of the four stages is where, from what has actually happened. */
export function deriveStages(
  hasFile: boolean,
  stage: 'idle' | 'ready' | 'processing' | 'done' | 'error',
  exported: boolean,
): StripStage[] {
  const processState: StripState =
    stage === 'processing'
      ? 'running'
      : stage === 'done'
        ? 'done'
        : stage === 'error'
          ? 'failed'
          : hasFile
            ? 'waiting'
            : 'waiting';
  return [
    { id: 'dem-stage-upload', label: 'Upload', state: hasFile ? 'done' : 'current' },
    {
      id: 'dem-stage-configure',
      label: 'Configure',
      state: !hasFile ? 'waiting' : stage === 'ready' || stage === 'error' ? 'current' : 'done',
    },
    {
      id: 'dem-stage-process',
      label: 'Process',
      state: processState === 'waiting' && hasFile ? 'waiting' : processState,
    },
    {
      id: 'dem-stage-export',
      label: 'Export',
      state: exported ? 'done' : stage === 'done' ? 'current' : 'waiting',
    },
  ];
}

function StageStrip({ stages }: { stages: readonly StripStage[] }): JSX.Element {
  const go = (id: string): void => {
    const el = document.getElementById(id);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };
  return (
    <Box
      component="ol"
      aria-label={t('Stages')}
      className="le-chrome"
      sx={{
        display: 'flex',
        alignItems: 'center',
        listStyle: 'none',
        m: 0,
        p: 0,
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        overflowX: 'auto',
      }}
    >
      {stages.map((s, i) => {
        const active = s.state === 'current' || s.state === 'running';
        const done = s.state === 'done';
        const failed = s.state === 'failed';
        return (
          <Box
            component="li"
            key={s.id}
            aria-current={active ? 'step' : undefined}
            sx={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}
          >
            <Box
              component="button"
              type="button"
              onClick={() => go(s.id)}
              sx={{
                'all': 'unset',
                'boxSizing': 'border-box',
                'display': 'flex',
                'alignItems': 'center',
                'gap': 1.25,
                'flex': 1,
                'minWidth': 0,
                'px': 2,
                'py': 1.25,
                'cursor': 'pointer',
                'borderRadius': 'var(--radius-md)',
                '&:hover': { bgcolor: 'action.hover' },
                '&:focus-visible': { boxShadow: 'var(--focus-ring)' },
              }}
            >
              <Box
                className="le-mono"
                aria-hidden
                sx={{
                  width: 26,
                  height: 26,
                  flexShrink: 0,
                  display: 'grid',
                  placeItems: 'center',
                  borderRadius: '50%',
                  fontSize: 11,
                  fontWeight: 600,
                  border: '2px solid',
                  borderColor: done
                    ? 'var(--accent)'
                    : failed
                      ? 'var(--status-error)'
                      : active
                        ? 'var(--accent)'
                        : 'var(--hairline-strong)',
                  bgcolor: done ? 'var(--accent)' : 'transparent',
                  color: done
                    ? 'var(--accent-contrast)'
                    : failed
                      ? 'var(--status-error)'
                      : active
                        ? 'var(--accent)'
                        : 'text.disabled',
                }}
              >
                {done ? (
                  <CheckRoundedIcon sx={{ fontSize: 15 }} />
                ) : s.state === 'running' ? (
                  <CircularProgress size={12} thickness={5} color="inherit" />
                ) : (
                  i + 1
                )}
              </Box>
              <Box sx={{ minWidth: 0 }}>
                <Typography
                  noWrap
                  sx={{
                    fontSize: 13,
                    fontWeight: active ? 600 : 500,
                    color: active || done ? 'text.primary' : 'text.secondary',
                    lineHeight: 1.2,
                  }}
                >
                  {t(s.label)}
                </Typography>
                <Typography sx={{ fontSize: 11, color: 'text.secondary', lineHeight: 1.2 }} noWrap>
                  {s.state === 'done'
                    ? t('done')
                    : s.state === 'running'
                      ? t('running')
                      : s.state === 'failed'
                        ? t('failed')
                        : s.state === 'current'
                          ? t('now')
                          : t('later')}
                </Typography>
              </Box>
            </Box>
            {i < stages.length - 1 && (
              <Box
                aria-hidden
                sx={{
                  width: 24,
                  height: 2,
                  flexShrink: 0,
                  bgcolor: done ? 'var(--accent)' : 'var(--hairline-strong)',
                  mx: 0.5,
                  display: { xs: 'none', sm: 'block' },
                }}
              />
            )}
          </Box>
        );
      })}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page furniture
// ─────────────────────────────────────────────────────────────────────────────

function StepCard({
  id,
  index,
  title,
  hint,
  action,
  children,
  muted = false,
}: {
  id: string;
  index: number;
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
  muted?: boolean;
}): JSX.Element {
  return (
    <Box
      id={id}
      component="section"
      aria-labelledby={`${id}-title`}
      sx={{
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        opacity: muted ? 0.6 : 1,
        transition: 'opacity var(--dur-normal) var(--ease-standard)',
        scrollMarginTop: 16,
      }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ px: 2.5, py: 1.5, borderBottom: '1px solid var(--hairline)' }}
      >
        <Box
          className="le-mono"
          aria-hidden
          sx={{
            width: 26,
            height: 26,
            display: 'grid',
            placeItems: 'center',
            borderRadius: '50%',
            fontSize: 12,
            fontWeight: 600,
            bgcolor: 'var(--accent-quiet)',
            color: 'var(--accent)',
            flexShrink: 0,
          }}
        >
          {index}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            id={`${id}-title`}
            variant="subtitle1"
            sx={{ fontWeight: 600, lineHeight: 1.2 }}
          >
            {title}
          </Typography>
          {hint !== undefined && (
            <Typography variant="caption" color="text.secondary">
              {hint}
            </Typography>
          )}
        </Box>
        {action}
      </Stack>
      <Box sx={{ p: 2.5 }}>{children}</Box>
    </Box>
  );
}

function StatTile({
  label,
  value,
  unit,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: 'warn';
}): JSX.Element {
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-inset)',
        minWidth: 0,
      }}
    >
      <Typography
        sx={{
          fontSize: 11,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'text.secondary',
          lineHeight: 1.2,
          mb: 0.5,
        }}
      >
        {label}
      </Typography>
      <Typography
        className="le-mono"
        sx={{
          fontSize: 16,
          fontWeight: 600,
          lineHeight: 1.25,
          color: tone === 'warn' ? 'var(--status-warn)' : 'text.primary',
          wordBreak: 'break-word',
        }}
      >
        {value}
        {unit !== undefined && (
          <Typography
            component="span"
            className="le-mono"
            sx={{ fontSize: 11, color: 'text.secondary', ml: 0.5 }}
          >
            {unit}
          </Typography>
        )}
      </Typography>
      {sub !== undefined && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
          {sub}
        </Typography>
      )}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

export function DemPage({ embedded = false }: DemPageProps = {}): JSX.Element {
  const notify = useNotify();
  const inputRef = useRef<HTMLInputElement>(null);

  // ★ PROJECT MODE. `?project=<id>` (the image-setup page's "Process new DEM…"
  //   button) makes this run FOR that project: the processed output is adopted as
  //   its elevation source, exactly as if the result had been exported and then
  //   uploaded on the setup page — minus the round trip.
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const targetProjectId = searchParams.get('project');
  // ★ PER-IMAGE MODE (1.2.6). `?image=<id>` (with `?project=`) narrows the run to ONE
  //   photograph: the output becomes that image's own DEM, overriding the project DEM
  //   for it alone. Omitted ⇒ the whole project, exactly as before.
  const targetImageId = searchParams.get('image');
  // Bumped after each successful run so the library panel shows the new output.
  const [libraryRefresh, setLibraryRefresh] = useState(0);
  const targetProject = useProject(targetProjectId !== null ? asUuid(targetProjectId) : null);
  // The project's images, to populate the "Apply to" selector when a project is chosen.
  const projectImages = useImages(targetProjectId !== null ? asUuid(targetProjectId) : null);
  const selectedImageName =
    targetImageId !== null
      ? (projectImages.data?.items.find((img) => img.id === targetImageId)?.filename ?? null)
      : null;
  // ★ Without a target project the pipeline still runs, but its output feeds no
  //   project and Auto GCP keeps refusing ("this project has no DEM") — the exact
  //   trap a field user hit on 1.2.1. Offer the choice HERE instead of relying on
  //   arriving through a deep link.
  const projectChoices = useProjects({});
  const chooseProject = useCallback(
    (id: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === '') next.delete('project');
          else next.set('project', id);
          // ★ An image belongs to a project — changing (or clearing) the project drops
          //   any per-image target, so we never send an image_id from another project.
          next.delete('image');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /** Narrow the run to one image, or back to the whole project (`''`). */
  const chooseImage = useCallback(
    (id: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === '') next.delete('image');
          else next.set('image', id);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // ★ Form state lives in a STORE, not useState: the Workspace rail unmounts this
  //   page on every tab switch, and local state threw away everything a surveyor
  //   had typed (file, camera position, radius) — field report on 1.2.1.
  const {
    file,
    setFile,
    params,
    setParams,
    stage,
    setStage,
    uploadPct,
    setUploadPct,
    result,
    setResult,
    errorMessage,
    setErrorMessage,
  } = useDemFormStore();
  const [dragging, setDragging] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [exported, setExported] = useState(false);

  const setParam = useCallback(<K extends keyof DemParams>(key: K, value: DemParams[K]) => {
    setParams((prev) => ({ ...prev, [key]: value }));
  }, []);

  const setCorner = useCallback((index: number, field: keyof CornerInput, value: string) => {
    setParams((prev) => ({
      ...prev,
      corners: prev.corners.map((c, i) => (i === index ? { ...c, [field]: value } : c)),
    }));
  }, []);

  // ── import camera / AOI from a file (CSV, JSON, GeoJSON) ───────────────────
  const paramsInputRef = useRef<HTMLInputElement>(null);
  const onImportParams = useCallback(
    (importFile: File | undefined): void => {
      if (!importFile) return;
      void importFile.text().then((text) => {
        let parsed;
        try {
          parsed = parseDemParams(importFile.name, text);
        } catch (err) {
          notify(err instanceof DemParamsParseError ? err.message : 'Could not read that file.', {
            severity: 'error',
          });
          return;
        }
        setParams((prev) => {
          const next = { ...prev };
          if (parsed.camera) {
            next.aoiMode = 'camera';
            next.cameraLat = String(parsed.camera.lat);
            next.cameraLon = String(parsed.camera.lon);
            if (parsed.camera.radius_m !== undefined) next.radiusM = String(parsed.camera.radius_m);
          } else if (parsed.corners) {
            next.aoiMode = 'corners';
            next.corners = EMPTY_CORNERS.map((empty, i) =>
              parsed.corners![i]
                ? { lat: String(parsed.corners![i].lat), lon: String(parsed.corners![i].lon) }
                : empty,
            );
          }
          if (parsed.tolerance_pct !== undefined) next.tolerancePct = parsed.tolerance_pct;
          if (parsed.target_srid !== undefined) next.targetSrid = parsed.target_srid;
          return next;
        });
        notify(
          `Imported ${parsed.camera ? 'camera position' : 'AOI corners'} from ${importFile.name}.`,
          { severity: 'success' },
        );
        parsed.warnings.forEach((w) => notify(w, { severity: 'warning' }));
      });
    },
    [notify, setParams],
  );

  const browseParams = useCallback(() => {
    browseNativeOrInput(
      paramsInputRef.current,
      filtersFromAccept('.csv,.txt,.json,.geojson', 'DEM parameters'),
      (files) => onImportParams(files[0]),
    );
  }, [onImportParams]);

  const acceptFile = useCallback(
    (candidate: File | undefined) => {
      if (!candidate) return;
      if (!hasAcceptedExtension(candidate.name)) {
        notify(`Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(', ')}`, {
          severity: 'error',
        });
        return;
      }
      setFile({ kind: 'file', name: candidate.name, size: candidate.size, file: candidate });
      setStage('ready');
      setUploadPct(0);
      setResult(null);
      setErrorMessage(null);
      setExported(false);
    },
    [notify],
  );

  const acceptPath = useCallback(
    (picked: { name: string; path: string; size: number } | undefined) => {
      if (!picked) return;
      if (!hasAcceptedExtension(picked.name)) {
        notify(`Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(', ')}`, {
          severity: 'error',
        });
        return;
      }
      setFile({ kind: 'path', name: picked.name, size: picked.size, path: picked.path });
      setStage('ready');
      setUploadPct(0);
      setResult(null);
      setErrorMessage(null);
      setExported(false);
    },
    [notify],
  );

  // ★ Native-first: the in-page GTK chooser crashes the desktop app (see
  //   lib/nativeFilePicker); the browser input remains the web fallback.
  //   PATH-first on desktop: a DEM tile is routinely multiple GB, and the bytes
  //   route hard-fails above 2 GiB (this was the "3.8 GB tif does nothing" bug) —
  //   the path is handed to the LOCAL API, which streams the file from disk.
  const browseDem = useCallback(() => {
    if (hasNativePathPicker()) {
      void pickFilePathsNative(filtersFromAccept(ACCEPT_ATTR, 'DEM rasters'), false).then(
        (picked) => {
          if (picked && picked.length > 0) acceptPath(picked[0]);
        },
      );
      return;
    }
    browseNativeOrInput(
      inputRef.current,
      filtersFromAccept(ACCEPT_ATTR, 'DEM rasters'),
      (files) => acceptFile(files[0]),
      false,
      (skipped) => skipped.forEach((s) => notify(`${s.name}: ${s.reason}`, { severity: 'error' })),
    );
  }, [acceptFile, acceptPath, notify]);

  const onInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      acceptFile(e.target.files?.[0]);
      e.target.value = ''; // allow re-selecting the same file after a reset
    },
    [acceptFile],
  );

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      acceptFile(e.dataTransfer.files?.[0]);
    },
    [acceptFile],
  );

  const reset = useCallback(() => {
    setFile(null);
    setStage('idle');
    setUploadPct(0);
    setResult(null);
    setErrorMessage(null);
    setParams(DEFAULT_PARAMS);
    setExported(false);
  }, []);

  const onProcess = useCallback(async () => {
    if (!file) return;

    let corners: DemPoint[] | undefined;
    let cameraLat: number | undefined;
    let cameraLon: number | undefined;
    let radiusM: number | undefined;

    if (params.aoiMode === 'camera') {
      const lat = Number(params.cameraLat.trim());
      const lon = Number(params.cameraLon.trim());
      const radius = Number(params.radiusM.trim());
      if (params.cameraLat.trim() === '' || params.cameraLon.trim() === '') {
        setErrorMessage('Enter the camera latitude and longitude, in decimal degrees.');
        setStage('error');
        return;
      }
      if (
        !Number.isFinite(lat) ||
        Math.abs(lat) > 90 ||
        !Number.isFinite(lon) ||
        Math.abs(lon) > 180
      ) {
        setErrorMessage(
          'The camera position must be decimal degrees: latitude ±90, longitude ±180.',
        );
        setStage('error');
        return;
      }
      if (!(radius > 0)) {
        setErrorMessage('The working radius must be a positive number of metres.');
        setStage('error');
        return;
      }
      cameraLat = lat;
      cameraLon = lon;
      radiusM = radius;
    } else if (params.aoiMode === 'corners') {
      const filled = params.corners.filter((c) => c.lat.trim() !== '' && c.lon.trim() !== '');
      if (filled.length < 3) {
        setErrorMessage(
          'An AOI needs at least 3 complete corners to bound an area. Fill both latitude ' +
            'and longitude for each, or switch to a camera position.',
        );
        setStage('error');
        return;
      }
      corners = filled.map((c) => ({ lat: c.lat.trim(), lon: c.lon.trim() }));
    }

    setErrorMessage(null);
    setResult(null);
    setExported(false);
    // ★ Path mode has no upload phase at all — the API reads the file in place.
    //   100% flips the progress UI straight to its "Processing…" state.
    setUploadPct(file.kind === 'path' ? 100 : 0);
    setStage('processing');

    try {
      const response = await demApi.process(
        {
          ...(file.kind === 'file' ? { file: file.file } : { source_path: file.path }),
          aoi_corners: corners,
          camera_lat: cameraLat,
          camera_lon: cameraLon,
          radius_m: radiusM,
          tolerance: params.tolerancePct / 100,
          reproject: params.reproject,
          ...(targetProjectId !== null
            ? {
                project_id: targetProjectId,
                set_as_elevation_source: true,
                // ★ When an image is chosen, the output adopts for THAT image only.
                ...(targetImageId !== null ? { image_id: targetImageId } : {}),
              }
            : {}),
          // ★ Omitted when the camera fixes the zone — the server derives it from the
          //   position, and a value sent here would only be a chance to disagree.
          target_srid: cameraLat !== undefined ? undefined : params.targetSrid,
        },
        {
          onProgress: (sent, total) => {
            if (total > 0) setUploadPct(Math.round((sent / total) * 100));
          },
        },
      );
      setResult(response);
      setStage('done');
      setLibraryRefresh((n) => n + 1);
      notify(
        targetProjectId !== null
          ? targetImageId !== null
            ? `DEM processed and set as this image's elevation source — ${response.output_crs}`
            : `DEM processed and set as the project's elevation source — ${response.output_crs}`
          : `DEM processed — ${response.output_crs}`,
        { severity: 'success' },
      );
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'The DEM could not be processed.';
      setErrorMessage(message);
      setStage('error');
    }
  }, [file, notify, params, targetProjectId, targetImageId]);

  /** Done without downloading: back to where the user came from (the setup page's
   *  "Process new DEM…" button, usually), falling back to the project or Projects. */
  const onSkipExport = useCallback((): void => {
    const previous = useNavHistoryStore.getState().previous();
    if (previous !== null) navigate(previous);
    else if (targetProjectId !== null) navigate(`/projects/${targetProjectId}`);
    else navigate('/cameras');
  }, [navigate, targetProjectId]);

  const onExport = useCallback(async () => {
    if (!result) return;
    setDownloading(true);
    try {
      const blob = await demApi.download(result.run_id);
      const base = result.source_name.replace(/\.[^.]+$/, '');
      downloadBlob(blob, `${base}_processed.tif`);
      setExported(true);
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Download failed.', { severity: 'error' });
    } finally {
      setDownloading(false);
    }
  }, [notify, result]);

  const busy = stage === 'processing';
  const stages = deriveStages(file !== null, stage, exported);

  // ── header: title + the target card ──────────────────────────────────────────
  const header = (
    <Stack
      direction={{ xs: 'column', lg: 'row' }}
      spacing={2}
      alignItems={{ xs: 'stretch', lg: 'center' }}
      sx={{ mb: 2.5 }}
    >
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
        <Box
          aria-hidden
          sx={{
            width: 40,
            height: 40,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 'var(--radius-md)',
            bgcolor: 'var(--accent-quiet)',
            color: 'var(--accent)',
            flexShrink: 0,
          }}
        >
          <TerrainOutlinedIcon />
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h5" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            {t('Digital Elevation Model')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t(
              'Crop a DEM to your area of interest and reproject it into metres, then export the result as a GeoTIFF.',
            )}
          </Typography>
        </Box>
      </Stack>

      {/* ★ THE TARGET, AS A CARD. Amber (left rule + hint) while no project is
          chosen — the DEM would feed nothing and Auto GCP would keep saying
          "no DEM" — calm once one is. Same controls as before, a quarter of the room. */}
      <Box
        role="group"
        aria-label={t('Target project')}
        sx={{
          display: 'flex',
          flexDirection: { xs: 'column', sm: 'row' },
          alignItems: { sm: 'center' },
          gap: 1.5,
          px: 2,
          py: 1.5,
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--hairline)',
          borderLeft: '3px solid',
          borderLeftColor: targetProjectId !== null ? 'var(--accent)' : 'var(--status-warn)',
          bgcolor: 'var(--bg-elevated)',
          minWidth: { lg: 520 },
        }}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography
            className="le-mono"
            sx={{ fontSize: 10, letterSpacing: '0.08em', color: 'text.secondary' }}
          >
            {t('FEEDS')}
          </Typography>
          {targetProjectId !== null ? (
            <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
              {targetProject.data?.name ?? t('the selected project')}
              <Typography component="span" variant="body2" color="text.secondary">
                {targetImageId !== null
                  ? ` · ${selectedImageName ?? t('one image')} ${t('only')}`
                  : ` · ${t('every image')}`}
              </Typography>
            </Typography>
          ) : (
            <Typography variant="body2" sx={{ color: 'var(--status-warn)', fontWeight: 600 }}>
              {t('No project — Auto GCP there would keep reporting “no DEM”')}
            </Typography>
          )}
        </Box>
        {targetProjectId !== null ? (
          <>
            <FormControl size="small" sx={{ minWidth: 220 }} disabled={busy}>
              <InputLabel id="dem-apply-scope">{t('Apply this DEM to')}</InputLabel>
              <Select
                labelId="dem-apply-scope"
                label={t('Apply this DEM to')}
                value={targetImageId ?? ''}
                onChange={(e) => chooseImage(String(e.target.value))}
              >
                <MenuItem value="">{t('The whole project (every image)')}</MenuItem>
                {(projectImages.data?.items ?? []).map((img) => (
                  <MenuItem key={img.id} value={img.id}>
                    {img.filename}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {/* ★ UNSELECT (1.2.6): detach this run from the project. `chooseProject('')`
                drops the ?project= param — the DEM still processes and lands in the
                library, it just no longer becomes any project's elevation source. */}
            <Button color="inherit" size="small" onClick={() => chooseProject('')} disabled={busy}>
              {t('Unselect project')}
            </Button>
          </>
        ) : (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="dem-target-project">{t('Target project')}</InputLabel>
            <Select
              labelId="dem-target-project"
              label={t('Target project')}
              value=""
              onChange={(e) => chooseProject(String(e.target.value))}
            >
              {(projectChoices.data?.items ?? []).map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
      </Box>
    </Stack>
  );

  return (
    <Box sx={embedded ? undefined : { flex: 1, overflow: 'auto' }}>
      <Container
        maxWidth="lg"
        sx={embedded ? { py: 0, px: 0 } : { py: 4 }}
        disableGutters={embedded}
      >
        {header}
        <Box sx={{ mb: 3 }}>
          <StageStrip stages={stages} />
        </Box>

        {/* ★ Settings column + the library of previous outputs, side by side: what
            you are about to process next to what you have already processed. Below
            `md` the library stacks underneath — a phone gets the pipeline first. */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) 320px' },
            gap: 3,
            alignItems: 'start',
          }}
        >
          <Stack spacing={2.5}>
            {/* ── 1 · Upload ────────────────────────────────────────────────── */}
            <StepCard
              id="dem-stage-upload"
              index={1}
              title={t('Upload DEM')}
              hint={t(
                'A raw elevation raster, any size — large tiles are read in place on the desktop.',
              )}
              action={
                file ? (
                  <Chip
                    size="small"
                    icon={<CheckRoundedIcon />}
                    label={t('file chosen')}
                    variant="outlined"
                    sx={{ '& .MuiChip-icon': { color: 'var(--status-ok)' } }}
                  />
                ) : undefined
              }
            >
              <Box
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={browseDem}
                role="button"
                tabIndex={0}
                aria-label={t('Drag a DEM file here, or click to browse')}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') browseDem();
                }}
                sx={{
                  'display': 'flex',
                  'flexDirection': { xs: 'column', sm: 'row' },
                  'alignItems': 'center',
                  'gap': 2,
                  'p': 2.5,
                  'borderRadius': 'var(--radius-lg)',
                  'border': '2px dashed',
                  'borderColor': dragging ? 'var(--accent)' : 'var(--hairline-strong)',
                  'bgcolor': dragging ? 'var(--accent-quiet)' : 'var(--bg-inset)',
                  'cursor': 'pointer',
                  'outline': 'none',
                  'transition':
                    'border-color var(--dur-fast) var(--ease-standard), background-color var(--dur-fast) var(--ease-standard)',
                  '&:hover': { borderColor: 'var(--accent)' },
                  '&:focus-visible': { boxShadow: 'var(--focus-ring)' },
                }}
              >
                <Box
                  aria-hidden
                  sx={{
                    width: 56,
                    height: 56,
                    display: 'grid',
                    placeItems: 'center',
                    borderRadius: 'var(--radius-md)',
                    bgcolor: 'var(--accent-quiet)',
                    color: 'var(--accent)',
                    flexShrink: 0,
                  }}
                >
                  <CloudUploadOutlinedIcon sx={{ fontSize: 30 }} />
                </Box>
                <Box sx={{ flex: 1, minWidth: 0, textAlign: { xs: 'center', sm: 'left' } }}>
                  <Typography variant="body1" sx={{ fontWeight: 600 }}>
                    {t('Drag a DEM file here, or click to browse')}
                  </Typography>
                  <Stack
                    direction="row"
                    spacing={0.5}
                    useFlexGap
                    flexWrap="wrap"
                    sx={{ mt: 0.75, justifyContent: { xs: 'center', sm: 'flex-start' } }}
                  >
                    {ACCEPTED_EXTENSIONS.map((ext) => (
                      <Box
                        key={ext}
                        component="span"
                        className="le-mono"
                        sx={{
                          fontSize: 10,
                          px: 0.75,
                          py: 0.125,
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--hairline)',
                          color: 'text.secondary',
                        }}
                      >
                        {ext}
                      </Box>
                    ))}
                  </Stack>
                </Box>
                <Button variant="outlined" size="small" sx={{ flexShrink: 0 }} tabIndex={-1}>
                  {t('Browse')}
                </Button>
                <input
                  ref={inputRef}
                  type="file"
                  hidden
                  accept={ACCEPT_ATTR}
                  onChange={onInputChange}
                />
              </Box>

              {file && (
                <Stack
                  direction="row"
                  spacing={1.5}
                  alignItems="center"
                  sx={{
                    mt: 1.5,
                    p: 1.5,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--hairline)',
                  }}
                >
                  <InsertDriveFileOutlinedIcon sx={{ color: 'var(--accent)' }} />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="body2" noWrap title={file.name} sx={{ fontWeight: 600 }}>
                      {file.name}
                    </Typography>
                    <Typography className="le-mono" sx={{ fontSize: 11, color: 'text.secondary' }}>
                      {formatBytes(file.size)}
                      {file.kind === 'path' && ` · ${t('read in place from disk')}`}
                    </Typography>
                  </Box>
                  <Button size="small" color="inherit" onClick={reset} disabled={busy}>
                    {t('Remove')}
                  </Button>
                </Stack>
              )}
            </StepCard>

            {/* ── 2 · Configure ─────────────────────────────────────────────── */}
            <StepCard
              id="dem-stage-configure"
              index={2}
              title={t('Configure the crop and projection')}
              hint={t('Where the terrain matters, and the metre grid it lands on.')}
              action={
                <>
                  {/* ★ IMPORT (1.2.6): fill the camera station or AOI corners from a
                      file the crew already has — CSV (key,value or lat,lon rows),
                      JSON, or GeoJSON (a Point → camera, a Polygon → corners). */}
                  <Tooltip title="Import camera position or AOI corners from a CSV, JSON, or GeoJSON file">
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={<UploadFileOutlinedIcon fontSize="small" />}
                      onClick={browseParams}
                      disabled={busy}
                    >
                      {t('Import parameters')}
                    </Button>
                  </Tooltip>
                  <input
                    ref={paramsInputRef}
                    type="file"
                    hidden
                    accept=".csv,.txt,.json,.geojson"
                    onChange={(e) => {
                      onImportParams(e.target.files?.[0]);
                      e.target.value = '';
                    }}
                  />
                </>
              }
            >
              <Stack spacing={2.5}>
                {/* Stage 1 — the area of interest */}
                <Box>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    {t('Area of interest')}
                  </Typography>
                  <ToggleButtonGroup
                    exclusive
                    value={params.aoiMode}
                    onChange={(_, value: AoiMode | null) => {
                      if (value !== null) setParam('aoiMode', value);
                    }}
                    aria-label={t('Area of interest')}
                    disabled={busy}
                    sx={{
                      'flexWrap': 'wrap',
                      '& .MuiToggleButton-root': {
                        textTransform: 'none',
                        fontWeight: 600,
                        px: 1.75,
                        gap: 1,
                        borderColor: 'var(--hairline-strong)',
                      },
                      '& .MuiToggleButton-root.Mui-selected': {
                        color: 'var(--accent)',
                        bgcolor: 'var(--accent-quiet)',
                        borderColor: 'var(--accent)',
                      },
                    }}
                  >
                    <ToggleButton value="camera" size="small">
                      <MyLocationOutlinedIcon fontSize="small" />
                      {t('Camera position + radius')}
                    </ToggleButton>
                    <ToggleButton value="corners" size="small">
                      <CropFreeOutlinedIcon fontSize="small" />
                      {t('Four corners')}
                    </ToggleButton>
                    <ToggleButton value="none" size="small">
                      <PublicOutlinedIcon fontSize="small" />
                      {t('Whole DEM (no crop)')}
                    </ToggleButton>
                  </ToggleButtonGroup>

                  {params.aoiMode === 'camera' && (
                    <Stack spacing={2} sx={{ mt: 2 }}>
                      <Typography variant="caption" color="text.secondary">
                        {t(
                          'Where the camera stood, and how far out its frames contain usable ground. The DEM is cropped to that disc — and the position also fixes the UTM zone, so there is no zone to choose.',
                        )}
                      </Typography>
                      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                        <TextField
                          size="small"
                          label={t('Camera latitude')}
                          placeholder="34.1128"
                          value={params.cameraLat}
                          onChange={(e) => setParam('cameraLat', e.target.value)}
                          disabled={busy}
                          fullWidth
                        />
                        <TextField
                          size="small"
                          label={t('Camera longitude')}
                          placeholder="36.0229"
                          value={params.cameraLon}
                          onChange={(e) => setParam('cameraLon', e.target.value)}
                          disabled={busy}
                          fullWidth
                        />
                        <TextField
                          size="small"
                          type="number"
                          label={t('Radius (m)')}
                          value={params.radiusM}
                          onChange={(e) => setParam('radiusM', e.target.value)}
                          inputProps={{ min: 1, step: 100 }}
                          disabled={busy}
                          fullWidth
                        />
                      </Stack>
                      <DerivedZone lat={params.cameraLat} lon={params.cameraLon} />
                    </Stack>
                  )}

                  {params.aoiMode === 'corners' && (
                    <Stack spacing={1.5} sx={{ mt: 2 }}>
                      <Typography variant="caption" color="text.secondary">
                        {t('Decimal degrees or DMS —')} <code>34°07&apos;39.16&quot;N</code>,{' '}
                        <code>34.127544</code>, or <code>34; 7; 39.16; N</code> {t('all work.')}
                      </Typography>
                      <Box
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
                          gap: 1.5,
                        }}
                      >
                        {params.corners.map((corner, i) => (
                          <Box
                            key={i}
                            sx={{
                              p: 1.5,
                              borderRadius: 'var(--radius-md)',
                              border: '1px solid var(--hairline)',
                              bgcolor: 'var(--bg-inset)',
                            }}
                          >
                            <Typography
                              className="le-mono"
                              sx={{
                                fontSize: 10,
                                letterSpacing: '0.08em',
                                color: 'text.secondary',
                                mb: 1,
                              }}
                            >
                              {t('CORNER')} {i + 1}
                            </Typography>
                            <Stack direction="row" spacing={1.5}>
                              <TextField
                                size="small"
                                label={t('Latitude')}
                                placeholder={i === 0 ? `34°07'39.16"N` : ''}
                                value={corner.lat}
                                onChange={(e) => setCorner(i, 'lat', e.target.value)}
                                disabled={busy}
                                fullWidth
                              />
                              <TextField
                                size="small"
                                label={t('Longitude')}
                                placeholder={i === 0 ? `36°01'35.17"E` : ''}
                                value={corner.lon}
                                onChange={(e) => setCorner(i, 'lon', e.target.value)}
                                disabled={busy}
                                fullWidth
                              />
                            </Stack>
                          </Box>
                        ))}
                      </Box>
                    </Stack>
                  )}

                  {params.aoiMode !== 'none' && (
                    <Box sx={{ mt: 2.5 }}>
                      <Stack direction="row" alignItems="center" spacing={2}>
                        <Box sx={{ flex: 1, px: 1 }}>
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            id="dem-tolerance-label"
                          >
                            {t('Tolerance (% padding)')} —{' '}
                            {t('margin added on every side, as a share of the area’s own span')}
                          </Typography>
                          <Slider
                            aria-labelledby="dem-tolerance-label"
                            value={Math.min(100, Math.max(0, params.tolerancePct))}
                            onChange={(_, v) => setParam('tolerancePct', Number(v))}
                            min={0}
                            max={100}
                            step={5}
                            marks={[
                              { value: 0, label: '0%' },
                              { value: 25, label: '25%' },
                              { value: 50, label: '50%' },
                              { value: 100, label: '100%' },
                            ]}
                            valueLabelDisplay="auto"
                            valueLabelFormat={(v) => `${v}%`}
                            disabled={busy}
                            sx={{ '& .MuiSlider-markLabel': { fontSize: 10 } }}
                          />
                        </Box>
                        <TextField
                          size="small"
                          type="number"
                          label="%"
                          value={params.tolerancePct}
                          onChange={(e) => setParam('tolerancePct', Number(e.target.value))}
                          inputProps={{
                            'min': 0,
                            'max': 500,
                            'step': 5,
                            'aria-label': t('Tolerance (% padding)'),
                          }}
                          disabled={busy}
                          sx={{ width: 96, flexShrink: 0 }}
                        />
                      </Stack>
                    </Box>
                  )}
                </Box>

                <Divider />

                {/* Stage 2 — reproject to metres. ★ ALWAYS ON, no longer a choice:
                    every downstream consumer (ray/DEM intersection, GCP elevation,
                    slope, the 3D surface) does metric arithmetic, so a DEM left in
                    degrees is not a slower answer — it is a WRONG one. The stage
                    still skips itself when the raster is already in ground metres,
                    which is the only case where "off" was ever correct. */}
                <Box>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                    <Typography variant="subtitle2">
                      {t('Reproject to metres')}{' '}
                      <Typography
                        component="span"
                        className="le-mono"
                        sx={{ fontSize: 12, color: 'text.secondary' }}
                      >
                        (λ, φ, H) → (E, N, H)
                      </Typography>
                    </Typography>
                    <Chip size="small" variant="outlined" label={t('always on')} />
                  </Stack>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {t(
                      'Always applied. Distances, slopes and ray geometry are only meaningful in metres — a degree of longitude is 111 km at the equator and 64 km at 55°N. Skipped automatically if the DEM is already in a metre grid.',
                    )}
                  </Typography>
                </Box>

                {/* ★ The CRS picker appears only when the camera is NOT fixing the zone.
                    With a camera position there is nothing to choose — the zone follows
                    from where it stood, and offering a second answer invites a wrong one. */}
                {params.aoiMode !== 'camera' && (
                  <FormControl size="small" fullWidth disabled={busy} sx={{ maxWidth: 480 }}>
                    <InputLabel id="dem-srid-label">
                      {t('Output coordinate reference system')}
                    </InputLabel>
                    <Select
                      labelId="dem-srid-label"
                      label={t('Output coordinate reference system')}
                      value={params.targetSrid === null ? 'auto' : String(params.targetSrid)}
                      onChange={(e) =>
                        setParam(
                          'targetSrid',
                          e.target.value === 'auto' ? null : Number(e.target.value),
                        )
                      }
                    >
                      {SRID_OPTIONS.map((o) => (
                        <MenuItem key={o.label} value={o.value === null ? 'auto' : String(o.value)}>
                          <Tooltip title={o.hint} placement="right">
                            <span>{o.label}</span>
                          </Tooltip>
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}
              </Stack>
            </StepCard>

            {/* ── 3 · Process ───────────────────────────────────────────────── */}
            <StepCard
              id="dem-stage-process"
              index={3}
              title={t('Process')}
              hint={t(
                'Crop, reproject and measure — the result is saved to the library as it finishes.',
              )}
              muted={!file}
              action={
                stage === 'done' ? (
                  <Chip
                    size="small"
                    icon={<CheckRoundedIcon />}
                    label={t('Processing complete')}
                    variant="outlined"
                    sx={{ '& .MuiChip-icon': { color: 'var(--status-ok)' } }}
                  />
                ) : undefined
              }
            >
              <Stack
                direction="row"
                spacing={1.5}
                alignItems="center"
                sx={{ flexWrap: 'wrap', rowGap: 1 }}
              >
                <Button
                  variant="contained"
                  size="large"
                  startIcon={
                    busy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />
                  }
                  onClick={onProcess}
                  disabled={!file || busy}
                >
                  {busy ? 'Processing…' : 'Process DEM'}
                </Button>
                {/* ★ Beside the action it undoes: "reset" belongs with "process",
                    not down in Export where it read as part of downloading. */}
                <Button
                  color="inherit"
                  startIcon={<RestartAltOutlinedIcon />}
                  onClick={reset}
                  disabled={stage === 'idle' || busy}
                >
                  {t('Reset process')}
                </Button>
              </Stack>

              {busy && (
                <Box sx={{ mt: 2.5 }}>
                  <LinearProgress
                    variant={uploadPct < 100 ? 'determinate' : 'indeterminate'}
                    value={uploadPct}
                    sx={{ mb: 1.25 }}
                  />
                  <ProgressStage
                    stages={[
                      {
                        label:
                          file?.kind === 'path' ? t('Reading the file in place') : t('Uploading'),
                        state: uploadPct < 100 ? 'running' : 'done',
                        pct: uploadPct < 100 ? uploadPct : undefined,
                      },
                      {
                        label: t('Cropping and reprojecting on the server'),
                        state: uploadPct < 100 ? 'waiting' : 'running',
                      },
                      { label: t('Measuring the result'), state: 'waiting' },
                    ]}
                  />
                </Box>
              )}

              {stage === 'error' && errorMessage && (
                <Box sx={{ mt: 2 }}>
                  {/* Phase 5: the server's words, with a copy button — a DEM
                      failure message is exactly what a support report needs. */}
                  <ErrorState message={errorMessage} />
                </Box>
              )}

              {result && <DemResultPanel result={result} />}
            </StepCard>

            {/* ── 4 · Export ────────────────────────────────────────────────── */}
            <StepCard
              id="dem-stage-export"
              index={4}
              title={t('Export and continue')}
              hint={t(
                'The result is already saved in the library; export only to use it elsewhere.',
              )}
              muted={stage !== 'done'}
            >
              <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                {/* ★ THE ROUND TRIP HOME (1.2.6). Arriving here via the setup page's
                    "Process new DEM…" used to be a one-way door: processing finished
                    and no control led back. `?image=` present ⇒ the run came from a
                    photo's IMAGE SETUP (per-image DEM) and returns there; absent ⇒ it
                    came from PROJECT SETTINGS (project DEM) and returns THERE. Both
                    pages keep everything typed before the excursion via their session
                    draft stores. */}
                {targetProjectId !== null && (
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<ArrowBackOutlinedIcon />}
                    onClick={() => {
                      // ★ A CAMERA's project returns to the camera's settings (2026-09-04):
                      //   its DEM step adopts the processed tile from the library.
                      const ref = cameraRefForProject(targetProjectId);
                      navigate(
                        ref !== null
                          ? cameraSettingsPath(ref)
                          : targetImageId !== null
                            ? `/projects/${targetProjectId}/images/${targetImageId}/setup`
                            : `/projects/${targetProjectId}/settings`,
                      );
                    }}
                    disabled={stage !== 'done' || downloading}
                  >
                    {cameraRefForProject(targetProjectId) !== null
                      ? t('Add processed DEM to camera settings')
                      : targetImageId !== null
                        ? 'Add processed DEM to image setup'
                        : 'Add processed DEM to project settings'}
                  </Button>
                )}
                <Button
                  variant={targetProjectId !== null ? 'outlined' : 'contained'}
                  startIcon={<DownloadOutlinedIcon />}
                  onClick={onExport}
                  disabled={stage !== 'done' || downloading}
                >
                  {downloading ? 'Preparing…' : 'Export .tif'}
                  {result && !downloading && ` (${formatBytes(result.output_bytes)})`}
                </Button>
                {/* ★ EXPORT IS OPTIONAL, and this says so. The output is already
                    saved server-side — in the DEM library, and (in project mode) as
                    the project's elevation source — so the download is only for use
                    OUTSIDE this app. Skip returns to where the user came from. */}
                <Button
                  color="inherit"
                  startIcon={<SkipNextOutlinedIcon fontSize="small" />}
                  onClick={onSkipExport}
                  disabled={stage !== 'done' || downloading}
                >
                  {t('Skip export')}
                </Button>
              </Stack>
              {stage === 'done' && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  display="block"
                  sx={{ mt: 1.5 }}
                >
                  The result is already saved in your DEM library
                  {targetProjectId !== null &&
                    targetImageId !== null &&
                    ' and set as this image’s own elevation source — “Add processed DEM to image setup” returns there with everything you had entered intact'}
                  {targetProjectId !== null &&
                    targetImageId === null &&
                    ' and set as the project’s elevation source — “Add processed DEM to project settings” returns there with everything you had entered intact'}
                  {targetProjectId === null &&
                    ' — exporting is only needed to use it outside Mono Camera Geolocator'}
                  .
                </Typography>
              )}
            </StepCard>
          </Stack>

          <Box
            sx={{
              position: { md: 'sticky' },
              top: { md: 16 },
              borderRadius: 'var(--radius-lg)',
              border: '1px solid var(--hairline)',
              bgcolor: 'var(--bg-elevated)',
              p: 2,
            }}
          >
            <DemLibraryPanel
              projectId={targetProjectId !== null ? asUuid(targetProjectId) : null}
              imageId={targetImageId !== null ? asUuid(targetImageId) : null}
              // ★ The DEM page is the library's HOME, so it manages it too (1.2.6):
              //   each row offers delete-with-confirm. The adoption dialogs on the
              //   settings pages keep this off — a picker should not destroy.
              allowDelete
              refreshKey={libraryRefresh}
              onAdopted={() =>
                notify(
                  targetImageId !== null
                    ? 'This image now reads elevations from the library DEM.'
                    : 'The project now reads elevations from the library DEM.',
                  { severity: 'info' },
                )
              }
            />
          </Box>
        </Box>
      </Container>
    </Box>
  );
}

/**
 * The UTM zone the typed camera position falls in, shown as it is typed.
 *
 * ★ This is the whole reason the camera position is asked for rather than a zone: the
 *   surveyor states where they stood, and the zone follows. Blank until both fields
 *   parse, so it never shows a zone for a half-typed coordinate.
 */
function DerivedZone({ lat, lon }: { lat: string; lon: string }): JSX.Element | null {
  if (lat.trim() === '' || lon.trim() === '') return null;
  const latN = Number(lat);
  const lonN = Number(lon);
  if (!Number.isFinite(latN) || !Number.isFinite(lonN)) return null;

  const epsg = utmEpsgFor(latN, lonN);
  if (epsg === null) {
    return (
      <Alert severity="warning" sx={{ py: 0.5 }}>
        {t('Beyond ±84° latitude UTM is undefined — this position needs a polar (UPS) grid.')}
      </Alert>
    );
  }
  const zone = Number(epsg.slice(-2));
  const hemisphere = latN >= 0 ? 'N' : 'S';
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
      <Chip
        size="small"
        variant="outlined"
        className="le-mono"
        label={`UTM zone ${zone}${hemisphere} · ${epsg}`}
        sx={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
      />
      <Typography variant="caption" color="text.secondary">
        {t('derived from the camera position — the DEM is reprojected into this zone')}
      </Typography>
    </Stack>
  );
}

/**
 * The run report.
 *
 * ★ The GSD and the elevation range are shown because they are how a surveyor checks
 *   the result is real. A DEM whose range is 0–0, or whose cell size is 10⁵ m, is a
 *   broken read — and seeing that here beats discovering it three steps downstream.
 */
function DemResultPanel({ result }: { result: DemProcessResponse }): JSX.Element {
  const { statistics: stats, reproject, crop } = result;
  const gsd = result.output_pixel_size_m;
  const voidPct =
    stats.valid_cells + stats.void_cells > 0
      ? (stats.void_cells / (stats.valid_cells + stats.void_cells)) * 100
      : 0;

  // ★ Actionable warnings read as warnings; expected narration ("no AOI", "already
  //   metric") reads as calm info — same information, no false alarm.
  const { actionable, informational } = classifyDemWarnings(result.warnings);

  return (
    <Box sx={{ mt: 2.5 }}>
      {actionable.map((w) => (
        <Alert severity="warning" sx={{ mb: 1.5 }} key={w}>
          {w}
        </Alert>
      ))}
      {informational.map((w) => (
        <Alert severity="info" sx={{ mb: 1.5 }} key={w}>
          {w}
        </Alert>
      ))}

      <Typography
        className="le-mono"
        sx={{ fontSize: 10, letterSpacing: '0.08em', color: 'text.secondary', mb: 1 }}
      >
        {t('RESULT')}
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(3, 1fr)' },
          gap: 1.5,
        }}
      >
        <StatTile
          label={t('Coordinate system')}
          value={result.output_crs}
          sub={
            <>
              {t('from')} {result.source_crs}
              {reproject?.auto_utm && ` · ${t('auto UTM')}`}
            </>
          }
        />
        <StatTile
          label={t('Ground sample distance')}
          value={gsd ? gsd[0].toFixed(3) : '—'}
          unit={gsd ? 'm / px' : undefined}
          sub={gsd ? undefined : t('not in ground metres — reprojection was skipped')}
        />
        <StatTile
          label={t('Output size')}
          value={`${result.output_size[0]} × ${result.output_size[1]}`}
          unit="px"
          sub={
            crop
              ? `${t('cropped at')} ${(crop.tolerance * 100).toFixed(0)}% ${t('tolerance')}${crop.clipped ? ` · ${t('clamped to tile edge')}` : ''}`
              : t('whole DEM')
          }
          tone={crop?.clipped ? 'warn' : undefined}
        />
        <StatTile
          label={t('Elevation range')}
          value={
            stats.min_m === null ? '—' : `${stats.min_m.toFixed(1)} – ${stats.max_m?.toFixed(1)}`
          }
          unit={stats.min_m === null ? undefined : 'm'}
          sub={
            stats.min_m === null
              ? t('no valid elevation cells')
              : `${t('mean')} ${stats.mean_m?.toFixed(1)} m`
          }
          tone={stats.min_m === null ? 'warn' : undefined}
        />
        <StatTile
          label={t('Coverage')}
          value={stats.valid_cells.toLocaleString()}
          unit={t('valid cells')}
          sub={
            stats.void_cells > 0
              ? `${stats.void_cells.toLocaleString()} ${t('void')} (${voidPct.toFixed(1)}%)`
              : t('no voids')
          }
        />
        <StatTile
          label={t('Output file')}
          value={formatBytes(result.output_bytes)}
          sub={`${result.source_name.replace(/\.[^.]+$/, '')}_processed.tif`}
        />
      </Box>

      {/* ★ NO VOID NOTE. Two used to fire: the pipeline's ">10% voids" warning and an
          info panel here explaining voids as a reprojection artefact. Both are gone.
          The second was also WRONG whenever reprojection was skipped (an
          already-metric DEM is not rotated, so its voids come from the source data,
          not from margins) — an explanation that names the wrong cause is worse than
          none. The COVERAGE TILE above still states the counts and the percentage,
          which is the fact without the lecture. */}
    </Box>
  );
}

export default DemPage;
