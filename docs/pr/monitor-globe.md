# Monitor: a globe of cameras, and a per-camera monitoring page

Replaces the flat **Live stream** tab with `/monitor` (a MapLibre globe, one marker per
registered camera) and `/monitor/cameras/:id` (the tab's functionality in a new layout:
video hero, staged inspector, status header, synced deck). Navigation and presentation
only — detection, placement, tracking, drift and capture run on the same hooks and the
same endpoints as before. **Backend: zero changes.**

## Files

New

| Path | What |
| --- | --- |
| `frontend/src/pages/monitor/GlobePage.tsx` | `/monitor` — lazy chunk |
| `frontend/src/pages/monitor/CameraMonitorPage.tsx` | `/monitor/cameras/:id` — lazy chunk |
| `frontend/src/components/monitor/globe/{GlobeMap,GlobeHud,CameraListPanel,CameraDialog}.tsx`, `globeStyle.ts`, `useCameraProbe.ts` | the globe, its HUD, list, add-camera dialog, inline style, hover probe |
| `frontend/src/components/monitor/camera/{VideoHero,DetectionOverlay,Inspector,InspectorStage,MonitorHeader,BottomDeck,MapDeck,DetectionsDeck,EventsDeck}.tsx` | the camera page |
| `frontend/src/store/cameraRegistryStore.ts` | persisted `le.cameras.v1`, validating merge, Result-returning validation, CSV/JSON |
| `frontend/src/store/monitorLayoutStore.ts` | splitters, deck, overlay toggles — persisted `le.monitorLayout.v1` |
| `frontend/src/lib/monitor/geojson.ts` | **the one `[lon, lat]` flip site** (+ FOV wedge) |
| `frontend/src/lib/monitor/stages.ts` | the inspector's five gates, pure |
| `frontend/src/lib/monitor/fit.ts` | contain-fit arithmetic for the canvas overlay, pure |
| `frontend/src/hooks/useLiveFeed.ts` | the MJPEG state machine, extracted from the tab |
| `frontend/src/hooks/useMonitorEvents.ts` | the per-camera event log |
| `frontend/src/__tests__/{camera-registry,monitor-geojson,use-live-feed,monitor-stages}.test.*` | 34 new tests |
| `docs/screenshots/monitor/*.png` | the three screenshots below |

Modified

| Path | Why |
| --- | --- |
| `frontend/src/api/client.ts` | `fetchStream()` — the streaming read the player needs, so this module stays the only `fetch()` site; `ulid()` exported for camera ids |
| `frontend/src/components/live/LiveStreamTab.tsx` | consumes `useLiveFeed`; re-exports the helpers its tests import. Its 11 tests pass unchanged |
| `frontend/src/components/live/LiveMarksMap.tsx` | optional `selectedIndex` / `onSelect` for the map ↔ video sync |
| `frontend/src/router.tsx`, `shell/workspaces.tsx`, `shell/pageNav.ts`, `pages/ProjectsPage.tsx` | routes; the registry's Live stream page is now **Monitor** at `/monitor`; `/projects?tab=live` forwards with `replace` |
| `frontend/vite.config.ts` | `maplibre-gl` in its own `globe` chunk |
| `frontend/src/theme/paint.ts` | the globe's MapLibre paint (CSS cannot reach a style JSON) |
| `frontend/src/i18n/ar.ts` | Arabic for the monitor |
| `frontend/src/__tests__/{page-nav,workspace-nav}.test.tsx` | the three expectations the rename/redirect changes |

## maplibre-gl

Before: `^5.24.0` (installed 5.24.0). After: **unchanged** — the globe projection and
`sky.atmosphere-blend` are already in 5.x. No dependency change was needed.

## Screenshots

(a) `docs/screenshots/monitor/a-globe.png` — the globe with four cameras and the HUD
(Zulu clock · counts · provider + attribution · Online chip), imagery tiles answering 204
(offline), so the sphere is the token's own colour with the atmosphere at the limb.

(b) `docs/screenshots/monitor/b-camera-page.png` — video live (measured: `● live 10 fps
1280×720 MJPEG`), inspector ①②③ satisfied, ④ gated with "Use current frame", ⑤ gated,
deck on Map.

