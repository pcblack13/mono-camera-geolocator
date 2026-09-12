/**
 * `lib/monitor/mapWindow.ts` — the satellite map in ITS OWN WINDOW.
 *
 * ★ FOR THE SECOND SCREEN. An operator with two monitors puts the picture on one
 *   and the map on the other. The map opens as a real window on the app's own
 *   route (`/monitor/cameras/<id>/map`) — its own document, so Leaflet drags and
 *   zooms natively there — and the two windows keep in step over a
 *   `BroadcastChannel` (same origin, no server): the monitor page announces the
 *   run and the lookup table; the map window reports marker clicks and its own
 *   closing, at which point the panel comes back into the page.
 *
 * Pure helpers here (URL, channel name, the message vocabulary), so the tests
 * can pin the protocol without a window.
 */

export interface MapWindowParams {
  /** The detection session whose marks the window should follow; null = none yet. */
  session: string | null;
  /** The chosen lookup table — the map opens on its site before any mark lands. */
  lut: string;
}

/** The route the popped-out window loads. Relative — the origin is the app's own. */
export function mapWindowUrl(cameraId: string, params: MapWindowParams): string {
  const q = new URLSearchParams();
  if (params.session !== null && params.session !== '') q.set('session', params.session);
  if (params.lut !== '') q.set('lut', params.lut);
  const query = q.toString();
  return `/monitor/cameras/${encodeURIComponent(cameraId)}/map${query === '' ? '' : `?${query}`}`;
}

/** One channel per camera — two monitors of two cameras must not cross talk. */
export function mapChannelName(cameraId: string): string {
  return `le.monitor.map.${cameraId}`;
}

/** What the monitor page tells the window. */
export interface MapWindowStateMessage {
  type: 'state';
  session: string | null;
  lut: string;
  selectedIndex: number | null;
}
/** What the window tells the page. */
export type MapWindowMessage =
  | MapWindowStateMessage
  /** The window loaded and wants the current state. */
  | { type: 'hello' }
  /** A marker was clicked in the window. */
  | { type: 'select'; index: number }
  /** The window is going away — bring the panel back. */
  | { type: 'closed' };

export function isMapWindowMessage(value: unknown): value is MapWindowMessage {
  if (value === null || typeof value !== 'object') return false;
  const m = value as { type?: unknown; index?: unknown; lut?: unknown };
  switch (m.type) {
    case 'hello':
    case 'closed':
      return true;
    case 'select':
      return typeof m.index === 'number' && Number.isInteger(m.index) && m.index >= 0;
    case 'state':
      return typeof m.lut === 'string';
    default:
      return false;
  }
}

/** The channel, or null where the platform has none (old browsers, some test DOMs). */
export function openMapChannel(cameraId: string): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null;
  try {
    return new BroadcastChannel(mapChannelName(cameraId));
  } catch {
    return null;
  }
}

/**
 * Open the map window. Returns the window, or null when the platform refused
 * (a popup blocker; an embedder whose window policy denies it).
 */
export function openMapWindow(cameraId: string, params: MapWindowParams): Window | null {
  try {
    const w = window.open(
      mapWindowUrl(cameraId, params),
      `le-map-${cameraId}`,
      'popup=yes,width=1000,height=760,resizable=yes',
    );
    return w ?? null;
  } catch {
    return null;
  }
}
