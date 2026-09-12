/**
 * `lib/calibrationCsv.ts` — parse the field tool's calibration CSV into camera fields.
 *
 * ★ THE FORMAT IS THE TEAMMATE TOOL'S, VERBATIM: two columns, `key,value`, no header —
 *
 *     fx,4123
 *     fy,4123
 *     cx,2969
 *     ...
 *
 *   Keys are case-insensitive. Values are parsed leniently the way that tool's `_num`
 *   does (`"4123 px"` → 4123): surveyors paste from spreadsheets and reports, and a
 *   unit suffix should not silently drop a row. Unknown keys are ignored, not errors —
 *   the same file often carries extra bookkeeping columns.
 *
 * ★ FULL PRECISION IS KEPT. The desktop tool re-formats imports to 6 significant
 *   digits on display (`fx=2799.7344` → `2799.73`); here the parsed number goes into
 *   the form untouched, because the database stores what was imported, not what a
 *   display format kept.
 *
 * ★ The tool's CSVs may also carry pose keys (`cam_lat`, `cam_lon`, `zoff`,
 *   `tilt_down`) — its importer applies any key matching a GUI field, and files in the
 *   wild use that. They map onto our position/tilt fields so a full station imports in
 *   one gesture.
 */

/** Every camera-form field a calibration CSV may fill. */
export interface ParsedCalibration {
  fx?: number;
  fy?: number;
  cx?: number;
  cy?: number;
  k1?: number;
  k2?: number;
  p1?: number;
  p2?: number;
  k3?: number;
  img_w?: number;
  img_h?: number;
  lat?: number;
  lon?: number;
  mast_offset_m?: number;
  tilt_deg?: number;
}

/** CSV key (lowercased) → form field. Aliases mirror the desktop tool's field names. */
const KEY_MAP: Record<string, keyof ParsedCalibration> = {
  fx: 'fx',
  fy: 'fy',
  cx: 'cx',
  cy: 'cy',
  k1: 'k1',
  k2: 'k2',
  p1: 'p1',
  p2: 'p2',
  k3: 'k3',
  img_w: 'img_w',
  img_h: 'img_h',
  cam_lat: 'lat',
  lat: 'lat',
  latitude: 'lat',
  cam_lon: 'lon',
  lon: 'lon',
  longitude: 'lon',
  zoff: 'mast_offset_m',
  mast_offset_m: 'mast_offset_m',
  tilt_down: 'tilt_deg',
  tilt_deg: 'tilt_deg',
};

/** Lenient numeric parse: `Number()` first, else the first numeric token in the string. */
function parseNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const direct = Number(trimmed);
  if (Number.isFinite(direct)) return direct;
  const match = /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(trimmed);
  if (match === null) return null;
  const extracted = Number(match[0]);
  return Number.isFinite(extracted) ? extracted : null;
}

export interface CalibrationParseResult {
  fields: ParsedCalibration;
  /** How many `key,value` rows were recognised — 0 means "this was not a calibration CSV". */
  matched: number;
  /** Recognised keys whose value could not be read as a number. */
  badValues: string[];
}

/** Parse calibration CSV text. Never throws — a mangled file is `{matched: 0}`. */
export function parseCalibrationCsv(text: string): CalibrationParseResult {
  const fields: ParsedCalibration = {};
  const badValues: string[] = [];
  let matched = 0;

  // Strip a BOM (the desktop tool writes/reads utf-8-sig) and split on any line ending.
  for (const line of text.replace(/^\uFEFF/, '').split(/\r\n|\r|\n/)) {
    const cells = line.split(',');
    if (cells.length < 2) continue;
    const key = cells[0].trim().toLowerCase();
    const field = KEY_MAP[key];
    if (field === undefined) continue;
    const value = parseNumber(cells.slice(1).join(','));
    if (value === null) {
      badValues.push(key);
      continue;
    }
    fields[field] = value;
    matched += 1;
  }

  return { fields, matched, badValues };
}