(c) `docs/screenshots/monitor/c-refused-banner.png` — a start refused: the server's
verbatim `error.message` in a banner under the header, with copy and Dismiss; the Events
count advanced.

Taken with Electron against the vite dev server and a stand-in API (providers, 204
tiles, a 10 fps MJPEG of one frame, a 422 on session start). The real API was not
available in this environment (no backend venv), so the hover probe, the 6 s stall,
capture and a real detection run were verified through their unit tests, not a browser.

## Acceptance (§8), what was verified how

- `npm run build` passes; `maplibre-gl` lives only in `globe-*.js` (the entry chunk mentions it once — the preload dependency map's CSS filename — and the projects list is in the entry chunk).
- Empty imagery: the globe renders with 204 tiles (screenshot a); only the API host is requested (inline style, no glyphs/sprite/fonts). With the providers list **unreadable** the globe still renders without an imagery source.
- 33.8330 / 35.5410 → `[35.541, 33.833]`, east and north (`monitor-geojson.test`).
- Stages gate and link (`monitor-stages.test`); the refused start shows verbatim with a copy button (screenshot c).
- Stall: frames flowing then stopping trips `lost` after `STALL_MS` (`use-live-feed.test`); the header pill reads "lost · stalled 6 s · Ns", Capture/Start disable, the Events deck logs it, the registry status turns the marker red on return.
- Selection: a box click selects by track id → mark ringed on the map + row selected; a marker click selects the mark → box ringed; the map never re-centres (`CenterOnce`).
- Layout persists (`le.monitorLayout.v1`, validating merge); a corrupt registry JSON drops rows with a count and a warning (`camera-registry.test`).
- Existing detector/placement/tracking/drift/live tests pass unchanged (53 files, 353 tests).
- Reduced motion: no idle rotation, `flyTo` duration 0. RTL: see conflicts.

## Where §6 (constraints) met §5 (behaviour), and what was done

1. **"Boxes on a canvas overlay" vs "zero backend changes."** While a run is on, the
   picture is the detector's own MJPEG (the device admits one opener), and the backend
   burns its boxes into that stream. The canvas overlay draws from the polled
   `session.latest` — boxes, labels, track ids, the selection ring, the drift ghost —
   over the same picture. The Boxes/Labels/Tracks chips control the overlay; they cannot
   remove the server's burned-in boxes. Changing that needs a backend flag, which this
   PR does not touch.
2. **"⑤ needs ④ applied."** The drift watch never depended on the tracker, and gating
   it there would take a working control away (the tab lets you freeze without a
   handoff). ⑤ gates on ③ applied **and the table carrying a pose** — the real
   requirement (`drift_service` re-solves geometry from `pose.R/C/K`).
3. **"PiP re-uses the same `<img>`."** Browsers offer PiP for `<video>` only. The
   Document Picture-in-Picture API moves the hero's own element into the PiP window
   — the same `<img>`/canvas, no second socket — and where that API is absent the
   button is disabled with a tooltip. No second player was written.
4. **"RTL: mirror the layout."** This app pins `dir="ltr"` on purpose (`i18n/index.ts`:
   mirroring broke the photo stage, the maps and the splitters). The monitor uses
   logical properties (`insetInlineStart/End`, `borderInlineStart`) and every numeric
   readout is `direction: ltr`, so it mirrors correctly if that decision is ever
   reversed — but under the app's standing rule it renders left-to-right in Arabic
   like every other page.
5. **"`client.ts` is the only `fetch()`."** The canvas reader needs a streaming body no
   `fetchJson` can give. `fetchStream(url, signal)` now lives in `client.ts`, mints the
   request id for our own server only (a custom header would force a preflight a
   third-party camera may refuse), and the hook calls that. The tab previously called
   `fetch` directly; it no longer does.
6. **"Camera registry supersedes `liveSourcesStore`."** The old bookmarks store stays:
   the Drift monitor page still lists saved sources from it. Nothing was deleted.

## Not done / out of scope

Server-side persistence, sharing, other layers, new models, `live_stream_service.py`,
GCP picking from the globe — none touched. The Video detection, Drift monitor and
Video editor tabs are untouched; only the Live stream tab is replaced (and its file is
kept, consuming the extracted hook, so its tests keep running).
