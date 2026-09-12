/**
 * `monitor/camera/DetectionsDeck.tsx` — every mark of the run, as a table.
 *
 * ★ VIRTUALISED: the DOM holds the rows in view plus a margin, positioned by two
 *   spacer rows, so a night's run costs what a screenful costs. Filter by class;
 *   export the current run as CSV from the data already in memory — no request.
 *
 * ★ THE TRACK IS THE FIRST COLUMN (2026-09-11, owner ask): a tracking system is
 *   organised by WHO, not by when. Every track the run has seen is a chip; one
 *   chip filters the table and the export to that object. A track can be NAMED —
 *   "#3" becomes "white pickup" — and the name rides the table, the export and
 *   the picture. Marks keep the id; the name is looked up, so it is one edit.
 */

import { useMemo, useState, type JSX, type KeyboardEvent } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import InputBase from '@mui/material/InputBase';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';

import type { DetectionMark } from '../../../api/detection';
import { t } from '../../../i18n';

export interface DetectionsDeckProps {
  marks: DetectionMark[];
  /** Epoch ms the run started — a mark's `time_s` is relative to it. */
  runStartedMs: number;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  cameraName: string;
  /** The operator's names for tracks, keyed by the id as a string (the wire's form). */
  trackNames?: Record<string, string>;
  /** Rename a track (empty clears). Absent = names are read-only here. */
  onRenameTrack?: (trackId: number, name: string) => void;
  /** The track to show alone, driven from outside (a click on a box); null = all. */
  trackFilter?: number | null;
  onTrackFilterChange?: (trackId: number | null) => void;
}

/** "#3" or "#3 · white pickup" — the track as the table and the export say it. */
export function trackLabel(trackId: number | null, names?: Record<string, string>): string {
  if (trackId === null) return '—';
  const name = names?.[String(trackId)];
  return name ? `#${trackId} · ${name}` : `#${trackId}`;
}

const ROW_PX = 30;
const OVERSCAN = 8;

/**
 * The mark's wall clock, three renderings — date, local time, UTC time.
 *
 * ★ THE SERVER'S RECORD WINS. Marks carry `detected_at` / `detected_at_local`,
 *   stamped at the instant of detection (owner request 2026-08-31); those strings
 *   are shown verbatim. Marks from an older backend fall back to deriving from
 *   the run start — same answer on the desktop app, where browser and server
 *   share a machine and a zone.
 */
export function clockOf(
  m: DetectionMark,
  runStartedMs: number,
): { date: string; local: string; utc: string } {
  if (m.detected_at_local != null && m.detected_at_local.includes('T')) {
    const [date, tail] = m.detected_at_local.split('T');
    return {
      date,
      local: tail.slice(0, 8),
      utc: m.detected_at != null ? m.detected_at.slice(11, 19) : '—',
    };
  }
  if (!Number.isFinite(runStartedMs)) return { date: '—', local: '—', utc: '—' };
  const dt = new Date(runStartedMs + m.time_s * 1000);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return {
    date: `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`,
    local: `${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}`,
    utc: dt.toISOString().slice(11, 19),
  };
}

export function marksToCsv(
  marks: DetectionMark[],
  runStartedMs: number,
  trackNames: Record<string, string> = {},
): string {
  // ★ `drift` and `centre_m` state what each coordinate claims (1.3): the camera's
  //   drift verdict when the mark was placed, and any centre offset applied.
  //   `track_name` is the operator's word for the object, beside the id it names.
  const head =
    'date,time_local,time_utc,class,confidence,lat,lon,track_id,track_name,frame_index,u,v,predicted,drift,drift_shift_m,centre_m';
  const rows = marks.map((m) => {
    const clock = clockOf(m, runStartedMs);
    return [
      clock.date,
      m.detected_at_local ?? clock.local,
      m.detected_at ??
        (Number.isFinite(runStartedMs)
          ? new Date(runStartedMs + m.time_s * 1000).toISOString()
          : ''),
      m.cls_name,
      m.score.toFixed(3),
      // ★ An unplaced detection exports an EMPTY cell, never a zero.
      m.lat === null ? '' : m.lat.toFixed(7),
      m.lon === null ? '' : m.lon.toFixed(7),
      m.track_id ?? '',
      csvCell(m.track_id === null ? '' : (trackNames[String(m.track_id)] ?? '')),
      m.frame_index,
      m.u ?? '',
      m.v ?? '',
      m.predicted ? 1 : 0,
      m.drift_status ?? 'unwatched',
      m.drift_shift_m ?? '',
      m.centre_offset_m ?? '',
    ].join(',');
  });
  return [head, ...rows].join('\n');
}

