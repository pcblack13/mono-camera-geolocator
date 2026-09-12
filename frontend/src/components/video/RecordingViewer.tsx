/**
 * `video/RecordingViewer.tsx` — a recording watched beside its attribute table.
 *
 * ★ ONE CLOCK, TWO VIEWS (2026-09-07, owner ask). The player and the table share
 *   the recording's own time — seconds since it started. Playing or seeking moves
 *   the table's cursor to the rows at that moment (and scrolls them into view
 *   while "follow" is on); picking a row seeks the player to its moment. Nothing
 *   is stored: the current second is browser-only transient state, kept in step
 *   with the `<video>` element.
 *
 * ★ THE PLAYABLE FILE IS DERIVED. The recorder's own mp4 is MPEG-4 Part 2, which
 *   no browser decodes; the player asks for `preview.mp4`, which the server makes
 *   once with ffmpeg (seconds for a short clip) and serves with Range support.
 *
 * ★ TRIM IS A CUT INTO A NEW RECORDING, never an edit of this one. The selection
 *   — two thumbs under the timeline, or "Set start / end here" — goes to the
 *   server, which writes a new folder holding the window's video and rows, and
 *   the page moves there. The original stays exactly as it was.
 *
 * ★ THE TABLE IS VIRTUAL. A detection run at 10 fps writes thousands of rows;
 *   only the rows in view (plus a margin) are in the DOM.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type UIEvent,
} from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ContentCutIcon from '@mui/icons-material/ContentCut';
import PauseIcon from '@mui/icons-material/Pause';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import Replay10Icon from '@mui/icons-material/Replay10';
import Forward10Icon from '@mui/icons-material/Forward10';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious';
import VerticalAlignCenterIcon from '@mui/icons-material/VerticalAlignCenter';

import {
  liveApi,
  type RecordingLibraryEntry,
  type RecordingTable,
  type RecordingTableRow,
} from '../../api/live';
import { fmtClock } from '../../lib/clock';
import { LtrIsland } from '../common/LtrIsland';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';

// ─────────────────────────────────────────────────────────────────────────────
// The clock
// ─────────────────────────────────────────────────────────────────────────────

/** The recorder writes ten frames a second — one frame is the finest step. */
const FRAME_S = 0.1;
/** A row "is at" the current moment when it lies within this of it. */
const MOMENT_S = 0.5;
/** The smallest cut the server accepts. */
const MIN_TRIM_S = 0.5;

/** Rows in order of `t`; the ones without a time are kept out of the clock's way. */
function timedRows(rows: readonly RecordingTableRow[]): RecordingTableRow[] {
  return rows.filter((r): r is RecordingTableRow & { t: number } => r.t !== null);
}

