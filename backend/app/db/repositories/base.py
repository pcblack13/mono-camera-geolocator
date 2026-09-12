"""The generic repository and the helpers every concrete repository shares.

★ **This package is the only place a ``select()`` exists** (L6). Routers receive loaded
entities from ``api.deps`` and call services; services orchestrate and call *these*
classes. A ``select()`` above this layer is a defect.

Three concerns live here, and each of them is here rather than repeated thirteen times:

**1. Error translation.** ``session.py``'s :func:`raise_if_unavailable` documents that
"repositories catch ``SQLAlchemyError`` at their boundary and call this" — so that
``tasks.base`` sees ``DatabaseUnavailable`` (which its error map classifies as
*transient and retryable*) rather than a driver exception it has never heard of and
would classify as ``INTERNAL_ERROR``, i.e. terminal, i.e. a job that will not retry
through a five-second database restart. **The catch is deliberately narrow**:
``OperationalError``/``InterfaceError`` are the connection-class failures.
``IntegrityError`` is *not* caught — a violated constraint is a domain answer, not an
outage, and swallowing it as "unavailable" would turn a duplicate GCP code into a retry
storm.

**2. Sorting.** ``SortParams`` arrives already whitelisted by the schema layer, but a
whitelisted *wire* name is not a column: ``?sort=lat`` must become ``ST_Y(geom)`` and
``?sort=image_count`` a correlated subquery. **Only this layer can make that mapping**,
because only this layer may write SQL. Each repository declares its own
``_sortable`` map; :func:`apply_sort` resolves it and — critically — appends the
``id`` tiebreaker, which is why ``id`` is injected into every map automatically
(``SortParams.stabilised`` adds a key the map must be able to resolve, and a repository
that forgot it would 422 every sorted list in the product).

**3. Counting.** ``Page.total`` is "the exact count matching the filter, ignoring
limit/offset" (§6.2), so it is a second query over the same predicate. :meth:`count_of`
derives it from the *same* ``Select`` the page is built from, which is the only way the
two cannot drift.

**Async, with a sync door for the workers.** The API is async (§6.4: every ``deps.get_*``
is ``async def`` over an ``AsyncSession``), so :class:`BaseRepository` is async and is
what twelve of the thirteen modules use. Celery is **not** async — ``session.py`` is
explicit that driving an asyncio loop per task "is how you get a task that hangs on a
loop that is already running" — so :class:`BaseSyncRepository` exists for the worker,
and ``jobs.py`` additionally ships a full sync repository because the job state machine
*is* the worker's job. The two base classes share their statement construction; only the
``await`` differs.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, Iterable, Mapping, Sequence, TypeVar

from geoalchemy2 import Geography
from sqlalchemy import ColumnElement, Select, cast, func, inspect, select
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidSortField
from app.core.pagination import PaginationParams, SortParams
from app.db.session import raise_if_unavailable
from app.db.types import WGS84_SRID
from app.models.base import Base

__all__ = [
    "BaseRepository",
    "BaseSyncRepository",
    "SortableColumns",
    "apply_pagination",
    "apply_sort",
    "bbox_geography",
    "constraint_name_of",
    "count_stmt_of",
    "csv_enum_filter",
    "like_escape",
]

ModelT = TypeVar("ModelT", bound=Base)

#: A repository's wire-name → SQL-expression map. The keys are exactly the schema
#: layer's ``*_SORT_FIELDS`` whitelist; the values are whatever SQL produces them.
SortableColumns = Mapping[str, ColumnElement[Any]]

#: The tiebreaker ``SortParams.stabilised()`` appends. Every ``_sortable`` map gets it
#: injected, so no repository has to remember.
_TIEBREAKER = "id"


# ─────────────────────────────────────────────────────────────────────────────
# Statement helpers — pure, shared by the async and sync bases
# ─────────────────────────────────────────────────────────────────────────────


def apply_sort(
    stmt: Select[Any],
    sort: SortParams,
    columns: SortableColumns,
    *,
    tiebreaker: ColumnElement[Any] | None = None,
) -> Select[Any]:
    """Resolve a whitelisted ``?sort=`` onto real SQL and stabilise it.

    Args:
        stmt: The select to order.
        sort: Already parsed and whitelisted by ``SortParams.parse``.
        columns: This repository's wire-name → expression map.
        tiebreaker: The column ``id`` resolves to. Defaults to ``columns["id"]``.

    Returns:
        ``stmt`` with an ``ORDER BY`` that is a **total** order.

    Raises:
        InvalidSortField: the schema whitelisted a field this repository cannot
            express. That is a map/whitelist drift bug rather than a client error, and
            it is reported rather than silently dropped — an ignored sort key returns
            rows in an arbitrary order, which is the failure ``stabilised()`` exists to
            prevent.

    ★ The tiebreaker is not optional and is invisible to the client. Offset pagination
    over equal-valued rows — forty GCPs all at ``confidence = 100`` — duplicates and
    drops rows across pages without a total order, and nothing anywhere reports an
    error. ``SortParams.stabilised`` appends ``id``; this function is what makes ``id``
    resolvable.
    """
    resolved: dict[str, ColumnElement[Any]] = dict(columns)
    if tiebreaker is not None:
        resolved.setdefault(_TIEBREAKER, tiebreaker)

    for key in sort.stabilised(_TIEBREAKER).keys:
        expr = resolved.get(key.field)
        if expr is None:
            raise InvalidSortField(
                f"Cannot sort by {key.field!r}.",
                details=[
                    {
                        "loc": ["query", "sort"],
                        "msg": f"Sortable fields: {', '.join(sorted(resolved))}",
                        "type": "sort.unmapped_field",
                        "input": key.field,
                    }
                ],
            )
        stmt = stmt.order_by(expr.desc() if key.descending else expr.asc())
    return stmt


def apply_pagination(stmt: Select[Any], pagination: PaginationParams) -> Select[Any]:
    """``LIMIT``/``OFFSET`` from a validated :class:`PaginationParams`."""
    return stmt.limit(pagination.limit).offset(pagination.offset)


def count_stmt_of(stmt: Select[Any]) -> Select[tuple[int]]:
    """Build ``SELECT count(*)`` over the *same* predicate as a page's select.

    ``ORDER BY``/``LIMIT``/``OFFSET`` are stripped first. Not a micro-optimisation:
    ``Page.total`` is the count "ignoring limit/offset" by definition (§6.2), and
    leaving the ordering in would make the database materialise ``ST_Y(geom)`` or a
    correlated ``image_count`` subquery for every row just to throw the order away.
    """
    inner = stmt.order_by(None).limit(None).offset(None).subquery()
    return select(func.count()).select_from(inner)


def like_escape(value: str) -> str:
    """Escape ``%``, ``_`` and ``\\`` for a ``LIKE``/``ILIKE`` pattern.

    Free-text ``?q=`` reaches ``ILIKE`` on ``name``/``filename``/``label``. Without
    escaping, a search for ``100%`` matches every row and a search for ``a_b`` matches
    ``axb`` — a filter that silently returns the wrong parcel is exactly what
    ``extra="forbid"`` on the query models exists to prevent one layer up.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def csv_enum_filter(raw: str | None, allowed: Iterable[str]) -> list[str]:
    """Split a CSV query value (``?status=pending,running``) and keep known members.

    Unknown members are **dropped rather than rejected**: the schema layer owns request
    validation (``extra="forbid"``, typed enum fields), so by the time a value reaches a
    repository it has already been through it. Dropping keeps this total for internal
    callers that pass a member list directly.

    Args:
        raw: The raw CSV, or None.
        allowed: The enum's legal values.

    Returns:
        The requested members, de-duplicated, order-preserved. ``[]`` when nothing was
        requested — the caller reads that as "no filter", not as "match nothing".
    """
    if not raw:
        return []
    permitted = set(allowed)
    out: list[str] = []
    for token in (t.strip() for t in raw.split(",")):
        if token and token in permitted and token not in out:
            out.append(token)
    return out


