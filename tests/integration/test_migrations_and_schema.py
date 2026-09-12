"""★ Tier-2 migration test — compose-backed, `@pytest.mark.db` (§13.1 IU-31).

*"`upgrade head` against real PostGIS, `alembic check` reports no drift vs the models, then
`downgrade base` + `upgrade head` proves reversibility. Skipped automatically when
`LE_DATABASE_URL` is unset, so `pytest` on the dev machine is green."*

This is the **live-database** counterpart to IU-16's Tier-1 test, which renders the DDL
offline with `--sql`. Tier 1 catches import errors, a missing `import geoalchemy2`, broken
revision chains and multiple heads with zero infrastructure; only a real PostGIS can prove
that the migrations *apply*, that PostGIS accepts every `geography`/`geometry` column, and
that `downgrade` is actually the inverse of `upgrade`.

★ **Every test here is `@pytest.mark.db`**, and `tests/conftest.py` auto-skips the whole
marker unless `LE_DATABASE_URL` is set. On the dev machine — no Docker, no Postgres (§0.1) —
this file collects and skips. It is red only where a database exists to make it meaningful.

The 17 tables (§5.5) the DDL must create — held here as the acceptance list so a dropped
migration is caught by name, not by a vague count:
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
BACKEND_DIR: Final[Path] = REPO_ROOT / "backend"

#: §5.5's "Class -> table map (17 models, 17 tables)". A dropped or renamed migration shows
#: up here as a missing name, which is more useful than "expected 17, found 16".
EXPECTED_TABLES: Final[frozenset[str]] = frozenset(
    {
        "projects",
        "project_revisions",
        "images",
        "annotations",
        "annotation_versions",
        "match_jobs",
        "aux_jobs",
        "batch_jobs",
        "batch_job_items",
        "match_results",
        "gcps",
        "camera_poses",
        "confidence_heatmaps",
        "confidence_heatmap_cells",
        "semantic_features",
        "landmark_suggestions",
        "exports",
    }
)

#: SCOPE.md §4 rule 5: the deferred tables are CREATED, they simply hold no rows. Their
#: presence in the schema is the "schema is NOT cut" guarantee — re-enabling the engine must
#: not require a migration.
DEFERRED_BUT_PRESENT: Final[frozenset[str]] = frozenset(
    {"match_jobs", "match_results", "camera_poses", "confidence_heatmaps", "semantic_features"}
)


pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("LE_DATABASE_URL")
    if not url:
        pytest.skip("LE_DATABASE_URL unset")
    return url


def _alembic(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run alembic in the backend directory, capturing output."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["alembic", *args],
        cwd=BACKEND_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_head_applies_against_real_postgis(database_url: str) -> None:
    """★ Every migration applies to a live PostGIS, and every §5.5 table exists after.

    The offline Tier-1 test proves the DDL *renders*; only this proves PostGIS *accepts* it —
    the `CREATE EXTENSION postgis`, the `geography(Point, 4326)` columns, the partial GIST
    indexes. The deferred tables are asserted present too (SCOPE.md §4 rule 5): the schema is
    not cut, it merely holds no rows.
    """
    pytest.importorskip("sqlalchemy", reason="the DB tier needs sqlalchemy")
    from sqlalchemy import create_engine, inspect

    result = _alembic("upgrade", "head", env={"LE_DATABASE_URL": database_url})
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"

    engine = create_engine(database_url.replace("+asyncpg", "+psycopg"))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    missing = EXPECTED_TABLES - tables
    assert not missing, f"upgrade head did not create: {sorted(missing)}"
    assert DEFERRED_BUT_PRESENT <= tables, (
        "a deferred table is absent; SCOPE.md §4 rule 5 requires the schema uncut so "
        "re-enabling the engine is not a migration"
    )


def test_alembic_check_reports_no_drift(database_url: str) -> None:
    """★ The migrations and the ORM models agree.

    `alembic check` autogenerates against the current models and asserts the diff is empty.
    A non-empty diff means a model gained a column that no migration adds — the schema the
    tests run against is not the schema the code expects.
    """
    _alembic("upgrade", "head", env={"LE_DATABASE_URL": database_url})
    result = _alembic("check", env={"LE_DATABASE_URL": database_url})
    assert result.returncode == 0, (
        "alembic check found drift between the models and the migrations:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_downgrade_then_upgrade_is_reversible(database_url: str) -> None:
    """★ `downgrade base` + `upgrade head` — the migrations are actually invertible.

    A migration whose `downgrade()` is a stub passes every forward test and then strands a
    production database the first time a release is rolled back. Round-tripping to base and
    back is the only thing that exercises the `downgrade()` bodies.
    """
    down = _alembic("downgrade", "base", env={"LE_DATABASE_URL": database_url})
    assert down.returncode == 0, f"downgrade base failed:\n{down.stderr}"

    up = _alembic("upgrade", "head", env={"LE_DATABASE_URL": database_url})
    assert up.returncode == 0, f"re-upgrade after downgrade failed:\n{up.stderr}"


def test_single_head(database_url: str) -> None:
    """★ Exactly one head — parallel migration branches are a silent merge hazard."""
    result = _alembic("heads", env={"LE_DATABASE_URL": database_url})
    assert result.returncode == 0
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected a single head, found {len(heads)}:\n{result.stdout}"
