/**
 * `map/GcpMarker.tsx` — one committed GCP on the satellite map. 50-frontend §2.17.
 *
 * ★ Renders a `Marker` (a Leaflet `divIcon`) filled with the CONFIDENCE colour, plus a
 *   `Circle` of `accuracy.total_ce90_m` metres — **the error circle is not decoration:
 *   it is the visual statement that a fix is a distribution, not a point.**
 *
 * ★ SCOPE.md §5 — SOURCE IS GLANCEABLE. A `manual` GCP carries the blue PROVENANCE
 *   ring (`MANUAL_SOURCE_COLOR`) so an observed coordinate can never be mistaken for
 *   an inferred one. Every GCP in this build is manual; the `automatic` branch exists
 *   only so the seam is real (SCOPE.md §7).
 *
 * ★ NEVER COLOUR ALONE (§8.8 item 6): the band's GLYPH and, for low/unreliable, a
 *   dashed ring ride alongside the colour, so the marker survives colour-blindness and
 *   a greyscale print.
 *
 * ★ Re-render discipline (§3.5): this component subscribes to `selectionStore` with a
 *   NARROW BOOLEAN selector, so selecting another point does not re-render this
 *   marker. The tree marks it "(pure)"; the narrow subscription is the correctness
 *   requirement §3.5 states, and it wins — the layer above stays a plain `.map`.
 */

import { useMemo } from 'react';
import { Circle, Marker } from 'react-leaflet';
import L from 'leaflet';

import type { ThemeMode } from '../../theme';
import {
  CONFIDENCE_ENCODING,
  MANUAL_SOURCE_COLOR,
  MARKER_OUTLINE,
  NO_RESULT_COLOR,
  confidenceColor,
  gcpConfidenceBand,
} from '../../theme';
import type { GcpRead } from '../../types/gcp';
import { isHoveredSelector, isSelectedSelector, useSelectionStore } from '../../store';
import type { SelectionMode } from '../../store';
import { t } from '../../i18n';
import { readableOn } from '../../lib/contrast';

export interface GcpMarkerProps {
  gcp: GcpRead;
  themeMode: ThemeMode;
  /**
   * One colour for every marker on the MAP. NULL — the default — colours each by its
   * CONFIDENCE BAND, which is what makes the map readable at a glance. A chosen
   * colour replaces that reading; the band's glyph and dash pattern still carry it.
   * A point's own colour (`pointColors`) beats both.
   */
  mapColor?: string | null;
  onSelect: (id: string, mode: SelectionMode, linkedId: string | null) => void;
  onHover: (ref: { id: string; linkedId: string | null } | null) => void;
}

const BADGE = 26;

