/**
 * `shell/navItems.tsx` — THE SHELL'S OWN DESTINATIONS.
 *
 * ★ TWO LISTS, ONE VOCABULARY. This file holds the pages that belong to the SHELL
 *   — Home, the dashboard, the workflow guide. The pages that belong to the WORK
 *   live in `workspaces.tsx`, grouped into the Locator and Monitoring workspaces,
 *   and every navigation surface (navbar tabs, icon rail, drawer, palette,
 *   palette) renders from those two lists and nothing else. Adding a shell page
 *   is one entry here plus its route in `router.tsx`; adding a work page is one
 *   entry there plus its `?tab=` branch in `ProjectsPage`.
 *
 * ★ It lives in its own module, not inside `AppShell`, purely to keep the import
 *   graph acyclic: `AppShell → TopBar → MainNav → navItems`. `AppShell` re-exports
 *   {@link NAV_ITEMS} so the shell remains the documented entry point.
 *
 * ★ `disabled` exists for a page that is routed but not yet usable (SCOPE.md §4
 *   rule 4: a deferred feature is shown, disabled, with an honest reason — never
 *   hidden, and never a control that silently does nothing).
 */

import type { JSX, ReactNode } from 'react';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import HomeOutlinedIcon from '@mui/icons-material/HomeOutlined';
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined';

export interface NavItem {
  label: string;
  /** An absolute route path, matching `router.tsx`. */
  path: string;
  icon: ReactNode;
  /** Rendered but not navigable, with `title` as the honest reason. */
  disabled?: boolean;
  /** Why it is disabled, or a one-line description for assistive tech. */
  title?: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { label: 'Home', path: '/', icon: <HomeOutlinedIcon fontSize="small" /> },
  { label: 'Dashboard', path: '/dashboard', icon: <DashboardOutlinedIcon fontSize="small" /> },
  // ★ The workflow guide — the whole method as a board. On desktop the icon rail
  //   pins it at its foot; this entry is the drawer's (below-md) way in.
  { label: 'Workflow guide', path: '/guide', icon: <MenuBookOutlinedIcon fontSize="small" /> },
];

/**
 * Which shell item owns a pathname — `null` for the work pages, which the
 * workspace registry owns (`pageForLocation`).
 *
 * ★ `/` is matched EXACTLY — a prefix match would light "Home" up on every
 *   route in the app. Everything else matches on a path SEGMENT boundary.
 */
export function activeNavPath(pathname: string): string | null {
  const match = NAV_ITEMS.filter((item) => !item.disabled).find((item) =>
    item.path === '/'
      ? pathname === '/'
      : pathname === item.path || pathname.startsWith(`${item.path}/`),
  );
  return match ? match.path : null;
}

/** Typed so `NAV_ITEMS.map` in a `.tsx` file stays inference-friendly. */
export type NavItemRenderer = (item: NavItem, active: boolean) => JSX.Element;
