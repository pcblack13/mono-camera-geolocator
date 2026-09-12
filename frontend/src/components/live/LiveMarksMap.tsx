/**
 * `live/LiveMarksMap.tsx` — where the detected objects ARE, while the stream runs.
 *
 * ★ THE MAP IS THE PRODUCT of the detection pipeline: a box on a video says "I see
 *   a car"; the mark says "the car is HERE". This is the standalone tool's live map,
 *   rebuilt on this app's own tile proxy so the provider allow-list, cache and
 *   usage ledger all stay in force.
 *
 * ★ Marks are coloured by class and dimmed by age — the newest sighting of a moving
 *   object matters most, but the trail it leaves IS the route it travelled, so old
 *   marks fade rather than vanish.
 *
 * ★ Loaded lazily by the tab (Leaflet is heavy and most live sessions never detect).
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
// ★ THE LINE WHOSE ABSENCE DESTROYED THE PAGE. Leaflet positions tiles with its own
//   stylesheet; without it they render unclipped, in normal flow, painting a tile
//   grid across the whole tab. Every map component imports it for itself because no
//   map can assume another one loaded first — this one is lazy-loaded on a page
//   where it is the ONLY map, so there is no other.
import 'leaflet/dist/leaflet.css';
import {
  CircleMarker,
  MapContainer,
  Marker,
  TileLayer,
  Tooltip as LeafletTooltip,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';

import { API_BASE_URL } from '../../api/client';
import { LtrIsland } from '../common/LtrIsland';
import { GLOBE, ON_MEDIA, ON_MEDIA_SHADOW } from '../../theme/paint';
import type { DetectionMark } from '../../api/detection';
import type { ProviderInfo } from '../../types/geo';
import { proxyTileUrl } from '../map/tileMath';
import { detectionMarkColour, detectionTrackColour } from '../../theme/dataColors';
import { t } from '../../i18n';

export interface LiveMarksMapProps {
  marks: readonly DetectionMark[];
  /** The map recentres on the LUT's footprint once, when it is known. */
  center: [number, number] | null;
  /**
   * ★ The WHOLE provider, not a name + tile size. The first version hardcoded the
   *   zoom range (1–19) — outside the provider's REAL range the proxy answers every
   *   request with its "Map data not yet available" placeholder, which read as a
   *   broken map. The provider declares what it serves; the map obeys the
   *   declaration, exactly as the picking page's satellite pane does.
   */
  provider: ProviderInfo;
  /**
   * ★ SELECTION, FROM EITHER SIDE. The monitor page highlights the mark a chosen
   *   detection produced, and reports a marker click back so the video overlay and
   *   the table can follow. A map click never re-centres the map — the centre is the
   *   user's the moment they touch it (CenterOnce), and selection must not steal it.
   */
  selectedIndex?: number | null;
  onSelect?: (index: number) => void;
  /**
   * ★ The floor under the map's height. The live tab's row needs one (360, the
   *   default) because its parent takes height from content; the monitor's DECK
   *   must pass 0 — the deck's own height is the law there, and a 360px floor in
   *   a shorter pane made the map spill out of the deck over what sat below it.
   */
  minHeight?: number;
  /**
   * ★ LIVE PREDICT (2026-09-10): where the pixel under the operator's cursor on
   *   the video lands, read through the camera's lookup table. Drawn as a faint
   *   reticle — a look, never a mark — and the map pans just enough to keep it
   *   in view; it never re-centres a view the operator is holding.
   */
  prediction?: { lat: number; lon: number } | null;
  predictionPinned?: boolean;
}

const RETICLE = 28;

function reticleIcon(color: string, pinned: boolean): L.DivIcon {
  const c = RETICLE / 2;
  const r = c - 4;
  const svg = `
    <svg width="${RETICLE}" height="${RETICLE}" viewBox="0 0 ${RETICLE} ${RETICLE}" style="opacity:${pinned ? 1 : 0.8}">
      <circle cx="${c}" cy="${c}" r="${r}" fill="${pinned ? color : 'none'}" fill-opacity="0.18" stroke="${color}" stroke-width="${pinned ? 2.5 : 1.5}" />
      <line x1="${c}" y1="${c - r - 2}" x2="${c}" y2="${c - r + 4}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c}" y1="${c + r - 4}" x2="${c}" y2="${c + r + 2}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c - r - 2}" y1="${c}" x2="${c - r + 4}" y2="${c}" stroke="${color}" stroke-width="1.5" />
      <line x1="${c + r - 4}" y1="${c}" x2="${c + r + 2}" y2="${c}" stroke="${color}" stroke-width="1.5" />
      <circle cx="${c}" cy="${c}" r="1.8" fill="${color}" />
    </svg>`;
  return L.divIcon({
    className: 'le-live-prediction',
    html: svg,
    iconSize: [RETICLE, RETICLE],
    iconAnchor: [c, c],
  });
}

