/**
 * `map/CursorElevationReadout.tsx` (pure) — the Z under the cursor, or an honest reason.
 *
 * The vertical companion to {@link MapAccuracyReadout}. That chip answers *"how precise
 * is a click here?"*; this one answers *"what height will a GCP placed here be given?"* —
 * and, when the answer is nothing, says which kind of nothing it is.
 *
 * ★ **Four states, all rendered.** `no_dem` (attach one — a setup step the surveyor can
 *   take), `no_data` (a DEM is attached but has nothing at this spot), `loading`, and a
 *   value. A blank chip would conflate the first two, leaving someone hunting a coverage
 *   problem when they simply never attached a raster.
 *
 * ★ **The error bar travels with the number, always.** `elevation_ce90_m` is what makes
 *   an elevation a survey figure rather than a readout, and a height shown without it
 *   invites being treated as exact. When the provider gives no CE90 the chip says so
 *   rather than omitting the term — *"± unknown"* is a real statement, a missing ± is not.
 *
 * **Pure.** State in, chip out. No store, no fetch, no Leaflet.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import TerrainIcon from '@mui/icons-material/Terrain';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import type { CursorElevation } from '../../types/elevation';

export interface CursorElevationReadoutProps {
  elevation: CursorElevation;
}

/** Human labels for the `elevation_source` vocabulary (`gis.elevation.base`). */
const SOURCE_LABEL: Record<string, string> = {
  local_dem: 'your DEM',
  copernicus_dem: 'Copernicus DEM',
  srtm: 'SRTM',
  exif: 'photo EXIF',
  manual: 'entered by hand',
};

function body(elevation: CursorElevation): { text: string; tip: string; dim: boolean } | null {
  switch (elevation.kind) {
    case 'idle':
      return null;

    case 'loading':
      return { text: 'Z …', tip: 'Sampling this project’s DEM.', dim: true };

    case 'no_dem':
      return {
        text: 'Z — no DEM',
        tip:
          'This project has no elevation source, so GCPs placed here record a null Z ' +
          'rather than a guessed one. Attach a DEM in Project settings to populate it.',
        dim: true,
      };

    case 'no_data':
      return {
        text: 'Z — no data',
        tip:
          'A DEM is attached but has no value at this point — outside its coverage, or a ' +
          'nodata void. A GCP placed here records a null Z, never 0.',
        dim: true,
      };

    case 'value': {
      const ce90 =
        elevation.vertical_ce90_m !== null
          ? `± ${elevation.vertical_ce90_m.toFixed(1)} m`
          : '± unknown';
      const source = SOURCE_LABEL[elevation.source] ?? elevation.source;
      return {
        text: `Z ${elevation.elevation_m.toFixed(1)} m ${ce90}`,
        tip:
          `Elevation from ${source}, vertical CE90 ${ce90}. This is the height a GCP ` +
          `placed here would be given.`,
        dim: false,
      };
    }
  }
}

export function CursorElevationReadout({
  elevation,
}: CursorElevationReadoutProps): JSX.Element | null {
  const content = body(elevation);
  if (content === null) return null;

  return (
    <Tooltip title={content.tip} placement="top">
      <Box
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.75,
          px: 1,
          py: 0.5,
          borderRadius: 1,
          bgcolor: 'background.paper',
          boxShadow: 2,
          opacity: content.dim ? 0.7 : 1,
        }}
      >
        <TerrainIcon fontSize="small" sx={{ color: 'text.secondary' }} aria-hidden />
        <Typography
          variant="caption"
          sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap', fontWeight: 600 }}
        >
          {content.text}
        </Typography>
      </Box>
    </Tooltip>
  );
}
