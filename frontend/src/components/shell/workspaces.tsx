/**
 * `shell/workspaces.tsx` — THE PAGES of the app, and the tools beside them.
 *
 * ★ ONE REGISTRY. The navbar's page tabs, the small-screen drawer, the command
 *   palette and the page bar's titles all render from this list. Adding a
 *   page is one entry here — there is no second place to forget.
 *
 * ★ THREE PAGES IN THE BAR, TWO TOOLS BEHIND A CAMERA (2026-09-07, owner
 *   decision). The bar holds the CAMERA WORKSPACE (the registry of cameras and
 *   each camera's settings pipeline), CAMERAS MONITORING (the globe, the wall,
 *   each camera's page) and RECORDED VIDEOS (what the cameras recorded, and the
 *   clips uploaded by hand). DEM processing and the drift monitor are still pages
 *   with addresses, but a camera's settings open them — they are `tool`s here,
 *   kept out of the bar and the drawer, still named by the palette and the
 *   palette. Video detection is gone: a clip is detected where a camera is
 *   watched. The workspace dropdown that grouped six pages went with it.
 *
 * ★ EVERY PAGE HAS ITS OWN ADDRESS. The old `/projects?tab=…` links forward to
 *   these (`LegacyTabForwarder` in the router), so bookmarks and the guide's old
 *   doors keep working; `?tab=detect` lands on cameras monitoring.
 */

import type { JSX } from 'react';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import MovieOutlinedIcon from '@mui/icons-material/MovieOutlined';
import RadarOutlinedIcon from '@mui/icons-material/RadarOutlined';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';

export type WorkspaceKey = 'monitoring';

/** The legacy `?tab=` value each page answered to under `/projects` — forwarded now. */
export type WorkspacePageTab = 'cameras' | 'live' | 'videos' | 'dem' | 'drift';

export type WorkspacePageKey = 'cameras' | 'live' | 'videos' | 'dem' | 'drift';

export interface WorkspacePage {
  key: WorkspacePageKey;
  workspace: WorkspaceKey;
  /** English — the stable id, translated at render with `t()`. */
  label: string;
  /** One line, for the drawer and the palette. */
  description: string;
  icon: JSX.Element;
  /** The legacy `/projects?tab=` value, still forwarded to `path`. */
  tab: WorkspacePageTab;
  /** The absolute route. */
  path: string;
  /**
   * A tool a camera's settings open — routed, named by the palette and the
   * palette, but not in the bar or the drawer.
   */
  tool?: boolean;
}

export interface Workspace {
  key: WorkspaceKey;
  label: string;
  /** What the operator does here, in one sentence. */
  tagline: string;
  icon: JSX.Element;
  pages: readonly WorkspacePage[];
}

function page(
  key: WorkspacePageKey,
  tab: WorkspacePageTab,
  path: string,
  label: string,
  description: string,
  icon: JSX.Element,
  tool = false,
): WorkspacePage {
  return { key, workspace: 'monitoring', label, description, icon, tab, path, tool };
}

export const WORKSPACES: readonly Workspace[] = [
  {
    key: 'monitoring',
    label: 'Pages',
    tagline: 'Register cameras, watch them, and keep what they recorded.',
    icon: <MonitorHeartOutlinedIcon fontSize="small" />,
    pages: [
      // ★ THE THREE PAGES OF THE BAR, in the order the work runs: the CAMERA
      //   WORKSPACE, where a camera is registered through one pipeline (name,
      //   connection, position, DEM, calibration, frame, control points, lookup
      //   table); CAMERAS MONITORING, where it is watched; RECORDED VIDEOS, where
      //   what it recorded is kept.
      page(
        'cameras',
        'cameras',
        '/cameras',
        'Camera workspace',
        'Register each camera once — its connection, DEM, calibration, frame and lookup table — and every machine sees it.',
        <DnsOutlinedIcon fontSize="small" />,
      ),
      page(
        'live',
        'live',
        '/monitor',
        'Cameras Monitoring',
        'Every camera on a globe or a wall — open one to watch, measure, detect and capture from it.',
        <SensorsOutlinedIcon fontSize="small" />,
      ),
      page(
        'videos',
        'videos',
        '/videos',
        'Recorded videos',
        'What the cameras recorded, and the clips you uploaded — scrub to a moment and keep that frame as a photograph.',
        <MovieOutlinedIcon fontSize="small" />,
      ),
      // ★ THE TOOLS a camera's settings open — out of the bar, still addressed.
      page(
        'dem',
        'dem',
        '/dem',
        'DEM processing',
        'Crop and reproject an elevation model — the terrain every ray from a camera lands on.',
        <TerrainOutlinedIcon fontSize="small" />,
        true,
      ),
      page(
        'drift',
        'drift',
        '/drift',
        'Drift monitor',
        'Freeze a trusted view and be told the moment the camera moves or its optics change.',
        <RadarOutlinedIcon fontSize="small" />,
        true,
      ),
    ],
  },
];

