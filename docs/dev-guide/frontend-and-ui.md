# Frontend & UI

All paths relative to:

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator/frontend
```

The working rules that keep frontend changes from bouncing. Everything here was
learned by breaking it first.

---

## The verification loop — a change is not done until all four pass

```bash
npx tsc --noEmit          # type-check alone, fastest signal
npx vitest run            # the whole suite (~400 tests, ~40 s)
npx eslint src/<files you touched>
npm run build             # tsc AND the production bundle — catches what vitest cannot
```

Targeted while iterating:

```bash
npx vitest run src/__tests__/status-page.test.tsx
npx vitest                # watch mode
```

★ There are **gate tests** that fail on things eslint does not check — see the
design gate below. If a full `vitest run` fails on a file you never touched,
read the failure: it is probably a gate naming your new code.

---

## ★ The design gate: zero hard-coded colours in `src/components`

`src/__tests__/design-gate.test.ts` greps every component for hex literals and
fails the suite on any hit. This is enforced, not advisory — it caught a
`#00e5ff` in a brand-new map marker the day it was written.

A component that needs a colour imports a **name that says what the colour is
for** from `src/theme/paint.ts` (e.g. `ON_MEDIA`, `GLOBE.live`) or
`dataColors.ts` — or uses a CSS token (`var(--status-ok)`, `var(--accent)`).
Colours live in `src/theme/**` and nowhere else.

---

## i18n: English is the key, Arabic is the value

- Wrap every user-visible string in `t('…')` (`src/i18n/index.ts`). The English
  sentence **is** the translation key — an untranslated string renders as its
  English, never as a raw id.
- Add the Arabic to `src/i18n/ar.ts`. Coverage grows sentence by sentence;
  a missing entry is English, not a blank.
- ★ `ar.ts` is one object literal — a **duplicate key is a tsc error**
  (TS1117). Grep before adding: `grep -n "'Your string'" src/i18n/ar.ts`.
- Switching language **remounts the whole tree** (`main.tsx` keys it by
  language). Interaction state that must survive that uses
  `lib/survivingState.ts`, not `useState`.

---

## ★ Arabic RTL: the document mirrors, geometry does not

Since 2026-08-31 (owner decision) Arabic sets `dir="rtl"` and the chrome
mirrors. The traps, each of which has already cost a round trip:

**1. Geometry surfaces get an `LtrIsland`.** Konva stages, Leaflet/MapLibre
maps, drag handles — anything computing left-to-right pixel maths — is wrapped
in `components/common/LtrIsland.tsx`, which pins `dir`, theme direction and the
style cache back to LTR.

**2. Chrome that floats OVER a map is geometry too.** `MapPanel`'s control
overlay keeps the top-left clear for Leaflet's +/− control via
`justify-content: flex-end`. In RTL, flex-end becomes the *left* — and the
cluster parked itself on the zoom control (fixed 2026-09-01 by `dir="ltr"` on
the overlay). Rule: **an overlay shares the direction of the surface it
overlays.** Arabic text inside still shapes correctly via bidi.

**3. Bidi scrambles mixed lines.** `2 ms` renders as `ms 2`, and
`v1.0.0 · Uptime 0m 42s` comes out shuffled. Pin the technical fragment:
`<span dir="ltr">…</span>` (or `dir="ltr"` on the Typography). Log lines,
timestamps, coordinates and stream URLs are Latin technical text — give the
whole pane `dir="ltr"`.

**4. MUI `Stack spacing` flips, flex `gap` does not.** Inside a `dir="ltr"`
pane, the RTL theme still emits `margin-right` for Stack spacing and the
columns collapse. Use `sx={{ gap: … }}` in any LTR island.

---

## Persisted stores and their localStorage keys

Every persisted zustand store follows one convention: **a validating merge** —
each rehydrated row is re-judged by the same validator the UI uses; corrupt
rows are dropped and counted (`console.warn`), never repaired or trusted.
Copy an existing store (`cameraRegistryStore`) when adding one.

