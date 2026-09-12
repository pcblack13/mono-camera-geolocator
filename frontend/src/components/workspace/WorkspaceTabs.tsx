/**
 * `workspace/WorkspaceTabs.tsx` — the tablet/mobile tabbed layout (50-frontend §1.5 / §2.6). **(pure)**
 *
 * ★ INVARIANT 1 — THE REFLOW NEVER UNMOUNTS A PANE. Tabs are `keepMounted` and hidden
 *   with `visibility:hidden; position:absolute`, NOT conditional rendering.
 *   "Unmounting the Konva stage would destroy the viewer transform, and unmounting
 *   the Leaflet map would destroy tile cache and force a re-fetch — costly on field
 *   cellular." All three panes stay mounted; only the active one is visible.
 *
 * ★ Badges surface e.g. "3 points below threshold" on the Points tab so a mobile user
 *   is not required to be looking at the table to learn something is wrong (§2.6).
 *
 * ★ `tabBarPosition` puts the bar at the bottom on `xs` (thumb zone) and the top on
 *   `sm`. Targets are ≥44×44 below `md` via the theme's overrides (§1.5 invariant 5).
 */

import type { JSX, ReactNode } from 'react';
import Badge from '@mui/material/Badge';
import Box from '@mui/material/Box';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import TableRowsOutlinedIcon from '@mui/icons-material/TableRowsOutlined';

import type { WorkspaceTab } from '../../store/workspaceStore';

export interface WorkspaceTabsProps {
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  tabBarPosition: 'top' | 'bottom';
  badges: Partial<Record<WorkspaceTab, number | 'dot'>>;
  imagePane: ReactNode;
  mapPane: ReactNode;
  dock: ReactNode;
}

const TAB_META: { tab: WorkspaceTab; label: string; icon: JSX.Element }[] = [
  { tab: 'image', label: 'Image', icon: <ImageOutlinedIcon /> },
  { tab: 'map', label: 'Map', icon: <MapOutlinedIcon /> },
  { tab: 'points', label: 'Points', icon: <TableRowsOutlinedIcon /> },
];

function PaneHost({ active, children }: { active: boolean; children: ReactNode }): JSX.Element {
  return (
    <Box
      role="tabpanel"
      hidden={!active}
      aria-hidden={!active}
      sx={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        overflow: 'hidden',
        // ★ Hidden, NOT unmounted — keep the stage and the map alive (§1.5 inv. 1).
        visibility: active ? 'visible' : 'hidden',
        pointerEvents: active ? 'auto' : 'none',
      }}
    >
      {children}
    </Box>
  );
}

export function WorkspaceTabs({
  activeTab,
  onTabChange,
  tabBarPosition,
  badges,
  imagePane,
  mapPane,
  dock,
}: WorkspaceTabsProps): JSX.Element {
  const bar = (
    <Tabs
      value={activeTab}
      onChange={(_e, v: WorkspaceTab) => onTabChange(v)}
      variant="fullWidth"
      sx={{
        flex: '0 0 auto',
        borderTop: tabBarPosition === 'bottom' ? 1 : 0,
        borderBottom: tabBarPosition === 'top' ? 1 : 0,
        borderColor: 'divider',
      }}
    >
      {TAB_META.map(({ tab, label, icon }) => {
        const badge = badges[tab];
        return (
          <Tab
            key={tab}
            value={tab}
            label={label}
            icon={
              badge !== undefined ? (
                <Badge
                  color="warning"
                  variant={badge === 'dot' ? 'dot' : 'standard'}
                  badgeContent={badge === 'dot' ? undefined : badge}
                >
                  {icon}
                </Badge>
              ) : (
                icon
              )
            }
          />
        );
      })}
    </Tabs>
  );

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {tabBarPosition === 'top' && bar}
      <Box sx={{ position: 'relative', flex: 1, minHeight: 0 }}>
        <PaneHost active={activeTab === 'image'}>{imagePane}</PaneHost>
        <PaneHost active={activeTab === 'map'}>{mapPane}</PaneHost>
        <PaneHost active={activeTab === 'points'}>{dock}</PaneHost>
      </Box>
      {tabBarPosition === 'bottom' && bar}
    </Box>
  );
}

export default WorkspaceTabs;