/** Flat, in registry order — the palette walks it, tools included. */
export const WORKSPACE_PAGES: readonly WorkspacePage[] = WORKSPACES.flatMap((w) => w.pages);

/** The bar's pages: what the navbar and the drawer show. */
export const NAV_PAGES: readonly WorkspacePage[] = WORKSPACE_PAGES.filter((p) => !p.tool);

export function workspaceByKey(key: WorkspaceKey): Workspace {
  const found = WORKSPACES.find((w) => w.key === key);
  if (found === undefined) throw new Error(`Unknown workspace: ${key}`);
  return found;
}

export function pageByKey(key: WorkspacePageKey): WorkspacePage {
  const found = WORKSPACE_PAGES.find((p) => p.key === key);
  if (found === undefined) throw new Error(`Unknown workspace page: ${key}`);
  return found;
}

export function isWorkspacePageKey(key: string): key is WorkspacePageKey {
  return WORKSPACE_PAGES.some((p) => p.key === key);
}

/** The legacy `?tab=` value of a `/projects` location, or null. */
function tabOf(search: string): string | null {
  return new URLSearchParams(search).get('tab');
}

/** Where a legacy `/projects?tab=…` link now lands — the page, or null for the retired list. */
export function pageForLegacyTab(search: string): WorkspacePage | null {
  const tab = tabOf(search);
  if (tab === null) return null;
  // ★ Video detection is retired (2026-09-07): its old tab lands where a camera is watched.
  const wanted = tab === 'detect' ? 'live' : tab;
  return WORKSPACE_PAGES.find((p) => p.tab === wanted) ?? null;
}

/**
 * Which page a location IS — `null` for anything that is not one of the
 * five (Home, the dashboard, the guide, a frame's editor, a clip's own page).
 *
 * ★ A page's OWN address and everything under it is that page: the monitor and
 *   each camera's monitoring page are Cameras Monitoring; the camera workspace
 *   and each camera's settings and editor are the Camera workspace. The legacy
 *   `/projects?tab=…` spelling still resolves, for the forwarder and old tabs.
 */
/** The pages whose children are still that page: a camera's settings/editor, a camera's monitor page. */
const HOSTS: ReadonlySet<WorkspacePageKey> = new Set<WorkspacePageKey>(['cameras', 'live']);

export function pageForLocation(pathname: string, search = ''): WorkspacePage | null {
  for (const p of WORKSPACE_PAGES) {
    if (pathname === p.path) return p;
    // ★ Only the hosting pages claim what lives under them; a clip's own page
    //   (`/videos/:id`) is a record with a tab of its own, not Recorded videos.
    if (HOSTS.has(p.key) && pathname.startsWith(`${p.path}/`)) return p;
  }
  if (pathname === '/projects') return pageForLegacyTab(search);
  return null;
}

/**
 * The bar's lit tab for a location: the page itself, or the page a deeper record
 * belongs to — a clip is Recorded videos, a frame's editor and the tools a
 * camera's settings open are the Camera workspace.
 */
export function navPageForLocation(pathname: string, search = ''): WorkspacePage | null {
  const page = pageForLocation(pathname, search);
  if (page !== null) return page.tool ? pageByKey('cameras') : page;
  if (pathname.startsWith('/videos/') || /^\/projects\/[^/]+\/videos\//.test(pathname)) {
    return pageByKey('videos');
  }
  if (pathname.startsWith('/projects/')) return pageByKey('cameras');
  return null;
}

/**
 * Which workspace a location belongs to. A frame's editor and setup pages
 * (`/projects/:id/…`) and a clip's page belong to the one workspace there is.
 */
export function workspaceForLocation(pathname: string, search = ''): WorkspaceKey | null {
  const page = pageForLocation(pathname, search);
  if (page !== null) return page.workspace;
  if (pathname.startsWith('/projects/') || pathname.startsWith('/videos/')) return 'monitoring';
  return null;
}
