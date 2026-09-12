# ADR-001 — `ai_engine` and `gis` are separate installable packages, not backend subpackages

**Status:** Accepted
**Normative record:** `CONTRACT.md` §2.2, §2.3, §10 · enforced by `.importlinter` in CI

---

## Context

The obvious layout is `backend/app/services/matching.py` — one Django-shaped tree, one install, done.

The verified environment (`CONTRACT.md` §0.1) makes that layout hostile:

| Installed on this machine | **Not installed** |
|---|---|
| `cv2` 4.13, `numpy` 2.4, `scipy` 1.17, `torch` 2.11+cu130, `osgeo`/GDAL 3.8, PIL | `fastapi`, `pydantic`, `sqlalchemy`, `alembic`, `celery`, `redis`, `rasterio`, `geopandas`, `shapely`, `pyproj`, `reportlab`, `httpx`, `pytest` |

The CV stack is present. The web stack is absent. Under a single tree, **every CV test imports
`fastapi` transitively and dies at collection** — on the only machine we can test on.

## Decision

Three Python distributions in one monorepo:

| Distribution | Path | May depend on |
|---|---|---|
| `landexplorer-ai-engine` | `ai_engine/` | numpy, cv2, scipy · `[deep]` torch |
| `landexplorer-gis` | `gis/` | numpy, PIL, httpx · `[rasterio]` `[redis]` `[exports]` `[pyproj]` |
| `landexplorer-backend` | `backend/` | fastapi, sqlalchemy, pydantic, celery + path deps on the two above |

Neither `ai_engine` nor `gis` may import a web or DB framework. Enforced by import-linter via
`scripts/verify_boundaries.sh` — **a build failure, not a code-review opinion.**

`import ai_engine` and `import gis` are **clean today with zero installs**.

## Consequences

**Positive.**
- `cd ai_engine && pytest` runs on this machine after one `--no-deps` editable install.
- A DB migration cannot break RANSAC. The blast radius of a web-framework upgrade stops at `backend/`.
- The CV core is reusable from a notebook, a CLI, or QGIS — with no FastAPI in the process.
- The boundary makes L3/L4 (`ai_engine` knows no CRS; `gis` knows no descriptor) **checkable** rather
  than aspirational.

**Negative, stated honestly.**
- Three `pyproject.toml` files, editable installs in dev, path dependencies in the Docker build.
  A few hours of setup, once — versus a permanently untestable core.
- `venv` **hides system site-packages**, and `osgeo` cannot be pip-installed at all. Therefore
  `scripts/bootstrap_dev.sh` **must** use `python -m venv --system-site-packages .venv` and
  `pip install -e … --no-deps`. **The one script whose job is making the repo runnable here is the one
  most able to break it** (§0.1). See [`docs/guides/running-locally.md`](../../guides/running-locally.md).
- One sanctioned cross-package import exists: `gis.candidates` may import **`ai_engine.types` only**.
  It is permitted because `ai_engine.types` is provably cheap — `test_types_import_cheap` asserts that
  on a fresh interpreter, `import ai_engine.types` leaves `cv2`, `torch` **and `ai_engine.models`**
  absent from `sys.modules`. **If that property ever breaks, the import must go, not the test.**

## Alternatives considered

**Rejected — everything under `backend/app/`.** Every CV test imports `fastapi` transitively and fails
at collection **today**. Cycles between services and CV code appear within weeks; they always do.

**Rejected — a separate git repo per package.** Cross-cutting changes need coordinated PRs and version
pins before the interfaces have stabilised. A monorepo with package boundaries gives the isolation
without the release choreography. Revisit if `ai_engine` gains external consumers.

**Rejected — a microservice per concern (a gRPC CV service).** Real isolation, but it adds
serialisation of multi-MB rasters, a second deploy unit, and network failure modes to a system whose
actual concurrency problem is **already solved by Celery**. Nothing is gained that a process boundary
does not already give.

**Rejected — a fourth `contracts` package holding the shared value types.** Ceremony that would be
imported by everything and owned by no one. The `types` subpackage of the side that *declares* the
Protocol owns it instead.

## Related

- ADR-004 (the pixel/CRS boundary) — the rule this packaging makes enforceable.
- `CONTRACT.md` §10 (dependency rules), §0.1 (the environment facts).
