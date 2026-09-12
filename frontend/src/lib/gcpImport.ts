/**
 * `lib/gcpImport.ts` — read already-located GCPs from a CSV or GeoJSON file.
 *
 * ★ THE ROUND TRIP IS THE CONTRACT. This app's own exports carry everything a
 *   correspondence needs — Image X/Y and Latitude/Longitude in the CSV,
 *   `pixel_col`/`pixel_row` plus the Point geometry in the GeoJSON — so a file
 *   exported from one project re-deploys onto THE SAME PHOTOGRAPH in another
 *   project (or against a different basemap) without re-picking a single point.
 *   Foreign files work too, as long as each row names both halves of the pair;
 *   common header spellings (`pixel_x`, `u`, `lng`, …) are accepted.
 *
 * ★ ROWS WITHOUT PIXEL COORDINATES ARE SKIPPED AND NAMED, never guessed: a GCP is
 *   a photo↔world correspondence, and a file that only knows the world half cannot
 *   place anything on the photo. The parser reports each skip with its reason —
 *   silence would read as "imported everything".
 */

export interface ImportedGcp {
  name: string | null;
  image_x: number;
  image_y: number;
  lat: number;
  lon: number;
}

export interface SkippedRow {
  /** 1-based position in the file (or feature index for GeoJSON). */
  row: number;
  reason: string;
}

export interface GcpImportResult {
  points: ImportedGcp[];
  skipped: SkippedRow[];
}

// ── header vocabulary ────────────────────────────────────────────────────────
/** Normalise a header: lower-case, alphanumerics only ("Image X" → "imagex"). */
function norm(header: string): string {
  return header.toLowerCase().replace(/[^a-z0-9]/g, '');
}

const X_KEYS = new Set(['imagex', 'pixelcol', 'pixelx', 'imgx', 'u', 'x', 'col']);
const Y_KEYS = new Set(['imagey', 'pixelrow', 'pixely', 'imgy', 'v', 'y', 'row']);
const LAT_KEYS = new Set(['latitude', 'lat']);
const LON_KEYS = new Set(['longitude', 'lon', 'lng', 'long']);
const NAME_KEYS = new Set(['name', 'label', 'code', 'pointname']);

function finite(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const text = String(v).trim();
  // ★ '' must be ABSENT, not zero: Number('') === 0, and a blank Image X cell
  //   coerced to 0 would silently deploy the point onto the photo's corner.
  if (text === '') return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function validate(
  row: number,
  name: string | null,
  x: number | null,
  y: number | null,
  lat: number | null,
  lon: number | null,
): { point?: ImportedGcp; skip?: SkippedRow } {
  if (x === null || y === null) {
    return { skip: { row, reason: 'no image pixel coordinates — cannot place it on the photo' } };
  }
  if (lat === null || lon === null) return { skip: { row, reason: 'no latitude/longitude' } };
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    return { skip: { row, reason: `out-of-range coordinate (${lat}, ${lon})` } };
  }
  if (x < 0 || y < 0) return { skip: { row, reason: `negative pixel position (${x}, ${y})` } };
  return { point: { name, image_x: x, image_y: y, lat, lon } };
}

// ── CSV ──────────────────────────────────────────────────────────────────────
/** Minimal RFC-4180 field splitter: quoted fields, embedded commas and quotes. */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') {
      out.push(field);
      field = '';
    } else field += c;
  }
  out.push(field);
  return out;
}

