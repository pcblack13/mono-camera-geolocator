/**
 * `pages/StatusPage.tsx` — the extended app status: every component explained, and a
 * live log monitor.
 *
 * ★ WHY IT EXISTS. The desktop app has no terminal. When something fails in the
 *   field, the ConnectionChip's popover says WHICH component is unhappy; this page
 *   says WHY — the same `/health/ready` detail with each component's job spelled
 *   out, plus the server's own log lines from `GET /health/logs`, scrubbed
 *   server-side (§9.10) and tailed live. The developer's question — "what happened
 *   right before it broke?" — is answered here, not in an ssh session.
 *
 * ★ THE TAIL IS LOCAL. The page polls only for NEW lines (`?after=last_seq`) and
 *   filters level/search on what it already holds — flipping a filter is instant
 *   and costs no request. The buffer is bounded server-side, the tail bounded
 *   client-side; neither can grow without limit.
 *
 * ★ LOG LINES ARE LTR ISLANDS. Timestamps, logger names and tracebacks are Latin
 *   technical text; in Arabic the page chrome mirrors but the log pane pins
 *   `dir="ltr"` so a traceback reads as a traceback.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Collapse from '@mui/material/Collapse';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteSweepOutlinedIcon from '@mui/icons-material/DeleteSweepOutlined';
import PauseIcon from '@mui/icons-material/Pause';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import VerticalAlignBottomIcon from '@mui/icons-material/VerticalAlignBottom';

import { capabilitiesApi } from '../api/capabilities';
import { t } from '../i18n';
import type { ComponentHealth, ComponentStatus, LogRecordEntry } from '../types/capabilities';

// ─────────────────────────────────────────────────────────────────────────────
// The components, explained
// ─────────────────────────────────────────────────────────────────────────────

const DOT: Record<ComponentStatus, string> = {
  up: 'var(--status-ok)',
  degraded: 'var(--status-warn)',
  down: 'var(--status-error)',
  skipped: 'var(--acc-none)',
};

type ComponentRole = 'required' | 'optional' | 'informational';

/**
 * ★ Each component's JOB, in the operator's language — mirroring `health.py`'s
 *   checks. `required` = gates readiness (503 when down); `optional` = the app
 *   degrades but keeps serving; `informational` = never affects readiness.
 */
const COMPONENT_META: Record<string, { desc: string; role: ComponentRole }> = {
  postgres: {
    desc: 'The main database — projects, images, GCPs, detections and jobs all live here.',
    role: 'required',
  },
  redis: {
    desc: 'In-memory store for caching, rate limiting and job coordination.',
    role: 'required',
  },
  storage: {
    desc: 'File storage for uploaded photos, exports and cached map tiles.',
    role: 'required',
  },
  celery: {
    desc: 'Background workers that run long jobs — ingest, exports, processing.',
    role: 'optional',
  },
  imagery: {
    desc: 'The satellite imagery provider the maps fetch their tiles from.',
    role: 'optional',
  },
  models: {
    desc: 'The AI model pipeline. Reported for information only.',
    role: 'informational',
  },
  raster: {
    desc: 'The raster / DEM backend that reads elevation data for geolocation.',
    role: 'optional',
  },
};

const ROLE_LABEL: Record<ComponentRole, string> = {
  required: 'Required',
  optional: 'Optional',
  informational: 'Informational',
};

const STATUS_LABEL: Record<ComponentStatus, string> = {
  up: 'Up',
  degraded: 'Degraded',
  down: 'Down',
  skipped: 'Skipped',
};

function ComponentCard({ component }: { component: ComponentHealth }): JSX.Element {
  const meta = COMPONENT_META[component.name];
  return (
    <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: DOT[component.status],
            flexShrink: 0,
          }}
        />
        <Typography className="le-mono" sx={{ fontSize: 13, fontWeight: 700, flex: 1 }}>
          {component.name}
        </Typography>
        {component.latency_ms !== null && (
          // ★ dir="ltr": "2 ms" must not become "ms 2" when the page is Arabic.
          <Typography className="le-mono" dir="ltr" sx={{ fontSize: 11, color: 'text.disabled' }}>
            {Math.round(component.latency_ms)} ms
          </Typography>
        )}
        <Chip
          size="small"
          label={t(STATUS_LABEL[component.status])}
          sx={{ height: 18, fontSize: 10.5 }}
        />
      </Stack>
      {meta !== undefined && (
        <>
          <Typography variant="caption" color="text.secondary">
            {t(meta.desc)}
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.disabled' }}>
            {t(ROLE_LABEL[meta.role])}
          </Typography>
        </>
      )}
      {component.message !== null && (
        <Typography
          className="le-mono"
          sx={{ fontSize: 10.5, color: 'text.secondary', wordBreak: 'break-word' }}
          dir="ltr"
        >
          {component.message}
        </Typography>
      )}
    </Paper>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The log tail
