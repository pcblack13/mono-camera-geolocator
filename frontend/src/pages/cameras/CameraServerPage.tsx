/**
 * `pages/cameras/CameraServerPage.tsx` — `/cameras`: the CAMERA WORKSPACE (named
 * "Server of cameras" until 2026-09-07).
 *
 * ★ ONE OF THE MAIN PAGES (2026-09-04, owner ask). The registry lives on the
 *   server (1.3); this page is that registry as a place to work: with NO cameras it
 *   asks for the first one — that is the whole page, nothing else to look at; with
 *   cameras it shows them as cards beside an "Add camera".
 *
 * ★ A CARD IS A PICTURE, A NAME AND ONE THING TO DO (2026-09-07, owner ask: the
 *   old card listed the address, the coordinates, three chips and a sentence —
 *   too much to read six times). Now the camera's own frame is the card's cover
 *   (a placeholder until one is chosen), the status and readiness sit on it as
 *   pills, one line names what the setup still lacks (the meter is gone) and what comes
 *   next, and the primary button is the one thing that camera needs: WATCH when
 *   its lookup table exists, CONTINUE SETUP until then. Everything else — the
 *   other page, removal — is one menu away. The whole cover opens the camera.
 *
 * ★ FIND ONE FAST. A search box filters by name or address and a toggle shows
 *   only the ready cameras or only the ones still in setup — six cameras is where
 *   scanning stops working.
 *
 * ★ Adding goes to the SETTINGS PIPELINE (`/cameras/new`), not a dialog: a camera
 *   is registered by walking name → connection → DEM → calibration → position →
 *   frame → control points → lookup table, and that needs a page.
 */

import { useMemo, useState, type JSX, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '@mui/material/styles';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import Container from '@mui/material/Container';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import DataObjectOutlinedIcon from '@mui/icons-material/DataObjectOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import EditLocationOutlinedIcon from '@mui/icons-material/EditLocationOutlined';
import FolderZipOutlinedIcon from '@mui/icons-material/FolderZipOutlined';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import SearchIcon from '@mui/icons-material/Search';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined';

import { camerasApi } from '../../api/cameras';
import { imagesApi } from '../../api/images';
import { EmptyState } from '../../components/common/EmptyState';
import { useNotify } from '../../components/common/Notifications';
import { DetectedSenders } from '../../components/monitor/DetectedSenders';
import { senderIdFromSource } from '../../hooks/useSenders';
import { t } from '../../i18n';
import { connectionLabel } from '../../lib/cameras/connection';
import {
  selectCameraStatus,
  selectCameras,
  useCameraRegistryStore,
  type CameraStatusState,
  type RegisteredCamera,
} from '../../store/cameraRegistryStore';
import { asUuid } from '../../types/common';

// ─────────────────────────────────────────────────────────────────────────────
// What a camera's setup has, and what it still needs
// ─────────────────────────────────────────────────────────────────────────────

/** Which of the pipeline's outputs a camera already has. */
export function setupProgress(camera: RegisteredCamera): {
  frame: boolean;
  calibration: boolean;
  lut: boolean;
  complete: boolean;
} {
  const frame = Boolean(camera.frame_image_id);
  const calibration = Boolean(camera.calibration);
  const lut = Boolean(camera.lut_site);
  return { frame, calibration, lut, complete: lut };
}

export type SetupStep = 'calibration' | 'frame' | 'lut';

/** The first thing the setup still needs, in pipeline order — `null` once the table is built. */
export function nextSetupStep(camera: RegisteredCamera): SetupStep | null {
  const p = setupProgress(camera);
  if (p.complete) return null;
  if (!p.calibration) return 'calibration';
  if (!p.frame) return 'frame';
  return 'lut';
}

/** The setup's three recorded outputs, in pipeline order — the note names the missing ones. */
const SETUP_STEPS: readonly { key: SetupStep; label: string }[] = [
  { key: 'calibration', label: 'Calibration' },
  { key: 'frame', label: 'Frame' },
  { key: 'lut', label: 'Lookup table' },
];

/** The live state as a pill on the cover — nothing at all while it is unknown. */
const STATUS_PILL: Record<CameraStatusState, { label: string; dot: string } | null> = {
  live: { label: 'Live', dot: 'var(--status-ok)' },
  connecting: { label: 'Connecting', dot: 'var(--status-busy)' },
  lost: { label: 'Lost', dot: 'var(--status-error)' },
  refused: { label: 'Refused', dot: 'var(--status-error)' },
  unknown: null,
};

// ─────────────────────────────────────────────────────────────────────────────
// The card's parts
// ─────────────────────────────────────────────────────────────────────────────

/** A small pill over the picture: a dot and a word. */
function Pill({
  dot,
  icon,
  label,
  tone,
}: {
  dot?: string;
  icon?: JSX.Element;
  label: string;
  tone: 'ok' | 'quiet';
}): JSX.Element {
  // ★ Tracking is for Latin capitals; spaced-out Arabic letters lose their joins.
  const rtl = useTheme().direction === 'rtl';
  return (
    <Box
      component="span"
      className="le-mono"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.5,
        px: 0.875,
        height: 22,
        borderRadius: 'var(--radius-pill)',
        fontSize: 10,
        letterSpacing: rtl ? 0 : '0.06em',
        textTransform: 'uppercase',
        color: tone === 'ok' ? 'var(--status-ok)' : 'text.secondary',
        bgcolor: 'var(--scrim-panel)',
        backdropFilter: 'blur(6px)',
        border: '1px solid var(--hairline)',
      }}
    >
      {dot !== undefined && (
        <Box
          component="span"
          aria-hidden
          sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: dot }}
        />
      )}
      {icon}
      {label}
    </Box>
  );
}

