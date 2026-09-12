/**
 * `map/GcpOverviewMap.tsx` — EVERY GCP, EVERY PROJECT, ON ONE SATELLITE MAP.
 *
 * ★ THE DASHBOARD'S CENTREPIECE. Not a summary card and not a table: the first thing
 *   a surveyor sees on opening the app is *where their work is*, geographically.
 *
 * ★ TILES GO THROUGH THE BACKEND PROXY (L2, CONTRACT §7.2) — {@link proxyTileUrl},
 *   never a provider's upstream URL. That is what keeps API keys server-side, and it
 *   is as true on the dashboard as it is in the workspace. Default provider is the
 *   KEYLESS `esri_world_imagery`, so a fresh `docker compose up` with an empty `.env`
 *   renders this map.
 *
 * ★ IT DOES NOT TOUCH `mapStore`. That store is the WORKSPACE's view — the pane the
 *   photo is synchronised against (§8.5). If the dashboard wrote to it, opening the
 *   home page would silently move the surveyor's working view. This map owns its own
 *   uncontrolled view and fits to the data instead.
 *
 * ★ CONFIDENCE COLOURING MATCHES THE WORKSPACE (`theme/confidence`), including the
 *   band GLYPH and the manual-provenance ring, so a point does not change meaning
 *   between the two screens — and never colour alone (§8.8 item 6).
 */

import { useEffect, useMemo, useState, type JSX } from 'react';
import {
  CircleMarker,
  MapContainer,
  Marker,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import Box from '@mui/material/Box';
import { useTheme } from '@mui/material/styles';
import L from 'leaflet';

import 'leaflet/dist/leaflet.css';

import { API_BASE_URL } from '../../api/client';
import { LtrIsland } from '../common/LtrIsland';
import { CursorCoordinateReadout } from './CursorCoordinateReadout';
import { DrawingBanner } from './DrawingBanner';
import { OfflineCacheLayer } from './OfflineCacheLayer';
import { OfflineCachePanel } from './OfflineCachePanel';
import { useOfflineCacheStore } from '../../store/offlineCacheStore';
import { useWorkspaceStore } from '../../store/workspaceStore';
import {
  CONFIDENCE_ENCODING,
  MANUAL_SOURCE_COLOR,
  MARKER_OUTLINE,
  NO_RESULT_COLOR,
  confidenceBand,
  confidenceColor,
  type ThemeMode,
} from '../../theme';
import type { BasemapKind, LatLon, ProviderId } from '../../types/geo';
import type { GcpOverview } from '../../types/gcp';
import { proxyTileUrl } from './tileMath';

export interface GcpOverviewMapProps {
  points: readonly GcpOverview[];
  themeMode: ThemeMode;
  /** ★ Keyless default (L2). Overridable so a project's provider can drive it later. */
  providerId?: ProviderId;
  basemap?: BasemapKind;
  /** The provider's tile edge (`capabilities.tile_size_px`); 512 engages Leaflet's paired `zoomOffset: -1`. */
  tileSizePx?: number;
  onSelect: (gcp: GcpOverview) => void;
  /**
   * ★ A place to fly to, from the "Go to location" control. Carries a `nonce` so
   * that asking for the SAME coordinate twice still moves the map — a surveyor who
   * pans away and re-enters the same point expects to go back, and equal props
   * would otherwise be a no-op.
   */
  flyTo?: { at: LatLon; zoom: number; nonce: number } | null;
}

/**
 * Reports the pointer's world position (and null when it leaves).
 *
 * ★ No debounce and nothing fetched: this is a matrix transform Leaflet has already
 *   done, so it is free — unlike the DEM elevation sample on the workspace map,
 *   which is debounced precisely because it costs a raster read.
 */
function CursorReporter({ onMove }: { onMove: (at: LatLon | null) => void }): null {
  useMapEvents({
    mousemove: (e) => onMove({ lat: e.latlng.lat, lon: e.latlng.lng }),
    mouseout: () => onMove(null),
  });
  return null;
}

/** Imperatively flies the map when a new `flyTo` request arrives. */
function FlyTo({ target }: { target: GcpOverviewMapProps['flyTo'] }): null {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    map.flyTo([target.at.lat, target.at.lon], target.zoom, { duration: 0.8 });
  }, [map, target]);
  return null;
}

