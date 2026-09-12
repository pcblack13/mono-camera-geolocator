/**
 * ★★ COORDINATE FORMATTING + THE PRECISION-TRUNCATION POLICY — CONTRACT.md §8.7.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ **A banner can be dismissed; digits cannot.**
 *
 *   `41.8721943` on a fix that could be 50 m off is **a fabricated precision claim
 *   in the data itself** — and that is the number that gets pasted into a legal
 *   document. So the number of decimals we render is a FUNCTION of the reported
 *   accuracy. This is the honesty mechanism that actually works, because it travels
 *   with the value instead of sitting next to it.
 *
 *   Full precision stays available on hover and in exports, adjacent to the
 *   confidence column — we truncate the CLAIM, never the DATUM. Nothing in this
 *   module ever rounds a stored coordinate (§8.6: round for display, never for
 *   storage).
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * **Pure.** No React, no store. Unit-testable in isolation.
 */

import type { ConfidenceBand } from '../../types/gcp';
import type { CoordinateFormat } from '../../types/common';
import type { LatLon } from '../../types/geo';

// ─────────────────────────────────────────────────────────────────────────────
// §8.7 — the truncation table, NORMATIVE
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ **Keyed on `accuracy.total_ce90_m` — NEVER `relative_ce90_m`.**
 *
 *   Reporting the relative figure would tell a surveyor they have 0.3 m GCPs when
 *   they have 3 m ones (`types/gcp.ts`). `total_ce90_m = sqrt(relative² + georef²)`
 *   is THE headline number, and it is the one a decimal digit is a claim about.
 */
const METRES_DECIMALS: readonly { readonly max_m: number; readonly decimals: number }[] = [
  { max_m: 1, decimals: 7 }, // < 1 m   → 41.8721943
  { max_m: 5, decimals: 6 }, // 1–5 m   → 41.872194
  { max_m: 20, decimals: 4 }, // 5–20 m  → 41.8722
  { max_m: Infinity, decimals: 2 }, // > 20 m  → 41.87
];

/**
 * ★ The band can only ever TAKE DIGITS AWAY, never add them.
 *
 * §8.7's table pairs each metre range with the band it typically co-occurs with, and
 * states one hard rule in prose: **"> 20 m *or* band = `unreliable`" → 2**. The
 * table is silent on the off-diagonal cases it never anticipated — e.g. a `low` band
 * at 3 m. Taking `min(metres-derived, band cap)` reproduces **every row of §8.7's
 * table exactly** while resolving the gaps in the only direction this module is
 * allowed to err: fewer digits, never more. A truncation policy that could be talked
 * into an extra digit is not a truncation policy.
 */
const BAND_DECIMAL_CAP: Record<ConfidenceBand, number> = {
  high: 7,
  moderate: 6,
  low: 4,
  unreliable: 2,
};

/**
 * ★ THE FUNCTION. How many decimals may a lat/lon be rendered with?
 *
 * @param total_ce90_m `GcpRead.accuracy.total_ce90_m` — the headline CE90 radius.
 * @param band the confidence band (`lib/confidence.ts` → `gcpConfidenceBand`).
 *
 * ★ A non-finite or negative accuracy yields the FLOOR (2), not a throw and not the
 *   maximum. An unknown accuracy is not a good accuracy, and this function's whole
 *   purpose is to refuse to over-claim (L12).
 */
export function displayDecimals(total_ce90_m: number, band: ConfidenceBand): number {
  const cap = BAND_DECIMAL_CAP[band];
  if (!Number.isFinite(total_ce90_m) || total_ce90_m < 0) return BAND_DECIMAL_CAP.unreliable;
  const row =
    METRES_DECIMALS.find((r) => total_ce90_m < r.max_m) ??
    METRES_DECIMALS[METRES_DECIMALS.length - 1]!;
  return Math.min(row.decimals, cap);
}

/**
 * Decimals for a distance in metres, derived from the same accuracy figure.
 *
 * Used for the UTM easting/northing and for `adjustment_offset_m`. Sub-metre
 * accuracy earns centimetres; a 20 m CE90 earns whole metres.
 */
