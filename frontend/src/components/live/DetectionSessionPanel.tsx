/**
 * `live/DetectionSessionPanel.tsx` — the run's truth, beside the stream stats.
 *
 * ★ EVERY HONESTY COUNTER THE PIPELINE KEEPS IS SHOWN, because each one is a claim
 *   the marks depend on: frames the detector never saw (the price of staying live),
 *   ground pixels with no terrain (counted, never guessed), marks dropped by the
 *   cap. A panel that showed only the successes would make the map look more
 *   complete than the run was.
 */

import type { JSX } from 'react';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { DetectionSession } from '../../api/detection';
import { useT } from '../../i18n';
// ★ Phase 2: this panel is the primitives' first real home — StatReadout for the
//   honesty counters, ErrorState for the server's verbatim words, StatusPill for
//   the run's lifecycle (shape, not colour — colour stays with accuracy).
import { ErrorState, StatReadout, StatusPill } from '../ui';

const Row = StatReadout;

export function DetectionSessionPanel({ session }: { session: DetectionSession }): JSX.Element {
  const t = useT();
  const running = session.status === 'starting' || session.status === 'running';

  return (
    <Card variant="outlined" sx={{ width: '100%', borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle2" sx={{ flex: 1 }}>
            {t('Detection')}
          </Typography>
          <StatusPill
            lifecycle={
              session.status === 'failed'
                ? 'refused'
                : running
                  ? 'draft' // a run in flight is not yet a result
                  : 'committed'
            }
          >
            {session.status.toUpperCase()}
          </StatusPill>
        </Stack>

        {session.error !== null && (
          <Stack sx={{ mb: 1 }}>
            <ErrorState message={session.error} />
          </Stack>
        )}

        <Row label={t('Device')} value={session.device_name || '—'} />
        <Row
          label={t('Algorithm')}
          value={
            session.phase === 'tracker'
              ? t('CSRT tracking (locked)')
              : Number(session.settings?.tracker_start_frame ?? 0) > 0
                ? `YOLO — CSRT locks after ${String(session.settings.tracker_start_frame)} sightings`
                : t('YOLO every frame')
          }
        />
        <Row label={t('Detected FPS')} value={session.fps > 0 ? session.fps.toFixed(1) : '—'} />
        <Row label={t('Frames detected')} value={String(session.frames_done)} />
        {/* ★ The price of staying live, stated — not hidden in a log. */}
        <Row label={t('Frames skipped')} value={String(session.frames_dropped)} />
        {session.lut_site !== null ? (
          <>
            <Row label={t('Lookup table')} value={session.lut_site} />
            <Row label={t('Marks placed')} value={String(session.marks_total)} />
            <Row label={t('No terrain under feet')} value={String(session.skipped_no_terrain)} />
            {session.marks_dropped > 0 && (
              <Row label={t('Oldest marks dropped')} value={String(session.marks_dropped)} />
            )}
          </>
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            {t(
              'No lookup table chosen — objects are detected and counted but not placed on the map.',
            )}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