// ★ The reticle GLIDES between readings: Leaflet places markers with a transform,
//   so a short linear transition on it (matching the lookup cadence) turns the
//   80 ms steps into continuous motion. Leaflet's own zoom transition is restated
//   for this class so zooming stays exactly as it was.
const RETICLE_GLIDE = {
  '& .le-live-prediction': { transition: 'transform 90ms linear' },
  '& .leaflet-zoom-anim .le-live-prediction': {
    transition: 'transform 0.25s cubic-bezier(0,0,0.25,1)',
  },
} as const;

/**
 * Keeps the reticle on screen with the SMALLEST animated pan (2026-09-10, owner
 * ask: "smoother"). `panInside` moves the map only as far as it takes to bring
 * the point back inside the padded view — never re-centres — and a short eased
 * pan replaces the snap. A new reading during a pan restarts it from where the
 * map is, so a cursor sweeping across the picture reads as one glide.
 */
function KeepInView({ point }: { point: { lat: number; lon: number } | null }): null {
  const map = useMap();
  useEffect(() => {
    if (point === null) return;
    map.panInside(L.latLng(point.lat, point.lon), {
      padding: [56, 56],
      animate: true,
      duration: 0.25,
      easeLinearity: 0.35,
      noMoveStart: true,
    });
  }, [map, point]);
  return null;
}

/**
 * Fly to the site ONCE — then never touch the view again.
 *
 * ★ THE PAN/ZOOM CRASH LIVED HERE. The first version re-ran on every centre change,
 *   and the centre was derived from the NEWEST mark — so every poll called
 *   `setView` while the surveyor was mid-gesture, which is the classic way to kill
 *   a Leaflet map (and at best yanked the view away every 500 ms). A map is the
 *   user's the moment they touch it; the app gets to aim it exactly once.
 */
function CenterOnce({ center, zoom }: { center: [number, number] | null; zoom: number }): null {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || center === null) return;
    done.current = true;
    map.setView(center, zoom, { animate: false });
  });
  return null;
}

/**
 * Mirror of SatelliteMap's watcher: re-measure when the box changes size.
 * The container is `height: 100%`, so its PARENT is watched too — and the
 * fullscreen toggle is exactly the resize this exists to catch.
 */
