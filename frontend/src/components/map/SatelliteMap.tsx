/**
 * `map/SatelliteMap.tsx` — the react-leaflet `MapContainer`. 50-frontend §2.16, §3.6.
 *
 * ★ **2D ONLY** (task brief). Raster Leaflet, north-up; there is no bearing/tilt.
 *
 * ★ **UNCONTROLLED CONTAINER** (§3.6): `center`/`zoom` are INITIAL values only. The
 *   single source of truth is `mapStore.view`, reconciled by {@link MapViewSync} — a
 *   controlled `MapContainer` oscillates. The initial view is captured once, on mount.
 *
 * ★ **TILES COME FROM THE BACKEND PROXY** (L2, CONTRACT §7.2): the `TileLayer` URL is
 *   {@link proxyTileUrl}, never a provider's upstream URL — that is what keeps API
 *   keys server-side. Leaflet's own `AttributionControl` is DISABLED; attribution is a
 *   ToS obligation rendered by `ProviderAttribution` (always visible, non-dismissible).
 *
 * ★ Manual GCP mode: a map click is reported through `onMapClick` in EPSG:4326. The
 *   container's `maxZoom` is the provider's NATIVE max, so the ground-sample-distance
 *   readout stays honest — we do not over-zoom into upsampled tiles and imply a
 *   precision the imagery does not have.
 */

import { useEffect, useRef, useState } from 'react';
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import type { ReactNode } from 'react';

import 'leaflet/dist/leaflet.css';

import { API_BASE_URL } from '../../api/client';
import { LtrIsland } from '../common/LtrIsland';
import type { BasemapKind, LatLon, MapViewState, ProviderId, ViewOrigin } from '../../types/geo';
import { MapViewSync } from './MapViewSync';
import { beyondNativeResolution, proxyTileUrl } from './tileMath';
import { t } from '../../i18n';
import { ON_MEDIA, ON_MEDIA_LINK } from '../../theme/paint';

export interface SatelliteMapCapabilities {
  min_zoom: number;
  max_zoom: number;
  tile_size_px: number;
  /**
   * ★ Where NATIVE detail typically ends (provider zoom levels). `max_zoom` is what the
   * provider SERVES; above `native_max_zoom` the tiles are upsampled — sharp-looking
   * pixels carrying no new information. Null/undefined = unknown.
   */
  native_max_zoom?: number | null;
  /** How `native_max_zoom` was obtained (`known` / `estimated` / `unknown`). */
  native_resolution_status?: 'known' | 'estimated' | 'unknown';
}

export interface SatelliteMapProps {
  /** Captured once for the uncontrolled container; live view flows through `view`. */
  initialView: MapViewState;
  view: MapViewState;
  seq: number;
  lastOrigin: ViewOrigin;
  providerId: ProviderId;
  basemap: BasemapKind;
  capabilities: SatelliteMapCapabilities;
  reducedMotion: boolean;
  onViewChange: (view: MapViewState, origin: ViewOrigin) => void;
  /** A map click, EPSG:4326. Drives manual-mode placement (`correspondenceStore`). */
  onMapClick: (at: LatLon) => void;
  /**
   * Pointer position, EPSG:4326 — `null` when the pointer leaves the map.
   *
   * ★ Raw and undebounced: this component reports what Leaflet tells it and makes no
   * policy decision about rate. The consumer (`useCursorElevation`) owns the settle
   * delay, because how long to wait depends on what the position is being used FOR.
   */
  onCursorMove?: (at: LatLon | null) => void;
  /** Leaflet overlays: marker layers, footprint, correspondence, heatmap. */
  children?: ReactNode;
}

/** Emits map clicks up. A `<MapContainer>` child so it may use `useMapEvents`. */
function MapClickHandler({ onMapClick }: { onMapClick: (at: LatLon) => void }): null {
  useMapEvents({
    click: (e) => onMapClick({ lat: e.latlng.lat, lon: e.latlng.lng }),
  });
  return null;
}

/**
 * Emits pointer position up.
 *
 * ★ `mouseout` reports `null` rather than simply going quiet. A readout that kept
 *   showing the last position after the pointer left the map would be stating a fact
 *   about a place the surveyor is no longer pointing at.
 */
function MapHoverHandler({ onCursorMove }: { onCursorMove: (at: LatLon | null) => void }): null {
  useMapEvents({
    mousemove: (e) => onCursorMove({ lat: e.latlng.lat, lon: e.latlng.lng }),
    mouseout: () => onCursorMove(null),
  });
  return null;
}

/**
 * Keeps Leaflet's internal size in sync with its CONTAINER (not just the window).
 *
 * ★ Leaflet only re-measures on a window `resize`. When the container itself changes size —
 *   the pane splitter, or **maximising the map** — the tiles clip and the centre drifts until
 *   the next window resize. A `ResizeObserver` calling `invalidateSize()` fixes every such case.
 */
