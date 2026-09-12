# ADR-013 — Server state in React Query, UI state in Zustand, and never both

**Status:** Accepted
**Normative record:** `CONTRACT.md` L7, §8.4

---

## Context

The mandated stack includes both React Query and Zustand. Overlapping them is the classic way to get
**two sources of truth and a stale GCP on screen** — and a stale GCP on screen is a coordinate a
surveyor may write down.

The sharp edge is specific and unavoidable: **landmarks and GCPs are edited locally at 60 fps and
persisted server-side.** A Konva drag produces dozens of intermediate positions per second, none of
which are server state; the drop produces exactly one fact that is.

## Decision

**One rule, no exceptions:**

> **If it came from the API, it lives in React Query. If it exists only in the browser, it lives in
> Zustand.** (L7 — *the frontend store holds no server data*.)

| Data | Owner |
|---|---|
| Projects, images, annotations, jobs, results, GCPs, exports, provider list, capabilities | **React Query** |
| Tool mode, selected landmark id, canvas zoom/pan, brightness/contrast, undo stack, basemap choice, overlay opacity, compare-pane sync, drawer/toast/theme, upload queue | **Zustand** |

**The drag resolution.** A Konva drag updates a **transient Zustand draft**. On drop, a React Query
mutation `PUT`s the bulk upsert with an optimistic update and rollback on error, **and the server
response is authoritative**. The draft is cleared on settle.

**Query keys are centralised** in `api/queryKeys.ts` — one factory, no stringly-typed keys.
**Components never call `api/` directly**; they go through `api/hooks/`, which is what makes
MSW-based tests possible **with no backend running**.

**The uncommitted correspondence is browser state, and that is load-bearing.** `SCOPE.md` §5:
*"Uncommitted correspondences must never appear in the GCP table or an export."* An open correspondence
— photo point marked, map click pending — is **Zustand**. It becomes a GCP, and therefore React Query
data, **only on commit.** The rule and the requirement are the same rule.

## Rationale

**Cache invalidation is React Query's problem, not ours.** Staleness, refetching, retry, polling,
dedupe, and the `202 → poll → invalidate` job flow are the library's core competence. Reimplementing
them in a store is the wheel React Query already turns.

**Canvas zoom/pan in a server cache is a category error**, and the re-render behaviour is wrong for
60 fps dragging. Zustand's transient updates exist precisely for this.

**The rule is testable, not just stated.** MSW mocks every endpoint and no backend runs; if server data
had leaked into Zustand, the mocks would not control what the component renders and the tests would
quietly stop meaning anything.

## Consequences

**Positive.**
- One source of truth per datum, enforceable by reading an import.
- Optimistic updates with rollback are a mutation option, not a bespoke reducer.
- `useJob`'s adaptive poller stops on **every** terminal status (table-driven test), and a
  `useMatch` success invalidates the GCP and job keys — invalidation is declarative.
- The frontend test suite runs with **no backend, no network**.

**Negative, stated honestly.**
- Two state libraries is two mental models for a new contributor, and the boundary case (a landmark
  being dragged) is exactly where a newcomer will guess wrong. The draft-then-mutate pattern must be
  in the contributing guide, not folklore.
- Optimistic updates can flash: the draft clears on settle, and a slow server means a visible snap-back
  on error. Correct, and occasionally ugly.
- The rule forbids the convenient thing — caching a GCP list in Zustand "just for the table" — which
  will be proposed at least once. It is the whole ADR; the answer is no.

## Alternatives considered

**Rejected — Redux Toolkit + RTK Query.** Capable, and not in the mandated stack. Heavier for a
form-light, canvas-heavy app.

**Rejected — Zustand for everything.** Hand-rolled caching, refetching, staleness, polling and
invalidation. That is React Query, written worse, by us, under deadline.

**Rejected — React Query for everything, no Zustand.** Canvas zoom/pan and an undo stack in a server
cache is a category error, and the re-render behaviour cannot hold 60 fps.

**Rejected — "server data in Zustand, synced by an effect".** The version of this bug that ships: an
effect copies query data into a store, the store goes stale, and the GCP table shows a coordinate the
server no longer holds. This is the failure L7 exists to make unrepresentable.

## Related

- `CONTRACT.md` L7, §8.4 (query client defaults), §8.6 (the two-stage transform), §13.1 IU-23..28.
- [ADR-014](ADR-014-landmarks-are-user-marked.md) — why the draft is a *human assertion* and the server
  response is authoritative.
