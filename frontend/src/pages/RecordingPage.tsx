/**
 * `pages/RecordingPage.tsx` — `/videos/recordings/:folder`: a camera's recording,
 * watched in the app beside its attribute table (2026-09-07, owner ask).
 *
 * ★ The page is the frame around `RecordingViewer`: the folder's name and facts,
 *   the downloads, and the viewer. A trim moves the page to the new recording it
 *   wrote. Lazy in `router.tsx`, like every player.
 *
 * ★ THE PACKAGE IS THE PRIMARY DOWNLOAD (2026-09-12, owner ask): the video, the
 *   satellite map of the scene and the attribute table, one folder, one file. The
 *   single-file buttons stay beside it for whoever wants only one of the three.
 */

import type { JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import FolderZipOutlinedIcon from '@mui/icons-material/FolderZipOutlined';
import MovieOutlinedIcon from '@mui/icons-material/MovieOutlined';

import { liveApi } from '../api/live';
import { EmptyState } from '../components/common/EmptyState';
import { RecordingViewer } from '../components/video/RecordingViewer';
import { fmtClock } from '../lib/clock';
import { t } from '../i18n';

export function RecordingPage(): JSX.Element {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { folder } = useParams();
  const table = useQuery({
    queryKey: ['live', 'recordings', 'table', folder ?? ''],
    queryFn: ({ signal }) => liveApi.recordingTable(folder ?? '', signal),
    enabled: folder !== undefined && folder !== '',
  });

  if (folder === undefined || folder === '') {
    return (
      <Box sx={{ flex: 1, display: 'flex' }}>
        <EmptyState
          title={t('No recording selected')}
          description={t('This page needs a recording in its URL.')}
          primaryAction={{
            label: t('Back to Recorded videos'),
            onClick: () => navigate('/videos'),
          }}
        />
      </Box>
    );
  }
  if (table.isLoading) {
    return (
      <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }
  if (table.isError || table.data === undefined) {
    return (
      <Box sx={{ flex: 1, display: 'flex' }}>
        <EmptyState
          title={t('This recording isn’t available')}
          description={t('It may have been deleted, or the server could not read its folder.')}
          primaryAction={{ label: t('Try again'), onClick: () => void table.refetch() }}
          secondaryAction={{
            label: t('Back to Recorded videos'),
            onClick: () => navigate('/videos'),
          }}
        />
      </Box>
    );
  }

  const data = table.data;
  const started = data.started_at ? new Date(data.started_at).toLocaleString() : '';

  return (
    <Box sx={{ flex: 1, overflow: 'auto' }}>
      <Container maxWidth="xl" sx={{ py: { xs: 2, md: 3 } }}>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={2}
          alignItems={{ xs: 'flex-start', md: 'center' }}
          sx={{ mb: 2 }}
        >
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              variant="h5"
              component="h1"
              className="le-mono"
              noWrap
              title={data.folder}
              sx={{ fontWeight: 700, lineHeight: 1.2 }}
            >
              {data.folder}
            </Typography>
            <Typography variant="body2" color="text.secondary" component="div">
              {data.camera_name} · <bdi dir="ltr">{started}</bdi> · {fmtClock(data.duration_s)} ·{' '}
              <bdi>
                {data.rows.length} {t('rows')}
              </bdi>
              {data.trimmed_from ? (
                <>
                  {' · '}
                  <bdi>
                    {t('cut from')} {data.trimmed_from}
                  </bdi>
                </>
              ) : null}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} sx={{ flexShrink: 0, flexWrap: 'wrap' }}>
            <Button
              size="small"
              variant="contained"
              startIcon={<FolderZipOutlinedIcon />}
              component="a"
              href={liveApi.recordingPackageUrl(data.folder)}
              download
              title={t('The video, the satellite map and the attribute table — one folder')}
            >
              {t('Download the package')}
            </Button>
            {data.has_video && (
              <Button
                size="small"
                variant="outlined"
                startIcon={<MovieOutlinedIcon />}
                component="a"
                href={liveApi.recordingFileUrl(data.folder, 'video.mp4')}
                download
              >
                {t('Download the video')}
              </Button>
            )}
            <Button
              size="small"
              variant="outlined"
              startIcon={<DescriptionOutlinedIcon />}
              component="a"
              href={liveApi.recordingFileUrl(data.folder, 'detections.csv')}
              download
            >
              {t('Download the table (CSV)')}
            </Button>
          </Stack>
        </Stack>

        <RecordingViewer
          key={data.folder}
          table={data}
          onTrimmed={(entry) => {
            void queryClient.invalidateQueries({ queryKey: ['live', 'recordings'] });
            navigate(`/videos/recordings/${encodeURIComponent(entry.folder)}`);
          }}
        />
      </Container>
    </Box>
  );
}

export default RecordingPage;