// ─────────────────────────────────────────────────────────────────────────────

/** The client keeps at most this many lines — a bound, like the server's buffer. */
const MAX_CLIENT_LINES = 3000;
const POLL_MS = 2000;

interface LogTail {
  entries: LogRecordEntry[];
  error: string | null;
  clear: () => void;
}

/**
 * Polls `GET /health/logs` for lines newer than the last seen `seq`.
 *
 * ★ A ref, not state, holds the cursor: the interval callback must read the value
 *   the LAST tick wrote, not the value the closure captured. `clear` empties the
 *   view but keeps the cursor — cleared lines stay cleared.
 */
function useLogTail(live: boolean): LogTail {
  const [entries, setEntries] = useState<LogRecordEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const afterRef = useRef(0);

  useEffect(() => {
    if (!live) return undefined;
    let cancelled = false;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const res = await capabilitiesApi.logs(afterRef.current, 1000, controller.signal);
        if (cancelled) return;
        // ★ The cursor advances even when every new line is later filtered out
        //   client-side — `last_seq` is filter-independent by contract.
        afterRef.current = Math.max(afterRef.current, res.last_seq);
        if (res.entries.length > 0) {
          setEntries((prev) => [...prev, ...res.entries].slice(-MAX_CLIENT_LINES));
        }
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };

    void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(id);
    };
  }, [live]);

  const clear = useCallback(() => setEntries([]), []);
  return { entries, error, clear };
}

// ─────────────────────────────────────────────────────────────────────────────
// Log rendering
// ─────────────────────────────────────────────────────────────────────────────

const LEVEL_RANK: Record<string, number> = { debug: 10, info: 20, warning: 30, error: 40, critical: 50 };

const LEVEL_COLOR: Record<string, string> = {
  debug: 'var(--acc-none, #888)',
  info: 'var(--status-ok)',
  warning: 'var(--status-warn)',
  error: 'var(--status-error)',
  critical: 'var(--status-error)',
};

function timeOf(timestamp: string): string {
  const d = new Date(timestamp);
  return Number.isNaN(d.getTime()) ? timestamp : d.toLocaleTimeString(undefined, { hour12: false });
}

