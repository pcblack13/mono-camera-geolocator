# Troubleshooting

Real problems from real sessions, with the command that actually found the
cause. Each heading is the symptom as you will experience it.

---

## ★ Start here: the app-status page and the log monitor (2026-09-01)

The desktop app has no terminal, so for most "what just happened?" questions
the answer is now **inside the app**: click the status chip in the top bar
(Online / Degraded / …) → **Open app status & logs**, or browse to `/status`.

What it gives you:

- **Every health component explained** — the same `GET /health/ready` detail,
  with each component's job, whether it gates readiness (postgres / redis /
  storage do; celery / imagery / raster only degrade; models is informational),
  its latency and its own error message.
- **A live tail of the server's log** — everything the terminal would show
  (uvicorn, SQLAlchemy, app code), filterable by level and full-text search.
  **Click a line to expand it**: the full traceback, the structured fields, and
  the `request_id` — the same id an error dialog shows, so a user's screenshot
  links straight to its log lines.

The same data over HTTP (managed app = port **8123**; `uvicorn` by hand =
whatever you started, typically 8000):

```bash
# newest 500 lines
curl -s "http://127.0.0.1:8123/api/v1/health/logs" | python3 -m json.tool

# errors only, free-text filter, poll only what is new
curl -s "http://127.0.0.1:8123/api/v1/health/logs?level=error"
curl -s "http://127.0.0.1:8123/api/v1/health/logs?q=redis"
curl -s "http://127.0.0.1:8123/api/v1/health/logs?after=<last_seq>"
```

Two properties worth knowing: the buffer is a **bounded ring** (last ~2000
lines — a flood evicts old lines, never eats the process), and every line has
already been through the **secret scrubber** — tokens, passwords and
connection-string credentials cannot reach this page. It lives in
`backend/app/core/logbuffer.py`; the endpoint is in `api/v1/health.py`.

