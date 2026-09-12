"""Albums — a user-defined, **many-to-many** collection of projects.

Mirrors ``project.py``'s shape exactly: a ``*Create``, a ``*Update`` on
:class:`~app.schemas.common.PatchModel` with UNSET semantics, a fat ``*Read`` and a
thin ``*Summary`` list projection.

★ **The membership endpoints carry no body at all** —
``POST/DELETE /albums/{album_id}/projects/{project_id}`` say everything in the path and
answer ``204``. There is therefore no ``AlbumProjectCreate`` here: a body whose only
possible content is the id already in the URL is a second place for the two to disagree.

★ :class:`~app.schemas.common.AlbumRef` — the ``{id, name}`` pair a project row carries —
lives in ``common`` rather than here, for the reason §6.2 gives when it moved
``RevisionSummary`` there: ``project.py`` needs it and this module needs it, and a
``project → album`` import would be a fourth domain-to-domain edge in a package whose
stated rule is one-way ``common``/``enums``/``errors`` ← everything else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from .common import ApiModel, ListParams, PatchModel

__all__ = [
    "ALBUM_SORT_FIELDS",
    "AlbumCreate",
    "AlbumListParams",
    "AlbumRead",
    "AlbumSummary",
    "AlbumUpdate",
]

#: ★ ``project_count`` is on the whitelist and is **not a column** — the repository
#: resolves it onto a correlated count over ``album_projects``, exactly as
#: ``PROJECT_SORT_FIELDS`` does for ``image_count``. Every sort is stabilised by the
#: repository with a trailing ``id ASC``.
ALBUM_SORT_FIELDS = frozenset({"name", "created_at", "updated_at", "project_count"})

#: 1–200, non-blank after strip. ``str_strip_whitespace`` on ``ApiModel`` runs BEFORE
#: ``min_length``, so ``"   "`` becomes ``""`` and fails the bound with no extra
#: validator — the same mechanism ``ProjectName`` relies on, and it mirrors
#: ``ck_albums_name_nonblank``.
AlbumName = Annotated[str, Field(min_length=1, max_length=200)]

#: A hex triple/sextet or a short design token (``"#3B82F6"``, ``"amber"``). Deliberately
#: **not** a strict hex pattern: the field is a UI tint, the frontend owns the palette,
#: and rejecting ``"amber"`` here would make the server the arbiter of a colour system it
#: cannot see. The bound mirrors ``ck_albums_color_short`` so a violation is a clean 422
#: rather than a ``23514`` from Postgres.
AlbumColor = Annotated[str, Field(min_length=1, max_length=32)]


class AlbumCreate(ApiModel):
    """``POST /albums``.

    ``{"name": "2026 season"}`` alone is a complete album — description and colour are
    both genuinely optional, and neither is invented server-side.
    """

    name: AlbumName
    description: str | None = Field(default=None, max_length=4000)
    color: AlbumColor | None = Field(
        default=None,
        description=(
            "A short hex or design token for UI tinting, e.g. '#3B82F6' or 'amber'. "
            "★ null means NO COLOUR CHOSEN — the server never picks one."
        ),
    )


class AlbumUpdate(PatchModel):
    """``PATCH /albums/{album_id}`` — rename / re-describe / re-tint. ★ UNSET semantics.

    ``{"color": null}`` **clears** the colour; ``{}`` is a ``400 EMPTY_PATCH`` raised by
    the router off :meth:`PatchModel.is_empty`. ``name`` is ``T | None`` only because
    every PATCH field must be omittable — clearing it is refused by the service, since
    an album with no name is not a thing the UI can render.
    """

    name: AlbumName | None = None
    description: str | None = Field(default=None, max_length=4000)
    color: AlbumColor | None = None


class AlbumRead(ApiModel):
    """``AlbumRead`` — the create, get and patch responses."""

    id: UUID
    name: str
    description: str | None
    color: str | None
    project_count: int = Field(
        ge=0,
        description=(
            "How many projects are in this album. ★ One batched aggregate, never a "
            "loaded relationship — ``Album.projects`` is ``lazy='raise'`` precisely so "
            "an N+1 cannot creep in through it."
        ),
    )
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class AlbumSummary(ApiModel):
    """List projection — ``GET /albums``.

    Carries the same fields as :class:`AlbumRead` minus ``deleted_at``: an album has no
    expensive projection to omit (no AOI, no five-subquery rollup), so the two differ
    only in the soft-delete marker, which a list of live albums has no use for.
    """

    id: UUID
    name: str
    description: str | None
    color: str | None
    project_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class AlbumListParams(ListParams):
    """``GET /albums``."""

    q: str | None = Field(default=None, description="Free-text over name + description.")
    include_deleted: bool = False