function InvalidateSizeWatcher(): null {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const resize = (): void => {
      map.invalidateSize({ animate: false });
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    if (el.parentElement) ro.observe(el.parentElement);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

export function LiveMarksMap({
  marks,
  center,
  provider,
  selectedIndex = null,
  onSelect,
  minHeight = 360,
  prediction = null,
  predictionPinned = false,
}: LiveMarksMapProps): JSX.Element {
  // ★ ONE ICON PER STATE, NOT ONE PER RENDER. A fresh divIcon every render made
  //   react-leaflet call setIcon on every reading, which rebuilt the marker's DOM
  //   node — so the reticle blinked into each new place. A stable icon keeps the
  //   node, and the CSS transition below lets it glide between readings.
  const reticle = useMemo(() => reticleIcon(GLOBE.live, predictionPinned), [predictionPinned]);
  const caps = provider.capabilities;
  // ★ 512-px tiles require `zoomOffset: -1` — the PAIR rule; SatelliteMap documents it.
  const zoomShift = caps.tile_size_px === 512 ? 1 : 0;
  const minZoom = caps.min_zoom + zoomShift;
  const maxZoom = caps.max_zoom + zoomShift;
  // ★ EVERY MARK, not the newest 400. The cap was there because thousands of SVG
  //   circles kill Leaflet — but a run's marks ARE its result, and a map that
  //   quietly forgot the first two-thirds of a clip misrepresented it (2026-08-28).
  //   The container draws paths on CANVAS instead (`preferCanvas`), where
  //   thousands of circles are one bitmap and cost nothing to hit-test.
  const drawn = marks;
  const newestIndex = drawn.length - 1;

  // ★ EACH TRACK ITS OWN HUE (2026-09-01). Two tracked cars are the same class,
  //   so class-colouring painted both trails identically — the map could not say
  //   which route was whose. Tracked marks colour by identity; untracked
  //   sightings keep their class hue. The legend below names the mapping.
  const trackIds: number[] = [];
  for (const m of drawn) {
    if (m.track_id !== null && !trackIds.includes(m.track_id)) trackIds.push(m.track_id);
  }

  // ── fullscreen: the browser's own, on this box — same gesture as the player's ──
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const onChange = (): void => setFullscreen(document.fullscreenElement === boxRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);
  const toggleFullscreen = (): void => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else if (boxRef.current) {
      void boxRef.current.requestFullscreen();
    }
  };

  return (
    // ★ Leaflet island — the map's left-origin geometry must not mirror with the
    //   Arabic chrome. See LtrIsland.
    <LtrIsland>
      <Box
        ref={boxRef}
        sx={{
          // Fills whatever the parent gives it — the big side-by-side card and any
          // smaller embed share one component.
          position: 'relative',
          height: '100%',
          minHeight,
          borderRadius: 1,
          overflow: 'hidden',
          border: 1,
          borderColor: 'divider',
          bgcolor: 'background.default',
          ...RETICLE_GLIDE,
        }}
      >
        <MapContainer
          preferCanvas
          center={center ?? [20, 0]}
          zoom={center === null ? minZoom : Math.min(17, maxZoom)}
          minZoom={minZoom}
          maxZoom={maxZoom}
          attributionControl={false}
          zoomControl
          style={{ width: '100%', height: '100%' }}
        >
          <TileLayer
            key={provider.name}
            url={proxyTileUrl(API_BASE_URL, provider.name, 'satellite')}
            minZoom={minZoom}
            maxNativeZoom={maxZoom}
            maxZoom={maxZoom}
            tileSize={caps.tile_size_px}
            zoomOffset={-zoomShift}
            attribution=""
          />
          <CenterOnce center={center} zoom={Math.min(17, maxZoom)} />
          <InvalidateSizeWatcher />
          <KeepInView point={prediction} />
          {prediction !== null && (
            <Marker
              position={[prediction.lat, prediction.lon]}
              icon={reticle}
              interactive={false}
              keyboard={false}
              zIndexOffset={1000}
            />
          )}
          {/* ★ A detection without a position is a real sighting (an embedded
              board sends them while its lookup table cannot place them), but it
              is not a place — the attribute table lists it; the map cannot. */}
          {drawn.map((mark, i) => {
            if (mark.lat === null || mark.lon === null) return null;
            const lat = mark.lat;
            const lon = mark.lon;
            const hue = detectionMarkColour(mark.cls_name, mark.track_id);
            return (
              <CircleMarker
                key={`${mark.frame_index}:${mark.u}:${mark.v}:${i}`}
                center={[lat, lon]}
                radius={i === selectedIndex ? 9 : i === newestIndex ? 7 : 4}
                pathOptions={{
                  color: i === selectedIndex ? ON_MEDIA : hue,
                  fillColor: hue,
                  // age fades the trail; the newest mark is solid; the selected one is ringed
                  fillOpacity:
                    i === selectedIndex ? 0.9 : 0.25 + 0.6 * (i / Math.max(1, newestIndex)),
                  opacity: i === selectedIndex ? 1 : 0.4 + 0.6 * (i / Math.max(1, newestIndex)),
                  weight: i === selectedIndex ? 3 : 1,
                }}
                eventHandlers={onSelect ? { click: () => onSelect(i) } : undefined}
              >
                <LeafletTooltip>
                  {mark.cls_name}
                  {mark.track_id !== null ? ` #${mark.track_id}` : ''}{' '}
                  {(100 * mark.score).toFixed(0)}% · {lat.toFixed(6)}, {lon.toFixed(6)}
                </LeafletTooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
        {/* ★ The legend that makes the hues readable: which colour is which track.
            Bottom-left, above Leaflet's panes; capped so twenty tracks do not
            wallpaper the map — the tooltip on every mark still names its track. */}
        {trackIds.length > 0 && (
          <Box
            sx={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              zIndex: 1100,
              display: 'flex',
              alignItems: 'center',
              gap: 0.75,
              flexWrap: 'wrap',
              maxWidth: '70%',
              px: 1,
              py: 0.5,
              borderRadius: 1,
              bgcolor: 'background.paper',
              border: 1,
              borderColor: 'divider',
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
            }}
          >
            <Box component="span" sx={{ color: 'text.secondary' }}>
              {t('Tracks')}
            </Box>
            {trackIds.slice(0, 8).map((id) => (
              <Box
                key={id}
                component="span"
                sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
              >
                <Box
                  component="span"
                  sx={{
                    width: 9,
                    height: 9,
                    borderRadius: '50%',
                    bgcolor: detectionTrackColour(id),
                    border: `1px solid ${ON_MEDIA_SHADOW}`,
                    flexShrink: 0,
                  }}
                />
                #{id}
              </Box>
            ))}
            {trackIds.length > 8 && (
              <Box component="span" sx={{ color: 'text.secondary' }}>
                +{trackIds.length - 8}
              </Box>
            )}
          </Box>
        )}
        {/* Above Leaflet's panes (z ≤ 1000) so the button survives every zoom level. */}
        <Tooltip title={fullscreen ? 'Exit full screen' : 'Full screen'}>
          <IconButton
            size="small"
            onClick={toggleFullscreen}
            aria-label={fullscreen ? 'Exit full screen' : 'View map full screen'}
            sx={{
              'position': 'absolute',
              'top': 8,
              'right': 8,
              'zIndex': 1100,
              'bgcolor': 'background.paper',
              'border': 1,
              'borderColor': 'divider',
              '&:hover': { bgcolor: 'background.paper' },
            }}
          >
            {fullscreen ? (
              <FullscreenExitIcon fontSize="small" />
            ) : (
              <FullscreenIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
      </Box>
    </LtrIsland>
  );
}

export default LiveMarksMap;
