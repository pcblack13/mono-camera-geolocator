# ADR-008 — PostgreSQL + PostGIS with `geography(*, 4326)`; PostGIS is a real dependency

**Status:** Accepted
**Normative record:** `CONTRACT.md` §5 (models), §5.6 (`gcps`)

---

## Context

The deliverable is a table of geographic coordinates plus the questions a surveyor asks of them:
*which GCPs are in this project's AOI?*, *how far did this point move when it was adjusted?*, *give me
everything within 500 m of here*. Those are spatial queries. Either the database answers them or the
application does — in Python, over a full table scan, with hand-rolled geodesy.

## Decision

**PostgreSQL + PostGIS. `geography(Point, 4326)` for anything on the Earth.** PostGIS is a **real
dependency**, not an optional accelerant: migration `0001` runs `CREATE EXTENSION postgis` and the
readiness probe checks `postgis_version()`, so an instance without it is **`not_ready` → 503** rather
than mysteriously wrong.

**`gcps.geom` is the canonical truth.** `lat`/`lon` are **serialised from `geom`** on the wire — never
a raw WKB/GeoJSON blob. Flat floats are what a CSV exporter, a Leaflet marker and a surveyor all want.

**`geography`, not `geometry`, for Earth coordinates.** `ST_Distance` on `geography` returns **real
metres on the ellipsoid**. On `geometry(4326)` it returns *degrees* — a number that is neither a
distance nor an error, just a lie with units nobody wrote down. `adjustment_offset_m` is
`ST_Distance(original_geom, geom)` and must be metres a surveyor can act on.

**Every spatial column declares `spatial_index=False`** in the model; indexes are created explicitly in
the migrations. GeoAlchemy2's implicit index creation and Alembic autogenerate **do not compose** —
autogenerate mishandles PostGIS types and index changes, so every migration is hand-reviewed and
autogenerate is a **draft** (ADR-011).

**Storage of derived representations is deliberate, and the invariant is enforced in one transaction.**
`gcps` stores both `geom` and `satellite_pixel_x/y`; `PATCH /gcps/{id}` **derives the one the client
did not send** rather than updating only what it received. They are two views of one fact: if a PATCH
updated only one, **the map would show the marker in one place and the CSV would export another, with
no indication which is right.** Deriving is not redundant work; it is the invariant.

**`match_results.tile_bounds` (4326) is canonical; `tile_bounds_3857` is denormalised** for the MVT and
overlap queries, written by the **same transaction from the same source arithmetic** — not a
re-projection of the 4326 column, so no round-trip error accumulates. **If they ever disagree,
`tile_bounds` wins.**

## Rationale

**The alternative to PostGIS is writing PostGIS, badly.** Geodesic distance, `ST_Within` against an
AOI polygon, GIST indexes, antimeridian handling, valid-geometry checks — all of it exists, is
correct, and is thirty years old. Reimplementing any of it in the service layer is how the ~108 m class
of bug (ADR-004) gets a new home.

**Making it a hard dependency is the honest call.** A codebase that *optionally* has spatial queries
grows two paths, one of which is exercised only in the deployment nobody tests. The readiness probe
checks `postgis_version()` so the failure is **loud and diagnosed**, not a subtly wrong answer.

**The CHECK constraints are the schema refusing to store a lie.** `ck_gcps_accuracy_total_ge_parts`
(`total >= greatest(relative, georef)`) catches a unit or sign slip in `combine_accuracy` **at write
time** — a quadrature can never be smaller than either leg. `ck_gcps_elevation_source_consistent`
(`(elevation_m IS NULL) = (elevation_source IS NULL)`) means **the source may never name a producer
that did not run**. `ck_gcps_adjustment_complete` means an adjusted GCP always has its `adjusted_at`
and its `original_geom`. These are not belt-and-braces; they are the last line of defence for a number
someone may file against.

**`original_geom` is written once and never again — it is the algorithm's answer, and there is only
one of those.**

## Consequences

**Positive.**
- Spatial queries are a `SELECT`. `gcps` repository owns them; the service layer never does geodesy.
- Real metres, from the database, on the ellipsoid.
- The database enforces what code might forget: at most one selected result per job
  (`uq_match_results_job_selected`), accuracy quadrature sanity, adjustment completeness.

**Negative, stated honestly.**
- PostGIS is an operational dependency: a specific extension, in a specific image, with version
  coupling to the `geoalchemy2` layer. `infra/postgres/init/01-postgis.sql` and the backend Dockerfile
  both carry it, and `/health/ready` tells you when it is missing.
- `geography` operations are slower than `geometry` and support fewer functions. Correct metres beat
  fast degrees for this product; where a planar op is genuinely needed the 3857 column is explicit and
  denormalised rather than derived on read.
- Alembic autogenerate cannot be trusted here. That is a real, permanent tax on schema changes, paid
  in review time.
- **Under `SCOPE.md` the deferred tables (`match_jobs`, `match_results`, `camera_poses`,
  `confidence_heatmaps`, `semantic_features`) are created and hold no rows.** Accepted deliberately —
  schema churn later is far more expensive than unused tables now.

## ★ Open defect this ADR must not paper over

`gcps.match_result_id` is **`NOT NULL`** with an FK `RESTRICT` to `match_results`, and matching is
deferred — **so no `match_results` row can exist, and therefore no GCP can be inserted at all.** As
specified, manual mode is unimplementable. The resolution (nullable `match_result_id`, a `source`
column, a `POST /images/{id}/gcps` endpoint) is recorded in
[`TRACEABILITY.md` §4.1](../TRACEABILITY.md#41--schema-and-api-additions-that-manual-mode-requires--escalated)
as **S-1/S-2/S-3, release-blocking**. It is named here because this is the ADR a reader consults
before touching the schema.

## Alternatives considered

**Rejected — `geometry(Point, 4326)`.** `ST_Distance` returns degrees. Every distance in the product
would be wrong by a latitude-dependent factor, and nothing would crash.

**Rejected — store lat/lon as two floats, no PostGIS.** Then every spatial question is a full scan and
a hand-rolled haversine, the AOI check is Python, and the ~108 m bug gets a new home. Cheaper on day
one; unpayable by month three.

**Rejected — SQLite + SpatiaLite for dev, PostGIS for prod.** Two dialects, two behaviours, two sets of
bugs — and the dialect that differs is precisely the spatial one. `@pytest.mark.db` against real
PostGIS, skipped when `LE_DATABASE_URL` is unset, gives a green dev suite without a second dialect.

**Rejected — a document store with GeoJSON.** No constraints, no transactions across the invariants
above, no `ST_Distance`. The schema *is* the product's integrity story.

## Related

- ADR-004 — the CRS boundary; `gis` is the only module that projects.
- ADR-011 (`00-overview.md` §7) — migrations are explicit; auto-migrate is dev-only.
- `CONTRACT.md` §5.6 (`gcps` — *the deliverable*), §7.1 (readiness).
