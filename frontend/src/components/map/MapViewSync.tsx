/**
 * `map/MapViewSync.tsx` — 50-frontend §2.19 / §3.6.
 *
 * ★★ THE SINGLE RECONCILIATION POINT between Leaflet's imperative view and
 *    `mapStore.view`. **No other component may call `map.setView`.** Isolating this is
 *    what defeats the classic react-leaflet oscillation bug.
 *
 * ★ THE ANTI-FEEDBACK MECHANISM (§3.6), and every piece of it is load-bearing:
 *   - **Downward**: when the store `view` differs from the live map beyond the epsilon
 *     AND the change did not originate from the map (`lastOrigin !== 'map'`), apply it
 *     with `setView`/`flyTo`. The `seq` token gates this — we apply each store `seq`
 *     at most once, so a `flyTo` animation's own `move` events cannot re-trigger it.
 *   - **Upward**: on `moveend`/`zoomend`, report the live view up as origin `'map'`.
 *   - **The epsilon** (`VIEW_EPSILON_DEG` / `VIEW_EPSILON_ZOOM`, from `mapStore`)
 *     absorbs Leaflet's coordinate rounding so a value that never exactly converges
 *     cannot spin the effect forever.
 *
 * ★ `prefers-reduced-motion` ⇒ instant `setView`, never `flyTo` (§8.8 item 7).
 *
 * Renders `null`. Must be a child of `<MapContainer>`.
 */

import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';

import type { MapViewState, ViewOrigin } from '../../types/geo';
import { VIEW_EPSILON_DEG, VIEW_EPSILON_ZOOM } from '../../store';

/**
 * Is this a view Leaflet can actually be given?
 *
 * ★ WHY THIS GUARD EXISTS. A Leaflet map whose container has been measured at 0 × 0 —
 *   which happens the moment an ancestor is hidden, or during the first frame before
 *   layout settles — reports a degenerate centre. That value used to travel up into
 *   `mapStore` on the `moveend` that resizing fires, and the next component to apply
 *   the stored view called `setView(NaN, NaN)`, which Leaflet answers with
 *   `Invalid LatLng object: (NaN, NaN)` — thrown during a render effect, so the whole
 *   editor was replaced by its error boundary.
 *
 *   The store is shared state: one bad write reaches every map. So the check lives on
 *   BOTH sides of this reconciliation point — nothing non-finite is reported up, and
 *   nothing non-finite is applied down. A momentarily unmeasurable map is a normal,
 *   transient condition; it must be ignored, not propagated.
 */
function isFiniteView(lat: number, lon: number, zoom: number): boolean {
  return (
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    Number.isFinite(zoom) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180
  );
}

export interface MapViewSyncProps {
  view: MapViewState;
  /** Monotonic token from `mapStore`. Each value is applied downward at most once. */
  seq: number;
  /** Who last set `view`. A `'map'`-origin change is already live; we must not re-apply it. */
  lastOrigin: ViewOrigin;
  onViewChange: (view: MapViewState, origin: ViewOrigin) => void;
  reducedMotion: boolean;
}

export function MapViewSync({
  view,
  seq,
  lastOrigin,
  onViewChange,
  reducedMotion,
}: MapViewSyncProps): null {
  const map = useMap();
  /** The last store `seq` we pushed into Leaflet. Guards against re-applying. */
  const appliedSeq = useRef<number>(-1);
  /** True while WE are moving the map, so the `moveend` echo is not reported back up. */
  const programmatic = useRef(false);
  /** ★ A bounds fit lets LEAFLET pick the zoom (2026-09-10): its echo IS news — the
   *  store still holds the placeholder zoom, and every readout keyed on it (the
   *  "z2 · GSD" caption) would lie until the next pan. That one echo is reported. */
  const fittedBounds = useRef(false);

  // ★ LISTEN BEFORE APPLYING (2026-09-10). A fit that jumps more than Leaflet's
  //   zoom-animation threshold (4 levels — a frame opening from the world view
  //   onto its points) completes SYNCHRONOUSLY inside the apply below, firing
  //   `zoomend`/`moveend` at once. With the listeners attached afterwards, that
  //   echo was lost and the store kept the placeholder zoom — the "z2 · GSD"
  //   caption lied until the next pan. Effects run in order: the listeners go first.
  // ── Upward: Leaflet → store ────────────────────────────────────────────────
  useEffect(() => {
    const report = (): void => {
      // Swallow the echo of our own programmatic move; report only genuine user pans —
      // except a bounds fit, whose zoom only Leaflet knew (see `fittedBounds`).
      if (programmatic.current) {
        programmatic.current = false;
        if (!fittedBounds.current) return;
        fittedBounds.current = false;
      }
      const c = map.getCenter();
      const z = map.getZoom();
      // ★ A resize to 0 × 0 fires `moveend` too. Reporting that measurement would
      //   poison the shared store for every other map — drop it and keep the last
      //   good view instead.
      if (!isFiniteView(c.lat, c.lng, z)) return;
      onViewChange({ center: { lat: c.lat, lon: c.lng }, zoom: z, bounds: null }, 'map');
    };
    map.on('moveend', report);
    map.on('zoomend', report);
    return () => {
      map.off('moveend', report);
      map.off('zoomend', report);
    };
  }, [map, onViewChange]);

  // ── Downward: store → Leaflet ──────────────────────────────────────────────
  useEffect(() => {
    if (seq === appliedSeq.current) return;
    appliedSeq.current = seq;

    // A change the map itself produced is already reflected in Leaflet — applying it
    // would be a no-op at best and a fight at worst.
    if (lastOrigin === 'map') return;

    // Never hand Leaflet a view it will reject. A stored NaN can only come from a
    // degenerate measurement upstream; applying it throws mid-effect and takes the
    // editor down with it. `fitBounds` rejects a non-finite corner exactly as
    // `setView` rejects a non-finite centre, so BOTH paths are checked — a box is
    // dropped back to the centre path rather than abandoning the update outright.
    const target =
      view.bounds &&
      isFiniteView(view.bounds.min_lat, view.bounds.min_lon, 0) &&
      isFiniteView(view.bounds.max_lat, view.bounds.max_lon, 0)
        ? view.bounds
        : null;
    const center = map.getCenter();
    const zoom = map.getZoom();

    if (!target && !isFiniteView(view.center.lat, view.center.lon, view.zoom)) return;

    const closeEnough =
      Math.abs(center.lat - view.center.lat) < VIEW_EPSILON_DEG &&
      Math.abs(center.lng - view.center.lon) < VIEW_EPSILON_DEG &&
      Math.abs(zoom - view.zoom) < VIEW_EPSILON_ZOOM;

    programmatic.current = true;
    fittedBounds.current = target !== null;
    if (target) {
      // Leaflet frames the bounds and derives the zoom — a wrong zoom guess would
      // frame the wrong area, which on a satellite pane is invisible (§3.6).
      map.fitBounds(
        [
          [target.min_lat, target.min_lon],
          [target.max_lat, target.max_lon],
        ],
        { animate: !reducedMotion },
      );
    } else if (!closeEnough) {
      if (reducedMotion) {
        map.setView([view.center.lat, view.center.lon], view.zoom, { animate: false });
      } else {
        map.flyTo([view.center.lat, view.center.lon], view.zoom, { duration: 0.5 });
      }
    } else {
      programmatic.current = false;
    }
  }, [seq, lastOrigin, view, map, reducedMotion]);

  return null;
}
