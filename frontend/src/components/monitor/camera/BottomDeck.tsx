/**
 * `monitor/camera/BottomDeck.tsx` — the drag-resizable, collapsible deck under the
 * video: [Map] [Detections] [Events].
 *
 * ★ The seam is the workspace's own `Splitter` — deltas up, clamping by the store —
 *   and the height persists with the rest of the monitor layout.
 */

import type { JSX, ReactNode } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Tooltip from '@mui/material/Tooltip';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import { useMonitorLayoutStore, type DeckTab } from '../../../store/monitorLayoutStore';
import { Splitter } from '../../workspace/Splitter';
import { t } from '../../../i18n';

const ALL_TABS: readonly DeckTab[] = ['map', 'detections', 'events'];

export interface BottomDeckProps {
  /** Resizable on desktop; a fixed-height tab strip below 1280 px. */
  resizable: boolean;
  counts: { detections: number; events: number };
  /** Which tabs the deck offers — the map leaves it when it sits beside the video. */
  tabs?: readonly DeckTab[];
  /** Controls at the end of the tab row (before collapse) — e.g. "map beside video". */
  actions?: ReactNode;
  children: (tab: DeckTab) => ReactNode;
}

export function BottomDeck({
  resizable,
  counts,
  tabs = ALL_TABS,
  actions,
  children,
}: BottomDeckProps): JSX.Element {
  const deckPx = useMonitorLayoutStore((s) => s.deckPx);
  const setDeckPx = useMonitorLayoutStore((s) => s.setDeckPx);
  const deckOpen = useMonitorLayoutStore((s) => s.deckOpen);
  const setDeckOpen = useMonitorLayoutStore((s) => s.setDeckOpen);
  const storedTab = useMonitorLayoutStore((s) => s.deckTab);
  const setTab = useMonitorLayoutStore((s) => s.setDeckTab);
  // ★ A remembered tab the deck no longer offers falls back to the first one it does.
  const tab: DeckTab = tabs.includes(storedTab) ? storedTab : (tabs[0] ?? 'detections');
  const height = deckOpen ? (resizable ? deckPx : 280) : 40;

  return (
    <Box
      component="section"
      aria-label={t('Deck')}
      sx={{
        height,
        // ★ A persisted deck height from a taller window (or a smaller display
        //   size) must not crush the video to nothing: the deck yields, keeping
        //   at least ~140px of the column for the picture above it.
        maxHeight: deckOpen ? 'calc(100% - 140px)' : undefined,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        borderTop: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        position: 'relative',
      }}
    >
      {resizable && deckOpen && (
        <Box sx={{ position: 'absolute', top: -3, left: 0, right: 0, zIndex: 2 }}>
          <Splitter
            orientation="horizontal"
            ariaLabel={t('Resize the deck')}
            valueNow={Math.round((deckPx / 720) * 100)}
            // Dragging the seam UP grows the deck.
            onDragDelta={(d) => setDeckPx(deckPx - d)}
          />
        </Box>
      )}
      <Stack direction="row" alignItems="center" sx={{ height: 40, px: 1, flexShrink: 0 }}>
        <Tabs value={tab} onChange={(_e, v: DeckTab) => setTab(v)} sx={{ minHeight: 40, flex: 1 }}>
          {tabs.includes('map') && <Tab value="map" label={t('Map')} sx={{ minHeight: 40 }} />}
          {tabs.includes('detections') && (
            <Tab
              value="detections"
              label={`${t('Detections')}${counts.detections > 0 ? ` · ${counts.detections}` : ''}`}
              sx={{ minHeight: 40 }}
            />
          )}
          {tabs.includes('events') && (
            <Tab
              value="events"
              label={`${t('Events')}${counts.events > 0 ? ` · ${counts.events}` : ''}`}
              sx={{ minHeight: 40 }}
            />
          )}
        </Tabs>
        {actions}
        <Tooltip title={deckOpen ? t('Collapse the deck') : t('Expand the deck')}>
          <IconButton
            size="small"
            onClick={() => setDeckOpen(!deckOpen)}
            aria-label={deckOpen ? t('Collapse the deck') : t('Expand the deck')}
          >
            {deckOpen ? <ExpandMoreIcon fontSize="small" /> : <ExpandLessIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Stack>
      {/* ★ overflow hidden: whatever a pane insists on (a map with a height floor,
          a wide table), it clips at the deck's edge instead of painting over the
          page below — the deck's height is the deck's height. */}
      {deckOpen && (
        <Box sx={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }}>
          {children(tab)}
        </Box>
      )}
    </Box>
  );
}
