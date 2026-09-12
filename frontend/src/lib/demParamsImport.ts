/**
 * `demParamsImport` — read a DEM AOI from a file the surveyor already has.
 *
 * ★ WHY: the DEM page asks for a camera station (lat/lon/radius) or ≥3 AOI corners,
 *   and until 1.2.6 every one had to be hand-typed. Field crews already hold those
 *   numbers — in a calibration CSV, a JSON config, or a GeoJSON drawn in QGIS — so
 *   this parses the common shapes into the same values the form holds. No format is
 *   privileged: the extension only picks which reader to TRY first; a mislabelled
 *   file still parses if its content is recognisable.
 *
 * Recognised:
 *   - CSV / TSV / TXT, `key,value` per line — camera_lat|lat, camera_lon|lon,
 *     radius_m|radius, tolerance_pct, target_srid|epsg; OR two numeric columns
 *     per line read as a `lat,lon` corner list (≥3 rows → an AOI).
 *   - JSON — `{camera_lat, camera_lon, radius_m?, corners?:[{lat,lon}], ...}`.
 *   - GeoJSON — a Point (→ camera station) or a Polygon (→ AOI corners).
 */

export interface DemParamsImport {
  camera?: { lat: number; lon: number; radius_m?: number };
  corners?: { lat: number; lon: number }[];
  tolerance_pct?: number;
  target_srid?: number;
  /** Non-fatal notes (e.g. "radius not found — enter it manually"). */
  warnings: string[];
}

export class DemParamsParseError extends Error {}

const KEY_ALIASES: Record<
  string,
  keyof DemParamsImport | 'lat' | 'lon' | 'radius' | 'tolerance' | 'srid'
> = {
  camera_lat: 'lat',
  lat: 'lat',
  latitude: 'lat',
  camera_lon: 'lon',
  lon: 'lon',
  lng: 'lon',
  longitude: 'lon',
  radius_m: 'radius',
  radius: 'radius',
  tolerance_pct: 'tolerance',
  tolerance: 'tolerance',
  target_srid: 'srid',
  srid: 'srid',
  epsg: 'srid',
};

function num(value: unknown): number | null {
  const n = typeof value === 'string' ? Number(value.trim()) : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Pull a corner list out of a GeoJSON-style ring `[[lon,lat], …]`. */
function ringToCorners(ring: unknown): { lat: number; lon: number }[] {
  if (!Array.isArray(ring)) return [];
  const out: { lat: number; lon: number }[] = [];
  for (const pt of ring) {
    if (Array.isArray(pt) && pt.length >= 2) {
      const lon = num(pt[0]);
      const lat = num(pt[1]);
      if (lat !== null && lon !== null) out.push({ lat, lon });
    }
  }
  // A GeoJSON ring repeats its first point last — drop the duplicate.
  if (out.length > 1) {
    const a = out[0];
    const b = out[out.length - 1];
    if (a.lat === b.lat && a.lon === b.lon) out.pop();
  }
  return out;
}

function firstGeometry(obj: Record<string, unknown>): Record<string, unknown> | null {
  const type = obj.type;
  if (type === 'FeatureCollection' && Array.isArray(obj.features) && obj.features.length > 0) {
    const feat = obj.features[0] as Record<string, unknown>;
    return (feat.geometry as Record<string, unknown>) ?? null;
  }
  if (type === 'Feature') return (obj.geometry as Record<string, unknown>) ?? null;
  if (type === 'Point' || type === 'Polygon') return obj;
  return null;
}

function fromJson(text: string): DemParamsImport | null {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    return null; // not JSON — let the CSV reader try
  }
  if (obj === null || typeof obj !== 'object') return null;
  const record = obj as Record<string, unknown>;
  const result: DemParamsImport = { warnings: [] };

  // GeoJSON first.
  const geom = firstGeometry(record);
  if (geom) {
    if (geom.type === 'Point' && Array.isArray(geom.coordinates)) {
      const lon = num(geom.coordinates[0]);
      const lat = num(geom.coordinates[1]);
      if (lat !== null && lon !== null) {
        result.camera = { lat, lon };
        result.warnings.push(
          'Camera position read from the GeoJSON point — enter the working radius.',
        );
        return result;
      }
    }
    if (geom.type === 'Polygon' && Array.isArray(geom.coordinates)) {
      const corners = ringToCorners(geom.coordinates[0]);
      if (corners.length >= 3) {
        result.corners = corners.slice(0, 4);
        if (corners.length > 4)
          result.warnings.push(`Polygon had ${corners.length} corners; the first 4 were used.`);
        return result;
      }
    }
    throw new DemParamsParseError('the GeoJSON has no usable Point or Polygon geometry.');
  }

  // Plain config object.
  const lat = num(record.camera_lat ?? record.lat);
  const lon = num(record.camera_lon ?? record.lon);
  const radius = num(record.radius_m ?? record.radius);
  if (lat !== null && lon !== null) {
    result.camera = { lat, lon, ...(radius !== null ? { radius_m: radius } : {}) };
    if (radius === null) result.warnings.push('No radius in the file — enter the working radius.');
  }
  if (Array.isArray(record.corners)) {
    const corners = record.corners
      .map((c) => {
        const r = c as Record<string, unknown>;
        const clat = num(r.lat ?? r.latitude);
        const clon = num(r.lon ?? r.lng ?? r.longitude);
        return clat !== null && clon !== null ? { lat: clat, lon: clon } : null;
      })
      .filter((c): c is { lat: number; lon: number } => c !== null);
    if (corners.length >= 3) result.corners = corners.slice(0, 4);
  }
  const tol = num(record.tolerance_pct ?? record.tolerance);
  if (tol !== null) result.tolerance_pct = tol;
  const srid = num(record.target_srid ?? record.srid ?? record.epsg);
  if (srid !== null) result.target_srid = srid;

  if (!result.camera && !result.corners) return null;
  return result;
}

