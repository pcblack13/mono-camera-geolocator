/**
 * `map/PredictionLayer.tsx` — the LIVE cursor-prediction ghost (1.2.6).
 *
 * ★ Draws where the auto-GCP locator thinks the pixel UNDER THE PHOTO CURSOR lands on the
 *   ground, updated as the surveyor moves the cursor. It is a look-only aid:
 *     - it reads `predictionStore` only, which holds a bare `LatLon` and can represent no
 *       GCP — so, like the correspondence draft, it can never leak into the table/export;
 *     - it is NON-INTERACTIVE (no drag, no click) and styled as a faint reticle, clearly
 *       not the solid committed markers nor the dashed correspondence draft;
 *     - it hides whenever a correspondence is open, so the two never fight for attention
 *       (during placement the correspondence draft is the one that matters).
 */

import { useMemo } from 'react';
import { Marker } from 'react-leaflet';
import L from 'leaflet';

import { usePredictionStore } from '../../store/predictionStore';
import { useCorrespondenceStore } from '../../store';

export interface PredictionLayerProps {
  /** The active-tool accent (the map already resolves `theme.palette.primary.main`). */
  activeColor: string;
}

const SIZE = 26;

function predictionIcon(color: string): L.DivIcon {
  const c = SIZE / 2;
  const r = SIZE / 2 - 4;
  // A faint reticle: thin ring + crosshair ticks + centre dot, half-opacity — reads as
  // "a live guess that follows your cursor", never a placed point.
  const svg = `
    <svg width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}" style="opacity:0.75">
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${color}" stroke-width="1.5" />
      <line x1="${c}" y1="${c - r - 2}" x2="${c}" y2="${c - r + 4}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c}" y1="${c + r - 4}" x2="${c}" y2="${c + r + 2}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c - r - 2}" y1="${c}" x2="${c - r + 4}" y2="${c}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c + r - 4}" y1="${c}" x2="${c + r + 2}" y2="${c}" stroke="${color}" stroke-width="1.5" />
      <circle cx="${c}" cy="${c}" r="1.6" fill="${color}" />
    </svg>`;
  return L.divIcon({
    className: 'le-prediction-marker',
    html: svg,
    iconSize: [SIZE, SIZE],
    iconAnchor: [c, c],
  });
}

export function PredictionLayer({ activeColor }: PredictionLayerProps): JSX.Element | null {
  const active = usePredictionStore((s) => s.active);
  const latLon = usePredictionStore((s) => s.latLon);
  const corrOpen = useCorrespondenceStore((s) => s.status !== 'idle');

  const icon = useMemo(() => predictionIcon(activeColor), [activeColor]);

  // Off, no estimate yet, or a correspondence is placing — draw nothing.
  if (!active || corrOpen || latLon === null) return null;

  return (
    <Marker
      position={[latLon.lat, latLon.lon]}
      icon={icon}
      interactive={false}
      keyboard={false}
      zIndexOffset={1500}
      alt="Live predicted ground position under the photo cursor"
    />
  );
}

export default PredictionLayer;
