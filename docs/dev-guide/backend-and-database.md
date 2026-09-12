# Backend & database

Everything here assumes:

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator
```

---

## There are TWO databases. Know which one you are in.

This trips people up constantly, because both are named `landexplorer`, with a
role called `landexplorer`, and the same schema.

| Mode | How it starts | Host / port | Data lives in |
|---|---|---|---|
| **Dev / source** | your own system PostgreSQL | `localhost:5432` | your system cluster |
| **Managed / bundled** | the app starts it | `127.0.0.1:15432` | `~/.local/share/MonoCameraGeolocator/pgdata` |

You can tell them apart from the boot log, which prints the URL it connected to:

```
"url": "postgresql+psycopg://landexplorer:***@localhost:5432/landexplorer"     ← dev
"url": "postgresql+psycopg://landexplorer@127.0.0.1:15432/landexplorer"        ← managed
```

**The bundled cluster only exists while the app is running.** It is started by
`desktop/boot.js` and shut down with the app. If `psql` on 15432 says
_"connection refused"_, that is not a broken database — the app is closed.
Launch it, then connect.

---

## Connect to the bundled database

Start the app (or `npm run smoke:managed` in `desktop/`, which boots the stack
and holds it up), then:

```bash
psql -h 127.0.0.1 -p 15432 -U landexplorer -d landexplorer
```

No password — the bundled cluster uses `trust` auth on loopback only.

Connect to the **dev** database instead:

```bash
psql -h localhost -p 5432 -U landexplorer -d landexplorer
```

---

## Useful psql session settings

```sql
\x on          -- expanded display: one column per line. Essential for wide tables.
\x off         -- back to normal
\x auto        -- expand ONLY when a row is too wide to fit. Usually the best setting.
\timing on     -- show how long each query took
\pset pager off -- stop results opening in a scroller you have to quit out of
\q             -- quit
```

> ### ★ THE BACKSLASH RULE
>
> **Anything starting with `\` goes on its own line, alone. Never mix a
> backslash command and SQL in one paste.**
>
> `\x on` and friends are psql meta-commands, not SQL. They consume the rest of
> the pasted line — and in practice the rest of the paste — as their arguments.
> Paste `\x on` together with a query and the query never runs: no output, no
> error, just a fresh prompt, which looks exactly like a query that returned
> nothing.
>
> Send `\x on`, press Enter, wait for *"Expanded display is on"*, **then** paste
> the SQL.
>
> `\x auto` set once at the start avoids the whole problem for the rest of the
> session.

---

## Explore the schema

Do this instead of guessing column names — the schema changes between releases.

```sql
\dt                    -- list all tables
\d gcps                -- full column list, types, indexes, FKs for one table
\d+ gcps               -- same plus storage/description
\di                    -- list indexes
```

---

## Census: how much data is in here?

```sql
SELECT
  (SELECT count(*) FROM projects) AS projects,
  (SELECT count(*) FROM images)   AS images,
  (SELECT count(*) FROM gcps)     AS gcps;
```

A quick sanity check after a migration or a restore — but **these are raw row
counts and they will not match the app.** See the next section.

---

## ★ Raw counts do NOT match what the Dashboard shows

`projects` and `images` are **soft-deleted**: the row stays, `deleted_at` is
set. Every API read filters on it. `gcps` are **hard**-deleted, but the overview
excludes any GCP whose image or project is soft-deleted:

```python
# app/db/repositories/gcps.py — list_overview()
.where(Image.deleted_at.is_(None), Project.deleted_at.is_(None))

# app/db/repositories/projects.py — list_projects()
stmt.where(Project.deleted_at.is_(None))

# app/db/repositories/projects.py — _image_count_subquery()
.where(Image.project_id == Project.id, Image.deleted_at.is_(None))
```

So a plain `count(*)` counts the graveyard too. To reproduce the Dashboard's
numbers exactly, ask the question the API asks:

```sql
SELECT
  (SELECT count(*) FROM projects WHERE deleted_at IS NULL)              AS projects,
  (SELECT count(*) FROM images i
     JOIN projects p ON p.id = i.project_id
    WHERE i.deleted_at IS NULL AND p.deleted_at IS NULL)                AS photographs,
  (SELECT count(*) FROM gcps g
     JOIN images   i ON i.id = g.image_id
     JOIN projects p ON p.id = i.project_id
    WHERE i.deleted_at IS NULL AND p.deleted_at IS NULL)                AS gcps;
