/**
 * Typography — 50-frontend.md §9.4.
 *
 * ★ **JetBrains Mono for all numerics**, `font-variant-numeric: tabular-nums`: every
 *   coordinate, pixel value and confidence score renders in a tabular monospace.
 *   Non-tabular figures make a column of latitudes impossible to scan for anomalies,
 *   and scanning for anomalies is the surveyor's core review task (§8.2). This is
 *   the load-bearing half of §9.4 and it works with or without the font files.
 *
 * ★ `textTransform: none` globally. SHOUTING BUTTONS harm scannability and hurt
 *   localization.
 *
 * ★ NO CDN — the app must work with the NIC unplugged. See `public/fonts/README.md`
 *   for why the `.woff2` files are absent and how to activate them; the stacks below
 *   name the real families first and fall back to the system, so the app is
 *   correctly typeset either way.
 */

import type { TypographyOptions } from '@mui/material/styles/createTypography';

export const FONT_SANS = [
  'Inter',
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI"',
  'Roboto',
  '"Helvetica Neue"',
  'Arial',
  '"Noto Sans"',
  'sans-serif',
].join(', ');

export const FONT_MONO = [
  '"JetBrains Mono"',
  'ui-monospace',
  'SFMono-Regular',
  '"SF Mono"',
  'Menlo',
  'Consolas',
  '"Liberation Mono"',
  'monospace',
].join(', ');

/**
 * ★ ACTIVE — the variable `.woff2` files live in `public/fonts/` (Inter and
 *   JetBrains Mono, both SIL OFL), served from our own origin so the app stays
 *   fully offline. `font-display: swap` keeps text visible during load: a surveyor
 *   must never see a blank coordinate.
 *
 * See `public/fonts/README.md`.
 */
export const FONT_FACE_CSS = `
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('/fonts/inter-variable.woff2') format('woff2-variations');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 100 800;
  font-display: swap;
  src: url('/fonts/jetbrains-mono-variable.woff2') format('woff2-variations');
}
`;

/**
 * ★ The custom `mono` variant — **all coordinates & scores** (§9.4).
 *   Declared here and augmented onto MUI's `Typography` in `index.ts`, so
 *   `<Typography variant="mono">` is a real, type-checked variant rather than an
 *   `sx` incantation every table cell has to repeat correctly.
 */
export const monoVariant = {
  fontFamily: FONT_MONO,
  fontSize: '0.8125rem', // 13px
  lineHeight: '18px',
  fontWeight: 450,
  fontVariantNumeric: 'tabular-nums',
  letterSpacing: 0,
} as const;

export const typography: TypographyOptions = {
  fontFamily: FONT_SANS,
  fontSize: 14,
  htmlFontSize: 16,

  h1: { fontSize: '1.75rem', lineHeight: '34px', fontWeight: 600, letterSpacing: '-0.02em' },
  h2: { fontSize: '1.375rem', lineHeight: '28px', fontWeight: 600, letterSpacing: '-0.01em' },
  h3: { fontSize: '1.125rem', lineHeight: '24px', fontWeight: 600, letterSpacing: 0 },
  h4: { fontSize: '1rem', lineHeight: '22px', fontWeight: 600 },
  h5: { fontSize: '0.9375rem', lineHeight: '20px', fontWeight: 600 },
  h6: { fontSize: '0.875rem', lineHeight: '20px', fontWeight: 600 },

  subtitle1: { fontSize: '0.9375rem', lineHeight: '20px', fontWeight: 600 },
  subtitle2: {
    fontSize: '0.8125rem',
    lineHeight: '18px',
    fontWeight: 600,
    letterSpacing: '0.02em',
  },

  body1: { fontSize: '0.9375rem', lineHeight: '22px', fontWeight: 400 },
  body2: { fontSize: '0.8125rem', lineHeight: '20px', fontWeight: 400 },

  caption: { fontSize: '0.75rem', lineHeight: '16px', fontWeight: 400 },
  overline: {
    fontSize: '0.6875rem',
    lineHeight: '16px',
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },

  button: {
    fontSize: '0.875rem',
    lineHeight: '20px',
    fontWeight: 600,
    letterSpacing: '0.01em',
    textTransform: 'none',
  },

  mono: monoVariant,
};
