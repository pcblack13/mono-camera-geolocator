/**
 * `shell/AppShell.tsx` — the top-level chrome (50-frontend §2.1).
 *
 * ★ DIVISION OF LABOUR (resolved in `App.tsx`): `main.tsx` owns `ThemeProvider`,
 *   `CssBaseline`, `QueryClientProvider` and `RouterProvider` — they sit ABOVE the
 *   router, and `AppShell` renders INSIDE it. **AppShell must NOT mount those.** It
 *   owns the chrome that belongs below the router: the root `ErrorBoundary`, the
 *   toast channel, the global live-region announcer, `TopBar`, and the global keymap.
 *
 * ★ `100dvh`, not `vh` (§2.1): mobile Safari's collapsing URL bar makes `vh` wrong
 *   exactly when a surveyor is in a field. `overflow: hidden` — the page body never
 *   scrolls; each region manages its own overflow (§1.1).
 *
 * ★ Deliberately thin. It composes providers and the bar; it renders no data.
 */

import { useEffect, type JSX, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useAnnotationStore } from '../../store/annotationStore';
import { useToolStore } from '../../store/toolStore';
import { installDisplayZoomShortcuts } from '../../lib/displayZoom';
import { ErrorBoundary } from '../common/ErrorBoundary';
import { LiveAnnounceProvider } from '../common/LiveRegion';
import { NotificationsProvider } from '../common/Notifications';
import { PageNavBar } from './PageNavBar';
import { TopBar } from './TopBar';
import { t } from '../../i18n';
import { cameraRefForParam, type CameraRef } from '../../lib/cameras/projectCamera';
import { useCameraDraftStore } from '../../store/cameraDraftStore';
import { useCameraRegistryStore } from '../../store/cameraRegistryStore';

/**
 * ★ THE NAV IS ONE ARRAY. Re-exported here because `AppShell` is the chrome's
 *   documented entry point, but defined in `./navItems` so the import graph stays
 *   acyclic (`AppShell → TopBar → MainNav → navItems`). **Adding a page is one line
 *   in `NAV_ITEMS` plus its route in `router.tsx`.**
 */
export { NAV_ITEMS, activeNavPath, type NavItem } from './navItems';

export interface AppShellProps {
  children: ReactNode;
}

/** The current project id, parsed from the URL — the screen's identity (router.tsx). */
/**
 * ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04): the bar names the camera the
 *   current page belongs to — its settings, its editor, its monitoring page, or
 *   a frame inside its backing project — and the draft on `/cameras/new`.
 */
function useRouteCameraRef(): CameraRef | null {
  const { pathname, search } = useLocation();
  const cameras = useCameraRegistryStore((s) => s.cameras);
  const draftName = useCameraDraftStore((s) => s.draft.name);
  const draftProject = useCameraDraftStore((s) => s.draft.project_id);
  if (pathname === '/cameras/new' || pathname.startsWith('/cameras/new/')) {
    return { kind: 'draft', name: draftName.trim() };
  }
  const cam = pathname.match(/^\/(?:cameras|monitor\/cameras)\/([^/]+)/);
  if (cam) {
    const found = cameras.find((c) => c.id === cam[1]);
    return found ? { kind: 'camera', id: found.id, name: found.name } : null;
  }
  const project = pathname.match(/^\/projects\/([^/]+)/);
  if (project) {
    const byParam = cameraRefForParam(new URLSearchParams(search).get('camera'));
    if (byParam !== null) return byParam;
    const owner = cameras.find((c) => c.project_id === project[1]);
    if (owner) return { kind: 'camera', id: owner.id, name: owner.name };
    if (draftProject === project[1]) return { kind: 'draft', name: draftName.trim() };
  }
  return null;
}

/**
 * The global keymap (§8.9). Registered ONCE. Shortcuts are suppressed while focus is
 * in a text input, and `⌘`/`⌃` is treated equivalently. Store actions are read via
 * `getState()` so this effect never re-subscribes.
 */
function useGlobalKeymap(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      // ★ A keydown can target `window`/`document` (synthetic dispatch, some
      //   embedders); those have no tagName/getAttribute — guard, don't throw.
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable ||
          target.getAttribute('role') === 'textbox')
      ) {
        return;
      }

      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) useAnnotationStore.getState().redo();
        else useAnnotationStore.getState().undo();
        return;
      }
      if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        useAnnotationStore.getState().redo();
        return;
      }
      // Leave every other modifier combination to the browser / focused pane.
      if (mod) return;

      switch (e.key.toLowerCase()) {
        case 'v':
          useToolStore.getState().setTool('cursor');
          break;
        // ★ P/G/L (point/polygon/polyline) removed with their toolbar buttons —
        //   a shortcut into an invisible mode would be a haunting, not a feature.
        // ★ C (compare) removed with the compare view itself (1.2.6) — same rule:
        //   a shortcut that toggles something no longer in the product is a ghost.
        default:
          return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

function RootErrorFallback(error: Error, reset: () => void): JSX.Element {
  return (
    <Box role="alert" sx={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', p: 3 }}>
      <Stack spacing={2} sx={{ maxWidth: 520, textAlign: 'center' }}>
        <Typography variant="h5">{t('Something went wrong')}</Typography>
        <Typography variant="body2" color="text.secondary">
          {error.message || t('An unexpected error occurred.')}
        </Typography>
        <Box>
          <Button variant="contained" onClick={reset} sx={{ mr: 1 }}>
            {t('Try again')}
          </Button>
          <Button variant="text" onClick={() => window.location.assign('/projects')}>
            {t('Back to projects')}
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}

export function AppShell({ children }: AppShellProps): JSX.Element {
  const cameraRef = useRouteCameraRef();
  useGlobalKeymap();
  // ★ Display size from the keyboard (Ctrl + / − / 0) — desktop shell only.
  useEffect(() => installDisplayZoomShortcuts(), []);

  return (
    <ErrorBoundary
      fallback={RootErrorFallback}
      onError={(error) => {
        // eslint-disable-next-line no-console
        console.error('AppShell root boundary caught:', error);
      }}
    >
      <NotificationsProvider>
        <LiveAnnounceProvider>
          <Box
            sx={{
              height: '100dvh',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              bgcolor: 'background.default',
            }}
          >
            <TopBar cameraRef={cameraRef} />
            {/* ★ ONE navbar, no side rail. Under it the slim page bar (the way
                back + the editor's Save — see PageNavBar)
                and, under that, the page. */}
            <PageNavBar />
            <Box
              component="main"
              sx={{
                flex: 1,
                minWidth: 0,
                minHeight: 0,
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {children}
            </Box>
          </Box>
        </LiveAnnounceProvider>
      </NotificationsProvider>
    </ErrorBoundary>
  );
}

export default AppShell;