```

See exactly what is hidden:

```sql
SELECT id, name, deleted_at FROM projects WHERE deleted_at IS NOT NULL;
SELECT id, filename, deleted_at FROM images WHERE deleted_at IS NOT NULL;

-- GCPs stranded behind a soft-deleted parent
SELECT count(*) FROM gcps g
  JOIN images   i ON i.id = g.image_id
  JOIN projects p ON p.id = i.project_id
 WHERE i.deleted_at IS NOT NULL OR p.deleted_at IS NOT NULL;
```

Soft deletes are reversible — `projects.py` has a `restore()` that clears
`deleted_at`. Nothing purges them, so the gap between raw and visible counts
only ever grows.

---

## "I have a UUID — what is it?"

IDs are UUIDs everywhere and nothing in the id tells you what kind of row it is.
Ask every table at once:

```sql
SELECT 'project' AS kind, name                        AS label FROM projects WHERE id = 'PASTE-UUID-HERE'
UNION ALL
SELECT 'image',   filename                                     FROM images   WHERE id = 'PASTE-UUID-HERE'
UNION ALL
SELECT 'gcp',     coalesce(code, name, '(unnamed)')            FROM gcps     WHERE id = 'PASTE-UUID-HERE';
```

One row back tells you what you are holding. **Zero rows means the UUID is not
in this database at all** — most often because you are connected to the *other*
one (see the table at the top), or because the id is a project id and you were
treating it as an image id.

---

## Every image UUID, with the project it belongs to

The lookup you need most often — you have the app in front of you and you want
the UUID to paste into a query, a URL or a bug report.

```sql
\x off

SELECT
  i.id        AS image_id,
  i.filename,
  p.name      AS project,
  p.id        AS project_id
FROM images i
JOIN projects p ON p.id = i.project_id
ORDER BY p.name, i.filename;
```

Only the ones the app can actually see (excludes soft-deleted — see the section
above):

```sql
SELECT
  i.id        AS image_id,
  i.filename,
  p.name      AS project,
  p.id        AS project_id
FROM images i
JOIN projects p ON p.id = i.project_id
WHERE i.deleted_at IS NULL
  AND p.deleted_at IS NULL
ORDER BY p.name, i.filename;
```

### With GCP counts — the version worth keeping

Tells you which image is worth opening, and which hidden images are still
holding points:

```sql
SELECT
  i.id        AS image_id,
  i.filename,
  p.name      AS project,
  count(g.id) AS gcps,
  i.deleted_at
FROM images i
JOIN projects p ON p.id = i.project_id
LEFT JOIN gcps g ON g.image_id = i.id
GROUP BY i.id, i.filename, p.name, i.deleted_at
ORDER BY count(g.id) DESC;
```

★ `LEFT JOIN`, not `JOIN`. An inner join silently drops every image with **no**
GCPs yet — which are usually the exact images you were looking for.

A non-null `deleted_at` marks a soft-deleted image. Its GCP rows are still in
the table but no longer reachable from the app.

### Export the list to a file

```sql
\copy (SELECT i.id, i.filename, p.name FROM images i JOIN projects p ON p.id = i.project_id ORDER BY p.name) TO '~/images.csv' CSV HEADER
```

`\copy` runs client-side and writes where **you** can write. Plain `COPY … TO`
runs as the server process and will fail on permissions.

---

## Every project with its image and GCP totals

```sql
SELECT
  p.id        AS project_id,
  p.name,
  count(DISTINCT i.id) AS images,
  count(g.id)          AS gcps
FROM projects p
LEFT JOIN images i ON i.project_id = p.id AND i.deleted_at IS NULL
LEFT JOIN gcps   g ON g.image_id   = i.id
WHERE p.deleted_at IS NULL
GROUP BY p.id, p.name
ORDER BY count(g.id) DESC;
```

`count(DISTINCT i.id)` is required here — without `DISTINCT`, the join to `gcps`
multiplies each image row once per GCP and the image count comes out inflated.

---

## Inspect the GCPs of one image

```sql
SELECT id, name, code, created_at
FROM gcps
WHERE image_id = 'PASTE-IMAGE-UUID'
ORDER BY created_at DESC;
```

`ORDER BY created_at DESC` is deliberate — it matches the API's default sort, so
what you see here is the order the frontend receives.

---

## Full GCP detail, with its photo and project

The workhorse query. Rounded so it fits on a screen, and it accepts **either** a
GCP id or an image id in the same place — paste the UUID you have and it works
out which it is.

```sql
\x on
```

Then, as a separate paste:

```sql
SELECT p.name AS project, i.filename AS photo, g.id,
       g.code, g.name,
       round(ST_Y(g.geom::geometry)::numeric, 6) AS lat,
       round(ST_X(g.geom::geometry)::numeric, 6) AS lon,
       round(g.pixel_x::numeric, 1) AS px,
       round(g.pixel_y::numeric, 1) AS py,
       g.elevation_m, g.manually_adjusted, g.adjustment_offset_m, g.adjusted_at
