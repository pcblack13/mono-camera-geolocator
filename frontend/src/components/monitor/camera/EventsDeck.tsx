/**
 * `monitor/camera/EventsDeck.tsx` — the log: what changed, and when.
 *
 * ★ Newest first, each line a timestamp in tabular mono and one sentence. Warnings
 *   and errors are toned; nothing is summarised away.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { MonitorEvent } from '../../../hooks/useMonitorEvents';
import { t } from '../../../i18n';

export interface EventsDeckProps {
  events: MonitorEvent[];
  onClear: () => void;
}

function stamp(at: number): string {
  return new Date(at).toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}

const TONE: Record<NonNullable<MonitorEvent['tone']>, string> = {
  ok: 'var(--status-ok)',
  warn: 'var(--status-warn)',
  error: 'var(--status-error)',
};

export function EventsDeck({ events, onClear }: EventsDeckProps): JSX.Element {
  if (events.length === 0) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t(
            'Nothing has happened on this camera yet. Stream, detection and drift events are recorded here.',
          )}
        </Typography>
      </Box>
    );
  }
  return (
    <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <Stack direction="row" sx={{ px: 1, py: 0.5 }}>
        <Box sx={{ flex: 1 }} />
        <Button size="small" onClick={onClear}>
          {t('Clear')}
        </Button>
      </Stack>
      <Box component="ol" sx={{ flex: 1, overflowY: 'auto', m: 0, p: 0, listStyle: 'none' }}>
        {[...events].reverse().map((e, i) => (
          <Stack
            key={`${e.at}:${i}`}
            component="li"
            direction="row"
            spacing={1.5}
            sx={{ px: 1.5, py: 0.5, borderBottom: '1px solid var(--hairline)' }}
          >
            <Typography
              variant="mono"
              sx={{ fontSize: 12, color: 'var(--text-tertiary)', direction: 'ltr', flexShrink: 0 }}
            >
              {stamp(e.at)}
            </Typography>
            <Typography
              variant="caption"
              sx={{
                fontSize: 11,
                letterSpacing: '0.06em',
                color: 'var(--text-tertiary)',
                width: 72,
                flexShrink: 0,
              }}
            >
              {e.kind.toUpperCase()}
            </Typography>
            <Typography variant="body2" sx={{ color: e.tone ? TONE[e.tone] : 'inherit' }}>
              {e.message}
            </Typography>
          </Stack>
        ))}
      </Box>
    </Box>
  );
}
