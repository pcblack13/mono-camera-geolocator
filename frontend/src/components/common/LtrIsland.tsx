/**
 * `common/LtrIsland.tsx` — a left-to-right fence inside the mirrored Arabic UI.
 *
 * ★ WHY IT EXISTS. The first RTL attempt (2026-08-21) flipped the document alone
 *   and broke every surface that computes its own geometry: the Konva photo stage,
 *   the Leaflet and MapLibre maps, the drag handles. Those components translate
 *   `clientX` into their own left-origin coordinate systems, and a mirrored
 *   document moves the page out from under that maths. The 2026-08-31 redo mirrors
 *   the chrome but wraps each geometry surface in this island, which pins all
 *   three direction mechanisms back to LTR at once:
 *
 *     1. `dir="ltr"` on a wrapper — CSS `direction` for the subtree (flex order,
 *        text alignment, scroll behaviour);
 *     2. an LTR emotion cache — so `sx`/styled physical properties (`left`,
 *        `marginLeft`) stop being flipped by `stylis-plugin-rtl`;
 *     3. an LTR MUI theme — so sliders, tabs and menus anchor the LTR way.
 *
 * ★ `display: contents` keeps the wrapper out of layout: the island's child sizes
 *   against the island's PARENT, so wrapping a full-bleed map or stage costs no
 *   pixels. (CSS `direction` still inherits through a box-less element.)
 *
 * ★ In an LTR session it renders nothing extra — children pass straight through.
 */

import type { JSX, ReactNode } from 'react';
import { CacheProvider } from '@emotion/react';
import { ThemeProvider, useTheme } from '@mui/material/styles';

import { getTheme } from '../../theme';
import { ltrCache } from '../../theme/styleCache';

export interface LtrIslandProps {
  children: ReactNode;
}

export function LtrIsland({ children }: LtrIslandProps): JSX.Element {
  const theme = useTheme();
  if (theme.direction !== 'rtl') return <>{children}</>;
  return (
    <CacheProvider value={ltrCache}>
      <ThemeProvider theme={getTheme(theme.palette.mode)}>
        <div dir="ltr" style={{ display: 'contents' }}>
          {children}
        </div>
      </ThemeProvider>
    </CacheProvider>
  );
}
