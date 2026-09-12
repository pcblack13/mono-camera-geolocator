"""``KmlImportService`` — match uploaded KML placemarks to GCPs and adjust them.

The inverse of the KML export, and deliberately the *only* inverse: a placemark can
**move an existing GCP** and can do nothing else. See ``app.schemas.imports`` for the wire
shapes and the reasons behind each field.

★ **WHY AN IMPORT CANNOT CREATE A GCP.** ``gcps.pixel_x``/``pixel_y`` are ``NOT NULL``
(``app.models.gcp``). A GCP is a *pairing* — an image pixel bound to a ground coordinate —
and a placemark carries only the ground half. There is no pixel to write and no honest way
to invent one, so an unmatched placemark is reported, never absorbed. This is the same rule
that makes the whole product trustworthy: a record exists only when the observation behind
it exists.

★ **WHAT A ROUND TRIP THROUGH SOMEONE ELSE'S VIEWER DOES AND DOES NOT ESTABLISH.** The
operator opened our KML in a program of their choosing, looked at imagery this system never
saw, moved a marker, and saved. That is a real act of survey judgement and it is worth
recording — it is *their* observation, which is the same standing as a click on our own map.
What it does not do is give the server new grounds for an *accuracy* claim: the horizontal
CE90 on the record was derived from a known provider's GSD and pointing precision
(``gis.accuracy``), and nothing in an imported file supports recomputing it. So the existing
accuracy columns are left exactly as they are, ``manually_adjusted`` and
``adjustment_offset_m`` record that a human moved the point and by how far, and an imported
altitude is written with a **NULL** vertical error bar. Every one of those is the honest
answer rather than the flattering one.

★ **NO PRODUCER SNIFFING.** This service never asks which program wrote the file, and
there is no field in which it could record an answer. ``docs/legal/imagery-terms.md`` §1
excludes a particular vendor's globe as an *imagery provider* — we do not fetch its tiles or
call its endpoints, and reading an OGC-standard file the operator hands us is not that. The
absence of producer detection is what keeps the two things from being confused: there is no
code path here that treats one source differently from another, because the service cannot
tell them apart and must not pretend to.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Sequence

from gis.errors import ImportParseError as GisImportParseError
from gis.geometry import great_circle_distance_m
from gis.imports import PlacemarkRecord, read_kml_bytes
from gis.types import LonLat

from app.core.exceptions import ImportFileChanged, ValidationError
from app.db.repositories.gcps import GcpRepository
from app.models.gcp import GCP
from app.schemas.imports import (
    KmlImportApplyRequest,
    KmlImportApplyResponse,
    KmlImportMatch,
    KmlImportPreview,
    KmlImportSkipped,
    KmlImportUnmatched,
)

__all__ = ["KmlImportService", "NO_OP_THRESHOLD_M"]

_log = logging.getLogger("app.services.kml_import")

NO_OP_THRESHOLD_M: Final[float] = 0.001
"""Below this, a match is treated as "did not move" and is not written (1 mm).

★ Not a tolerance for *survey* purposes — it is a float-identity guard. Exporting a
coordinate rounds it to ``LONLAT_DECIMALS``, so re-importing our own untouched file yields
positions that differ from the stored ones only in the digits the writer dropped. Without
this floor, a round trip that changed nothing would mark every GCP ``manually_adjusted``
and stamp a fictitious ``adjustment_offset_m`` on it, corrupting the one flag that tells a
downstream reader a human intervened. 1 mm is far below any imagery GSD, so it can never
swallow a real edit.
"""

#: Altitude modes under which a placemark's third ordinate is a real height claim.
#:
#: ★ ``clampToGround`` means "put this on the terrain, whatever the terrain is" — the
#: number beside it is ignored by the viewer that rendered it and asserts nothing. Writing
#: it into ``gcps.elevation_m`` would turn a display instruction into a survey elevation.
#: ``relativeToGround`` is an offset from an unstated surface, which we equally cannot
#: resolve. Absent mode is accepted: plenty of tools omit it while writing a real altitude,
#: and KML's own default applies only to rendering.
_ABSOLUTE_ALTITUDE_MODES: Final[frozenset[str]] = frozenset({"absolute"})

_IMPORTED_ELEVATION_SOURCE: Final[str] = "manual"
"""``gcps.elevation_source`` for a height the operator supplied from outside the system.

