"""★★ THE ENUM PARITY TEST — three files, identical values, none importing another.

`CONTRACT.md` §3 makes the separation deliberate::

    backend/app/models/enums.py   -> IU-16   (ORM mirror of the PG types)
    backend/app/schemas/enums.py  -> IU-17   (wire mirror)
    ai_engine/src/ai_engine/types/enums.py -> IU-01  (pure-CV vocabulary)

    "All **separate files with identical values** for the 17 paired enums; none imports
     another; `test_enum_parity.py` asserts all three legs agree via the normative
     `PARITY_MAP` (§5.3)."

They are separate because `ai_engine` may not import `backend` (§10.6 — it would drag in
sqlalchemy and pydantic and make `cd ai_engine && pytest` impossible on this machine), and
because the ORM mirror and the wire mirror answer to different masters. The cost of that
decision is that **nothing but a test keeps them in step**, and a silent divergence between
a PG label and a wire label is a 500 on a real survey job. This file is that test.

★ **It runs on a bare interpreter, today.** sqlalchemy and pydantic are not installed here
(§0.1), so an import-based parity test cannot run on this machine at all. This one parses
the three files with `ast` and imports none of them. See `_astsupport` for the reasoning.

Scope: §5.3's `PARITY_MAP` — 17 pairs, three of them triples — plus the 13 wire-only enums,
which are asserted to be OUT of scope so that a new schema enum must be **deliberately**
bucketed rather than silently unchecked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from _astsupport import REPO_ROOT, enum_members

MODELS_ENUMS: Final[Path] = REPO_ROOT / "backend" / "app" / "models" / "enums.py"
SCHEMAS_ENUMS: Final[Path] = REPO_ROOT / "backend" / "app" / "schemas" / "enums.py"
AI_ENUMS: Final[Path] = REPO_ROOT / "ai_engine" / "src" / "ai_engine" / "types" / "enums.py"
CORE_CONSTANTS: Final[Path] = REPO_ROOT / "backend" / "app" / "core" / "constants.py"


# =============================================================================
# §5.3 PARITY_MAP — NORMATIVE. Transcribed, not invented.
# =============================================================================

#: ``(pg_type, models.enums name, schemas.enums name, ai_engine.types.enums name | None)``
#:
#: ★ Copied verbatim from CONTRACT.md §5.3's table. The `schemas` column is deliberately
#:   NOT always equal to the `models` column — §6.2 names five of them differently
#:   (`ProviderName`, `FeatureDetectorName`, `ExtractorName`, `MatcherName`,
#:   `EstimatorName`). That mismatch is exactly why a naive "same class name in both files"
#:   test could not pair them, and why this table exists.
PARITY_MAP: Final[tuple[tuple[str, str, str, str | None], ...]] = (
    ("job_status", "JobStatus", "JobStatus", None),
    ("job_type", "JobType", "JobType", None),
    ("image_status", "ImageStatus", "ImageStatus", None),
    ("imagery_provider", "ImageryProvider", "ProviderName", None),
    ("annotation_geom_type", "AnnotationGeomType", "AnnotationGeomType", None),
    ("annotation_kind", "AnnotationKind", "AnnotationKind", None),
    ("annotation_op", "AnnotationOp", "AnnotationOp", None),
    ("semantic_class", "SemanticClass", "SemanticClass", "SemanticClass"),
    ("feature_space", "FeatureSpace", "FeatureSpace", None),
    ("feature_detector", "FeatureDetector", "FeatureDetectorName", None),
    ("feature_extractor", "FeatureExtractor", "ExtractorName", None),
    ("feature_matcher", "FeatureMatcher", "MatcherName", None),
    ("robust_estimator", "RobustEstimator", "EstimatorName", "HomographyMethod"),
    ("pose_method", "PoseMethod", "PoseMethod", "PoseMethod"),
    ("export_format", "ExportFormat", "ExportFormat", None),
    ("gcp_stale_reason", "GcpStaleReason", "GcpStaleReason", None),
    ("suggestion_status", "SuggestionStatus", "SuggestionStatus", None),
)

#: §5.3: "The 13 wire-only enums are explicitly OUT OF PARITY SCOPE and the test asserts
#: that too (a new schema enum must be *deliberately* placed in one bucket or the other)."
WIRE_ONLY: Final[frozenset[str]] = frozenset(
    {
        "JobStage",
        "SegmentBackend",
        "SuggestionStrategy",
        "BatchOnError",
        "HealthStatus",
        "ComponentStatus",
        "ThumbnailSize",
        "ImageFormat",
        "HeatmapFormat",
        "Colormap",
        "ViewRegime",
        "QualityFlag",
        "CoordinateFormat",
    }
)

#: Wire-only enums whose **declaration** lives outside `schemas/enums.py`, which re-exports
#: them. §3 gives `core/constants.py` as `JobStage`'s SOLE HOME, while §5.3 lists it as a
#: wire-only schema enum. See `test_re_exported_wire_enums_are_declared_once_and_only_once`.
RE_EXPORTED: Final[dict[str, Path]] = {"JobStage": CORE_CONSTANTS}

#: ★★ A THIRD BUCKET, ADDED BY THIS UNIT. SCOPE.md §5 postdates §5.3's table.
#:
#: SCOPE.md §5 is normative and overrides the contract: *"The GCP records `source = 'manual'`
#: so an automatic GCP can never be confused with an observed one downstream or in an
#: export."* IU-16 and IU-17 both implemented it, so `GcpSource` exists in **both** backend
#: legs — and it is in neither of §5.3's two buckets, because §5.3 was written when the
#: automatic engine was still in scope and there was nothing to distinguish.
#:
#: Left unbucketed it would trip `test_every_backend_enum_is_deliberately_bucketed`, which
#: is that test working: a new paired enum turned up and someone has to rule on it. The
#: ruling: it is **paired** (both legs define it, values must agree) but has **no PG type**,
#: so it is checked for value parity and excluded from the PG-type count.
#:
#: ★ IU-16 and IU-17 DISAGREE IN WRITING about the disposition, and their docstrings say so
#:   explicitly. `test_gcp_source_disposition_conflict` pins the disagreement rather than
#:   papering over it. The VALUES agree, so nothing is broken today.
PAIRED_NO_PG_TYPE: Final[tuple[tuple[str, str, str | None], ...]] = (("GcpSource", "GcpSource", None),)


# =============================================================================
# Parsed once
# =============================================================================


@pytest.fixture(scope="module")
def models_enums() -> dict[str, dict[str, str]]:
    return enum_members(MODELS_ENUMS)


@pytest.fixture(scope="module")
def schemas_enums() -> dict[str, dict[str, str]]:
    return enum_members(SCHEMAS_ENUMS)


@pytest.fixture(scope="module")
def ai_enums() -> dict[str, dict[str, str]]:
    return enum_members(AI_ENUMS)


def test_the_three_enum_files_exist() -> None:
    """Nothing below means anything if a leg is missing."""
    for path in (MODELS_ENUMS, SCHEMAS_ENUMS, AI_ENUMS):
        assert path.is_file(), f"missing enum leg: {path}"


def test_none_of_the_three_legs_imports_another() -> None:
    """★ §3: "separate files with identical values; **none imports another**".

    The moment one leg imports another the parity test becomes a tautology and the real
    constraint — that `ai_engine` never depends on `backend` (§10.6) — quietly dies.
    """
    forbidden = {
        MODELS_ENUMS: ("app.schemas", "ai_engine"),
        SCHEMAS_ENUMS: ("app.models", "ai_engine"),
        AI_ENUMS: ("app.", "backend"),
    }
    for path, bad_prefixes in forbidden.items():
        source = path.read_text(encoding="utf-8")
        for prefix in bad_prefixes:
            assert f"import {prefix}" not in source, f"{path.name} imports {prefix}"
            assert f"from {prefix}" not in source, f"{path.name} imports from {prefix}"


# =============================================================================
# ★ The parity assertions
# =============================================================================


@pytest.mark.parametrize(
    ("pg_type", "models_name", "schemas_name", "ai_name"),
    PARITY_MAP,
    ids=[row[0] for row in PARITY_MAP],
)
def test_enum_parity(
    pg_type: str,
    models_name: str,
    schemas_name: str,
    ai_name: str | None,
    models_enums: dict[str, dict[str, str]],
    schemas_enums: dict[str, dict[str, str]],
    ai_enums: dict[str, dict[str, str]],
) -> None:
    """★★ Every leg of every row of `PARITY_MAP` agrees VALUE-for-VALUE.

    Values, not names: the PG label is the value, and the member name is a Python
    convenience. `ImageryProvider.ESRI_WORLD_IMAGERY` and `ProviderName.ESRI_WORLD_IMAGERY`
    could be spelled differently and still be correct; their `.value`s could not.
    """
    assert models_name in models_enums, f"{models_name} missing from models/enums.py"
    assert schemas_name in schemas_enums, f"{schemas_name} missing from schemas/enums.py"

    models_values = set(models_enums[models_name].values())
    schemas_values = set(schemas_enums[schemas_name].values())

    assert models_values == schemas_values, (
        f"{pg_type}: models.{models_name} and schemas.{schemas_name} disagree.\n"
        f"  only in models:  {sorted(models_values - schemas_values)}\n"
        f"  only in schemas: {sorted(schemas_values - models_values)}"
    )

    if ai_name is None:
        return

    assert ai_name in ai_enums, f"{ai_name} missing from ai_engine/types/enums.py"
    ai_values = set(ai_enums[ai_name].values())
    assert ai_values == models_values, (
        f"{pg_type}: ai_engine.{ai_name} disagrees with models.{models_name}.\n"
        f"  only in ai_engine: {sorted(ai_values - models_values)}\n"
        f"  only in models:    {sorted(models_values - ai_values)}"
    )


@pytest.mark.parametrize(("models_name", "schemas_name", "ai_name"), PAIRED_NO_PG_TYPE)
def test_paired_enums_without_a_pg_type_still_agree(
    models_name: str,
    schemas_name: str,
    ai_name: str | None,
    models_enums: dict[str, dict[str, str]],
    schemas_enums: dict[str, dict[str, str]],
    ai_enums: dict[str, dict[str, str]],
) -> None:
    """★ `GcpSource` — SCOPE.md §5's addition. No PG type, but still two hand-kept mirrors.

    Having no PG type is a reason to skip the *migration*, not a reason to skip *parity*: if
    the wire says `automatic` and the ORM's CHECK constraint says `auto`, every automatic GCP
    is a 500 whenever the engine is re-enabled.
    """
    assert models_name in models_enums, f"{models_name} missing from models/enums.py"
    assert schemas_name in schemas_enums, f"{schemas_name} missing from schemas/enums.py"

    models_values = set(models_enums[models_name].values())
    schemas_values = set(schemas_enums[schemas_name].values())
    assert models_values == schemas_values, (
        f"{models_name}: models and schemas disagree.\n"
        f"  only in models:  {sorted(models_values - schemas_values)}\n"
        f"  only in schemas: {sorted(schemas_values - models_values)}"
    )

    if ai_name is not None:
        assert set(ai_enums[ai_name].values()) == models_values


def test_manual_is_a_gcp_source(models_enums: dict[str, dict[str, str]]) -> None:
    """★ SCOPE.md §5: "Every GCP records `source = 'manual'`". The value is the contract."""
    assert "manual" in set(models_enums["GcpSource"].values())


# =============================================================================
# ★ The bucketing assertion — so a NEW enum cannot be silently unchecked
# =============================================================================


def test_every_backend_enum_is_deliberately_bucketed(
    models_enums: dict[str, dict[str, str]],
    schemas_enums: dict[str, dict[str, str]],
) -> None:
    """★★ §5.3: a new schema enum must be **deliberately** placed in one bucket or the other.

    This is the test that makes the other tests durable. Value parity only checks the rows
    someone remembered to add; this checks that nobody added an enum and forgot. When it
    fails, the fix is a one-line ruling in `PARITY_MAP`, `WIRE_ONLY` or `PAIRED_NO_PG_TYPE`
    — the point is that the ruling is *made*, not that it is made a particular way.
    """
    bucketed_models = {row[1] for row in PARITY_MAP} | {row[0] for row in PAIRED_NO_PG_TYPE}
    bucketed_schemas = (
        {row[2] for row in PARITY_MAP} | WIRE_ONLY | {row[1] for row in PAIRED_NO_PG_TYPE}
    )

    unbucketed_models = set(models_enums) - bucketed_models
    unbucketed_schemas = set(schemas_enums) - bucketed_schemas

    assert not unbucketed_models, (
        f"models/enums.py declares enums in no bucket: {sorted(unbucketed_models)}. "
        "Add each to PARITY_MAP (it mirrors a PG type) or to PAIRED_NO_PG_TYPE."
    )
    assert not unbucketed_schemas, (
        f"schemas/enums.py declares enums in no bucket: {sorted(unbucketed_schemas)}. "
        "Add each to PARITY_MAP (it mirrors a PG type), WIRE_ONLY (it never reaches the "
        "DB) or PAIRED_NO_PG_TYPE."
    )


def test_wire_only_enums_really_are_wire_only(
    models_enums: dict[str, dict[str, str]],
    schemas_enums: dict[str, dict[str, str]],
) -> None:
    """★ The 13 wire-only enums exist on the wire and NOT in the ORM.

    Asserted in both directions. `ViewRegime` is wire-only *on purpose* — §5.6 makes
    `match_results.view_regime` a plain `Text` column because it is diagnostic provenance
    rather than a queried dimension, and it is the field most likely to gain members. If it
    ever appears in `models.enums`, that decision has been quietly reversed.
    """
    for name in sorted(WIRE_ONLY - set(RE_EXPORTED)):
        assert name in schemas_enums, f"{name} is listed wire-only but schemas/enums.py lacks it"
    for name in sorted(WIRE_ONLY):
        assert name not in models_enums, (
            f"{name} is listed wire-only in §5.3 but models/enums.py declares it. Either it "
            "gained a PG type (move it to PARITY_MAP) or the mirror is a mistake."
        )


@pytest.mark.parametrize("name", sorted(RE_EXPORTED))
def test_re_exported_wire_enums_are_declared_once_and_only_once(
    name: str, schemas_enums: dict[str, dict[str, str]]
) -> None:
    """★ §3's SOLE HOME ruling, pinned — and a genuine §5.3-vs-§3 contradiction, resolved.

    §5.3 lists `JobStage` among *"the 13 wire-only enums"*, phrased as though it were a
    schema enum: *"a new **schema** enum must be deliberately bucketed"*. But §3 rules::

        `backend/app/core/constants.py` -> **IU-15**. **THE SOLE HOME** of `JobStage`,
        `STAGES`, `STAGE_WEIGHTS` and the docs_url map — **no enums** (those live in
        IU-16/IU-17). `tasks/progress.py` imports; it does not redeclare.

    Both cannot be followed literally: one puts `JobStage` in `schemas/enums.py`, the other
    forbids it. IU-17 resolved it the right way — `from app.core.constants import JobStage`,
    re-exported in `__all__` and never redeclared — and said so in the module docstring.
    This test pins that resolution, because the failure mode is silent: a second `class
    JobStage(StrEnum)` in `schemas/enums.py` would satisfy §5.3's letter, import cleanly,
    pass every value test, and then drift from `STAGES`/`STAGE_WEIGHTS` the first time a
    stage is added — turning a progress bar into a `KeyError` in a Celery worker.
    """
    home = RE_EXPORTED[name]
    home_source = home.read_text(encoding="utf-8")
    schemas_source = SCHEMAS_ENUMS.read_text(encoding="utf-8")

    assert f"class {name}(" in home_source, f"{name}'s declared home {home.name} no longer declares it"
    assert name not in schemas_enums, (
        f"schemas/enums.py REDECLARES {name}. §3 makes {home.name} its sole home; "
        f"re-export it (`from app.core.constants import {name}`) instead of redeclaring it."
    )
    assert f"import {name}" in schemas_source or f"{name}," in schemas_source, (
        f"schemas/enums.py neither declares nor re-exports {name}; the wire cannot name it."
    )


def test_parity_map_is_the_seventeen_pg_types() -> None:
    """§5.3 counted them: **seventeen**, against v1.0's heading that said 13."""
    assert len(PARITY_MAP) == 17
    assert len({row[0] for row in PARITY_MAP}) == 17, "duplicate pg_type in PARITY_MAP"


