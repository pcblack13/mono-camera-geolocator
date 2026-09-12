"""``gcps`` — :class:`GCP`. ★ THE DELIVERABLE (CONTRACT.md §5.6, SCOPE.md §5).

``gcps.geom`` is **the canonical truth** of this entire system (§5.8 step [7]).
Everything after it is serialisation; nothing before it is stored as a coordinate.
**If an export disagrees with the map, the exporter is wrong, not the database.**

★ **Three deviations from §5.6, all forced by SCOPE.md §5 (manual GCP mode), all
widening rather than narrowing** — every INSERT that was legal under §5.6 is still
legal here:

1. ``source`` is **added**. SCOPE.md §5 requires a GCP record whether its coordinate is
   a direct observation or an inference "so an automatic GCP can never be confused with
   an observed one downstream or in an export". §5.6 defines no such column. It is
   ``Text`` + ``CHECK``, not an 18th native enum, because §5.3 is normative that there
   are exactly seventeen (see :class:`app.models.enums.GcpSource`).
2. ``match_result_id`` becomes **nullable**. §5.6 makes it ``NOT NULL`` + ``RESTRICT``,
   because invariant I2 (provenance is total) assumes a homography produced the point.
   A manual GCP has no ``match_results`` row to point at — there was no matching — so
   under ``NOT NULL`` **the product's core interaction is unwritable**. I2 is preserved
   exactly where it applies by ``ck_gcps_automatic_has_provenance``: an *automatic* GCP
   still cannot exist without its evidence, and the ``RESTRICT`` still makes destroying
   that evidence an explicit act.
3. ``satellite_pixel_x``/``satellite_pixel_y`` become **nullable**, for the same reason:
   they are mosaic pixel coordinates, and a manual GCP has no stored mosaic. The map
   click is captured in EPSG:4326 and stored in ``geom`` directly — that *is* the
   observation. ``ck_gcps_automatic_has_provenance`` keeps them mandatory for automatic
   GCPs.

★ **Manual ``confidence`` is SURVEYOR-DECLARED, never computed** (SCOPE.md §5). The
column is unchanged; what changes is who writes it. Reported accuracy for a manual GCP
comes from imagery GSD + click precision via ``gis.accuracy`` — a real, defensible
number — not from a match score.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import GcpSource, GcpStaleReason, pg_enum
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.image import Image
    from app.models.match import MatchResult

__all__ = ["GCP"]


class GCP(UUIDPkMixin, TimestampMixin, Base):
    """A ground control point: a survey coordinate someone may dig, build, or file against.

    **The three FK behaviours are each deliberate and each different.**
    ``image_id CASCADE`` — deleting the photo deletes everything derived from it; there
    is no meaning left. ``landmark_id SET NULL`` — the surveyor may tidy up annotations
    after the fact; **the coordinate they already exported must survive**, orphaned but
    intact, which is exactly why ``pixel_x``/``pixel_y`` are copied onto the GCP.
    ``match_result_id RESTRICT`` — **the load-bearing one.** A GCP is a *claim about the
    world*; the homography is the *evidence*. Allowing the evidence to be deleted while
    the claim persists would let LandExplorer emit a coordinate it cannot justify. It
    also means the 30-day retention job that prunes losing candidates does not need to
    know about GCPs — the FK protects them.
    """

    __tablename__ = "gcps"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    landmark_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: ★ Provenance. Nullable **only** for ``source = 'manual'`` — see the module
    #: docstring. ``RESTRICT`` is unchanged.
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="RESTRICT"),
        nullable=True,
    )

    #: ★ ``manual`` — the surveyor clicked the spot on the satellite map and the
    #: coordinate is a **direct observation**. ``automatic`` — a homography transported
    #: it and the coordinate is an **inference**. Never confusable, by construction.
    #:
    #: Typed ``str`` rather than ``Mapped[GcpSource]``: the column is ``Text``, so the
    #: round trip is a plain string. :class:`~app.models.enums.GcpSource` is the value
    #: vocabulary and — being a ``StrEnum`` — compares equal to what comes back, so
    #: ``gcp.source == GcpSource.MANUAL`` is true without a conversion layer.
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{GcpSource.MANUAL.value}'")
    )

    #: ``'GCP01'``.
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The surveyor's free-text name for the point — the table's "Name" column. Unconstrained
    #: (unlike ``code``); null when unnamed.
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Image pixel space — original full-resolution pixels, y-DOWN, independent of
    #: viewer zoom or brightness/contrast (SCOPE.md §5).
    pixel_x: Mapped[float] = mapped_column(Double, nullable=False)
    pixel_y: Mapped[float] = mapped_column(Double, nullable=False)
    #: ★ The FIX location in **mosaic pixels**: the direct patch/descriptor fix when
    #: ``has_direct_fix``, else ``H · [pixel_x, pixel_y, 1]`` dehomogenised.
    #: NULL for a manual GCP, which has no mosaic.
    satellite_pixel_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    satellite_pixel_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ Makes ``residual_px IS NULL`` distinguishable from ``residual_px = 0``.
    has_direct_fix: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: ★ **THE CANONICAL TRUTH.**
    geom: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    elevation_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ``local_dem|copernicus_dem|srtm|exif|manual|null``.
    elevation_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Vertical CE90 from ``ElevationSample``. ``NULL`` is honest; ``0`` would not be.
    elevation_ce90_m: Mapped[float | None] = mapped_column(Double, nullable=True)

    #: ★ **0–100.** In manual mode this is the surveyor's own deliberate judgement and
    #: is **never** computed (SCOPE.md §5).
    confidence: Mapped[float] = mapped_column(Double, nullable=False)

    #: ★ Our fit, CE90, TRUE metres. For a manual GCP: imagery GSD + click precision.
    accuracy_relative_ce90_m: Mapped[float] = mapped_column(Double, nullable=False)
    #: The provider's contribution — always knowable, since
    #: ``ProviderCapabilities.georef_ce90_m`` is mandatory.
    georef_ce90_m: Mapped[float] = mapped_column(Double, nullable=False)
    #: ★ ``sqrt(relative² + georef²)``. **THE headline number.**
    accuracy_total_ce90_m: Mapped[float] = mapped_column(Double, nullable=False)
    accuracy_semi_major_ce90_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    accuracy_semi_minor_ce90_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: Major-axis bearing, 0 = North, clockwise.
    accuracy_azimuth_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ``match|georeference|landmark_click|rectification``.
    accuracy_dominant_term: Mapped[str] = mapped_column(Text, nullable=False)

    #: ★ ``‖H·image_px − satellite_px‖`` for **this** point. Non-zero only when
    #: ``has_direct_fix``; NULL otherwise.
    residual_px: Mapped[float | None] = mapped_column(Double, nullable=True)

    manually_adjusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ★ The algorithm's answer, **kept forever**.
    original_geom: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    original_satellite_pixel_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    original_satellite_pixel_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    original_confidence: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ``ST_Distance(original_geom, geom)`` — **real metres**, which is the whole reason
    #: storage is ``geography`` and not ``geometry(…,3857)`` (§5.2).
    adjustment_offset_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    adjusted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjusted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    adjustment_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: ★ **Stored**, set by the writer paths — not derived at read time.
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    stale_reason: Mapped[GcpStaleReason | None] = mapped_column(
        pg_enum(GcpStaleReason, "gcp_stale_reason"), nullable=True
    )
    is_included_in_export: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    #: ★ IMAGERY PROVENANCE — which basemap the coordinate was measured against
    #: (provider, cache variant, zoom, tile address, GSD/accuracy epistemic statuses,
    #: imagery-date-known, whether the tile was served from the local cache). Answers
    #: "which imagery was used, at what zoom, was it cached, how trustworthy were its
    #: numbers" long after the click. NULL for pre-existing rows and non-map paths
    #: (GeoTIFF short-circuit) — an absent record is honest, a backfilled one is not.
    reference_imagery: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    image: Mapped[Image] = relationship(back_populates="gcps", lazy="raise")
    landmark: Mapped[Annotation | None] = relationship(
        back_populates="gcps", foreign_keys=lambda: [GCP.landmark_id], lazy="raise"
    )
    match_result: Mapped[MatchResult | None] = relationship(
        back_populates="gcps", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("source IN ('manual', 'automatic')", name="source"),
        # ★ SCOPE.md §5 + invariant I2, expressed exactly where it applies: an inferred
        # coordinate cannot exist without the evidence that inferred it. An *observed*
        # one needs no homography, because nothing was inferred.
        CheckConstraint(
            "source <> 'automatic' OR ("
            " match_result_id   IS NOT NULL AND"
            " satellite_pixel_x IS NOT NULL AND"
            " satellite_pixel_y IS NOT NULL)",
            name="automatic_has_provenance",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence"),
        CheckConstraint("pixel_x >= 0 AND pixel_y >= 0", name="pixel_nonneg"),
        CheckConstraint(
            "code IS NULL OR code ~ '^[A-Za-z0-9_\\-]{1,32}$'", name="code_format"
        ),
        CheckConstraint(
            "elevation_m IS NULL OR elevation_m BETWEEN -500 AND 9000",
            name="elevation_sane",
        ),
        # ★ The source may never name a producer that did not run (§4.27).
        CheckConstraint(
            "(elevation_m IS NULL) = (elevation_source IS NULL)",
            name="elevation_source_consistent",
        ),
        CheckConstraint(
            "accuracy_relative_ce90_m >= 0"
            " AND georef_ce90_m >= 0"
            " AND accuracy_total_ce90_m >= 0"
            " AND (accuracy_semi_major_ce90_m IS NULL OR accuracy_semi_major_ce90_m >= 0)"
            " AND (accuracy_semi_minor_ce90_m IS NULL OR accuracy_semi_minor_ce90_m >= 0)",
            name="accuracy_nonneg",
        ),
        # ★ A quadrature can never be smaller than either leg. This catches a unit or
        # sign slip in `combine_accuracy` at write time, not in a deliverable.
        CheckConstraint(
            "accuracy_total_ce90_m >= greatest(accuracy_relative_ce90_m, georef_ce90_m)",
            name="accuracy_total_ge_parts",
        ),
        CheckConstraint(
            "accuracy_dominant_term IN"
            " ('match', 'georeference', 'landmark_click', 'rectification')",
            name="accuracy_dominant_term",
        ),
        CheckConstraint(
            "has_direct_fix OR residual_px IS NULL", name="residual_iff_direct_fix"
        ),
        CheckConstraint(
            "NOT manually_adjusted OR (adjusted_at IS NOT NULL AND original_geom IS NOT NULL)",
            name="adjustment_complete",
        ),
        CheckConstraint(
            "manually_adjusted OR ("
            " original_geom IS NULL AND"
            " original_satellite_pixel_x IS NULL AND"
            " original_satellite_pixel_y IS NULL AND"
            " original_confidence IS NULL AND"
            " adjustment_offset_m IS NULL AND"
            " adjusted_by IS NULL AND"
            " adjusted_at IS NULL AND"
            " adjustment_note IS NULL)",
            name="no_adjustment_metadata_unless_adjusted",
        ),
        CheckConstraint("(is_stale) = (stale_reason IS NOT NULL)", name="stale_reason"),
        Index(
            "uq_gcps_landmark_match",
            "landmark_id",
            "match_result_id",
            unique=True,
            postgresql_where=text("landmark_id IS NOT NULL"),
        ),
        Index(
            "uq_gcps_image_code",
            "image_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
        Index("ix_gcps_image", "image_id"),
        Index("ix_gcps_match_result", "match_result_id"),
        Index(
            "ix_gcps_landmark",
            "landmark_id",
            postgresql_where=text("landmark_id IS NOT NULL"),
        ),
        # ★ The hottest spatial query in the product.
        Index("ix_gcps_geom", "geom", postgresql_using="gist"),
        Index(
            "ix_gcps_export",
            "image_id",
            text("confidence DESC"),
            postgresql_where=text("is_included_in_export"),
        ),
        Index(
            "ix_gcps_adjusted",
            text("adjusted_at DESC"),
            postgresql_where=text("manually_adjusted"),
        ),
        Index("ix_gcps_stale", "image_id", postgresql_where=text("is_stale")),
        Index("ix_gcps_source", "image_id", "source"),
    )