def bbox_geography(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> ColumnElement[Any]:
    """``ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)::geography``.

    ★★ **The package's only envelope site**, for the same reason
    :func:`app.db.types.point_wkt` is its only point site — and the two guard the same
    mistake from opposite directions.

    ``ST_MakeEnvelope`` is ``(xmin, ymin, xmax, ymax)``: **longitudes first, interleaved
    with latitudes.** It is the easiest signature in PostGIS to fill in from a
    ``(lat, lon)`` mental model, and doing so does not raise — it produces a box
    somewhere else on Earth that matches nothing, so the caller sees an empty result and
    reads it as "no data here". An **inverted** box (``min > max``) does the same. Both
    are checked here, because a viewport that silently renders nothing is a bug that
    survives review, a demo, and a release.

    The cast is explicit — ``geography(POLYGON,4326)``, not a bare ``Geography`` class —
    so the emitted SQL is the ``::geography`` of §5.8 rather than whatever a default
    typmod would resolve to. A ``geography`` GIST index is a 3-D geocentric box, so the
    resulting predicate is correct across the antimeridian and at the poles; a 2-D 4326
    ``geometry`` index gives **wrong answers** across ±180° (§5.2).

    Args:
        min_lon: West edge. **Longitude first.**
        min_lat: South edge.
        max_lon: East edge.
        max_lat: North edge.

    Returns:
        A geography polygon expression, ready for ``ST_Intersects`` against a geography
        column.

    Raises:
        ValueError: an ordinate out of range (the transposition guard) or an inverted
            box.
    """
    if not -180.0 <= min_lon <= 180.0 or not -180.0 <= max_lon <= 180.0:
        raise ValueError(
            f"longitudes ({min_lon}, {max_lon}) outside [-180, 180] — are lon/lat transposed?"
        )
    if not -90.0 <= min_lat <= 90.0 or not -90.0 <= max_lat <= 90.0:
        raise ValueError(
            f"latitudes ({min_lat}, {max_lat}) outside [-90, 90] — are lon/lat transposed?"
        )
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError(
            f"inverted bbox: ({min_lon}, {min_lat}) is not the lower-left of "
            f"({max_lon}, {max_lat}). An inverted envelope matches nothing and raises "
            f"nothing — say so here instead."
        )
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, WGS84_SRID)
    return cast(envelope, Geography(geometry_type="POLYGON", srid=WGS84_SRID))


