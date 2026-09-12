# LandExplorer API — errors

**Derived from `CONTRACT.md` §6.3, §11 · amended by [`SCOPE.md`](../architecture/SCOPE.md) §4 rule 3.**

---

## 1. The envelope

**Every non-2xx response has this exact shape** — including FastAPI's own `RequestValidationError` and
unhandled exceptions. `ErrorEnvelope` is registered via a shared `COMMON_ERROR_RESPONSES` dict on
**every** route, so `openapi.json` documents it everywhere rather than on a lucky few. *A missing 404
in the spec becomes an untyped `any` in the generated client.*

```jsonc
{
  "error": {
    "code": "GCP_ADJUSTMENT_AMBIGUOUS",   // ★ STABLE, machine-readable, SCREAMING_SNAKE.
                                          //   The client switches on this. Never localised.
    "message": "…",                       // human, English, safe to display.
                                          //   NEVER SQL, stack frames, file paths, or provider keys.
    "status": 422,                        // mirrors HTTP. Duplicated in-body deliberately:
                                          //   it survives logging, proxies, and client libs.
    "feature": null,                      // ★ "deferred" on 501; null everywhere else. See §2.
    "details": [                          // ErrorDetail[] | null
      { "loc": ["body", "lat"], "msg": "…", "type": "…", "input": null }
    ],
    "request_id": "01J5X8QKZ3P7VN2M4RB9TCWDFA",  // ULID. Also the X-Request-ID header.
                                                  //   The string a user pastes into a bug report.
    "timestamp": "2026-07-17T10:31:02.481Z",
    "docs_url": "https://…"               // nullable
  }
}
```

**The single explicit exception:** `GET /health/ready` returns `ReadinessResponse` on 503, not
`ErrorEnvelope` — *a probe wants the check detail, and that response is not an application error.*

**A single handler** reads `exc.status` / `exc.code`. **There is no per-exception `if`-ladder.**

---

## 2. ★ `501 NOT_IMPLEMENTED` — the deferred-feature contract

**The automatic matching engine is DEFERRED** ([`SCOPE.md`](../architecture/SCOPE.md) §1,
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). Endpoints
**30, 43, 47, 48, 49** are registered, documented, and return:

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

### The three rules a client can rely on

1. **`code === "NOT_IMPLEMENTED"` and `feature === "deferred"`.** Both are stable; switch on either.
   `feature` is **`null` on every other response**, so `error.feature === "deferred"` is a total test
   for "this is a planned-but-absent feature" without string-matching a message.
2. ★ **It is never a 404.** *The feature is planned, not absent.* A 404 would say *"no such image"* or
   *"this image has no pose"* — statements about **data**. The truth is a statement about **the
   build**. `SCOPE.md` §4 rule 3 makes the distinction normative.
3. ★ **It never fakes a result.** No fabricated coordinate, no placeholder confidence, no empty-but-
   successful `202` for a job that will never run. **Never `pass`, never a silent `None`.**

### ★ Implementation note — `ErrorBody.feature` and `FeatureDeferredError` are additions

`CONTRACT.md` §6.3 defines `ErrorBody` **without a `feature` field**, and its exception hierarchy has
**no 501 branch** — because it was written for the build in which matching works. `SCOPE.md` §4 rule 3
mandates the marker, and **`SCOPE.md` overrides `CONTRACT.md`.**

