/**
 * `video/VideoLibrary.tsx` — the **Recorded videos** page.
 *
 * ★ ONE PLACE FOR EVERY VIDEO (2026-09-07, owner ask): the recordings the live
 *   cameras made (`RecordingsLibrary`, first — they are what the page is named
 *   for) and the clips uploaded by hand, both as cards with a picture, a name and
 *   one door. A search narrows both; a toggle shows one kind at a time.
 *
 * ★ A CLIP IS A FRAME SOURCE. Uploaded clips still belong to a project (the frames
 *   they yield are that project's photographs); the work on them happens on the
 *   scrub-and-capture page. A clip's captured frames are one press away, in a
 *   dialog — found by provenance, not bookkeeping: a captured frame is a real
 *   image row whose `source_video_id` names its video.
 *
 * ★ UPLOAD PICKS THE OWNING PROJECT FIRST — or skips it: a clip for detection or
 *   drift work need not belong to a survey project; it lives in the library and a
 *   frame captured from it asks for its project later.
 */

import { useMemo, useState, type JSX, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import InputLabel from '@mui/material/InputLabel';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import PhotoLibraryOutlinedIcon from '@mui/icons-material/PhotoLibraryOutlined';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SearchIcon from '@mui/icons-material/Search';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import VideoFileOutlinedIcon from '@mui/icons-material/VideoFileOutlined';

import { useAllVideos } from '../../api/hooks/useVideos';
import { useImages } from '../../api/hooks/useImages';
import { useCreateProject, useProjects } from '../../api/hooks/useProjects';
import { videosApi } from '../../api/videos';
import { fmtClock } from '../../lib/clock';
import { videoHref } from '../../lib/videoHref';
import { useNotify } from '../common/Notifications';
import { RecordingsLibrary } from './RecordingsLibrary';
import { VideoUploadDialog } from './VideoUploadDialog';
import { asUuid, type Uuid } from '../../types/common';
import type { VideoSummary } from '../../types/video';
import { t } from '../../i18n';

// ─────────────────────────────────────────────────────────────────────────────
// A clip's captured frames
// ─────────────────────────────────────────────────────────────────────────────

function FramesDialog({
  video,
  projectName,
  open,
  onClose,
}: {
  video: VideoSummary;
  projectName: string;
  open: boolean;
  onClose: () => void;
}): JSX.Element {
  const navigate = useNavigate();
  // ★ Fetched only while the dialog is open — a closed card costs nothing.
  const { data: imagesPage, isLoading } = useImages(
    open && video.project_id !== null ? video.project_id : null,
  );
  const frames = useMemo(
    () => (imagesPage?.items ?? []).filter((image) => image.source_video_id === video.id),
    [imagesPage, video.id],
  );
  const go = (to: string): void => {
    onClose();
    navigate(to);
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ pb: 0.5 }}>
        {t('Captured frames')}
        <Typography variant="body2" color="text.secondary" noWrap title={video.filename}>
          {video.filename} · {projectName}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {video.project_id === null ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 1.5 }}>
            {t('A library-only clip keeps its frames in the project chosen at capture time.')}
          </Typography>
        ) : isLoading ? (
          <Box sx={{ display: 'grid', placeItems: 'center', py: 2 }}>
            <CircularProgress size={20} />
          </Box>
        ) : frames.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 1.5 }}>
            {t(
              'No frames captured from this video yet — open scrub & capture and seek to the moment you need.',
            )}
          </Typography>
        ) : (
          <List dense disablePadding>
            {frames.map((frame) => (
              <ListItemButton
                key={frame.id}
                onClick={() => go(`/projects/${video.project_id ?? ''}/images/${frame.id}`)}
                sx={{ borderRadius: 1 }}
              >
                <ListItemIcon sx={{ minWidth: 34 }}>
                  <ImageOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary={frame.filename}
                  secondary={`${frame.width} × ${frame.height}${frame.gcp_count > 0 ? ` · ${frame.gcp_count} GCPs` : ''}`}
                  primaryTypographyProps={{ noWrap: true, title: frame.filename }}
                />
                <Tooltip title={t('Image setup')}>
                  <IconButton
                    size="small"
                    edge="end"
                    aria-label={`${t('Image setup')} ${frame.filename}`}
                    onClick={(e: MouseEvent) => {
                      e.stopPropagation();
                      go(`/projects/${video.project_id ?? ''}/images/${frame.id}/setup`);
                    }}
                  >
                    <TuneOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </ListItemButton>
            ))}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => go(videoHref(video))} startIcon={<PlayArrowRoundedIcon />}>
          {t('Scrub & capture')}
        </Button>
        <Button onClick={onClose}>{t('Close')}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// One clip
// ─────────────────────────────────────────────────────────────────────────────

