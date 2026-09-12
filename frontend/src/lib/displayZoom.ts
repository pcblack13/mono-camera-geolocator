/**
 * `lib/displayZoom.ts` — the app's DISPLAY SIZE, through the desktop shell.
 *
 * ★ WHY THE SHELL AND NOT CSS. A 50-inch TV reported at scale factor 1 draws
 *   the UI at laptop size. Scaling it in CSS (`zoom`, rem tricks) would put the
 *   photo canvas, the maps and every `getBoundingClientRect` on different rulers;
 *   Chromium's page zoom — what the shell applies — scales all of them together,
 *   exactly as Ctrl + does in a browser. So the renderer only ASKS; the shell
 *   applies and remembers. In a plain browser there is no shell and no control.
 */

export type ZoomPreference = 'auto' | number;

export interface ZoomInfo {
  preference: ZoomPreference;
  /** The factor in force right now. */
  zoom: number;
  /** What 'auto' resolves to on the window's current display. */
  auto: number;
  steps: readonly number[];
}

interface ZoomBridge {
  get: () => Promise<ZoomInfo>;
  set: (preference: ZoomPreference) => Promise<ZoomInfo>;
  /** Absent on a desktop shell older than the shortcuts. */
  step?: (direction: 1 | -1) => Promise<ZoomInfo>;
  onChange: (callback: (info: ZoomInfo) => void) => () => void;
}

function bridge(): ZoomBridge | null {
  const w = window as unknown as { leNative?: { zoom?: ZoomBridge } };
  const z = w.leNative?.zoom;
  return z && typeof z.get === 'function' && typeof z.set === 'function' ? z : null;
}

/** True inside a desktop shell new enough to scale the display. */
export function hasDisplayZoom(): boolean {
  return bridge() !== null;
}

export async function getDisplayZoom(): Promise<ZoomInfo | null> {
  const b = bridge();
  if (b === null) return null;
  try {
    return await b.get();
  } catch {
    return null;
  }
}

export async function setDisplayZoom(preference: ZoomPreference): Promise<ZoomInfo | null> {
  const b = bridge();
  if (b === null) return null;
  try {
    return await b.set(preference);
  } catch {
    return null;
  }
}

export async function stepDisplayZoom(direction: 1 | -1): Promise<ZoomInfo | null> {
  const b = bridge();
  if (b === null || typeof b.step !== 'function') return null;
  try {
    return await b.step(direction);
  } catch {
    return null;
  }
}

/**
 * Which display-size action a keydown asks for — Ctrl/⌘ with + = − _ 0 — or null.
 * Pure, so the keymap is pinned without a window.
 */
export function zoomActionForKey(e: {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}): 'in' | 'out' | 'auto' | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null;
  if (e.key === '=' || e.key === '+') return 'in';
  if (e.key === '-' || e.key === '_') return 'out';
  if (e.key === '0') return 'auto';
  return null;
}

/**
 * Ctrl + / Ctrl − / Ctrl 0 on this window, applied through the shell.
 *
 * ★ In the renderer, not the main process: the shell's `before-input-event`
 *   never sees injected input, and one path that both the keyboard and the
 *   menu take is one path to test. Installed by the app shell AND the popped-out
 *   map window (which has no shell), so the shortcut works wherever the app is.
 */
export function installDisplayZoomShortcuts(target: Window = window): () => void {
  if (!hasDisplayZoom()) return () => undefined;
  const onKey = (e: KeyboardEvent): void => {
    const action = zoomActionForKey(e);
    if (action === null) return;
    e.preventDefault();
    if (action === 'auto') void setDisplayZoom('auto');
    else void stepDisplayZoom(action === 'in' ? 1 : -1);
  };
  target.addEventListener('keydown', onKey);
  return () => target.removeEventListener('keydown', onKey);
}

export function onDisplayZoom(callback: (info: ZoomInfo) => void): () => void {
  const b = bridge();
  if (b === null || typeof b.onChange !== 'function') return () => undefined;
  return b.onChange(callback);
}

/** "150 %" — the same everywhere the size is named. */
export function formatZoom(factor: number): string {
  return `${Math.round(factor * 100)} %`;
}