function fromDelimited(text: string): DemParamsImport {
  const result: DemParamsImport = { warnings: [] };
  const rows: [number, number][] = [];
  const kv: Record<string, number> = {};

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === '' || line.startsWith('#') || line.startsWith('//')) continue;
    const cells = line.split(/[,;\t]/).map((c) => c.trim());
    if (cells.length < 2) continue;

    const key = cells[0].toLowerCase();
    const alias = KEY_ALIASES[key];
    const value = num(cells[1]);
    if (alias && value !== null) {
      kv[alias] = value;
      continue;
    }
    // Two numeric columns with no known key → a bare lat,lon corner.
    const a = num(cells[0]);
    const b = num(cells[1]);
    if (a !== null && b !== null) rows.push([a, b]);
  }

  if (kv.lat !== undefined && kv.lon !== undefined) {
    result.camera = {
      lat: kv.lat,
      lon: kv.lon,
      ...(kv.radius !== undefined ? { radius_m: kv.radius } : {}),
    };
    if (kv.radius === undefined)
      result.warnings.push('No radius in the file — enter the working radius.');
  } else if (rows.length >= 3) {
    // Bare coordinate list — assume lat,lon (the app's own export order).
    result.corners = rows.slice(0, 4).map(([lat, lon]) => ({ lat, lon }));
    if (rows.length > 4)
      result.warnings.push(
        `${rows.length} coordinate rows found; the first 4 were used as AOI corners.`,
      );
  }
  if (kv.tolerance !== undefined) result.tolerance_pct = kv.tolerance;
  if (kv.srid !== undefined) result.target_srid = kv.srid;

  if (!result.camera && !result.corners) {
    throw new DemParamsParseError(
      'no camera position or AOI corners found. Expected key,value rows ' +
        '(camera_lat, camera_lon, radius_m) or ≥3 lat,lon rows.',
    );
  }
  return result;
}

/**
 * Parse a DEM-parameter file. `filename` only chooses which reader to try first;
 * content decides. Throws `DemParamsParseError` with a readable message on failure.
 */
export function parseDemParams(filename: string, text: string): DemParamsImport {
  const ext = filename.includes('.') ? filename.split('.').pop()!.toLowerCase() : '';
  const jsonFirst = ext === 'json' || ext === 'geojson';

  if (jsonFirst) {
    const viaJson = fromJson(text);
    if (viaJson) return viaJson;
    throw new DemParamsParseError('the file is not valid JSON/GeoJSON, or holds no camera/AOI.');
  }
  // CSV/TXT and everything else: JSON is still tried (a .txt may hold JSON), then delimited.
  return fromJson(text) ?? fromDelimited(text);
}
