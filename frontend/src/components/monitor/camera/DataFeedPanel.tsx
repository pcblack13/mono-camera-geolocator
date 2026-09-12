/**
 * `monitor/camera/DataFeedPanel.tsx` — the hero for an integration with NO picture.
 *
 * ★ A serial/UART device or a Pi that SENDS detections has nothing to stream;
 *   pretending otherwise would be a black rectangle. This panel stands where the
 *   video would: the feed's state, its wire, the flow of lines, and the newest
 *   detection — while the map beside it does the real showing.
 */

import { type JSX } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';

import type { DetectionMark } from '../../../api/detection';
import type { DataFeedRead } from '../../../api/live';
import { StatusPill, type Lifecycle } from '../../ui';
import { t } from '../../../i18n';

export interface DataFeedPanelProps {
  feed: DataFeedRead | null;
  /** The feed's newest mark, when one exists. */
  latest: DetectionMark | null;
  error: string | null;
}

const PILL: Record<string, { lifecycle: Lifecycle; label: string }> = {
  starting: { lifecycle: 'draft', label: 'connecting' },
  running: { lifecycle: 'committed', label: 'receiving' },
  stopped: { lifecycle: 'stale', label: 'stopped' },
  failed: { lifecycle: 'refused', label: 'failed' },
};

function Readout({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <Stack direction="row" spacing={1} alignItems="baseline">
      <Typography
        className="le-mono"
        sx={{ fontSize: 10.5, color: 'text.disabled', width: 96, textTransform: 'uppercase' }}
      >
        {label}
      </Typography>
      <Typography className="le-mono" sx={{ fontSize: 12.5 }} dir="ltr">
        {value}
      </Typography>
    </Stack>
  );
}

export function DataFeedPanel({ feed, latest, error }: DataFeedPanelProps): JSX.Element {
  const pill = PILL[feed?.status ?? 'starting'] ?? PILL.starting;
  return (
    <Box
      sx={{
        height: '100%',
        display: 'grid',
        placeItems: 'center',
        bgcolor: 'var(--bg-canvas)',
        p: 2,
      }}
    >
      <Stack spacing={1.25} sx={{ maxWidth: 420, width: '100%' }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <SensorsOutlinedIcon sx={{ color: 'var(--accent)' }} />
          <Typography variant="subtitle2" sx={{ flex: 1 }}>
            {t('Detection data feed')}
          </Typography>
          <StatusPill lifecycle={pill.lifecycle}>{t(pill.label)}</StatusPill>
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {t(
            'This integration sends detections instead of video — every line it emits becomes a point on the map.',
          )}
        </Typography>
        <Readout label={t('wire')} value={feed?.source ?? '—'} />
        <Readout
          label={t('received')}
          value={
            feed === null ? '—' : `${feed.lines_ok} ${t('lines')} · ${feed.lines_bad} ${t('bad')}`
          }
        />
        <Readout
          label={t('newest')}
          value={
            latest === null
              ? t('nothing yet')
              : `${latest.cls_name}${latest.track_id !== null ? ` #${latest.track_id}` : ''} @ ${
                  latest.lat === null || latest.lon === null
                    ? t('no position')
                    : `${latest.lat.toFixed(6)}, ${latest.lon.toFixed(6)}`
                }`
          }
        />
        {(error !== null || feed?.error != null) && (
          <Typography className="le-mono" sx={{ fontSize: 11, color: 'var(--status-error)' }}>
            {error ?? feed?.error}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}
