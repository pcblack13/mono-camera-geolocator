/**
 * `map/OfflineCachePanel.tsx` — the OFFLINE AREA MANAGER: draw an area on the satellite
 * map, see what it would cost (tiles, upstream requests, storage), and download it for
 * offline field work. Companion out-of-map control to {@link OfflineCacheLayer}.
 *
 * ★ HOW IT WORKS NOW. The download runs SERVER-SIDE (`POST /imagery/offline/operations`):
 *   the backend enumerates the AOI's XYZ tiles, skips what its read-through cache already
 *   holds, enforces the configured request budgets, fetches with bounded concurrency and
 *   the provider's rate limit, and writes an offline manifest on completion. This panel
 *   drives the polygon + zoom band, shows the server's ESTIMATE before anything
 *   downloads, and polls progress — with pause / resume / cancel / retry. A page
 *   navigation no longer kills a download.
 *
 * ★ A MUI `Popper` (not `Popover`/`Dialog`) so there is NO modal backdrop — the map stays
 *   fully interactive for drawing while this panel is open.
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Popper from '@mui/material/Popper';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ClickAwayListener from '@mui/material/ClickAwayListener';
import DownloadForOfflineIcon from '@mui/icons-material/DownloadForOffline';
import UndoIcon from '@mui/icons-material/Undo';

import {
  formatBytes,
  offlineApi,
  type BasemapKindStr,
  type LonLat,
  type OfflineEstimate,
  type PrecacheOperation,
} from '../../api/offline';
import { useOfflineCacheStore } from '../../store';
import { t } from '../../i18n';

export interface OfflineCachePanelProps {
  /** Active provider name — the tiles are cached for THIS provider + kind. */
  providerId: string;
  /** Basemap kind (satellite / hybrid / terrain). */
  kind: string;
  /** Whether the active provider can be fetched at all (offline/local providers cannot warm). */
  cacheable: boolean;
  /** Outline colour for the trigger's active state. */
  color: string;
}

/**
 * ★ The DEFAULT band, not the only one — the manager now exposes min/max pickers.
 *
 * z13 keeps enough context to navigate to the area; z17 is the precision the picker
 * needs (at z15 one pixel is ~4 m — a surveyor could see the field but not click a gate
 * post). The pickers allow up to z19 for sub-metre work, with the tile count and the
 * server's budget check making the cost visible before anything downloads.
 */
const DEFAULT_ZOOM_BAND: readonly [number, number] = [13, 17];
// ★ Up to z22 — everything Mapbox serves (native detail ends ~z19; z20–22 are
//   upsampled). The server's estimate + budget check shows the true cost before
//   anything downloads, which is what makes offering the deep levels safe.
const ZOOM_CHOICES = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] as const;

const POLL_MS = 1_000;

const ACTIVE_STATES = new Set(['pending', 'running', 'paused']);

