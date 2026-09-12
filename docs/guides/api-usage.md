# API usage — the whole product, as `curl`

**Base:** `http://localhost:8000/api/v1` · **Auth:** none by default · **Casing:** snake_case (L9)

Every command below is runnable. Reference: [`docs/api/endpoints.md`](../api/endpoints.md).

```bash
export API=http://localhost:8000/api/v1
```

---

## ★ The flow this build actually supports

```
upload a photo  →  mark a landmark  →  click the same spot on the map  →  a GCP  →  export
                                       ▲
                                       └── a DIRECT OBSERVATION, not an inference
```

**There is no `POST /match` step.** The automatic matching engine is **DEFERRED**
([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)) and endpoint 30 returns
**501**. §7 below shows exactly what you get if you call it.

---

## 1. Is it alive?

```bash
curl -s $API/health | jq
curl -s "$API/health/ready?verbose=true" | jq
```

```jsonc
// /health/ready — a healthy dev box in THIS build
{
  "status": "ready",
  "checks": {
    "postgres": { "status": "up" },
    "redis":    { "status": "up" },
    "storage":  { "status": "up" },
    "celery":   { "status": "up" },
    "imagery":  { "status": "up", "provider": "esri_world_imagery" },
    "raster":   { "status": "degraded", "backend": "gdal" },   // ★ rasterio absent, GDAL substitutes
    "models":   { "status": "degraded",                        // ★ EXPECTED — never affects readiness
                  "message": "Automatic matching is deferred in this build (SCOPE.md §1)." }
  },
  "auth_mode": "none"
}
```

> ★ **`models: degraded` and `raster: degraded` are both correct here** and return **`200`**. Only
> `postgres`, `redis` and `storage` gate readiness — *returning 503 would take the whole UI offline,
> including the screens that would tell the operator what is wrong.*

## 2. What can this deployment do?

```bash
curl -s $API/capabilities | jq
```

★ **Query this rather than assuming.** It reports the **live** export-format list (optional deps are
**dropped, not crashed on**), the provider list, the raster backend, and — in this build — every
matching component as **deferred**. It reads the **cached** `PreflightReport` and never re-resolves;
*re-sha256'ing a 2.4 GB SAM checkpoint per request is not a health check, it is an outage.*

## 3. A project

```bash
PROJECT=$(curl -s -X POST $API/projects \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "Westland greenhouse survey",
        "description": "Manual GCP survey, block 4",
        "default_provider": "esri_world_imagery",
        "tags": ["2026", "westland"]
      }' | jq -r .id)
echo "project: $PROJECT"
```

## 4. Upload a photo

```bash
IMAGE=$(curl -s -X POST $API/images \
  -H "Idempotency-Key: $(uuidgen)" \
  -F "project_id=$PROJECT" \
  -F "file=@/path/to/field-photo.jpg" | jq -r .id)
echo "image: $IMAGE"
```

**`201 ImageRead`** = small file, ingested inline, ready to annotate.
**`202 ImageUploadAccepted`** = above `LE_ASYNC_INGEST_THRESHOLD_BYTES` (50 MB) — poll the job:

```bash
curl -s "$API/jobs/$JOB_ID?wait=10" | jq '.status, .progress'   # long-poll up to 10s
curl -s $API/images/$IMAGE | jq '.status'                       # -> "ready"
```

**MIME is sniffed, not trusted from the header.** JPG, PNG, TIFF, GeoTIFF, WebP. Max 500 MB.

```bash
curl -s $API/images/$IMAGE/metadata | jq
```

```jsonc
{
  "file":   { "filename": "field-photo.jpg", "size_bytes": 4718592, "checksum_sha256": "…" },
  "raster": { "width": 4032, "height": 3024, "band_count": 3 },
  "gps":    { "lat": 51.99, "lon": 4.21, "hpe_m": 8.0, "source": "exif" },  // null if no EXIF GPS
  "camera": { "make": "Apple", "model": "iPhone 14 Pro", "focal_length_mm": 6.86 },
  "is_geotiff": false
}
```

