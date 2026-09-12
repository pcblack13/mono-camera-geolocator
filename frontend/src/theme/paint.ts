/**
 * `theme/paint.ts` — colours for surfaces CSS variables cannot reach.
 *
 * ★ WHY THIS FILE EXISTS. The token set lives in `tokens.css`, but three renderers
 *   in this app never read CSS: MapLibre paints from a JSON style object, Leaflet
 *   markers are built as raw HTML strings, and Konva draws to a canvas. Each used
 *   to carry its own hex literals — which is exactly the drift the "zero
 *   hard-coded colours in components" gate forbids. Every such literal now lives
 *   here, once, under a name that says what it is FOR.
 *
 * ★ ON-MEDIA CHROME IS THEME-INDEPENDENT, deliberately. Text sitting on a
 *   photograph, a video frame or satellite imagery must read against the MEDIA,
 *   not against the app theme — imagery does not turn white in light mode. So
 *   `ON_MEDIA` is white-with-shadow in both themes, and that is a decision, not
 *   an oversight.
 */

/** Ink drawn directly over imagery/video — readable on media, in either theme. */
export const ON_MEDIA = '#FFFFFF';

/** The shadow that keeps ON_MEDIA legible over a bright sky or white gravel. */
export const ON_MEDIA_SHADOW = '#000000';

/** The well a video or photo sits in — true black, so letterboxing disappears. */
export const MEDIA_WELL = '#000000';

/** The tile-failure banner's link — amber, matching `--status-warn` intent. */
export const ON_MEDIA_LINK = '#FFD54F';

/**
 * The 3D terrain scene's own paint (MapLibre style JSON — no CSS reaches it).
 * The background matches `--bg-canvas`: the void the terrain floats in.
 */
export const TERRAIN_3D = {
  background: '#06090D',
  markerHalo: '#000000',
  markerStroke: '#FFFFFF',
  /**
   * ★ The draft point is VIOLET now, not the previous alarm-orange: violet is the
   *   system's unsaved-work hue (`--status-draft`), and orange belongs to the
   *   accuracy bands — a draft that looked like "low accuracy" was a misreading
   *   waiting to happen.
   */
  draftFill: '#FFFFFF',
  draftStroke: '#A78BFA',
} as const;

/**
 * The monitor globe's own paint (MapLibre style JSON — no CSS reaches it). Space
 * is `--bg-canvas`; the marker colours are the STATUS hues of the token set, so a
 * cyan dot on the globe means exactly what a cyan pill means in a panel.
 */
export const GLOBE = {
  space: '#06090D',
  /** The sphere itself, under the imagery — visibly a planet when tiles are 204. */
  earth: '#101A26',
  atmosphere: '#35C8D8',
  /** Status → marker colour. `unknown` is dim: never opened, nothing claimed. */
  live: '#35C8D8',
  connecting: '#FBBF24',
  lost: '#F87171',
  unknown: '#64748B',
  markerStroke: '#0B0F14',
  cluster: '#93A1B3',
  wedge: '#35C8D8',
  // ── places on the globe (2026-09-10): borders, names and their halo ──
  border: 'rgba(255,255,255,0.55)',
  borderMinor: 'rgba(255,255,255,0.35)',
  label: 'rgba(255,255,255,0.92)',
  labelQuiet: 'rgba(255,255,255,0.7)',
  labelHalo: 'rgba(0,0,0,0.75)',
  cityDot: 'rgba(255,255,255,0.9)',
  cityDotStroke: 'rgba(0,0,0,0.6)',
  vertexStroke: '#FFFFFF',
} as const;
