"""Pagination and sorting parameter objects (CONTRACT.md §6.2, §6.4).

**Offset, not cursor** — and §6.2 records why: cursor pagination is strictly better
for large, hot, append-heavy collections, and LandExplorer has none. A project holds
tens of images; an image holds tens to low-hundreds of annotations; a match produces
at most 25 results. Offset over a ``(image_id, id DESC)`` index at those cardinalities
is free, and ``total`` is what the UI actually renders ("1,274 events") — which
cursor pagination cannot cheaply produce.

Framework-free: plain dataclasses, no FastAPI. ``api.deps`` builds these from
``Query(...)`` and hands them to services, which must stay importable in a worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Final, Sequence

from app.core.exceptions import InvalidSortField, ParamConflict

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_SORT_KEYS",
    "PaginationParams",
    "SortKey",
    "SortParams",
]

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
MAX_SORT_KEYS: Final = 3

#: The tiebreaker silently appended to every sort. See ``SortParams.stabilised``.
DEFAULT_TIEBREAKER: Final = "id"


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """A validated ``limit``/``offset`` pair."""

    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be in [1, {MAX_LIMIT}], got {self.limit}")
        if self.offset < 0:
            raise ValueError(f"offset must be >= 0, got {self.offset}")


@dataclass(frozen=True, slots=True)
class SortKey:
    """One sort term: a whitelisted field and a direction."""

    field: str
    descending: bool = False

    def __str__(self) -> str:
        return f"-{self.field}" if self.descending else self.field


@dataclass(frozen=True, slots=True)
class SortParams:
    """A parsed, whitelisted, stabilised ``?sort=`` list.

    ``?sort=`` is comma-separated, a leading ``-`` means descending, at most three
    keys, and every key must be on the endpoint's whitelist.
    """

    keys: tuple[SortKey, ...] = ()

    @classmethod
    def parse(
        cls,
        raw: str | None,
        *,
        allowed: Collection[str],
        default: Sequence[SortKey] | None = None,
        max_keys: int = MAX_SORT_KEYS,
    ) -> SortParams:
        """Parse a raw ``?sort=`` value against an endpoint's whitelist.

        Args:
            raw: The raw query value, e.g. ``"-created_at,name"``. None/empty => default.
            allowed: The fields this endpoint permits sorting on.
            default: The sort to use when none was requested.
            max_keys: Cap on sort terms. Each one is an index the planner must
                satisfy; an unbounded list is a free full-table sort for any caller.

        Returns:
            The parsed params — **not** yet stabilised. Call ``stabilised()`` at the
            repository, which is the layer that knows the tiebreaker column exists.

        Raises:
            InvalidSortField: an unknown field, a duplicate, or too many keys. The
                allowed set travels in ``details`` — an error that says only
                "invalid" makes the client guess.
        """
        if not raw or not raw.strip():
            return cls(keys=tuple(default or ()))

        allowed_set = set(allowed)
        keys: list[SortKey] = []
        seen: set[str] = set()

        for term in (t.strip() for t in raw.split(",")):
            if not term:
                continue
            descending = term.startswith("-")
            field = term[1:] if descending else term
            field = field.strip()

            if field not in allowed_set:
                raise InvalidSortField(
                    f"Cannot sort by {field!r}.",
                    details=_sort_detail(field, sorted(allowed_set), "sort.unknown_field"),
                )
            if field in seen:
                # Two directions for one column is a contradiction the DB would
                # silently resolve by taking the first. Say so instead.
                raise InvalidSortField(
                    f"Field {field!r} appears more than once in sort.",
                    details=_sort_detail(field, sorted(allowed_set), "sort.duplicate_field"),
                )
            seen.add(field)
            keys.append(SortKey(field=field, descending=descending))

        if len(keys) > max_keys:
            raise InvalidSortField(
                f"At most {max_keys} sort keys are allowed, got {len(keys)}.",
                details=_sort_detail(raw, sorted(allowed_set), "sort.too_many_keys"),
            )

        return cls(keys=tuple(keys))

    def stabilised(self, tiebreaker: str = DEFAULT_TIEBREAKER) -> SortParams:
        """Append ``tiebreaker ASC`` unless it is already a sort key.

        ★ Not optional, and invisible to the client. Offset pagination over
        equal-valued rows — 40 GCPs all at ``confidence = 100`` — **duplicates and
        drops rows across pages** without a total order, because the database is free
        to return ties in any order and will happily return a different one for page 2
        than it did for page 1. The surveyor sees a GCP twice and never sees another,
        and nothing anywhere reports an error.
        """
        if any(key.field == tiebreaker for key in self.keys):
            return self
        return SortParams(keys=(*self.keys, SortKey(field=tiebreaker, descending=False)))

    @property
    def is_empty(self) -> bool:
        return not self.keys

    def __str__(self) -> str:
        return ",".join(str(k) for k in self.keys)


def _sort_detail(value: str, allowed: list[str], type_: str) -> list:
    """Build the ``details`` payload for a sort error.

    Returns plain dicts, not ``ErrorDetail`` instances: ``app.core`` may not import
    ``app.schemas`` (§10.2 — it would invert the layer stack), and pydantic validates
    these into ``ErrorDetail`` at the handler anyway, so the dict is the honest
    intermediate rather than a compromise.
    """
    return [
        {
            "loc": ["query", "sort"],
            "msg": f"Allowed sort fields: {', '.join(allowed)}",
            "type": type_,
            "input": value,
        }
    ]


def reject_param_conflict(*, offset: int | None, before_id: int | None) -> None:
    """Enforce the one documented offset/keyset exception (§6.2).

    ``GET /images/{id}/annotation-versions`` accepts ``before_id`` to switch into
    keyset mode for the undo stack's infinite scroll, where ``offset`` would skip
    events as new ones land. The two together are meaningless — they describe
    different pages — so it is a 422 rather than a guess about which one was meant.
    """
    if offset and before_id is not None:
        raise ParamConflict(
            "offset and before_id cannot be combined; before_id selects keyset pagination.",
            details=[
                {
                    "loc": ["query", "before_id"],
                    "msg": "Use either offset or before_id, not both.",
                    "type": "param.conflict",
                    "input": before_id,
                }
            ],
        )
