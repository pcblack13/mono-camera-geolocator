/**
 * The MUI theme — `src/theme/` (§2.5), owned by IU-23.
 *
 * Assembles tokens + palette + typography + component overrides into the light and
 * dark themes, and augments MUI's types so `theme.palette.confidence.high`,
 * `theme.palette.surfaces.canvasBackdrop` and `<Typography variant="mono">` are all
 * real, type-checked members rather than casts.
 */

import type { CSSProperties } from 'react';
import { createTheme, responsiveFontSizes } from '@mui/material/styles';
import type { Theme } from '@mui/material/styles';

import { components } from './components';
import { palettes } from './palette';
import { tokens } from './tokens';
import { typography } from './typography';
import type { ThemeMode } from './confidence';
import type { AppSurfaces } from './palette';

// ─────────────────────────────────────────────────────────────────────────────
// MUI module augmentation
// ─────────────────────────────────────────────────────────────────────────────

/** ★ Exposed on the theme so `sx` can reach the scale without importing (§9.5).
 *  The functions in `confidence.ts` remain the single source of truth for the
 *  THRESHOLDS; this is only the colour lookup. */
export interface ConfidencePalette {
  high: string;
  moderate: string;
  low: string;
  unreliable: string;
  /** ★ The `source === 'manual'` provenance accent — NOT a band. See `confidence.ts`. */
  manual: string;
  /** ★ Absence of a result. Grey, never green. */
  none: string;
  /** The contrasting outline every marker on imagery carries. */
  outline: string;
}

declare module '@mui/material/styles' {
  interface Palette {
    confidence: ConfidencePalette;
    surfaces: AppSurfaces;
  }
  interface PaletteOptions {
    confidence?: ConfidencePalette;
    surfaces?: AppSurfaces;
  }

  interface Theme {
    tokens: typeof tokens;
  }
  interface ThemeOptions {
    tokens?: typeof tokens;
  }

  interface TypographyVariants {
    mono: CSSProperties;
  }
  interface TypographyVariantsOptions {
    mono?: CSSProperties;
  }
}

declare module '@mui/material/Typography' {
  interface TypographyPropsVariantOverrides {
    mono: true;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Theme factory
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ A SOFT SHADOW RAMP replacing MUI's default. The defaults are dense, dark and
 *   short — they read as 2014. These are layered, low-alpha and slightly larger, so
 *   elevation reads as *air* rather than ink; the alpha is a touch higher in dark
 *   mode where shadows must fight an already-dark ground.
 */
function softShadows(mode: ThemeMode): Theme['shadows'] {
  const a = mode === 'dark' ? 0.5 : 0.1;
  const lift = (n: number): string =>
    [
      `0 ${Math.max(1, Math.round(n / 2))}px ${n * 2}px -${Math.round(n / 2)}px rgba(8,12,20,${a + 0.06})`,
      `0 ${n}px ${n * 3}px -${n}px rgba(8,12,20,${a})`,
    ].join(', ');
  const ramp = ['none'];
  for (let i = 1; i <= 24; i += 1) ramp.push(lift(Math.ceil(i / 2) + 1));
  return ramp as Theme['shadows'];
}

function build(mode: ThemeMode, direction: 'ltr' | 'rtl' = 'ltr'): Theme {
  const theme = createTheme({
    // ★ Arabic is right-to-left, and MUI needs telling: `direction` is what makes
    //   its own components mirror (tabs, sliders, drawers, menu anchoring). The
    //   document's `dir` attribute — set by the i18n module — handles the rest.
    direction,
    palette: palettes[mode],
    typography,
    spacing: tokens.spacing,
    shape: { borderRadius: tokens.radius.md },
    shadows: softShadows(mode),
    zIndex: {
      appBar: tokens.zIndex.appBar,
      drawer: tokens.zIndex.drawer,
      modal: tokens.zIndex.dialog,
      snackbar: tokens.zIndex.snackbar,
      tooltip: tokens.zIndex.tooltip,
    },
    transitions: {
      duration: {
        shortest: tokens.duration.fast,
        shorter: tokens.duration.fast,
        short: tokens.duration.normal,
        standard: tokens.duration.normal,
        complex: tokens.duration.slow,
        enteringScreen: tokens.duration.normal,
        leavingScreen: tokens.duration.fast,
      },
      easing: {
        easeInOut: tokens.easing.standard,
        easeOut: tokens.easing.decel,
        easeIn: tokens.easing.standard,
        sharp: tokens.easing.standard,
      },
    },
    // ★ Exact MUI breakpoints — 50-frontend §1.5's responsive reflow keys off these.
    breakpoints: {
      values: { xs: 0, sm: 600, md: 900, lg: 1200, xl: 1536 },
    },
    tokens,
  });

  return responsiveFontSizes(createTheme(theme, { components: components() }), {
    // The scale is already tuned per-variant (§9.4); only the headings need to
    // breathe on small screens, and the numerics must NEVER be rescaled — a
    // coordinate column that changes size between breakpoints stops being scannable.
    variants: ['h1', 'h2', 'h3'],
    // ★ disableAlign is REQUIRED here: our typography uses px line heights
    // (typography.ts), and responsiveFontSizes' 4px-baseline-grid alignment THROWS at
    // runtime on non-unitless line heights ("Unsupported non-unitless line height with
    // grid alignment") — which crashes getTheme() before React can mount, i.e. a blank
    // page. The px values are already hand-snapped to the grid, so alignment is
    // redundant; disabling it keeps every tuned value and only skips the re-snap.
    disableAlign: true,
  });
}

export const lightTheme = build('light');
export const darkTheme = build('dark');

export const themes: Record<ThemeMode, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

/** The RTL pair, built lazily: an English-only session never pays for them. */
const rtlThemes: Partial<Record<ThemeMode, Theme>> = {};

export function getTheme(mode: ThemeMode, direction: 'ltr' | 'rtl' = 'ltr'): Theme {
  if (direction === 'ltr') return themes[mode];
  // ★ Cached per mode, not rebuilt per render: `createTheme` is not cheap, and a
  //   fresh theme object on every render would remount every styled subtree.
  rtlThemes[mode] ??= build(mode, 'rtl');
  return rtlThemes[mode]!;
}

// ─────────────────────────────────────────────────────────────────────────────
// Re-exports — the theme's public surface
// ─────────────────────────────────────────────────────────────────────────────

export { tokens } from './tokens';
export type { Tokens } from './tokens';

export { grey, surfaces } from './palette';
export type { AppSurfaces } from './palette';

export { FONT_MONO, FONT_SANS } from './typography';

export {
  CONFIDENCE_BANDS,
  CONFIDENCE_COLORS,
  CONFIDENCE_ENCODING,
  CONFIDENCE_THRESHOLDS,
  HEATMAP_OPACITY,
  MANUAL_SOURCE_COLOR,
  MARKER_OUTLINE,
  MIN_CONFIDENCE,
  NO_RESULT_COLOR,
  SURVEYOR_CONFIDENCE_SCALE,
  confidenceBand,
  confidenceColor,
  confidenceLabel,
  confidenceMeaning,
  gcpConfidenceBand,
  heatmapColor,
  heatmapCssColor,
  surveyorConfidenceBand,
  surveyorConfidenceToNumeric,
  surveyorStep,
} from './confidence';
export type { ConfidenceEncoding, SurveyorConfidenceStep, ThemeMode } from './confidence';

export { ColorModeProvider, useColorMode } from './ColorModeProvider';
