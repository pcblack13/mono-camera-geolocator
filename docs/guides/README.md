# LandExplorer — developer guides

**New here? Read [`SCOPE.md`](../architecture/SCOPE.md) first.** It is 138 lines, it **overrides
`CONTRACT.md`**, and it tells you what this build actually is.

---

## ★ The 30-second version

**LandExplorer is a manual GCP surveying tool.** A surveyor marks a landmark in a photograph, clicks
the same physical spot on a satellite map, and **the coordinate is recorded as a direct observation —
not an inference.**

**The automatic matching engine is DEFERRED**
([ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). The contract describes
it in loving detail; **we are not building it now.** Its endpoints return **`501`** with
`feature: "deferred"` — **not a 404, and never a fake result.**

**Why:** matching a **ground-level oblique photo** against **nadir satellite imagery** is a ~90°
viewpoint problem that no architecture removes, and **a confidently-wrong coordinate handed to a
surveyor is this system's worst failure mode.** Manual mode has none of that risk.

**Everything deferred is listed, loudly, in [`TRACEABILITY.md`](../architecture/TRACEABILITY.md).**

---

## The guides

| Guide | Read it when |
|---|---|
| **[quickstart.md](quickstart.md)** | You want it running and your first GCP placed. **10 minutes.** |
| **[navigation.md](navigation.md)** | The two workspace tabs, the workchain (open pages as tabs), and how to add a page. |
| **[installation.md](installation.md)** | Compose, or the bare-host prerequisites. |
| **★ [running-locally.md](running-locally.md)** | ★ **Docker is NOT installed on this machine.** The honest, verified, no-Docker path. |
| **[configuration.md](configuration.md)** | Every env var from `CONTRACT.md` §9 and what it does. |
| **[api-usage.md](api-usage.md)** | The whole product as runnable `curl`. |
| **[architecture-tour.md](architecture-tour.md)** | You are about to change something and want the map. |
| **[offline-mode.md](offline-mode.md)** | No network — ★ **a first-class supported mode, not a test flag.** |
| **[simulated-camera.md](simulated-camera.md)** | Test the monitor with **no camera**: a simulated MJPEG camera against the real backend (with stall / drop / refuse / drift controls), or a fake API for the UI alone. |
| **[kml-round-trip.md](kml-round-trip.md)** | Refining GCP positions in an external viewer and importing them back. ★ Reads **files**, never a vendor's imagery — see §1 of [the legal doc](../legal/imagery-terms.md). |
| **[adding-a-provider.md](adding-a-provider.md)** | ★ Read [the legal doc](../legal/imagery-terms.md) **first**. |
| **[adding-a-backend.md](adding-a-backend.md)** | Adding an extractor/matcher/estimator — ★ **mostly deferred stubs right now.** |
| **[contributing.md](contributing.md)** | Before your first PR. |

## Elsewhere

| | |
|---|---|
| **[`docs/api/`](../api/)** | Endpoint reference · error envelope · OpenAPI notes |
| **[`docs/legal/imagery-terms.md`](../legal/imagery-terms.md)** | ★ **Per-provider ToS, the operator checklist, and why Google Earth cannot be a provider.** A compliance obligation. |
| **[`docs/architecture/adr/`](../architecture/adr/)** | The decisions and — the point — **the rejected alternatives** |
| **[`docs/architecture/TRACEABILITY.md`](../architecture/TRACEABILITY.md)** | ★ **Every client requirement → module → BUILT or DEFERRED.** How the client checks we delivered. |
| `CONTRACT.md` | **LAW** for names. 7339 lines — **grep it, do not read it.** §4 L852 · §5 L3965 · §6 L4787 · §7 L5617 · §8 L5757 · §9 L6336 · §10 L6650 · §11 L6904 · §13 L7160 |

---

## Five facts that will save you an afternoon

1. ★ **`python -m venv` without `--system-site-packages` deletes your CV stack.** `cv2`, `numpy`,
   `scipy`, `torch` and `osgeo` are **system** packages, and **`osgeo` cannot be pip-installed back.**
   Always use `scripts/bootstrap_dev.sh`.
2. ★ **Zero required env vars** (L10). **The default imagery provider is keyless** (L2). `Settings()`
   with an empty environment **never raises**. Copying `.env.example` is **optional**.
3. ★ **`models: degraded` in `/health/ready` is CORRECT here** and returns `200`. No weights, and
   matching is deferred. **`models` never affects readiness** — *if it did, the app would never start
   on this machine.*
4. ★ **`POST /images/{id}/match` → `501` is EXPECTED.** Place GCPs manually:
   `POST /images/{id}/gcps`.
5. ★ **Docker is not installed. Compose files are authored blind and are NOT verified**
   (§13.4 rule 9). **No task may claim otherwise.**
