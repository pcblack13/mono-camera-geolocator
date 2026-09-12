"""The closed vocabularies of the CV domain.

★ THREE of these enums are **parity leg 3**: their values are identical, member for
member, to a PostgreSQL enum type and to a `schemas.enums` mirror. The pairing is
normative (CONTRACT §5.3 PARITY_MAP) and asserted by
`backend/app/tests/unit/test_enum_parity.py`:

    semantic_class    <-> models.enums.SemanticClass    <-> SemanticClass
    robust_estimator  <-> models.enums.RobustEstimator  <-> HomographyMethod
    pose_method       <-> models.enums.PoseMethod       <-> PoseMethod

The three files are deliberately separate and none imports another — `ai_engine` may
not import `sqlalchemy` and `app.schemas` may not import `ai_engine`. The test is what
keeps them honest. **Changing a value here is a schema change.**

`ViewRegime` is deliberately NOT in parity scope: `match_results.view_regime` is a
plain text column because it is diagnostic provenance rather than a queried dimension,
and it is the member set most likely to grow as the regime taxonomy is tuned.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "DescriptorKind",
    "Device",
    "HomographyMethod",
    "PoseMethod",
    "SemanticClass",
    "Severity",
    "ViewRegime",
]


class DescriptorKind(StrEnum):
    """How a descriptor block is stored, and therefore which metric is meaningful."""

    BINARY = "binary"  # Hamming metric; descriptors stored bit-packed uint8
    FLOAT = "float"  # L2 metric; descriptors L2-normalised float32


class HomographyMethod(StrEnum):
    """★ THIS IS `RansacConfig.method` — a ROBUST-FIT METHOD. It is NOT a component
    registry key. The only registered ESTIMATOR BACKEND is "opencv", and
    `AiEngineConfig.estimator_backend` selects it.

    Conflating the two is a boot crash on an empty environment: resolving
    "usac_magsac" against `ComponentKind.ESTIMATOR` finds no spec, finds no fallback,
    exhausts the chain and raises `ComponentUnavailable` at preflight — a traceback
    with zero env vars set, violating L10 and L11 simultaneously. Two names, two
    concepts, no overlap: `LE_AI_RANSAC_METHOD` sets this; `LE_AI_ESTIMATOR_BACKEND`
    sets the component.

    ★ PARITY LEG 3 — every member is representable in the `robust_estimator` PG enum,
      so a job can always record what actually ran.
    """

    USAC_MAGSAC = "usac_magsac"  # cv2.USAC_MAGSAC          [DEFAULT]
    PROSAC = "prosac"  # UsacParams(sampler=SAMPLING_PROSAC, score=SCORE_METHOD_MAGSAC)
    RANSAC = "ransac"  # cv2.RANSAC               [baseline]
    LMEDS = "lmeds"  # cv2.LMEDS   [available; DISQUALIFIED by default]
    USAC_ACCURATE = "usac_accurate"
    LSQ = "lsq"  # no robustification; tests / already-clean inliers only


class SemanticClass(StrEnum):
    """★ PARITY LEG 3. Values are IDENTICAL to the `semantic_class` PG enum and to
    `schemas.enums.SemanticClass`. `SemanticMap.masks` is keyed by this.

    Without this leg, `ai_engine` could emit a mask class the DB cannot store, or drop
    one the enum promised, and nothing would fail — the parity test used to cover only
    models<->schemas. The triangle is now closed.
    """

    FIELD_BORDER = "field_border"
    ROAD = "road"
    IRRIGATION_CANAL = "irrigation_canal"
    TREE = "tree"
    TREE_LINE = "tree_line"
    GREENHOUSE = "greenhouse"
    BUILDING = "building"
    WATER_BODY = "water_body"
    CROP_ROW = "crop_row"
    BARE_SOIL = "bare_soil"
    VEGETATION = "vegetation"
    SHADOW = "shadow"
    UNKNOWN = "unknown"


class PoseMethod(StrEnum):
    """★ PARITY LEG 3. Mirrors the `pose_method` PG enum member-for-member.

    `camera_poses.method` is NOT NULL, so a method without a label here is a pose that
    is literally unwritable — which is why `zhang_plane`, the PRIMARY method, has one.
    """

    ZHANG_PLANE = "zhang_plane"  # ★ PRIMARY
    HOMOGRAPHY_DECOMPOSITION = "homography_decomposition"  # decomposeHomographyMat fallback
    PNP = "pnp"
    EXIF_GPS_ONLY = "exif_gps_only"
    MANUAL = "manual"
    HEATMAP_ARGMAX = "heatmap_argmax"


class ViewRegime(StrEnum):
    """How the query photograph sees the ground — the single strongest predictor of
    whether a planar homography is even the right model.

    A homography is strictly valid only for a planar scene or a pure rotation. A
    ground-level oblique violates both, which is why the regime clamps the reported
    confidence rather than merely annotating it.
    """

    NADIR = "nadir"
    OBLIQUE_RECTIFIABLE = "oblique_rectifiable"
    OBLIQUE_RAW = "oblique_raw"
    GROUND_HORIZON = "ground_horizon"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """A degeneracy check's disposition."""

    HARD = "hard"  # gate := 0.0, status := "rejected"
    SOFT = "soft"  # gate *= factor


class Device(StrEnum):
    """Compute placement. `AUTO` resolves to CPU on the verified box: the cu130 wheel
    is installed but `torch.cuda.is_available()` is False. Never infer a device from a
    build name — `models/device.py` asks, it does not assume.
    """

    AUTO = "auto"  # -> CPU on the verified box
    CPU = "cpu"
    CUDA = "cuda"
