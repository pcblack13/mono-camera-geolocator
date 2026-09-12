/**
 * `pages/cameras/CameraSettingsPage.tsx` — `/cameras/new` and `/cameras/:id/settings`:
 * ONE camera's settings, as the pipeline that registers it.
 *
 * ★ THE PIPELINE (2026-09-04, owner ask), top to bottom, numbered — and EVERY STEP
 *   OPEN FROM THE START, with ONE button at the end:
 *     1  Name
 *     2  Connection — UTP/LAN (address), USB (capture device), serial/UART (data)
 *     3  Position on the map (the server's own imagery provider, picked or pasted)
 *     4  Camera DEM
 *     5  Optional data — calibration: intrinsics, distortion, mast, tilt
 *     6  The frame — captured from the camera now, uploaded, or chosen from the
 *        capture library — and the door into the GCP editor to place control points
 *     7  Lookup table — built here or from the editor's strip
 *   then "Add camera to the server" (a new camera) or "Save camera" (an existing one).
 *
 * ★ A NEW CAMERA IS A DRAFT UNTIL THAT LAST PRESS (`cameraDraftStore`). The DEM,
 *   the frame and the control points are server records that need a home, so the
 *   first of them to arrive creates the camera's BACKING PROJECT — quietly, named
 *   after the draft — and the draft remembers it. The lookup table is built for
 *   the frame; its site name rides the draft. The final press posts everything as
 *   one camera row and clears the draft. The draft persists, so "Place control
 *   points" → the editor → "Back to camera settings" lands on the same draft.
 *
 * ★ An EXISTING camera edits in place: every step writes to its row as it happens
 *   (frame, lookup table) or on Save (the typed fields).
 */

import {
  Suspense,
  createContext,
  lazy,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type JSX,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import Tooltip from '@mui/material/Tooltip';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import FolderZipOutlinedIcon from '@mui/icons-material/FolderZipOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import CollectionsOutlinedIcon from '@mui/icons-material/CollectionsOutlined';
import DeleteSweepOutlinedIcon from '@mui/icons-material/DeleteSweepOutlined';
import EditLocationOutlinedIcon from '@mui/icons-material/EditLocationOutlined';
import GridOnOutlinedIcon from '@mui/icons-material/GridOnOutlined';
import PhotoCameraOutlinedIcon from '@mui/icons-material/PhotoCameraOutlined';
import RadarOutlinedIcon from '@mui/icons-material/RadarOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';
import UsbIcon from '@mui/icons-material/Usb';

import { captureLibraryApi } from '../../api/captureLibrary';
import { useGcps, useProjectDem, useProviders } from '../../api/hooks';
import { useDriftMonitors, useDriftReferences } from '../../api/hooks/useDrift';
import { driftApi } from '../../api/drift';
import { gcpsApi } from '../../api/gcps';
import { useImage } from '../../api/hooks/useImages';
import { useImageCamera } from '../../api/hooks/useImageCamera';
import { imageCameraApi } from '../../api/imageCamera';
import { imagesApi, isUploadAccepted } from '../../api/images';
import { liveApi, type LiveDeviceInfo } from '../../api/live';
import { lutApi } from '../../api/lut';
import { projectsApi } from '../../api/projects';
import { qk } from '../../api/queryKeys';
import { EmptyState } from '../../components/common/EmptyState';
import { useNotify } from '../../components/common/Notifications';
import { DriftPill } from '../../components/drift/DriftPill';
import { ProjectDemCard } from '../../components/project/ProjectDemCard';
import { MIN_GCPS_FOR_LUT } from '../../components/cameras/CameraSetupBanner';
import { CaptureFrameDialog } from '../../components/cameras/CaptureFrameDialog';
import {
  FrameChangeDialog,
  type FrameChangeDecision,
} from '../../components/cameras/FrameChangeDialog';
import { useCameraDriftFreeze } from '../../hooks/useCameraDrift';
import { useCameraLutBuild } from '../../hooks/useCameraLutBuild';
import { t } from '../../i18n';
import { CONNECTION_KINDS, connectionKind } from '../../lib/cameras/connection';
import {
  DATA_SCHEMES,
  STREAM_SCHEMES,
  joinScheme,
  schemeOptions,
  splitScheme,
} from '../../lib/cameras/urlScheme';
import { parseCoordinateValue, parseLocation } from '../../lib/geo/parseLocation';
import {
  EMPTY_DRAFT,
  draftHasContent,
  useCameraDraftStore,
  type CameraDraftFields,
} from '../../store/cameraDraftStore';
import {
  CALIBRATION_KEYS,
  DEVICE_CONNECTIONS,
  selectCameraById,
  useCameraRegistryStore,
  validateCamera,
  type CalibrationKey,
  type CameraConnection,
  type CameraValidationError,
  type RegisteredCamera,
} from '../../store/cameraRegistryStore';
import { camerasApi } from '../../api/cameras';
import { ApiError, asUuid, type Uuid } from '../../types/common';
import type { LatLon } from '../../types/geo';
import type { ImageRead } from '../../types/image';

// ★ Leaflet arrives ONLY with this page — the same picker the monitor's dialog uses.
const PositionPickerMap = lazy(() => import('../../components/monitor/globe/PositionPickerMap'));
const ImportFromLibraryDialog = lazy(async () => ({
  default: (await import('../../components/image/ImportFromLibraryDialog')).ImportFromLibraryDialog,
}));

// ─────────────────────────────────────────────────────────────────────────────
// The draft — every field as typed
// ─────────────────────────────────────────────────────────────────────────────

type Draft = CameraDraftFields;

const str = (v: number | null | undefined): string =>
  v === null || v === undefined ? '' : String(v);

/** Split a stored `serial://<port>?baud=N` back into its two boxes. */
function splitSerial(dataSource: string | undefined): { port: string; baud: string } {
  if (!dataSource) return { port: '', baud: '115200' };
  const m = /^serial:\/\/([^?]+)(?:\?baud=(\d+))?$/i.exec(dataSource.trim());
  if (m) return { port: m[1], baud: m[2] ?? '115200' };
  return { port: dataSource, baud: '115200' };
}

/** An existing camera's row → the draft shape (the edit form's seed). */
function draftFromCamera(camera: RegisteredCamera): Draft {
  const serial = splitSerial(camera.data_source);
  const dataOnly = camera.connection === 'serial';
  const cal: Record<string, string> = {};
  if (camera.calibration) {
    for (const k of CALIBRATION_KEYS) cal[k] = str(camera.calibration[k]);
  }
  return {
    name: camera.name,
    connection: camera.connection ?? 'lan',
    source: camera.source ?? '',
    dataUrl: dataOnly ? '' : (camera.data_source ?? ''),
    serialPort: dataOnly ? serial.port : '',
    serialBaud: dataOnly ? serial.baud : '115200',
    lat: str(camera.lat),
    lon: str(camera.lon),
    heading_deg: str(camera.heading_deg),
    fov_deg: str(camera.fov_deg),
    calibration: cal,
    // ★ Seeded from the frame's station once it arrives (GEO-DRIFT C2).
    no_calibration: false,
    project_id: camera.project_id ?? null,
    frame_image_id: camera.frame_image_id ?? null,
    lut_site: camera.lut_site ?? null,
  };
}

/** The wire shape a draft implies: what it connects with, what it delivers. */
function integrationOf(draft: Draft): {
  source: string;
  data_source: string;
  provides: 'camera' | 'data' | 'both';
} {
  const kind = connectionKind(draft.connection);
  const dataSource =
    kind.needs === 'serial'
      ? draft.serialPort.trim() === ''
        ? ''
        : `serial://${draft.serialPort.trim()}?baud=${draft.serialBaud}`
      : draft.dataUrl.trim();
  const source = kind.needs === 'serial' ? '' : draft.source.trim();
  const hasData = dataSource !== '';
  const hasVideo = source !== '';
  return {
    source,
    data_source: dataSource,
    provides: hasData && hasVideo ? 'both' : hasData ? 'data' : 'camera',
  };
}

function errorFor(errors: CameraValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

// ─────────────────────────────────────────────────────────────────────────────
// The setup table — one row per step, the chosen row's form beside it
// ─────────────────────────────────────────────────────────────────────────────
// ★ A TABLE THAT FITS THE PAGE (2026-09-10, owner ask). Seven rows — number,
//   step, status with WHAT is filled — always visible without scrolling; the
//   row the operator is on shows its controls in the panel beside the table,
//   and only that panel scrolls when a form is tall. The panel follows the
//   first empty row until the operator picks or touches one, so the page opens
//   on what needs filling next and never jumps away mid-typing. There is no
//   "Done" banner: the status cell says the value, the strip says the phase.

type StepState = 'done' | 'todo' | 'optional';

/** The seven rows, in pipeline order — the strip names the next one. */
const ROW_TITLES: readonly string[] = [
  'Name the camera',
  'How does it connect?',
  'Where does the camera stand?',
  'Camera DEM',
  'Optional data — camera calibration',
  'The frame, and its control points',
  'Lookup table',
  'Drift watch',
];

/** The first row still to fill (1-based); the last row once every required one is filled. */
function nextRow(states: readonly StepState[]): number {
  const i = states.findIndex((st) => st === 'todo');
  return i === -1 ? states.length : i + 1;
}

function SetupStatus({
  states,
  onNext,
}: {
  states: readonly StepState[];
  onNext: (n: number) => void;
}): JSX.Element {
  const filled = states.filter((st) => st === 'done').length;
  const nextIndex = states.findIndex((st) => st === 'todo');
  const complete = nextIndex === -1;
  const pct = Math.round((filled / states.length) * 100);
  return (
    <Stack
      role="status"
      aria-live="polite"
      direction="row"
      spacing={1.5}
      alignItems="center"
      useFlexGap
      flexWrap="wrap"
      sx={{
        mb: 1.5,
        px: 2,
        py: 1,
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
      }}
    >
      <Typography
        className="le-mono"
        sx={{ fontSize: 11, letterSpacing: '0.12em', color: 'text.secondary' }}
      >
        {t('SETUP STATUS')}
      </Typography>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
        {t('{filled} of {total} rows filled')
          .replace('{filled}', String(filled))
          .replace('{total}', String(states.length))}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={pct}
        aria-label={t('Rows filled')}
        sx={{ flex: 1, minWidth: 120, height: 6, borderRadius: 3 }}
      />
      {complete ? (
        <Typography variant="body2" sx={{ color: 'var(--accent)', fontWeight: 600 }}>
          {t('Setup complete — the camera is measurable.')}
        </Typography>
      ) : (
        <Button size="small" variant="text" onClick={() => onNext(nextIndex + 1)} sx={{ py: 0 }}>
          {`${t('Next:')} ${t(ROW_TITLES[nextIndex] ?? '')}`}
        </Button>
      )}
    </Stack>
  );
}

const HEAD_CELL = {
  py: 1,
  px: 1.5,
  textAlign: 'start',
  fontSize: 11,
  letterSpacing: '0.12em',
  fontWeight: 600,
  color: 'text.secondary',
  borderBottom: '1px solid var(--hairline-strong)',
  position: 'sticky',
  top: 0,
  bgcolor: 'var(--bg-elevated)',
} as const;

const ROW_CELL = { px: 1.5, py: 1.25, borderBottom: '1px solid var(--hairline)' } as const;

const PANE = {
  minHeight: 0,
  overflow: 'auto',
  borderRadius: 'var(--radius-lg)',
  border: '1px solid var(--hairline)',
  bgcolor: 'var(--bg-elevated)',
} as const;

interface SetupPanel {
  selected: number;
  panel: HTMLElement | null;
  onSelect: (n: number) => void;
}

const SetupPanelContext = createContext<SetupPanel>({
  selected: 1,
  panel: null,
  onSelect: () => undefined,
});

function SetupTable({
  selected,
  onSelect,
  onTouch,
  children,
}: {
  selected: number;
  onSelect: (n: number) => void;
  /** The operator started working in the panel — keep it on this row. */
  onTouch: () => void;
  children: ReactNode;
}): JSX.Element {
  const [panel, setPanel] = useState<HTMLElement | null>(null);
  const ctx = useMemo(() => ({ selected, panel, onSelect }), [selected, panel, onSelect]);
  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: 'minmax(340px, 5fr) minmax(400px, 7fr)' },
        gridTemplateRows: { xs: 'auto auto', md: 'minmax(0, 1fr)' },
        gap: 2,
      }}
    >
      <Box sx={PANE}>
        <Box component="table" sx={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0 }}>
          <colgroup>
            <col style={{ width: 52 }} />
            <col />
            <col style={{ width: 200 }} />
          </colgroup>
          <thead>
            <tr>
              <Box component="th" scope="col" className="le-mono" sx={HEAD_CELL}>
                #
              </Box>
              <Box component="th" scope="col" className="le-mono" sx={HEAD_CELL}>
                {t('STEP')}
              </Box>
              <Box component="th" scope="col" className="le-mono" sx={HEAD_CELL}>
                {t('STATUS')}
              </Box>
            </tr>
          </thead>
          <tbody>
            <SetupPanelContext.Provider value={ctx}>{children}</SetupPanelContext.Provider>
          </tbody>
        </Box>
      </Box>
      <Box
        ref={setPanel}
        onFocusCapture={onTouch}
        onPointerDownCapture={onTouch}
        sx={{ ...PANE, p: 2 }}
      />
    </Box>
  );
}