FROM gcps g
JOIN images   i ON i.id = g.image_id
JOIN projects p ON p.id = i.project_id
WHERE g.id       = 'PASTE-UUID-HERE'
   OR g.image_id = 'PASTE-UUID-HERE'
ORDER BY g.adjusted_at DESC NULLS LAST, g.created_at DESC;
```

### ★★ `geom` is a GEOGRAPHY column — `ST_Y` needs a cast

```sql
ST_Y(g.geom)              -- ✗ ERROR: function st_y(geography) does not exist
ST_Y(g.geom::geometry)    -- ✓
```

The column is `geography` because distance and containment maths on it are done
on the spheroid, which is what survey work needs. The trade-off is that the
plain accessor functions (`ST_X`, `ST_Y`) live on the geometry side. The cast is
free — identical coordinates, still EPSG:4326.

`original_geom` is a geography too, so the same cast applies:

```sql
ST_Y(g.original_geom::geometry) AS original_lat,
ST_X(g.original_geom::geometry) AS original_lon
```

Avoid the cast entirely if you only want to eyeball it:

```sql
ST_AsText(g.geom)     -- POINT(36.0286117 34.1133990)
```

★ Longitude comes **first** in that text form — the opposite order to how you
read "lat, lon". Check before copying a pair out of it.

`round(… ::numeric, 6)` matters more than it looks: these are `double precision`
columns, and `round(x, 6)` has no double overload in Postgres. Without the
`::numeric` cast you get *"function round(double precision, integer) does not
exist"*.

---

## Every GCP in a project

```sql
SELECT i.filename AS photo, g.code, g.name,
       round(ST_Y(g.geom::geometry)::numeric, 6) AS lat,
       round(ST_X(g.geom::geometry)::numeric, 6) AS lon,
       round(g.pixel_x::numeric, 1) AS px,
       round(g.pixel_y::numeric, 1) AS py,
       g.manually_adjusted, g.adjusted_at
FROM gcps g
JOIN images i ON i.id = g.image_id
WHERE i.project_id = 'PASTE-PROJECT-UUID'
ORDER BY g.created_at DESC;
```

---

## ★ "Where are my GCPs, actually?"

Run this whenever a photograph looks empty and you expected points on it. It
lays out every photo in the database with its point count and the last time
anything on it was adjusted:

```sql
SELECT p.name AS project, i.filename AS photo, count(g.id) AS gcps,
       max(g.adjusted_at) AS last_edit
FROM images i
JOIN projects p ON p.id = i.project_id
LEFT JOIN gcps g ON g.image_id = i.id
GROUP BY p.name, i.filename
ORDER BY gcps DESC;
```

This is the query that settles "I tested it on that photo and nothing saved" —
usually the answer is that the points went to a different photograph, or were
never committed at all. `LEFT JOIN` keeps the zero-GCP photos in the list, which
are precisely the ones you are trying to find.

---

## ★ Narrowing a query to ONE image or ONE project

The two mistakes that make these queries fail or, worse, quietly lie.

### 1. UUIDs are strings. They need quotes.

```sql
p.id = 4b3335ce-b6b0-49b9-8fb0-e6e669ca0ccf     -- ✗
p.id = '4b3335ce-b6b0-49b9-8fb0-e6e669ca0ccf'   -- ✓
```

Unquoted, Postgres reads `4b3335ce` as the number 4 followed by garbage:

```
ERROR:  trailing junk after numeric literal at or near "4b3335ce"
```

### 2. ★★ Never put your UUID in the `ON` clause

`ON` describes **how two tables connect**. `WHERE` describes **which rows you
want**. They are different jobs and swapping them does not error — it returns a
wrong answer that looks plausible.

```sql
-- ✗ WRONG: connects EVERY image to that project, whether it owns them or not
JOIN projects p ON p.id = '4b3335ce-...'

