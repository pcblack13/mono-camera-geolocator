/**
 * Component overrides — 50-frontend.md §9.6.
 *
 * ★ Several of these are ACCESSIBILITY GUARANTEES enforced in the theme rather than
 *   left to each component, "so no component can opt out" (§9.6). That placement is
 *   the point: a rule that lives in a review checklist decays; a rule that lives in
 *   the theme cannot.
 */

import { alpha } from '@mui/material/styles';
import type { Components, Theme } from '@mui/material/styles';

import { FONT_FACE_CSS, FONT_MONO } from './typography';
import { tokens } from './tokens';

export function components(): Components<Omit<Theme, 'components'>> {
  return {
    MuiCssBaseline: {
      styleOverrides: (theme) => `
        ${FONT_FACE_CSS}

        html, body, #root {
          height: 100%;
        }

        body {
          /* ★ Kills pull-to-refresh over the canvas. A surveyor panning an image on
             a tablet must NEVER accidentally reload the app and lose a draft. */
          overscroll-behavior: none;
          -webkit-tap-highlight-color: transparent;
        }

        /* ★ Chrome is not selectable; content is. Dragging on a tool rail must not
           blue-select the label. */
        .le-chrome {
          user-select: none;
        }

        /* ★ Konva/Leaflet stage containers own their gestures completely. */
        .le-stage-container {
          touch-action: none;
          user-select: none;
        }

        /* ★ All numerics, everywhere — §9.4. Available to non-MUI nodes (Konva HTML
           overlays, Leaflet popups) that cannot reach the 'mono' variant. */
        .le-mono {
          font-family: ${FONT_MONO};
          font-variant-numeric: tabular-nums;
        }

        /* ★ prefers-reduced-motion disables flyTo animation, marker pulses and
           skeleton shimmer (§8.8 item 7). Belt and braces at the CSS level; the
           components also read the media query so 'setView' goes instant. */
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
            scroll-behavior: auto !important;
          }
        }

        /* ★ Focus ring: 2px primary with a 2px offset, via :focus-visible ONLY —
           so a mouse click does not ring, but a Tab does (§9.6). */
        :focus-visible {
          outline: 2px solid ${theme.palette.primary.main};
          outline-offset: 2px;
        }

        /* ★ Crisp type on low-DPI panels — the difference between "web page" and
           "product" on most field laptops. */
        body {
          -webkit-font-smoothing: antialiased;
          -moz-osx-font-smoothing: grayscale;
        }

        /* ★ THEMED SCROLLBARS. Default OS scrollbars shout against dark chrome;
           thin, divider-coloured ones read as part of the design. Firefox first,
           then WebKit. */
        * {
          scrollbar-width: thin;
          scrollbar-color: ${theme.palette.divider} transparent;
        }
        *::-webkit-scrollbar {
          width: 10px;
          height: 10px;
        }
        *::-webkit-scrollbar-thumb {
          background: ${theme.palette.divider};
          border-radius: 8px;
          border: 2px solid transparent;
          background-clip: content-box;
        }
        *::-webkit-scrollbar-thumb:hover {
          background: ${theme.palette.text.disabled};
          border: 2px solid transparent;
          background-clip: content-box;
        }
        *::-webkit-scrollbar-corner {
          background: transparent;
        }

        /* ★ Selection in the brand colour — a small cue that everything is one system. */
        ::selection {
          background: ${alpha(theme.palette.primary.main, 0.28)};
        }
      `,
    },

    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          // ★ Kills MUI's dark-mode elevation tint, which shifts panel colour with
          //   elevation and undermines the neutral-chrome principle (§9.1).
        },
      },
    },

    // ★ Depth from the TOKEN SET, not MUI's 24-step shadow ladder: one popover
    //   shadow, one dialog shadow, each carrying its own 1px hairline so floating
    //   surfaces stay separated even over imagery (Phase 2 of the redesign).
    MuiPopover: {
      styleOverrides: { paper: { boxShadow: 'var(--elev-popover)' } },
    },

    MuiCard: {
      styleOverrides: {
        root: ({ theme }) => ({
          'borderRadius': tokens.radius.lg,
          'transition': theme.transitions.create(['border-color', 'box-shadow'], {
            duration: theme.transitions.duration.shorter,
          }),
          // ★ Only cards that DO something invite the pointer — a static info card
          //   must not pretend to be a button. `:has` scopes the lift to cards
          //   wrapping a CardActionArea.
          '&:has(.MuiCardActionArea-root):hover': {
            borderColor: alpha(theme.palette.primary.main, 0.5),
            boxShadow: theme.shadows[3],
          },
        }),
      },
    },

    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: tokens.radius.md,
          textTransform: 'none',
          padding: '6px 14px',
          // ★ The instrument heights: 32px default, 28px compact — a control the
          //   eye can align against the 4px grid, not whatever the label makes it.
          minHeight: 'var(--control-md)',
        },
        sizeSmall: { minHeight: 'var(--control-sm)' },
        sizeLarge: { padding: '9px 22px', fontSize: '0.9375rem' },
        // ★ Contained buttons get their depth from INTERACTION, not from sitting
        //   there: flat at rest (disableElevation), a soft lift under the pointer.
        contained: ({ theme }) => ({
          '&:hover': { boxShadow: theme.shadows[2] },
        }),
      },
    },

    MuiIconButton: {
      styleOverrides: {
        root: {
          // ★ §8.8 item 8 / WCAG 2.2 AA (2.5.8): ≥24×24 everywhere, ≥44×44 on a
          //   coarse pointer. Enforced here so no component can opt out.
          'minWidth': tokens.target.min,
          'minHeight': tokens.target.min,
          'borderRadius': tokens.radius.md,
          '@media (pointer: coarse)': {
            minWidth: tokens.target.coarse,
            minHeight: tokens.target.coarse,
          },
        },
      },
    },

    MuiTooltip: {
      defaultProps: {
        enterDelay: 400,
        arrow: true,
      },
      styleOverrides: {
        tooltip: {
          borderRadius: tokens.radius.sm,
          fontSize: '0.75rem',
          lineHeight: '16px',
          maxWidth: 320,
        },
      },
    },

    MuiTableCell: {
      styleOverrides: {
        root: {
          padding: '6px 12px',
          fontSize: '0.8125rem',
          lineHeight: '20px',
        },
        head: {
          fontSize: '0.6875rem',
          lineHeight: '16px',
          fontWeight: 600,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        },
        // ★ Numeric columns get mono + right-align. Right-aligned decimals make a
        //   misplaced digit visible at a glance — which is the whole review task.
        alignRight: {
          fontFamily: FONT_MONO,
          fontVariantNumeric: 'tabular-nums',
          textAlign: 'right',
        },
      },
    },

    MuiTableRow: {
      styleOverrides: {
        root: { '&:last-child td': { borderBottom: 0 } },
      },
    },

    MuiChip: {
      styleOverrides: {
        root: { borderRadius: tokens.radius.sm, fontWeight: 600 },
        sizeSmall: { height: 22 },
      },
    },

    MuiMenu: {
      styleOverrides: {
        paper: ({ theme }) => ({
          borderRadius: tokens.radius.lg,
          border: `1px solid ${theme.palette.divider}`,
          // Phase 2: depth from the token set — one popover shadow everywhere.
          boxShadow: 'var(--elev-popover)',
          marginTop: 4,
        }),
        list: { padding: '4px' },
      },
    },

    MuiMenuItem: {
      styleOverrides: {
        root: { borderRadius: tokens.radius.sm, margin: '1px 0' },
      },
    },

    MuiListItemButton: {
      styleOverrides: {
        root: { borderRadius: tokens.radius.md },
      },
    },

    MuiDialog: {
      styleOverrides: {
        // ★ Dialogs float on a dimmed, slightly blurred ground: the work behind
        //   recedes without vanishing, and the dialog reads as a layer, not a patch.
        paper: ({ theme }) => ({
          borderRadius: tokens.radius.xl,
          border: `1px solid ${theme.palette.divider}`,
          boxShadow: 'var(--elev-dialog)',
          backgroundImage: 'none',
        }),
      },
    },

    MuiBackdrop: {
      styleOverrides: {
        root: {
          'backgroundColor': 'rgba(8, 11, 17, 0.55)',
          '&.MuiBackdrop-invisible': { backgroundColor: 'transparent' },
        },
      },
    },

    MuiTextField: {
      defaultProps: { size: 'small', variant: 'outlined' },
    },

    MuiOutlinedInput: {
      styleOverrides: {
        root: ({ theme }) => ({
          'borderRadius': tokens.radius.md,
          // ★ The token set's focus is ring + soft INNER glow — depth from light,
          //   not from a drop shadow. Outline stays for the ring (a11y: no layout
          //   shift); the glow rides box-shadow, inputs only.
          '&.Mui-focused': { boxShadow: 'inset 0 0 12px rgb(53 200 216 / 12%)' },
          '&:hover:not(.Mui-focused) .MuiOutlinedInput-notchedOutline': {
            borderColor: theme.palette.text.secondary,
          },
        }),
      },
    },

    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: tokens.radius.md },
      },
    },

    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: tokens.radius.pill, height: 6 },
      },
    },

    MuiTab: {
      styleOverrides: {
        root: { textTransform: 'none', fontWeight: 600, minHeight: 40 },
      },
    },

    MuiTabs: {
      styleOverrides: {
        indicator: { height: 3, borderTopLeftRadius: 3, borderTopRightRadius: 3 },
      },
    },
  };
}
