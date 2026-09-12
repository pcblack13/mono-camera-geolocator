"""``FieldNameMapper`` — the ``.dbf`` 10-character problem (CONTRACT.md §4.21, 40-imagery §8.4).

Shapefile is a 1990s format the industry cannot leave, and its ``.dbf`` attribute table
caps field names at **10 ASCII characters**. That is not an edge case here; it is
load-bearing. Our own schema collides under naive truncation in at least four places:

===========================  ===============  ==========================================
field                        naive ``[:10]``  outcome
===========================  ===============  ==========================================
``elevation_m``              ``elevation``    …
``elevation_source``         ``elevation``    **collides**
``satellite_pixel_x``        ``satellite``    …
``satellite_pixel_y``        ``satellite``    **collides**
``confidence``               ``confidence``   …
``confidence_basis``         ``confidence``   **collides**
``accuracy_relative_ce90_m`` ``accuracy_r``   …
``accuracy_dominant_term``   ``accuracy_d``   (survives, unreadably)
===========================  ===============  ==========================================

A silent collision is the worst outcome: the driver either drops a column or renames it
behind your back, and the surveyor discovers in ArcGIS that ``elevation`` holds the string
``'srtm'``. So this module does three things, in order:

1. **An explicit table first.** A hand-chosen abbreviation beats an algorithmic one —
   ``LON`` is better than ``LON`` ever would have been as ``LONGITUDE``\\ [:10], and
   ``IMG_DATE`` is better than ``IMAGERY_CA``. These are the names a surveyor reads at 6pm.
2. **A deterministic fallback** for anything not in the table: sanitise, truncate, and
   de-duplicate with a numeric suffix that **replaces** trailing characters rather than
   extending past 10.
3. **Tell the user.** Every rename is a warning, and the FULL mapping goes in the zip's
   ``README.txt`` — because the ``.dbf`` has nowhere to record what it did to the
   operator's schema.

Names are uppercase here, and only here. ``.dbf`` field names are conventionally uppercase
and this is a file-format internal, not a wire field — L9's snake_case rule governs the
API and the TypeScript, neither of which can see a ``.dbf``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "DBF_MAX_FIELD_NAME_LEN",
    "DBF_MAX_TEXT_LEN",
    "EXPLICIT_FIELD_NAMES",
    "FieldNameMapper",
    "FieldNameMapping",
]


DBF_MAX_FIELD_NAME_LEN: Final[int] = 10
"""The ``.dbf`` field-name limit. Not negotiable, not configurable, not going away."""

DBF_MAX_TEXT_LEN: Final[int] = 254
"""The ``.dbf`` character-field limit. Attribution strings can exceed it."""


EXPLICIT_FIELD_NAMES: Final[dict[str, str]] = {
    # Identity
    "gcp_id": "GCP_ID",
    "code": "CODE",
    "label": "LABEL",
    # Geometry
    "lon": "LON",
    "longitude": "LON",
    "lat": "LAT",
    "latitude": "LAT",
    "elevation_m": "ELEV_M",
    "elevation_source": "ELEV_SRC",
    # Image space
    "pixel_col": "PIX_COL",
    "pixel_row": "PIX_ROW",
    "satellite_pixel_x": "SAT_PIX_X",
    "satellite_pixel_y": "SAT_PIX_Y",
    # The number and what it means
    "confidence": "CONF",
    "confidence_basis": "CONF_BASIS",
    # Accuracy
    "horizontal_accuracy_m": "HACC_M",
    "total_ce90_m": "CE90_TOT_M",
    "relative_ce90_m": "CE90_REL_M",
    "georef_ce90_m": "CE90_GEO_M",
    "accuracy_dominant_term": "ACC_TERM",
    "residual_px": "RESID_PX",
    "rmse_m": "RMSE_M",
    # Provenance
    "method": "METHOD",
    "source": "SOURCE",
    "coordinate_kind": "COORD_KIND",
    "manually_adjusted": "ADJUSTED",
    "adjustment_offset_m": "ADJ_OFF_M",
    "landmark_kind": "LMK_KIND",
    "provider": "PROVIDER",
    "attribution": "ATTRIB",
    "terms_url": "TERMS_URL",
    "imagery_captured_at": "IMG_DATE",
    "retrieved_at": "RETR_DATE",
    "generated_at": "GEN_DATE",
    "project_name": "PROJECT",
    "image_filename": "IMAGE_FILE",
    "software_version": "SW_VER",
}
"""Hand-chosen ``.dbf`` names.