/** The first index whose `t` is ≥ `time` (binary search over rows sorted by `t`). */
function lowerBound(rows: readonly RecordingTableRow[], time: number): number {
  let lo = 0;
  let hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((rows[mid].t ?? Infinity) < time) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

// ─────────────────────────────────────────────────────────────────────────────
// The table
// ─────────────────────────────────────────────────────────────────────────────

const ROW_H = 32;
const OVERSCAN = 8;

interface Column {
  key: string;
  label: string;
  width: string;
  cell: (row: RecordingTableRow) => string;
  mono?: boolean;
}

const num = (v: number | null, digits: number): string => (v === null ? '—' : v.toFixed(digits));

function columnsFor(table: RecordingTable['table']): Column[] {
  const time: Column = {
    key: 't',
    label: 'Time',
    width: '72px',
    cell: (r) => fmtClock(r.t ?? 0),
    mono: true,
  };
  const cls: Column = {
    key: 'class',
    label: 'Class',
    width: 'minmax(80px, 1fr)',
    cell: (r) => r.class_name || '—',
  };
  const score: Column = {
    key: 'score',
    label: 'Score',
    width: '56px',
    cell: (r) => (r.score === null ? '—' : `${Math.round(r.score * 100)}%`),
    mono: true,
  };
  const track: Column = {
    key: 'track',
    label: 'Track',
    width: '56px',
    cell: (r) => (r.track_id === null ? '—' : String(r.track_id)),
    mono: true,
  };
  if (table === 'detections') {
    const frame: Column = {
      key: 'frame',
      label: 'Frame',
      width: '64px',
      cell: (r) => (r.frame === null ? '—' : String(r.frame)),
      mono: true,
    };
    return [time, cls, score, frame, track];
  }
  const lat: Column = {
    key: 'lat',
    label: 'Lat',
    width: '84px',
    cell: (r) => num(r.lat, 5),
    mono: true,
  };
  const lon: Column = {
    key: 'lon',
    label: 'Lon',
    width: '84px',
    cell: (r) => num(r.lon, 5),
    mono: true,
  };
  const drift: Column = {
    key: 'drift',
    label: 'Drift',
    width: '72px',
    cell: (r) => r.drift ?? '—',
  };
  return [time, cls, score, lat, lon, track, drift];
}

interface AttributeTableProps {
  table: RecordingTable;
  rows: readonly RecordingTableRow[];
  current: number;
  /** The row the clock stands on — the last row at or before `current`. */
  cursor: number;
  /** `[lo, hi)` — the rows within MOMENT_S of `current`. */
  moment: readonly [number, number];
  follow: boolean;
  onFollow: (on: boolean) => void;
  onPick: (row: RecordingTableRow) => void;
}

function AttributeTable({
  table,
  rows,
  current,
  cursor,
  moment,
  follow,
  onFollow,
  onPick,
}: AttributeTableProps): JSX.Element {
  const columns = useMemo(() => columnsFor(table.table), [table.table]);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(420);
  const programmatic = useRef(false);

  useEffect(() => {
    const el = listRef.current;
    if (el === null) return;
    setViewportH(el.clientHeight || 420);
  }, []);

  // ★ Follow: keep the cursor row in the middle band while the clock moves. A
  //   wheel or a touch on the list is the reader taking over — follow turns off.
  useEffect(() => {
    const el = listRef.current;
    if (!follow || el === null || cursor < 0) return;
    const top = cursor * ROW_H;
    const lo = el.scrollTop + ROW_H;
    const hi = el.scrollTop + viewportH - 2 * ROW_H;
    if (top < lo || top > hi) {
      programmatic.current = true;
      el.scrollTop = Math.max(0, top - viewportH / 2);
    }
  }, [cursor, follow, viewportH]);

  const onScroll = (e: UIEvent<HTMLDivElement>): void => {
    setScrollTop(e.currentTarget.scrollTop);
    programmatic.current = false;
  };
  const takeOver = (): void => {
    if (follow) onFollow(false);
  };

  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const last = Math.min(rows.length, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN);
  const template = columns.map((c) => c.width).join(' ');
  const atMoment = moment[1] - moment[0];

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        overflow: 'hidden',
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ px: 1.5, py: 1, borderBottom: '1px solid var(--hairline)' }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            {t('Attribute table')}
          </Typography>
          <Typography variant="caption" color="text.secondary" component="div">
            <bdi>
              {rows.length} {t('rows')}
            </bdi>
            {' · '}
            <bdi>
              {atMoment} {t('at this moment')}
            </bdi>
            {' · '}
            <Box component="span" className="le-mono">
              {fmtClock(current)}
            </Box>
          </Typography>
        </Box>
        <Tooltip title={t('Follow playback')}>
          <IconButton
            size="small"
            aria-label={t('Follow playback')}
            aria-pressed={follow}
            onClick={() => onFollow(!follow)}
            sx={{
              color: follow ? 'var(--accent)' : 'text.secondary',
              bgcolor: follow ? 'var(--accent-quiet)' : 'transparent',
            }}
          >
            <VerticalAlignCenterIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ p: 3, textAlign: 'center' }}>
          {t('No rows — no detection ran while this was recorded.')}
        </Typography>
      ) : (
        <Box role="grid" aria-rowcount={rows.length + 1} aria-label={t('Attribute table')}>
          <Box
            role="row"
            sx={{
              display: 'grid',
              gridTemplateColumns: template,
              gap: 1,
              px: 1.5,
              py: 0.5,
              borderBottom: '1px solid var(--hairline)',
              bgcolor: 'var(--bg-inset)',
            }}
          >
            {columns.map((c) => (
              <Typography
                key={c.key}
                role="columnheader"
                className="le-mono"
                sx={{ fontSize: 10, letterSpacing: '0.06em', color: 'text.secondary' }}
              >
                {t(c.label)}
              </Typography>
            ))}
          </Box>
          <Box
            ref={listRef}
            role="rowgroup"
            aria-label={t('Rows')}
            onScroll={onScroll}
            onWheel={takeOver}
            onTouchMove={takeOver}
            sx={{ height: { xs: 320, md: 460 }, overflowY: 'auto', position: 'relative' }}
          >
            <Box sx={{ height: first * ROW_H }} />
            {rows.slice(first, last).map((row, i) => {
              const index = first + i;
              const isCursor = index === cursor;
              const inMoment = index >= moment[0] && index < moment[1];
              return (
                <Box
                  key={`${row.index}:${row.t ?? 'x'}`}
                  role="row"
                  tabIndex={0}
                  aria-selected={isCursor}
                  data-moment={inMoment ? 'true' : undefined}
                  onClick={() => onPick(row)}
                  onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onPick(row);
                    }
                  }}
                  sx={{
                    'display': 'grid',
                    'gridTemplateColumns': template,
                    'gap': 1,
                    'alignItems': 'center',
                    'height': ROW_H,
                    'px': 1.5,
                    'cursor': 'pointer',
                    'borderLeft': '3px solid',
                    'borderLeftColor': isCursor ? 'var(--accent)' : 'transparent',
                    'bgcolor': inMoment ? 'var(--accent-quiet)' : 'transparent',
                    'transition': 'background-color var(--dur-fast) var(--ease-standard)',
                    '&:hover': { bgcolor: 'action.hover' },
                    '&:focus-visible': { outline: 'none', boxShadow: 'inset var(--focus-ring)' },
                  }}
                >
                  {columns.map((c) => (
                    <Typography
                      key={c.key}
                      role="cell"
                      noWrap
                      className={c.mono ? 'le-mono' : undefined}
                      sx={{ fontSize: 12.5, color: inMoment ? 'text.primary' : 'text.secondary' }}
                    >
                      {c.cell(row)}
                    </Typography>
                  ))}
                </Box>
              );
            })}
            <Box sx={{ height: Math.max(0, rows.length - last) * ROW_H }} />
          </Box>
        </Box>
      )}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The viewer
