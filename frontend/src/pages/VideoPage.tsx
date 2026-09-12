/**
 * `pages/VideoPage.tsx` — `/projects/:projectId/videos/:videoId`, and `/videos/:videoId`
 * for a clip that lives in the library only (no project).
 *
 * ★ Renders the `VideoPlayer` (scrub → capture a frame → land in that image's
 *   workspace) with a back link to the project. Lazy in `router.tsx`, like the
 *   workspace: nobody reading a project list should download this.
 *
 * ★ DEGRADES GRACEFULLY. The `/videos` endpoints are built concurrently — while they
 *   are absent the query errors, and this page shows an honest explainer with a way
 *   back, never an infinite spinner.
 */

import { type JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useVideo } from '../api/hooks/useVideos';
import { VideoPlayer } from '../components/video/VideoPlayer';
import { EmptyState } from '../components/common/EmptyState';
import { asUuid } from '../types/common';
import { cameraRefForProject, cameraSettingsPath } from '../lib/cameras/projectCamera';
import { t } from '../i18n';

export function VideoPage(): JSX.Element {
  const navigate = useNavigate();
  const params = useParams();
  const projectId = params.projectId ? asUuid(params.projectId) : null;
  const videoId = params.videoId ? asUuid(params.videoId) : null;

  const { data: video, isLoading, isError, refetch } = useVideo(videoId);

  const backToProject = (): void => {
    // ★ A camera's clip goes back to the camera; there is no project page (2026-09-04).
    const ref = cameraRefForProject(projectId);
    navigate(ref !== null ? cameraSettingsPath(ref) : '/videos');
  };

  if (videoId === null) {
    return (
      <Box sx={{ flex: 1, display: 'flex' }}>
        <EmptyState
          title={t('No video selected')}
          description="This page needs a video in its URL."
          primaryAction={{ label: 'Back to the Video editor', onClick: () => navigate('/videos') }}
        />
      </Box>
    );
  }

  if (isLoading) {
    return (
      <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (isError || !video) {
    return (
      <Box sx={{ flex: 1, display: 'flex' }}>
        <EmptyState
          title={t('This video isn’t available')}
          description="It may still be processing, or video support may not be enabled in this build yet."
          primaryAction={{ label: 'Try again', onClick: () => void refetch() }}
          secondaryAction={{ label: 'Back to project', onClick: backToProject }}
        />
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, overflow: 'auto' }}>
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Stack spacing={3}>
          <Box>
            <Typography variant="h4" noWrap title={video.filename}>
              {video.filename}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('Seek to a second, then capture that frame to annotate it as a photo.')}
            </Typography>
          </Box>

          <VideoPlayer video={video} />
        </Stack>
      </Container>
    </Box>
  );
}

export default VideoPage;
