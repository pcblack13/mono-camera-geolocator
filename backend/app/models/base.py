"""Declarative base and the naming convention (CONTRACT.md §5.4, §5.5).

Every ORM class in ``app.models`` inherits :class:`Base`. The ``NAMING_CONVENTION``
is attached to ``Base.metadata`` **and** re-applied in ``alembic/env.py``, because a
convention that exists only on one side produces migrations whose constraint names
drift from the models' — and a constraint whose name Alembic cannot predict is a
constraint Alembic will happily drop and recreate on every autogenerate.

Constraint names in §5.6 are written out in full (``ck_projects_name_nonblank``).
They are produced here by passing the **short** name (``name_nonblank``) to
``CheckConstraint`` and letting ``ck: "ck_%(table_name)s_%(constraint_name)s"``
expand it. The full name is therefore never typed twice.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base", "NAMING_CONVENTION"]

#: §5.4 — ``ix_/uq_/ck_/fk_/pk_`` prefixes, snake_case, tables plural.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """The declarative base for every LandExplorer ORM model.

    ``metadata`` here is the *whole* schema: ``app/models/__init__.py`` imports every
    module precisely so that ``Base.metadata`` is complete before Alembic reads it
    (§5.5 — an unimported model module autogenerates to an empty diff, silently).
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    #: ``metadata`` is reserved on ``DeclarativeBase``; the JSONB column named
    #: ``metadata`` in §5.6 is therefore mapped to the attribute ``meta`` on the
    #: three tables that carry it. This alias table makes that explicit to readers.
    type_annotation_map: dict[Any, Any] = {}

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance only
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk!r}>"