function LogRow({ entry }: { entry: LogRecordEntry }): JSX.Element {
  const [open, setOpen] = useState(false);
  const extra = Object.keys(entry.fields).length > 0;
  const hasDetail = extra || entry.exception !== null || entry.request_id !== null;
  return (
    <Box
      component="li"
      data-testid="log-row"
      sx={{
        listStyle: 'none',
        px: 1,
        py: 0.25,
        borderBottom: '1px solid var(--hairline, rgba(128,128,128,0.12))',
        cursor: hasDetail ? 'pointer' : 'default',
        '&:hover': { bgcolor: 'action.hover' },
      }}
      onClick={hasDetail ? () => setOpen((v) => !v) : undefined}
    >
      {/* ★ gap, not Stack spacing: the theme is RTL in Arabic and would emit
          margin-right inside this LTR pane, collapsing the columns. Flex gap
          is direction-agnostic. */}
      <Stack direction="row" alignItems="baseline" sx={{ minWidth: 0, gap: 1 }}>
        <Typography className="le-mono" sx={{ fontSize: 10.5, color: 'text.disabled', flexShrink: 0 }}>
          {timeOf(entry.timestamp)}
        </Typography>
        <Typography
          className="le-mono"
          sx={{
            fontSize: 10.5,
            fontWeight: 700,
            color: LEVEL_COLOR[entry.level] ?? 'text.secondary',
            width: 64,
            flexShrink: 0,
            textTransform: 'uppercase',
          }}
        >
          {entry.level}
        </Typography>
        <Typography
          className="le-mono"
          sx={{ fontSize: 10.5, color: 'text.disabled', flexShrink: 0, maxWidth: 220 }}
          noWrap
        >
          {entry.logger}
        </Typography>
        <Typography className="le-mono" sx={{ fontSize: 11.5, wordBreak: 'break-word', flex: 1 }}>
          {entry.event}
        </Typography>
      </Stack>
      {hasDetail && (
        // ★ unmountOnExit: with thousands of rows the folded details must not
        //   weigh on the DOM — and a folded traceback is genuinely absent.
        <Collapse in={open} unmountOnExit>
          <Box sx={{ pl: 2, py: 0.5 }}>
            {entry.request_id !== null && (
              <Typography className="le-mono" sx={{ fontSize: 10.5, color: 'text.secondary' }}>
                request_id: {entry.request_id}
              </Typography>
            )}
            {extra && (
              <Typography
                className="le-mono"
                component="pre"
                sx={{ fontSize: 10.5, color: 'text.secondary', m: 0, whiteSpace: 'pre-wrap' }}
              >
                {JSON.stringify(entry.fields, null, 2)}
              </Typography>
            )}
            {entry.exception !== null && (
              <Typography
                className="le-mono"
                component="pre"
                sx={{
                  fontSize: 10.5,
                  color: 'var(--status-error)',
                  m: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {entry.exception}
              </Typography>
            )}
          </Box>
        </Collapse>
      )}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

function formatUptime(uptimeS: number): string {
  const s = Math.max(0, Math.floor(uptimeS));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

type LevelFilter = 'all' | 'info' | 'warning' | 'error';

export function StatusPage(): JSX.Element {
  const [live, setLive] = useState(true);
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('all');
  const [search, setSearch] = useState('');
  const { entries, error: logError, clear } = useLogTail(live);
  const listRef = useRef<HTMLUListElement | null>(null);
  const followRef = useRef(true);

  const readiness = useQuery({
    queryKey: ['health', 'readiness', 'verbose'],
    queryFn: ({ signal }) => capabilitiesApi.readiness(undefined, true, signal),
    refetchInterval: 10_000,
    retry: 1,
  });
  const liveness = useQuery({
    queryKey: ['health', 'liveness'],
    queryFn: ({ signal }) => capabilitiesApi.health(signal),
    refetchInterval: 30_000,
    retry: 1,
  });

  const visible = useMemo(() => {
    const minRank = levelFilter === 'all' ? 0 : LEVEL_RANK[levelFilter];
    const needle = search.trim().toLowerCase();
    return entries.filter((e) => {
      if ((LEVEL_RANK[e.level] ?? 20) < minRank) return false;
      if (needle === '') return true;
      const haystack =
        `${e.event} ${e.logger ?? ''} ${e.request_id ?? ''} ${e.exception ?? ''} ` +
        JSON.stringify(e.fields);
      return haystack.toLowerCase().includes(needle);
    });
  }, [entries, levelFilter, search]);

  const errorCount = useMemo(
    () => entries.filter((e) => (LEVEL_RANK[e.level] ?? 0) >= LEVEL_RANK.error).length,
    [entries],
  );
  const warningCount = useMemo(
    () => entries.filter((e) => e.level === 'warning').length,
    [entries],
  );

  // ★ Follow the tail — unless the reader scrolled up to study something, in
  //   which case new lines must not yank the traceback out from under them.
  useEffect(() => {
    const el = listRef.current;
    if (el !== null && followRef.current) el.scrollTop = el.scrollHeight;
  }, [visible]);

  const onScroll = useCallback(() => {
    const el = listRef.current;
    if (el === null) return;
    followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  const jumpToEnd = useCallback(() => {
    followRef.current = true;
    const el = listRef.current;
    if (el !== null) el.scrollTop = el.scrollHeight;
  }, []);

  const copyVisible = useCallback(() => {
    const text = visible
      .map(
        (e) =>
          `${e.timestamp} ${e.level.toUpperCase()} ${e.logger ?? ''} ${e.event}` +
          (e.exception !== null ? `\n${e.exception}` : ''),
      )
      .join('\n');
    void navigator.clipboard?.writeText(text);
  }, [visible]);

  const unreachable = readiness.isError;

  return (
    <Box sx={{ p: 2, maxWidth: 1280, mx: 'auto', width: '100%' }}>
      {/* ── header ─────────────────────────────────────────────────────────── */}
      <Stack
        direction="row"
        alignItems="baseline"
        spacing={2}
        flexWrap="wrap"
        useFlexGap
        sx={{ mb: 2 }}
      >
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          {t('App status')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 200 }}>
          {t('Every component the app depends on, and the server’s own log — live.')}
        </Typography>
        {liveness.data !== undefined && (
          // ★ Mixed-direction line: the Arabic label flows with the page; the
          //   version and the duration are pinned LTR so bidi cannot scramble them.
          <Typography className="le-mono" sx={{ fontSize: 11, color: 'text.disabled' }}>
            <span dir="ltr">v{liveness.data.version}</span> · {t('Uptime')}{' '}
            <span dir="ltr">{formatUptime(liveness.data.uptime_s)}</span>
          </Typography>
        )}
      </Stack>

      {/* ── components ─────────────────────────────────────────────────────── */}
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        {t('System components')}
      </Typography>
      {unreachable ? (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography className="le-mono" sx={{ fontSize: 12, color: 'error.main' }}>
            {t('The API did not answer — the app cannot reach its own server.')}
          </Typography>
        </Paper>
      ) : readiness.data === undefined ? (
        <Box sx={{ display: 'grid', placeItems: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 1.5,
            mb: 3,
          }}
        >
          {readiness.data.components.map((c) => (
            <ComponentCard key={c.name} component={c} />
          ))}
        </Box>
      )}

      {/* ── log monitor ────────────────────────────────────────────────────── */}
      <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        <Typography variant="subtitle2" sx={{ flex: 1, minWidth: 120 }}>
          {t('Log monitor')}
        </Typography>
        {errorCount > 0 && (
          <Chip
            size="small"
            label={`${errorCount} ${t('errors')}`}
            sx={{ height: 20, fontSize: 10.5, color: 'var(--status-error)' }}
          />
        )}
        {warningCount > 0 && (
          <Chip
            size="small"
            label={`${warningCount} ${t('warnings')}`}
            sx={{ height: 20, fontSize: 10.5, color: 'var(--status-warn)' }}
          />
        )}
        <TextField
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('Search logs')}
          inputProps={{ 'aria-label': t('Search logs') }}
          sx={{ width: 200 }}
        />
        <TextField
          size="small"
          select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value as LevelFilter)}
          inputProps={{ 'aria-label': t('Minimum level') }}
          sx={{ width: 170 }}
        >
          <MenuItem value="all">{t('All levels')}</MenuItem>
          <MenuItem value="info">{t('Info and above')}</MenuItem>
          <MenuItem value="warning">{t('Warnings and errors')}</MenuItem>
          <MenuItem value="error">{t('Errors only')}</MenuItem>
        </TextField>
        <Tooltip title={live ? t('Pause the live tail') : t('Resume the live tail')}>
          <Button
            size="small"
            variant="outlined"
            startIcon={live ? <PauseIcon /> : <PlayArrowIcon />}
            onClick={() => setLive((v) => !v)}
          >
            {live ? t('Pause') : t('Resume')}
          </Button>
        </Tooltip>
        <Tooltip title={t('Copy the visible lines')}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon />} onClick={copyVisible}>
            {t('Copy')}
          </Button>
        </Tooltip>
        <Tooltip title={t('Clear the view — new lines keep arriving')}>
          <Button size="small" variant="outlined" startIcon={<DeleteSweepOutlinedIcon />} onClick={clear}>
            {t('Clear')}
          </Button>
        </Tooltip>
        <Tooltip title={t('Jump to the newest line')}>
          <Button size="small" variant="outlined" startIcon={<VerticalAlignBottomIcon />} onClick={jumpToEnd}>
            {t('End')}
          </Button>
        </Tooltip>
      </Stack>

      {logError !== null && (
        <Typography className="le-mono" sx={{ fontSize: 11, color: 'error.main', mb: 0.5 }}>
          {t('Could not fetch logs:')} {logError}
        </Typography>
      )}

      {/* ★ dir="ltr": log lines are Latin technical text even when the app is Arabic. */}
      <Paper variant="outlined" dir="ltr" sx={{ overflow: 'hidden' }}>
        <Box
          component="ul"
          ref={listRef}
          onScroll={onScroll}
          aria-label={t('Log monitor')}
          sx={{ m: 0, p: 0, height: '52vh', minHeight: 260, overflowY: 'auto', overflowX: 'hidden' }}
        >
          {visible.length === 0 ? (
            <Box sx={{ display: 'grid', placeItems: 'center', height: '100%' }}>
              <Typography variant="body2" color="text.secondary">
                {entries.length === 0
                  ? t('Waiting for log entries…')
                  : t('No log entries match the current filters.')}
              </Typography>
            </Box>
          ) : (
            visible.map((e) => <LogRow key={e.seq} entry={e} />)
          )}
        </Box>
      </Paper>
      <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 0.5 }}>
        {t('The server keeps the most recent lines in memory; older lines are dropped. Secrets are scrubbed before they reach this page.')}
      </Typography>
    </Box>
  );
}
