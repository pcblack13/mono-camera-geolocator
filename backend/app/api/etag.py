"""ETag helpers — optimistic concurrency and conditional GET (§6.5).

Pure functions (no DB, no framework state beyond the request headers), shared by the routers
that carry ``ETag`` / ``If-Match`` / ``If-None-Match``. A strong ETag is derived from a
resource's version counter and its ``updated_at``, so two edits that land in the same second
still differ.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from starlette.requests import Request

__all__ = ["etag_for", "if_match_ok", "if_none_match_hit", "version_etag"]


def version_etag(version: int | str) -> str:
    """A strong ETag from a bare version counter (e.g. an annotation's ``version_no``)."""
    return f'"{version}"'


def etag_for(version: int | str, updated_at: datetime | None) -> str:
    """A strong ETag from a version counter plus ``updated_at`` (µs epoch)."""
    stamp = int(updated_at.timestamp() * 1_000_000) if updated_at is not None else 0
    return f'"{version}-{stamp}"'


def _normalise(value: str) -> str:
    return value.strip().removeprefix("W/").strip().strip('"')


def if_none_match_hit(request: Request, etag: str) -> bool:
    """True when the client's ``If-None-Match`` already holds this ETag → serve 304."""
    header = request.headers.get("if-none-match")
    if not header:
        return False
    if header.strip() == "*":
        return True
    wanted = _normalise(etag)
    return any(_normalise(part) == wanted for part in header.split(","))


def if_match_ok(supplied: str, current: Any) -> bool:
    """True when a supplied (already-unquoted) ``If-Match`` value matches the current version."""
    return _normalise(str(supplied)) == _normalise(str(current))