function InvalidateSizeWatcher(): null {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const resize = (): void => {
      map.invalidateSize({ animate: false });
    };

    // ★ OBSERVE THE PARENT TOO, NOT ONLY THE CONTAINER.
    //   The container is `width/height: 100%`, so in a CSS **grid** cell it can report an
    //   unchanged box while the cell around it resizes — the observer never fires and
    //   Leaflet keeps whatever width it measured at mount. That is the failure this
    //   watcher exists to prevent, and observing only the container does not prevent it.
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    if (el.parentElement) ro.observe(el.parentElement);

    // ★ RE-MEASURE AFTER LAYOUT SETTLES.
    //   Leaflet takes its size when the map is created. In a grid whose columns are
    //   fractions of a container that is itself still being laid out, that first
    //   measurement can be a few pixels — which paints a thin strip of tiles down the
    //   left edge and leaves the rest of the pane blank. Exactly the reported symptom.
    //   A frame later the real width exists, so measure again; the timeout covers the
    //   case where a font or a sibling pane settles later still. `invalidateSize` is
    //   idempotent, so extra calls cost nothing.
    const raf = requestAnimationFrame(resize);
    const timer = window.setTimeout(resize, 300);
    window.addEventListener('orientationchange', resize);

    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
      window.removeEventListener('orientationchange', resize);
    };
  }, [map]);
  return null;
}

export function SatelliteMap({
  initialView,
  view,
  seq,
  lastOrigin,
  providerId,
  basemap,
  capabilities,
  reducedMotion,
  onViewChange,
  onMapClick,
  onCursorMove,
  children,
}: SatelliteMapProps): JSX.Element {
  // ★ Freeze the mount-time view so a later `view` prop change never re-seeds the
  //   uncontrolled container (which would yank the map).
  const seed = useRef(initialView).current;

  // ── the tile-failure banner ─────────────────────────────────────────────────
  /**
   * ★ FAIL LOUDLY, NEVER SILENTLY SUBSTITUTE. When the provider rejects tiles
   * (a bad token → 401 upstream → 503 per tile; or no route to the provider),
   * the map used to just stay BLANK — twenty failing requests per pan and the
   * actionable message buried in server logs (the field bug: a malformed Mapbox
   * token blanked a teammate's map for days). After three consecutive tile
   * failures, ONE failing tile is re-fetched as JSON to extract the server's own
   * error message, and it is shown ON the map. Deliberately NOT a fallback to
   * another provider: substituting imagery changes the answer's provenance —
   * the surveyor gets the truth and the fix, not different pixels.
   */
  const [tileFailure, setTileFailure] = useState<string | null>(null);
  const consecutiveFailures = useRef(0);
  const probing = useRef(false);
  const failureShown = useRef(false);

  // A provider/basemap switch is a new world — judge it from zero.
  useEffect(() => {
    consecutiveFailures.current = 0;
    failureShown.current = false;
    setTileFailure(null);
  }, [providerId, basemap]);

  const onTileLoad = (): void => {
    consecutiveFailures.current = 0;
    if (failureShown.current) {
      failureShown.current = false;
      setTileFailure(null);
    }
  };

  const onTileError = (event: unknown): void => {
    consecutiveFailures.current += 1;
    if (consecutiveFailures.current < 3 || probing.current || failureShown.current) return;
    probing.current = true;
    const coords = (event as { coords?: { x: number; y: number; z: number } }).coords;
    const template = proxyTileUrl(API_BASE_URL, providerId, basemap);
    const probeUrl = template
      .replace('{z}', String(coords?.z ?? 1))
      .replace('{x}', String(coords?.x ?? 0))
      .replace('{y}', String(coords?.y ?? 0));
    void fetch(probeUrl, { headers: { Accept: 'application/json' } })
      .then(async (res) => {
        if (res.ok || res.status === 204) return; // transient — the grid may recover
        let message = `imagery tiles are failing (HTTP ${res.status}).`;
        try {
          const body = (await res.json()) as { error?: { message?: string }; message?: string };
          message = body.error?.message ?? body.message ?? message;
        } catch {
          // non-JSON body — the status line above is the honest summary
        }
        failureShown.current = true;
        setTileFailure(message);
      })
      .catch(() => {
        failureShown.current = true;
        setTileFailure('the local API is unreachable.');
      })
      .finally(() => {
        probing.current = false;
      });
  };

  // ★★ 512-px TILES REQUIRE `zoomOffset: -1` IN LEAFLET — the two options are a PAIR,
  //    never separate. Leaflet's world is always 256·2^zoom CSS pixels; `tileSize`
  //    only changes how that world is diced into requests, so a 512 grid holds half
  //    as many tiles per axis and the tile zoom must sit ONE LEVEL BELOW the map
  //    zoom. `tileSize={512}` alone keeps requesting map-zoom tile numbers on the
  //    half-size grid — every index lands at half its true value and the map renders
  //    REAL tiles of the WRONG PLACE (this AOI's indices halved land in open ocean:
  //    a "blank" dark map with markers floating on it, while the 256-px dashboard
  //    map looked fine). The zoom bounds shift by the same +1 so the tile zoom the
  //    offset produces stays inside the provider's declared range.
  const zoomShift = capabilities.tile_size_px === 512 ? 1 : 0;

  return (
    // ★ Leaflet computes its own left-origin geometry; the mirrored Arabic UI
    //   must not run under it. See LtrIsland.
    <LtrIsland>
      <MapContainer
        center={[seed.center.lat, seed.center.lon]}
        zoom={seed.zoom}
        minZoom={capabilities.min_zoom + zoomShift}
        maxZoom={capabilities.max_zoom + zoomShift}
        // We render attribution ourselves (ToS obligation, always on) — §2.21.
        attributionControl={false}
        zoomControl
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          // ★ Force a fresh tile grid when the provider or kind changes — same URL
          //   shape, different pixels and different ToS.
          key={`${providerId}:${basemap}`}
          url={proxyTileUrl(API_BASE_URL, providerId, basemap)}
          minZoom={capabilities.min_zoom + zoomShift}
          maxNativeZoom={capabilities.max_zoom + zoomShift}
          maxZoom={capabilities.max_zoom + zoomShift}
          tileSize={capabilities.tile_size_px}
          zoomOffset={-zoomShift}
          // Attribution travels via ProviderAttribution, not Leaflet's control.
          attribution=""
          // ★ The failure banner's senses — see the block above the component body.
          eventHandlers={{ tileload: onTileLoad, tileerror: onTileError }}
        />
        <MapViewSync
          view={view}
          seq={seq}
          lastOrigin={lastOrigin}
          onViewChange={onViewChange}
          reducedMotion={reducedMotion}
        />
        <MapClickHandler onMapClick={onMapClick} />
        {onCursorMove ? <MapHoverHandler onCursorMove={onCursorMove} /> : null}
        <InvalidateSizeWatcher />
        <NativeResolutionNotice
          zoom={view.zoom}
          zoomShift={zoomShift}
          nativeMaxZoom={capabilities.native_max_zoom ?? null}
          status={capabilities.native_resolution_status ?? 'unknown'}
        />
        {tileFailure !== null && (
          <div
            style={{
              position: 'absolute',
              bottom: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 1000,
              maxWidth: '86%',
              background: 'rgba(112, 22, 22, 0.92)',
              color: ON_MEDIA,
              borderRadius: 6,
              padding: '8px 14px',
              fontSize: 13,
              lineHeight: 1.45,
              textAlign: 'center',
              pointerEvents: 'none',
            }}
            role="alert"
            aria-label={t('Satellite imagery is failing')}
          >
            <strong>{t('Satellite imagery is unavailable —')} </strong>
            {tileFailure}
          </div>
        )}
        {children}
      </MapContainer>
    </LtrIsland>
  );
}

