# Dev guide — commands that actually get used

A working reference for Mono Camera Geolocator (LandExplorer), built from real
sessions rather than from the source tree. Every command here has been run on
this project, and the gotchas marked ★ are ones that cost real time.

This complements the existing docs — it does not replace them:

| Doc | Answers |
|---|---|
| `docs/guides/quickstart.md` | how do I get started |
| `docs/guides/running-locally.md` | how do I set up a dev environment |
| `docs/guides/configuration.md` | what does each setting mean |
| `docs/architecture/` | why is it built this way |
| `RELEASE_CHECKLIST.md` | what must I verify before shipping |
| **this folder** | **what do I type** |

---

## The files

### [`backend-and-database.md`](backend-and-database.md)
Connecting to the right database (there are two, both named `landexplorer`),
psql session settings, schema exploration, census and lookup queries, alembic,
running the API and worker by hand, and reading the app's own logs over HTTP
(`GET /api/v1/health/logs`).

### [`tests-and-builds.md`](tests-and-builds.md)
The full pre-release test run in order, targeted test invocations, why vitest
and `npm run build` catch different failures, and why `frontend/dist/` being
stale silently ships a broken UI.

### [`release-and-github.md`](release-and-github.md)
The `win-build-*` vs `gcp_picker-*` tag distinction, the complete release
sequence, `gh` release and workflow commands, and the two traps that have
already bitten: `git push --tags` firing old builds, and the workflow requiring
the release to exist before it finishes.

### [`desktop-and-install.md`](desktop-and-install.md)
Running from source, building installers, artifact names, installing and
upgrading the `.deb`, the process-leak check, launcher `.desktop` entries, and
reclaiming disk space without destroying your data.

### [`frontend-and-ui.md`](frontend-and-ui.md)
The frontend's working rules: the verification loop (vitest, tsc, eslint,
build), i18n and the Arabic RTL traps, the no-hex-colours design gate, the
persisted stores and their localStorage keys, and which map engine loads where.

### [`troubleshooting.md`](troubleshooting.md)
Symptom-first. Each entry is a real problem, the command that found the cause,
and the fix. **Starts with the app-status page (`/status`) — the built-in log
monitor that answers "what just happened" without an ssh session.**

---

## The six things worth knowing before anything else

**1. `work/.env` beats `backend/.env`.**
The running app reads `~/.local/share/MonoCameraGeolocator/work/.env`. Editing
`backend/.env` does nothing to an installed or managed run. Nothing keeps them
in sync.

**2. There are two databases and two Redis instances.**
Dev is `5432` / `6379`. The bundled stack is **`15432`** / **`16379`**, and it
only exists while the app is running.

**3. Passing tests do not mean the app compiles.**
`npx vitest run` and `npm run build` fail on different things. Run both.

**4. The packager copies `frontend/dist/` verbatim.**
It never rebuilds. Build the frontend immediately before packaging or you will
ship a stale UI with a current backend.

**5. Never delete `~/.local/share/MonoCameraGeolocator/`.**
It is not a version — it is `pgdata`, `work/.env` and the DEM library. Upgrades
preserve it deliberately.

**6. The app carries its own log monitor.** (2026-09-01)
Status chip (top bar) → **Open app status & logs**, or browse to `/status`.
Every component explained, plus a live, filterable tail of the server's log —
tracebacks, request ids, the lot. Same data over HTTP:
`curl -s http://127.0.0.1:8123/api/v1/health/logs?level=error`. Start there
before reaching for journalctl.

---

## Two paths you will type constantly

```bash
REPO=~/Desktop/GEO-1                        # git runs from here
SW=$REPO/tools/mono-camera-geolocator              # almost everything else
```

`git`, `gh` and the workflow file live at the repo root. Tests, builds and the
desktop app live under `tools/mono-camera-geolocator/` (the folder some older
notes still call `software/` — same place, renamed). Running the right command
from the wrong one is the most common small mistake.

---

## Keeping this current

When something costs you more than ten minutes to work out, add it. The value
here is not the commands — those are discoverable — it is the ★ notes that say
which obvious-looking thing is a trap.
