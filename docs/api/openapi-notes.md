# OpenAPI — generation, drift, and the rules that keep the spec honest

**Normative record:** `CONTRACT.md` §8.1 (the casing law), §13.4 rules 5 and 11 · `SCOPE.md` §4 rule 3.

---

## 1. Where the spec lives

| | |
|---|---|
| **Served at** | `/openapi.json` · Swagger UI `/docs` · ReDoc `/redoc` |
| **Toggle** | `LE_ENABLE_DOCS` — **default `true`**. *An internal survey tool benefits more from discoverable docs than it loses to disclosure.* |
| **Title** | `LE_APP_NAME` (default `LandExplorer`) |
| **Not in the spec** | `GET /metrics` — Prometheus, same port, **excluded deliberately** (§12 C-42). It is not part of the public contract. |

## 2. ★ The casing law

> **snake_case at the API boundary, in the generated types, AND in the hand-written domain types.
> There is no case-mapping layer anywhere in the frontend.** (L9, §8.1)

**No alias generator. No `camelCase` on the wire. One name per field, everywhere.**

The temptation is real: `camelCase` is idiomatic TypeScript, and Pydantic's `alias_generator` makes it
a one-line change. It is rejected because it puts a **translation layer** between the Python source of
truth and the TypeScript that consumes it — and a translation layer is a place where `pixel_x` and
`pixelX` can drift apart while both look correct. **The cost is that TS field names look un-idiomatic.
The benefit is that a field has exactly one name from the DB column to the React prop**, and grepping
for it finds every use in both languages.

## 3. ★ The generated client is byte-compared in CI (§13.4 rule 5)

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o frontend/src/api/generated/schema.ts
```

> **`openapi-typescript` output must be BYTE-IDENTICAL to the committed
> `frontend/src/api/generated/schema.ts`. A diff fails the build.**

**`frontend/src/api/generated/schema.ts` is machine-generated and NEVER hand-edited** (IU-24 owns the
path; the generator owns the content).

**Why byte-identical rather than "roughly compatible":** *the API cannot change shape without the
change being visible in a reviewed PR.* A backend field rename that silently reshapes the client is
exactly the drift this rule exists to catch — and it is invisible at review time unless the generated
file moves in the same diff.

**The same rule applies to `ApiErrorCode` and `.env.example`** (§13.4 rule 11): **anything that mirrors
a Python source of truth is generated or it drifts.**

| Artefact | Generated from | Rule |
|---|---|---|
| `frontend/src/api/generated/schema.ts` | `/openapi.json` | §13.4 rule 5 |
| `ApiErrorCode` | `app/core/exceptions.py` | §13.4 rule 11 |
| `.env.example` | `CONTRACT.md` §9 via `scripts/check_env.py --emit-example` | §13.4 rules 7, 11 |

## 4. Rules the spec must satisfy

1. ★ **`ErrorEnvelope` is on EVERY route**, via a shared `COMMON_ERROR_RESPONSES` dict — not on a
   lucky few. **A missing 404 in the spec becomes an untyped `any` in the generated client.**
2. ★ **`operation_id` is unique across the app** — a **startup assertion**, not a lint. Duplicate
   operation ids produce silently-colliding generated client methods.
3. ★ **No duplicate `(method, path)`** — a **startup assertion**. Starlette matches in registration
   order, so **a duplicate route silently shadows in FastAPI** and is otherwise found in production.
4. **Router registration order matters** and `router.py` includes in exactly the §2.4 order — with
   `gcps.router_image` **before** `gcps.router_flat`.
5. **`Page[T]` generates a distinct named component** per `T`, not an inlined anonymous object.
6. **Every schema sets `extra="forbid"`** (an introspection sweep asserts it) — **including `Page`**.
   Every `*Read` sets `from_attributes=True`.
7. **The prefix `/api/v1` appears exactly once**, in `backend/app/api/v1/router.py` (`LE_API_PREFIX`).

## 5. ★ Deferred endpoints in the spec

**Endpoints 30, 43, 47, 48, 49 MUST appear in `openapi.json`** with their full request and response
schemas, **and must document `501` as a response** (`SCOPE.md` §4 rule 3).

**They are not hidden, not `include_in_schema=False`, and not removed.**

> **Why a deferred endpoint stays in the spec.** The generated TypeScript client is how the frontend
> knows the feature *exists and is planned*. Hiding the route would delete `MatchRequest` and
> `MatchResultRead` from `schema.ts`, which would force IU-24/IU-27 to inline `any` for the disabled
> controls' types — **exactly the drift §8.1 exists to prevent** — and would make re-enabling the
> engine a frontend change. `SCOPE.md` §7's requirement is that enabling matching touches **nothing
> outside `ai_engine/`** plus flipping 501→live. **A hidden route makes that false.**

**The `501` response documents `ErrorEnvelope` with `feature: "deferred"`.** See
[`errors.md` §2](errors.md#2--501-not_implemented--the-deferred-feature-contract).

## 6. Regenerating

```bash
# 1. Start the API (no DB needed for the spec itself — see docs/guides/running-locally.md)
uvicorn app.main:app --port 8000

# 2. Regenerate
npx openapi-typescript http://localhost:8000/openapi.json -o frontend/src/api/generated/schema.ts

# 3. Commit the result IN THE SAME PR as the backend change.
#    CI byte-compares. A drifted file fails the build.
```

**If CI reports drift and you did not intend an API change, you made one.** That is the rule working.