export function parseGcpCsv(text: string): GcpImportResult {
  const lines = text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter((l) => l.trim() !== '');
  if (lines.length < 2) return { points: [], skipped: [{ row: 1, reason: 'no data rows' }] };

  const header = splitCsvLine(lines[0]).map(norm);
  const find = (keys: Set<string>): number => header.findIndex((h) => keys.has(h));

  // \u2605 THE FIELD TOOL'S PROJECT FORMAT (geolocation_gui `gcps.csv`):
  //   `id,name,u,v,lat,lon,offset_m,X,Y,Z,excluded,residual_px`. Recognised by its
  //   signature (`u`+`v`+`excluded`) and mapped DELIBERATELY, not by the generic
  //   header guesses below, because two of its columns are traps:
  //   - `X`/`Y` are UTM GROUND metres \u2014 the generic `x`/`y` vocabulary must never
  //     bind them as pixel positions (an Easting of 224949 is not a pixel);
  //   - `excluded=1` marks points the surveyor REJECTED from the pose solve there;
  //     importing them as good points would resurrect exactly the rows a human
  //     already judged wrong. They are skipped and each skip is named.
  //   `Z` is intentionally ignored: elevations here come from THIS project's DEM at
  //   commit time, one surface for every point \u2014 not from a foreign file.
  //   Names: the tool writes a generic `pt` on every row, so the distinct `id` is
  //   appended (`pt-14`) \u2014 a table of thirty rows all named "pt" identifies nothing.
  const isFieldToolProject =
    header.includes('u') && header.includes('v') && header.includes('excluded');

  const ix = isFieldToolProject ? header.indexOf('u') : find(X_KEYS);
  const iy = isFieldToolProject ? header.indexOf('v') : find(Y_KEYS);
  const ilat = find(LAT_KEYS);
  const ilon = find(LON_KEYS);
  const iname = find(NAME_KEYS);
  const iid = header.indexOf('id');
  const iexcluded = header.indexOf('excluded');
  if (ix < 0 || iy < 0 || ilat < 0 || ilon < 0) {
    const missing = [
      ix < 0 ? 'Image X' : null,
      iy < 0 ? 'Image Y' : null,
      ilat < 0 ? 'Latitude' : null,
      ilon < 0 ? 'Longitude' : null,
    ].filter(Boolean);
    return {
      points: [],
      skipped: [{ row: 1, reason: `missing column(s): ${missing.join(', ')}` }],
    };
  }

  const points: ImportedGcp[] = [];
  const skipped: SkippedRow[] = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cells = splitCsvLine(lines[i]);
    if (isFieldToolProject && iexcluded >= 0 && cells[iexcluded]?.trim() === '1') {
      skipped.push({
        row: i + 1,
        reason:
          'marked excluded in the source project \u2014 the surveyor rejected this point there',
      });
      continue;
    }
    let name = iname >= 0 ? cells[iname]?.trim() || null : null;
    if (isFieldToolProject && iid >= 0) {
      const id = cells[iid]?.trim();
      if (id) name = name ? `${name}-${id}` : `gcp-${id}`;
    }
    const verdict = validate(
      i + 1,
      name,
      finite(cells[ix]),
      finite(cells[iy]),
      finite(cells[ilat]),
      finite(cells[ilon]),
    );
    if (verdict.point) points.push(verdict.point);
    else if (verdict.skip) skipped.push(verdict.skip);
  }
  return { points, skipped };
}

// ── GeoJSON ──────────────────────────────────────────────────────────────────
export function parseGcpGeojson(text: string): GcpImportResult {
  let doc: unknown;
  try {
    doc = JSON.parse(text.replace(/^\uFEFF/, ''));
  } catch {
    return { points: [], skipped: [{ row: 1, reason: 'not valid JSON' }] };
  }
  const features: unknown[] = Array.isArray((doc as { features?: unknown[] })?.features)
    ? (doc as { features: unknown[] }).features
    : [];
  if (features.length === 0) {
    return { points: [], skipped: [{ row: 1, reason: 'no features in the file' }] };
  }

  const points: ImportedGcp[] = [];
  const skipped: SkippedRow[] = [];
  features.forEach((raw, index) => {
    const f = raw as {
      geometry?: { type?: string; coordinates?: unknown[] };
      properties?: Record<string, unknown>;
    };
    const row = index + 1;
    if (f?.geometry?.type !== 'Point' || !Array.isArray(f.geometry.coordinates)) {
      skipped.push({ row, reason: 'not a Point feature' });
      return;
    }
    const [lonRaw, latRaw] = f.geometry.coordinates;
    const props = f.properties ?? {};
    // Accept the export's names first, then the same vocabulary the CSV headers use.
    const byKeys = (keys: Set<string>): unknown => {
      for (const [k, v] of Object.entries(props)) if (keys.has(norm(k))) return v;
      return undefined;
    };
    const nameRaw = byKeys(NAME_KEYS);
    const verdict = validate(
      row,
      typeof nameRaw === 'string' && nameRaw.trim() !== '' ? nameRaw.trim() : null,
      finite(byKeys(X_KEYS)),
      finite(byKeys(Y_KEYS)),
      finite(latRaw),
      finite(lonRaw),
    );
    if (verdict.point) points.push(verdict.point);
    else if (verdict.skip) skipped.push(verdict.skip);
  });
  return { points, skipped };
}

/** Dispatch on filename. `.json` is treated as GeoJSON. */
export function parseGcpFile(filename: string, text: string): GcpImportResult {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.geojson') || lower.endsWith('.json')) return parseGcpGeojson(text);
  return parseGcpCsv(text);
}