/** Builds the `divIcon` HTML for a committed GCP. Pure string assembly. */
function buildIcon(
  gcp: GcpRead,
  mode: ThemeMode,
  selected: boolean,
  hovered: boolean,
  mapColor: string | null,
): L.DivIcon {
  const band = gcpConfidenceBand(gcp);
  const enc = CONFIDENCE_ENCODING[band];
  const fill = mapColor ?? confidenceColor(band, mode);
  const outline = MARKER_OUTLINE[mode];
  const provenance = gcp.source === 'manual' ? MANUAL_SOURCE_COLOR[mode] : NO_RESULT_COLOR[mode];
  const ringDash = enc.dash ? `stroke-dasharray="${enc.dash}"` : '';
  const staleOpacity = gcp.is_stale ? 0.5 : 1;
  const halo = selected
    ? `box-shadow: 0 0 0 3px ${provenance}, 0 0 8px 3px rgba(0,0,0,0.45);`
    : hovered
      ? `box-shadow: 0 0 0 2px ${provenance};`
      : '';
  const label = gcp.code ?? '';

  // The provenance ring is the OUTER stroke; the marker body is the band colour; the
  // glyph is the band symbol. `manually_adjusted` adds a small caret badge (§2.17).
  const svg = `
    <svg width="${BADGE}" height="${BADGE}" viewBox="0 0 ${BADGE} ${BADGE}" style="opacity:${staleOpacity}">
      <circle cx="${BADGE / 2}" cy="${BADGE / 2}" r="${BADGE / 2 - 3}"
              fill="${fill}" stroke="${provenance}" stroke-width="3" ${ringDash} />
      <circle cx="${BADGE / 2}" cy="${BADGE / 2}" r="${BADGE / 2 - 1.5}"
              fill="none" stroke="${outline}" stroke-width="1" />
      <text x="${BADGE / 2}" y="${BADGE / 2 + 3.5}" text-anchor="middle"
            font-size="10" fill="${outline}" font-family="system-ui, sans-serif">${enc.symbol}</text>
    </svg>`;

  const adjustedBadge = gcp.manually_adjusted
    ? `<span style="position:absolute;top:-4px;right:-4px;width:9px;height:9px;border-radius:50%;background:${provenance};border:1px solid ${outline}" title="${t('Manually adjusted')}"></span>`
    : '';

  const labelHtml = label
    ? `<span style="position:absolute;left:${BADGE + 3}px;top:50%;transform:translateY(-50%);
         white-space:nowrap;font:600 11px system-ui,sans-serif;color:${readableOn(outline)};
         background:${outline};padding:0 4px;border-radius:3px;box-shadow:0 1px 2px rgba(0,0,0,0.4)">${escapeHtml(label)}</span>`
    : '';

  return L.divIcon({
    className: 'le-gcp-marker',
    html: `<div style="position:relative;width:${BADGE}px;height:${BADGE}px;border-radius:50%;${halo}">${svg}${adjustedBadge}${labelHtml}</div>`,
    iconSize: [BADGE, BADGE],
    iconAnchor: [BADGE / 2, BADGE / 2],
  });
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '"' ? '&quot;' : '&#39;',
  );
}

export function GcpMarker({
  gcp,
  themeMode,
  mapColor = null,
  onSelect,
  onHover,
}: GcpMarkerProps): JSX.Element {
  const selected = useSelectionStore(isSelectedSelector(gcp.id));
  const hovered = useSelectionStore(isHoveredSelector(gcp.id));

  const icon = useMemo(
    () => buildIcon(gcp, themeMode, selected, hovered, mapColor),
    [gcp, themeMode, selected, hovered, mapColor],
  );

  const band = gcpConfidenceBand(gcp);
  const ringColor = mapColor ?? confidenceColor(band, themeMode);
  const linkedId = gcp.landmark_id ?? null;

  return (
    <>
      {Number.isFinite(gcp.accuracy.total_ce90_m) && gcp.accuracy.total_ce90_m > 0 ? (
        <Circle
          center={[gcp.lat, gcp.lon]}
          radius={gcp.accuracy.total_ce90_m}
          pathOptions={{
            color: ringColor,
            weight: 1,
            opacity: selected ? 0.9 : 0.5,
            fillOpacity: selected ? 0.12 : 0.05,
            // The circle is a passive uncertainty ring; clicks belong to the marker.
            interactive: false,
          }}
        />
      ) : null}
      <Marker
        position={[gcp.lat, gcp.lon]}
        icon={icon}
        // Selected markers win the stacking contest so a cluster cannot bury the one
        // the surveyor is inspecting.
        zIndexOffset={selected ? 1000 : hovered ? 500 : 0}
        keyboard
        alt={`Point ${gcp.code ?? gcp.id}`}
        eventHandlers={{
          click: (e) => {
            const oe = e.originalEvent;
            const mode: SelectionMode = oe.shiftKey
              ? 'range'
              : oe.metaKey || oe.ctrlKey
                ? 'add'
                : 'replace';
            onSelect(gcp.id, mode, linkedId);
          },
          mouseover: () => onHover({ id: gcp.id, linkedId }),
          mouseout: () => onHover(null),
        }}
      />
    </>
  );
}