> ★ **If `is_geotiff` is `true`, the upload is already georeferenced** and exact GCPs are derivable
> **with no matching and no clicking at all** (`SCOPE.md` §3). `detect_georeferencing()` distinguishes
> a real geotransform from **GDAL's identity transform on a plain TIFF**.

## 5. Mark a landmark

```bash
ANNOTATION=$(curl -s -X POST $API/images/$IMAGE/annotations \
  -H 'Content-Type: application/json' \
  -d '{
        "kind": "landmark",
        "geom_type": "point",
        "pixel_x": 2113.5,
        "pixel_y": 1204.0,
        "geometry": { "type": "Point", "coordinates": [2113.5, 1204.0] },
        "label": "NE fence corner",
        "description": "Concrete post, base centre",
        "confidence": 0.9
      }' | jq -r .id)
```

> ★ **`geometry` is GeoJSON-*shaped* but carries IMAGE PIXELS** — `[x, y]`, **y-down**, SRID 0.
> **`AnnotationCreate` REJECTS a `crs` member.** It is not a geographic geometry and must never be
> mistaken for one.
>
> ★ **`confidence` here is 0–1 and is the SURVEYOR'S certainty** — never a detector's score
> ([ADR-014](../architecture/adr/ADR-014-landmarks-are-user-marked.md)). *(`GcpRead.confidence` is
> **0–100**. Two scales, two meanings.)*
>
> ★ **`pixel_x`/`pixel_y` are in ORIGINAL image pixel space** — independent of viewer zoom, brightness
> or contrast. The client converts with `D = variant_width / original_width` (§8.6). **This conversion
> is normative and correctness-critical.**

## 6. ★ Place the GCP — the manual correspondence

**This is the product.** The surveyor has the landmark in the photo; now they click the same physical
spot on the satellite map, and that coordinate is recorded directly.

```bash
GCP=$(curl -s -X POST $API/images/$IMAGE/gcps \
  -H 'Content-Type: application/json' \
  -d '{
        "image_px":    { "x": 2113.5, "y": 1204.0 },
        "lat":         51.9912345,
        "lon":         4.2108765,
        "confidence":  80,
        "landmark_id": "'"$ANNOTATION"'",
        "code":        "GCP01"
      }' | jq -r .id)
```

```jsonc
// 201 GcpRead
{
  "id": "…",
  "image_id": "…",
  "source": "manual",              // ★ ALWAYS. An automatic GCP can never be confused with an observed one.
  "match_result_id": null,         // ★ there is no match — this is a direct observation
  "landmark_id": "…",
  "code": "GCP01",
  "image_px":  { "x": 2113.5, "y": 1204.0 },
  "lat": 51.9912345, "lon": 4.2108765,
  "crs": "EPSG:4326",              // ★ always. Present so nobody has to assume.
  "elevation_m": null,             // ★ null + elevation_source null => ELEVATION_UNAVAILABLE.
  "elevation_source": null,        //   The source may NEVER name a producer that did not run.
  "confidence": 80.0,              // ★ EXACTLY what you sent. Never computed. Never overwritten.
  "accuracy": {
    "confidence_level": "ce90",    // ★ every *_ce90_m is a 2-D 90% radius (2.146σ)
    "relative_ce90_m": 0.31,       //   click precision at this zoom + imagery GSD
    "georef_ce90_m": 3.0,          //   the PROVIDER's contribution
    "total_ce90_m": 3.02,          //   sqrt(relative² + georef²) — THE headline number
    "dominant_term": "georeference"  // ★ "your accuracy is limited by the basemap, not the match"
  },
  "has_direct_fix": true,          // ★ the surveyor's click IS a direct fix
  "residual_px": null,             // ★ no homography => no residual. `null` is honest; `0` would not be.
  "manually_adjusted": false,
  "is_stale": false
}
```

