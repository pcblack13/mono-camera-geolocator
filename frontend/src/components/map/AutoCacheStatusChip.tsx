/**
 * `map/AutoCacheStatusChip.tsx` — the compact automatic-caching indicator + toggle.
 *
 * ★ Deliberately small (one chip in the map chrome): coverage of the current view,
 *   a spinner-ish count while tiles download, and the on/off switch in a popover.
 *   Never a modal, never a toast per tile — background work stays in the background.
 */

import { useRef, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import ClickAwayListener from '@mui/material/ClickAwayListener';
import FormControlLabel from '@mui/material/FormControlLabel';
import Paper from '@mui/material/Paper';
import Popper from '@mui/material/Popper';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Typography from '@mui/material/Typography';
import CloudDoneIcon from '@mui/icons-material/CloudDone';
import CloudDownloadIcon from '@mui/icons-material/CloudDownload';
import CloudOffIcon from '@mui/icons-material/CloudOff';

import { autoCacheApi, formatBytes, type AutoCacheStatus } from '../../api/offline';
import { useAutoCacheStore } from '../../store/autoCacheStore';
import { t } from '../../i18n';

/**
 * The chip's one-line label — pure, exported for tests.
 *
 * Precedence: offline beats everything (cached imagery still serves, and the user must
 * know why nothing new downloads) → toggle off → live download count → coverage.
 */
export function autoCacheLabel(
  enabled: boolean,
  online: boolean,
  status: AutoCacheStatus | null,
): string {
  if (!online) return 'Offline — cached imagery';
  if (!enabled) return 'Auto-cache off';
  const queued = status?.queued_tiles ?? 0;
  if (queued > 0) return `Caching… ${queued} left`;
  const coverage = status?.coverage_percent;
  if (coverage === null || coverage === undefined) return 'Auto-cache on';
  return coverage >= 100 ? 'Area cached' : `${coverage.toFixed(0)}% cached`;
}

export function AutoCacheStatusChip(): JSX.Element {
  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const enabled = useAutoCacheStore((s) => s.enabled);
  const online = useAutoCacheStore((s) => s.online);
  const status = useAutoCacheStore((s) => s.status);
  const setEnabled = useAutoCacheStore((s) => s.setEnabled);
  const setStatus = useAutoCacheStore((s) => s.setStatus);

  const downloading = (status?.queued_tiles ?? 0) > 0;
  const coverage = status?.coverage_percent;
  const label = autoCacheLabel(enabled, online, status);

  const icon = !online ? (
    <CloudOffIcon fontSize="small" />
  ) : downloading ? (
    <CloudDownloadIcon fontSize="small" />
  ) : (
    <CloudDoneIcon fontSize="small" />
  );

  const toggle = (next: boolean): void => {
    setEnabled(next); // optimistic — the map must never feel blocked
    autoCacheApi
      .setEnabled(next)
      .then(setStatus)
      .catch(() => undefined); // preference still applies locally (reporter stops posting)
  };

  const session = status?.session;

  return (
    <>
      <Box ref={anchorRef} sx={{ pointerEvents: 'auto' }}>
        <Chip
          size="small"
          icon={icon}
          label={label}
          onClick={() => setOpen((o) => !o)}
          color={!online ? 'warning' : downloading ? 'info' : 'default'}
          sx={{ bgcolor: 'background.paper', boxShadow: 2 }}
          aria-label={t('Automatic imagery caching status')}
        />
      </Box>
      <Popper
        open={open}
        anchorEl={anchorRef.current}
        placement="bottom-end"
        style={{ zIndex: 1300 }}
      >
        <ClickAwayListener onClickAway={() => setOpen(false)}>
          <Paper elevation={6} sx={{ p: 1.5, width: 260, mt: 0.5 }}>
            <Stack spacing={0.75}>
              <Typography variant="subtitle2">{t('Offline cache')}</Typography>
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={enabled}
                    onChange={(e) => toggle(e.target.checked)}
                    inputProps={{ 'aria-label': 'Automatic caching' }}
                  />
                }
                label={<Typography variant="body2">{t('Automatic caching')}</Typography>}
              />
              <Typography variant="caption" color="text.secondary">
                {t(
                  'Caches the area you are working in (current zoom, plus a small buffer) into the same offline cache the manual area download uses.',
                )}
              </Typography>
              {!online && (
                <Typography variant="caption" color="warning.main">
                  Offline — automatic caching paused; cached imagery keeps working.
                </Typography>
              )}
              {status?.note && (
                <Typography variant="caption" color="text.secondary">
                  {status.note}
                </Typography>
              )}
              {status && status.zoom !== null && (
                <Typography variant="caption" color="text.secondary">
                  Current area:{' '}
                  {coverage !== null && coverage !== undefined ? `${coverage.toFixed(0)}%` : '—'}{' '}
                  cached · z{status.zoom}
                  {downloading ? ` · ${status.queued_tiles} queued` : ''}
                </Typography>
              )}
              {session && (
                <Typography variant="caption" color="text.secondary">
                  Session: {session.tiles_downloaded.toLocaleString()} tiles ·{' '}
                  {formatBytes(session.bytes_downloaded)}
                  {session.tiles_failed > 0 ? ` · ${session.tiles_failed} failed` : ''}
                  {session.limit_reached ? ` · limit: ${session.limit_reached}` : ''}
                </Typography>
              )}
            </Stack>
          </Paper>
        </ClickAwayListener>
      </Popper>
    </>
  );
}

export default AutoCacheStatusChip;
