"""``app.schemas`` — the WIRE contract (§6).

★ **L9 IS ABSOLUTE: snake_case on the wire, in Python, AND in TypeScript.** No
alias generator. No case-mapping layer. ``frontend/src/types/**`` (IU-23) mirrors
these field-for-field; any drift is a bug.

The package's only two field-level aliases are **named, single, and forced by the
Python language**, not by a convention:

===============  ==========================  ==================================
Wire key         Python attribute            Declared in
===============  ==========================  ==================================
``metadata``     ``metadata`` (ORM: ``meta``) ``common.META_FIELD``
``class``        ``class_``                  ``semantic.CLASS_FIELD``
===============  ==========================  ==================================

L9 forbids an alias *generator* — which renames every field invisibly and creates
a second source of truth — not an exemption declared once at the one place a
reserved word left no choice.

Import rules
------------
§10.2: ``app.schemas`` may import **``pydantic`` and ``app.core.constants``**.
Not ``sqlalchemy``, not ``app.models``, not ``ai_engine``, not ``gis``, not
``cv2``. Consequently:

- The ``Settings``-dependent checks this layer cannot make are exposed as
  methods for the service layer to call with the live value — see
  ``matching.MatchOptions.check_timeout_against``.
- ``PostGIS``-dependent checks (``ST_IsValid``, area bounds, in-image-bounds)
  live in the services. A schema cannot know how wide an image is.
- Domain errors (``400 EMPTY_PATCH``) are raised by the router off
  ``common.PatchModel.is_empty``; a bare ``ValueError`` here would surface as a
  422 and the contract says 400.

The module DAG
--------------
§6.2 states: *"Import direction is strictly one-way: common / enums / errors <-
everything else. No schema module imports another domain schema module."* The
stated reasons are (a) keep the graph **acyclic** and (b) let any schema be
imported into a Celery worker without dragging in FastAPI.

Three edges between domain modules are **unavoidable and are declared here**
rather than worked around. Each is acyclic, each is FastAPI-free, and in each the
alternative was worse than the edge:

- ``image -> job``       — ``ImageUploadAccepted`` is *literally*
  ``{image: ImageRead, job: JobRead}`` (§6.2). Hoisting ``JobRead`` into
  ``common`` to dodge the import would move the whole job vocabulary into the
  shared module and mean nothing.
- ``batch -> matching``  — ``BatchCreate.search_hint``/``options`` **are** a
  match request's parameters (§6.2). Re-declaring them would be two sources of
  truth for one set of defaults.
- ``revision -> annotation`` — ``RevisionSnapshot.annotations: list[AnnotationRead]``
  (§6.2). This edge is why §6.2 moved ``RevisionSummary`` **into ``common``**:
  ``annotation`` needs the summary, ``revision`` needs ``AnnotationRead``, and
  without the move the pair would be a genuine **cycle**. The move is the
  contract already resolving this exact class of problem, in this exact pair —
  which is what tells us the rule means *acyclic*, not *edgeless*.

The resulting graph, and it is a DAG::

    enums   errors   common          (leaves; import nothing from this package)
      |        |        |
      +--------+--------+
               |
      +--------+---------+---------+----------+-----------+---------+
      |        |         |         |          |           |         |
    health  capabilities project  imagery  suggestion  semantic   pose
                                                                  export
               job  ->  image
          annotation ->  revision
            matching ->  batch
                             gcp        (leaf consumer)

Flagged in IU-17's report so IU-21/IU-22 are not surprised by them.

SCOPE.md
--------
★★ **The automatic matching engine is DEFERRED** (SCOPE.md §1). The schemas for it
stay **complete and honest** — the seam must be real, not decorative, and
re-enabling it must cost zero changes outside ``ai_engine/`` (SCOPE.md §7). What
changes is the *response*: those endpoints return ``501`` with the uniform
envelope and ``errors.DeferredFeature`` — never a 404, never a fabricated
coordinate. Build one with :func:`app.schemas.errors.deferred_envelope`.

★★ **Manual GCP mode is the product** (SCOPE.md §5). Its schemas — ``GcpSource``,
``SurveyorConfidence``, ``GcpManualCreate``, ``GcpCorrespondenceUpdate``, and
``source``/``declared_confidence`` on the GCP reads — are **added by this unit**
because §6 predates the ruling. They are flagged in IU-17's report.
"""

from __future__ import annotations

from .common import (
    ApiModel,
    BBox,
    CountResponse,
    DeletedResponse,
    GeoJsonFeature,
    GeoJsonFeatureCollection,
    GeoJsonGeometry,
    GeoJsonLineString,
    GeoJsonMultiPolygon,
    GeoJsonPoint,
    GeoJsonPolygon,
    IdResponse,
    LatLon,
    LatLonAlt,
    ListParams,
    Page,
    PaginationParams,
    PatchModel,
    PixelBox,
    PixelXY,
    ResultRef,
    RevisionSummary,
    SortParams,
    UNSET,
    Unset,
    WarningItem,
)
from .errors import (
    DeferredFeature,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    deferred_envelope,
)

__all__ = [
    # common
    "UNSET",
    "ApiModel",
    "BBox",
    "CountResponse",
    "DeletedResponse",
    "GeoJsonFeature",
    "GeoJsonFeatureCollection",
    "GeoJsonGeometry",
    "GeoJsonLineString",
    "GeoJsonMultiPolygon",
    "GeoJsonPoint",
    "GeoJsonPolygon",
    "IdResponse",
    "LatLon",
    "LatLonAlt",
    "ListParams",
    "Page",
    "PaginationParams",
    "PatchModel",
    "PixelBox",
    "PixelXY",
    "ResultRef",
    "RevisionSummary",
    "SortParams",
    "Unset",
    "WarningItem",
    # errors
    "DeferredFeature",
    "ErrorBody",
    "ErrorDetail",
    "ErrorEnvelope",
    "deferred_envelope",
]

# ★ Deliberately NOT a star-barrel over the domain modules.
#
# Re-exporting every schema here would make `import app.schemas` load all
# nineteen modules, which turns the DAG above from a checkable property into a
# comment: an accidental `annotation -> revision` import would never fail, it
# would just be absorbed by the barrel's own ordering. It would also make
# `from app.schemas import X` the path of least resistance for IU-21, and the
# routers are the exact layer that should be naming which module it took a type
# from.
#
# `common` and `errors` ARE re-exported because they are the leaves every module
# already depends on and §6.2 names them as the shared vocabulary — importing
# them costs nothing new. Domain schemas are imported from their own module:
#
#     from app.schemas.gcp import GcpRead, GcpManualCreate
#     from app.schemas.job import JobRead
