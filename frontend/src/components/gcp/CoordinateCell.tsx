/**
 * `gcp/CoordinateCell.tsx` (pure) — a Latitude or Longitude cell. 50-frontend §2.22, §8.7.
 *
 * ★★ THE PRECISION-TRUNCATION POLICY (§8.7) is applied through `lib/geo/format.ts`, the
 *    single owner of it. **A decimal digit is a claim about accuracy** — printing
 *    `41.8721943` for a fix that could be 50 m off is a fabricated precision claim in
 *    the data itself. The displayed decimals are a function of `total_ce90_m` and the
 *    band; the FULL precision stays in the `title` (hover) and in exports — we truncate
 *    the CLAIM, never the DATUM.
 *
 * ★ UTM: the Latitude cell shows Northing, the Longitude cell Easting (labelled N/E),
 *   derived display-only via `toUtm`; outside UTM's ±80/84° range it falls back to
 *   decimal degrees rather than rendering nothing.
 *
 * **Pure.**
 */

import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

import type { CoordinateFormat } from '../../types/common';
import type { ConfidenceBand } from '../../types/gcp';
import type { LatLon } from '../../types/geo';
import { formatAccuracy, formatLatLon, metreDecimals, toUtm } from '../../lib/geo/format';

export interface CoordinateCellProps {
  p: LatLon;
  axis: 'lat' | 'lon';
  format: CoordinateFormat;
  /** `GcpRead.accuracy.total_ce90_m` — the headline CE90 that gates the digits. */
  total_ce90_m: number;
  band: ConfidenceBand;
}

/** ★ Six degree decimals (~0.11 m), fixed for every row — see `formatLatLon`. */
const TABLE_DEGREE_DECIMALS = 6;

export function CoordinateCell({
  p,
  axis,
  format,
  total_ce90_m,
  band,
}: CoordinateCellProps): JSX.Element {
  const raw = axis === 'lat' ? p.lat : p.lon;
  const title = `Full precision: ${raw} · estimated error ${formatAccuracy(total_ce90_m)}.`;

  // ★ DD+UTM+Z: stack decimal degrees (top) over the UTM northing/easting (below). The UTM
  //   zone and the Z elevation are their own columns (see GcpTableRow).
  if (format === 'ddutmz') {
    const dd = formatLatLon(p, 'dd', total_ce90_m, band, TABLE_DEGREE_DECIMALS);
    const ddText = (axis === 'lat' ? dd.lat_text : dd.lon_text) ?? dd.text;
    const u = toUtm(p);
    const d = metreDecimals(total_ce90_m);
    const utmText = u
      ? axis === 'lat'
        ? `N ${u.northing_m.toFixed(d)}`
        : `E ${u.easting_m.toFixed(d)}`
      : '—';
    return (
      <Box title={title}>
        <Typography variant="mono" sx={{ fontSize: 13, whiteSpace: 'nowrap', display: 'block' }}>
          {ddText}
        </Typography>
        <Typography
          variant="mono"
          sx={{ fontSize: 11, whiteSpace: 'nowrap', display: 'block', color: 'text.secondary' }}
        >
          {utmText}
        </Typography>
      </Box>
    );
  }

  const formatted = formatLatLon(p, format, total_ce90_m, band, TABLE_DEGREE_DECIMALS);

  let text: string;
  if (format === 'utm') {
    const u = toUtm(p);
    if (u) {
      const d = metreDecimals(total_ce90_m);
      text = axis === 'lat' ? `${u.northing_m.toFixed(d)} N` : `${u.easting_m.toFixed(d)} E`;
    } else {
      text = (axis === 'lat' ? formatted.lat_text : formatted.lon_text) ?? formatted.text;
    }
  } else {
    text = (axis === 'lat' ? formatted.lat_text : formatted.lon_text) ?? formatted.text;
  }

  return (
    <Typography variant="mono" sx={{ fontSize: 13, whiteSpace: 'nowrap' }} title={title}>
      {text}
    </Typography>
  );
}