export function metreDecimals(total_ce90_m: number): number {
  if (!Number.isFinite(total_ce90_m) || total_ce90_m < 0) return 0;
  if (total_ce90_m < 1) return 2;
  if (total_ce90_m < 5) return 1;
  return 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Decimal degrees
// ─────────────────────────────────────────────────────────────────────────────

const hemiLat = (lat: number): string => (lat >= 0 ? 'N' : 'S');
const hemiLon = (lon: number): string => (lon >= 0 ? 'E' : 'W');

/** `41.8721943° N` */
export function formatDecimalDegrees(value: number, decimals: number, hemisphere: string): string {
  return `${Math.abs(value).toFixed(decimals)}° ${hemisphere}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Degrees / minutes / seconds
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ The seconds' decimals are DERIVED from the decimal-degree budget, so switching
 *   `coordinateFormat` can never smuggle back precision §8.7 just removed.
 *
 *   One degree is 3600″, so `d` decimal degrees ≈ `d − 4` decimal seconds
 *   (`10^-4 ° ≈ 0.36″`). Clamped to `[0, 3]`.
 */
export function secondsDecimals(decimals: number): number {
  return Math.min(3, Math.max(0, decimals - 4));
}

/** `41° 52' 19.900" N` */
export function formatDms(value: number, decimals: number, hemisphere: string): string {
  const abs = Math.abs(value);
  const secDecimals = secondsDecimals(decimals);

  let deg = Math.floor(abs);
  let min = Math.floor((abs - deg) * 60);
  let sec = (abs - deg - min / 60) * 3600;

  // ★ Carry on rounding: 59.9999″ at 2 dp is 60.00″, which must become the next
  //   minute. Formatting the raw value would render `41° 52' 60.00"` — not wrong by
  //   much, but visibly broken, and it is the kind of thing that ends up in a report.
  const secRounded = Number(sec.toFixed(secDecimals));
  if (secRounded >= 60) {
    sec = 0;
    min += 1;
  } else {
    sec = secRounded;
  }
  if (min >= 60) {
    min = 0;
    deg += 1;
  }

  return `${deg}° ${String(min).padStart(2, '0')}' ${sec.toFixed(secDecimals).padStart(secDecimals > 0 ? secDecimals + 3 : 2, '0')}" ${hemisphere}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// UTM — WGS84 forward projection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Implemented here rather than delegated because **`proj4` is not a dependency**
 *   (IU-23 owns `package.json` and did not add one), while `CoordinateFormat`
 *   includes `'utm'` and `workspaceStore` PERSISTS that choice — so the format must
 *   work or the setting is a lie.
 *
 * ★ **This is DISPLAY-ONLY.** L3/L4 keep CRS knowledge out of `ai_engine` and
 *   descriptors out of `gis`; the equivalent discipline here is that nothing derived
 *   from this function is ever stored, exported, or sent to the server. The wire
 *   carries EPSG:4326 (`GcpRead.crs: 'EPSG:4326'`, always), the SERVER owns every
 *   real reprojection (`gis/crs.py`, the one module allowed to see pyproj), and this
 *   is a rendering of a number the user already has.
 *
 * Snyder's series (USGS Professional Paper 1395) on the WGS84 ellipsoid, truncated
 * at the 6th-order term — sub-millimetre within a zone's ±3° of the central
 * meridian, which is orders of magnitude finer than the CE90 figures that gate the
 * digits we are allowed to print anyway.
 */
export interface UtmCoordinate {
  zone: number;
  /** The MGRS latitude band letter, `C`–`X` (`I` and `O` omitted). */
  band: string;
  hemisphere: 'N' | 'S';
  easting_m: number;
  northing_m: number;
}

const WGS84_A = 6378137.0;
const WGS84_F = 1 / 298.257223563;
const UTM_K0 = 0.9996;
const UTM_FALSE_EASTING = 500000.0;
const UTM_FALSE_NORTHING = 10000000.0;

const rad = (deg: number): number => (deg * Math.PI) / 180;

/** `C`–`X`, `I`/`O` omitted (they read as 1/0). `null` outside UTM's ±80°/±84° range. */
export function utmBand(lat: number): string | null {
  if (lat < -80 || lat > 84) return null;
  const letters = 'CDEFGHJKLMNPQRSTUVWX';
  const i = Math.floor((lat + 80) / 8);
  return letters[Math.min(i, letters.length - 1)] ?? null;
}

/**
 * ★ The zone, INCLUDING the two irregularity sets. They are not trivia: omitting
 *   them puts a Norwegian or Svalbard coordinate in the wrong zone, and a
 *   wrong-zone easting is a plausible-looking number that is ~hundreds of km out.
 */
export function utmZone(lat: number, lon: number): number {
  let zone = Math.floor((lon + 180) / 6) + 1;

  // South-west Norway: zone 32 is widened westward.
  if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) zone = 32;

  // Svalbard: zones 31/33/35/37 are widened, 32/34/36 suppressed.
  if (lat >= 72 && lat < 84) {
    if (lon >= 0 && lon < 9) zone = 31;
    else if (lon >= 9 && lon < 21) zone = 33;
    else if (lon >= 21 && lon < 33) zone = 35;
    else if (lon >= 33 && lon < 42) zone = 37;
  }
  return zone;
}

/**
 * WGS84 lat/lon → UTM. Returns `null` outside UTM's valid latitude range (±80°S /
 * +84°N) — **`null`, not a clamped guess**: UTM genuinely does not define the polar
 * regions, and the caller falls back to decimal degrees.
 */
export function toUtm(p: LatLon): UtmCoordinate | null {
  const band = utmBand(p.lat);
  if (band === null) return null;
  if (!Number.isFinite(p.lat) || !Number.isFinite(p.lon)) return null;

  const zone = utmZone(p.lat, p.lon);
  const lon0 = rad((zone - 1) * 6 - 180 + 3);

  const phi = rad(p.lat);
  const lam = rad(p.lon);

  const e2 = WGS84_F * (2 - WGS84_F);
  const ep2 = e2 / (1 - e2);

  const sinPhi = Math.sin(phi);
  const cosPhi = Math.cos(phi);
  const tanPhi = Math.tan(phi);

  const N = WGS84_A / Math.sqrt(1 - e2 * sinPhi * sinPhi);
  const T = tanPhi * tanPhi;
  const C = ep2 * cosPhi * cosPhi;

  // Normalise the central-meridian offset into (-π, π] so a zone spanning the
  // antimeridian does not produce a ±2π excursion.
  let dLam = lam - lon0;
  while (dLam > Math.PI) dLam -= 2 * Math.PI;
  while (dLam < -Math.PI) dLam += 2 * Math.PI;
  const A = dLam * cosPhi;

  const e4 = e2 * e2;
  const e6 = e4 * e2;
  const M =
    WGS84_A *
    ((1 - e2 / 4 - (3 * e4) / 64 - (5 * e6) / 256) * phi -
      ((3 * e2) / 8 + (3 * e4) / 32 + (45 * e6) / 1024) * Math.sin(2 * phi) +
      ((15 * e4) / 256 + (45 * e6) / 1024) * Math.sin(4 * phi) -
      ((35 * e6) / 3072) * Math.sin(6 * phi));

  const A2 = A * A;
  const A3 = A2 * A;
  const A4 = A3 * A;
  const A5 = A4 * A;
  const A6 = A5 * A;

  const easting =
    UTM_K0 *
      N *
      (A + ((1 - T + C) * A3) / 6 + ((5 - 18 * T + T * T + 72 * C - 58 * ep2) * A5) / 120) +
    UTM_FALSE_EASTING;

  let northing =
    UTM_K0 *
    (M +
      N *
        tanPhi *
        (A2 / 2 +
          ((5 - T + 9 * C + 4 * C * C) * A4) / 24 +
          ((61 - 58 * T + T * T + 600 * C - 330 * ep2) * A6) / 720));

  const hemisphere: 'N' | 'S' = p.lat >= 0 ? 'N' : 'S';
  if (hemisphere === 'S') northing += UTM_FALSE_NORTHING;

  return { zone, band, hemisphere, easting_m: easting, northing_m: northing };
}

/** `33T 315428.31 E  4638251.07 N` */
export function formatUtm(u: UtmCoordinate, decimals: number): string {
  return `${u.zone}${u.band} ${u.easting_m.toFixed(decimals)} E  ${u.northing_m.toFixed(decimals)} N`;
}

// ─────────────────────────────────────────────────────────────────────────────
// The dispatcher — what every GCP surface calls
// ─────────────────────────────────────────────────────────────────────────────

export interface FormattedCoordinate {
  /** The single string for a cell or a chip. */
  text: string;
  /** Lat and lon separately, for a two-column table. `null` in UTM (it is one grid ref). */
  lat_text: string | null;
  lon_text: string | null;
  /** ★ The UNTRUNCATED value, for the hover title and the copy action (§8.7). */
  full_precision: string;
  /** How many decimals §8.7 permitted. Rendered by the inspector as provenance. */
  decimals: number;
}

/**
 * ★ **THE function every coordinate surface should call.**
 *
 * It takes the accuracy and the band rather than a decimal count, so no caller can
 * accidentally pick its own precision — which is the whole point of §8.7. The
 * `full_precision` field carries the real number for the `title` attribute and the
 * copy-to-clipboard action, so nothing is ever lost, only unclaimed.
 *
 * ★ UTM outside ±80°S/+84°N falls back to decimal degrees rather than rendering
 *   nothing. The band letter is undefined there; the coordinate is not.
 */
export function formatLatLon(
  p: LatLon,
  format: CoordinateFormat,
  total_ce90_m: number,
  band: ConfidenceBand,
  /**
   * ★ Fixed degree decimals, overriding the accuracy-driven count. The GCP TABLE
   * passes 6: rows must be comparable at a glance (and against a printed sheet),
   * and accuracy already has its own column — encoding it a second time by varying
   * decimal counts made identical-looking coordinates differ row to row.
   */
  fixedDecimals?: number,
): FormattedCoordinate {
  const decimals = fixedDecimals ?? displayDecimals(total_ce90_m, band);
  const full = `${p.lat}, ${p.lon}`;

  if (format === 'utm') {
    const u = toUtm(p);
    if (u) {
      const d = metreDecimals(total_ce90_m);
      return {
        text: formatUtm(u, d),
        lat_text: null,
        lon_text: null,
        full_precision: full,
        decimals: d,
      };
    }
    // Fall through to `dd` — see the note above.
  }

  if (format === 'dms') {
    const lat_text = formatDms(p.lat, decimals, hemiLat(p.lat));
    const lon_text = formatDms(p.lon, decimals, hemiLon(p.lon));
    return { text: `${lat_text}  ${lon_text}`, lat_text, lon_text, full_precision: full, decimals };
  }

  const lat_text = formatDecimalDegrees(p.lat, decimals, hemiLat(p.lat));
  const lon_text = formatDecimalDegrees(p.lon, decimals, hemiLon(p.lon));
  return { text: `${lat_text}  ${lon_text}`, lat_text, lon_text, full_precision: full, decimals };
}

// ─────────────────────────────────────────────────────────────────────────────
// Image pixels + metres
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ §8.6 — image coordinates are displayed to **1 decimal** and are NEVER rounded
 *   for storage. The sub-pixel digit is not decoration: the surveyor placed the
 *   point between pixels and the tool should say so.
 */
export function formatImagePx(p: { x: number; y: number }): string {
  return `${p.x.toFixed(1)}, ${p.y.toFixed(1)}`;
}

/** `±3.2 m` — the CE90 radius chip. */
export function formatAccuracy(total_ce90_m: number): string {
  if (!Number.isFinite(total_ce90_m)) return '—';
  return `±${total_ce90_m.toFixed(metreDecimals(total_ce90_m))} m`;
}