| Key | Store | Holds |
|---|---|---|
| `le.cameras.v1` | `cameraRegistryStore` | **a cache** of the server's cameras (1.3) — `GET /cameras/all` replaces it on every app start and window focus; a ULID row here is a pre-1.3 leftover |
| `le.cameras.migrated.v1` | `CameraRegistrySync` | the one-time answer to "move this browser's pre-1.3 cameras to the server?" (`imported` / `discarded`) |
| `le.monitorSettings.v1` | `monitorSettingsStore` | **each camera's live-detection setup** (2026-09-01) |
| `le.monitorLayout.v1` | `monitorLayoutStore` | monitor pane sizes, map-beside, deck tab |
| `landexplorer.language` | i18n | `en` / `ar` |
| `landexplorer.workchain` | workchain | open page tabs |

Per-camera monitor settings semantics: **Apply / Start saves** (never a
half-edit), re-entering the camera restores everything and counts the saved
LUT as applied (map centres, drift watch runs), the header shows "setup saved"
+ **Edit settings**, and removing a camera from the registry forgets its
setup. Session-surviving dial state is keyed per camera
(`detection.live.<cameraId>.…`) so camera B never inherits camera A's draft.

★ **Since 1.3 the registry is the server's** (`api/cameras.ts`, `cameras`
table). `cameraRegistryStore.add/update/remove/importJson` are `async` and go
to the API first; the store takes the server's row (a UUID id). Start /
Watch / data-feed calls pass `camera_id`, which makes the run the camera's
*desired state* — `camera_service.reconcile_at_boot` restarts it after an API
restart, and Stop clears it. Only a server camera (`isServerCameraId`) carries
intent; a legacy ULID row cannot.

---

## Map engines are a budget: who loads what

- **MapLibre** — the monitor globe (and camera-monitor map). Lazy per route.
- **Leaflet** — the workspace/dashboard satellite maps. Lazy per route.
- ★ Never let one page pull both. The add-camera dialog's position picker
  (`PositionPickerMap.tsx`) is Leaflet **inside** the MapLibre globe page — so
  it loads via `React.lazy` only when the dialog opens. Follow that pattern.
- Tiles always come from the backend proxy (`proxyTileUrl`) — provider keys
  stay server-side.

---

## Where the newer surfaces live (for orientation)

| Surface | Entry | Code |
|---|---|---|
| App status + log monitor | status chip → "Open app status & logs", or `/status` | `pages/StatusPage.tsx`, `GET /health/logs` |
| Camera monitor, per-camera setup | `/monitor/cameras/:id` | `pages/monitor/CameraMonitorPage.tsx`, `store/monitorSettingsStore.ts` |
| Add camera (three questions + map picker) | globe → **+** (or `A`) | `components/monitor/globe/CameraDialog.tsx`, `PositionPickerMap.tsx` |
| Coordinate paste parsing | add-camera, go-to-location | `lib/geo/parseLocation.ts` |

---

## Seeing a change in the real app without touching a running instance

The user-facing app (API on **8123**) may be in use — never kill it. To verify
UI + backend changes together:

```bash
# 1. a private API on 8124, from the packaged runtime, against the SAME db
#    (env copied from the running worker; backend edits are live via the
#     local-resources symlinks)
#    see desktop-and-install.md for the runtime layout

# 2. a dev server proxying to it
cd frontend && VITE_PROXY_TARGET=http://localhost:8124 npx vite --port 5174 --strictPort

# 3. stop things by their LISTENING SOCKET, never pkill -f
pid=$(ss -ltnp "sport = :5174" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2); kill $pid
```

★ `pkill -f <pattern>` with any text that also appears in your own shell
command matches the shell and kills it (exit 144). This has bitten twice.
Kill by socket, as above.

And after any UI change that should reach the desktop app:

```bash
cd frontend && npm run build     # the packager and the app serve dist/ as-is
```