const BADGE = 22;

/** The same visual grammar as `GcpMarker`, at overview scale. */
function buildIcon(gcp: GcpOverview, mode: ThemeMode): L.DivIcon {
  const band = confidenceBand(gcp.confidence);
  const enc = CONFIDENCE_ENCODING[band];
  const fill = confidenceColor(band, mode);
  const outline = MARKER_OUTLINE[mode];
  const provenance = gcp.source === 'manual' ? MANUAL_SOURCE_COLOR[mode] : NO_RESULT_COLOR[mode];
  const ringDash = enc.dash ? `stroke-dasharray="${enc.dash}"` : '';

  const svg = `
    <svg width="${BADGE}" height="${BADGE}" viewBox="0 0 ${BADGE} ${BADGE}">
      <circle cx="${BADGE / 2}" cy="${BADGE / 2}" r="${BADGE / 2 - 2.5}"
              fill="${fill}" stroke="${provenance}" stroke-width="2.5" ${ringDash} />
      <circle cx="${BADGE / 2}" cy="${BADGE / 2}" r="${BADGE / 2 - 1}"
              fill="none" stroke="${outline}" stroke-width="1" />
      <text x="${BADGE / 2}" y="${BADGE / 2 + 3}" text-anchor="middle"
            font-size="9" fill="${outline}" font-family="system-ui, sans-serif">${enc.symbol}</text>
    </svg>`;

  return L.divIcon({
    className: 'le-gcp-overview-marker',
    html: `<div style="width:${BADGE}px;height:${BADGE}px">${svg}</div>`,
    iconSize: [BADGE, BADGE],
    iconAnchor: [BADGE / 2, BADGE / 2],
  });
}

/**
 * Fits the view to the data.
 *
 * ★ A single point cannot make a bounds rectangle, so it gets an explicit zoom
 *   instead — `fitBounds` on a degenerate box zooms to the map's maximum and drops
 *   the surveyor onto a blur.
 */
function FitToPoints({ points }: { points: readonly GcpOverview[] }): null {
  const map = useMap();

  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lon], 15);
      return;
    }
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number]));
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 16 });
  }, [map, points]);

  return null;
}

