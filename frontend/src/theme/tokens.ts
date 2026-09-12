/**
 * Design tokens — 50-frontend.md §9.2, adopted verbatim.
 *
 * ★ THE PRINCIPLE (§9.1): the chrome is desaturated and low-contrast **so that the
 *   imagery and the confidence colours are the only saturated things on screen**.
 *   In a tool whose entire job is judging photographs and communicating risk, a
 *   colourful UI is actively harmful: it competes with the imagery for attention
 *   and it dilutes the semantic weight of the confidence palette. Every colour in
 *   the chrome earns its place or is removed.
 */

export const tokens = {
  radius: { none: 0, sm: 4, md: 6, lg: 8, xl: 12, pill: 999 },

  /** MUI base; `theme.spacing(n) = 8n`. */
  spacing: 8,

  elevation: { panel: 0, dock: 1, drawer: 8, dialog: 16, tooltip: 24 },

  duration: { instant: 0, fast: 120, normal: 200, slow: 320, fly: 500 },

  easing: {
    standard: 'cubic-bezier(0.2, 0, 0, 1)',
    decel: 'cubic-bezier(0, 0, 0, 1)',
  },

  layout: {
    topBarHeight: 56,
    toolRailWidth: 56,
    inspectorWidth: 280,
    dockHeightDefault: 240,
    dockHeightMin: 120,
    paneMinWidth: 320,
    splitterSize: 6,
  },

  zIndex: {
    canvasOverlay: 10,
    mapControl: 400,
    dock: 1000,
    appBar: 1100,
    drawer: 1200,
    dialog: 1300,
    snackbar: 1400,
    tooltip: 1500,
  },

  /**
   * ★ These are CSS pixels AFTER inverse-scaling — the ON-SCREEN sizes, constant at
   *   every zoom. A 6px point must stay 6px whether the viewer is at 0.1× or 40×;
   *   scaling it with the stage would make a landmark unclickable when zoomed out
   *   and a blob when zoomed in.
   */
  annotation: {
    pointRadius: 6,
    pointRadiusSelected: 8,
    vertexRadius: 4,
    strokeWidth: 2,
    strokeWidthSelected: 3,
    /** Generous invisible hit area — a 2px line is not a 2px target (WCAG 2.5.8). */
    hitStrokeWidth: 12,
    /**
     * ★ Markers sit on satellite imagery of ARBITRARY colour, so a contrast claim
     *   against a known background is not available. The outline is what makes the
     *   claim actually true (§8.8 item 6).
     */
    outlineWidth: 1.5,
  },

  /** Minimum interactive target sizes — §8.8 item 8, WCAG 2.2 AA (2.5.8). */
  target: { min: 24, coarse: 44 },
} as const;

export type Tokens = typeof tokens;