/** A CSV cell that may hold a comma, a quote or nothing. */
function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function DetectionsDeck(p: DetectionsDeckProps): JSX.Element {
  const [cls, setCls] = useState<string | null>(null);
  const [ownTrack, setOwnTrack] = useState<number | null>(null);
  // ★ The track filter is the page's when the page drives it (a click on a box
  //   in the picture filters the table), the deck's own otherwise.
  const track = p.trackFilter !== undefined ? p.trackFilter : ownTrack;
  const setTrack = (id: number | null): void => {
    setOwnTrack(id);
    p.onTrackFilterChange?.(id);
  };
  // ★ The editor opens in ONE row — the row whose pencil was pressed — even though
  //   a track has many rows. Two editors for one track would autofocus each other
  //   apart: the second's focus blurs the first, the blur commits, and both close.
  const [editing, setEditing] = useState<{ id: number; row: number; value: string } | null>(
    null,
  );
  const [scrollTop, setScrollTop] = useState(0);
  const [viewPx, setViewPx] = useState(240);
  const names = p.trackNames ?? {};

  const classes = useMemo(() => [...new Set(p.marks.map((m) => m.cls_name))].sort(), [p.marks]);
  // Every track the run has seen, ascending — the chips.
  const tracks = useMemo(
    () =>
      [...new Set(p.marks.flatMap((m) => (m.track_id === null ? [] : [m.track_id])))].sort(
        (a, b) => a - b,
      ),
    [p.marks],
  );
  const keep = (m: DetectionMark): boolean =>
    (cls === null || m.cls_name === cls) && (track === null || m.track_id === track);
  // Newest first; keep the ORIGINAL index so selection lines up with the map.
  const rows = useMemo(() => {
    const out: Array<{ m: DetectionMark; i: number }> = [];
    for (let i = p.marks.length - 1; i >= 0; i -= 1) {
      if (keep(p.marks[i])) out.push({ m: p.marks[i], i });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.marks, cls, track]);

  const commitName = (): void => {
    if (editing === null) return;
    p.onRenameTrack?.(editing.id, editing.value.trim());
    setEditing(null);
  };
  const onNameKey = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter') commitName();
    if (e.key === 'Escape') setEditing(null);
  };
  const start = Math.max(0, Math.floor(scrollTop / ROW_PX) - OVERSCAN);
  const end = Math.min(rows.length, Math.ceil((scrollTop + viewPx) / ROW_PX) + OVERSCAN);

  const exportCsv = (): void => {
    // ★ The export is what the table shows: the same class AND track filters.
    const blob = new Blob([marksToCsv(p.marks.filter(keep), p.runStartedMs, names)], {
      type: 'text/csv',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${p.cameraName.replace(/[^A-Za-z0-9_-]+/g, '_')}_detections.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (p.marks.length === 0) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t('No marks yet — they appear here the moment a detected object lands on the map.')}
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <Stack
        direction="row"
        spacing={0.75}
        alignItems="center"
        sx={{ px: 1, py: 0.5, flexWrap: 'wrap' }}
      >
        <Chip
          size="small"
          label={t('All')}
          variant={cls === null ? 'filled' : 'outlined'}
          onClick={() => setCls(null)}
        />
        {classes.map((c) => (
          <Chip
            key={c}
            size="small"
            label={c}
            variant={cls === c ? 'filled' : 'outlined'}
            onClick={() => setCls(c)}
          />
        ))}
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={exportCsv}>
          {t('Export CSV')}
        </Button>
      </Stack>
      {/* ★ THE TRACK CHIPS: one per object the run has followed. A chip shows the
          table — and the export — for that object alone. Absent until a track
          exists, because a filter over nothing is noise. */}
      {tracks.length > 0 && (
        <Stack
          direction="row"
          spacing={0.75}
          alignItems="center"
          sx={{ px: 1, pb: 0.5, flexWrap: 'wrap' }}
          data-testid="track-filter"
        >
          <Typography variant="caption" color="text.secondary" sx={{ mr: 0.25 }}>
            {t('Track')}
          </Typography>
          <Chip
            size="small"
            label={t('All tracks')}
            variant={track === null ? 'filled' : 'outlined'}
            onClick={() => setTrack(null)}
          />
          {tracks.map((id) => (
            <Chip
              key={id}
              size="small"
              label={trackLabel(id, names)}
              color={track === id ? 'primary' : 'default'}
              variant={track === id ? 'filled' : 'outlined'}
              onClick={() => setTrack(track === id ? null : id)}
            />
          ))}
        </Stack>
      )}
      <TableContainer
        sx={{ flex: 1 }}
        ref={(el: HTMLDivElement | null) => {
          if (el && el.clientHeight !== viewPx && el.clientHeight > 0) setViewPx(el.clientHeight);
        }}
        onScroll={(e) => setScrollTop((e.currentTarget as HTMLDivElement).scrollTop)}
      >
        <Table size="small" stickyHeader aria-label={t('Detections')}>
          <TableHead>
            <TableRow>
              <TableCell>{t('Track')}</TableCell>
              <TableCell>{t('Date')}</TableCell>
              <TableCell>{t('Local time')}</TableCell>
              <TableCell>{t('Time (UTC)')}</TableCell>
              <TableCell>{t('Class')}</TableCell>
              <TableCell align="right">{t('Confidence')}</TableCell>
              <TableCell align="right">{t('Latitude')}</TableCell>
              <TableCell align="right">{t('Longitude')}</TableCell>
              <TableCell>{t('Drift')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {start > 0 && (
              <TableRow aria-hidden>
                <TableCell colSpan={9} sx={{ p: 0, border: 0, height: start * ROW_PX }} />
              </TableRow>
            )}
            {rows.slice(start, end).map(({ m, i }) => {
              const clock = clockOf(m, p.runStartedMs);
              return (
                <TableRow
                  key={`${m.frame_index}:${m.u}:${m.v}:${i}`}
                  hover
                  selected={i === p.selectedIndex}
                  onClick={() => p.onSelect(i)}
                  sx={{ height: ROW_PX, cursor: 'pointer' }}
                >
                  {/* ★ FIRST: the object. Its id, its name when it has one, and the
                      pencil that gives it one — Enter saves, Escape cancels. */}
                  <TableCell
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, whiteSpace: 'nowrap' }}
                    onClick={(e) => {
                      if (editing !== null) e.stopPropagation();
                    }}
                  >
                    {m.track_id === null ? (
                      '—'
                    ) : editing !== null && editing.row === i ? (
                      <InputBase
                        autoFocus
                        value={editing.value}
                        placeholder={`#${m.track_id}`}
                        inputProps={{ 'aria-label': t('Track name'), 'maxLength': 64 }}
                        onChange={(e) =>
                          setEditing({ id: m.track_id as number, row: i, value: e.target.value })
                        }
                        onKeyDown={onNameKey}
                        onBlur={commitName}
                        onClick={(e) => e.stopPropagation()}
                        sx={{ fontSize: 12, fontFamily: 'inherit', width: 160 }}
                      />
                    ) : (
                      <>
                        {trackLabel(m.track_id, names)}
                        {p.onRenameTrack && (
                          <IconButton
                            size="small"
                            aria-label={t('Rename track')}
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditing({
                                id: m.track_id as number,
                                row: i,
                                value: names[String(m.track_id)] ?? '',
                              });
                            }}
                            sx={{ ml: 0.25, p: 0.25, opacity: 0.6 }}
                          >
                            <EditOutlinedIcon sx={{ fontSize: 13 }} />
                          </IconButton>
                        )}
                      </>
                    )}
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, direction: 'ltr' }}
                  >
                    {clock.date}
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, direction: 'ltr' }}
                  >
                    {clock.local}
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, direction: 'ltr' }}
                  >
                    {clock.utc}
                  </TableCell>
                  <TableCell>{m.cls_name}</TableCell>
                  <TableCell align="right" sx={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    {(100 * m.score).toFixed(0)}%
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, direction: 'ltr' }}
                  >
                    {m.lat === null ? '—' : m.lat.toFixed(6)}
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ fontFamily: 'var(--font-mono)', fontSize: 12, direction: 'ltr' }}
                  >
                    {m.lon === null ? '—' : m.lon.toFixed(6)}
                  </TableCell>
                  {/* ★ The verdict the mark was placed under — moved / changed mean
                    the coordinate is in doubt; unwatched means nobody checked. */}
                  <TableCell
                    sx={{
                      fontSize: 12,
                      color:
                        m.drift_status === 'moved' || m.drift_status === 'changed'
                          ? 'var(--status-warn)'
                          : 'text.secondary',
                    }}
                  >
                    {t(m.drift_status ?? 'unwatched')}
                    {/* ★ The measured shift on the ground at THIS mark (2026-09-09). */}
                    {m.drift_shift_m != null && (
                      <Typography component="span" variant="caption" className="le-mono" sx={{ ml: 0.5 }}>
                        ±{m.drift_shift_m.toFixed(1)} m
                      </Typography>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {end < rows.length && (
              <TableRow aria-hidden>
                <TableCell
                  colSpan={9}
                  sx={{ p: 0, border: 0, height: (rows.length - end) * ROW_PX }}
                />
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
