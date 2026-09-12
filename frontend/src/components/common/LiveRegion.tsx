/**
 * `common/LiveRegion.tsx` — the `aria-live` announcer (50-frontend §8.8 item 4).
 *
 * ★ A Konva stage is one opaque `<canvas>`, invisible to assistive technology. Canvas
 *   actions ("Added point P4", "Match complete. 6 points. 1 below threshold.") are
 *   announced HERE so a screen-reader user hears what a sighted user sees. Destructive
 *   or failure announcements use `assertive`; everything else is `polite`.
 *
 * ★ Visually hidden, never `display:none` — a hidden element is not announced. The
 *   off-screen clip pattern keeps it in the accessibility tree while removing it from
 *   the visual and layout flow.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type JSX,
  type ReactNode,
} from 'react';
import Box from '@mui/material/Box';

export interface LiveRegionProps {
  /** `polite` waits for a pause; `assertive` interrupts. Failures use `assertive`. */
  politeness?: 'polite' | 'assertive';
  /** The text to announce. Changing this string is what triggers an announcement. */
  message: string;
}

/** The single off-screen-clip style, shared so every hidden-but-announced node matches.
 *
 * ★ THE UNITS ARE STRINGS, NOT NUMBERS (2026-09-01). In MUI's `sx`, a numeric
 * `width`/`height` in (0, 1] means **100%** — so `height: 1` made each announcer a
 * FULL-VIEWPORT absolute box. Invisible (clipped), but it still stretched the
 * document's scroll extent: every page could suddenly scroll a whole viewport of
 * nothing, sliding the top bars away. `'1px'` means one pixel and nothing else. */
export const visuallyHiddenSx = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

export function LiveRegion({ politeness = 'polite', message }: LiveRegionProps): JSX.Element {
  return (
    <Box
      component="div"
      role="status"
      aria-live={politeness}
      aria-atomic="true"
      sx={visuallyHiddenSx}
    >
      {message}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The global announcer — mounted once by AppShell (§2.1 / §8.8 item 4).
//
// ★ Any component (notably IU-26's Konva canvas, whose actions are invisible to AT)
//   calls `useAnnounce()('Added point P4', 'polite')` and the shell's off-screen live
//   region speaks it. Two channels — polite and assertive — so a failure interrupts
//   while a routine edit waits for a pause.
// ─────────────────────────────────────────────────────────────────────────────

export type Announce = (message: string, politeness?: 'polite' | 'assertive') => void;

const LiveAnnounceContext = createContext<Announce | null>(null);

export function LiveAnnounceProvider({ children }: { children: ReactNode }): JSX.Element {
  const [polite, setPolite] = useState('');
  const [assertive, setAssertive] = useState('');

  const announce = useCallback<Announce>((message, politeness = 'polite') => {
    // A duplicate string is not re-announced by AT; append a zero-width space to force it.
    // Escaped, not a literal — an invisible char in source is unreviewable.
    const ZWSP = '\u200B';
    const stamped = message.endsWith(ZWSP) ? message.slice(0, -1) : `${message}${ZWSP}`;
    if (politeness === 'assertive') setAssertive(stamped);
    else setPolite(stamped);
  }, []);

  const value = useMemo(() => announce, [announce]);

  return (
    <LiveAnnounceContext.Provider value={value}>
      {children}
      <LiveRegion politeness="polite" message={polite} />
      <LiveRegion politeness="assertive" message={assertive} />
    </LiveAnnounceContext.Provider>
  );
}

/** Get the announce function. Degrades to a no-op outside the provider (never throws). */
export function useAnnounce(): Announce {
  const ctx = useContext(LiveAnnounceContext);
  return useCallback<Announce>(
    (message, politeness) => {
      ctx?.(message, politeness);
    },
    [ctx],
  );
}

export default LiveRegion;