def constraint_name_of(exc: IntegrityError) -> str | None:
    """Pull the violated constraint's name out of a driver ``IntegrityError``.

    Repositories map a *named* constraint to a domain error — ``uq_gcps_image_code`` →
    ``GcpCodeConflict`` — because the constraint name is SQL, and SQL lives here. The
    alternative is a service that string-matches a driver message, which breaks on a
    driver upgrade and on a locale change.

    Returns:
        The constraint name, or None when the driver did not supply one (a check
        without a name, a non-psycopg driver). Callers must handle None by re-raising:
        **guessing which constraint fired is how a 409 lands on a 500.**
    """
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else None


# ─────────────────────────────────────────────────────────────────────────────
# The async base — twelve of the thirteen modules
# ─────────────────────────────────────────────────────────────────────────────


class BaseRepository(Generic[ModelT]):
    """Generic async CRUD over one mapped class.

    Subclasses set :attr:`model` and add the queries their entity actually needs. The
    generic operations here are the ones whose SQL is identical for every table; the
    interesting SQL is never generic and lives in the subclass.

    **Nothing here commits.** The request is the transaction boundary (``get_session``
    commits on a clean return, rolls back on an exception), and the worker's
    ``sync_session()`` does the same. A repository that committed for itself would mean
    a bulk annotation upsert that fails halfway leaves half its writes behind — a
    corrupt survey. :meth:`flush` exists for the one legitimate need: making a
    server-generated default (an id, a ``created_at``) readable *within* the
    transaction.
    """

    #: Set by every subclass. Not abstract-by-ABC on purpose: an ABC here buys nothing
    #: and costs a metaclass conflict with SQLAlchemy's declarative machinery.
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: The request's (or task's) session. Never created here — the
                caller owns the transaction.
        """
        self.session = session

    # ── execution — the single error-translation boundary ────────────────────

    async def _execute(self, stmt: Any) -> Any:
        """Execute, translating connection failures into ``DatabaseUnavailable``.

        Every query in every subclass goes through here, which is what makes the
        translation total rather than aspirational.
        """
        try:
            return await self.session.execute(stmt)
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)
            raise  # pragma: no cover — raise_if_unavailable never returns.

    async def _scalars(self, stmt: Select[Any]) -> Sequence[Any]:
        result = await self._execute(stmt)
        return result.scalars().all()

    async def _scalar_one_or_none(self, stmt: Select[Any]) -> Any | None:
        result = await self._execute(stmt)
        return result.scalar_one_or_none()

    async def _scalar(self, stmt: Any) -> Any:
        result = await self._execute(stmt)
        return result.scalar()

    # ── generic reads ────────────────────────────────────────────────────────

    async def get(self, entity_id: uuid.UUID | int) -> ModelT | None:
        """One row by primary key, or None.

        Returns None rather than raising: ``deps.get_*`` turns None into the 404 with
        the right error code, and a repository does not know whether its caller wants a
        404 or a "create if absent".
        """
        return await self._scalar_one_or_none(
            select(self.model).where(self._pk() == entity_id)
        )

    async def exists(self, entity_id: uuid.UUID | int) -> bool:
        """Whether a row exists, without loading it."""
        stmt = select(func.count()).select_from(self.model).where(self._pk() == entity_id)
        return bool(await self._scalar(stmt))

    async def count_of(self, stmt: Select[Any]) -> int:
        """``Page.total`` for a page's select. See :func:`count_stmt_of`."""
        return int(await self._scalar(count_stmt_of(stmt)) or 0)

    async def page(
        self,
        stmt: Select[Any],
        pagination: PaginationParams,
        sort: SortParams,
        columns: SortableColumns,
    ) -> tuple[Sequence[ModelT], int]:
        """The (items, total) pair every ``list_*`` returns.

        ★ The **total is counted from the unsorted, unpaginated form of the same
        statement**, so the count and the page can never disagree about the filter.
        Two hand-written queries would be two chances to forget a predicate, and the
        symptom — a page that says "1,274 events" and returns rows from a different
        filter — is invisible in review.
        """
        total = await self.count_of(stmt)
        ordered = apply_sort(stmt, sort, columns, tiebreaker=self._pk())
        rows = await self._scalars(apply_pagination(ordered, pagination))
        return rows, total

    # ── generic writes ───────────────────────────────────────────────────────

    def add(self, obj: ModelT) -> ModelT:
        """Stage an INSERT. Not async — ``Session.add`` does no IO."""
        self.session.add(obj)
        return obj

    def add_all(self, objs: Iterable[ModelT]) -> list[ModelT]:
        """Stage many INSERTs."""
        staged = list(objs)
        self.session.add_all(staged)
        return staged

    async def delete(self, obj: ModelT) -> None:
        """Stage a DELETE of a loaded row.

        Hard delete. Soft delete is ``projects``/``images`` only (§5.4) and is a column
        update, so it lives on those two repositories where it means something.
        """
        try:
            await self.session.delete(obj)
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)

    async def flush(self) -> None:
        """Flush pending changes so server-side defaults become readable.

        Not a commit. Use it when you need the id of a row you just added *inside* the
        same transaction — an annotation's id for its ledger event, a match result's id
        for the GCP that cites it.
        """
        try:
            await self.session.flush()
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)

    async def refresh(self, obj: ModelT, attrs: Sequence[str] | None = None) -> ModelT:
        """Re-read an object's columns from the database.

        Needed after an ``UPDATE ... RETURNING`` issued as Core SQL: the ORM's identity
        map still holds the pre-update values, and every relationship on every model is
        ``lazy="raise"``, so a stale attribute cannot be papered over by a lazy load.
        """
        try:
            await self.session.refresh(obj, attribute_names=list(attrs) if attrs else None)
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)
        return obj

    # ── internals ────────────────────────────────────────────────────────────

    def _pk(self) -> ColumnElement[Any]:
        """The single-column primary key of :attr:`model`.

        Every table in §5.5 has one — ``id``, UUID or BIGSERIAL. A composite key would
        break the generic ``get``, so it is asserted rather than assumed.
        """
        pks = inspect(self.model).primary_key
        if len(pks) != 1:  # pragma: no cover — §5.4 admits no composite key.
            raise TypeError(
                f"{self.model.__name__} has a composite primary key; the generic "
                f"repository operations require the single-column key §5.4 mandates."
            )
        return pks[0]


