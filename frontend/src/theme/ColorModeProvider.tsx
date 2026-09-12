/**
 * Light/dark mode — the provider `main.tsx` wraps the app in.
 *
 * ★ WHY THIS IS A CONTEXT AND NOT A ZUSTAND STORE. L7 says browser-only state goes
 *   to Zustand, and colour mode qualifies — but §8.5's eight stores are enumerated
 *   and owned by IU-25, and none of them holds it (`workspaceStore` holds
 *   `coordinateFormat`, not the theme). Adding a ninth store would mean writing in
 *   another unit's directory. A context in `theme/` keeps the seam clean and is the
 *   right shape anyway: the value is read by `ThemeProvider` at the very root, above
 *   the router, where a store subscription buys nothing.
 *
 * ★ WHY DARK IS THE DEFAULT (§9.3). "A bright chrome surrounding a photograph biases
 *   perception of that photograph's exposure — the surveyor is judging the image,
 *   and the frame must not lie to their eye. This is the same reason image editors
 *   are dark." `system` is the default *preference*, which resolves to whatever the
 *   OS says; `dark` is what fullscreen/compare force regardless.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import useMediaQuery from '@mui/material/useMediaQuery';

import type { ThemeMode } from './confidence';

export type ColorModePreference = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'landexplorer.color-mode';

export interface ColorModeContextValue {
  /** What the user chose. */
  preference: ColorModePreference;
  /** What that resolves to right now — this is what `getTheme()` takes. */
  mode: ThemeMode;
  setPreference: (p: ColorModePreference) => void;
  /** Cycles light → dark → system. */
  toggle: () => void;
}

const ColorModeContext = createContext<ColorModeContextValue | null>(null);

function readStored(): ColorModePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  } catch {
    // ★ localStorage throws in private mode and in sandboxed iframes. A theme
    //   preference is not worth crashing the app for (L11: degrade, never traceback).
  }
  return 'system';
}

export function ColorModeProvider({ children }: { children: ReactNode }): JSX.Element {
  const [preference, setPreferenceState] = useState<ColorModePreference>(readStored);
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)');

  const setPreference = useCallback((p: ColorModePreference) => {
    setPreferenceState(p);
    try {
      window.localStorage.setItem(STORAGE_KEY, p);
    } catch {
      // See readStored().
    }
  }, []);

  const toggle = useCallback(() => {
    setPreferenceState((prev) => {
      const next: ColorModePreference =
        prev === 'light' ? 'dark' : prev === 'dark' ? 'system' : 'light';
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // See readStored().
      }
      return next;
    });
  }, []);

  const mode: ThemeMode = preference === 'system' ? (prefersDark ? 'dark' : 'light') : preference;

  // Keeps form controls, scrollbars and the address bar in step with the app.
  useEffect(() => {
    document.documentElement.style.colorScheme = mode;
  }, [mode]);
  // ★ THE TOKENS SWITCH ON THIS ATTRIBUTE. `tokens.css` declares the light set
  //   under `[data-theme='light']`, so without stamping it the CSS variables
  //   would stay dark while MUI went light — two half-themes at once.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
  }, [mode]);

  const value = useMemo<ColorModeContextValue>(
    () => ({ preference, mode, setPreference, toggle }),
    [preference, mode, setPreference, toggle],
  );

  return <ColorModeContext.Provider value={value}>{children}</ColorModeContext.Provider>;
}

export function useColorMode(): ColorModeContextValue {
  const ctx = useContext(ColorModeContext);
  if (!ctx) {
    throw new Error('useColorMode must be used within a <ColorModeProvider>.');
  }
  return ctx;
}
