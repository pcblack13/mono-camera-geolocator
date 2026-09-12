/**
 * `shell/pageNav.ts` — where does "back" go, and what is this page called?
 *
 * ★ BACK IS STRUCTURAL "UP", NOT BROWSER HISTORY. `navigate(-1)` replays however the
 *   surveyor happened to arrive — after a deep link it leaves the app entirely, and
 *   after a lateral hop (workspace → settings → workspace) it bounces between siblings.
 *   The browser already has a history button; duplicating it in the toolbar adds a
 *   second one that behaves identically and surprises identically. What a page header
 *   owes the user is the PARENT: editor → its project → the project list → home.
 *   Same place every time, regardless of how they got here.
 *
 * ★ THE QUERY IS PART OF THE NAME. `/projects?tab=dem` IS the DEM processing page,
 *   so `resolvePageNav` takes the search string too and names the page from the
 *   workspace registry — one vocabulary for the tab strip, the back control and the
 *   palette.
 *
 * Pure data → data; exported for tests.
 */

import { matchPath } from 'react-router-dom';

import {
  cameraRefForParam,
  cameraRefForProject,
  cameraSettingsPath,
} from '../../lib/cameras/projectCamera';

import { pageForLocation } from './workspaces';

export interface PageNav {
  /** Human name of the current page, for the header. */
  title: string;
  /** Where "back" navigates, or null on the root (no up from the home page). */
  parent: string | null;
  /** Name of the parent, for the button's tooltip/aria-label. */
  parentTitle: string | null;
  /** True when this page hosts the annotation draft — the one savable thing. */
  hasDraft: boolean;
}

interface RouteRule {
  pattern: string;
  title: string;
  parent: ((params: Record<string, string | undefined>) => string) | null;
  parentTitle: string | null;
  hasDraft?: boolean;
}

/**
 * ★ ORDER MATTERS: first match wins, so the deepest patterns come first. One entry per
 *   route in `router.tsx` — adding a page there means adding a line here (the same
 *   one-line contract `workspaces.tsx` documents for the registry's pages).
 */
// ★ VOCABULARY: the projects LIST is "Projects" (a page of the Locator Workspace);
//   the three-pane annotation screen is the "Editor", so the two never share a
//   name. "Workspace" alone now means one of the two workspaces in the navbar.
//   URL segments keep the original spelling; only what the user reads changed.
const RULES: readonly RouteRule[] = [
  // ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04): a frame's editor and setup go
  //   up to the camera (resolved below); the project page and project settings
  //   no longer exist.
  {
    pattern: '/projects/:projectId/images/:imageId/setup',
    title: 'Image setup',
    parent: () => '/cameras',
    parentTitle: 'Camera workspace',
  },
  {
    pattern: '/projects/:projectId/images/:imageId',
    title: 'Editor',
    parent: () => '/cameras',
    parentTitle: 'Camera workspace',
    hasDraft: true,
  },
  {
    pattern: '/projects/:projectId/videos/:videoId',
    title: 'Video',
    parent: () => '/videos',
    parentTitle: 'Recorded videos',
  },
  {
    // A camera's recording, watched in the app — up to Recorded videos (2026-09-07).
    pattern: '/videos/recordings/:folder',
    title: 'Recording',
    parent: () => '/videos',
    parentTitle: 'Recorded videos',
  },
  {
    // A library-only clip goes up to Recorded videos, its only home.
    pattern: '/videos/:videoId',
    title: 'Video',
    parent: () => '/videos',
    parentTitle: 'Recorded videos',
  },
  // ★ `/projects?tab=…` is the legacy spelling of the tool pages; the registry
  //   names it, and the forwarder sends it on. Bare `/projects` is the retired list.
  { pattern: '/projects', title: 'Camera workspace', parent: () => '/', parentTitle: 'Home' },
  // ★ The monitor: the globe, and a camera's page under it.
  {
    pattern: '/monitor/cameras/:id',
    title: 'Camera',
    parent: () => '/monitor',
    parentTitle: 'Cameras Monitoring',
  },
  { pattern: '/monitor', title: 'Cameras Monitoring', parent: () => '/', parentTitle: 'Home' },
  // ★ The camera workspace: the list, a new camera's pipeline and its editor, a
  //   registered camera's settings and its editor. Every child goes up one step.
  {
    pattern: '/cameras/new/editor',
    title: 'Editor',
    parent: () => '/cameras/new',
    parentTitle: 'New camera',
    hasDraft: true,
  },
  {
    pattern: '/cameras/new',
    title: 'New camera',
    parent: () => '/cameras',
    parentTitle: 'Camera workspace',
  },
  {
    pattern: '/cameras/:id/editor',
    title: 'Editor',
    parent: (p) => `/cameras/${p.id}/settings`,
    parentTitle: 'Camera settings',
    hasDraft: true,
  },
  {
    pattern: '/cameras/:id/settings',
    title: 'Camera settings',
    parent: () => '/cameras',
    parentTitle: 'Camera workspace',
  },
  { pattern: '/cameras', title: 'Camera workspace', parent: () => '/', parentTitle: 'Home' },
  // ★ Recorded videos, and the tools a camera's settings open — each at its own address.
  { pattern: '/dem', title: 'DEM processing', parent: () => '/', parentTitle: 'Home' },
  { pattern: '/videos', title: 'Recorded videos', parent: () => '/', parentTitle: 'Home' },
  { pattern: '/drift', title: 'Drift monitor', parent: () => '/', parentTitle: 'Home' },
  { pattern: '/dashboard', title: 'Dashboard', parent: () => '/', parentTitle: 'Home' },
  { pattern: '/guide', title: 'Workflow guide', parent: () => '/', parentTitle: 'Home' },
  { pattern: '/', title: 'Home', parent: null, parentTitle: null },
];

export function resolvePageNav(pathname: string, search = ''): PageNav {
  for (const rule of RULES) {
    const match = matchPath({ path: rule.pattern, end: true }, pathname);
    if (match) {
      // ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04): an editor opened on a camera's
      //   frame — named by `?camera=` or by its backing project — goes UP to that
      //   camera's settings, not to a project page that no longer exists for it.
      if (
        rule.pattern === '/projects/:projectId/images/:imageId' ||
        rule.pattern === '/projects/:projectId/images/:imageId/setup'
      ) {
        const ref =
          cameraRefForParam(new URLSearchParams(search).get('camera')) ??
          cameraRefForProject(match.params.projectId);
        if (ref !== null) {
          return {
            title: rule.title,
            parent: cameraSettingsPath(ref),
            parentTitle: ref.kind === 'draft' ? 'New camera' : 'Camera settings',
            hasDraft: rule.hasDraft ?? false,
          };
        }
      }
      // The workspace pages share a pathname; the registry names them — but only
      // at the page's OWN address. A page UNDER one (a camera's monitor page, a
      // camera's settings) keeps the specific name its rule gives it.
      const workspacePage = pageForLocation(pathname, search);
      const atPageRoot =
        workspacePage !== null && (pathname === '/projects' || pathname === workspacePage.path);
      return {
        title: atPageRoot ? workspacePage.label : rule.title,
        parent: rule.parent ? rule.parent(match.params) : null,
        parentTitle: rule.parentTitle,
        hasDraft: rule.hasDraft ?? false,
      };
    }
  }
  // Unknown route (the 404 page): offer the way home rather than nothing.
  return { title: 'Not found', parent: '/', parentTitle: 'Home', hasDraft: false };
}
