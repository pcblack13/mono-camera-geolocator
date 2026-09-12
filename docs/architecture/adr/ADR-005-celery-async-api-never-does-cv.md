# ADR-005 — Celery + Redis for async work; the API never performs CV

**Status:** Accepted
**Normative record:** `CONTRACT.md` L5, §7 (*"only seven endpoints initiate async work"*), §7.2.1

---

## Context

Image ingest decodes a file that may be 500 MB. Thumbnailing, overview generation, export rendering
and (when it exists) matching are all seconds-to-minutes of CPU. An HTTP worker that does any of this
is a worker that is not serving requests — and under `uvicorn`'s async model, a **synchronous** CV call
inside an `async def` blocks the **entire event loop of the whole process**, taking `/health` down
alongside it. That failure is then misdiagnosed as "the API is down" when in fact it is one slow tile.

## Decision

**L5 — the API never performs CV.** Any OpenCV/Torch operation heavier than EXIF parsing or one
thumbnail downsample runs in **Celery**. **A `cv2` import reachable from an `async def` route is a
defect.**

**Exactly seven endpoints initiate async work** — 30 (match), 42 (recompute), 43 (suggest), 47
(segment), 54 (batch), 58/59 (export). Every one returns **`202 JobRead`** + `Location` +
`Retry-After: 1`. **Everything else answers immediately.** *That is the shape of a system where CV
never touches a request handler.*

**Tile proxying is IO and is exempt — but must still run off the event loop.** Endpoints 51/52/53 are
declared **`def`, not `async def`**, so Starlette runs them in the threadpool. `ImageryProvider` is
synchronous by design (Celery calls it from a worker pool); a synchronous `httpx` call inside an
`async def` would block the loop for the entire process.

**Endpoint 53's budget is request-scale, not job-scale:** `LE_MAX_STATIC_TILES=16`,
`LE_MAX_STATIC_PIXELS=4194304` (4 MP). At the original 256 tiles / 64 MP, one GET could trigger 256
fetches, a 64-megapixel NumPy stitch, a crop and a PNG encode — **that is not tile proxying, it is
precisely the workload L5 forbids, wearing a GET.** Beyond budget ⇒ `422 STATIC_IMAGE_TOO_LARGE`
pointing at the `202 → GET /jobs/{id}` pattern.

**Services enqueue through a Protocol, not through Celery.** `app.core.queue.JobQueue`
(`submit(spec: JobSpec) -> str`) is implemented by `app.tasks.queue.CeleryJobQueue` and injected at
the composition root. **`app.services` does not import celery** — which is what keeps the service
layer framework-free and unit-testable with mocked repos.

## Rationale

**`202` is not a compromise; it is the honest answer.** The work genuinely has not finished. A
synchronous endpoint that blocks for 60 s is lying about its own nature to every proxy, load balancer
and browser between it and the user.

**The `JobQueue` Protocol resolves a real contradiction.** §2.4 required `match_service` to *"enqueue"*
while the `services-no-fastapi` boundary forbade importing Celery. Without the Protocol, one of the two
had to give (§14 F-05/F-57). The Protocol/impl split is the same pattern as `WindowSource` and
`ImageStore`: **the side that declares the Protocol owns the Protocol.**

**`degraded` is 200, and only three dependencies gate readiness.** If no Celery worker is running the
API can still serve every read — projects, images, annotations, past results, past exports,
downloads. **Returning 503 would take the whole UI offline, including the screens that would tell the
operator the workers are down.** Meanwhile `POST /images/{id}/match` independently returns
`503 WORKER_UNAVAILABLE`, so the failure is reported **precisely at the operation that needs a
worker** rather than by blanket-failing the instance.

**Under `SCOPE.md`, L5 is unchanged and cheaper to honour.** Matching is deferred, so the heaviest
async job is not in this build — but ingest, thumbnailing, overviews, batch and export **are**, and
they are exactly the workloads that would otherwise stall the loop. **Manual GCP creation is a
database write and stays synchronous:** the surveyor clicks and the coordinate is there. A `202` for a
manual GCP would be absurd — there is nothing to compute.

## Consequences

**Positive.**
- The API stays responsive under load; `/health` means what it says.
- Retries, backoff, soft time limits and cancellation are Celery's problem, configured once in
  `tasks/base.py`.
- `LE_CELERY_TASK_ALWAYS_EAGER=true` makes the whole job path testable in-process with no broker.
- The composition root for a job lives **inside the worker** (`app/tasks/matching.py`) — the only place
  a live provider session and a `MatchContext` may coexist, because a `TileWindowSource` holds an
  httpx session and **is not broker-serialisable**.

**Negative, stated honestly.**
- Redis is a hard dependency for anything async, and a second stateful service to run and back up.
- The `202 → poll` pattern is more client work than a blocking call. `useJob` (the adaptive poller)
  exists to absorb it, and `GET /jobs/{id}?wait=…` (0..30 s) offers a long-poll to cut latency.
- Job specs must be **JSON-serialisable**, which constrains what a service may hand a task. That
  constraint is load-bearing and is why `match_service` builds a `MatchJobSpec` dict rather than an
  object graph.
- `LE_CELERY_WORKER_CONCURRENCY=2` is deliberately low — SIFT is CPU-hungry. Operators who raise it
  without measuring will find out why.

## Alternatives considered

**Rejected — do the work in the request with a long timeout.** Blocks the event loop, breaks
`/health`, and pushes the timeout problem onto nginx, the browser and the user's patience.

**Rejected — `BackgroundTasks` / `asyncio.create_task`.** In-process, so it competes with request
serving for the same CPU; **lost on restart**; no retries, no visibility, no cancellation, no queue
depth metric. Fine for sending an email; not for a job whose output is a survey coordinate.

**Rejected — a thread pool inside the API process.** Same process, same memory, same deploy unit; CV
work would still contend with request serving, and OpenCV's own threading would fight the pool.
`cv2.setNumThreads(1)` in workers exists precisely because this contention is real.

**Rejected — SSE for job progress** (§12 C-07). Out of scope for v1; polling with an adaptive interval
is enough and has none of the proxy-buffering failure modes. `VITE_JOB_SSE_ENABLED` is deleted rather
than left as a tempting stub.

## Related

- ADR-008 — PostGIS; the DB the jobs write to.
- ADR-015 — the match job type exists but its endpoint returns 501 in this build.
- `CONTRACT.md` §7.1 (readiness aggregation), §7.2.1 (the `/imagery` threadpool ruling), §6.2 (stages).