**Read the `accuracy` block, every time.** `dominant_term: "georeference"` means **your click was
better than the basemap** — more zooming will not help; a better provider will. ★ **Reported accuracy
excludes the provider's own georegistration error for web providers**, so it is *optimistic*
everywhere except `local_orthophoto` (see [legal §3.5](../legal/imagery-terms.md)).

★ **`confidence` is surveyor-declared and never computed** (`SCOPE.md` §5,
[ADR-006](../architecture/adr/ADR-006-confidence-gating.md)). A 1–5 or low/med/high UI maps to 0–100
**in the client**, deliberately and visibly.

## 7. ★ What matching does in this build

```bash
curl -s -i -X POST $API/images/$IMAGE/match \
  -H 'Content-Type: application/json' \
  -d '{"search_hint": {"lat": 51.99, "lon": 4.21, "radius_m": 500}}'
```

```http
HTTP/1.1 501 Not Implemented
Content-Type: application/json
X-Request-ID: 01J5X8QKZ3P7VN2M4RB9TCWDFA
```
```json
{
  "error": {
    "code": "NOT_IMPLEMENTED",
    "message": "Automatic matching is not enabled in this build. Place GCPs manually: POST /api/v1/images/{image_id}/gcps. See docs/architecture/SCOPE.md.",
    "status": 501,
    "feature": "deferred",
    "details": null,
    "request_id": "01J5X8QKZ3P7VN2M4RB9TCWDFA",
    "timestamp": "2026-07-17T10:31:02.481Z",
    "docs_url": "https://docs.landexplorer.local/scope#deferred"
  }
}
```

★ **Not a 404** — the feature is *planned*, not *absent*. ★ **Never a fake result.** Same for
`/suggest-landmarks`, `/segment`, `/camera-pose`, `/heatmap`.

## 8. Review and adjust

```bash
curl -s "$API/images/$IMAGE/gcps?limit=50&sort=code" | jq '.items[] | {code, lat, lon, confidence, total: .accuracy.total_ce90_m}'
curl -s "$API/images/$IMAGE/gcps?format=geojson" | jq        # RFC 7946: [lon, lat], no `crs` member
```

**Adjusting requires `If-Match`** — someone else may have edited it:

```bash
ETAG=$(curl -s -I $API/gcps/$GCP | awk -F'"' '/[Ee][Tt]ag/{print $2}')

curl -s -X PATCH $API/gcps/$GCP \
  -H "If-Match: \"$ETAG\"" \
  -H 'Content-Type: application/json' \
  -d '{"lat": 51.9912400, "lon": 4.2108800, "adjustment_note": "Re-checked against RTK fix"}' | jq
```

| You send | Server does |
|---|---|
| `lat`/`lon` only | Sets `geom`; **derives** `satellite_px` by the inverse chain |
| `satellite_px` only | Sets it; **derives** `lat`/`lon` by the forward chain |
| **both** | Compares them. Within 0.5 m → accept. Beyond → **`422 GCP_ADJUSTMENT_AMBIGUOUS`** |
| neither (`code`/`note` only) | Metadata-only. ★ **Renaming a GCP is not adjusting it.** |

> ★ **`image_px` is NOT adjustable here.** Moving the point *on the photograph* is
> `PATCH /annotations/{id}`, which marks this GCP **stale**. **Two endpoints, two meanings:** *"the
> coordinate is in the wrong place"* vs *"I marked the wrong pixel"*.
>
> ★ **`confidence` is left untouched by every adjustment.** A surveyor nudging a marker 3 m is
> *guessing better*, not measuring.
>
> ★ **Staleness is a flag and never an auto-recompute.** A GCP may already be in a survey report, a
> contract, or a machine-control file. **It changes when a human decides it changes.**

## 9. Export

```bash
JOB=$(curl -s -X POST "$API/images/$IMAGE/export?format=csv" \
  -H 'Content-Type: application/json' \
  -d '{"filter": {"is_included_in_export": true}}' | jq -r .id)

curl -s "$API/jobs/$JOB?wait=10" | jq '.status'
EXPORT=$(curl -s $API/jobs/$JOB | jq -r '.result_ref.id')

curl -sL -o gcps.csv $API/exports/$EXPORT/download
```