/**
 * ★ THE OVERZOOM WARNING. Past the provider's native detail the tiles are upsampled —
 *   they LOOK sharp, and a surveyor about to place a GCP deserves to know the extra
 *   "detail" is interpolation, not information. Shown only when the boundary is known
 *   or estimated and actually crossed; when the boundary itself is an estimate the
 *   wording says so. Pure display: never blocks the click — the honest number lands in
 *   the accuracy readout and the stored GCP's provenance either way.
 */
function NativeResolutionNotice({
  zoom,
  zoomShift,
  nativeMaxZoom,
  status,
}: {
  zoom: number;
  zoomShift: number;
  nativeMaxZoom: number | null;
  status: 'known' | 'estimated' | 'unknown';
}): JSX.Element | null {
  // `zoom` is the MAP zoom; the provider's native boundary shifts by the same +1 a
  // 512-px grid shifts every other zoom bound.
  if (nativeMaxZoom === null || !beyondNativeResolution(zoom, zoomShift, nativeMaxZoom)) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        top: 8,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1000,
        pointerEvents: 'none',
        background: 'rgba(0, 0, 0, 0.65)',
        color: ON_MEDIA_LINK,
        borderRadius: 4,
        padding: '2px 10px',
        fontSize: 12,
        whiteSpace: 'nowrap',
      }}
      role="note"
      aria-label="Imagery may be upsampled beyond native source resolution"
    >
      {status === 'estimated'
        ? `Beyond ~z${nativeMaxZoom}: imagery may be upsampled beyond native resolution`
        : `Beyond z${nativeMaxZoom}: imagery is upsampled beyond native resolution`}
    </div>
  );
}
