/**
 * `monitor/globe/GlobeHud.tsx` — the thin instrument strip over the globe.
 *
 * ★ EVERY NUMBER IS TABULAR MONO and never reflows: the Zulu clock ticks in place,
 *   the counts change width by digits only. Attribution is a licence obligation
 *   and rides the page's BOTTOM-LEFT corner permanently (2026-09-12) — off the
 *   strip, but never a dismissible map control.
 */

import { useEffect, useState, type JSX, type ReactNode } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import ViewSidebarOutlinedIcon from '@mui/icons-material/ViewSidebarOutlined';

import type { ProviderInfo } from '../../../types/geo';
import { t } from '../../../i18n';

export interface GlobeHudProps {
  /** Globe or grid — the trafficvision-style pair (2026-09-02). */
  view: 'globe' | 'grid';
  onView: (v: 'globe' | 'grid') => void;
  cameras: number;
  live: number;
  lost: number;
  provider: ProviderInfo | undefined;
  hudOpen: boolean;
  onToggleHud: () => void;
  onHelp: () => void;
  /** ★ 2026-09-10: the place/coordinate search box, and the offline-cache tool. */
  search?: ReactNode;
  tools?: ReactNode;
  /** Borders and names on the globe. */
  placesVisible?: boolean;
  onTogglePlaces?: () => void;
}

function zulu(d: Date): string {
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}Z`;
}

/** A live UTC clock, one re-render a second. */
export function ZuluClock(): JSX.Element {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <Typography
      variant="mono"
      component="span"
      aria-label={t('UTC time')}
      sx={{ fontSize: 13, direction: 'ltr', letterSpacing: '0.04em' }}
    >
      {zulu(now)}
    </Typography>
  );
}

function Stat({
  value,
  label,
  tone,
}: {
  value: number;
  label: string;
  tone?: string;
}): JSX.Element {
  return (
    <Stack direction="row" spacing={0.75} alignItems="baseline" sx={{ direction: 'ltr' }}>
      <Typography variant="mono" component="span" sx={{ fontSize: 14, color: tone ?? 'inherit' }}>
        {value}
      </Typography>
      <Typography
        variant="caption"
        component="span"
        sx={{ letterSpacing: '0.08em', color: 'var(--text-tertiary)', fontSize: 11 }}
      >
        {label}
      </Typography>
    </Stack>
  );
}

export function GlobeHud({
  view,
  onView,
  cameras,
  live,
  lost,
  provider,
  hudOpen,
  onToggleHud,
  onHelp,
  search,
  tools,
  placesVisible = true,
  onTogglePlaces,
}: GlobeHudProps): JSX.Element {
  const attribution =
    provider === undefined
      ? ''
      : provider.attribution.text.trim() !== ''
        ? provider.attribution.text
        : provider.title;
  return (
    <>
      <Box
        component="header"
        sx={{
          position: 'absolute',
          top: 0,
          insetInlineStart: 0,
          insetInlineEnd: 0,
          height: 40,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          px: 1.5,
          bgcolor: 'var(--scrim-hud)',
          borderBottom: '1px solid var(--hairline)',
          backdropFilter: 'blur(6px)',
          zIndex: 2,
        }}
      >
        <ZuluClock />
        {/* ★ GRID | GLOBE — the wall of live tiles, or the Earth. One fleet, two readings. */}
        <ToggleButtonGroup
          exclusive
          size="small"
          value={view}
          onChange={(_e, v: 'globe' | 'grid' | null) => {
            if (v !== null) onView(v);
          }}
          sx={{ height: 26 }}
        >
          <ToggleButton value="grid" sx={{ px: 1, fontSize: 10.5, letterSpacing: 1 }}>
            {t('GRID')}
          </ToggleButton>
          <ToggleButton value="globe" sx={{ px: 1, fontSize: 10.5, letterSpacing: 1 }}>
            {t('GLOBE')}
          </ToggleButton>
        </ToggleButtonGroup>
        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
          <Stat value={cameras} label={t('CAMERAS')} />
          <Stat value={live} label={t('LIVE')} tone="var(--status-busy)" />
          <Stat
            value={lost}
            label={t('LOST')}
            tone={lost > 0 ? 'var(--status-error)' : undefined}
          />
        </Stack>
        <Box sx={{ flex: 1, display: 'flex', justifyContent: 'center', minWidth: 0 }}>{search}</Box>
        {tools}
        {onTogglePlaces !== undefined && view === 'globe' && (
          <Tooltip
            title={placesVisible ? t('Hide borders and names') : t('Show borders and names')}
          >
            <IconButton
              size="small"
              onClick={onTogglePlaces}
              aria-label={placesVisible ? t('Hide borders and names') : t('Show borders and names')}
              aria-pressed={placesVisible}
              sx={{ color: placesVisible ? 'var(--accent)' : undefined }}
            >
              <PublicOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        {/* ★ NO CONNECTION CHIP HERE (owner ask 2026-09-12): the top bar already
          carries the app's pulse, and a second Online beside it read as chrome.
          The library door left with it — Recorded videos is a page of its own in
          the nav, and the strip is for what is happening NOW. */}
        <Tooltip title={`${t('Keyboard shortcuts')} (?)`}>
          <IconButton size="small" onClick={onHelp} aria-label={t('Keyboard shortcuts')}>
            <HelpOutlineIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={hudOpen ? t('Hide camera list') : t('Show camera list')}>
          <IconButton
            size="small"
            onClick={onToggleHud}
            aria-label={hudOpen ? t('Hide camera list') : t('Show camera list')}
            aria-pressed={hudOpen}
          >
            <ViewSidebarOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      {/* ★ ATTRIBUTION RIDES THE BOTTOM-LEFT CORNER (owner ask 2026-09-12). It is
          still a licence obligation and still never dismissible — it simply stops
          crowding the instrument strip, where it sat between the tools and the
          status and read as one more control. */}
      {provider !== undefined && (
        <Typography
          variant="caption"
          noWrap
          title={attribution}
          sx={{
            position: 'absolute',
            bottom: 6,
            insetInlineStart: 10,
            zIndex: 2,
            maxWidth: 'min(60%, 420px)',
            px: 0.75,
            py: 0.25,
            borderRadius: 'var(--radius-sm)',
            bgcolor: 'var(--scrim-hud)',
            color: 'var(--text-tertiary)',
          }}
        >
          {provider.title} · {attribution}
        </Typography>
      )}
    </>
  );
}