Every value is ``<= 10`` chars and a legal identifier, and no two DISTINCT fields share a
name — both asserted by the IU-13 suite, because a typo here would silently reintroduce
exactly the collision this table exists to prevent. ``lon``/``longitude`` and
``lat``/``latitude`` deliberately map to the same name: they are aliases for one quantity
and never appear in the same table.
"""


_INVALID_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(frozen=True, slots=True)
class FieldNameMapping:
    """What happened to one field name.

    Attributes:
        original: The name the caller asked for.
        mapped: The ``.dbf``-legal name actually written.
        renamed: True when ``mapped != original.upper()`` — i.e. the operator's schema
            changed and they must be told.
        deduplicated: True when a numeric suffix was needed to break a collision. These are
            the dangerous ones: two distinct fields wanted the same name.
    """

    original: str
    mapped: str
    renamed: bool
    deduplicated: bool


class FieldNameMapper:
    """Map long attribute names to unique, valid, ``<=10``-char ``.dbf`` names.

    Stateless and deterministic: the same input sequence always yields the same mapping,
    which is what lets a test pin the table and a user re-export reproducibly.

    Example:
        >>> mapper = FieldNameMapper()
        >>> mapping, warnings = mapper.map(["elevation_m", "elevation_source"])
        >>> mapping["elevation_m"], mapping["elevation_source"]
        ('ELEV_M', 'ELEV_SRC')
        >>> warnings
        []
    """

    def __init__(self, max_length: int = DBF_MAX_FIELD_NAME_LEN) -> None:
        """Initialise the mapper.

        Args:
            max_length: The field-name cap. Defaults to the ``.dbf`` limit of 10; it is a
                parameter only so the collision logic is testable at a length short enough
                to force collisions on purpose.

        Raises:
            ValueError: If ``max_length < 2`` — below that the de-duplication suffix has
                nowhere to live and the mapper could not guarantee uniqueness.
        """
        if max_length < 2:
            raise ValueError(f"max_length must be >= 2, got {max_length}")
        self.max_length: int = max_length

    def map(self, field_names: Sequence[str]) -> tuple[dict[str, str], list[str]]:
        """Map field names to ``.dbf``-legal names.

        Args:
            field_names: The names, in the order the columns will be written. Order
                matters: the first claimant of a truncated name keeps it, so a stable
                input order gives a stable mapping.

        Returns:
            ``(mapping, warnings)`` where ``mapping`` is ``original -> dbf_name`` and
            ``warnings`` names EVERY rename in prose fit for an API response.

        Raises:
            ValueError: If ``field_names`` contains a duplicate, which is a caller bug the
                mapper must not paper over by silently merging two columns.
        """
        mappings = self.mappings(field_names)
        mapping = {m.original: m.mapped for m in mappings}
        warnings: list[str] = []
        for m in mappings:
            if m.deduplicated:
                warnings.append(
                    f"Shapefile field {m.original!r} was renamed to {m.mapped!r}: its "
                    f"{self.max_length}-character .dbf name collided with another field. "
                    "See README.txt in this archive for the full field-name map."
                )
            elif m.renamed:
                warnings.append(
                    f"Shapefile field {m.original!r} was shortened to {m.mapped!r} "
                    f"(.dbf field names are limited to {self.max_length} characters). "
                    "See README.txt in this archive for the full field-name map."
                )
        return mapping, warnings

    def mappings(self, field_names: Sequence[str]) -> list[FieldNameMapping]:
        """Return the full per-field record of what was renamed and why.

        Args:
            field_names: The names, in column order.

        Returns:
            One :class:`FieldNameMapping` per input, in input order.

        Raises:
            ValueError: On a duplicate input name.
        """
        seen: set[str] = set()
        for name in field_names:
            if name in seen:
                raise ValueError(f"duplicate field name in input: {name!r}")
            seen.add(name)

        results: list[FieldNameMapping] = []
        # Case-insensitive: several .dbf drivers fold case, so two names differing only by
        # case are a collision even though Python would call them distinct.
        taken: set[str] = set()
        for name in field_names:
            candidate = self._candidate(name)
            mapped, deduplicated = self._deduplicate(candidate, taken)
            taken.add(mapped.upper())
            results.append(
                FieldNameMapping(
                    original=name,
                    mapped=mapped,
                    renamed=mapped != name.upper(),
                    deduplicated=deduplicated,
                )
            )
        return results

    def readme_table(self, field_names: Sequence[str]) -> str:
        """Render the full mapping as a fixed-width table for the archive's ``README.txt``.

        ★ This is the only place the truncation is recorded losslessly. The ``.dbf`` itself
        physically cannot hold the original names, so an archive without this table leaves
        the operator to reverse-engineer ``CE90_GEO_M``.

        Args:
            field_names: The names, in column order.

        Returns:
            A plain-text table, newline-terminated.
        """
        mappings = self.mappings(field_names)
        width = max((len(m.original) for m in mappings), default=0)
        width = max(width, len("Original field"))
        lines = [
            f"{'Original field'.ljust(width)}  .dbf name   Note",
            f"{'-' * width}  ----------  ----",
        ]
        for m in mappings:
            if m.deduplicated:
                note = "RENAMED (10-char collision)"
            elif m.renamed:
                note = "shortened to 10 chars"
            else:
                note = ""
            lines.append(f"{m.original.ljust(width)}  {m.mapped.ljust(10)}  {note}".rstrip())
        return "\n".join(lines) + "\n"

    # ── internals ───────────────────────────────────────────────────────────

    def _candidate(self, name: str) -> str:
        """Return the preferred ``.dbf`` name for ``name``, before collision handling."""
        explicit = EXPLICIT_FIELD_NAMES.get(name)
        if explicit is not None and len(explicit) <= self.max_length:
            return explicit
        return self._sanitize(name)[: self.max_length]

    def _sanitize(self, name: str) -> str:
        """Make ``name`` a legal ``.dbf`` identifier: ASCII, alnum + underscore, not
        leading with a digit, never empty."""
        cleaned = _INVALID_CHARS.sub("_", name).upper().strip("_")
        if not cleaned:
            cleaned = "FIELD"
        if cleaned[0].isdigit():
            cleaned = "F" + cleaned
        return cleaned

    def _deduplicate(self, candidate: str, taken: set[str]) -> tuple[str, bool]:
        """Return a name not in ``taken``, and whether a suffix was needed.

        The suffix REPLACES trailing characters rather than extending past the limit —
        ``SOMEFIELDX`` becomes ``SOMEFIELD1``, ``SOMEFIELD2``, … and, once single digits
        run out, ``SOMEFIEL10``. It is bounded: with ``max_length >= 2`` there are always
        at least 10 distinct suffixed forms per stem before the stem itself shortens
        further, and the loop is guaranteed to terminate because the suffix width grows.
        """
        if candidate.upper() not in taken:
            return candidate, False
        index = 1
        while True:
            suffix = str(index)
            if len(suffix) >= self.max_length:
                # Pathological: more collisions than the name length can encode. Fall back
                # to a stem-free name rather than returning a duplicate, which would make
                # the driver silently drop a column.
                stem = "F"
                suffix = str(index)
                trial = (stem + suffix)[: self.max_length]
                if trial.upper() not in taken:
                    return trial, True
                index += 1
                continue
            stem = candidate[: self.max_length - len(suffix)]
            trial = stem + suffix
            if trial.upper() not in taken:
                return trial, True
            index += 1