-- ✓ RIGHT: the relationship stays in ON, the filter goes in WHERE
JOIN projects p ON p.id = i.project_id
WHERE i.id = '11d29edd-...'
```

Read `ON` as *"a project matches an image when the project's id equals the
image's project_id"* — a rule about the tables, never about one specific row.

### One image — its project and its GCP count

```sql
SELECT
  i.id        AS image_id,
  i.filename,
  p.name      AS project,
  p.id        AS project_id,
  count(g.id) AS gcps,
  i.deleted_at
FROM images i
JOIN projects p ON p.id = i.project_id
LEFT JOIN gcps g ON g.image_id = i.id
WHERE i.id = 'PASTE-IMAGE-UUID'
GROUP BY i.id, i.filename, p.name, p.id, i.deleted_at;
```

### One project — all of its images

```sql
SELECT
  i.id        AS image_id,
  i.filename,
  count(g.id) AS gcps,
  i.deleted_at
FROM images i
LEFT JOIN gcps g ON g.image_id = i.id
WHERE i.project_id = 'PASTE-PROJECT-UUID'
GROUP BY i.id, i.filename, i.deleted_at
ORDER BY count(g.id) DESC;
```

★ No `projects` table in this one. `images.project_id` is already on the row —
**only join a table when you need a column out of it.** An unnecessary join is
another chance to get an `ON` clause wrong.

### A query returned nothing at all

Not `(0 rows)` — literally no output before the next prompt. That is the `\x on`
paste trap: psql swallowed the query as part of the meta-command line. Send
`\x on`, press Enter, *then* paste. Or use `\x auto` and stop thinking about it.

If it did print `(0 rows)`, the query ran and the answer is genuinely empty —
check the UUID is the kind of id you think it is (see *"I have a UUID — what is
it?"* above), and that you are connected to the database the app is using.

---

## Migrations

```bash
cd backend
alembic upgrade head            # apply everything
alembic current                 # which revision is this database on
alembic history --verbose       # the chain of revisions
alembic downgrade -1            # step back one (know what you are doing)
```

The desktop boot applies migrations automatically — that is the
`[boot] applying database migrations…` line in the smoke output.

---

## Run the API by hand

Sometimes you want the API without the Electron shell:

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check it is listening:

```bash
lsof -i :8000
curl -s http://127.0.0.1:8000/api/v1/health/ready | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/v1/capabilities | python3 -m json.tool
```

The worker, if you need background jobs (exports, DEM processing, video):

```bash
cd backend
celery -A app.tasks.celery_app worker --loglevel info -Q cv,io,export,celery --concurrency 2
```

★ The **managed / installed** app's API listens on **8123**, not 8000. Every
`curl` in this guide works against either — just pick the right port.

---

## Read the app's logs over HTTP (2026-09-01)

The API keeps its own recent log lines in a bounded in-process ring buffer
(`app/core/logbuffer.py`, last ~2000 lines, attached to the root logger — so
uvicorn's and SQLAlchemy's lines are in there too). `GET /api/v1/health/logs`
serves it; the `/status` page in the UI is the same data with a live tail.

```bash
# the newest lines
curl -s "http://127.0.0.1:8123/api/v1/health/logs" | python3 -m json.tool

# filters: minimum level, free-text (matches every field), size
curl -s "http://127.0.0.1:8123/api/v1/health/logs?level=warning&limit=100"
curl -s "http://127.0.0.1:8123/api/v1/health/logs?q=job.failed"

# poll cheaply: pass back last_seq from the previous response
curl -s "http://127.0.0.1:8123/api/v1/health/logs?after=1234"
```

Each entry carries `timestamp`, `level`, `logger`, `event`, the bound
`request_id` when there was one, the formatted `exception` for error lines,
and every other structured field under `fields`. Everything has already been
through the §9.10 secret scrubber — credentials never reach this endpoint.

★ This is why grepping a terminal is no longer the first move: the desktop app
has no terminal, but it has this.

---

## Configuration: which `.env` is actually being read?

**This is the single most expensive gotcha in this codebase.** See
`troubleshooting.md` for the full story. The short version:

```bash
# the RUNNING copy's config — this is the one that wins
cat ~/.local/share/MonoCameraGeolocator/work/.env

# the source tree's config — NOT what a managed run reads
cat backend/.env
```

Nothing keeps them in sync. A setting you "fixed" in `backend/.env` can have no
effect whatsoever on the installed app.
