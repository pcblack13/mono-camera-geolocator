/**
 * `video/RecordingsLibrary.tsx` — the recordings from the live cameras, as cards
 * on the Recorded videos page.
 *
 * ★ ONE FOLDER PER RECORDING (2026-09-02, owner ask): Record on a camera writes a
 *   folder holding the video as watched (boxes burned in during a run) and the
 *   run's attribute table as CSV. The card IS that folder: its first frame as the
 *   picture, its camera and moment as the name, and one door — WATCH — into the
 *   recording's own page, where the video plays beside its table. The downloads,
 *   the folder path and the delete wait in the card's menu.
 *
 * ★ A CARD, NOT A ROW (2026-09-07, owner ask). The list of mono folder names with
 *   four icons each read like a directory listing; a picture and a name read like
 *   a library. The folder's slug stays on the card in small type — it is still
 *   the name on disk.
 */

import { useMemo, useState, type JSX, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import FolderZipOutlinedIcon from '@mui/icons-material/FolderZipOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import MovieOutlinedIcon from '@mui/icons-material/MovieOutlined';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import VideocamOffOutlinedIcon from '@mui/icons-material/VideocamOffOutlined';

import { liveApi, type RecordingLibraryEntry } from '../../api/live';
import { fmtClock } from '../../lib/clock';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';

function fmtBytes(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} GB`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1000))} kB`;
}

/** The path a recording's page answers at. */
function recordingHref(folder: string): string {
  return `/videos/recordings/${encodeURIComponent(folder)}`;
}

