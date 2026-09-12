# LandExplorer API documentation

**Base path:** `/api/v1` · **Casing:** snake_case everywhere (L9) · **Auth:** off by default
(`LE_AUTH_MODE=none`)

| Document | What it covers |
|---|---|
| **[endpoints.md](endpoints.md)** | The full endpoint reference, derived from `CONTRACT.md` §7. ★ **Every deferred endpoint is marked as returning 501 in this build.** |
| **[errors.md](errors.md)** | The error envelope, every code by status, the **`501` deferred-feature contract**, and — importantly — **what is NOT an error**. |
| **[openapi-notes.md](openapi-notes.md)** | How `openapi.json` is generated, why CI byte-compares the generated client, and why deferred endpoints stay in the spec. |
| **[../guides/api-usage.md](../guides/api-usage.md)** | The same flows as runnable `curl`. **Start here if you want to see it work.** |

---

## ★ What this build actually does

**LandExplorer is delivered as a manual GCP surveying tool.** The surveyor marks a landmark in the
photograph, clicks the same physical spot on the satellite map, and **the coordinate is recorded as a
direct observation, not an inference.**

**The automatic matching engine is DEFERRED** ([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). **Five endpoints return
`501 Not Implemented`** with `feature: "deferred"`:

| # | Endpoint |
|---|---|
| 30 | `POST /images/{image_id}/match` |
| 43 | `POST /images/{image_id}/suggest-landmarks` |
| 47 | `POST /images/{image_id}/segment` |
| 48 | `GET /images/{image_id}/camera-pose` |
| 49 | `GET /images/{image_id}/heatmap` |

**They do not 404. They never fake a result.** Full contract: [errors.md §2](errors.md#2--501-not_implemented--the-deferred-feature-contract).

**What replaces matching:** `POST /images/{image_id}/gcps` — the manual correspondence. See
[endpoints.md §7](endpoints.md#7-gcps--★-the-deliverable).

---

## The shape of the API in one table

| Group | Endpoints | Notes |
|---|---|---|
| Health · Capabilities | 1–3 | `/health` touches no dependency. `/health/ready` never 500s. |
| Projects | 4–8 | |
| Images | 9–15 | Upload is `201` (small) or `202` (large, async ingest). |
| Annotations | 16–22 | Pixel geometry, **not** geographic. `confidence` is 0–1, the surveyor's. |
| Revisions | 23–29 | Version history. Restoring marks GCPs **stale**, never recomputes. |
| Matching · Jobs | 30–37, 64 | ★ **30 is 501.** Jobs (31–33) are live and matter — ingest/export/batch. |
| **GCPs** | **38–42, 65, 66** | ★ **The deliverable.** 65 (`POST`) is the manual correspondence. |
| Suggestions · Semantics · Pose · Heatmap | 43–49 | ★ **43, 47, 48, 49 are 501.** 44/46 return empty pages. |
| Imagery | 50–53 | Tile proxy. Keys never reach the browser. |
| Batch | 54–57 | Upload/metadata/export only — **no batch matching**. |
| Exports | 58–63 | CSV/GeoJSON/KML/KMZ **can never degrade** (stdlib only). |

★ **Only seven endpoints initiate async work** — 30, 42, 43, 47, 54, 58, 59 — and they return `202`.
**Everything else answers immediately.** *That is the shape of a system where CV never touches a
request handler* (L5).

---

## Conventions worth knowing before you start

- **`request_id`** (ULID) is on every response as `X-Request-ID` and in every error body. **Surface it.**
- **`If-Match` is REQUIRED** on `PATCH /annotations/{id}` and `PATCH /gcps/{id}` → `412` on staleness.
- **`X-Confirm-Delete`** is required for hard deletes and for bulk annotation delete.
- **PATCH bodies use an `UNSET` sentinel:** `{"aoi": null}` **clears**; `{}` is `400 EMPTY_PATCH`.
- **Never parse `error.message`.** Switch on `error.code`.
- **Query `GET /capabilities`** for the live export-format and provider list rather than assuming —
  optional dependencies are **dropped, not crashed on**.
