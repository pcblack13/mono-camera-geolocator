"""The export-layer DTO (CONTRACT.md §4.21).

``GcpRecord`` is **not** the ORM row and **not** the pydantic schema. It is the flat,
framework-free value a writer consumes. ``backend.services.export_service`` assembles the
list once, from the database, and hands it over; **no writer in this package ever imports
the ORM, opens a session, or touches the network** (CONTRACT.md §13.1, IU-13 — asserted by
an AST sweep over this package).

That indirection is what makes every writer trivially unit-testable offline: a test builds
``GcpRecord`` objects by hand and never needs Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["GcpRecord"]


@dataclass(frozen=True, slots=True)
class GcpRecord:
    """One ground control point, flattened for export.

    Field names and types are normative (CONTRACT.md §4.21). ``lon``/``lat`` are always
    EPSG:4326 degrees, longitude first — the writers that support a projected
    ``target_srid`` reproject from here; the ones that do not say so in their warnings.

    ``horizontal_accuracy_m`` is **an alias of** ``total_ce90_m``, serialised and never
    stored (CONTRACT.md §5.6). It exists because the client brief names it and the wire
    keeps it; it is not a second measurement, and it must never disagree with
    ``total_ce90_m``.

    Attributes:
        gcp_id: The GCP's UUID, as a string.
        code: Short operator code, e.g. ``'GCP01'``. ``None`` when unassigned.
        label: Human label. ``None`` when unassigned.
        lon: Longitude, EPSG:4326 degrees.
        lat: Latitude, EPSG:4326 degrees.
        elevation_m: Orthometric height in metres, or ``None`` when no elevation
            producer ran. ★ ``None`` is exported as an EXPLICIT empty value, never as
            ``0``, never as the string ``"None"``, and never by dropping the field — an
            absent third coordinate must be visibly absent (§4.27).
        elevation_source: ``'local_dem'``/``'copernicus_dem'``/``'srtm'``/``'exif'``/
            ``'manual'``, or ``None``. Invariant: ``(elevation_m is None) ==
            (elevation_source is None)`` — the source may never name a producer that did
            not run.
        pixel_col: Column in ORIGINAL image pixel space (not viewer space).
        pixel_row: Row in ORIGINAL image pixel space.
        satellite_pixel_x: Fix location in mosaic pixel space, x.
        satellite_pixel_y: Fix location in mosaic pixel space, y.
        confidence: ``0..100``. ★ In this build's manual mode this is a SURVEYOR-DECLARED
            judgement, never a computed score (SCOPE.md §5). Writers report the basis
            alongside the number rather than letting a reader assume.
        source: ``'manual'`` | ``'direct_georeference'`` | ``'automatic'`` | ``'unknown'``
            — who produced THIS coordinate, per row (SCOPE.md §5). ★ This is the per-GCP
            twin of :attr:`ExportProvenance.source`: the context carries the export's
            dominant method, but a project export can span a georeferenced upload (exact)
            and a hand-annotated photo (manual) at once, so the row that is measured must
            never borrow the label of the row that is inferred. A writer prefers this value
            and falls back to the context provenance only when it is ``'unknown'``.
        horizontal_accuracy_m: Alias of ``total_ce90_m``. ``None`` only if a producer
            genuinely left it unset.
        total_ce90_m: ``sqrt(relative² + georef²)`` — THE headline accuracy number, true
            ground metres.
        relative_ce90_m: Our own fit's contribution, CE90 true metres.
        georef_ce90_m: The imagery provider's absolute georeferencing error, CE90 metres.
        accuracy_dominant_term: ``'match'``/``'georeference'``/``'landmark_click'``/
            ``'rectification'`` — which term the total is limited by. The single most
            useful thing a surveyor can read.
        residual_px: ``‖H·image_px − satellite_px‖`` for this point, or ``None`` when
            there was no direct fix. ``None`` and ``0.0`` are different claims.
        manually_adjusted: True when a human moved this point after it was placed.
        adjustment_offset_m: How far it moved, in true metres. ``None`` when not adjusted.
        landmark_kind: The landmark class this GCP was placed on, when known.
    """

    gcp_id: str
    code: str | None
    label: str | None
    lon: float
    lat: float
    elevation_m: float | None
    pixel_col: float
    pixel_row: float
    satellite_pixel_x: float
    satellite_pixel_y: float
    confidence: float
    source: str
    horizontal_accuracy_m: float | None
    total_ce90_m: float
    relative_ce90_m: float
    georef_ce90_m: float
    accuracy_dominant_term: str
    residual_px: float | None
    manually_adjusted: bool
    adjustment_offset_m: float | None
    landmark_kind: str | None
    elevation_source: str | None
