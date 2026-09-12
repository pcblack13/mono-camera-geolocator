# Tests & builds

All paths relative to:

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator
```

---

## The full pre-release run, in order

Run these top to bottom. Later steps assume earlier ones passed.

```bash
# 1. Backend
cd backend && pytest app/tests -q

# 2. GIS
cd ../gis && pytest src/gis/tests -q

# 3. Frontend unit tests
cd ../frontend && npx vitest run

# 4. Frontend type-check + production bundle
npm run build

# 5. Desktop boot smokes
cd ../desktop && npm run smoke && npm run smoke:managed
```

Healthy output is **zero failures everywhere**, then `DESKTOP BOOT SMOKE: OK`
and `MANAGED DESKTOP SMOKE: OK`. The counts only grow — frontend was
`403 passed (60 files)` on 2026-09-01; treat a smaller number on your machine
as suspicious, not as a different baseline.

★ The frontend suite includes **gate tests** that police conventions, not
features — `design-gate` fails the run on any hard-coded hex colour in
`src/components`. If the suite fails on a file you never touched, the gate is
probably naming your new code. See `frontend-and-ui.md`.

---

## ★ vitest and `npm run build` catch DIFFERENT things. Run both.

This cost real time, twice, in one release:

- `npx vitest run` executes tests. It will **not** notice a TypeScript file that
  imports a module you deleted, if no test happens to import that file.
- `npm run build` runs `tsc` and fails on exactly that — `TS2307: Cannot find
  module '../../store/compareStore'`.

A green vitest run is **not** evidence the app compiles. In the 1.2.6 release
run, all 149 tests passed and the build then failed on a dangling import.

Type-check on its own, without producing a bundle (faster iteration):

```bash
cd frontend && npx tsc --noEmit
```

---

## Targeted test runs

```bash
# one backend test file
cd backend && pytest app/tests/test_live_stream_service.py -q

# one backend test, verbose, stop at first failure
pytest app/tests/test_live_stream_service.py -x -vv

# show print/log output
pytest app/tests/test_live_stream_service.py -q -s

# one frontend test file
cd frontend && npx vitest run src/__tests__/provider-menu.test.ts

# frontend watch mode while editing
npx vitest
```

---

## ★ When you delete a feature, grep the WHOLE tree — not the files you remember

Removing the Compare view broke the build twice, in two different places, for
the same reason: something still referenced the deleted module and it was not a
file anyone was thinking about.

```bash
# before deleting src/store/compareStore.ts, find every reference
cd frontend
grep -rn "compareStore\|useCompareStore\|CompareView" src/
```

Check especially:

- **barrel files** (`components/*/index.ts`) — they re-export deleted files and
  the error surfaces far from the deletion
- **test files** — `provider-menu.test.ts` pinned behaviour that was removed
- **keyboard shortcut maps** — `AppShell.tsx` held a `case 'c':` for a view that
  no longer existed

A deletion is not finished until `npm run build` passes.

---

## Frontend dev server

```bash
cd frontend
npm run dev
```

For UI work this is much faster than rebuilding the desktop app. Note it talks
to whatever API you have running — see `backend-and-database.md`.

---

## ★ `frontend/dist/` is a build artifact, and the desktop packager copies it as-is

`desktop/package.json` lists `../frontend/dist` under `extraResources`. The
packager copies whatever is on disk — it does **not** rebuild the frontend.

So if `npm run build` failed, or you never re-ran it after your last edit, the
`.deb` and the `.exe` will silently ship a **stale frontend**. The Python and
Electron sides will be current; the UI will not be.

Always build the frontend immediately before packaging:

```bash
cd frontend && npm run build && cd ../desktop && npm run dist
```

Verify after the fact by comparing timestamps — `dist/` must be **older** than
the installer, and **newer** than your last source edit:

```bash
ls -la frontend/dist/index.html
ls -la desktop/dist-installers/*.deb
```

---

## Desktop smoke tests

```bash
cd desktop
npm run smoke            # boots the API against your dev database
npm run smoke:managed    # boots the FULL bundled stack: postgres + redis + API + worker
```

`smoke:managed` is the more valuable of the two — it unpacks the bundled
runtime, creates the cluster on port 15432, runs migrations, starts Redis on
16379, boots the API, creates a real project in the bundled PostGIS, and tears
everything down. Cold run is ~20–25 s; first ever run is longer because it
unpacks a few hundred MB of runtime.

It passes when you see:

```
[smoke] created project <uuid> in the BUNDLED PostGIS
MANAGED DESKTOP SMOKE: OK
```

**A smoke test does not type-check anything.** It serves whatever is already in
`frontend/dist/`. Passing smokes plus a failing `npm run build` is a perfectly
possible — and misleading — combination.

---

## Import boundaries

```bash
lint-imports              # enforces .importlinter
```

Catches architectural violations (a layer importing something it must not) that
neither tests nor `tsc` will see.
