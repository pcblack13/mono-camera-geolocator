/**
 * The entry point — `src/main.tsx` (§2.5): `QueryClientProvider · ThemeProvider ·
 * RouterProvider`. Owned by IU-23.
 *
 * ★ Provider order is load-bearing, outermost → innermost:
 *     ColorModeProvider   — decides the mode; must be above ThemeProvider.
 *     ThemeProvider       — must be above CssBaseline (which reads the theme) and
 *                           above every MUI component.
 *     CssBaseline         — resets before anything paints.
 *     QueryClientProvider — must be above the router: pages and loaders use hooks.
 *     RouterProvider      — mounts App → AppShell → the page.
 *
 * ★ NOTHING here fetches. The query client is created by `api/queryClient.ts`
 *   (IU-24) with the §8.4 defaults — chiefly `retry: never on a 4xx` and
 *   `refetchOnWindowFocus: false`, because a surveyor tabbing back must not trigger
 *   a tile-fetch storm on cellular.
 */

import { lazy, StrictMode, Suspense, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { CacheProvider } from '@emotion/react';
import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider } from '@mui/material/styles';

// ★ Phase 1 of the redesign: one token set, both themes. Imported once, at the
//   root, so every surface — MUI or plain CSS — reads the same values.
import './theme/tokens.css';

import { useDirection, useLanguage } from './i18n';
import { useWorkspaceStore } from './store';

// ★ The workchain (open pages as tabs) was removed on 2026-09-07; its persisted
//   blob would otherwise sit in every existing browser for ever. Forget it once.
try {
  localStorage.removeItem('landexplorer.workchain');
} catch {
  // A browser that refuses storage has nothing to forget.
}

import { queryClient } from './api/queryClient';
import { router } from './router';
import { ColorModeProvider, getTheme, useColorMode } from './theme';
import { ltrCache, rtlCache } from './theme/styleCache';

/** ★ Default `false` (§9.11). Devtools are a dev affordance, not a prod payload. */
const DEVTOOLS_ENABLED = import.meta.env.VITE_ENABLE_DEVTOOLS === 'true';

/**
 * ★ Lazy so `@tanstack/react-query-devtools` — a devDependency — lands in its own
 *   chunk that a production session never fetches. A static import would put it in
 *   the entry bundle even with the flag off, and would break the build the moment
 *   devDependencies are pruned in `infra/docker/frontend.Dockerfile`.
 */
const ReactQueryDevtools = lazy(async () => {
  const mod = await import('@tanstack/react-query-devtools');
  return { default: mod.ReactQueryDevtools };
});

/**
 * Split out because `useColorMode` must be called BELOW `ColorModeProvider`, and
 * `ThemeProvider` needs its result.
 */
function ThemedApp(): JSX.Element {
  const { mode } = useColorMode();
  // ★ Arabic mirrors the chrome: the RTL theme tells MUI's own components to
  //   anchor right-to-left, and the RTL cache flips every physical style property
  //   as it is serialized (stylis-plugin-rtl). Geometry surfaces opt back out via
  //   `LtrIsland`. The document's `dir` attribute is stamped by the i18n module.
  const direction = useDirection();

  return (
    <CacheProvider value={direction === 'rtl' ? rtlCache : ltrCache}>
      <ThemeProvider theme={getTheme(mode, direction)}>
        <CssBaseline enableColorScheme />
        <QueryClientProvider client={queryClient}>
          {/* ★ Opt in early to v7's startTransition wrapping — silences the future-flag
              notice and is the behaviour the next major ships with. */}
          <RouterProvider router={router} future={{ v7_startTransition: true }} />
          {DEVTOOLS_ENABLED && (
            <Suspense fallback={null}>
              <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
            </Suspense>
          )}
        </QueryClientProvider>
      </ThemeProvider>
    </CacheProvider>
  );
}

/**
 * Re-mounts the app when the language changes.
 *
 * ★ WHY A REMOUNT. Translation is a plain `t()` call rather than a hook (see
 *   `i18n/index.ts`), so components do not individually subscribe to the language.
 *   Keying the tree makes every one of them re-render and re-read at once, which is
 *   what lets the switch reach ALL the app's text instead of only the components
 *   somebody remembered to wire. Switching is deliberate and rare; a remount is the
 *   honest price.
 *
 * ★ WHAT THE REMOUNT MUST NOT COST: the surveyor's work. A detection run in flight,
 *   its marks and its dials live in `lib/survivingState` slots that outlive the
 *   tree, and the run's unmount-stop waits a grace period the remount beats — so
 *   the language changes and the run carries on (2026-08-28).
 */
function LanguageBoundary(): JSX.Element {
  const language = useLanguage();
  // ★ The reduce-animation SETTING (⌘K → "Reduce animation"): tokens.css collapses
  //   every duration when the document carries this attribute. Stamped here, above
  //   the themed tree, so it also survives the language remount.
  const reduceMotion = useWorkspaceStore((s) => s.reduceMotion);
  useEffect(() => {
    document.documentElement.setAttribute('data-reduce-motion', String(reduceMotion));
  }, [reduceMotion]);
  return <ThemedApp key={language} />;
}

const container = document.getElementById('root');
if (!container) {
  // Cannot happen with our own index.html — and if it ever does, a stated cause
  // beats a blank page.
  throw new Error('Mono Camera Geolocator: #root is missing from index.html.');
}

createRoot(container).render(
  <StrictMode>
    <ColorModeProvider>
      <LanguageBoundary />
    </ColorModeProvider>
  </StrictMode>,
);
