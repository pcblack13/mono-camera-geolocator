/**
 * ┌───────────────────────────────────────────────────────────────────────────┐
 * │  THIS FILE IS MACHINE-GENERATED.  DO NOT EDIT.                            │
 * │                                                                           │
 * │  Generator:  openapi-typescript                                           │
 * │  Source:     the running API's `/openapi.json` (OpenAPI 3.1)              │
 * │  Command:    make openapi                                                 │
 * │                (infra Makefile target, IU-30 — verbatim:)                 │
 * │                  docker compose exec -T api python -c \                   │
 * │                    'import json, app.main as m; \                         │
 * │                     print(json.dumps(m.create_app().openapi()))' \        │
 * │                    > /tmp/openapi.json                                    │
 * │                  cd frontend && pnpm exec openapi-typescript \            │
 * │                    /tmp/openapi.json -o src/api/generated/schema.ts       │
 * │                (package.json also exposes `pnpm gen:api` against a         │
 * │                 locally-running API on :8000)                             │
 * │                                                                           │
 * │  CI fails on drift (§2.5, §8.1). Regenerate; never hand-edit.             │
 * └───────────────────────────────────────────────────────────────────────────┘
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ★★ THIS FILE HAS NEVER BEEN GENERATED. IT IS A PLACEHOLDER, AND IT SAYS SO.
 *
 *    Generating it requires two things that do not exist yet:
 *      1. **`openapi-typescript`** — the frontend's dependencies are not installed,
 *         and there is no network to install them from.
 *      2. **A running API** to serve `/openapi.json` — `fastapi` and `pydantic` are
 *         not installed, Docker is not installed, and IU-21 is writing `main.py` in
 *         parallel with this file.
 *
 *    So the honest options were: fabricate a hand-written file that CLAIMS to be
 *    generated, or ship a placeholder that is explicit about being empty. **The first
 *    is a lie that CI cannot catch** — `make openapi` would overwrite it, the diff
 *    would be enormous, and until someone ran it every reader would believe these
 *    types had been checked against the server. A generated file's entire value is
 *    the guarantee that it MATCHES THE SERVER; a hand-written one wearing the header
 *    has negative value, because it carries the guarantee without the property.
 *
 *    Hence: **no fabricated shapes below.** `paths`, `components`, `operations` and
 *    `webhooks` are declared with the names and structure `openapi-typescript` emits,
 *    and are EMPTY. Nothing imports them yet (see below), so nothing breaks; the first
 *    `make openapi` replaces this file wholesale and the emptiness is the loudest
 *    possible signal that it has not been run.
 *
 * ★★ NOTHING IN `src/api/**` OR `src/types/**` IMPORTS THIS FILE TODAY, and that is
 *    by design, not by omission.
 *
 *    §8.1 sets out the intended end state: *"The hand-written layer in `src/types/`
 *    re-exports the generated shapes with branding applied, adding zero renames."*
 *    IU-23's `src/types/**` is a complete, field-for-field mirror of §6 written
 *    directly from the contract — which is what the contract asked for, and is the
 *    only thing that was possible before an API existed. The two layers therefore
 *    agree by construction TODAY, and are kept honest by review rather than by the
 *    generator.
 *
 *    ★ THE OPEN ITEM, stated so it is not lost: once the API runs, someone must
 *      reconcile `src/types/**` against this file and wire the re-export seam §8.1
 *      describes. Until then the generator gate is **not** protecting the frontend
 *      from drift — the strongest claim this build can make is "hand-mirrored from
 *      CONTRACT.md §6". That is a real gap, it is IU-24's to flag and not IU-24's to
 *      close (it needs a server), and pretending otherwise by pre-writing plausible
 *      shapes here would only make it invisible.
 *
 *    ★ Two other generated artefacts share this seam and this hazard:
 *      `ApiErrorCode` in `types/common.ts` (from `scripts/gen_error_codes.py`) and
 *      `.env.example` (from `scripts/check_env.py --emit-example`). Both are
 *      hand-written today for the same reason and CI-gated for the same reason.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ★ CASING (§8.1 / L9): when generated, every property here is snake_case, straight
 *   from the Pydantic field names — there is no alias generator server-side and no
 *   case-mapping layer client-side. `.eslintrc.cjs` disables `camelcase` for
 *   `src/api/**` and additionally ignores `src/api/generated/**` entirely.
 */

/* eslint-disable @typescript-eslint/no-empty-interface */

/**
 * The API's paths. Populated by `make openapi` with one entry per §7 endpoint
 * (63 + endpoint 64, all under `/api/v1`, plus the unversioned `/metrics`, which is
 * excluded from the OpenAPI document — §12 C-42).
 */
export interface paths {}

/** Reusable schema objects — the §6 Pydantic models. Populated by `make openapi`. */
export interface components {
  schemas: Record<string, never>;
  responses: Record<string, never>;
  parameters: Record<string, never>;
  requestBodies: Record<string, never>;
  headers: Record<string, never>;
  pathItems: Record<string, never>;
}

/**
 * Per-operation types, keyed by `operation_id`.
 *
 * ★ §6.1 fixes `operation_id` as `{tag}_{action}` — so the generated TS reads
 *   `images_upload`, not `uploadImagesApiV1ImagesPost`. Asserted unique at startup.
 */
export interface operations {}

/** OpenAPI 3.1 webhooks. LandExplorer defines none. */
export interface webhooks {}

/** `$defs` emitted alongside the document. */
export type $defs = Record<string, never>;