function ClipCard({
  video,
  projectName,
}: {
  video: VideoSummary;
  projectName: string;
}): JSX.Element {
  const navigate = useNavigate();
  const [framesOpen, setFramesOpen] = useState(false);
  const [posterFailed, setPosterFailed] = useState(false);
  const open = (): void => navigate(videoHref(video));

  return (
    <Box
      component="li"
      aria-label={video.filename}
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
      <ButtonBase
        onClick={open}
        aria-label={`${t('Open')} ${video.filename} ${t('in scrub & capture')}`}
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
        {!posterFailed ? (
          <Box
            component="img"
            alt=""
            src={videosApi.frameUrl(video.id, 0)}
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
            <VideoFileOutlinedIcon sx={{ fontSize: 36 }} />
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
          {fmtClock(video.duration_s)}
        </Box>
      </ButtonBase>

      <Stack spacing={1} sx={{ p: 1.5, flex: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            variant="subtitle2"
            noWrap
            title={video.filename}
            sx={{ fontWeight: 700, lineHeight: 1.2, fontSize: 14 }}
          >
            {video.filename}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            {projectName} · {video.width}×{video.height}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} sx={{ mt: 'auto' }}>
          <Button
            size="small"
            variant="contained"
            fullWidth
            startIcon={<PlayArrowRoundedIcon />}
            onClick={open}
          >
            {t('Scrub & capture')}
          </Button>
          <Tooltip title={t('Captured frames')}>
            <Button
              size="small"
              variant="outlined"
              aria-label={`${t('Captured frames')} ${video.filename}`}
              onClick={() => setFramesOpen(true)}
              sx={{ minWidth: 40, px: 1, flexShrink: 0 }}
            >
              <PhotoLibraryOutlinedIcon fontSize="small" />
            </Button>
          </Tooltip>
        </Stack>
      </Stack>
      <FramesDialog
        video={video}
        projectName={projectName}
        open={framesOpen}
        onClose={() => setFramesOpen(false)}
      />
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

type Shown = 'all' | 'recordings' | 'clips';

export function VideoLibrary(): JSX.Element {
  const navigate = useNavigate();
  const { data: videosPage, isLoading, isError, refetch } = useAllVideos();
  const { data: projectsPage } = useProjects({ limit: 100, sort: 'name' });
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState<Shown>('all');
  const needle = query.trim().toLowerCase();

  const projects = useMemo(() => projectsPage?.items ?? [], [projectsPage]);
  const videos = useMemo(() => videosPage?.items ?? [], [videosPage]);
  const projectName = useMemo(() => {
    const byId = new Map(projects.map((p) => [p.id as string, p.name]));
    return (id: Uuid | null): string =>
      id === null ? t('Library only') : (byId.get(id as string) ?? 'Unknown project');
  }, [projects]);
  const clips = useMemo(
    () =>
      videos.filter(
        (v) =>
          needle === '' ||
          v.filename.toLowerCase().includes(needle) ||
          projectName(v.project_id).toLowerCase().includes(needle),
      ),
    [videos, needle, projectName],
  );

  // Upload = pick the owning project, then the normal video upload dialog.
  const [picking, setPicking] = useState(false);
  const [pickedProject, setPickedProject] = useState<string>('');
  // ★ Inline "new project" lane inside the picker: the video often arrives BEFORE
  //   its project exists, and bouncing away to make one just to come back here
  //   was a dead end. A blank project needs only a name.
  const [creatingNew, setCreatingNew] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const createProject = useCreateProject();
  const notify = useNotify();
  // ★ `undefined` = no upload dialog; `null` = upload with NO project (library only).
  const [uploadingFor, setUploadingFor] = useState<Uuid | null | undefined>(undefined);

  const createAndContinue = (): void => {
    const trimmed = newProjectName.trim();
    if (trimmed === '') return;
    createProject.mutate(
      { name: trimmed, description: null },
      {
        onSuccess: (project) => {
          setPicking(false);
          setCreatingNew(false);
          setNewProjectName('');
          setUploadingFor(asUuid(project.id));
        },
        onError: () => notify('Could not create the project.', { severity: 'error' }),
      },
    );
  };

  return (
    <Box>
      {/* ── the header: what the page holds, find one fast, upload ─────────── */}
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        alignItems={{ xs: 'stretch', md: 'center' }}
        sx={{ mb: 3 }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            {t('Recorded videos')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t(
              'What the cameras recorded, and the clips you upload — watch one beside its table, or scrub to a moment and keep the frame.',
            )}
          </Typography>
        </Box>
        <TextField
          size="small"
          placeholder={t('Search recordings and clips')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          inputProps={{ 'aria-label': t('Search recordings and clips') }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
          sx={{ width: { xs: '100%', md: 260 } }}
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
          <ToggleButton value="recordings">{t('Recordings')}</ToggleButton>
          <ToggleButton value="clips">{t('Clips')}</ToggleButton>
        </ToggleButtonGroup>
        <Button
          variant="contained"
          startIcon={<VideoFileOutlinedIcon />}
          onClick={() => setPicking(true)}
          sx={{ flexShrink: 0 }}
        >
          {t('Upload video')}
        </Button>
      </Stack>

      {/* ── the recordings first — they are what the page is named for ────── */}
      {shown !== 'clips' && (
        <Box sx={{ mb: 4 }}>
          <RecordingsLibrary query={needle} />
        </Box>
      )}

      {/* ── the uploaded clips ─────────────────────────────────────────────── */}
      {shown !== 'recordings' && (
        <Box component="section" aria-labelledby="uploaded-clips-title">
          <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 0.25 }}>
            <Typography
              id="uploaded-clips-title"
              variant="h6"
              component="h2"
              sx={{ fontWeight: 700, lineHeight: 1.2 }}
            >
              {t('Uploaded clips')}
            </Typography>
            {!isLoading && !isError && (
              <Typography className="le-mono" sx={{ fontSize: 11, color: 'text.secondary' }}>
                {videos.length}
              </Typography>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
            {t('Scrub a clip to the moment and keep that frame as a photograph.')}
          </Typography>
          {isLoading ? (
            <Box sx={{ display: 'grid', placeItems: 'center', py: 4 }}>
              <CircularProgress size={22} />
            </Box>
          ) : isError ? (
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ py: 2 }}>
              <Typography variant="body2" color="error">
                {t('Could not load videos')}
              </Typography>
              <Button size="small" variant="outlined" onClick={() => void refetch()}>
                {t('Try again')}
              </Button>
            </Stack>
          ) : videos.length === 0 ? (
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
              <VideoFileOutlinedIcon />
              <Typography variant="body2">{t('No clips uploaded yet')}</Typography>
              <Button
                size="small"
                variant="outlined"
                startIcon={<VideoFileOutlinedIcon />}
                onClick={() => setPicking(true)}
              >
                {t('Upload video')}
              </Button>
            </Stack>
          ) : clips.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
              {t('No clip matches.')}
            </Typography>
          ) : (
            <Box
              component="ul"
              aria-label={t('Uploaded clips')}
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
              {clips.map((video) => (
                <ClipCard
                  key={video.id}
                  video={video}
                  projectName={projectName(video.project_id)}
                />
              ))}
            </Box>
          )}
        </Box>
      )}

      {/* Step 1 — which project owns this video (its frames become that project's photos). */}
      <Dialog open={picking} onClose={() => setPicking(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Upload a video')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t(
              'Pick the project this video belongs to — frames you capture from it become that project’s photographs.',
            )}
          </Typography>
          {!creatingNew ? (
            <>
              <FormControl fullWidth size="small" disabled={projects.length === 0}>
                <InputLabel id="video-project-label">{t('Project')}</InputLabel>
                <Select
                  labelId="video-project-label"
                  label={t('Project')}
                  value={pickedProject}
                  onChange={(e) => setPickedProject(e.target.value)}
                >
                  {projects.map((p) => (
                    <MenuItem key={p.id} value={p.id}>
                      {p.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {/* ★ The no-project case is a LANE, not a dead end: the video is in
                  hand NOW, so the project it needs is one name away. */}
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() => setCreatingNew(true)}
                sx={{ mt: 1.5 }}
              >
                {t('New project for this video')}
              </Button>
            </>
          ) : (
            <TextField
              autoFocus
              fullWidth
              size="small"
              label={t('New project name')}
              value={newProjectName}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setNewProjectName(e.target.value)
              }
              onKeyDown={(e: React.KeyboardEvent) => {
                if (e.key === 'Enter' && !createProject.isPending) createAndContinue();
              }}
              helperText="Just a name — the video (and every frame you capture from it) lands in this project; each photo gets its camera setup when you open it."
              disabled={createProject.isPending}
            />
          )}
        </DialogContent>
        <DialogActions>
          {creatingNew ? (
            <>
              <Button onClick={() => setCreatingNew(false)} disabled={createProject.isPending}>
                {t('Back')}
              </Button>
              <Button
                variant="contained"
                disabled={newProjectName.trim() === '' || createProject.isPending}
                onClick={createAndContinue}
              >
                {createProject.isPending ? 'Creating…' : 'Create & continue'}
              </Button>
            </>
          ) : (
            <>
              <Button onClick={() => setPicking(false)}>{t('Cancel')}</Button>
              {/* ★ THE SKIP LANE: a clip for detection or drift work need not belong to
                  a survey project. It lives in the library; a captured frame asks for
                  its project later. */}
              <Button
                onClick={() => {
                  setPicking(false);
                  setUploadingFor(null);
                }}
              >
                {t('Skip — library only')}
              </Button>
              <Button
                variant="contained"
                disabled={pickedProject === ''}
                onClick={() => {
                  setPicking(false);
                  setUploadingFor(asUuid(pickedProject));
                }}
              >
                {t('Continue')}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>

      {uploadingFor !== undefined && (
        <VideoUploadDialog
          open
          projectId={uploadingFor}
          onClose={() => setUploadingFor(undefined)}
          onUploaded={(videoId) => {
            const projectId = uploadingFor;
            setUploadingFor(undefined);
            navigate(videoHref({ id: videoId, project_id: projectId }));
          }}
        />
      )}
    </Box>
  );
}

export default VideoLibrary;