def test_three_legged_rows_are_exactly_the_three_the_contract_names() -> None:
    """§5.3 marks exactly three rows "★ 3-leg": `semantic_class`, `robust_estimator`,
    `pose_method`. §13.1 IU-01 names the same three from the other side.
    """
    three_leg = {row[0] for row in PARITY_MAP if row[3] is not None}
    assert three_leg == {"semantic_class", "robust_estimator", "pose_method"}


# =============================================================================
# ★ The recorded cross-unit disagreement
# =============================================================================


def test_gcp_source_disposition_conflict_is_recorded_not_silent() -> None:
    """★★ IU-16 and IU-17 shipped OPPOSITE rulings on `GcpSource`, in writing.

    `models/enums.py`::

        "**Not a PG enum type.** … stored as ``Text`` + ``CHECK``, **not** as an 18th
         native enum, because §5.3 is normative that there are exactly seventeen …
         Consequently it is **out of ``PARITY_MAP`` scope** by construction."

    `schemas/enums.py`::

        "… which makes it a PG enum and a parity enum. IU-16 must mirror it, IU-30 must
         ``CREATE TYPE gcp_source``, and IU-22 must add the ``PARITY_MAP`` row."

    **Nothing is broken today**: the values agree, and `models/gcp.py` stores `source` as
    `Text` + `CHECK`, which a `StrEnum` on the wire serialises to correctly. The live risk is
    IU-17's *instruction*: if IU-30 acts on it and adds `CREATE TYPE gcp_source` to migration
    `0002` while IU-16's column stays `Text`, the migration creates a type no table uses —
    and `alembic check` (§13.1 IU-31, tier 2) then reports drift forever.

    This test pins the state both units actually shipped. It fails the moment someone
    "fixes" one side without the other, which is the only way this gets resolved once rather
    than oscillating.
    """
    models_source = MODELS_ENUMS.read_text(encoding="utf-8")
    gcp_model = (REPO_ROOT / "backend" / "app" / "models" / "gcp.py").read_text(encoding="utf-8")

    assert "PG_ENUM_NAMES" in models_source, "models/enums.py no longer names the PG type list"
    assert '"gcp_source"' not in models_source, (
        "models/enums.py now declares a `gcp_source` PG type. IU-17 asked for exactly this, "
        "so this may be the intended resolution — but §5.3's count of seventeen, migration "
        "0002, and models/gcp.py's Text+CHECK column must ALL move together."
    )
    assert "GcpSource" in gcp_model, "models/gcp.py no longer references GcpSource"
