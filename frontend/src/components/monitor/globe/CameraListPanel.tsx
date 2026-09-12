/**
 * `monitor/globe/CameraListPanel.tsx` — the right HUD: every camera, searchable.
 *
 * ★ A row click FLIES the globe; the row's "Open" goes to the camera page. Status
 *   is a pill in shape AND colour (the two-channel rule), and reads the same
 *   last-known state the marker paints.
 *
 * ★ SEARCH AND A FILTER, NO ADD (2026-09-07, owner ask). A camera is registered
 *   through the camera workspace's pipeline — name, connection, DEM, calibration,
 *   frame, control points, lookup table — so the "+" that added one by bare
 *   coordinates is gone from the fleet. What the fleet needs instead is to narrow:
 *   the search box, and All / Live / Lost over the same states the HUD counts
 *   (`monitor/cameraFilter.ts`).
 */

import { useMemo, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LaunchOutlinedIcon from '@mui/icons-material/LaunchOutlined';
import SearchIcon from '@mui/icons-material/Search';

import type {
  CameraStatus,
  CameraStatusState,
  RegisteredCamera,
} from '../../../store/cameraRegistryStore';
import { matchesFilter, statusOf, type CameraFilter } from '../cameraFilter';
import { StatusPill, type Lifecycle } from '../../ui';
import { t } from '../../../i18n';

export interface CameraListPanelProps {
  cameras: readonly RegisteredCamera[];
  statuses: Readonly<Record<string, CameraStatus>>;
  onFly: (id: string) => void;
  onOpen: (id: string) => void;
  /** The search box's element, so `/` can focus it. */
  searchRef?: (el: HTMLInputElement | null) => void;
}

const PILL: Record<CameraStatusState, { lifecycle: Lifecycle; dot: string }> = {
  live: { lifecycle: 'committed', dot: 'var(--status-busy)' },
  connecting: { lifecycle: 'draft', dot: 'var(--status-warn)' },
  lost: { lifecycle: 'refused', dot: 'var(--status-error)' },
  refused: { lifecycle: 'refused', dot: 'var(--status-error)' },
  unknown: { lifecycle: 'stale', dot: 'var(--text-tertiary)' },
};

export function CameraListPanel({
  cameras,
  statuses,
  onFly,
  onOpen,
  searchRef,
}: CameraListPanelProps): JSX.Element {
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<CameraFilter>('all');
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return cameras.filter((c) => {
      if (!matchesFilter(statusOf(statuses, c.id), filter)) return false;
      if (needle === '') return true;
      return (
        c.name.toLowerCase().includes(needle) ||
        c.source.toLowerCase().includes(needle) ||
        (c.tags ?? []).some((tag) => tag.toLowerCase().includes(needle))
      );
    });
  }, [cameras, statuses, q, filter]);

  return (
    <Box
      component="aside"
      aria-label={t('Cameras')}
      sx={{
        position: 'absolute',
        top: 48,
        bottom: 12,
        insetInlineEnd: 12,
        width: 300,
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'var(--scrim-panel)',
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--radius-lg, 8px)',
        backdropFilter: 'blur(6px)',
        zIndex: 2,
        overflow: 'hidden',
      }}
    >
      <Stack spacing={1} sx={{ p: 1.25, borderBottom: '1px solid var(--hairline)' }}>
        <TextField
          size="small"
          fullWidth
          placeholder={t('Search cameras')}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          inputRef={searchRef}
          inputProps={{ 'aria-label': t('Search cameras') }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Stack direction="row" spacing={1} alignItems="center">
          <ToggleButtonGroup
            exclusive
            size="small"
            value={filter}
            onChange={(_e, v: CameraFilter | null) => {
              if (v !== null) setFilter(v);
            }}
            aria-label={t('Show')}
            sx={{ '& .MuiToggleButton-root': { px: 1.25, py: 0.25, fontSize: 12 } }}
          >
            <ToggleButton value="all">{t('All')}</ToggleButton>
            <ToggleButton value="live">{t('Live')}</ToggleButton>
            <ToggleButton value="lost">{t('Lost')}</ToggleButton>
          </ToggleButtonGroup>
          <Typography
            className="le-mono"
            sx={{ fontSize: 11, color: 'text.secondary', ml: 'auto' }}
          >
            {shown.length} / {cameras.length}
          </Typography>
        </Stack>
      </Stack>
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        {shown.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            {cameras.length === 0
              ? t('No cameras yet — register one in the camera workspace.')
              : q.trim() === ''
                ? // ★ Blaming the search when no search was typed sends the reader
                  //   looking for a box they did not touch — name the filter.
                  filter === 'live'
                  ? t('No camera is live right now.')
                  : t('No camera is lost right now.')
                : t('No camera matches that search.')}
          </Typography>
        ) : (
          shown.map((c) => {
            const st = statusOf(statuses, c.id);
            return (
              <Stack
                key={c.id}
                direction="row"
                alignItems="center"
                spacing={1}
                role="button"
                tabIndex={0}
                onClick={() => onFly(c.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onFly(c.id);
                  }
                }}
                sx={{
                  'px': 1.25,
                  'py': 0.75,
                  'cursor': 'pointer',
                  'borderBottom': '1px solid var(--hairline)',
                  '&:hover': { bgcolor: 'var(--accent-quiet)' },
                }}
              >
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" noWrap>
                    {c.name}
                  </Typography>
                  <Typography
                    variant="mono"
                    sx={{
                      display: 'block',
                      fontSize: 11,
                      color: 'var(--text-tertiary)',
                      direction: 'ltr',
                    }}
                  >
                    {c.lat.toFixed(5)}, {c.lon.toFixed(5)}
                  </Typography>
                </Box>
                <StatusPill lifecycle={PILL[st].lifecycle} dotColor={PILL[st].dot}>
                  {t(st)}
                </StatusPill>
                <Tooltip title={t('Open camera')}>
                  <IconButton
                    size="small"
                    aria-label={`${t('Open')} ${c.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpen(c.id);
                    }}
                  >
                    <LaunchOutlinedIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                </Tooltip>
              </Stack>
            );
          })
        )}
      </Box>
    </Box>
  );
}