/** The status cell: the word, and WHAT is filled (the value, not a banner). */
function RowStatus({ state, summary }: { state: StepState; summary?: string }): JSX.Element {
  const filled = state === 'done';
  const tone = filled ? 'var(--accent)' : state === 'optional' ? 'text.secondary' : 'warning.main';
  return (
    <Stack direction="row" spacing={0.75} alignItems="flex-start">
      {filled ? (
        <CheckCircleOutlineIcon sx={{ fontSize: 18, color: tone }} />
      ) : (
        <RadioButtonUncheckedIcon sx={{ fontSize: 18, color: tone }} />
      )}
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, color: tone, lineHeight: 1.3 }}>
          {filled ? t('Filled') : state === 'optional' ? t('Optional — empty') : t('Not filled')}
        </Typography>
        {summary !== undefined && summary !== '' && (
          <Typography
            variant="caption"
            color="text.secondary"
            dir="auto"
            sx={{
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
              overflowWrap: 'anywhere',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {summary}
          </Typography>
        )}
      </Box>
    </Stack>
  );
}

function StepNumber({
  n,
  state,
  active,
}: {
  n: number;
  state: StepState;
  active: boolean;
}): JSX.Element {
  const done = state === 'done';
  return (
    <Box
      aria-hidden
      className="le-mono"
      sx={{
        width: 28,
        height: 28,
        borderRadius: '50%',
        display: 'grid',
        placeItems: 'center',
        fontSize: 12,
        fontWeight: 700,
        color: done ? 'var(--accent-contrast)' : 'var(--accent)',
        bgcolor: done ? 'var(--accent)' : 'var(--accent-quiet)',
        border: '2px solid',
        borderColor: active || done ? 'var(--accent)' : 'var(--hairline-strong)',
      }}
    >
      {n}
    </Box>
  );
}

function Step({
  n,
  title,
  state,
  hint,
  summary,
  children,
}: {
  n: number;
  title: string;
  state: StepState;
  hint?: string;
  /** What this row holds once filled — shown in the status cell. */
  summary?: string;
  children: ReactNode;
}): JSX.Element {
  const { selected, panel, onSelect } = useContext(SetupPanelContext);
  const active = selected === n;
  return (
    <>
      <Box
        component="tr"
        tabIndex={0}
        aria-current={active ? 'step' : undefined}
        onClick={() => onSelect(n)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(n);
          }
        }}
        sx={{
          'cursor': 'pointer',
          'bgcolor': active ? 'var(--accent-quiet)' : 'transparent',
          '&:hover': {
            bgcolor: active ? 'var(--accent-quiet)' : 'var(--bg-hover, rgba(127,127,127,0.06))',
          },
          '&:focus-visible': { outline: '2px solid var(--accent)', outlineOffset: -2 },
          '&:last-of-type td, &:last-of-type th': { borderBottom: 0 },
        }}
      >
        <Box component="td" sx={ROW_CELL}>
          <StepNumber n={n} state={state} active={active} />
        </Box>
        <Box component="th" scope="row" sx={{ ...ROW_CELL, textAlign: 'start', fontWeight: 400 }}>
          <Typography
            id={`camera-step-${n}`}
            component="h3"
            variant="subtitle2"
            sx={{ fontWeight: active ? 800 : 600, lineHeight: 1.3 }}
          >
            {title}
          </Typography>
        </Box>
        <Box component="td" sx={ROW_CELL}>
          <RowStatus state={state} summary={summary} />
        </Box>
      </Box>
      {panel !== null &&
        createPortal(
          <Box component="section" hidden={!active} aria-labelledby={`camera-step-${n}`}>
            <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ mb: 1.5 }}>
              <StepNumber n={n} state={state} active />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography
                  component="p"
                  variant="subtitle1"
                  sx={{ fontWeight: 700, lineHeight: 1.3 }}
                >
                  {title}
                </Typography>
                {hint && (
                  <Typography variant="body2" color="text.secondary">
                    {hint}
                  </Typography>
                )}
              </Box>
            </Stack>
            {children}
          </Box>,
          panel,
        )}
    </>
  );
}

const mono = { dir: 'ltr' as const, style: { fontFamily: 'var(--font-mono)' } };

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