`journalctl -k` and `~/.local/share/MonoCameraGeolocator/boot.log` are still
the places to look when the **process itself** died (native crashes, "the API
exited unexpectedly") — a dead process serves no log endpoint.

---

## ★ "I changed a setting and nothing happened"

**This is the most expensive gotcha in the codebase. Read this one even if
nothing is broken yet.**

There are two `.env` files and they are not synchronised:

```bash
backend/.env                                      # the source tree
~/.local/share/MonoCameraGeolocator/work/.env     # the RUNNING copy
```

The app runs with its working directory set to `work/`, and `config.py` mirrors
values with `setdefault` — so **the CWD `.env` wins**. A managed or installed run
never reads `backend/.env`. The `work/.env` is created once, on first run, and
then keeps whatever it was first given, forever.

Diagnose:

```bash
diff ~/.local/share/MonoCameraGeolocator/work/.env backend/.env
grep -n "LE_ALLOWED_PROVIDERS" ~/.local/share/MonoCameraGeolocator/work/.env
```

Fix: edit `work/.env`, then restart the app. Comment a line out to fall back to
the default:

```bash
sed -i 's/^LE_ALLOWED_PROVIDERS=/#LE_ALLOWED_PROVIDERS=/' \
  ~/.local/share/MonoCameraGeolocator/work/.env
```

This one line hid Esri and Sentinel from the map settings for an entire release.
`RELEASE_CHECKLIST.md` §3 now says to diff these two files on every machine you
upgrade — that step exists because of this.

---

## A map provider is missing from the settings menu

Two independent gates, and you have to check both:

1. **Server allow-list** — `LE_ALLOWED_PROVIDERS` in `work/.env` (see above). An
   absent or empty line allows every provider.
2. **A client-side ban list** — historically `BasemapSwitcher.tsx` carried a
   hardcoded `NEVER_OFFERED` array that hid providers regardless of what the
   server allowed.

```bash
grep -rn "NEVER_OFFERED" frontend/src/
```

The general rule: the server's allow-list is the single source of truth. A
second, duplicated list on the client is how a provider ends up enabled on the
server and still invisible in the UI.

Ask the server what it actually offers (**8123** for the managed/installed
app, 8000 for a hand-started `uvicorn`):

```bash
curl -s http://127.0.0.1:8123/api/v1/imagery/providers | python3 -m json.tool
```

---

## `preflight.unavailable — TypeError: 'module' object is not callable`

**FIXED 2026-08-30.** A healthy boot now logs `preflight complete in …s` then
`preflight.completed`, and `/capabilities` answers from a real report. If you
still see the TypeError line, you are running a build older than 2026-08-30.

The history, kept because it explains the fix in `main.py`: `_run_preflight()`
did `from ai_engine.models import preflight`, which binds the **submodule**,
not the function — so `preflight()` raised on every boot, the `except` ate it,
and `app.state.preflight_report` was silently `None` from the day it was
written. The corrected import (`from ai_engine.models.preflight import
preflight`) also passes the required `AiEngineConfig`. Every `ai_engine`
component still reports `deferred` by design — that part is scope, not a bug.

---

## A camera streams but the app calls it uncompressed / refuses it

OpenCV's V4L2 backend **does not apply `CAP_PROP_FOURCC` until streaming has
actually started.** Reading the format back immediately after setting it returns
the old value, so a camera that is perfectly happy to deliver MJPEG reports a
raw format.

The fix — already in `live_stream_service.py` — is a warm-up read:

```python
cap.set(cv2.CAP_PROP_FOURCC, MJPG)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.read()          # ★ warm-up: only now is the negotiated format truthful
```

Policy since 1.2.6: **warn, never refuse.** A raw-format device still streams,
with a note explaining why the frame rate is low. If you see a refusal panel,
that is a regression.

Inspect a device from the shell:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

---

## The API returns an error and the message in the UI is generic

This API does **not** use FastAPI's default `{"detail": "..."}` envelope. It
uses:

```json
{"error": {"code": "...", "message": "...", "status": 422}}
```

Client code that reads `body.detail` gets `undefined` and falls back to
something useless like "HTTP 422". Parse defensively:

```ts
const text = body.error?.message ?? body.detail ?? body.message ?? `HTTP ${res.status}`;
```

---

## `MissingGreenlet` / a 500 on save right after an update

Symptom: a PATCH or PUT succeeds in the database but the response 500s.

Cause: a trigger-maintained column (`updated_at`) is expired by the UPDATE
flush, and SQLAlchemy then tries to lazy-load it **outside** the async context.

Fix: refresh the object explicitly before serialising it.

```python
await session.refresh(obj)
```

---

## The build fails on a module you deleted

```
error TS2307: Cannot find module '../../store/compareStore'
```

`npx vitest run` will not catch this — only `npm run build` (which runs `tsc`)
will. Before deleting anything, grep the whole tree:

```bash
cd frontend && grep -rn "compareStore\|CompareView" src/
```

The three places that bite, in order of how often they are forgotten: **barrel
files** (`components/*/index.ts`), **test files**, and **keyboard shortcut maps**.

---

## The installer shipped an old UI

`desktop/package.json` lists `../frontend/dist` under `extraResources`. The
packager copies it verbatim — it never rebuilds. If your last `npm run build`
failed, `dist/` still holds the previous successful build and the installer
silently ships a stale frontend.

Verify by timestamp. `dist/` must be **newer than your last source edit** and
**older than the installer**:

```bash
ls -la frontend/dist/index.html
ls -la desktop/dist-installers/*.deb
```

Always chain them:

```bash
cd frontend && npm run build && cd ../desktop && npm run dist
```

---

## Two identical app icons in the applications menu

Both are real. One is the installed `.deb`, one is written by `run-desktop.sh`
on every source run, and they share the same `Name=`.

```bash
find / -xdev -name "*.desktop" 2>/dev/null \
  | xargs grep -liE "mono.?camera|landexplorer" 2>/dev/null
```

> **Regex trap that cost a round trip here:** `mono-?camera` matches
> `monocamera` and `mono-camera` but **not** `Mono Camera` with a space — which
> is what `Name=` actually contains. The file was read and silently didn't match.
> Use `mono.?camera`.

Full detail and removal in `desktop-and-install.md`.

---

## `psql: connection refused` on port 15432

The bundled cluster only runs while the app runs. Start the app, or hold the
stack up with `npm run smoke:managed`. See `backend-and-database.md`.

---

## The GitHub workflow built for 45 minutes then failed on the last step

The workflow only does `gh release upload`, which requires the release to exist
already. Create `gcp_picker-v<version>` **before** the build finishes. See
`release-and-github.md`.

---

## An old version's CI workflow fired unexpectedly

You ran `git push --tags`, which pushes every local tag the remote lacks —
including old `win-build-*` tags, each of which triggers its own build from old
source. Push one tag by name instead:

```bash
git push origin win-build-v1.2.6
```

---

## Auto GCP mode does nothing

Auto requires **all three**: the camera is solved, `auto_gcp_enabled` is true,
and the image already has **≥ 4 GCPs** (`AUTO_GCP_REQUIRED = 4`). Until then the
button reads `Auto 2/4`.

Also note the directions are asymmetric by design:

- **create mode** — photo → map only (the photo point is the input)
- **edit mode** — both directions

Dragging a map marker while *creating* a point will not move the photo mark.
That is intended, not a bug.

---

## Known issue: duplicate auto-generated GCP names

Auto-naming reads one page of GCPs (`DEFAULT_LIMIT = 50`, sorted
`created_at DESC`). On an image where the highest `GCP-NN` has aged off page
one, it can propose a name that already exists.

The one-line fix is `useGcps(imageId, { limit: 200 })`, deferred because it
forks the React Query cache key. Related and pre-existing: `MapPanel` and
`ImagePanel` render only 50 markers per image.
