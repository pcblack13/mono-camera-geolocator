/**
 * `map/MapAccuracyReadout.tsx` (pure, added) — SCOPE.md §5's honesty-at-the-cursor.
 *
 * ★ SCOPE.md §5, verbatim on manual mode: show *"a zoom-level readout, and the
 *   ground-sample-distance / achievable-accuracy at the current zoom shown honestly to
 *   the surveyor as they click."* This is that readout.
 *
 * ★ **Every figure here is a live PREVIEW, labelled as such.** The authoritative
 *   `GcpAccuracy` is computed server-side on commit from the imagery GSD and click
 *   precision (`gis/accuracy.py`). This tells the surveyor whether the CURRENT zoom is
 *   good enough *before* they click — zooming in visibly tightens the number, which is
 *   the honest incentive to zoom before committing.
 *
 * ★ It never over-claims: the "±" figure is a CE90 in true ground metres combining the
 *   click term and the provider's georeferencing error (`estimateClickAccuracy`), on
 *   the same scale as the row that will land. `dominant_term` names what limits it.
 *
 * **Pure.** No store, no Leaflet — numbers in, chips out.
 */

import Box from '@mui/material/Box';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import type { ClickAccuracyEstimate } from './tileMath';

export interface MapAccuracyReadoutProps {
  zoom: number;
  estimate: ClickAccuracyEstimate;
  /** Emphasise the readout while a correspondence is awaiting the map click. */
  active: boolean;
}

function fmtMetres(m: number): string {
  if (!Number.isFinite(m)) return '—';
  if (m < 1) return `${(m * 100).toFixed(0)} cm`;
  if (m < 10) return `${m.toFixed(1)} m`;
  return `${m.toFixed(0)} m`;
}

const DOMINANT_LABEL: Record<ClickAccuracyEstimate['dominant_term'], string> = {
  landmark_click: 'limited by your click at this zoom — zoom in to tighten it',
  georeference: "limited by the basemap's georeferencing, not your click",
};

export function MapAccuracyReadout({
  zoom,
  estimate,
  active,
}: MapAccuracyReadoutProps): JSX.Element {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1,
        py: 0.5,
        borderRadius: 1,
        bgcolor: 'background.paper',
        boxShadow: 2,
        border: active ? 2 : 0,
        borderColor: 'primary.main',
      }}
    >
      <Typography variant="mono" sx={{ fontSize: 12 }} aria-label={`Zoom level ${zoom.toFixed(1)}`}>
        z{zoom.toFixed(zoom % 1 === 0 ? 0 : 1)}
      </Typography>

      <Tooltip title="Ground distance spanned by one screen pixel at this zoom and latitude.">
        <Typography variant="mono" sx={{ fontSize: 12, color: 'text.secondary' }}>
          GSD {fmtMetres(estimate.mpp_m)}/px
        </Typography>
      </Tooltip>

      <Tooltip
        title={`Estimated positional accuracy (CE90) of a click here — ${DOMINANT_LABEL[estimate.dominant_term]}. The final value is computed on the server when you commit.`}
      >
        <Typography
          variant="mono"
          sx={{ fontSize: 12, fontWeight: 600, color: active ? 'primary.main' : 'text.primary' }}
        >
          ±{fmtMetres(estimate.total_ce90_m)} est.
        </Typography>
      </Tooltip>
    </Box>
  );
}
