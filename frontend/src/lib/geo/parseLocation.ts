/**
 * `lib/geo/parseLocation.ts` — read a place the surveyor typed.
 *
 * ★ ACCEPTS WHAT PEOPLE ACTUALLY PASTE, in one function:
 *     34.1067, 36.0172          decimal degrees, comma or whitespace separated
 *     34.1067 36.0172
 *     34.1067°N 36.0172°E       with hemispheres, either order (N/S decides which
 *                               number is the latitude — a paste from a phone often
 *                               arrives longitude-first)
 *     34°06'24.1"N 36°01'02"E   degrees/minutes/seconds
 *     34 6 24.1 N, 36 1 2 E     the same, spaces instead of symbols
 *
 * ★ It NEVER guesses. A string that is not unambiguously a coordinate returns
 *   `null`, and the caller falls back to searching named places — a wrong "did you
 *   mean" that silently flies the map somewhere is worse than saying "not a
 *   coordinate".
 *
 * ★ Bounds are enforced (|lat| ≤ 90, |lon| ≤ 180): a transposed pair like
 *   "36.0172, 34.1067" for a Lebanese site is still valid geography, so it is
 *   accepted — but "95, 36" is not a latitude at all and is rejected rather than
 *   clamped.
 */

import type { LatLon } from '../../types/geo';

/** One parsed half of the pair: a value plus the hemisphere letter it carried. */
interface Component {
  value: number;
  hemisphere: 'N' | 'S' | 'E' | 'W' | null;
}

/** A single half: `34.1067`, `34.1067N`, `34°06'24.1"N`, `34 6 24.1 N`. */
const HALF = new RegExp(
  '^\\s*(-?\\d+(?:\\.\\d+)?)' + // degrees, or a plain decimal
    '(?:\\s*[°d\\s:]\\s*(\\d+(?:\\.\\d+)?)' + // minutes
    "(?:\\s*['m\\s:]\\s*(\\d+(?:\\.\\d+)?))?" + // seconds
    ')?\\s*["s]?\\s*([NSEWnsew])?\\s*$',
);

function toDecimal(deg: string, min?: string, sec?: string): number {
  const d = Number(deg);
  const m = min === undefined ? 0 : Number(min);
  const s = sec === undefined ? 0 : Number(sec);
  const magnitude = Math.abs(d) + m / 60 + s / 3600;
  return d < 0 ? -magnitude : magnitude;
}

function parseHalf(text: string): Component | null {
  const m = HALF.exec(text.trim());
  if (m === null) return null;
  // ★ DEGREES ARE WHOLE when minutes follow. Without this, "34.1067 36.0172"
  //   (two decimal degrees, space separated) parses as 34.1067° 36.0172′ — a
  //   silently wrong place, which is the one outcome this parser must never
  //   produce. A fractional degree therefore ends the component.
  if (m[2] !== undefined && !Number.isInteger(Number(m[1]))) return null;
  return {
    value: toDecimal(m[1], m[2], m[3]),
    hemisphere: m[4] ? (m[4].toUpperCase() as Component['hemisphere']) : null,
  };
}

/** Split the input into its two halves — on a comma, else on whitespace. */
function splitHalves(text: string): [string, string] | null {
  if (text.includes(',')) {
    const parts = text.split(',');
    if (parts.length !== 2) return null;
    return [parts[0], parts[1]];
  }
  // Whitespace: the halves are DMS groups, so split at the midpoint of the token
  // list only when it divides evenly (2, 4, 6 or 8 tokens: N/N, DM/DM, DMS/DMS…).
  const tokens = text.split(/\s+/).filter((t) => t !== '');
  if (tokens.length < 2 || tokens.length % 2 !== 0) return null;
  const half = tokens.length / 2;
  return [tokens.slice(0, half).join(' '), tokens.slice(half).join(' ')];
}

/**
 * Parse a typed location into a coordinate, or `null` when it is not one.
 */
export function parseLocation(input: string): LatLon | null {
  const text = input.trim();
  if (text === '') return null;
  // Reject anything carrying letters other than hemisphere markers — that is a
  // place NAME, and names are somebody else's job.
  if (/[a-mo-rt-vx-zA-MO-RT-VX-Z]/.test(text.replace(/[NSEWnsew]/g, ''))) return null;

  const halves = splitHalves(text);
  if (halves === null) return null;
  const first0 = parseHalf(halves[0]);
  const second0 = parseHalf(halves[1]);
  if (first0 === null || second0 === null) return null;

  let first = first0;
  let second = second0;
  // ★ Hemispheres decide the ORDER when they are given: "36.0172E, 34.1067N" is a
  //   longitude-first paste and must not be read as a latitude of 36.
  const firstIsLon = first.hemisphere === 'E' || first.hemisphere === 'W';
  const secondIsLat = second.hemisphere === 'N' || second.hemisphere === 'S';
  if (firstIsLon || secondIsLat) [first, second] = [second, first];

  const signed = (c: Component): number =>
    c.hemisphere === 'S' || c.hemisphere === 'W' ? -Math.abs(c.value) : c.value;

  const lat = signed(first);
  const lon = signed(second);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

/**
 * Parse ONE typed coordinate value for a named axis — the separate latitude and
 * longitude boxes of the "go to location" form.
 *
 * Accepts the same shapes as one half of a pair (`34.1067`, `34.1067N`,
 * `34°06'24.1"N`), applies the hemisphere letter when present, and enforces the
 * axis's own range. Returns `null` for anything else — never a clamped guess.
 */
export function parseCoordinateValue(input: string, axis: 'lat' | 'lon'): number | null {
  const component = parseHalf(input);
  if (component === null) return null;
  // ★ A hemisphere from the WRONG axis is a mistake, not a detail to absorb: "36E"
  //   typed into the latitude box means the two boxes were swapped, and silently
  //   accepting it would place the point in the wrong hemisphere of the wrong axis.
  const { hemisphere } = component;
  if (hemisphere !== null) {
    const belongsToLat = hemisphere === 'N' || hemisphere === 'S';
    if (belongsToLat !== (axis === 'lat')) return null;
  }
  const value =
    hemisphere === 'S' || hemisphere === 'W' ? -Math.abs(component.value) : component.value;
  if (!Number.isFinite(value)) return null;
  if (Math.abs(value) > (axis === 'lat' ? 90 : 180)) return null;
  return value;
}

export default parseLocation;