| Format | Availability |
|---|---|
| `csv` · `geojson` · `kml` · `kmz` | ★ **stdlib only — can NEVER degrade.** *So the surveyor can always get their coordinates out, regardless of environment.* |
| `shapefile` · `gpkg` | needs geopandas/fiona — **dropped from `/capabilities` when absent** |
| `dxf` | needs ezdxf — dropped |
| `pdf` | needs reportlab — dropped |

**Guarantees:** CSV → UTF-8 **BOM**, ★ **longitude before latitude**, 8 dp. GeoJSON → RFC 7946,
`[lon, lat]`, ★ **no `crs` member**. ★ **A GCP with `elevation_m: null` exports an EXPLICIT empty cell,
never a silent blank.** Every bundle carries `checksum_sha256`.

★ **Attribution is included by default and should not be turned off** — several providers' ToS require
it on derived output. It is served **from the stored row**, never by re-resolving a provider that may
have been reconfigured since the pixels were fetched.

**Download codes:** `409` = still rendering (poll). `410` = expired (`LE_EXPORT_TTL_SECONDS`, 7 d) —
re-request it. **Neither is a 404**; the distinction between *"not yet"*, *"gone"* and *"never
existed"* is one you can act on.

## 10. Imagery

```bash
curl -s $API/imagery/providers | jq '.items[] | {name, configured, max_zoom, attribution}'
curl -s -o tile.png "$API/imagery/tiles/esri_world_imagery/18/134526/86014?kind=satellite"
curl -s -o chip.png "$API/imagery/static?bbox=4.2100,51.9908,4.2118,51.9918&zoom=18&kind=hybrid"
```

★ **`tile_url_template` is our proxy path for EVERY provider by default** — keys never reach the
browser, and the ToS chokepoint, the shared quota bucket and cache identity all apply to browser
traffic too ([ADR-010](../architecture/adr/ADR-010-tile-proxy.md)).

★ **`204` on a valid tile with no imagery** (ocean, gap) is deliberate — **not an error**.

`/imagery/static` is **request-scale**: 16 tiles / 4 MP. Beyond ⇒ `422 STATIC_IMAGE_TOO_LARGE`.
*A 64-megapixel stitch inside a GET is the workload L5 forbids.*

## 11. Version history

```bash
curl -s -X POST $API/projects/$PROJECT/revisions \
  -H 'Content-Type: application/json' -d '{"label": "Before field re-check"}' | jq
curl -s $API/projects/$PROJECT/revisions | jq '.items[] | {id, label, created_at}'
curl -s $API/images/$IMAGE/annotation-versions | jq '.items[] | {version_no, op, created_at}'
curl -s -X POST $API/revisions/$REVISION/restore \
  -H 'Content-Type: application/json' -d '{"image_id": "'"$IMAGE"'"}' | jq
```

★ **Restoring marks affected GCPs `is_stale`. It never recomputes them.**

---

## Error handling — the short version

```bash
curl -s $API/gcps/00000000-0000-0000-0000-000000000000 | jq .error.code   # "GCP_NOT_FOUND"
```

- ★ **Never parse `error.message`.** Switch on **`error.code`** — stable, SCREAMING_SNAKE, never localised.
- ★ **Always surface `error.request_id`.** It is the one string that makes a bug report actionable.
- **`501` + `feature: "deferred"`** ⇒ do **not** retry, do **not** spin. Disable the control.
- **`412`** ⇒ refetch, re-apply, retry once.
- **`503 PROVIDER_NOT_CONFIGURED`** ⇒ you explicitly asked for a provider with no key. *An explicit
  request is not a default.*
- **An empty page is not a 404.** `/match-results` returns `200` with `items: []` — the table exists
  and holds no rows.

Full reference: [`docs/api/errors.md`](../api/errors.md).