The vocabulary is fixed by ``gis.elevation.base`` — ``local_dem|copernicus_dem|srtm|exif|
manual`` — and ``manual`` is exactly right: a human asserted this number. There is
deliberately no source value naming an external viewer, and adding one would be a claim
about provenance that this service is in no position to make.
"""


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An existing GCP with its position already decoded, ready to compare against."""

    gcp: GCP
    lon: float
    lat: float


class KmlImportService:
    """Preview and apply a KML/KMZ placemark import against one project's GCPs.

    Args:
        gcps: The GCP repository. Position writes go through ``adjust`` so the original
            answer is preserved by the same ``COALESCE`` every other adjustment uses.
    """

    def __init__(self, gcps: GcpRepository) -> None:
        self._gcps = gcps

    # ── preview ───────────────────────────────────────────────────────────────

    async def preview(
        self, *, project_id: uuid.UUID, data: bytes, filename: str | None = None
    ) -> KmlImportPreview:
        """Parse ``data`` and report what an apply would do. **Writes nothing.**

        Raises:
            ValidationError: the file could not be parsed at all.
        """
        result = self._read(data)
        candidates = await self._candidates(project_id)
        matched, unmatched = self._match(result.placemarks, candidates)

        return KmlImportPreview(
            filename=filename,
            document_name=result.document_name,
            matched=matched,
            unmatched=unmatched,
            skipped=[
                KmlImportSkipped(placemark_name=s.name, reason=s.reason) for s in result.skipped
            ],
            untouched_gcp_count=len(candidates) - len(matched),
            moved_count=sum(1 for m in matched if m.offset_m >= NO_OP_THRESHOLD_M),
            exceeds_accuracy_count=sum(1 for m in matched if m.exceeds_accuracy),
        )

    # ── apply ─────────────────────────────────────────────────────────────────

    async def apply(
        self,
        *,
        project_id: uuid.UUID,
        data: bytes,
        body: KmlImportApplyRequest,
        filename: str | None = None,
    ) -> KmlImportApplyResponse:
        """Commit the moves ``data`` implies.

        Re-parses rather than trusting a cached preview, then checks the parse against
        ``expected_match_count`` so a file that changed under the operator is refused.

        Raises:
            ValidationError: the file could not be parsed at all.
            ImportFileChanged: the match count disagrees with what was previewed (409).
        """
        result = self._read(data)
        candidates = await self._candidates(project_id)
        matched, unmatched = self._match(result.placemarks, candidates)

        expected = body.expected_match_count
        if expected is not None and expected != len(matched):
            raise ImportFileChanged(
                f"This file now matches {len(matched)} GCP(s); the preview you confirmed "
                f"showed {expected}. Preview it again before applying."
            )

        note = body.note or self._default_note(filename, result.document_name)

        adjusted: list[uuid.UUID] = []
        elevation_written = 0
        unchanged = 0

        for match in matched:
            if match.offset_m < NO_OP_THRESHOLD_M and not self._elevation_changes(match, body):
                unchanged += 1
                continue

            if match.offset_m >= NO_OP_THRESHOLD_M:
                # ★ Through GcpService's own primitive: original_geom is preserved,
                #   manually_adjusted is set, and adjustment_offset_m is measured by
                #   PostGIS in true ground metres rather than by the estimate below.
                await self._gcps.adjust(
                    match.gcp_id,
                    lon=match.new_lon,
                    lat=match.new_lat,
                    adjustment_note=note,
                )
                adjusted.append(match.gcp_id)

            if body.apply_elevation and self._elevation_changes(match, body):
                await self._gcps.set_elevation(
                    match.gcp_id,
                    elevation_m=match.new_elevation_m,
                    elevation_source=_IMPORTED_ELEVATION_SOURCE,
                    # ★ NULL, always. See the module docstring: an imported height has no
                    #   error bar this system can derive, and 0 would be a lie.
                    elevation_ce90_m=None,
                )
                elevation_written += 1
                if match.gcp_id not in adjusted:
                    adjusted.append(match.gcp_id)

        _log.info(
            "kml_import.applied project=%s adjusted=%d elevation=%d unchanged=%d "
            "unmatched=%d skipped=%d",
            project_id,
            len(adjusted),
            elevation_written,
            unchanged,
            len(unmatched),
            len(result.skipped),
        )

        return KmlImportApplyResponse(
            adjusted_gcp_ids=adjusted,
            elevation_written_count=elevation_written,
            unchanged_count=unchanged,
            unmatched_count=len(unmatched),
            skipped_count=len(result.skipped),
        )

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _read(data: bytes):
        """Parse bytes, translating the gis error into the domain's 422."""
        try:
            return read_kml_bytes(data)
        except GisImportParseError as exc:
            raise ValidationError(f"Could not read this file as KML or KMZ: {exc}") from exc

    async def _candidates(self, project_id: uuid.UUID) -> list[_Candidate]:
        rows = await self._gcps.list_for_project(project_id)
        return [_Candidate(gcp=gcp, lon=lon, lat=lat) for gcp, lon, lat in rows]

    @staticmethod
    def _elevation_changes(match: KmlImportMatch, body: KmlImportApplyRequest) -> bool:
        """Whether this match would write a different elevation than the row already has."""
        if not body.apply_elevation or match.new_elevation_m is None:
            return False
        if match.elevation_note is not None:  # the altitude was rejected as non-absolute
            return False
        return match.new_elevation_m != match.current_elevation_m

    @staticmethod
    def _default_note(filename: str | None, document_name: str | None) -> str:
        """Name the file the move came from, so the provenance survives in the record."""
        origin = filename or document_name
        return (
            f"Position imported from {origin}" if origin else "Position imported from a KML file"
        )

    def _match(
        self, placemarks: Sequence[PlacemarkRecord], candidates: Sequence[_Candidate]
    ) -> tuple[list[KmlImportMatch], list[KmlImportUnmatched]]:
        """Tie placemarks to GCPs, most trustworthy strategy first.

        ★ **A GCP is claimed at most once.** Two placemarks that both resolve to the same
        point would otherwise apply in file order, and the last one would silently win.
        The second is reported unmatched with the collision named, so the operator fixes
        their file rather than discovering later that half their edits vanished.

        ★ **An ambiguous label matches nothing.** Codes are unique per image, not per
        project, and names are free text — so a label shared by two GCPs identifies
        neither. Picking one would be a coin flip written into the deliverable.
        """
        by_id = {str(c.gcp.id): c for c in candidates}
        by_code = self._unique_index(candidates, lambda c: c.gcp.code)
        by_name = self._unique_index(candidates, lambda c: c.gcp.name)

        matched: list[KmlImportMatch] = []
        unmatched: list[KmlImportUnmatched] = []
        claimed: set[uuid.UUID] = set()

        for placemark in placemarks:
            candidate, strategy, reason = self._resolve(placemark, by_id, by_code, by_name)

            if candidate is None:
                unmatched.append(
                    KmlImportUnmatched(
                        placemark_name=placemark.name,
                        lat=placemark.lat,
                        lon=placemark.lon,
                        elevation_m=placemark.elevation_m,
                        reason=reason,
                    )
                )
                continue

            if candidate.gcp.id in claimed:
                unmatched.append(
                    KmlImportUnmatched(
                        placemark_name=placemark.name,
                        lat=placemark.lat,
                        lon=placemark.lon,
                        elevation_m=placemark.elevation_m,
                        reason=(
                            f"an earlier placemark in this file already matched "
                            f"{candidate.gcp.code or candidate.gcp.id}"
                        ),
                    )
                )
                continue

            claimed.add(candidate.gcp.id)
            matched.append(self._to_match(placemark, candidate, strategy))

        return matched, unmatched

    @staticmethod
    def _unique_index(
        candidates: Sequence[_Candidate], key: Callable[[_Candidate], str | None]
    ) -> dict[str, _Candidate | None]:
        """Index by a label, mapping any duplicated label to None.

        None is the "ambiguous" marker: present in the index (so we know the label exists
        in this project and can say so) but unusable for a match.
        """
        index: dict[str, _Candidate | None] = {}
        for candidate in candidates:
            label = key(candidate)
            if not label:
                continue
            index[label] = None if label in index else candidate
        return index

    @staticmethod
    def _resolve(
        placemark: PlacemarkRecord,
        by_id: dict[str, _Candidate],
        by_code: dict[str, _Candidate | None],
        by_name: dict[str, _Candidate | None],
    ) -> tuple[_Candidate | None, str, str]:
        """Return ``(candidate, strategy, reason_when_none)`` for one placemark."""
        # 1. The id we exported, round-tripped in ExtendedData. A fact, not a guess.
        raw_id = (placemark.extended_data.get("gcp_id") or "").strip()
        if raw_id:
            hit = by_id.get(raw_id)
            if hit is not None:
                return hit, "gcp_id", ""
            return (
                None,
                "",
                f"carries gcp_id {raw_id} which is not a GCP in this project",
            )

        # 2. Labels, most specific first. Each must be unambiguous within the project.
        #
        # ★ THE PLACEMARK'S <name> IS TRIED AGAINST THE **CODE** INDEX BEFORE THE NAME ONE.
        #   ``kml_writer._placemark`` writes ``<name>`` as ``code or label or gcp_id``, and a
        #   foreign file has no ExtendedData at all — so for both our own exports and a file
        #   a surveyor typed by hand, the visible label of a point is normally its code. A
        #   resolver that only checked ``extended_data['code']`` would match nothing in the
        #   exact case this feature exists to serve.
        placemark_label = (placemark.name or "").strip()
        for index, strategy, label in (
            (by_code, "code", (placemark.extended_data.get("code") or "").strip()),
            (by_code, "code", placemark_label),
            (by_name, "name", placemark_label),
        ):
            if not label or label not in index:
                continue
            hit = index[label]
            if hit is None:
                return (
                    None,
                    "",
                    f"{strategy} {label!r} matches more than one GCP in this project",
                )
            return hit, strategy, ""

        return (
            None,
            "",
            "no gcp_id, code, or name in this file matches a GCP in this project",
        )

    @staticmethod
    def _to_match(
        placemark: PlacemarkRecord, candidate: _Candidate, strategy: str
    ) -> KmlImportMatch:
        """Build the preview row, including the movement and whether it is unusual."""
        gcp = candidate.gcp

        # ★ Haversine, not the projected measure: this number is a PREVIEW. The value
        #   written to adjustment_offset_m is computed by PostGIS on the geography column
        #   during the adjust. The two agree to well under a millimetre at survey scale,
        #   and using the cheap one here keeps a 500-point preview a single query.
        offset_m = great_circle_distance_m(
            LonLat(lon=candidate.lon, lat=candidate.lat),
            LonLat(lon=placemark.lon, lat=placemark.lat),
        )

        total_ce90 = gcp.accuracy_total_ce90_m

        elevation_note: str | None = None
        if placemark.elevation_m is not None:
            mode = (placemark.altitude_mode or "").strip().lower()
            if mode and mode not in _ABSOLUTE_ALTITUDE_MODES:
                elevation_note = (
                    f"altitude ignored: altitudeMode is {placemark.altitude_mode!r}, so the "
                    "value positions the marker for display rather than asserting a height"
                )

        return KmlImportMatch(
            gcp_id=gcp.id,
            placemark_name=placemark.name,
            code=gcp.code,
            matched_by=strategy,
            current_lat=candidate.lat,
            current_lon=candidate.lon,
            new_lat=placemark.lat,
            new_lon=placemark.lon,
            offset_m=offset_m,
            current_total_ce90_m=total_ce90,
            exceeds_accuracy=total_ce90 is not None and offset_m > total_ce90,
            current_elevation_m=gcp.elevation_m,
            new_elevation_m=placemark.elevation_m,
            elevation_note=elevation_note,
        )
