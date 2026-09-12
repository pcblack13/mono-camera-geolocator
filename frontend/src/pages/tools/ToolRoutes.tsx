/**
 * `pages/tools/ToolRoutes.tsx` — the tool pages' frame, and the legacy `?tab=` forwarder.
 *
 * ★ EVERY TOOL AT ITS OWN ADDRESS (2026-09-04). The tools used to be tabs of the
 *   Projects page (`/projects?tab=videos`…). The Projects page is retired — the
 *   camera is the unit of work — so each now answers at `/videos` and `/drift`
 *   (DEM processing is a page of its own already), inside the same
 *   full-bleed frame the tab host gave them. `LegacyTabForwarder` keeps every old
 *   link alive: `/projects?tab=x&…` becomes `/x?…`; the bare list goes to the
 *   camera workspace, which is where "your work" lives now.
 */

import type { JSX, ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';

import { pageForLegacyTab } from '../../components/shell/workspaces';

/** The frame the tab host used to give each tool: full-bleed, padded, scrolling. */
export function ToolFrame({ children }: { children: ReactNode }): JSX.Element {
  return (
    // ★ THE SCROLLBAR LANE IS ALWAYS RESERVED (2026-09-12). Without it the bar
    //   appearing steals 10px of width, the card grids inside are `1fr` columns of
    //   aspect-ratio tiles, so narrower columns mean shorter tiles, mean shorter
    //   content, mean the bar leaves again — a loop the page rides as a shake.
    //   Holding the lane open costs 10px and makes the width unconditional.
    <Box sx={{ flex: 1, overflow: 'auto', scrollbarGutter: 'stable' }}>
      <Box sx={{ py: { xs: 2, md: 4 }, px: { xs: 2, md: 3 } }}>
        <Box sx={{ minWidth: 0, width: '100%' }}>{children}</Box>
      </Box>
    </Box>
  );
}

/** `/projects?tab=x&rest` → `/x?rest`; anything else under `/projects` → the camera workspace. */
export function legacyTabTarget(search: string): string {
  const page = pageForLegacyTab(search);
  if (page === null) return '/cameras';
  const params = new URLSearchParams(search);
  params.delete('tab');
  const rest = params.toString();
  return rest === '' ? page.path : `${page.path}?${rest}`;
}

export function LegacyTabForwarder(): JSX.Element {
  const { search } = useLocation();
  // ★ `replace`, so the forwarding hop never becomes a back destination.
  return <Navigate to={legacyTabTarget(search)} replace />;
}
