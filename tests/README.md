# `tests/` — cross-package tests (IU-31)

The only suite that may see more than one package at once (CONTRACT.md §2.8). Everything
here asserts a property that lives **between** packages and that no single unit can check
from the inside. Per-unit tests live beside their unit (`ai_engine/…/tests/`,
`gis/…/tests/`, `backend/app/tests/`, `frontend/src/__tests__/`).

## Layout

```
tests/
├── conftest.py                     # shared fixtures; auto-skips @pytest.mark.db; blocks the network
├── contract/                       # ABC conformance + the structural cross-package invariants
│   ├── _astsupport.py              #   ast helpers — parse, don't import (deps aren't installed here)
│   ├── test_enum_parity.py         #   ★ the three enum legs agree, via §5.3 PARITY_MAP
│   ├── test_boundaries.py          #   ★ L3/L4 by §10.5's normative greps, comment-stripped
│   ├── test_deferred_surface.py    #   ★ the SCOPE.md deferred seam is honest end to end
│   └── test_provider_abc.py        #   ★ every provider conforms; PROVIDER_NAMES == the PG enum
├── e2e/
│   ├── test_manual_gcp_offline.py  #   ★ RUNS TODAY: photo → EXIF → imagery → GCP → export, offline
│   └── test_api_flow.py            #   the same over HTTP; skips until IU-21 + a DB exist
├── integration/
│   └── test_migrations_and_schema.py   #   Tier-2 migration test, @pytest.mark.db
└── fixtures/                       #   field_photo.jpg (+ no_gps, + rotated). See fixtures/README below.
```

## The three tiers, and what each needs

| Tier | Needs | On this machine (§0.1) |
|---|---|---|
| `contract/` | the source files only | ★ **runs today** — parses with `ast`, imports only `gis` + `ai_engine` |
| `e2e/` | `gis` (offline half) · backend + DB (API half) | offline half **runs today**; API half skips |
| `integration/` | live PostgreSQL + PostGIS | `@pytest.mark.db` → auto-skips unless `LE_DATABASE_URL` |

★ **Green by default.** `@pytest.mark.db` is auto-skipped when `LE_DATABASE_URL` is unset
(§13.1 IU-31), and the API e2e guards its imports with `pytest.importorskip`. On a bare dev
box `pytest tests/` is green, not red-with-excuses — a suite that is red by default trains
everyone to ignore red.

## Why `ast`, not `import`

The two highest-value tests here — enum parity and the L3/L4 boundaries — parse Python
source with `ast` instead of importing it. That is not a workaround: `backend.app.models.
enums` needs sqlalchemy and `backend.app.schemas.enums` needs pydantic, **neither installed
on this machine** (§0.1). An import-based parity test could not run here at all. The `ast`
version runs on a bare interpreter, today, and catches three-file enum drift on the first
commit rather than an hour into CI. See `contract/_astsupport.py`.

## Running

```bash
pytest tests/                       # everything runnable here (DB tiers auto-skip)
pytest tests/contract/              # the structural invariants — the fastest signal
LE_DATABASE_URL=postgresql+psycopg://… pytest tests/ -m db   # add the DB tiers
```

★ `tests/` deliberately has **no `__init__.py`** in any subdirectory. That is what lets
pytest's default *prepend* import mode put each test directory on `sys.path`, so
`contract/` tests can `from _astsupport import …`. Test-file basenames are unique across the
tree (prepend mode requires it). Do not add `__init__.py` files.

## Two findings recorded in-suite

Both are places where following the contract literally is wrong; each test documents the
ruling so the next reader does not "fix" the code back to the bug.

1. **The London slippy golden.** §13.3 prints `TileRef(12, 2047, 1362)`; the correct x is
   **2046** by the contract's own formula (`fixtures/README.md`, `test_enum_parity` is
   unrelated — see `gis/…/fixtures/_generate.py`). IU-09 caught it independently; the two
   agree.
2. **`GcpSource` disposition.** SCOPE.md §5 added a `source` field after §5.3's `PARITY_MAP`
   was written. IU-16 shipped it as "out of PARITY_MAP scope"; IU-17 shipped a docstring
   instructing IU-30 to `CREATE TYPE gcp_source`. Values agree, so nothing is broken — but
   the instructions conflict. `test_enum_parity.py::test_gcp_source_disposition_conflict_is_
   recorded_not_silent` pins the state both units actually shipped.