The minimal additive resolution, recorded as **S-4** in
[`TRACEABILITY.md` §4.1](../architecture/TRACEABILITY.md#41--schema-and-api-additions-that-manual-mode-requires--escalated):

```python
# backend/app/schemas/errors.py  (IU-17)
class ErrorBody(ApiModel):
    code: str
    message: str
    status: int
    feature: str | None = None      # ★ "deferred" on 501; None everywhere else.
    details: list[ErrorDetail] | None = None
    request_id: str
    timestamp: datetime
    docs_url: str | None = None


# backend/app/core/exceptions.py  (IU-15)
class FeatureDeferredError(LandExplorerError):
    """A feature that is specified, planned, and not implemented in this build (SCOPE.md §4)."""
    code: ClassVar[str] = "NOT_IMPLEMENTED"
    status: ClassVar[int] = 501
```

**Additive, snake_case, `None` everywhere else — so no existing response shape changes.** The handler
(IU-21) sets `feature` from the exception. Owners: **IU-15** (`exceptions.py`), **IU-17**
(`errors.py`), **IU-21** (the handler).

---

## 3. Error codes by status

| Status | Codes |
|---|---|
| **400** | `EMPTY_PATCH` · `EMPTY_PATCH_ERROR` |
| **401** | `MISSING_CREDENTIALS` · `INVALID_CREDENTIALS` |
| **403** | `PROVIDER_TOS_FORBIDDEN` · `READ_ONLY_MODE` |
| **404** | `PROJECT_NOT_FOUND` · `IMAGE_NOT_FOUND` · `ANNOTATION_NOT_FOUND` · `JOB_NOT_FOUND` · `MATCH_RESULT_NOT_FOUND` · `GCP_NOT_FOUND` · `REVISION_NOT_FOUND` · `ANNOTATION_VERSION_NOT_FOUND` · `EXPORT_NOT_FOUND` · `BATCH_NOT_FOUND` · `SUGGESTION_NOT_FOUND` · `CAMERA_POSE_NOT_AVAILABLE` · `HEATMAP_NOT_AVAILABLE` · `UNKNOWN_PROVIDER` |
| **409** | `MATCH_JOB_ALREADY_RUNNING` · `EXPORT_NOT_READY` · `JOB_NOT_CANCELLABLE` · `REVISION_CONFLICT` · `REVISION_RESTORE_CONFLICT` · `IMAGE_STILL_PROCESSING` · `PROJECT_HAS_ACTIVE_JOBS` · `GCP_CODE_CONFLICT` · `PROJECT_NAME_CONFLICT` · `IDEMPOTENCY_KEY_REUSED` · `IDEMPOTENCY_IN_PROGRESS` · `GCP_ORIGINAL_UNAVAILABLE` |
| **410** | `EXPORT_EXPIRED` · `IMAGE_PURGED` · `REVISION_PRUNED` · `SATELLITE_IMAGE_PURGED` |
| **412** | `STALE_ANNOTATION_VERSION` · `STALE_GCP_VERSION` · `STALE_PROJECT_VERSION` |
| **413** | `UPLOAD_TOO_LARGE` · `BATCH_TOO_LARGE` |
| **415** | `UNSUPPORTED_IMAGE_FORMAT` |
| **416** | `RANGE_NOT_SATISFIABLE` |
| **422** | `INVALID_BBOX` · `BBOX_CROSSES_ANTIMERIDIAN` · `INVALID_SORT_FIELD` · `UNKNOWN_QUERY_PARAM` · `PARAM_CONFLICT` · `SEARCH_HINT_REQUIRED` · `ZOOM_OUT_OF_RANGE` · `SEARCH_AREA_TOO_LARGE` · `NO_ANNOTATIONS` · `GCP_ADJUSTMENT_AMBIGUOUS` · `GCP_OUT_OF_BOUNDS` · `ANNOTATION_GEOMETRY_INVALID` · `ANNOTATION_OUT_OF_BOUNDS` · `TOO_MANY_ANNOTATIONS` · `GEOMETRY_TOO_COMPLEX` · `STATIC_IMAGE_TOO_LARGE` · `IMAGE_TOO_LARGE` · `NO_ADJUSTED_GCPS` · `INSUFFICIENT_ANCHORS` · `REVISION_REPLAY_TOO_EXPENSIVE` |
| **428** | `PRECONDITION_REQUIRED` · `CONFIRMATION_REQUIRED` |
| **429** | `RATE_LIMIT_EXCEEDED` · `PROVIDER_RATE_LIMITED` |
| **500** | `INTERNAL_ERROR` · `ARTIFACT_WRITE_FAILED` · `ARTIFACT_READ_FAILED` |
| **★ 501** | **`NOT_IMPLEMENTED`** — §2 |
| **502** | `PROVIDER_UPSTREAM_ERROR` · `PROVIDER_INVALID_RESPONSE` |
| **503** | `PROVIDER_NOT_CONFIGURED` · `DATABASE_UNAVAILABLE` · `REDIS_UNAVAILABLE` · `WORKER_UNAVAILABLE` |
| **507** | `INSUFFICIENT_STORAGE` |

★ **`ApiErrorCode` is GENERATED and byte-compared in CI** (§13.4 rule 11), exactly as `schema.ts` is.
*Anything that mirrors a Python source of truth is generated or it drifts.*

---

## 4. The 500 handler

Logs `exc_info=True` with `request_id`, route and principal; increments
`unhandled_exceptions_total{route}`; and returns **exactly**:

```json
{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred.","status":500,
          "feature":null,"details":null,"request_id":"…","timestamp":"…","docs_url":null}}
```

★ **Never the exception string.** *Tracebacks contain storage paths, connection strings, and provider
keys.* With `LE_DEBUG=true` **only**, `details` carries
`[{"loc":[],"msg":"<repr>","type":"debug.traceback"}]`.

---

## 5. What is NOT an error

This is the section most likely to save you a support ticket.

### 5.1 A missing weight, key, optional dependency or GPU (L11)

> **A WARNING log line, a `WarningItem` on the response, a metric increment, and a fallback — never a
> traceback, and never silent. It is never a 4xx/5xx WHEN IT AFFECTS A DEFAULT.**

**Two exceptions**, both of which are the law working rather than breaking:

1. A client **explicitly requests** an unconfigured **provider** → **`503 PROVIDER_NOT_CONFIGURED`**.
   *An explicit request is not a default.*
2. Any unavailability under `LE_IMAGERY_STRICT=true` / `LE_AI_STRICT_BACKEND=true` → **raise**.
   *Dev is forgiving; prod is loud.*

★ **The asymmetry is deliberate — do not "fix" it.** An explicitly requested unconfigured **provider**
is a `503`, but an explicitly requested missing **weight** (`matcher: "superglue"`) is a `202` +
fallback + `WarningItem`.

> **Imagery changes the answer's *provenance*; a matcher changes only its *accuracy*.**

Silently serving 10 m Sentinel when the operator paid for 0.3 m Mapbox is worse than a 503. Silently
serving SIFT instead of SuperGlue is a **reported** accuracy trade. **Both are reported; only one is
refusable.**

### 5.2 "No match" (§11.6)

| Outcome | Job status | Response |
|---|---|---|
| Every window rejected by the confidence gate | **`succeeded`** | `result_count = 0`, `best_confidence = null`, **an empty page — not a 404** |
| Every window rejected by a hard degeneracy check | **`succeeded`** | Same, plus the `DegeneracyReport` per candidate so a reviewer can see *why* |
| Winner's margin < `LE_AI_RANK_MARGIN` | **`succeeded`** | `AMBIGUOUS_MATCH` warning, **candidates returned and visible** |
| The pipeline could not run (provider down, DB down, OOM) | **`failed`** | `error` populated |

> Modelling "no match" as `failed` would **trigger pointless retries of a deterministic outcome** and
> would tell the surveyor the system broke when the answer is *"not here"*. **`failed` is reserved for:
> the pipeline could not run.**

★ **Moot in this build** — matching is deferred; endpoint 30 is a 501. Documented because the
distinction is normative for the future engine and because §5.2's shape is *why* endpoint 34 returns an
empty page rather than a 501 (see [`endpoints.md` §7](endpoints.md#7-matching--jobs--★-mostly-deferred)).

### 5.3 An empty page

`GET /images/{id}/match-results`, `/landmark-suggestions` and `/semantic-features` return **`200` with
an empty page** in this build. The tables exist and hold no rows (`SCOPE.md` §4 rule 5). **The query
worked; there is nothing there.** That is not an error, and it is not a 404.

### 5.4 `204` from a tile

A valid tile address with no imagery (ocean, a gap in coverage) is **`204`**, deliberately. Not an
error. Leaflet renders nothing.

---

## 6. Client guidance

```ts
// frontend/src/api/client.ts — ErrorEnvelope → ApiError
if (err.code === "NOT_IMPLEMENTED") {
  // ★ Deferred in this build. Disable the control, show the honest tooltip.
  //   Do NOT retry. Do NOT show a spinner. Do NOT surface it as a crash.
  //   SCOPE.md §4 rule 4.
}
if (err.status === 412) { /* refetch, re-apply, retry once — someone else edited it */ }
if (err.status === 409 && err.code === "EXPORT_NOT_READY") { /* poll; it is still rendering */ }
if (err.status === 410) { /* gone for good — re-request the export, do not retry the download */ }
if (err.status === 503 && err.code === "WORKER_UNAVAILABLE") { /* surface: workers are down */ }
```

**Never parse `message`.** It is human, English, and may change. **`code` is the contract.**

**Always surface `request_id`** in any error UI. It is the one string that makes a bug report
actionable.
