/**
 * The root layout route — `src/App.tsx` (§2.5), owned by IU-23.
 *
 * ★ DIVISION OF LABOUR, and it is a resolved conflict worth stating:
 *   CONTRACT.md §2.5 puts `QueryClientProvider · ThemeProvider · RouterProvider` in
 *   **`main.tsx`**, while 50-frontend §2.1 says `AppShell` owns `ThemeProvider`,
 *   `CssBaseline`, `QueryClientProvider` and the root `ErrorBoundary`. **The
 *   contract wins** (its precedence over the specialist docs is absolute, §0), and
 *   for a mechanical reason as well as a formal one: `RouterProvider` must sit
 *   below the providers, and `AppShell` renders *inside* the router — so an
 *   `AppShell` that owned `QueryClientProvider` would put the query client below the
 *   router that its own loaders and pages need.
 *
 *   So: `main.tsx` = providers. `App.tsx` = this file, the layout route. `AppShell`
 *   = the chrome (TopBar + children), which is exactly what its
 *   `AppShellProps { children }` signature describes. **`AppShell` must NOT mount
 *   `ThemeProvider`, `CssBaseline` or `QueryClientProvider` — they are already
 *   above it.**
 */

import { Suspense } from 'react';
import { Outlet } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';

import { CameraRegistrySync } from './components/monitor/CameraRegistrySync';
import { AppShell } from './components/shell/AppShell';
import { t } from './i18n';

/**
 * The fallback for a lazily-loaded page chunk.
 *
 * ★ Indeterminate, deliberately. We do not fake a determinate bar for a network
 *   fetch whose size we do not know — "a lying progress bar teaches users to
 *   distrust the whole UI" (§8.4), and that distrust is expensive in a tool whose
 *   entire output is a claim about accuracy.
 */
function RouteFallback(): JSX.Element {
  return (
    <Box
      sx={{ flex: 1, display: 'grid', placeItems: 'center', minHeight: 240 }}
      role="status"
      aria-label={t('Loading')}
    >
      <CircularProgress size={28} />
    </Box>
  );
}

export function App(): JSX.Element {
  return (
    <AppShell>
      <Suspense fallback={<RouteFallback />}>
        <Outlet />
        {/* ★ The camera registry is a cache of the server (1.3): fetched here once
            per app run and on focus, with the one-time offer to move a browser's
            pre-1.3 cameras across. */}
        <CameraRegistrySync />
      </Suspense>
    </AppShell>
  );
}

export default App;