export function GcpOverviewMap({
  points,
  themeMode,
  providerId = 'esri_world_imagery',
  basemap = 'satellite',
  tileSizePx = 256,
  onSelect,
  flyTo = null,
}: GcpOverviewMapProps): JSX.Element {
  // ★ 512-px tiles and `zoomOffset: -1` are a PAIR in Leaflet — see the note in
  //   `SatelliteMap`. 256 alone stays geographically correct for a 512 provider (the
  //   image just renders into a smaller slot), but requests one zoom level deeper
  //   than needed: 4× the tiles, which is 4× the bill on per-tile providers (Mapbox).
  const zoomShift = tileSizePx === 512 ? 1 : 0;
  // ★ The seed view only ever shows for the instant before `FitToPoints` runs, and
  //   only matters when there are no points at all: a whole-world view, which is the
  //   honest picture of "nothing surveyed yet".
  const seed = useMemo(() => ({ center: [20, 0] as [number, number], zoom: 2 }), []);
  const theme = useTheme();
  // ★ Same two cues as the workspace map: a crosshair over the whole map and a
  //   banner, so "you are drawing an area" is visible BEFORE the first click.
  const cacheDrawing = useOfflineCacheStore((s) => s.drawing);
  const cachePoints = useOfflineCacheStore((s) => s.points.length);
  const coordinateFormat = useWorkspaceStore((s) => s.coordinateFormat);
  const [cursorAt, setCursorAt] = useState<LatLon | null>(null);

  return (
    // ★ Leaflet island — see LtrIsland: the map's geometry stays LTR under the
    //   mirrored Arabic chrome.
    <LtrIsland>
      <Box
        sx={{
          'position': 'relative',
          'width': '100%',
          'height': '100%',
          '& .leaflet-container': cacheDrawing ? { cursor: 'crosshair !important' } : undefined,
        }}
      >
        {cacheDrawing && <DrawingBanner count={cachePoints} />}
        <MapContainer
          center={seed.center}
          zoom={seed.zoom}
          minZoom={1}
          maxZoom={19}
          attributionControl={false}
          zoomControl
          style={{ width: '100%', height: '100%' }}
        >
          <TileLayer
            key={`${providerId}:${basemap}`}
            url={proxyTileUrl(API_BASE_URL, providerId, basemap)}
            minZoom={1}
            maxNativeZoom={19}
            maxZoom={19}
            tileSize={tileSizePx}
            zoomOffset={-zoomShift}
            attribution=""
          />
          <FitToPoints points={points} />
          <FlyTo target={flyTo} />
          <CursorReporter onMove={setCursorAt} />
          {/* ★ Draw an area to cache for offline use — same feature as the workspace map. */}
          <OfflineCacheLayer color={theme.palette.primary.main} />
          {points.map((gcp) => (
            <GcpOverviewPin key={gcp.id} gcp={gcp} themeMode={themeMode} onSelect={onSelect} />
          ))}
        </MapContainer>

        {/* ★ Bottom-left, clear of Leaflet's zoom control (top-left) and the cache
          panel (top-right); `pointerEvents: none` inside, so it never eats a click. */}
        <Box sx={{ position: 'absolute', left: 8, bottom: 8, zIndex: 1000 }}>
          <CursorCoordinateReadout at={cursorAt} format={coordinateFormat} />
        </Box>

        {/* Offline-cache control — floats top-right so it clears Leaflet's top-left zoom control. */}
        <Box sx={{ position: 'absolute', top: 8, right: 8, zIndex: 500 }}>
          <OfflineCachePanel
            providerId={providerId}
            kind={basemap}
            cacheable
            color={theme.palette.primary.main}
          />
        </Box>
      </Box>
    </LtrIsland>
  );
}

function GcpOverviewPin({
  gcp,
  themeMode,
  onSelect,
}: {
  gcp: GcpOverview;
  themeMode: ThemeMode;
  onSelect: (gcp: GcpOverview) => void;
}): JSX.Element {
  const icon = useMemo(() => buildIcon(gcp, themeMode), [gcp, themeMode]);
  const band = confidenceBand(gcp.confidence);
  const label = gcp.code ?? gcp.landmark_name ?? 'Point';

  return (
    <>
      {/* ★ The error circle is not decoration: a fix is a distribution, not a point.
          It is omitted entirely when the server has no CE90 — a zero-radius ring
          would read as perfect accuracy, the one lie this tool must not tell. */}
      {gcp.total_ce90_m !== null && gcp.total_ce90_m > 0 && (
        <CircleMarker
          center={[gcp.lat, gcp.lon]}
          radius={6}
          pathOptions={{
            color: confidenceColor(band, themeMode),
            weight: 1,
            opacity: 0.5,
            fillOpacity: 0.06,
            interactive: false,
          }}
        />
      )}
      <Marker
        position={[gcp.lat, gcp.lon]}
        icon={icon}
        keyboard
        alt={`${label} — ${gcp.project_name}`}
        eventHandlers={{ click: () => onSelect(gcp) }}
      >
        <Tooltip direction="top" offset={[0, -10]}>
          <strong>{label}</strong>
          <br />
          {gcp.project_name}
          <br />
          {gcp.image_filename}
          {gcp.total_ce90_m !== null && (
            <>
              <br />±{gcp.total_ce90_m.toFixed(1)} m (CE90)
            </>
          )}
        </Tooltip>
      </Marker>
    </>
  );
}

export default GcpOverviewMap;
