"""Declarative mixins (CONTRACT.md §5.4, §5.5).

Three concerns, three mixins, no inheritance chain: a table takes exactly the ones it
has. ``annotation_versions`` and ``confidence_heatmap_cells`` take **none** of the PK
mixin (they are ``BIGSERIAL`` — append-only, high-row-count, never in a URL), and only
``projects`` and ``images`` take :class:`SoftDeleteMixin` (§5.4: everything below them
hard-cascades).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["SoftDeleteMixin", "TimestampMixin", "UUIDPkMixin"]


class UUIDPkMixin:
    """``id UUID PRIMARY KEY DEFAULT gen_random_uuid()``.

    ``gen_random_uuid()`` is core in PG 13+, so there is no ``pgcrypto`` dependency.
    ``default=uuid.uuid4`` is declared **as well as** the server default because IDs are
    minted client-side for optimistic UI: the value normally arrives with the INSERT and
    the server default is the safety net, not the usual path.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """``created_at``/``updated_at``, both ``TIMESTAMPTZ NOT NULL DEFAULT now()``.

    ★ ``updated_at`` is maintained by the ``tg_set_updated_at()`` trigger attached per
    table in migration ``0009`` — **not** by the ORM (§5.4). A Celery bulk ``UPDATE``
    must not be able to skip it. ``server_onupdate`` records that fact for Alembic and
    for the reader; it emits no client-side value.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )


class SoftDeleteMixin:
    """``deleted_at TIMESTAMPTZ NULL`` — ``projects`` and ``images`` only."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