export function OfflineCachePanel({
  providerId,
  kind,
  cacheable,
  color,
}: OfflineCachePanelProps): JSX.Element {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  const [zoomMin, setZoomMin] = useState<number>(DEFAULT_ZOOM_BAND[0]);
  const [zoomMax, setZoomMax] = useState<number>(DEFAULT_ZOOM_BAND[1]);
  const [estimate, setEstimate] = useState<OfflineEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [op, setOp] = useState<PrecacheOperation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const drawing = useOfflineCacheStore((s) => s.drawing);
  const points = useOfflineCacheStore((s) => s.points);
  const startDrawing = useOfflineCacheStore((s) => s.startDrawing);
  const undoPoint = useOfflineCacheStore((s) => s.undoPoint);
  const finishDrawing = useOfflineCacheStore((s) => s.finishDrawing);
  const reset = useOfflineCacheStore((s) => s.reset);

  // ★ The draw store is global; leaving the page mid-draw must not carry `drawing: true`
  //   onto the next map. The DOWNLOAD deliberately survives unmount — it is server-side.
  useEffect(() => reset, [reset]);

  const polygon: LonLat[] = useMemo(() => points.map((p) => [p.lon, p.lat] as LonLat), [points]);
  const canDraw = points.length >= 3;

  const request = useMemo(
    () => ({
      provider: providerId,
      kind: kind as BasemapKindStr,
      polygon,
      zoom_min: zoomMin,
      zoom_max: zoomMax,
    }),
    [providerId, kind, polygon, zoomMin, zoomMax],
  );

  // ── the server's estimate: tiles, cached, new, storage, budget ──────────────
  useEffect(() => {
    setEstimate(null);
    setError(null);
    if (!open || !cacheable || !canDraw || op !== null) return;
    const controller = new AbortController();
    setEstimating(true);
    offlineApi
      .estimate(request, controller.signal)
      .then((e) => setEstimate(e))
      .catch((e: unknown) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : 'Estimate failed.');
      })
      .finally(() => {
        // An aborted estimate must not clear the spinner of the one that replaced it.
        if (!controller.signal.aborted) setEstimating(false);
      });
    return () => controller.abort();
  }, [open, cacheable, canDraw, request, op]);

  // ── progress polling while an operation is live ─────────────────────────────
  useEffect(() => {
    if (op === null || !ACTIVE_STATES.has(op.state)) return;
    const timer = setInterval(() => {
      offlineApi
        .getOperation(op.id)
        .then((next) => setOp(next))
        .catch(() => undefined); // a poll hiccup is not an error state
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [op]);

  // ── an already-running operation (page reloaded mid-download) ───────────────
  useEffect(() => {
    if (!open) return;
    offlineApi
      .listOperations()
      .then((ops) => {
        const live = ops.find((o) => o.provider === providerId && ACTIVE_STATES.has(o.state));
        if (live) setOp(live);
      })
      .catch(() => undefined);
  }, [open, providerId]);

  const closeAll = (): void => {
    reset();
    setEstimate(null);
    setError(null);
    setOp(null);
    setOpen(false);
  };

  const openPanel = (): void => {
    setOpen(true);
    setError(null);
    startDrawing();
  };

  const act = (fn: () => Promise<PrecacheOperation>): void => {
    setError(null);
    fn()
      .then((next) => setOp(next))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Request failed.'));
  };

  const runCache = (): void => {
    if (!estimate || !estimate.budget.within_budget) return;
    // ★ Starting the download IMPLICITLY finishes the outline — otherwise the map keeps
    //   swallowing clicks as new vertices while tiles download.
    finishDrawing();
    act(() => offlineApi.start(request));
  };

  const running = op !== null && op.state === 'running';
  const paused = op !== null && op.state === 'paused';
  const terminal = op !== null && !ACTIVE_STATES.has(op.state);

  return (
    <>
      <Tooltip title="Offline area manager — cache an area for offline use">
        <span>
          <IconButton
            ref={anchorRef}
            size="small"
            disabled={!cacheable}
            onClick={() => (open ? closeAll() : openPanel())}
            aria-label={t('Cache an area for offline use')}
            sx={{
              'bgcolor': 'background.paper',
              'boxShadow': 2,
              '&:hover': { bgcolor: 'background.paper' },
            }}
          >
            <DownloadForOfflineIcon
              fontSize="small"
              color={open ? 'primary' : 'inherit'}
              sx={{ color: open ? color : undefined }}
            />
          </IconButton>
        </span>
      </Tooltip>

      <Popper
        open={open}
        anchorEl={anchorRef.current}
        placement="bottom-end"
        style={{ zIndex: 1300 }}
      >
        <ClickAwayListener
          onClickAway={() => {
            /* keep open — map clicks draw vertices */
          }}
        >
          <Paper elevation={6} sx={{ p: 1.5, width: 320, mt: 0.5 }}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle2">{t('Offline area')}</Typography>

              {!cacheable && (
                <Alert severity="info" sx={{ py: 0 }}>
                  {t('This provider cannot be pre-cached.')}
                </Alert>
              )}

              {error && (
                <Alert severity="error" sx={{ py: 0 }}>
                  {error}
                </Alert>
              )}

              {/* ── live / finished operation ─────────────────────────────── */}
              {op !== null ? (
                <>
                  {op.state === 'completed' ? (
                    <Alert severity="success" sx={{ py: 0 }}>
                      Area cached: {op.completed_tiles.toLocaleString()} downloaded,{' '}
                      {op.skipped_cached.toLocaleString()} already cached
                      {op.failed_tiles > 0 ? `, ${op.failed_tiles} failed` : ''}.{' '}
                      {formatBytes(op.downloaded_bytes)} downloaded.
                    </Alert>
                  ) : op.state === 'cancelled' ? (
                    <Alert severity="warning" sx={{ py: 0 }}>
                      Stopped after {op.completed_tiles.toLocaleString()} of{' '}
                      {op.total_tiles.toLocaleString()} tiles.
                    </Alert>
                  ) : op.state === 'failed' ? (
                    <Alert severity="error" sx={{ py: 0 }}>
                      Download failed{op.note ? ` — ${op.note}` : '.'}
                    </Alert>
                  ) : (
                    <Box>
                      <LinearProgress variant="determinate" value={op.percent} />
                      <Typography variant="caption" color="text.secondary">
                        {(
                          op.completed_tiles +
                          op.skipped_cached +
                          op.no_imagery_tiles
                        ).toLocaleString()}{' '}
                        / {op.total_tiles.toLocaleString()} tiles ({op.percent.toFixed(0)}%)
                        {op.failed_tiles > 0 ? ` — ${op.failed_tiles} failed` : ''}
                        {paused ? ' — paused' : ''}
                      </Typography>
                      {op.note && (
                        <Typography variant="caption" color="warning.main" display="block">
                          {op.note}
                        </Typography>
                      )}
                    </Box>
                  )}

                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    {running && (
                      <Button size="small" onClick={() => act(() => offlineApi.pause(op.id))}>
                        {t('Pause')}
                      </Button>
                    )}
                    {paused && (
                      <Button size="small" onClick={() => act(() => offlineApi.resume(op.id))}>
                        {t('Resume')}
                      </Button>
                    )}
                    {(running || paused) && (
                      <Button
                        size="small"
                        color="inherit"
                        onClick={() => act(() => offlineApi.cancel(op.id))}
                      >
                        {t('Cancel')}
                      </Button>
                    )}
                    {terminal && op.failed_tiles > 0 && (
                      <Button size="small" onClick={() => act(() => offlineApi.retry(op.id))}>
                        {t('Retry failed')}
                      </Button>
                    )}
                    {terminal && (
                      <Button size="small" color="inherit" onClick={closeAll}>
                        {t('Close')}
                      </Button>
                    )}
                  </Stack>
                </>
              ) : (
                /* ── drawing + estimate ──────────────────────────────────── */
                <>
                  <Typography variant="caption" color="text.secondary">
                    {drawing
                      ? 'Drawing: click at least 3 corners on the map (4 for a rectangle), then press “Done”.'
                      : canDraw
                        ? 'Area set — review the estimate, then download.'
                        : 'Outline an area of at least three points.'}
                  </Typography>

                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
                      {points.length} point{points.length === 1 ? '' : 's'} drawn
                    </Typography>
                    <Tooltip title={t('Undo last point')}>
                      <span>
                        <IconButton size="small" onClick={undoPoint} disabled={points.length === 0}>
                          <UndoIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                    {drawing ? (
                      <Button size="small" onClick={finishDrawing} disabled={!canDraw}>
                        {t('Done')}
                      </Button>
                    ) : (
                      <Button size="small" onClick={startDrawing}>
                        {t('Redraw')}
                      </Button>
                    )}
                  </Stack>

                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="caption" color="text.secondary">
                      {t('Zoom')}
                    </Typography>
                    <Select
                      size="small"
                      value={zoomMin}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setZoomMin(v);
                        if (v > zoomMax) setZoomMax(v);
                      }}
                      sx={{ minWidth: 64 }}
                      inputProps={{ 'aria-label': 'Minimum zoom' }}
                    >
                      {ZOOM_CHOICES.map((z) => (
                        <MenuItem key={z} value={z}>
                          z{z}
                        </MenuItem>
                      ))}
                    </Select>
                    <Typography variant="caption" color="text.secondary">
                      →
                    </Typography>
                    <Select
                      size="small"
                      value={zoomMax}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setZoomMax(v);
                        if (v < zoomMin) setZoomMin(v);
                      }}
                      sx={{ minWidth: 64 }}
                      inputProps={{ 'aria-label': 'Maximum zoom' }}
                    >
                      {ZOOM_CHOICES.map((z) => (
                        <MenuItem key={z} value={z}>
                          z{z}
                        </MenuItem>
                      ))}
                    </Select>
                  </Stack>

                  {canDraw && (
                    <Box>
                      {estimating ? (
                        <Typography variant="caption" color="text.secondary">
                          {t('Estimating…')}
                        </Typography>
                      ) : estimate ? (
                        <>
                          <Typography variant="caption" color="text.secondary" component="div">
                            Total tiles: {estimate.total_tiles.toLocaleString()} · already cached:{' '}
                            {estimate.cached_tiles.toLocaleString()} (
                            {estimate.total_tiles > 0
                              ? Math.round((100 * estimate.cached_tiles) / estimate.total_tiles)
                              : 0}
                            %)
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            New tiles / upstream requests:{' '}
                            {estimate.estimated_upstream_requests.toLocaleString()}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" component="div">
                            Estimated storage: {formatBytes(estimate.estimated_storage_bytes)}
                            {estimate.average_tile_size_source === 'default'
                              ? ' (default tile size — no cached sample yet)'
                              : ''}
                          </Typography>
                          {!estimate.budget.within_budget && (
                            <Alert severity="warning" sx={{ py: 0, mt: 0.5 }}>
                              {estimate.budget.reason ?? 'Over the configured request budget.'}
                            </Alert>
                          )}
                        </>
                      ) : null}
                    </Box>
                  )}

                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    <Button size="small" color="inherit" onClick={closeAll}>
                      {t('Cancel')}
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      onClick={runCache}
                      disabled={
                        !canDraw ||
                        estimating ||
                        !estimate ||
                        !estimate.budget.within_budget ||
                        estimate.missing_tiles === 0
                      }
                    >
                      {estimate && estimate.missing_tiles === 0 && canDraw
                        ? 'Fully cached'
                        : `Download ${estimate ? estimate.missing_tiles.toLocaleString() : ''} tiles`}
                    </Button>
                  </Stack>
                </>
              )}
            </Stack>
          </Paper>
        </ClickAwayListener>
      </Popper>
    </>
  );
}

export default OfflineCachePanel;
