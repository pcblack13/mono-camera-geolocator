"""``projects`` — :class:`Project` (CONTRACT.md §5.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    FeatureExtractor,
    FeatureMatcher,
    ImageryProvider,
    RobustEstimator,
    pg_enum,
)
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.album import Album
    from app.models.export import Export
    from app.models.image import Image
    from app.models.job import BatchJob
    from app.models.revision import ProjectRevision

__all__ = ["Project"]


class Project(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A survey project: the owner of images, revisions, batches and exports.

    ★ ``default_provider`` defaults to ``esri_world_imagery`` **at the data layer**, so
    a freshly inserted row is runnable with an empty ``.env`` (L2). A keyed provider is
    never a default anywhere in this system, including here.
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Placeholder until the auth ADR lands (§5.6).
    owner_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Optional area of interest; seeds the search hint at precedence 5.
    aoi: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )
    #: ★ Exporter HINT ONLY — never storage. Reprojection happens in GeoPandas, in
    #: memory. Two stored copies of a geometry are two chances to disagree (§5.2).
    working_srid: Mapped[int | None] = mapped_column(Integer, nullable=True)

    default_provider: Mapped[ImageryProvider] = mapped_column(
        pg_enum(ImageryProvider, "imagery_provider"),
        nullable=False,
        server_default=text("'esri_world_imagery'::imagery_provider"),
    )
    default_extractor: Mapped[FeatureExtractor] = mapped_column(
        pg_enum(FeatureExtractor, "feature_extractor"),
        nullable=False,
        server_default=text("'sift'::feature_extractor"),
    )
    default_matcher: Mapped[FeatureMatcher] = mapped_column(
        pg_enum(FeatureMatcher, "feature_matcher"),
        nullable=False,
        server_default=text("'flann'::feature_matcher"),
    )
    #: ★ The robust-fit METHOD (``RansacConfig.method``), never a registry key (§4.7).
    default_estimator: Mapped[RobustEstimator] = mapped_column(
        pg_enum(RobustEstimator, "robust_estimator"),
        nullable=False,
        server_default=text("'usac_magsac'::robust_estimator"),
    )

    default_search_radius_m: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("1000.0")
    )
    default_search_zoom: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("18")
    )

    tags: Mapped[list[str]] = mapped_column(
        PG_ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    #: ★ attribute ``meta``, column ``metadata`` — ``metadata`` is reserved on
    #: ``DeclarativeBase`` and cannot be an attribute name.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Monotonic per-project revision counter. Bumped with
    #: ``UPDATE projects SET current_revision_seq = current_revision_seq + 1 …
    #: RETURNING current_revision_seq`` inside the same transaction that writes the
    #: revision: that row-level lock **is** the concurrency control for undo/redo.
    current_revision_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )

    images: Mapped[list[Image]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    revisions: Mapped[list[ProjectRevision]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    batch_jobs: Mapped[list[BatchJob]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    exports: Mapped[list[Export]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    #: ★ MANY-TO-MANY. A project may sit in several albums at once — see
    #: :mod:`app.models.album`. ``secondary`` is given as the **table name string** so
    #: this module does not import ``album`` and the two stay free of an import cycle;
    #: SQLAlchemy resolves it against ``Base.metadata`` at mapper configuration.
    #:
    #: ★ **No cascade, deliberately.** An album is a collection, not an owner: deleting
    #: a project removes its membership rows (the FK's ``ON DELETE CASCADE``), and
    #: deleting an album must never touch a project.
    albums: Mapped[list[Album]] = relationship(
        secondary="album_projects",
        back_populates="projects",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_nonblank"),
        CheckConstraint(
            "working_srid IS NULL OR (working_srid BETWEEN 1024 AND 32767)",
            name="working_srid",
        ),
        # ★ 50..50000, matching schemas.matching.SearchHint.radius_m exactly. A project
        # storing 10 would produce a MatchRequest the API rejects with 422 against its
        # own stored default (§5.6).
        CheckConstraint(
            "default_search_radius_m BETWEEN 50 AND 50000", name="search_radius"
        ),
        CheckConstraint("default_search_zoom BETWEEN 10 AND 21", name="search_zoom"),
        # §5.6 asks for "≤20, each ≤50 chars". Only the first half is expressible as a
        # CHECK: the per-element bound needs an aggregate over `unnest(tags)`, and a
        # CHECK may contain neither a subquery nor an aggregate. The element length is
        # enforced in the Pydantic layer (the same place §5.6 puts the annotation
        # in-bounds rule, and for the same reason).
        CheckConstraint(
            "array_length(tags, 1) IS NULL OR array_length(tags, 1) <= 20",
            name="tags_count",
        ),
        CheckConstraint("current_revision_seq >= 0", name="revision_seq_nonneg"),
        Index(
            "ix_projects_owner_active",
            "owner_id",
            text("updated_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_projects_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("ix_projects_aoi", "aoi", postgresql_using="gist"),
        Index("ix_projects_tags", "tags", postgresql_using="gin"),
    )
