/**
 * Palette — 50-frontend.md §9.3, adopted verbatim.
 *
 * ★ Neutrals are a slightly blue-COOL grey ramp, because they sit adjacent to
 *   satellite imagery which is dominated by warm earth tones; a cool chrome recedes
 *   and lets the imagery come forward.
 *
 * ★ `primary` is deliberately NOT green. Green is reserved for confidence and must
 *   be earned (§8.6.1).
 *
 * ★ The canvas backdrop is deliberately DARKER than `background.default` in both
 *   modes, so the image's extent is unambiguous and edge annotations are legible
 *   against the void.
 */

import type { PaletteOptions } from '@mui/material/styles';

import {
  CONFIDENCE_COLORS,
  MANUAL_SOURCE_COLOR,
  MARKER_OUTLINE,
  NO_RESULT_COLOR,
} from './confidence';
import type { ThemeMode } from './confidence';

/** The cool grey ramp. */
export const grey = {
  50: '#F5F6F7',
  100: '#EBEDEF',
  200: '#E0E3E7',
  300: '#CBD0D7',
  400: '#9AA3B0',
  500: '#5F6672',
  600: '#4A515C',
  700: '#3A414B',
  800: '#2A3038',
  900: '#1A1D21',
} as const;

/** Non-MUI surfaces this app needs and MUI has no slot for. */
export interface AppSurfaces {
  /** ★ Darker than `background.default`. The void the image sits in. */
  canvasBackdrop: string;
  /** The dock / inspector chrome. */
  panel: string;
  /** The satellite pane's loading/no-coverage hatch. */
  hatch: string;
}

export const surfaces: Record<ThemeMode, AppSurfaces> = {
  light: {
    canvasBackdrop: '#E8EAED',
    panel: '#FFFFFF',
    hatch: '#CBD0D7',
  },
  dark: {
    canvasBackdrop: '#06090D',
    panel: '#121821',
    hatch: '#2B3644',
  },
};

/** ★ `theme.palette.confidence[band]` — reachable from `sx` without an import (§9.5). */
function confidencePalette(mode: ThemeMode) {
  return {
    high: CONFIDENCE_COLORS.high[mode],
    moderate: CONFIDENCE_COLORS.moderate[mode],
    low: CONFIDENCE_COLORS.low[mode],
    unreliable: CONFIDENCE_COLORS.unreliable[mode],
    /** ★ The provenance accent, not a band. See `confidence.ts`. */
    manual: MANUAL_SOURCE_COLOR[mode],
    /** ★ Absence of a result. Grey, never green. */
    none: NO_RESULT_COLOR[mode],
    /** The contrasting marker outline that makes the contrast claim true on imagery. */
    outline: MARKER_OUTLINE[mode],
  };
}

export const lightPalette: PaletteOptions = {
  mode: 'light',
  // ★ THE SAME ACCENT AS THE TOKEN SET (`tokens.css` --accent, light): instrument
  //   teal, ≥4.5:1 on white. It used to be an indigo that only MUI knew about, so in
  //   light mode the chrome built on tokens was teal while buttons, step badges and
  //   icons built on `primary` were indigo — two products on one screen. Green
  //   remains reserved for confidence (§8.6.1).
  primary: { main: '#0E7C8C', light: '#2A98A8', dark: '#0B6674', contrastText: '#FFFFFF' },
  secondary: { main: '#64748B', contrastText: '#FFFFFF' },
  // ★ Retuned from the MUI defaults to hit 4.5:1 on both surfaces (§9.3).
  error: { main: '#B91C1C', contrastText: '#FFFFFF' },
  warning: { main: '#B45309', contrastText: '#FFFFFF' },
  // Distinct from the accent, so an info message never reads as a control.
  info: { main: '#1D4ED8', contrastText: '#FFFFFF' },
  success: { main: '#1B7F4B', contrastText: '#FFFFFF' },
  background: { default: '#F4F6F8', paper: '#FFFFFF' },
  text: { primary: '#101720', secondary: '#4A5666', disabled: '#6B7787' },
  divider: '#DFE4EA',
  grey,
  confidence: confidencePalette('light'),
  surfaces: surfaces.light,
};

export const darkPalette: PaletteOptions = {
  mode: 'dark',
  // ★ The same indigo family lifted for dark surfaces; light/dark stops give
  //   hover/active states real steps instead of MUI's auto-derived approximations.
  // ★ INSTRUMENT CYAN, one accent for every interactive state. It is the only
  //   saturated colour in the chrome, so "interactive" reads at a glance without
  //   competing with the accuracy bands — which own green/amber/orange/red.
  primary: { main: '#35C8D8', light: '#55D8E6', dark: '#23A9B8', contrastText: '#04141A' },
  secondary: { main: '#94A3B8', contrastText: '#0A0C0F' },
  error: { main: '#F87171', contrastText: '#0A0C0F' },
  warning: { main: '#FBBF24', contrastText: '#0A0C0F' },
  info: { main: '#38BDF8', contrastText: '#0A0C0F' },
  success: { main: '#4ADE80', contrastText: '#0A0C0F' },
  background: { default: '#0B0F14', paper: '#121821' },
  text: { primary: '#E6EDF5', secondary: '#93A1B3', disabled: '#64748B' },
  divider: '#1E2731',
  grey,
  confidence: confidencePalette('dark'),
  surfaces: surfaces.dark,
};

export const palettes: Record<ThemeMode, PaletteOptions> = {
  light: lightPalette,
  dark: darkPalette,
};
