"""Engines and sessions — async for the API, sync for Celery (CONTRACT.md §2.4).

Two engines, because there are two runtimes and they disagree about the world:

* **The API is async.** ``get_session`` is what ``api.deps.get_db`` yields.
* **Celery is not.** Its workers are prefork processes running synchronous code, and
  driving an asyncio loop per task to satisfy an interface is how you get a task
  that hangs on a loop that is already running. ``sync_session`` is for them.

Both are lazy and cached. Neither is built at import: a module-scope
``create_async_engine`` runs at import time in every process that touches this
module, including ``alembic``, ``pytest`` collection, and a ``--help`` invocation —
and it would resolve the ``db`` hostname, which does not exist outside compose. §9.13
promises that ``uvicorn app.main:app`` with no env **starts** and that
``/health/ready`` then returns a 503 *diagnosis* rather than a boot traceback. That
promise lives here.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, AsyncIterator, Final, Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.exceptions import DatabaseUnavailable
from app.core.logging import get_logger

__all__ = [
    "check_database",
    "dispose_engines",
    "get_async_engine",
    "get_session",
    "get_sessionmaker",
    "get_sync_engine",
    "get_sync_sessionmaker",
    "session_scope",
    "sync_session",
]

log = get_logger(__name__)

#: Drivers that only speak asyncio, mapped to the sync driver for the same database.
#: The default URL (``postgresql+psycopg``) needs no translation — psycopg3's
#: SQLAlchemy dialect serves both sync and async — but an operator who sets asyncpg
#: for the API would otherwise hand asyncpg to Celery, where it cannot work.
_ASYNC_TO_SYNC_DRIVER: Final[dict[str, str]] = {
    "postgresql+asyncpg": "postgresql+psycopg",
    "postgresql+psycopg_async": "postgresql+psycopg",
}
_SYNC_TO_ASYNC_DRIVER: Final[dict[str, str]] = {
    "postgresql+psycopg2": "postgresql+psycopg",
    "postgresql": "postgresql+psycopg",
}

_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_sync_engine: Engine | None = None
_sync_sessionmaker: sessionmaker[Session] | None = None


def _swap_driver(url: str, table: dict[str, str]) -> str:
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    return f"{table[scheme]}://{rest}" if scheme in table else url


def _async_url(settings: Settings) -> str:
    return _swap_driver(settings.database_url, _SYNC_TO_ASYNC_DRIVER)


def _sync_url(settings: Settings) -> str:
    return _swap_driver(settings.database_url, _ASYNC_TO_SYNC_DRIVER)


def _connect_args(settings: Settings) -> dict[str, Any]:
    """Per-connection libpq options.

    ``statement_timeout`` is set on the *connection*, not per query, because the
    protection has to cover the query nobody remembered to wrap. A runaway PostGIS
    scan holding a connection for an hour exhausts the pool and takes the API down
    with it; the timeout turns that into one failed request. 0 disables it, which is
    what a migration wants and what LE_DB_STATEMENT_TIMEOUT_MS=0 expresses.
    """
    if settings.db_statement_timeout_ms <= 0:
        return {}
    return {"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"}


def get_async_engine(settings: Settings | None = None) -> AsyncEngine:
    """The process-wide async engine. Built on first use, then cached."""
    global _async_engine
    if _async_engine is None:
        settings = settings or get_settings()
        _async_engine = create_async_engine(
            _async_url(settings),
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            # A connection idle for half an hour behind a cloud load balancer is a
            # connection that has already been silently closed at the other end;
            # recycling pre-empts the "server closed the connection unexpectedly"
            # that would otherwise surface as a random 500.
            pool_recycle=1800,
            # Costs one round trip per checkout and buys back every stale-connection
            # error class. At this system's request rate it is not measurable.
            pool_pre_ping=True,
            connect_args=_connect_args(settings),
        )
        log.info(
            "db.engine_created",
            kind="async",
            url=settings.redacted_database_url(),
            pool_size=settings.db_pool_size,
        )
    return _async_engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """The async session factory."""
    global _async_sessionmaker
    if _async_sessionmaker is None:
        _async_sessionmaker = async_sessionmaker(
            bind=get_async_engine(settings),
            class_=AsyncSession,
            # expire_on_commit=False: with it on, every attribute of every ORM object
            # is expired at commit, so a router serialising the object it just saved
            # triggers a lazy refresh — on an async session, from a sync serialiser,
            # which raises MissingGreenlet rather than doing anything useful.
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session for one request, committing on success and rolling back on error.

    This is what ``api.deps.get_db`` yields (§6.4). The request is the transaction
    boundary: a router that returns 200 has committed, and one that raises has not.
    Making each repository commit for itself would mean a request that fails halfway
    leaves half its writes behind — for annotation bulk-upsert or a revision restore,
    that is a corrupt survey.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_sync_engine(settings: Settings | None = None) -> Engine:
    """The process-wide sync engine, for Celery workers and offline scripts."""
    global _sync_engine
    if _sync_engine is None:
        settings = settings or get_settings()
        _sync_engine = create_engine(
            _sync_url(settings),
            echo=settings.db_echo,
            # ★ NullPool, deliberately, and it is not a performance oversight.
            #
            # Celery's default worker is prefork: the parent imports this module and
            # the children inherit its memory — including any pooled sockets. Two
            # processes writing to one TCP connection produce protocol desync errors
            # that read as random corruption and are miserable to diagnose. NullPool
            # holds nothing across the fork. A CV task runs for minutes and opens one
            # connection at the end; connection setup is not its bottleneck.
            poolclass=NullPool,
            connect_args=_connect_args(settings),
        )
        log.info("db.engine_created", kind="sync", url=settings.redacted_database_url())
    return _sync_engine


def get_sync_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    """The sync session factory."""
    global _sync_sessionmaker
    if _sync_sessionmaker is None:
        _sync_sessionmaker = sessionmaker(
            bind=get_sync_engine(settings),
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sync_sessionmaker


@contextmanager
def sync_session() -> Iterator[Session]:
    """A transactional sync session. The worker-side counterpart of ``get_session``.

    ::

        with sync_session() as db:
            repo = JobRepository(db)
            repo.mark_running(job_id)
    """
    factory = get_sync_sessionmaker()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope(session: Session) -> Iterator[Session]:
    """Wrap an existing sync session in a nested transaction (SAVEPOINT).

    For the worker's progress writes, which §5.5 requires to be a plain UPDATE that
    **never runs inside the CV transaction**: progress is telemetry, and it must never
    hold a lock a matcher needs.
    """
    with session.begin_nested():
        yield session


async def check_database(settings: Settings | None = None) -> tuple[bool, str]:
    """Probe the database for ``/health/ready``. Never raises.

    Returns:
        ``(ok, detail)``. The detail names the database it could not reach — with the
        password stripped (``redacted_database_url``) — because §9.3's whole premise
        is that a bare-host deployment with the default ``db`` hostname should get a
        **legible diagnosis** rather than a boot traceback. A readiness check that
        reports "not ready" without saying which dependency, or that leaks a password
        while saying it, has failed at its one job.
    """
    settings = settings or get_settings()
    try:
        engine = get_async_engine(settings)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "ok"
    except SQLAlchemyError as exc:
        log.warning("db.unreachable", url=settings.redacted_database_url(), error=str(exc))
        return False, f"cannot connect to {settings.redacted_database_url()}: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 — a probe that raises is a probe that lies.
        log.warning("db.probe_failed", url=settings.redacted_database_url(), error=str(exc))
        return False, f"database probe failed: {type(exc).__name__}"


async def dispose_engines() -> None:
    """Close both pools. Called from ``main.py``'s lifespan shutdown.

    Without this, a reload or a graceful shutdown leaves connections open on the
    server until they time out, and a rapid restart loop can exhaust
    ``max_connections`` with the corpses of previous boots.
    """
    global _async_engine, _async_sessionmaker, _sync_engine, _sync_sessionmaker
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_sessionmaker = None
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_sessionmaker = None


@event.listens_for(Engine, "connect")
def _register_connection(dbapi_connection: Any, connection_record: Any) -> None:
    """Trace new physical connections. Cheap, and the first thing you want in an
    incident where the pool is the suspect."""
    log.debug("db.connection_opened")


def raise_if_unavailable(exc: Exception) -> None:
    """Translate a driver-level connection failure into a domain error.

    Repositories catch ``SQLAlchemyError`` at their boundary and call this so the
    service layer sees ``DatabaseUnavailable`` — which ``tasks.base`` classifies as
    **transient and retryable** (§5.5) — rather than a driver exception that its
    error map has never heard of and would classify as ``INTERNAL_ERROR``, i.e.
    terminal, i.e. a job that will not retry through a five-second database restart.
    """
    raise DatabaseUnavailable("The database is unavailable.") from exc