# ─────────────────────────────────────────────────────────────────────────────
# The sync base — Celery
# ─────────────────────────────────────────────────────────────────────────────


class BaseSyncRepository(Generic[ModelT]):
    """The synchronous twin of :class:`BaseRepository`, for Celery workers.

    ``session.py``'s ``sync_session()`` is the worker's session and its docstring shows
    exactly this shape. Prefork workers run synchronous code; wrapping every task in
    ``asyncio.run()`` to satisfy an async interface is how you get a task that hangs on
    a loop that is already running.

    The SQL is the same SQL — statement construction is shared with the async base via
    the module-level helpers above, and only the ``await`` differs. Where a worker needs
    more than generic CRUD it gets a purpose-built sync class; see
    :class:`~app.db.repositories.jobs.SyncJobRepository`, which is the one the job state
    machine and the progress writer use.
    """

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def _execute(self, stmt: Any) -> Any:
        try:
            return self.session.execute(stmt)
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)
            raise  # pragma: no cover

    def _scalars(self, stmt: Select[Any]) -> Sequence[Any]:
        return self._execute(stmt).scalars().all()

    def _scalar_one_or_none(self, stmt: Select[Any]) -> Any | None:
        return self._execute(stmt).scalar_one_or_none()

    def _scalar(self, stmt: Any) -> Any:
        return self._execute(stmt).scalar()

    def get(self, entity_id: uuid.UUID | int) -> ModelT | None:
        """One row by primary key, or None."""
        return self._scalar_one_or_none(select(self.model).where(self._pk() == entity_id))

    def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        return obj

    def add_all(self, objs: Iterable[ModelT]) -> list[ModelT]:
        staged = list(objs)
        self.session.add_all(staged)
        return staged

    def flush(self) -> None:
        try:
            self.session.flush()
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)

    def _pk(self) -> ColumnElement[Any]:
        pks = inspect(self.model).primary_key
        if len(pks) != 1:  # pragma: no cover
            raise TypeError(f"{self.model.__name__} has a composite primary key.")
        return pks[0]
