# Contributing

**Read [`SCOPE.md`](../architecture/SCOPE.md) first — 138 lines, and it OVERRIDES `CONTRACT.md`.**
Then `CONTRACT.md` §0–§3, then the section for the module you are touching. **Do not read all 7339
lines; grep.**

---

## 0. The five things that get a PR rejected without discussion

1. **Violating one of the twelve laws** (`CONTRACT.md` §1). See the table in
   [architecture-tour.md §2](architecture-tour.md#2-the-twelve-laws-in-one-table).
2. **A deferred stub that does anything other than `raise NotImplementedDeferred`** — ★ never `pass`,
   never a silent `None`, **never a fabricated coordinate or confidence** (`SCOPE.md` §4 rule 2).
3. **A requirement with no test** (§13.4 rule 10). *A requirement with no test does not exist.*
4. **A new env var without a default** (L10) or missing from §9 + `.env.example` (§13.4 rule 7).
5. **Claiming a compose file is verified** (§13.4 rule 9). ★ **Docker is not installed. The first CI
   run with Docker is the gate. No task may claim otherwise.**

## 1. Setup

```bash
bash scripts/bootstrap_dev.sh     # ★ EXACT — see docs/guides/running-locally.md
```

> ★ **Never create a venv without `--system-site-packages`.** `cv2`, `numpy`, `scipy`, `torch` and
> `osgeo` are system packages; a plain venv **hides all five**, and **`osgeo` cannot be pip-installed
> back.** This is the single most common way to break your own environment here.

## 2. Definition of done (§13.4)

| # | Gate |
|---|---|
| 1 | Unit tests pass **without network, GPU, model weights, Docker, or a DB** (DB tests are `@pytest.mark.db`) |
| 2 | `scripts/verify_boundaries.sh` passes — import-linter **and** the §10.5 greps |
| 3 | `mypy --strict` on `ai_engine` and `gis`; `mypy` on `backend` |
| 4 | `ruff` + `black` clean; `eslint` + `prettier` clean; `tsc --noEmit` clean |
| 5 | ★ `openapi-typescript` output **byte-identical** to the committed `schema.ts` — **a diff fails the build** |
| 6 | ★ Public functions carry type hints and docstrings **stating units and coordinate frames** (`px` vs `m` vs `deg`; image frame vs window frame vs EPSG:4326) |
| 7 | New env vars are in `.env.example` **and** §9, **and have a default** |
| 8 | ★ New backends/providers/exporters/elevation providers/suggesters are **registered and appear in the parametrised contract test.** *A component that is not in the contract test does not exist.* |
| 9 | ★ **Compose files are NOT marked verified.** |
| 10 | ★ **Every row of [`TRACEABILITY.md`](../architecture/TRACEABILITY.md) names a test.** |
| 11 | ★ `ApiErrorCode` and `.env.example` are **generated and byte-compared** — as `schema.ts` is |

> **Rules 8 and 10 are the same rule at two scales:** *if it is not in a parametrised test, it does not
> exist* (components) and *if a requirement names no test, it does not exist* (deliverables). **Rule 10
> exists because rule 8 was not enough:** it is what would have caught `elevation` shipping as a
> fully-plumbed enum with **no producer**, and `suggest_landmarks` shipping as four endpoints with **no
> algorithm** — both invisible to a definition-of-done that was per-module and per-unit but **never
> per-requirement** (§14 F-101).

## 3. Rule 6 in practice — the docstring rule

Most bugs in this system will be a **frame confusion**. Naming is the cheapest defence.

```python
def pixel_to_lonlat(gt: GeoTransform, crs: str, u: float, v: float) -> LonLat:
    """Convert a WINDOW-frame pixel to geographic coordinates.

    Args:
        gt:  the window's affine geotransform (window px -> `crs` units).
        crs: EPSG authority string of `gt`'s target. ★ NOT assumed to be 3857 —
             local_orthophoto produces UTM geotransforms.
        u:   window-frame column, px. ★ NOT image-frame, NOT display-frame.
        v:   window-frame row, px, y-down.

    Returns:
        LonLat in EPSG:4326, degrees. ★ (lon, lat) order — always_xy.
    """
```

**Say the frame. Say the unit. Say the order.** `u: float` alone is how the 108 m bug ships.

## 4. File ownership — ★ this repo is built by parallel agents

**`CONTRACT.md` §3 is a disjoint ownership map. No two units touch the same file.**

> **If you need something from another unit, code to the contract's declared interface and TRUST that
> it will exist.** Touching a file you do not own corrupts someone's work in flight.

If the contract genuinely lacks a file you need: **add it in the spirit of the tree and flag it
prominently in your PR description.** Do not quietly annex it.

## 5. Testing

```bash
cd ai_engine && pytest      # green: no env, no network, no GPU, no weights
cd gis       && pytest      # green: httpx/redis/geopandas/fiona/reportlab/ezdxf ALL absent
cd backend   && pytest      # DB tests skip automatically when LE_DATABASE_URL is unset
cd frontend  && pnpm test   # MSW mocks every endpoint — NO backend runs
```

**No test may require network, a GPU, model weights, Docker, or a database** — except the explicitly
marked tiers (`@pytest.mark.db`).

★ **`pytest` is not a runtime dep.** `pip install -e ./ai_engine[dev] --no-deps` first.

★ **The call-time binding rule is what makes `cd gis && pytest` possible** (§11.3):

> **Any module whose dependency is not in its package's BASE install binds that dependency INSIDE the
> function that uses it, never at module scope.** `is_available()` / `is_configured()` /
> `capabilities()` / `probe()` **must be importable and callable with the dependency absent.**

*v1.0 mandated this for exactly one module and then violated it six times — which made `cd gis &&
pytest` die at **collection**, before a single test ran.*

## 6. Working on deferred code

**The seam is real, not decorative.** If you touch `ai_engine/`:

- **Callers depend on the ABC, never on a concrete class.**
- **Bodies raise `NotImplementedDeferred`** with the module name + a pointer to `SCOPE.md`.
- **Registry entries stay.** The DB schema stays. The fixtures stay.
- ★ **The acceptance test for every line you write:** *implementing the engine must require **zero
  changes outside `ai_engine/`**, plus flipping the deferred endpoints from 501 to live and enabling
  the UI controls.* **If your implementation makes that untrue, your implementation is wrong**
  (`SCOPE.md` §7).

**Do not "helpfully" implement a deferred component.** It is not a TODO left by an oversight; it is
[ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md), and shipping a
confidently-wrong coordinate is this system's worst failure mode.

## 7. Adding things

| Adding a… | Read | Do not forget |
|---|---|---|
| **Imagery provider** | [adding-a-provider.md](adding-a-provider.md) | ★ [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) **first.** Register explicitly; add to the parametrised contract test; `__init__` must **never** raise on a missing key. |
| **CV backend** | [adding-a-backend.md](adding-a-backend.md) | A registry entry, a **terminating** fallback, no module-scope torch (L8). |
| **Export writer** | §4.21 | `is_available()` must **never raise** with the dep absent; **call-time binding**; add to the parametrised writer test. |
| **Endpoint** | §7 | Unique `operation_id`; `ErrorEnvelope` on every route; regenerate `schema.ts`. |
| **Env var** | §9 | A **working default** (L10); §9 + `.env.example`; CI byte-compares. |
| **Client requirement** | ★ [`TRACEABILITY.md`](../architecture/TRACEABILITY.md) | **A row, naming a test.** Rule 10. |

## 8. ADRs

**Supersede rather than edit.** A reversed decision keeps its text and gains a banner pointing at the
new ADR. **The record of what we believed and why is the point; a rewritten ADR is a lost lesson.**
See [`adr/README.md`](../architecture/adr/README.md).

## 9. Commit and PR

- Conventional-ish subject: `feat(gis): …`, `fix(backend): …`, `docs(adr): …`
- **The PR description states:** which unit you own · which laws your change touches · **anything you
  added that is not in `CONTRACT.md` §2's tree** · what you could and could not verify.
- ★ **Be honest about verification.** *"Authored to spec; not executed — Docker/network absent"* is a
  perfectly good PR note. **A false "verified" is worse than an absent one**, and this codebase's
  entire value proposition is that it does not lie about what it knows.

## 10. The house style, in one line

> **Refuse rather than answer wrongly** (L12) — in the code, in the API, in the docs, and in the PR
> description.