/** Does the entry answer a search — by its folder or its camera? */
function matches(entry: RecordingLibraryEntry, needle: string): boolean {
  if (needle === '') return true;
  return (
    entry.folder.toLowerCase().includes(needle) || entry.camera_name.toLowerCase().includes(needle)
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// One card
// ─────────────────────────────────────────────────────────────────────────────

function RecordingCard({
  entry,
  onDelete,
}: {
  entry: RecordingLibraryEntry;
  onDelete: (entry: RecordingLibraryEntry) => void;
}): JSX.Element {
  const navigate = useNavigate();
  const notify = useNotify();
  const [menuAt, setMenuAt] = useState<HTMLElement | null>(null);
  const [posterFailed, setPosterFailed] = useState(false);
  const started = entry.started_at ? new Date(entry.started_at).toLocaleString() : '';
  const hasPicture = entry.has_video && !posterFailed;
  const open = (): void => navigate(recordingHref(entry.folder));
  const closeMenu = (): void => setMenuAt(null);

  return (
    <Box
      component="li"
      aria-label={entry.folder}
      sx={{
        'listStyle': 'none',
        'position': 'relative',
        'display': 'flex',
        'flexDirection': 'column',
        'borderRadius': 'var(--radius-lg)',
        'border': '1px solid var(--hairline)',
        'bgcolor': 'var(--bg-elevated)',
        'overflow': 'hidden',
        // ★ HOVER MOVES NOTHING (2026-09-12). The card used to lift 2px on hover.
        //   A lift is a geometry change, and geometry changes are what hover must
        //   never make here: these cards are aspect-ratio tiles in a 1fr grid
        //   inside a scrolling frame, so the smallest nudge can flip the vertical
        //   scrollbar — which narrows the columns, which shortens the tiles, which
        //   takes the scrollbar away again. The page shook for as long as the
        //   pointer rested on a card. The border and the shadow answer the pointer
        //   now; neither one can move a pixel of layout.
        'transition':
          'border-color var(--dur-fast) var(--ease-standard), box-shadow var(--dur-fast) var(--ease-standard)',
        '&:hover': {
          borderColor: 'var(--accent)',
          boxShadow: 'var(--elev-popover)',
        },
        '&:hover .le-play': { opacity: 1, transform: 'scale(1)' },
      }}
    >
      {/* ★ The picture is the door: the whole cover opens the recording. */}
      <ButtonBase
        onClick={open}
        aria-label={`${t('Open this recording')} ${entry.folder}`}
        sx={{
          'display': 'block',
          'width': '100%',
          'aspectRatio': '16 / 9',
          'position': 'relative',
          'bgcolor': 'var(--bg-inset)',
          'overflow': 'hidden',
          '&:focus-visible': { boxShadow: 'var(--focus-ring)' },
        }}
      >
        {hasPicture ? (
          <Box
            component="img"
            alt=""
            src={liveApi.recordingPosterUrl(entry.folder)}
            onError={() => setPosterFailed(true)}
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
              {entry.has_video ? (
                <MovieOutlinedIcon sx={{ fontSize: 36 }} />
              ) : (
                <VideocamOffOutlinedIcon sx={{ fontSize: 36 }} />
              )}
              <Typography className="le-mono" sx={{ fontSize: 10 }}>
                {entry.has_video ? t('No picture') : t('No video')}
              </Typography>
            </Stack>
          </Box>
        )}
        <Box
          className="le-play"
          aria-hidden
          sx={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 52,
            height: 52,
            ml: '-26px',
            mt: '-26px',
            borderRadius: '50%',
            display: 'grid',
            placeItems: 'center',
            bgcolor: 'var(--accent)',
            color: 'var(--accent-contrast)',
            opacity: 0,
            transform: 'scale(0.85)',
            transition:
              'opacity var(--dur-fast) var(--ease-standard), transform var(--dur-fast) var(--ease-standard)',
            boxShadow: 'var(--elev-popover)',
          }}
        >
          <PlayArrowRoundedIcon sx={{ fontSize: 32 }} />
        </Box>
        <Box
          component="span"
          className="le-mono"
          sx={{
            position: 'absolute',
            left: 10,
            bottom: 10,
            px: 0.875,
            height: 22,
            display: 'inline-flex',
            alignItems: 'center',
            borderRadius: 'var(--radius-pill)',
            fontSize: 11,
            bgcolor: 'var(--scrim-panel)',
            backdropFilter: 'blur(6px)',
            border: '1px solid var(--hairline)',
            color: 'text.primary',
          }}
        >
          {fmtClock(entry.duration_s)}
        </Box>
        {entry.trimmed_from ? (
          <Box
            component="span"
            className="le-mono"
            sx={{
              position: 'absolute',
              left: 10,
              top: 10,
              px: 0.875,
              height: 22,
              display: 'inline-flex',
              alignItems: 'center',
              borderRadius: 'var(--radius-pill)',
              fontSize: 10,
              letterSpacing: '0.06em',
              bgcolor: 'var(--scrim-panel)',
              backdropFilter: 'blur(6px)',
              border: '1px solid var(--hairline)',
              color: 'var(--accent)',
            }}
          >
            {t('CUT')}
          </Box>
        ) : null}
      </ButtonBase>

      <IconButton
        size="small"
        aria-label={`${t('More actions for')} ${entry.folder}`}
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
      <Menu anchorEl={menuAt} open={menuAt !== null} onClose={closeMenu}>
        {/* ★ THE WHOLE SCENE FIRST (2026-09-12). The single files below it are
            still here for whoever wants only one — but keeping a session means
            keeping all three, and that should not be three trips. */}
        <MenuItem
          component="a"
          href={liveApi.recordingPackageUrl(entry.folder)}
          download
          onClick={closeMenu}
        >
          <ListItemIcon>
            <FolderZipOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary={t('Download the whole package')}
            secondary={t('video, satellite map and attribute table')}
          />
        </MenuItem>
        <MenuItem
          component="a"
          href={liveApi.recordingFileUrl(entry.folder, 'satellite.png')}
          download
          disabled={entry.has_map !== true}
          onClick={closeMenu}
        >
          <ListItemIcon>
            <MapOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Download the satellite map')}</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem
          component="a"
          href={liveApi.recordingFileUrl(entry.folder, 'video.mp4')}
          download
          disabled={!entry.has_video}
          onClick={closeMenu}
        >
          <ListItemIcon>
            <MovieOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Download the video')}</ListItemText>
        </MenuItem>
        <MenuItem
          component="a"
          href={liveApi.recordingFileUrl(entry.folder, 'detections.csv')}
          download
          disabled={!entry.has_csv}
          onClick={closeMenu}
        >
          <ListItemIcon>
            <DescriptionOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Download the attribute table (CSV)')}</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            closeMenu();
            void navigator.clipboard?.writeText(entry.path);
            notify(t('Folder path copied.'), { severity: 'info' });
          }}
        >
          <ListItemIcon>
            <ContentCopyIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Copy the folder path')}</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            closeMenu();
            onDelete(entry);
          }}
          sx={{ color: 'error.main' }}
        >
          <ListItemIcon sx={{ color: 'inherit' }}>
            <DeleteOutlineIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Delete this recording')}</ListItemText>
        </MenuItem>
      </Menu>

      <Stack spacing={1} sx={{ p: 1.5, flex: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            variant="subtitle2"
            noWrap
            title={entry.camera_name || entry.folder}
            sx={{ fontWeight: 700, lineHeight: 1.2, fontSize: 14 }}
          >
            {entry.camera_name || entry.folder}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            {/* ★ An English-format timestamp inside an Arabic line is isolated, or the
                bidi algorithm reorders its halves. */}
            <bdi dir="ltr">{started}</bdi>
            {' · '}
            <bdi>
              {entry.marks} {t('marks')}
            </bdi>
            {' · '}
            {fmtBytes(entry.video_bytes)}
          </Typography>
          <Typography
            className="le-mono"
            noWrap
            title={entry.path}
            sx={{ fontSize: 11, color: 'text.disabled', mt: 0.25 }}
            dir="ltr"
          >
            {entry.folder}
          </Typography>
          {entry.trimmed_from ? (
            <Typography variant="caption" color="text.secondary" noWrap component="div">
              <bdi>
                {t('cut from')} {entry.trimmed_from}
              </bdi>
            </Typography>
          ) : null}
        </Box>
        <Stack direction="row" spacing={1} sx={{ mt: 'auto' }}>
          <Button
            size="small"
            variant="contained"
            startIcon={<PlayArrowRoundedIcon />}
            onClick={open}
            sx={{ flex: 1 }}
          >
            {t('Watch')}
          </Button>
          {/* ★ ONE BUTTON TAKES THE WHOLE SESSION (2026-09-12, owner ask): the
              video, the satellite map and the table, in one folder, in one file. */}
          {/* ★ describeChild: without it MUI puts the title in aria-label and the
              button's own word — the one on screen — stops being its name. */}
          <Tooltip
            describeChild
            title={t('The video, the satellite map and the attribute table — one folder')}
          >
            <Button
              size="small"
              variant="outlined"
              component="a"
              href={liveApi.recordingPackageUrl(entry.folder)}
              download
              startIcon={<FolderZipOutlinedIcon />}
              sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
            >
              {t('Package')}
            </Button>
          </Tooltip>
        </Stack>
      </Stack>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The section
// ─────────────────────────────────────────────────────────────────────────────

export interface RecordingsLibraryProps {
  /** The page's search, lower-cased and trimmed — filters by folder or camera. */
  query?: string;
}

/** The recordings as cards, newest first, with the library folder named above them. */
export function RecordingsLibrary({ query = '' }: RecordingsLibraryProps): JSX.Element {
  const navigate = useNavigate();
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [toDelete, setToDelete] = useState<RecordingLibraryEntry | null>(null);
  const [deleting, setDeleting] = useState(false);
  const library = useQuery({
    queryKey: ['live', 'recordings'],
    queryFn: ({ signal }) => liveApi.listRecordings(signal),
  });
  const entries = useMemo(() => library.data?.items ?? [], [library.data]);
  const shown = useMemo(() => entries.filter((e) => matches(e, query)), [entries, query]);

  const confirmDelete = (): void => {
    if (toDelete === null) return;
    const folder = toDelete.folder;
    setDeleting(true);
    liveApi
      .deleteRecording(folder)
      .then(() => {
        notify(`${t('Recording deleted:')} ${folder}`, { severity: 'info' });
        setToDelete(null);
        void queryClient.invalidateQueries({ queryKey: ['live', 'recordings'] });
      })
      .catch((e: unknown) =>
        notify(e instanceof Error ? e.message : String(e), { severity: 'error' }),
      )
      .finally(() => setDeleting(false));
  };

  return (
    <Box component="section" aria-labelledby="recordings-library-title">
      <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 0.25 }}>
        <Typography
          id="recordings-library-title"
          variant="h6"
          component="h2"
          sx={{ fontWeight: 700, lineHeight: 1.2 }}
        >
          {t('Camera recordings')}
        </Typography>
        {library.data !== undefined && (
          <Typography className="le-mono" sx={{ fontSize: 11, color: 'text.secondary' }}>
            {entries.length}
          </Typography>
        )}
      </Stack>
      <Typography variant="caption" color="text.secondary" component="div">
        {t(
          'One folder per recording — the video as watched, and the detection attribute table as CSV.',
        )}
      </Typography>
      {library.data !== undefined && (
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1.5 }}>
          <Typography variant="caption" color="text.disabled" noWrap>
            {t('Library folder')}
          </Typography>
          <Typography
            className="le-mono"
            sx={{ fontSize: 11, color: 'text.disabled' }}
            dir="ltr"
            noWrap
          >
            {library.data.root}
          </Typography>
          <Tooltip title={t('Copy the folder path')}>
            <IconButton
              size="small"
              aria-label={t('Copy the folder path')}
              onClick={() => void navigator.clipboard?.writeText(library.data.root)}
            >
              <ContentCopyIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
        </Stack>
      )}

      {library.isLoading ? (
        <Box sx={{ display: 'grid', placeItems: 'center', py: 4 }}>
          <CircularProgress size={22} />
        </Box>
      ) : library.isError ? (
        <Typography variant="body2" color="error" sx={{ py: 2 }}>
          {t('The library could not be read.')}
        </Typography>
      ) : entries.length === 0 ? (
        <Stack
          alignItems="center"
          spacing={1.5}
          sx={{
            py: 5,
            px: 2,
            borderRadius: 'var(--radius-lg)',
            border: '1px dashed var(--hairline-strong)',
            color: 'text.secondary',
            textAlign: 'center',
          }}
        >
          <MovieOutlinedIcon />
          <Typography variant="body2">
            {t('No recordings yet — press Record on a camera while its stream is live.')}
          </Typography>
          <Button
            size="small"
            variant="outlined"
            startIcon={<SensorsOutlinedIcon />}
            onClick={() => navigate('/monitor')}
          >
            {t('Open cameras monitoring')}
          </Button>
        </Stack>
      ) : shown.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
          {t('No recording matches.')}
        </Typography>
      ) : (
        <Box
          component="ul"
          aria-label={t('Camera recordings')}
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
          {shown.map((entry) => (
            <RecordingCard key={entry.folder} entry={entry} onDelete={setToDelete} />
          ))}
        </Box>
      )}

      <Dialog open={toDelete !== null} onClose={() => setToDelete(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Delete this recording?')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            {t('The folder — its video, its table and its meta — leaves the disk for good.')}
          </Typography>
          {toDelete !== null && (
            <Typography className="le-mono" sx={{ fontSize: 12, mt: 1.5 }} dir="ltr">
              {toDelete.folder}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToDelete(null)}>{t('Cancel')}</Button>
          <Button color="error" variant="contained" onClick={confirmDelete} disabled={deleting}>
            {t('Delete')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default RecordingsLibrary;