export function CameraSettingsPage(): JSX.Element {
  const { id } = useParams();
  const navigate = useNavigate();
  const notify = useNotify();
  const queryClient = useQueryClient();
  const mode: 'new' | 'edit' = id === undefined ? 'new' : 'edit';

  const camera = useCameraRegistryStore(selectCameraById(id ?? ''));
  const hydrated = useCameraRegistryStore((s) => s.hydrated);
  const add = useCameraRegistryStore((s) => s.add);
  const update = useCameraRegistryStore((s) => s.update);

  // ★ THE DRAFT: a new camera edits the persisted draft store (so the editor round
  //   trip and a reload keep it); an existing camera edits local state seeded once
  //   from its row (the router re-keys the page per camera).
  const storedDraft = useCameraDraftStore((s) => s.draft);
  const patchStored = useCameraDraftStore((s) => s.patch);
  const clearStored = useCameraDraftStore((s) => s.clear);
  const [local, setLocal] = useState<Draft>(() =>
    camera !== undefined ? draftFromCamera(camera) : EMPTY_DRAFT,
  );
  const draft: Draft = mode === 'new' ? storedDraft : local;
  const patch = (changes: Partial<Draft>): void => {
    if (mode === 'new') patchStored(changes);
    else setLocal((d) => ({ ...d, ...changes }));
    setErrors([]);
  };
  const [errors, setErrors] = useState<CameraValidationError[]>([]);
  const [saving, setSaving] = useState(false);
  // ★ The panel follows the next empty row until the operator picks one — or
  //   starts working in the panel, which pins it so filling row 1 does not
  //   swing the panel to row 2 under the cursor.
  const [chosenStep, setChosenStep] = useState<number | null>(null);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]): void =>
    patch({ [k]: v } as Partial<Draft>);
  const setCal = (k: CalibrationKey, v: string): void =>
    patch({ calibration: { ...draft.calibration, [k]: v } });

  // An existing camera whose row arrives after the first render (a cold deep link).
  useEffect(() => {
    if (mode === 'edit' && camera !== undefined && local.name === '' && camera.name !== '') {
      setLocal(draftFromCamera(camera));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed once the row arrives
  }, [camera?.id]);

  // ── what the server already holds for this camera ───────────────────────────
  // ★ For an EXISTING camera these come from its row; for a draft, from the draft.
  const projectId = draft.project_id ? asUuid(draft.project_id) : null;
  const frameId = draft.frame_image_id ? asUuid(draft.frame_image_id) : null;
  const lutSite = draft.lut_site;
  const frame = useImage(frameId);
  const frameCamera = useImageCamera(frameId);
  const gcps = useGcps(frameId);
  const dem = useProjectDem(projectId);
  // ★ `GET /projects/{id}/dem` answers for THIS project only — `active` is the fact.
  const hasDem = dem.data?.active === true;
  // ★ The frame's station holds what the solves read; fx/fy there is the truth.
  // ★ A blank field of view is fine in no-calibration mode (2026-09-09, owner
  //   ask): the focal solve starts from a default 60° seed with a wide bracket.
  //   The mode alone is the intrinsics; the typed angle only moves the seed.
  const frameHasIntrinsics =
    frameCamera.data?.configured === true &&
    ((frameCamera.data.fx !== null && frameCamera.data.fy !== null) ||
      frameCamera.data.no_calibration === true);

  // ★ GEO-DRIFT C2/C3 — NO CALIBRATION: the focal is SOLVED from the control
  //   points, seeded by the field of view at step 3. The station (the frame's
  //   camera row) is the truth; the form mirrors it for an existing camera.
  const noCalibration = draft.no_calibration;
  useEffect(() => {
    // ★ BOTH MODES (2026-09-09). A DRAFT edits the persisted draft store, and its
    //   `no_calibration` used to stay false while the station said true — so the
    //   next station sync (any typed change) wrote the mode OFF again. The station
    //   is the truth; the form — draft or row — mirrors it.
    if (frameCamera.data?.configured && frameCamera.data.no_calibration && !draft.no_calibration) {
      patch({ no_calibration: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed once the station arrives
  }, [frameCamera.data?.no_calibration]);
  const fovSeed = draft.fov_deg.trim() !== '' ? Number(draft.fov_deg) : null;
  const fovSeedOk = fovSeed !== null && Number.isFinite(fovSeed) && fovSeed > 0 && fovSeed < 180;
  const library = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
    staleTime: 30_000,
    enabled: lutSite !== null,
  });
  const lutEntry = (library.data ?? []).find((e) => e.site_name === lutSite);
  // ── the drift watch: frozen on THIS frame, watched in the background ─────────
  // ★ THE FRAME THE CONTROL POINTS SIT ON IS THE FROZEN DRIFT FRAME (2026-09-08,
  //   owner decision). The reference is made here — the moment the lookup table
  //   is built from the frame, and again whenever a new frame is chosen — and the
  //   server watches it from then on. The monitoring page only reads the verdict.
  const drift = useCameraDriftFreeze(mode === 'edit' ? (id ?? null) : null);
  const freezeDriftAndTell = async (target?: string): Promise<void> => {
    const { outcome, error } = await drift.freeze(target);
    if (outcome !== null) {
      notify(
        `${t('Drift reference frozen on the frame')} · ${t('{n} landmarks').replace('{n}', String(outcome.n_landmarks))} · ${t('watching in the background')}`,
        { severity: 'success' },
      );
    } else if (error !== null) {
      notify(`${t('The drift reference could not be frozen:')} ${error}`, { severity: 'warning' });
    }
  };
  const driftWatch = camera?.desired?.watch ?? null;
  const driftRefs = useDriftReferences();
  // ★ ASK EVEN WITH NO DESIRED WATCH (2026-09-10 fix): a reference frozen before
  //   the row carried its intent — or one started from the drift page — is real
  //   and running, and gating the query on `desired.watch` hid it from this row.
  const driftMonitors = useDriftMonitors(mode === 'edit');
  // ★ RESOLVED THE SAME WAY THE MONITORING PAGE RESOLVES IT: by the row's ref id
  //   when it has one, else by SOURCE. Row 8 said "not frozen yet" for a camera
  //   whose watch was running and reporting MOVED, because only the first path
  //   was tried — the two pages must never disagree about the same camera.
  const driftReference =
    (driftRefs.data ?? []).find((r) => r.ref_id === driftWatch?.ref_id) ??
    (camera !== undefined
      ? ((driftRefs.data ?? []).find((r) => r.source === camera.source) ?? null)
      : null);
  const driftMonitor =
    (driftMonitors.data ?? []).find((m) => m.ref_id === driftWatch?.ref_id) ??
    (camera !== undefined
      ? ((driftMonitors.data ?? []).find(
          (m) => m.source === camera.source && m.status === 'running',
        ) ??
        (driftMonitors.data ?? []).find((m) => m.source === camera.source) ??
        null)
      : null);
  /** The reference this row acts on: the row's own, else the one found by source. */
  const activeRefId = driftWatch?.ref_id ?? driftMonitor?.ref_id ?? driftReference?.ref_id ?? null;
  const driftVerdict = driftMonitor?.last ?? null;
  const driftWatching = driftMonitor?.status === 'running';
  // ── the watch's own controls (row 8, 2026-09-10) ─────────────────────────────
  const [watchBusy, setWatchBusy] = useState(false);
  const watchInterval = driftWatch?.interval_s ?? driftMonitor?.interval_s ?? 30;
  /** Restart the watch at `intervalS` — a change of cadence is a restart. */
  const setWatch = async (running: boolean, intervalS: number): Promise<void> => {
    if (activeRefId === null || id === undefined) return;
    setWatchBusy(true);
    try {
      if (running) await driftApi.startMonitor(activeRefId, intervalS, id);
      else await driftApi.stopMonitor(activeRefId, id);
      // The registry row mirrors the desired state the server now holds.
      useCameraRegistryStore.setState((st) => ({
        cameras: st.cameras.map((c) =>
          c.id === id
            ? {
                ...c,
                desired: {
                  watch: running ? { ref_id: activeRefId, interval_s: intervalS } : null,
                  detect: c.desired?.detect ?? null,
                  feed: c.desired?.feed ?? false,
                },
              }
            : c,
        ),
      }));
      void queryClient.invalidateQueries({ queryKey: qk.drift.all() });
      notify(
        running
          ? `${t('Drift watch running')} · ${t('every')} ${intervalS} s`
          : t('Drift watch paused. The reference stays frozen.'),
        { severity: 'success' },
      );
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), { severity: 'error' });
    } finally {
      setWatchBusy(false);
    }
  };
  const driftSummary =
    activeRefId === null
      ? undefined
      : `${driftWatching ? t('watching') : t('paused')} · ${t('every')} ${watchInterval} s${
          driftVerdict !== null ? ` · ${driftVerdict.status}` : ''
        }`;

  const build = useCameraLutBuild({
    // ★ A draft has no row to write to: the hook hands the site name back and the
    //   draft keeps it until "Add camera" posts it.
    cameraId: mode === 'edit' ? (id ?? null) : null,
    imageId: frameId,
    siteName: draft.name,
    onBuilt: (site) => {
      // The draft keeps it until "Add camera"; an existing camera's row was
      // written by the hook — the form mirrors it so the step reads Done.
      patch({ lut_site: site });
      notify(t('The lookup table is built and saved to the camera.'), { severity: 'success' });
      // ★ The drift reference follows the table (2026-09-08): frozen on the frame
      //   it was built from, watched from now on. A draft freezes on Add camera.
      if (mode === 'edit' && id !== undefined) void freezeDriftAndTell();
    },
  });
  const placed = gcps.data?.total ?? 0;
  const hasFrame = frameId !== null;
  const hasLut = lutSite !== null;
  // ★ FOUR POINTS UNLOCK THE BUILD (owner ask). Anything else missing — the DEM, the
  //   calibration — is NAMED below, and the server refuses with the exact reason
  //   rather than the page second-guessing it behind a disabled button.
  const canBuild = hasFrame && placed >= MIN_GCPS_FOR_LUT && !build.building;
  const stillNeeded: string[] = [
    !hasFrame ? t('a frame') : null,
    hasFrame && placed < MIN_GCPS_FOR_LUT
      ? `${MIN_GCPS_FOR_LUT - placed} ${t('more control point(s)')}`
      : null,
    !hasDem ? t('a DEM') : null,
    hasFrame && frameCamera.isSuccess && !frameHasIntrinsics
      ? t('calibration (fx, fy — or no-calibration mode)')
      : null,
  ].filter((x): x is string => x !== null);

  // ── the map picker ──────────────────────────────────────────────────────────
  const providersQuery = useProviders();
  const mapProvider = useMemo(() => {
    const items = providersQuery.data?.items ?? [];
    const usable = items.filter((p) => p.configured && p.allowed !== false);
    return (usable.find((p) => p.is_default) ?? usable[0])?.name;
  }, [providersQuery.data]);
  const cameras = useCameraRegistryStore((s) => s.cameras);
  const fallbackCenter = useMemo((): LatLon => {
    if (cameras.length === 0) return { lat: 33.9, lon: 35.9 };
    return {
      lat: cameras.reduce((a, c) => a + c.lat, 0) / cameras.length,
      lon: cameras.reduce((a, c) => a + c.lon, 0) / cameras.length,
    };
  }, [cameras]);
  const typedPosition = useMemo((): LatLon | null => {
    const lat = parseCoordinateValue(draft.lat, 'lat');
    const lon = parseCoordinateValue(draft.lon, 'lon');
    return lat === null || lon === null ? null : { lat, lon };
  }, [draft.lat, draft.lon]);
  const pick = (p: LatLon): void => patch({ lat: p.lat.toFixed(6), lon: p.lon.toFixed(6) });
  const pastePair = (e: ReactClipboardEvent): void => {
    const pair = parseLocation(e.clipboardData.getData('text'));
    if (pair === null) return;
    e.preventDefault();
    pick(pair);
  };
  const swap = (): void => patch({ lat: draft.lon, lon: draft.lat });

  // ── device scan (any capture card on this machine: USB, HDMI, BNC) ──────────
  const [devices, setDevices] = useState<LiveDeviceInfo[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);
  const scan = (): void => {
    setScanning(true);
    liveApi
      .listDevices()
      .then((page) => {
        setDevices(page.items);
        setScanned(true);
      })
      .catch((err: unknown) =>
        notify(err instanceof ApiError ? err.message : String(err), { severity: 'error' }),
      )
      .finally(() => setScanning(false));
  };
  const kind = connectionKind(draft.connection);
  // The address split into the protocol the operator picks and the rest they type.
  // ★ A PROTOCOL CHOSEN BEFORE THE ADDRESS IS REMEMBERED. The draft holds a whole
  //   URL or nothing at all (a bare "ws://" is not an address and must not raise
  //   the error that comes with one) — so a pick made while the field is empty
  //   lives here until there is an address to carry it. Once there is one, the
  //   address IS the truth: typing a full URL moves the picker with it.
  const [pickedVideoScheme, setPickedVideoScheme] = useState('');
  const [pickedDataScheme, setPickedDataScheme] = useState('');
  const streamUrl = splitScheme(draft.source, STREAM_SCHEMES, pickedVideoScheme || 'rtsp://');
  const dataUrl = splitScheme(draft.dataUrl, DATA_SCHEMES, pickedDataScheme || 'http://');
  const chooseConnection = (next: CameraConnection): void => {
    set('connection', next);
    if (connectionKind(next).needs === 'device' && !scanned && !scanning) scan();
  };

  // ── validation + persistence ────────────────────────────────────────────────
  const checkDraft = (): ReturnType<typeof validateCamera> =>
    validateCamera({
      name: draft.name,
      lat: draft.lat,
      lon: draft.lon,
      connection: draft.connection,
      heading_deg: draft.heading_deg,
      fov_deg: draft.fov_deg,
      calibration: draft.calibration,
      lut_site: draft.lut_site ?? undefined,
      project_id: draft.project_id ?? undefined,
      frame_image_id: draft.frame_image_id ?? undefined,
      ...integrationOf(draft),
    });

  /** The draft's project — created quietly the first time the DEM or the frame needs one. */
  const ensureProject = async (): Promise<Uuid | null> => {
    if (projectId !== null) return projectId;
    setSaving(true);
    try {
      const label = draft.name.trim() || camera?.name || t('New camera');
      const project = await projectsApi.create({
        name: `${t('Camera')}: ${label}`,
        description: t(
          'Backing project for a registered camera — its DEM, frame and control points.',
        ),
        tags: ['camera'],
      });
      if (mode === 'edit' && id !== undefined) await update(id, { project_id: project.id });
      patch({ project_id: project.id });
      return project.id;
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), { severity: 'error' });
      return null;
    } finally {
      setSaving(false);
    }
  };

  /**
   * The last press. A NEW camera: the whole draft becomes one row on the server
   * and the draft is cleared. An EXISTING one: its typed fields are patched.
   * Resolves with the camera, or null when the draft was refused.
   */
  const submit = async (): Promise<RegisteredCamera | null> => {
    const checked = checkDraft();
    if (!checked.ok) {
      setErrors(checked.errors);
      return null;
    }
    setSaving(true);
    try {
      if (mode === 'new') {
        const created = await add(checked.value);
        clearStored();
        notify(`“${created.name}” ${t('is added to the server.')}`, { severity: 'success' });
        // ★ A draft that already carries its frame AND its table gets its drift
        //   reference the moment the row exists (2026-09-08).
        if (created.lut_site && created.frame_image_id) await freezeDriftAndTell(created.id);
        navigate('/cameras');
        return created;
      }
      const { calibration, ...rest } = checked.value;
      await update(id as string, { ...rest, calibration });
      const saved = useCameraRegistryStore.getState().cameras.find((c) => c.id === id) ?? null;
      if (saved !== null) {
        notify(`“${saved.name}” ${t('is saved on the server.')}`, { severity: 'success' });
        navigate('/cameras');
      }
      return saved;
    } catch (err) {
      setErrors([
        {
          field: 'row',
          message: err instanceof Error ? err.message : t('The server refused the camera.'),
        },
      ]);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const discardDraft = (): void => {
    clearStored();
    navigate('/cameras');
  };

  // ── the frame's station follows the form ────────────────────────────────────
  // ★ The calibration and position typed here ARE the frame's camera (the auto
  //   estimate and the lookup table read the station, not the form). Whenever they
  //   change with a frame in place, the station is rewritten — quietly, a moment
  //   after typing stops, and only when the form is valid.
  const stationKey = JSON.stringify([
    frameId,
    draft.lat,
    draft.lon,
    CALIBRATION_KEYS.map((k) => draft.calibration[k] ?? ''),
    draft.no_calibration,
    draft.fov_deg,
  ]);
  const stationWritten = useRef<string | null>(null);
  useEffect(() => {
    if (frameId === null || frame.data === undefined) return;
    if (stationWritten.current === null) {
      // First sight of this frame: the server already matches the form (adoptFrame
      // wrote it, or the row was seeded from it) — nothing to write.
      stationWritten.current = stationKey;
      return;
    }
    if (stationWritten.current === stationKey) return;
    const checked = checkDraft();
    if (!checked.ok) return;
    const lat = parseCoordinateValue(draft.lat, 'lat');
    const lon = parseCoordinateValue(draft.lon, 'lon');
    if (lat === null || lon === null) return;
    const cal = checked.value.calibration;
    const image = frame.data;
    const timer = window.setTimeout(() => {
      stationWritten.current = stationKey;
      imageCameraApi
        .put(image.id, {
          fx: cal?.fx ?? null,
          fy: cal?.fy ?? null,
          cx: cal?.cx ?? image.width / 2,
          cy: cal?.cy ?? image.height / 2,
          k1: cal?.k1 ?? null,
          k2: cal?.k2 ?? null,
          p1: cal?.p1 ?? null,
          p2: cal?.p2 ?? null,
          k3: cal?.k3 ?? null,
          img_w: image.width,
          img_h: image.height,
          lat,
          lon,
          mast_offset_m: cal?.mast_offset_m ?? null,
          tilt_deg: cal?.tilt_deg ?? null,
          auto_gcp_enabled: frameCamera.data?.auto_gcp_enabled ?? false,
          // ★ GEO-DRIFT C2: the mode and its seed travel with the station.
          no_calibration: noCalibration,
          fov_h_deg: noCalibration && fovSeedOk ? fovSeed : null,
          fov_v_deg: null,
        })
        .then(() => queryClient.invalidateQueries({ queryKey: qk.imageCamera(image.id) }))
        .catch((err: unknown) =>
          notify(err instanceof Error ? err.message : String(err), { severity: 'error' }),
        );
    }, 700);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the station's inputs
  }, [stationKey, frame.data?.id]);

  // ── the frame ───────────────────────────────────────────────────────────────
  const [frameBusy, setFrameBusy] = useState<null | 'capture' | 'upload' | 'library'>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  /** The chosen frame becomes the camera's: its station is written (so the editor
   *  opens directly) and the draft — or the row — points at it. */
  // ★ A NEW FRAME OVER ONE THAT HAS CONTROL POINTS (2026-09-09, owner ask): ask
  //   whether the camera moved BEFORE adopting. The answer decides whether the
  //   points are carried over and the table kept, or the table is detached.
  const [pendingFrame, setPendingFrame] = useState<ImageRead | null>(null);
  const [adopting, setAdopting] = useState(false);
  const adoptFrame = async (image: ImageRead, decision?: FrameChangeDecision): Promise<void> => {
    const previousFrame = frameId;
    if (
      decision === undefined &&
      previousFrame !== null &&
      previousFrame !== image.id &&
      placed > 0
    ) {
      setPendingFrame(image);
      return;
    }
    const checked = checkDraft();
    const cal = checked.ok ? checked.value.calibration : undefined;
    const lat = parseCoordinateValue(draft.lat, 'lat');
    const lon = parseCoordinateValue(draft.lon, 'lon');
    // ★ GEO-DRIFT C3: no measured focal length is NOT a guessed one. With a field
    //   of view at step 3 the frame goes into no-calibration mode — the focal is
    //   solved from the control points, the angle is only its seed.
    const noCal = noCalibration || ((cal?.fx === null || cal?.fx === undefined) && fovSeedOk);
    if (noCal && !noCalibration) patch({ no_calibration: true });
    const fx = noCal ? null : (cal?.fx ?? null);
    const fy = noCal ? null : (cal?.fy ?? null);
    await imageCameraApi.put(image.id, {
      fx,
      fy,
      cx: cal?.cx ?? image.width / 2,
      cy: cal?.cy ?? image.height / 2,
      k1: cal?.k1 ?? null,
      k2: cal?.k2 ?? null,
      p1: cal?.p1 ?? null,
      p2: cal?.p2 ?? null,
      k3: cal?.k3 ?? null,
      img_w: image.width,
      img_h: image.height,
      lat,
      lon,
      mast_offset_m: cal?.mast_offset_m ?? null,
      tilt_deg: cal?.tilt_deg ?? null,
      auto_gcp_enabled: false,
      no_calibration: noCal,
      fov_h_deg: noCal && fovSeedOk ? fovSeed : null,
      fov_v_deg: null,
    });
    void queryClient.invalidateQueries({ queryKey: qk.imageCamera(image.id) });
    stationWritten.current = null; // the next render seeds the sync from this write
    // ★ IT MOVED: the old table was solved for the old aim — detach it, and stop
    //   the watch that guards the old reference. Nothing may look finished here.
    const detachTable = decision === 'moved' && hasLut;
    if (mode === 'edit' && id !== undefined) {
      // ★ The registry clears a field with `undefined` (the PATCH then carries null).
      await update(id, {
        frame_image_id: image.id,
        ...(detachTable ? { lut_site: undefined } : {}),
      });
      if (detachTable && driftWatch !== null) {
        await driftApi.stopMonitor(driftWatch.ref_id, id).catch(() => undefined);
        void queryClient.invalidateQueries({ queryKey: qk.drift.all() });
      }
    }
    patch({ frame_image_id: image.id, ...(detachTable ? { lut_site: null } : {}) });
    // ★ SAME AIM: the previous frame's points are valid at the same pixels — carry
    //   them over instead of asking for them again.
    let carried = 0;
    if (decision === 'same-aim' && previousFrame !== null) {
      try {
        const result = await gcpsApi.copyFrom(image.id, previousFrame);
        carried = result.copied;
        void queryClient.invalidateQueries({ queryKey: qk.gcps.all() });
      } catch (err) {
        notify(
          `${t('The control points could not be carried over:')} ${err instanceof Error ? err.message : String(err)}`,
          { severity: 'warning' },
        );
      }
    }
    notify(
      decision === 'same-aim'
        ? t('The frame is saved to the camera — {n} control points carried over.').replace(
            '{n}',
            String(carried),
          )
        : detachTable
          ? t(
              'The frame is saved to the camera. The lookup table was detached — place the control points and rebuild it.',
            )
          : t('The frame is saved to the camera — place its control points next.'),
      { severity: 'success' },
    );
    // ★ A NEW FRAME RE-FREEZES THE DRIFT REFERENCE (2026-09-08, owner decision):
    //   the table's pose still holds — only the picture the landmarks are matched
    //   in is new. Not after a move: there is no table left to freeze on.
    if (mode === 'edit' && id !== undefined && hasLut && !detachTable) await freezeDriftAndTell();
  };
  const decideFrameChange = async (decision: FrameChangeDecision): Promise<void> => {
    if (pendingFrame === null) return;
    setAdopting(true);
    try {
      await adoptFrame(pendingFrame, decision);
      setPendingFrame(null);
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), { severity: 'error' });
    } finally {
      setAdopting(false);
    }
  };

  // ★ CHOOSE THE FRAME FROM INSIDE THE LIVE CAMERA (2026-09-09, owner ask). The
  //   button opens the live picture; the surveyor presses "Capture this frame" at
  //   the moment they want, sees the frozen result, and only then uses it — or
  //   tries again. The blind grab is gone.
  const [capture, setCapture] = useState<{ source: string; projectId: Uuid } | null>(null);
  const captureNow = async (): Promise<void> => {
    const { source } = integrationOf(draft);
    if (source === '') {
      notify(t('This connection has no video to capture from — upload a photo instead.'), {
        severity: 'warning',
      });
      return;
    }
    const pid = await ensureProject();
    if (pid === null) return;
    setCapture({ source, projectId: pid });
  };
  /** The chosen frame: into the project, then adopted as the camera's. */
  const useCapturedFrame = async (shot: { filename: string }): Promise<void> => {
    if (capture === null) return;
    setFrameBusy('capture');
    try {
      const image = await captureLibraryApi.importIntoProject(shot.filename, capture.projectId);
      await adoptFrame(image);
    } finally {
      setFrameBusy(null);
    }
  };

  const uploadFile = async (file: File): Promise<void> => {
    const pid = await ensureProject();
    if (pid === null) return;
    setFrameBusy('upload');
    try {
      const response = await imagesApi.upload({ file, project_id: pid });
      const image = isUploadAccepted(response) ? response.image : response;
      await adoptFrame(image);
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), { severity: 'error' });
    } finally {
      setFrameBusy(null);
    }
  };

  const openLibrary = async (): Promise<void> => {
    const pid = await ensureProject();
    if (pid !== null) setLibraryOpen(true);
  };

  /** Into the editor — the draft (persisted) or the row (patched first) waits here. */
  const placePoints = async (): Promise<void> => {
    if (projectId === null || frameId === null) return;
    if (mode === 'edit') {
      const checked = checkDraft();
      if (checked.ok) {
        const { calibration, ...rest } = checked.value;
        await update(id as string, { ...rest, calibration }).catch(() => undefined);
      }
    }
    // ★ The editor is addressed by the camera (2026-09-04): `/cameras/:id/editor`.
    navigate(mode === 'new' ? '/cameras/new/editor' : `/cameras/${id}/editor`);
  };

  // ── guards ──────────────────────────────────────────────────────────────────
  if (mode === 'edit' && camera === undefined) {
    if (!hydrated) {
      return (
        <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
          <CircularProgress />
        </Box>
      );
    }
    return (
      <EmptyState
        title={t('This camera is not on the server')}
        description={t('It may have been removed from another machine.')}
        primaryAction={{
          label: t('Back to the camera workspace'),
          onClick: () => navigate('/cameras'),
        }}
      />
    );
  }

  const isNew = mode === 'new';
  const swapHint = errors.some((e) => e.hint === 'swap');
  const rowError = errorFor(errors, 'row');
  const calibrationErrors = errors.filter((e) => e.field === 'calibration');
  const calibrationEntered = CALIBRATION_KEYS.some(
    (k) => (draft.calibration[k] ?? '').trim() !== '',
  );
  const positionDone = typedPosition !== null;
  const integration = integrationOf(draft);
  const connectionDone = integration.source !== '' || integration.data_source !== '';
  const rowStates: StepState[] = [
    draft.name.trim() !== '' ? 'done' : 'todo',
    connectionDone ? 'done' : 'todo',
    positionDone ? 'done' : 'todo',
    hasDem ? 'done' : 'todo',
    calibrationEntered || noCalibration ? 'done' : 'optional',
    hasFrame ? 'done' : 'todo',
    hasLut ? 'done' : 'todo',
    // ★ Row 8 (owner ask 2026-09-10): the watch is its own row. A draft cannot
    //   watch yet — its reference freezes on Add camera — so it reads optional.
    isNew ? 'optional' : driftWatching ? 'done' : 'todo',
  ];
  const selectedStep = chosenStep ?? nextRow(rowStates);
  const pinStep = (): void => {
    if (chosenStep === null) setChosenStep(selectedStep);
  };

  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: { xs: 'auto', md: 'hidden' },
      }}
    >
      <Container
        maxWidth="xl"
        sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', py: 2 }}
      >
        {/* ── header ─────────────────────────────────────────────────────────── */}
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1.5 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.12em', color: 'var(--accent)' }}
            >
              {t('CAMERA WORKSPACE · SETUP PIPELINE')}
            </Typography>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              {isNew ? draft.name.trim() || t('New camera') : camera?.name}
            </Typography>
          </Box>
          {/* ★ THE WHOLE CAMERA, ONE FILE (2026-09-12, owner ask). Everything on
              this page and everything the steps below it produced — the frame, the
              control points, the DEM, its calibration, the lookup table, the drift
              reference — in one folder. Only once the camera exists on the server:
              a camera still being typed has nothing to export yet. */}
          {!isNew && camera !== undefined && (
            <Tooltip
              describeChild
              title={t(
                'Everything this camera is: settings, frame, control points, DEM, calibration, lookup table and drift reference',
              )}
            >
              <Button
                variant="outlined"
                startIcon={<FolderZipOutlinedIcon />}
                component="a"
                href={camerasApi.exportUrl(asUuid(camera.id))}
                download
                sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
              >
                {t('Download the settings')}
              </Button>
            </Tooltip>
          )}
          <Button variant="text" startIcon={<ArrowBackIcon />} onClick={() => navigate('/cameras')}>
            {t('Camera workspace')}
          </Button>
        </Stack>

        <SetupStatus states={rowStates} onNext={setChosenStep} />

        {rowError !== undefined && (
          <Alert severity="error" variant="outlined" sx={{ mb: 2 }}>
            {rowError}
          </Alert>
        )}

        <SetupTable selected={selectedStep} onSelect={setChosenStep} onTouch={pinStep}>
          {/* ── 1 name ────────────────────────────────────────────────────────── */}
          <Step
            n={1}
            title={t('Name the camera')}
            state={draft.name.trim() !== '' ? 'done' : 'todo'}
            summary={draft.name.trim()}
          >
            <TextField
              size="small"
              label={t('Name')}
              placeholder={t('e.g. North field gate')}
              value={draft.name}
              onChange={(e) => set('name', e.target.value)}
              error={errorFor(errors, 'name') !== undefined}
              helperText={
                errorFor(errors, 'name') ?? t('Also the name of its lookup table bundle.')
              }
              autoFocus={isNew && draft.name === ''}
              fullWidth
            />
          </Step>

          {/* ── 2 connection ──────────────────────────────────────────────────── */}
          <Step
            n={2}
            title={t('How does it connect?')}
            state={connectionDone ? 'done' : 'todo'}
            summary={
              connectionDone
                ? `${t(kind.label)} · ${integration.source || integration.data_source}`
                : undefined
            }
            hint={t(kind.hint)}
          >
            <ToggleButtonGroup
              exclusive
              size="small"
              value={draft.connection}
              onChange={(_e, v: CameraConnection | null) => {
                if (v !== null) chooseConnection(v);
              }}
              aria-label={t('Connection type')}
              sx={{ 'flexWrap': 'wrap', 'mb': 1.5, '& .MuiToggleButton-root': { px: 1.5 } }}
            >
              {CONNECTION_KINDS.map((k) => (
                <ToggleButton key={k.key} value={k.key} aria-label={t(k.label)}>
                  {t(k.label)}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>

            {kind.needs === 'address' || kind.needs === 'either' ? (
              /* ★ THE PROTOCOL IS CHOSEN, NOT TYPED (2026-09-11, owner ask). The
                 dropdown lists exactly what this server can open — the capture's
                 own schemes for video, the data feed's four for detections — so a
                 setup that saves is a setup that can connect. */
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1} alignItems="flex-start">
                  <TextField
                    size="small"
                    select
                    label={t('Protocol')}
                    value={streamUrl.scheme}
                    onChange={(e) => {
                      setPickedVideoScheme(e.target.value);
                      set('source', joinScheme(e.target.value, streamUrl.rest));
                    }}
                    sx={{ width: 128, flexShrink: 0 }}
                    inputProps={{ 'aria-label': t('Video protocol') }}
                  >
                    {schemeOptions(STREAM_SCHEMES, streamUrl.scheme).map((v) => (
                      <MenuItem key={v} value={v} sx={{ fontFamily: 'var(--font-mono)' }}>
                        {v}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    size="small"
                    label={t('Video address')}
                    placeholder="192.168.1.20:8080/stream"
                    value={streamUrl.rest}
                    onChange={(e) => set('source', joinScheme(streamUrl.scheme, e.target.value))}
                    error={errorFor(errors, 'source') !== undefined}
                    helperText={
                      errorFor(errors, 'source') ??
                      t(
                        'Host, port and path — the protocol is the box on the left. Leave it empty if this device only sends detection data.',
                      )
                    }
                    inputProps={mono}
                    fullWidth
                  />
                </Stack>
                <Stack direction="row" spacing={1} alignItems="flex-start">
                  <TextField
                    size="small"
                    select
                    label={t('Protocol')}
                    value={dataUrl.scheme}
                    onChange={(e) => {
                      setPickedDataScheme(e.target.value);
                      set('dataUrl', joinScheme(e.target.value, dataUrl.rest));
                    }}
                    sx={{ width: 128, flexShrink: 0 }}
                    inputProps={{ 'aria-label': t('Data feed protocol') }}
                  >
                    {schemeOptions(DATA_SCHEMES, dataUrl.scheme).map((v) => (
                      <MenuItem key={v} value={v} sx={{ fontFamily: 'var(--font-mono)' }}>
                        {v}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    size="small"
                    label={t('Data feed (optional)')}
                    placeholder="192.168.1.20:9000/detections"
                    value={dataUrl.rest}
                    onChange={(e) => set('dataUrl', joinScheme(dataUrl.scheme, e.target.value))}
                    error={errorFor(errors, 'data_source') !== undefined}
                    helperText={
                      errorFor(errors, 'data_source') ??
                      t(
                        'If the device also SENDS detections (JSON or CSV lines with lat/lon), its points land straight on the map. http(s) is polled; ws(s) and tcp are pushed by the sender.',
                      )
                    }
                    inputProps={mono}
                    fullWidth
                  />
                </Stack>
              </Stack>
            ) : kind.needs === 'serial' ? (
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1}>
                  <TextField
                    size="small"
                    label={t('Serial port')}
                    placeholder="/dev/ttyUSB0"
                    value={draft.serialPort}
                    onChange={(e) => set('serialPort', e.target.value)}
                    error={errorFor(errors, 'data_source') !== undefined}
                    helperText={errorFor(errors, 'data_source')}
                    inputProps={mono}
                    fullWidth
                  />
                  <TextField
                    size="small"
                    select
                    label={t('Baud')}
                    value={draft.serialBaud}
                    onChange={(e) => set('serialBaud', e.target.value)}
                    sx={{ width: 140 }}
                  >
                    {['9600', '19200', '38400', '57600', '115200', '230400'].map((b) => (
                      <MenuItem key={b} value={b}>
                        {b}
                      </MenuItem>
                    ))}
                  </TextField>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {t(
                    'A serial or UART line carries DATA, not video: the device sends detection lines and their points are plotted on the map.',
                  )}
                </Typography>
              </Stack>
            ) : (
              <Box>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<RefreshIcon />}
                    onClick={scan}
                    disabled={scanning}
                  >
                    {scanning ? t('Scanning…') : t('Scan again')}
                  </Button>
                  <Typography variant="caption" color="text.secondary">
                    {t('Capture cards and cameras on this machine.')}
                  </Typography>
                </Stack>
                {devices.length > 0 && (
                  <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap', rowGap: 1 }}>
                    {devices.map((d) => (
                      <Chip
                        key={d.id}
                        icon={<UsbIcon />}
                        label={d.label}
                        variant={draft.source === d.id ? 'filled' : 'outlined'}
                        color={draft.source === d.id ? 'primary' : 'default'}
                        onClick={() => {
                          patch({
                            source: d.id,
                            ...(draft.name.trim() === '' ? { name: d.label } : {}),
                          });
                        }}
                      />
                    ))}
                  </Stack>
                )}
                {scanned && devices.length === 0 && !scanning && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', mt: 1 }}
                  >
                    {t('No capture devices found — is the camera plugged in?')}
                  </Typography>
                )}
                {errorFor(errors, 'source') !== undefined && (
                  <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
                    {t('Pick a device above — it becomes this camera’s source.')}
                  </Typography>
                )}
              </Box>
            )}
          </Step>

          {/* ── 3 position ────────────────────────────────────────────────────── */}
          <Step
            n={3}
            title={t('Where does the camera stand?')}
            state={positionDone ? 'done' : 'todo'}
            summary={
              typedPosition !== null
                ? `${typedPosition.lat.toFixed(5)}, ${typedPosition.lon.toFixed(5)}`
                : undefined
            }
            hint={t(
              'Click its spot on the map — or paste coordinates from Google Maps into either box below.',
            )}
          >
            {mapProvider !== undefined ? (
              <Suspense
                fallback={
                  <Box sx={{ height: 240, display: 'grid', placeItems: 'center' }}>
                    <CircularProgress size={22} />
                  </Box>
                }
              >
                <PositionPickerMap
                  value={typedPosition}
                  fallbackCenter={fallbackCenter}
                  provider={mapProvider}
                  onPick={pick}
                />
              </Suspense>
            ) : (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                {t('The map needs an imagery provider — type or paste the coordinates instead.')}
              </Typography>
            )}
            <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ mt: 1.5 }}>
              <TextField
                size="small"
                label={t('Latitude')}
                value={draft.lat}
                onChange={(e) => set('lat', e.target.value)}
                onPaste={pastePair}
                inputProps={{ inputMode: 'decimal', ...mono }}
                error={errorFor(errors, 'lat') !== undefined}
                helperText={errorFor(errors, 'lat') ?? t('north–south · -90 … 90')}
                fullWidth
              />
              <TextField
                size="small"
                label={t('Longitude')}
                value={draft.lon}
                onChange={(e) => set('lon', e.target.value)}
                onPaste={pastePair}
                inputProps={{ inputMode: 'decimal', ...mono }}
                error={errorFor(errors, 'lon') !== undefined}
                helperText={errorFor(errors, 'lon') ?? t('east–west · -180 … 180')}
                fullWidth
              />
            </Stack>
            {swapHint && (
              <Alert
                severity="warning"
                sx={{ mt: 1 }}
                action={
                  <Button color="inherit" size="small" startIcon={<SwapHorizIcon />} onClick={swap}>
                    {t('Swap')}
                  </Button>
                }
              >
                {t(
                  'Latitude and longitude look swapped. Nothing was changed — swap them if that is right.',
                )}
              </Alert>
            )}
            <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
              <TextField
                size="small"
                label={t('Compass (°)')}
                placeholder="0"
                value={draft.heading_deg}
                onChange={(e) => set('heading_deg', e.target.value)}
                error={errorFor(errors, 'heading_deg') !== undefined}
                helperText={
                  errorFor(errors, 'heading_deg') ?? `0 = ${t('north')} · 90 = ${t('east')}`
                }
                inputProps={{ inputMode: 'decimal', dir: 'ltr' }}
                fullWidth
              />
              <TextField
                size="small"
                label={t('FOV / View width (°)')}
                placeholder="60"
                value={draft.fov_deg}
                onChange={(e) => set('fov_deg', e.target.value)}
                error={errorFor(errors, 'fov_deg') !== undefined}
                helperText={errorFor(errors, 'fov_deg') ?? t('how wide it sees')}
                inputProps={{ inputMode: 'decimal', dir: 'ltr' }}
                fullWidth
              />
            </Stack>
          </Step>

          {/* ── 4 DEM ─────────────────────────────────────────────────────────── */}
          <Step
            n={4}
            title={t('Camera DEM')}
            state={hasDem ? 'done' : 'todo'}
            summary={hasDem ? t('DEM attached') : undefined}
            hint={t(
              'The elevation model every ray from this camera lands on — the lookup table cannot be built without it.',
            )}
          >
            {projectId !== null ? (
              <ProjectDemCard projectId={projectId} title={t('Elevation source')} />
            ) : (
              <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap">
                <Button
                  variant="contained"
                  startIcon={
                    saving ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <TerrainOutlinedIcon />
                    )
                  }
                  disabled={saving}
                  onClick={() => void ensureProject()}
                >
                  {t('Attach the camera’s DEM')}
                </Button>
                <Typography variant="caption" color="text.secondary">
                  {t(
                    'Opens the elevation source: upload a preprocessed DEM, process a new one, or pick one from the library.',
                  )}
                </Typography>
              </Stack>
            )}
          </Step>

          {/* ── 5 calibration ─────────────────────────────────────────────────── */}
          <Step
            n={5}
            title={t('Optional data — camera calibration')}
            state={calibrationEntered || noCalibration ? 'done' : 'optional'}
            summary={
              calibrationEntered
                ? t('Calibration typed')
                : noCalibration
                  ? `${t('No calibration')} · ${fovSeedOk ? `${fovSeed}°` : t('60° seed')}`
                  : undefined
            }
            hint={t(
              'Intrinsics and position. Without fx, fy, cx, cy the camera can still be watched and detections counted, but a lookup table cannot be built.',
            )}
          >
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.75 }}>
              <Typography variant="overline" sx={{ color: 'text.secondary', flex: 1 }}>
                {t('Intrinsics (pixels)')}
              </Typography>
            </Stack>
            {/* ★ GEO-DRIFT C3: "no calibration" does not mean "assume a focal" — it means
                RECOVER it. A focal fixed from a guessed angle was 37–61 m out in the
                study; solved from the points, 2 m from any seed between 50° and 120°. */}
            <FormControlLabel
              control={
                <Switch
                  checked={noCalibration}
                  onChange={(e) => patch({ no_calibration: e.target.checked })}
                  inputProps={{ 'aria-label': t('No calibration') }}
                />
              }
              label={
                <Box>
                  <Typography variant="body2">
                    {t('No calibration — solve the focal from the control points')}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {fovSeedOk
                      ? `${t('Seeded by the field of view at step 3')} (${fovSeed}°). ${t('Any angle in the right ballpark works — the solve recovers the focal.')}`
                      : t(
                          'No field of view at step 3 — the solve starts from a default 60° seed, which covers roughly 37°–125°.',
                        )}
                  </Typography>
                </Box>
              }
              sx={{ alignItems: 'flex-start', mb: 1.5, mx: 0 }}
            />
            {noCalibration && !fovSeedOk && (
              <Alert severity="info" variant="outlined" sx={{ mb: 1.5, py: 0 }}>
                {t(
                  'Type the camera’s field of view at step 3 only for a telephoto or an ultra-wide lens — the true sensor angle, not a spec sheet’s diagonal figure.',
                )}
              </Alert>
            )}
            {hasFrame && frameCamera.isSuccess && !frameHasIntrinsics && !noCalibration && (
              <Alert severity="warning" variant="outlined" sx={{ mb: 1.5, py: 0 }}>
                {t(
                  'The frame has no focal length yet — the auto estimate and the lookup table need fx and fy. Enter them, or switch on no-calibration mode above.',
                )}
              </Alert>
            )}
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' },
                gap: 1,
                mb: 1.5,
              }}
            >
              {(['fx', 'fy', 'cx', 'cy'] as const).map((k) => (
                <TextField
                  key={k}
                  size="small"
                  label={k}
                  value={draft.calibration[k] ?? ''}
                  onChange={(e) => setCal(k, e.target.value)}
                  disabled={noCalibration}
                  inputProps={{ inputMode: 'decimal', ...mono }}
                />
              ))}
            </Box>
            <Typography
              variant="overline"
              sx={{ color: 'text.secondary', display: 'block', mb: 0.75 }}
            >
              {t('Distortion (Brown–Conrady)')}
            </Typography>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(5, 1fr)' },
                gap: 1,
                mb: 1.5,
              }}
            >
              {(['k1', 'k2', 'p1', 'p2', 'k3'] as const).map((k) => (
                <TextField
                  key={k}
                  size="small"
                  label={k}
                  value={draft.calibration[k] ?? ''}
                  onChange={(e) => setCal(k, e.target.value)}
                  inputProps={{ inputMode: 'decimal', ...mono }}
                />
              ))}
            </Box>
            <Typography
              variant="overline"
              sx={{ color: 'text.secondary', display: 'block', mb: 0.75 }}
            >
              {t('Position above ground')}
            </Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
              <TextField
                size="small"
                label={t('Mast height (m)')}
                value={draft.calibration.mast_offset_m ?? ''}
                onChange={(e) => setCal('mast_offset_m', e.target.value)}
                helperText={t('metres above the DEM at the camera’s spot')}
                inputProps={{ inputMode: 'decimal', ...mono }}
              />
              <TextField
                size="small"
                label={t('Tilt (°)')}
                value={draft.calibration.tilt_deg ?? ''}
                onChange={(e) => setCal('tilt_deg', e.target.value)}
                helperText={t('below horizontal, + = aimed down')}
                inputProps={{ inputMode: 'decimal', ...mono }}
              />
            </Box>
            {calibrationErrors.length > 0 && (
              <Alert severity="error" variant="outlined" sx={{ mt: 1.5, py: 0 }}>
                {calibrationErrors.map((e) => e.message).join(' ')}
              </Alert>
            )}
          </Step>

          {/* ── 6 frame + control points ──────────────────────────────────────── */}
          <Step
            n={6}
            title={t('The frame, and its control points')}
            state={hasFrame ? 'done' : 'todo'}
            summary={hasFrame ? `${placed} ${t('control points')}` : undefined}
            hint={t(
              'Choose one frame from this camera. Control points are placed on it in the editor; four make the camera measurable.',
            )}
          >
            <Stack spacing={1.5}>
              {hasFrame && frame.data !== undefined && (
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <Box
                    component="img"
                    alt={t('The camera’s frame')}
                    src={imagesApi.thumbnailUrl(frame.data.id, { width: 320 })}
                    // ★ The thumbnail is the worker's; right after an upload it may not
                    //   exist yet — the original stands in rather than a broken picture.
                    onError={(e) => {
                      const el = e.currentTarget;
                      if (frame.data !== undefined && !el.dataset.fallback) {
                        el.dataset.fallback = '1';
                        el.src = imagesApi.fileUrl(frame.data.id);
                      }
                    }}
                    sx={{
                      width: 160,
                      height: 90,
                      objectFit: 'cover',
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--hairline)',
                      bgcolor: 'var(--bg-inset)',
                    }}
                  />
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" noWrap>
                      {frame.data.filename}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" className="le-mono">
                      {frame.data.width} × {frame.data.height} · {placed}/{MIN_GCPS_FOR_LUT}{' '}
                      {t('control points placed')}
                    </Typography>
                  </Box>
                </Stack>
              )}
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Button
                  size="small"
                  variant={hasFrame ? 'outlined' : 'contained'}
                  startIcon={
                    frameBusy === 'capture' ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <PhotoCameraOutlinedIcon />
                    )
                  }
                  disabled={frameBusy !== null || saving}
                  onClick={() => void captureNow()}
                >
                  {t('Capture from the camera now')}
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={
                    frameBusy === 'upload' ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <UploadFileOutlinedIcon />
                    )
                  }
                  disabled={frameBusy !== null || saving}
                  onClick={() => fileRef.current?.click()}
                >
                  {t('Upload a photo')}
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  data-testid="camera-frame-file"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void uploadFile(f);
                    e.target.value = '';
                  }}
                />
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<CollectionsOutlinedIcon />}
                  disabled={frameBusy !== null || saving}
                  onClick={() => void openLibrary()}
                >
                  {t('Choose from the capture library')}
                </Button>
              </Stack>
              {hasFrame && (
                <Box>
                  <Button
                    variant="contained"
                    startIcon={<EditLocationOutlinedIcon />}
                    disabled={saving}
                    onClick={() => void placePoints()}
                  >
                    {placed >= MIN_GCPS_FOR_LUT
                      ? t('Review control points')
                      : t('Place control points')}
                  </Button>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', mt: 0.75 }}
                  >
                    {t(
                      'Opens the editor for this frame. A "Back to camera settings" button there brings you — and the lookup table — back here.',
                    )}
                  </Typography>
                </Box>
              )}
            </Stack>
          </Step>

          {/* ── 7 lookup table ────────────────────────────────────────────────── */}
          <Step
            n={7}
            title={t('Lookup table')}
            state={hasLut ? 'done' : 'todo'}
            summary={hasLut ? (lutSite ?? undefined) : canBuild ? t('Ready to build') : undefined}
            hint={t(
              'One ground coordinate per pixel, solved from the frame, its control points, the calibration and the DEM. The monitoring page places every detection through it, and the drift watch is frozen on the frame the moment the table is built.',
            )}
          >
            <Stack spacing={1.5}>
              {hasLut && (
                <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                  <Chip
                    size="small"
                    color="primary"
                    icon={<GridOnOutlinedIcon />}
                    label={lutSite}
                    sx={{ fontFamily: 'var(--font-mono)' }}
                  />
                  {lutEntry !== undefined && (
                    <Typography variant="caption" color="text.secondary">
                      {lutEntry.validation_passed === true
                        ? t('validated')
                        : lutEntry.validation_passed === false
                          ? t('validation failed')
                          : t('not validated')}
                      {lutEntry.max_error_m !== null && (
                        <>
                          {' · '}
                          {t('max error')} {lutEntry.max_error_m.toFixed(1)} m
                        </>
                      )}
                      {lutEntry.built_utc && (
                        <>
                          {' · '}
                          {new Date(lutEntry.built_utc).toLocaleString()}
                        </>
                      )}
                    </Typography>
                  )}
                  {/* ★ A table solved on an EARLIER frame of this camera (2026-09-09):
                      kept on purpose after a same-aim frame change — say so. */}
                  {lutEntry?.source_image_id != null &&
                    frameId !== null &&
                    lutEntry.source_image_id !== frameId && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        data-testid="lut-earlier-frame"
                        sx={{ flexBasis: '100%' }}
                      >
                        {t(
                          'Built from an earlier frame of this camera — kept because the aim is the same. Rebuild it to solve on the current frame.',
                        )}
                      </Typography>
                    )}
                  {/* ★ WAS THE FOCAL SOLVED? Say so, with the seed it started from
                      (2026-09-09): the one question a no-calibration build leaves open. */}
                  {lutEntry?.intrinsics && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      data-testid="lut-focal-solve"
                      sx={{ flexBasis: '100%' }}
                    >
                      {lutEntry.intrinsics.focal_solved &&
                      lutEntry.intrinsics.fov_h_solved_deg !== null
                        ? `${t('Focal solved from the control points')}: ${lutEntry.intrinsics.fov_h_solved_deg.toFixed(1)}° ${t('field of view')}`
                        : t('Focal taken from the seed — the solve could not improve on it')}
                      {lutEntry.intrinsics.fov_h_seed_deg !== null &&
                        ` (${t('seed')} ${lutEntry.intrinsics.fov_h_seed_deg.toFixed(0)}°${lutEntry.intrinsics.seed_defaulted ? `, ${t('default')}` : ''})`}
                    </Typography>
                  )}
                </Stack>
              )}
              {!build.building && (
                <Typography
                  variant="caption"
                  color={stillNeeded.length > 0 ? 'warning.main' : 'text.secondary'}
                >
                  {stillNeeded.length > 0
                    ? `${t('Still needed')}: ${stillNeeded.join(', ')}`
                    : t('Everything the build needs is in place.')}
                </Typography>
              )}
              <Stack direction="row" spacing={1} alignItems="center">
                <Button
                  variant={hasLut ? 'outlined' : 'contained'}
                  startIcon={
                    build.building ? (
                      <CircularProgress size={14} color="inherit" />
                    ) : (
                      <GridOnOutlinedIcon />
                    )
                  }
                  disabled={!canBuild}
                  onClick={build.start}
                >
                  {build.building
                    ? t('Building…')
                    : hasLut
                      ? t('Rebuild lookup table')
                      : t('Build lookup table')}
                </Button>
                {hasLut && !isNew && (
                  <Button
                    variant="text"
                    startIcon={<SensorsOutlinedIcon />}
                    onClick={() => navigate(`/monitor/cameras/${id}`)}
                  >
                    {t('Watch this camera')}
                  </Button>
                )}
              </Stack>
              {build.building && <LinearProgress sx={{ height: 3, borderRadius: 2 }} />}
              {build.error !== null && (
                <Alert severity="error" variant="outlined" sx={{ py: 0 }}>
                  {build.error}
                </Alert>
              )}
            </Stack>
          </Step>
          {/* ── 8 drift watch ─────────────────────────────────────────────────── */}
          <Step
            n={8}
            title={t('Drift watch')}
            state={rowStates[7]}
            summary={driftSummary}
            hint={t(
              'The reference is frozen on the frame the control points sit on, and the camera is checked against it in the background. Moved, changed or degraded is stamped on every mark.',
            )}
          >
            <Stack spacing={1.5} data-testid="camera-drift-status">
              {isNew ? (
                <Typography variant="body2" color="text.secondary">
                  {t(
                    'Available once the camera is added: its reference freezes the moment the lookup table is built.',
                  )}
                </Typography>
              ) : activeRefId === null ? (
                <Typography variant="body2" color="text.secondary">
                  {hasLut
                    ? t('The drift reference is not frozen yet.')
                    : t(
                        'The drift watch starts on this frame once the lookup table is built (step 7).',
                      )}
                </Typography>
              ) : (
                <>
                  <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                    <RadarOutlinedIcon fontSize="small" color="action" />
                    {driftVerdict !== null && (
                      <DriftPill
                        state={driftVerdict.state}
                        confirmed={driftVerdict.status === driftVerdict.state}
                      />
                    )}
                    <Typography variant="body2">
                      {driftWatching
                        ? `${t('watching in the background')} · ${t('every')} ${watchInterval} s`
                        : driftMonitors.data === undefined
                          ? t('checking the watch…')
                          : t('the watch is not running')}
                      {driftMonitor !== null && driftMonitor.checks_done > 0 && (
                        <Box component="span" sx={{ color: 'text.secondary' }}>
                          {' · '}
                          {driftMonitor.checks_done} {t('checks')}
                        </Box>
                      )}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    {t('Drift reference frozen on this frame')}
                    {driftReference !== null && (
                      <>
                        {' · '}
                        {t('{n} landmarks').replace('{n}', String(driftReference.n_landmarks))}
                        {' · '}
                        {t('Alert above')} {driftReference.alert_ground_m} m {t('at')}{' '}
                        {Math.round(driftReference.ref_range_m)} m
                        {driftReference.frozen_from_label
                          ? ` · ${driftReference.frozen_from_label}`
                          : ''}
                      </>
                    )}
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                    <TextField
                      select
                      size="small"
                      label={t('Check every')}
                      value={watchInterval}
                      disabled={watchBusy}
                      onChange={(e) => void setWatch(true, Number(e.target.value))}
                      sx={{ minWidth: 150 }}
                    >
                      {[10, 30, 60, 120, 300, 600].map((sec) => (
                        <MenuItem key={sec} value={sec}>
                          {sec < 60 ? `${sec} s` : `${sec / 60} min`}
                        </MenuItem>
                      ))}
                    </TextField>
                    <Button
                      size="small"
                      variant="outlined"
                      disabled={watchBusy}
                      onClick={() => void setWatch(!driftWatching, watchInterval)}
                    >
                      {driftWatching ? t('Pause the watch') : t('Resume the watch')}
                    </Button>
                  </Stack>
                </>
              )}
              {!isNew && hasLut && (
                <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                  <Button
                    size="small"
                    variant={activeRefId === null ? 'contained' : 'text'}
                    disabled={drift.busy || saving}
                    onClick={() => void freezeDriftAndTell()}
                  >
                    {drift.busy
                      ? t('Freezing…')
                      : activeRefId !== null
                        ? t('Re-freeze on this frame')
                        : t('Freeze on this frame')}
                  </Button>
                  <Button size="small" variant="text" onClick={() => navigate('/drift')}>
                    {t('Open the drift monitor')}
                  </Button>
                </Stack>
              )}
              {drift.error !== null && (
                <Typography variant="caption" sx={{ color: 'var(--status-warn)' }}>
                  {drift.error}
                </Typography>
              )}
            </Stack>
          </Step>
        </SetupTable>

        {/* ── footer: THE one button ──────────────────────────────────────────── */}
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          sx={{
            mt: 1.5,
            pt: 1.5,
            borderTop: '1px solid var(--hairline)',
          }}
        >
          {isNew && draftHasContent(draft) && (
            <Button
              variant="text"
              color="inherit"
              startIcon={<DeleteSweepOutlinedIcon />}
              onClick={discardDraft}
              sx={{ color: 'text.secondary' }}
            >
              {t('Discard draft')}
            </Button>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>
            {isNew
              ? t(
                  'Fill the rows top to bottom. The camera joins the server when you press Add camera at the end.',
                )
              : t(
                  'The frame and the lookup table save as they happen; the rest saves with the button at the end.',
                )}
          </Typography>
          <Button variant="text" onClick={() => navigate('/cameras')}>
            {isNew ? t('Cancel') : t('Back to the server')}
          </Button>
          <Button
            variant="contained"
            startIcon={
              saving ? (
                <CircularProgress size={14} color="inherit" />
              ) : isNew ? (
                <AddIcon />
              ) : (
                <SaveOutlinedIcon />
              )
            }
            disabled={saving}
            onClick={() => void submit()}
          >
            {isNew ? t('Add camera to the server') : t('Save camera')}
          </Button>
        </Stack>
      </Container>

      {projectId !== null && (
        <Suspense fallback={null}>
          {/* ★ A new frame over one with control points: has the camera moved? (2026-09-09) */}
          <FrameChangeDialog
            open={pendingFrame !== null}
            pointCount={placed}
            hasTable={hasLut}
            busy={adopting}
            onDecide={(d) => void decideFrameChange(d)}
            onCancel={() => setPendingFrame(null)}
          />
          {/* ★ The live capture: look, choose the moment, confirm (2026-09-09). */}
          {capture !== null && (
            <CaptureFrameDialog
              open
              source={capture.source}
              device={DEVICE_CONNECTIONS.includes(draft.connection)}
              name={draft.name}
              onClose={() => setCapture(null)}
              onUse={useCapturedFrame}
            />
          )}
          <ImportFromLibraryDialog
            open={libraryOpen}
            onClose={() => setLibraryOpen(false)}
            projectId={projectId}
            single
            onImported={(imported) => {
              setLibraryOpen(false);
              const image = imported[0];
              if (image !== undefined) {
                setFrameBusy('library');
                void adoptFrame(image)
                  .catch((err: unknown) =>
                    notify(err instanceof Error ? err.message : String(err), { severity: 'error' }),
                  )
                  .finally(() => setFrameBusy(null));
              }
            }}
          />
        </Suspense>
      )}
    </Box>
  );
}

export default CameraSettingsPage;
