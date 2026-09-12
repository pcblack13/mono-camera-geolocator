/**
 * The heat ramp, shared by the overlay legend and the arrow colours.
 *
 * ★ THESE FOUR STOPS ARE THE SERVER'S. `accuracy_service._HEAT_STOPS` renders the PNG
 *   overlay with exactly this ramp, and the vendored offline report embeds it too. A
 *   legend drawn from a different ramp than the pixels it explains is a lie told in
 *   good faith, so the values live in one place per side and are cross-referenced.
 *
 * Not in `ErrorMapView.tsx`: a module that exports both components and constants
 * breaks fast refresh (react-refresh/only-export-components).
 */

import { HEAT_STOPS } from '../../theme/dataColors';

export { HEAT_STOPS };

export { STAGE_COLOUR } from '../../theme/dataColors';

function parseHex(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/**
 * Error magnitude → ramp colour, clamped at `vmax`.
 *
 * ★ `vmax` is always the RAW error's maximum, for every stage — the whole point of the
 *   shared scale is that a correction visibly shrinks rather than re-normalising to
 *   look identical.
 */
export function heatColour(value: number, vmax: number): string {
  const t = Math.max(0, Math.min(1, value / Math.max(vmax, 1e-6)));
  const idx = Math.min(t * 3, 2.999);
  const lo = Math.floor(idx);
  const fr = idx - lo;
  const a = parseHex(HEAT_STOPS[lo]);
  const b = parseHex(HEAT_STOPS[lo + 1]);
  const mix = a.map((v, i) => Math.round(v * (1 - fr) + b[i] * fr));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}