/**
 * What the setup still lacks, in words (owner ask 2026-09-10). The three-segment
 * meter is gone: a bar said "how far" and left the operator to guess "of what";
 * this names the missing pieces in pipeline order — "Missing: Calibration ·
 * Frame · Lookup table" — and turns green once the table is built.
 */
function SetupNote({ camera }: { camera: RegisteredCamera }): JSX.Element {
  const progress = setupProgress(camera);
  const missing = SETUP_STEPS.filter((s) => !progress[s.key]).map((s) => t(s.label));
  const ready = progress.complete;
  const text = ready
    ? t('Ready — marks land on the map')
    : `${t('Missing:')} ${missing.join(' · ')}`;
  return (
    <Typography
      variant="caption"
      noWrap
      title={text}
      data-testid="setup-note"
      sx={{
        display: 'block',
        fontSize: 11.5,
        color: ready ? 'var(--status-ok)' : 'text.secondary',
      }}
    >
      {text}
    </Typography>
  );
}

function CameraCard({
  camera,
  onDelete,
}: {
  camera: RegisteredCamera;
  onDelete: (camera: RegisteredCamera) => void;
}): JSX.Element {
  const navigate = useNavigate();
  const rtl = useTheme().direction === 'rtl';
  const status = useCameraRegistryStore(selectCameraStatus(camera.id));
  const ready = setupProgress(camera).complete;
  const dataOnly = camera.provides === 'data';
  const settingsPath = `/cameras/${camera.id}/settings`;
  const watchPath = `/monitor/cameras/${camera.id}`;
  const editorPath = `/cameras/${camera.id}/editor`;
  const primaryPath = ready ? watchPath : settingsPath;
  const [menuAt, setMenuAt] = useState<HTMLElement | null>(null);
  const [pictureFailed, setPictureFailed] = useState(false);
  const pill = STATUS_PILL[status.state];
  const frameId = camera.frame_image_id;
  // ★ A FRAME IS CHOSEN → ITS POINTS CAN BE REVIEWED (owner ask 2026-09-10).
  //   The editor is where control points are placed and judged, and reaching it
  //   used to mean opening the camera's settings and finding row 6 first. The
  //   card offers it directly, and only once there is a frame to review on.
  const hasFrame = frameId !== undefined && frameId !== null && frameId !== '';
  const hasPicture = !dataOnly && frameId !== undefined && frameId !== '' && !pictureFailed;

  const go = (to: string): void => {
    setMenuAt(null);
    navigate(to);
  };

  return (
    <Box
      component="li"
      aria-label={camera.name}
      sx={{
        'listStyle': 'none',
        'position': 'relative',
        'display': 'flex',
        'flexDirection': 'column',
        'borderRadius': 'var(--radius-lg)',
        'border': '1px solid var(--hairline)',
        'bgcolor': 'var(--bg-elevated)',
        'overflow': 'hidden',
        'transition':
          'border-color var(--dur-fast) var(--ease-standard), transform var(--dur-fast) var(--ease-standard), box-shadow var(--dur-fast) var(--ease-standard)',
        '&:hover': {
          borderColor: 'var(--accent)',
          transform: 'translateY(-2px)',
          boxShadow: 'var(--elev-popover)',
        },
      }}
    >
      {/* ★ THE COVER IS THE CAMERA'S OWN FRAME, and the whole of it opens the
          camera — a placeholder until a frame is chosen. */}
      <ButtonBase
        onClick={() => navigate(primaryPath)}
        aria-label={`${t('Open')} ${camera.name}`}
        sx={{
          'display': 'block',
          'width': '100%',
          'aspectRatio': '16 / 9',
          'position': 'relative',
          'bgcolor': 'var(--bg-inset)',
          'overflow': 'hidden',
          '&:focus-visible': { boxShadow: 'var(--focus-ring)' },
          '& img': { transition: 'transform var(--dur-normal) var(--ease-standard)' },
          '&:hover img': { transform: 'scale(1.03)' },
        }}
      >
        {hasPicture ? (
          <Box
            component="img"
            alt=""
            src={imagesApi.thumbnailUrl(asUuid(frameId), { width: 480 })}
            // ★ The thumbnail is the worker's; right after an upload it may not
            //   exist yet — the original stands in, and failing that, the placeholder.
            onError={(e) => {
              const el = e.currentTarget;
              if (!el.dataset.fallback) {
                el.dataset.fallback = '1';
                el.src = imagesApi.fileUrl(asUuid(frameId));
              } else {
                setPictureFailed(true);
              }
            }}
            sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
        ) : (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeItems: 'center',
              color: 'var(--text-tertiary)',
              background:
                'radial-gradient(90% 90% at 50% 110%, var(--accent-quiet) 0%, transparent 70%)',
            }}
          >
            <Stack alignItems="center" spacing={0.75}>
              {dataOnly ? (
                <DataObjectOutlinedIcon sx={{ fontSize: 36 }} />
              ) : (
                <VideocamOutlinedIcon sx={{ fontSize: 36 }} />
              )}
              <Typography
                className="le-mono"
                sx={{ fontSize: 10, letterSpacing: rtl ? 0 : '0.1em' }}
              >
                {dataOnly ? t('DATA FEED') : t('NO FRAME YET')}
              </Typography>
            </Stack>
          </Box>
        )}
        <Stack direction="row" spacing={0.75} sx={{ position: 'absolute', left: 10, top: 10 }}>
          {ready ? (
            <Pill tone="ok" icon={<CheckRoundedIcon sx={{ fontSize: 12 }} />} label={t('Ready')} />
          ) : (
            <Pill tone="quiet" label={t('In setup')} />
          )}
          {pill !== null && <Pill tone="quiet" dot={pill.dot} label={t(pill.label)} />}
        </Stack>
      </ButtonBase>

      {/* the rest of what can be done with it — one menu, not three buttons */}
      <IconButton
        size="small"
        aria-label={`${t('More actions for')} ${camera.name}`}
        aria-haspopup="menu"
        onClick={(e: MouseEvent<HTMLElement>) => setMenuAt(e.currentTarget)}
        sx={{
          'position': 'absolute',
          'right': 8,
          'top': 8,
          'bgcolor': 'var(--scrim-panel)',
          'backdropFilter': 'blur(6px)',
          'border': '1px solid var(--hairline)',
          '&:hover': { bgcolor: 'var(--bg-overlay)' },
        }}
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={menuAt} open={menuAt !== null} onClose={() => setMenuAt(null)}>
        <MenuItem onClick={() => go(settingsPath)}>
          <ListItemIcon>
            <TuneOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Settings')}</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => go(watchPath)}>
          <ListItemIcon>
            <SensorsOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Watch')}</ListItemText>
        </MenuItem>
        {hasFrame && (
          <MenuItem onClick={() => go(editorPath)}>
            <ListItemIcon>
              <EditLocationOutlinedIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('Review control points')}</ListItemText>
          </MenuItem>
        )}
        <Divider />
        {/* ★ THE WHOLE CAMERA, ONE FILE (2026-09-12, owner ask). Setting a camera
            up is eight steps whose results land in five different places on disk;
            this is the one door that takes all of it — to another machine, to an
            archive, to a colleague. A half-configured camera exports too. */}
        <MenuItem
          component="a"
          href={camerasApi.exportUrl(asUuid(camera.id))}
          download
          onClick={() => setMenuAt(null)}
        >
          <ListItemIcon>
            <FolderZipOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary={t('Download the camera settings')}
            secondary={t('frame, control points, DEM, calibration, lookup table, drift')}
          />
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            setMenuAt(null);
            onDelete(camera);
          }}
          sx={{ color: 'error.main' }}
        >
          <ListItemIcon sx={{ color: 'inherit' }}>
            <DeleteOutlineIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Remove from the server')}</ListItemText>
        </MenuItem>
      </Menu>

      {/* the words: the name, how it connects, how far its setup is, the one thing to do */}
      <Stack spacing={1} sx={{ p: 1.5, flex: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            variant="subtitle2"
            noWrap
            title={camera.name}
            sx={{ fontWeight: 700, lineHeight: 1.2, fontSize: 14 }}
          >
            {camera.name}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            title={dataOnly ? camera.data_source : camera.source}
            sx={{ display: 'block' }}
          >
            {t(connectionLabel(camera.connection))}
          </Typography>
        </Box>
        <SetupNote camera={camera} />
        <Stack direction="row" spacing={1} sx={{ mt: 'auto', pt: 0.25 }}>
          <Button
            size="small"
            variant="contained"
            fullWidth
            startIcon={ready ? <SensorsOutlinedIcon /> : <TuneOutlinedIcon />}
            onClick={() => navigate(primaryPath)}
          >
            {ready ? t('Watch') : t('Continue setup')}
          </Button>
          <Tooltip title={ready ? t('Settings') : t('Watch')}>
            <Button
              size="small"
              variant="outlined"
              aria-label={ready ? t('Settings') : t('Watch')}
              onClick={() => navigate(ready ? settingsPath : watchPath)}
              sx={{ minWidth: 40, px: 1, flexShrink: 0 }}
            >
              {ready ? (
                <TuneOutlinedIcon fontSize="small" />
              ) : (
                <SensorsOutlinedIcon fontSize="small" />
              )}
            </Button>
          </Tooltip>
        </Stack>
        {hasFrame && (
          <Button
            size="small"
            variant="outlined"
            fullWidth
            startIcon={<EditLocationOutlinedIcon />}
            onClick={() => navigate(editorPath)}
          >
            {t('Review control points')}
          </Button>
        )}
      </Stack>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

type Shown = 'all' | 'ready' | 'setup';

export function CameraServerPage(): JSX.Element {
  const navigate = useNavigate();
  const notify = useNotify();
  const cameras = useCameraRegistryStore(selectCameras);
  // ★ A camera already registered against a sender should not offer to register
  //   it again. The source URL is what names the sender, so the registry itself
  //   answers "do I already have this one?" — no extra state to keep in step.
  const knownSenderIds = useMemo(() => {
    const ids = new Set<string>();
    for (const camera of cameras) {
      const id = senderIdFromSource(camera.source);
      if (id !== null) ids.add(id);
    }
    return ids;
  }, [cameras]);
  const remove = useCameraRegistryStore((s) => s.remove);
  const [toDelete, setToDelete] = useState<RegisteredCamera | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState<Shown>('all');

  const readyCount = useMemo(
    () => cameras.filter((c) => setupProgress(c).complete).length,
    [cameras],
  );
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return cameras.filter((c) => {
      const ready = setupProgress(c).complete;
      if (shown === 'ready' && !ready) return false;
      if (shown === 'setup' && ready) return false;
      if (needle === '') return true;
      return (
        c.name.toLowerCase().includes(needle) ||
        c.source.toLowerCase().includes(needle) ||
        (c.data_source ?? '').toLowerCase().includes(needle)
      );
    });
  }, [cameras, query, shown]);

  const confirmDelete = (): void => {
    if (toDelete === null) return;
    setDeleting(true);
    const name = toDelete.name;
    remove(toDelete.id)
      .then(() => {
        notify(`“${name}” ${t('was removed from the server.')}`, { severity: 'success' });
        setToDelete(null);
      })
      .catch((err: unknown) => {
        notify(err instanceof Error ? err.message : t('The server refused the removal.'), {
          severity: 'error',
        });
      })
      .finally(() => setDeleting(false));
  };

  const addFirst = (): void => navigate('/cameras/new');

  if (cameras.length === 0) {
    // ★ ZERO CAMERAS: the page IS the ask. Nothing else to look at until one exists.
    return (
      <Box sx={{ flex: 1, display: 'flex' }} data-testid="camera-server-empty">
        <EmptyState
          icon={<DnsOutlinedIcon />}
          title={t('No cameras on the server yet')}
          description={t(
            'Add the first camera to start: give it a name, say how it connects, attach its DEM and frame, place its control points, and build its lookup table. Every machine that opens this app will then see it.',
          )}
          primaryAction={{
            label: t('Add your first camera'),
            onClick: addFirst,
            icon: <AddIcon />,
          }}
          secondaryAction={{
            label: t('How the pipeline works'),
            onClick: () => navigate('/guide'),
          }}
        />
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, overflow: 'auto' }}>
      {/* ★ xl, not lg (2026-09-07, owner ask): five cameras to a row on a wide
          screen, four on a laptop — and the cards a size down to fit. */}
      <Container maxWidth="xl" sx={{ py: { xs: 3, md: 4 } }}>
        {/* the header: the count, then find-one-fast, then Add */}
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={2}
          alignItems={{ xs: 'stretch', md: 'center' }}
          sx={{ mb: 3 }}
        >
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              {t('Camera workspace')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {cameras.length}{' '}
              {t(cameras.length === 1 ? 'camera registered' : 'cameras registered')}
              {' · '}
              {readyCount} {t('ready')}
              {' · '}
              {cameras.length - readyCount} {t('in setup')}
            </Typography>
          </Box>
          <TextField
            size="small"
            placeholder={t('Search cameras')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            inputProps={{ 'aria-label': t('Search cameras') }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ width: { xs: '100%', md: 240 } }}
          />
          <ToggleButtonGroup
            exclusive
            size="small"
            value={shown}
            onChange={(_e, v: Shown | null) => {
              if (v !== null) setShown(v);
            }}
            aria-label={t('Show')}
          >
            <ToggleButton value="all">{t('All')}</ToggleButton>
            <ToggleButton value="ready">{t('Ready')}</ToggleButton>
            <ToggleButton value="setup">{t('In setup')}</ToggleButton>
          </ToggleButtonGroup>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate('/cameras/new')}
            sx={{ flexShrink: 0 }}
          >
            {t('Add camera')}
          </Button>
        </Stack>

        {/* ★ THE CABLE IS THE INSTALLATION (2026-09-09, owner ask). A camera that
            detects on its own hardware announces everything needed to talk to it,
            so plugging it in should be the whole of adding it. This sits ABOVE the
            registry rather than inside "Add camera": it is not a form to fill in,
            it is a list of things already on the wire. When nothing is announcing
            itself it says so quietly and takes one line — an unplugged cable is
            the normal state of a machine, not a problem to warn about. */}
        <Box sx={{ mb: 3 }}>
          <DetectedSenders
            knownSenderIds={knownSenderIds}
            onConnected={(cameraId) => navigate(`/monitor/cameras/${cameraId}`)}
          />
        </Box>

        {visible.length === 0 ? (
          <Stack alignItems="center" spacing={1.5} sx={{ py: 8, color: 'text.secondary' }}>
            <SearchIcon />
            <Typography variant="body2">{t('No camera matches.')}</Typography>
            <Button
              size="small"
              variant="outlined"
              onClick={() => {
                setQuery('');
                setShown('all');
              }}
            >
              {t('Clear filters')}
            </Button>
          </Stack>
        ) : (
          <Box
            component="ul"
            aria-label={t('Registered cameras')}
            sx={{
              m: 0,
              p: 0,
              display: 'grid',
              gridTemplateColumns: {
                xs: '1fr',
                sm: 'repeat(2, 1fr)',
                md: 'repeat(3, 1fr)',
                lg: 'repeat(4, 1fr)',
                xl: 'repeat(5, 1fr)',
              },
              gap: 1.5,
            }}
          >
            {visible.map((camera) => (
              <CameraCard key={camera.id} camera={camera} onDelete={setToDelete} />
            ))}
          </Box>
        )}
      </Container>

      <Dialog open={toDelete !== null} onClose={() => setToDelete(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Remove this camera?')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            {t(
              'The camera leaves the server for every machine. Its recorded detections stay; its project, frame and lookup table are kept on disk.',
            )}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToDelete(null)}>{t('Cancel')}</Button>
          <Button color="error" variant="contained" onClick={confirmDelete} disabled={deleting}>
            {t('Remove')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default CameraServerPage;