// ─────────────────────────────────────────────────────────────────────────────

export interface RecordingViewerProps {
  table: RecordingTable;
  /** The trim wrote a new recording — the page moves there. */
  onTrimmed: (entry: RecordingLibraryEntry) => void;
}

export function RecordingViewer({ table, onTrimmed }: RecordingViewerProps): JSX.Element {
  const notify = useNotify();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const rows = useMemo(() => timedRows(table.rows), [table.rows]);

  const [current, setCurrent] = useState(0);
  const [paused, setPaused] = useState(true);
  const [duration, setDuration] = useState(table.duration_s);
  const [playError, setPlayError] = useState(false);
  const [follow, setFollow] = useState(true);
  // The selection: `[start, end]`, `end === null` meaning "to the end".
  const [sel, setSel] = useState<[number, number | null]>([0, null]);
  const [trimming, setTrimming] = useState(false);
  const selEnd = sel[1] ?? duration;

  const clamp = useCallback(
    (time: number): number => Math.min(Math.max(0, time), duration > 0 ? duration : time),
    [duration],
  );
  const seek = useCallback(
    (time: number): void => {
      const to = clamp(time);
      const v = videoRef.current;
      if (v !== null) v.currentTime = to;
      setCurrent(to);
    },
    [clamp],
  );
  const togglePlay = (): void => {
    const v = videoRef.current;
    if (v === null) return;
    if (v.paused) {
      const p = v.play();
      if (p !== undefined) p.catch(() => setPlayError(true));
    } else {
      v.pause();
    }
  };

  // ★ While playing, read the element's clock a dozen times a second — smoother
  //   than `timeupdate`'s ~4 Hz, cheap enough for the virtual table.
  useEffect(() => {
    if (paused) return undefined;
    let id = 0;
    let last = 0;
    const tick = (now: number): void => {
      if (now - last >= 80) {
        last = now;
        const v = videoRef.current;
        if (v !== null) setCurrent(v.currentTime);
      }
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [paused]);

  // The rows at this moment (two binary searches), and the cursor: the row of
  // that band nearest the clock — or, with none at hand, the last row before it.
  const moment = useMemo(
    (): [number, number] => [
      lowerBound(rows, current - MOMENT_S),
      lowerBound(rows, current + MOMENT_S + 1e-6),
    ],
    [rows, current],
  );
  const cursor = useMemo(() => {
    if (moment[1] > moment[0]) {
      let best = moment[0];
      for (let i = moment[0]; i < moment[1]; i += 1) {
        if (Math.abs((rows[i].t ?? 0) - current) < Math.abs((rows[best].t ?? 0) - current)) {
          best = i;
        }
      }
      return best;
    }
    return lowerBound(rows, current + FRAME_S / 2) - 1;
  }, [rows, moment, current]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    const target = e.target as HTMLElement;
    if (
      target.tagName === 'INPUT' ||
      target.tagName === 'BUTTON' ||
      target.getAttribute('role') === 'slider'
    )
      return;
    const step = e.shiftKey ? FRAME_S : 1;
    switch (e.key) {
      case ' ':
        e.preventDefault();
        togglePlay();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        seek(current - step);
        break;
      case 'ArrowRight':
        e.preventDefault();
        seek(current + step);
        break;
      case 'Home':
        e.preventDefault();
        seek(0);
        break;
      case 'End':
        e.preventDefault();
        seek(duration);
        break;
      default:
        break;
    }
  };

  const trim = (): void => {
    setTrimming(true);
    liveApi
      .trimRecording(table.folder, sel[0], selEnd)
      .then((entry) => {
        notify(`${t('Trimmed clip saved:')} ${entry.folder}`, { severity: 'success' });
        onTrimmed(entry);
      })
      .catch((e: unknown) =>
        notify(e instanceof Error ? e.message : String(e), { severity: 'error' }),
      )
      .finally(() => setTrimming(false));
  };
  const canTrim = table.has_video && !trimming && selEnd - sel[0] >= MIN_TRIM_S;
  const selPct = duration > 0 ? [(sel[0] / duration) * 100, (selEnd / duration) * 100] : [0, 100];

  return (
    <Box
      onKeyDown={onKey}
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 3fr) minmax(360px, 2fr)' },
        gap: 2,
        alignItems: 'start',
      }}
    >
      {/* ── the player ─────────────────────────────────────────────────────── */}
      <Stack spacing={1.5} sx={{ minWidth: 0 }}>
        {table.has_video ? (
          <Box
            sx={{
              position: 'relative',
              borderRadius: 'var(--radius-lg)',
              overflow: 'hidden',
              bgcolor: 'var(--bg-canvas)',
              border: '1px solid var(--hairline)',
            }}
          >
            <Box
              component="video"
              ref={videoRef}
              src={liveApi.recordingPlayUrl(table.folder)}
              preload="metadata"
              playsInline
              aria-label={t('Recording')}
              onClick={togglePlay}
              onLoadedMetadata={(e) => {
                const d = e.currentTarget.duration;
                if (Number.isFinite(d) && d > 0) setDuration(d);
              }}
              onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
              onPlay={() => setPaused(false)}
              onPause={() => setPaused(true)}
              onEnded={() => setPaused(true)}
              onError={() => setPlayError(true)}
              sx={{
                display: 'block',
                width: '100%',
                aspectRatio: '16 / 9',
                maxHeight: '62vh',
                objectFit: 'contain',
                cursor: 'pointer',
              }}
            />
            {playError && (
              <Alert
                severity="warning"
                sx={{ position: 'absolute', left: 12, right: 12, bottom: 12 }}
              >
                {t('The video could not be played. The original file can still be downloaded.')}
              </Alert>
            )}
          </Box>
        ) : (
          <Box
            sx={{
              display: 'grid',
              placeItems: 'center',
              aspectRatio: '16 / 9',
              borderRadius: 'var(--radius-lg)',
              border: '1px dashed var(--hairline-strong)',
              color: 'text.secondary',
              p: 3,
            }}
          >
            <Typography variant="body2">
              {t('This recording has no video — its table still reads.')}
            </Typography>
          </Box>
        )}

        {/* ★ The timeline, the selection band beneath it, and the transport. The
            slider maths is left-to-right — island it. */}
        <LtrIsland>
          <Box sx={{ px: 0.5 }}>
            <Box sx={{ position: 'relative' }}>
              <Box
                aria-hidden
                sx={{
                  position: 'absolute',
                  top: '50%',
                  height: 10,
                  transform: 'translateY(-50%)',
                  left: `${selPct[0]}%`,
                  width: `${Math.max(0, selPct[1] - selPct[0])}%`,
                  bgcolor: 'var(--accent-quiet)',
                  borderRadius: 'var(--radius-pill)',
                  pointerEvents: 'none',
                }}
              />
              <Slider
                size="small"
                aria-label={t('Timeline')}
                value={Math.min(current, duration || current)}
                min={0}
                max={duration > 0 ? duration : 1}
                step={FRAME_S}
                onChange={(_e, v) => seek(v as number)}
                valueLabelDisplay="auto"
                valueLabelFormat={(v) => fmtClock(v as number)}
              />
            </Box>
            <Stack direction="row" alignItems="center" spacing={0.5} useFlexGap flexWrap="wrap">
              <Tooltip title={paused ? t('Play') : t('Pause')}>
                <span>
                  <IconButton
                    aria-label={paused ? t('Play') : t('Pause')}
                    onClick={togglePlay}
                    disabled={!table.has_video}
                    sx={{
                      'bgcolor': 'var(--accent)',
                      'color': 'var(--accent-contrast)',
                      '&:hover': { bgcolor: 'var(--accent-hover)' },
                    }}
                  >
                    {paused ? <PlayArrowIcon /> : <PauseIcon />}
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title={t('Back 1 s')}>
                <IconButton
                  size="small"
                  aria-label={t('Back 1 s')}
                  onClick={() => seek(current - 1)}
                >
                  <Replay10Icon />
                </IconButton>
              </Tooltip>
              <Tooltip title={t('Back one frame')}>
                <IconButton
                  size="small"
                  aria-label={t('Back one frame')}
                  onClick={() => seek(current - FRAME_S)}
                >
                  <SkipPreviousIcon />
                </IconButton>
              </Tooltip>
              <Typography
                className="le-mono"
                sx={{ fontSize: 13, px: 1, minWidth: 110, textAlign: 'center' }}
              >
                {fmtClock(current)} / {fmtClock(duration)}
              </Typography>
              <Tooltip title={t('Forward one frame')}>
                <IconButton
                  size="small"
                  aria-label={t('Forward one frame')}
                  onClick={() => seek(current + FRAME_S)}
                >
                  <SkipNextIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title={t('Forward 1 s')}>
                <IconButton
                  size="small"
                  aria-label={t('Forward 1 s')}
                  onClick={() => seek(current + 1)}
                >
                  <Forward10Icon />
                </IconButton>
              </Tooltip>
              <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                {t('Space plays · ← → one second · Shift ← → one frame')}
              </Typography>
            </Stack>

            {/* ── the trim ───────────────────────────────────────────────────── */}
            <Box
              sx={{
                mt: 1.5,
                p: 1.5,
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--hairline)',
                bgcolor: 'var(--bg-elevated)',
              }}
            >
              <Stack direction="row" alignItems="center" spacing={1.5}>
                <Typography
                  className="le-mono"
                  sx={{ fontSize: 10, letterSpacing: '0.1em', color: 'text.secondary' }}
                >
                  {t('TRIM')}
                </Typography>
                <Slider
                  size="small"
                  value={[sel[0], selEnd]}
                  min={0}
                  max={duration > 0 ? duration : 1}
                  step={FRAME_S}
                  disableSwap
                  onChange={(_e, v) => {
                    const [a, b] = v as number[];
                    setSel([a, b]);
                  }}
                  getAriaLabel={(i) => (i === 0 ? t('Selection start') : t('Selection end'))}
                  valueLabelDisplay="auto"
                  valueLabelFormat={(v) => fmtClock(v as number)}
                  sx={{ flex: 1 }}
                />
              </Stack>
              <Stack
                direction="row"
                alignItems="center"
                spacing={1}
                useFlexGap
                flexWrap="wrap"
                sx={{ mt: 1 }}
              >
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() =>
                    setSel(([, b]) => [current, b !== null && b > current + MIN_TRIM_S ? b : null])
                  }
                >
                  {t('Set start here')}
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() =>
                    setSel(([a]) => [Math.min(a, Math.max(0, current - MIN_TRIM_S)), current])
                  }
                >
                  {t('Set end here')}
                </Button>
                <Typography className="le-mono" sx={{ fontSize: 12, color: 'text.secondary' }}>
                  {fmtClock(sel[0])} – {fmtClock(selEnd)} · {(selEnd - sel[0]).toFixed(1)} s
                </Typography>
                <Box sx={{ flex: 1 }} />
                <Button size="small" onClick={() => setSel([0, null])}>
                  {t('Reset')}
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  startIcon={<ContentCutIcon />}
                  disabled={!canTrim}
                  onClick={trim}
                >
                  {trimming ? t('Trimming…') : t('Trim to selection')}
                </Button>
              </Stack>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mt: 0.75 }}
              >
                {t(
                  'The cut is saved as a new recording with the rows of that window — this one stays as it is.',
                )}
              </Typography>
            </Box>
          </Box>
        </LtrIsland>
      </Stack>

      {/* ── the table ──────────────────────────────────────────────────────── */}
      <AttributeTable
        table={table}
        rows={rows}
        current={current}
        cursor={cursor}
        moment={moment}
        follow={follow}
        onFollow={setFollow}
        onPick={(row) => {
          if (row.t !== null) seek(row.t);
        }}
      />
    </Box>
  );
}

export default RecordingViewer;
