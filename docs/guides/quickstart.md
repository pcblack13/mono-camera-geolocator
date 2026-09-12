# Quickstart — clone → run → your first GCP

**Ten minutes, no API keys, no GPU, no model weights.**

---

## ★ What you are about to use

**LandExplorer is a manual GCP surveying tool.** You mark a landmark in a photograph, click the same
physical spot on a satellite map, and **the coordinate is recorded as a direct observation — not an
inference.**

**The automatic matching engine is DEFERRED and is not in this build**
([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). `POST /images/{id}/match`
returns **`501`**, and the UI's automatic controls are **disabled with an honest tooltip**. That is a
deliberate ruling, not an unfinished feature — the reasoning is a ~90° viewpoint problem and the fact
that **a confidently-wrong coordinate handed to a surveyor is this system's worst failure mode.**

---

## 1. Run it

```bash
git clone <repo> landexplorer && cd landexplorer
docker compose -f infra/compose/docker-compose.yml up
```

★ **No `.env`. Zero required variables** (L10). **The default imagery provider is keyless** (L2) — you
get a working satellite view with no keys at all.

→ **http://localhost:8080**

**No Docker?** ★ It is **not installed on this machine**. See
**[running-locally.md](running-locally.md)** — the honest bare-host path.

**No network?** ★ Supported, and first-class:

```bash
make seed && make up      # fixture provider + committed tiles. Works with the NIC UNPLUGGED.
```

See [offline-mode.md](offline-mode.md).

---

## 2. Check it is healthy

```bash
curl -s localhost:8000/api/v1/health/ready?verbose=true | jq
```

★ **`models: degraded` is EXPECTED and returns `200`.** There are no weights, matching is deferred, and
**`models` never affects readiness.** *If missing weights made the app unready, it would never start
here.*

---

## 3. Your first GCP — in the UI

1. **New project** → name it.
2. **Upload a photo** — JPG, PNG, TIFF or GeoTIFF, up to 500 MB.
   ★ *A **GeoTIFF** is already georeferenced: it yields exact GCPs with no clicking at all.*
3. **Mark a landmark.** Point tool → click a feature you can also identify from above: a fence corner,
   a gate post, a road junction, the corner of a greenhouse.
   ★ *Pick what **you** know is the control point. That judgement is the product's actual input
   ([ADR-014](../architecture/adr/ADR-014-landmarks-are-user-marked.md)).*
4. **Click the same spot on the satellite map.** Both panes show a live linked marker while the
   correspondence is open.
5. **Declare your confidence** (1–5 / low-med-high) and **commit**.
   ★ *Confidence is **yours**. Nothing computes it, and no server path will ever overwrite it
   ([ADR-006](../architecture/adr/ADR-006-confidence-gating.md)).*
6. **Read the accuracy.** Every GCP carries `total_ce90_m` **and** a `dominant_term`.
   ★ *`"georeference"` means **your click was better than the basemap** — zooming further will not
   help; a better provider will.*
7. **Export.** CSV, GeoJSON, KML/KMZ, Shapefile, GPKG, DXF or PDF.
   ★ *CSV/GeoJSON/KML/KMZ are **stdlib-only and can never degrade** — you can always get your
   coordinates out.*

★ **An uncommitted correspondence never appears in the GCP table or an export.** Until you commit, it
is browser state only.

---

## 4. The same thing as `curl`

```bash
export API=http://localhost:8000/api/v1

PROJECT=$(curl -s -X POST $API/projects -H 'Content-Type: application/json' \
  -d '{"name":"Quickstart"}' | jq -r .id)

IMAGE=$(curl -s -X POST $API/images \
  -F "project_id=$PROJECT" -F "file=@field-photo.jpg" | jq -r .id)

curl -s -X POST $API/images/$IMAGE/annotations -H 'Content-Type: application/json' \
  -d '{"kind":"landmark","geom_type":"point","pixel_x":2113.5,"pixel_y":1204.0,
       "geometry":{"type":"Point","coordinates":[2113.5,1204.0]},
       "label":"NE fence corner","confidence":0.9}' | jq

# ★ THE PRODUCT: photo pixel ↔ map click → a GCP
curl -s -X POST $API/images/$IMAGE/gcps -H 'Content-Type: application/json' \
  -d '{"image_px":{"x":2113.5,"y":1204.0},
       "lat":51.9912345,"lon":4.2108765,
       "confidence":80,"code":"GCP01"}' | jq

curl -s "$API/images/$IMAGE/gcps" | jq '.items[] | {code, lat, lon, confidence, source,
                                                    total: .accuracy.total_ce90_m,
                                                    limited_by: .accuracy.dominant_term}'
```

Full walkthrough with every response shape: **[api-usage.md](api-usage.md)**.

---

## 5. What you will NOT find, and why

| | |
|---|---|
| ★ **An "auto-match" button that works** | **DEFERRED.** `POST /match` → `501` + `feature: "deferred"`. **Not a 404, never a fake result.** [ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md) |
| ★ **Automatic landmark suggestions** | **DEFERRED.** The control is disabled with an honest tooltip. |
| ★ **A camera pose or a confidence heatmap** | **DEFERRED.** `501`. |
| ★ **A computed confidence** | **There is none.** Confidence is **surveyor-declared** in this build, by design. |
| **Google Earth as a basemap** | ★ **Structurally excluded — not a disabled flag, an absence.** No provider, no enum member, unrepresentable in the type system. [ADR-002](../architecture/adr/ADR-002-abstract-the-imagery-provider.md) · [legal](../legal/imagery-terms.md) |

**Everything deferred is listed, loudly, in [`TRACEABILITY.md`](../architecture/TRACEABILITY.md).**

---

## 6. ★ Before you use this for real work

> **The keyless Esri default is a BOOTSTRAPPING decision, not a licensing one. Reachable ≠ licensed.**

**"Derive a survey control point from the imagery and sell it as a deliverable" is a materially
different use from "show a map in an app"** — and it is the use most likely to exceed the terms of any
web basemap.

★ **Read [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) §4 (the operator checklist) before
any commercial deployment.** If you own your own orthophotos, drop them in `./data/orthophotos` —
`local_orthophoto` wins automatically, has **no third party in the request path**, and is **the only
path where total error is knowable**.

---

## 7. Next

| | |
|---|---|
| Configure it | [configuration.md](configuration.md) |
| Understand it | [architecture-tour.md](architecture-tour.md) |
| Know exactly what is real | ★ [`TRACEABILITY.md`](../architecture/TRACEABILITY.md) |
| Contribute | [contributing.md](contributing.md) |
