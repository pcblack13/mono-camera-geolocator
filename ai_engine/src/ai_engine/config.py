"""Engine configuration — stdlib dataclasses, deliberately NOT pydantic.

`ai_engine` must import with zero runtime installs beyond numpy/cv2/scipy, and pydantic
is not installed on the verified box. More importantly, config validation here is a
*composition-time* concern with domain rules ("these four weights cannot all be zero"),
not a wire-parsing concern. The backend owns wire parsing; it reads the environment once,
in `app.core.config`, and constructs one of these.

★ NOTHING IN THIS MODULE READS THE ENVIRONMENT. Every field has a working default, so
`AiEngineConfig()` is a valid, fully-operational classical configuration — which is L10
and L1 expressed as a data structure: the product runs end to end with zero env vars and
zero weight files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_engine.errors import ConfigurationError
from ai_engine.logging import get_logger
from ai_engine.types import Device, HomographyMethod, RansacConfig

__all__ = [
    "AiEngineConfig",
    "AsiftConfig",
    "DeepConfig",
    "DegeneracyConfig",
    "ScoringConfig",
]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DegeneracyConfig:
    """Thresholds for the degeneracy checks. The letters map to the normative check list."""

    min_inliers: int = 12  # H1
    max_reproj_error_px: float = 8.0  # H7
    max_anisotropy: float = 20.0  # H8
    min_hull_area_frac: float = 0.05  # H6
    collinearity_ratio: float = 0.01  # H5
    scale_log10_range: tuple[float, float] = (-5.0, 2.5)  # H9
    max_landmarks_out_of_bounds_frac: float = 0.50  # H10
    max_placeholder_fraction: float = 0.20  # H13
    kappa_transfer: float = 1e3  # ★ H4(b) — the gauge-free vanishing-line test
    cond_ok: float = 1e4  # S1 lower knee
    cond_max: float = 1e7  # S1 upper knee
    flatness_sigma_m: float = 1.0  # S6


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """The composite score's weights and knees.

    The four weights are renormalised over whichever terms are present, so a missing
    semantic term does not shift the score — it just redistributes its weight.
    """

    w_feature: float = 0.25
    w_geometric: float = 0.35
    w_landmark: float = 0.30
    w_semantic: float = 0.10
    n0_inliers: float = 30.0  # S_f knee
    eps0_px: float = 3.0  # S_g RMS scale
    eps_landmark_px: float = 5.0  # transfer_k scale
    orient_coherence_min: float = 0.30  # s_orient gate
    orient_cond_max: float = 10.0  # ★ s_orient gate on cond(J)


@dataclass(frozen=True, slots=True)
class DeepConfig:
    """Deep-backend limits.

    ★ `max_candidates = 8` is CODE-ENFORCED, not advisory. `torch.cuda.is_available()` is
      False on the verified box and the detector-free models are 2-8 s per 1024^2 image on
      CPU. Deep matching runs only as a final refinement of the top candidates. The
      classical path is not merely the fallback — on this hardware it is the FASTER
      configuration (~3.2 s cold, ~1.0 s warm, versus +16-40 s deep).
    """

    max_candidates: int = 8
    batch_size: int = 1
    coarse_level: int = 8  # detector-free 1/8 resolution stage
    max_side_px: int = 1024


@dataclass(frozen=True, slots=True)
class AsiftConfig:
    """Affine simulation ladder for the ASIFT decorator."""

    tilts: tuple[float, ...] = (1.0, 1.41, 2.0, 2.83, 4.0)
    phi_step_deg: float = 72.0
    base_extractor: str = "sift"


@dataclass(frozen=True, slots=True)
class AiEngineConfig:
    """One job's configuration. Every field has a working default (L10)."""

    extractor: str = "sift"  # ★ classical default (L1)
    matcher: str | None = "flann"  # ★ classical default (L1)
    detector_free: str | None = None  # None => no detector-free pass
    segmenter: str = "classical"  # ★ classical default
    estimator_backend: str = "opencv"
    # ★ A COMPONENT REGISTRY KEY, and "opencv" is the only registered one. The ROBUST-FIT
    #   METHOD is `ransac.method` — a different concept with a different vocabulary.
    #   Conflating them was a boot crash on zero env.
    scorer: str = "composite"
    suggester: str = "classical_suggester"
    strict_models: bool = False
    weights_dir: Path | None = None
    device: Device = Device.AUTO  # -> CPU on the verified box
    max_features: int = 8000
    clahe_enabled: bool = True
    ratio_test: float = 0.75
    cross_check: bool = True
    min_matches: int = 10
    ransac: RansacConfig = field(default_factory=RansacConfig)
    # ★ ransac.method is the HomographyMethod. LE_AI_RANSAC_METHOD sets it.
    degeneracy: DegeneracyConfig = field(default_factory=DegeneracyConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    deep: DeepConfig = field(default_factory=DeepConfig)
    asift: AsiftConfig = field(default_factory=AsiftConfig)
    semantics_enabled: bool = False
    calibration_id: str = "identity"
    job_seed: int = 42  # -> deterministic RANSAC
    min_confidence: float = 40.0  # 0..100
    rank_margin: float = 10.0  # 0..100; below => status="advisory"
    max_results: int = 5

    def validate(self) -> None:
        """Raise `ConfigurationError` on a configuration that cannot produce a job.

        Raises on:
            * any scoring weight <= 0, or all four == 0;
            * `min_confidence` outside [0,100]; `rank_margin` outside [0,100];
            * `deep.max_candidates` outside [1,32];
            * `matcher` is None AND `detector_free` is None (no correspondence source);
            * `estimator_backend` not a registered ESTIMATOR name.

        Warns (never raises) on:
            * `ransac.method == LMEDS` — its 50% breakdown point disqualifies it for our
              ~80%-outlier regime, but it stays selectable for comparison runs.
        """
        s = self.scoring
        weights = {
            "w_feature": s.w_feature,
            "w_geometric": s.w_geometric,
            "w_landmark": s.w_landmark,
            "w_semantic": s.w_semantic,
        }
        negative = {k: v for k, v in weights.items() if v < 0}
        if negative:
            raise ConfigurationError(f"scoring weights must be non-negative; got {negative}")
        if sum(weights.values()) <= 0:
            raise ConfigurationError(
                "at least one scoring weight must be positive; all four are zero, which "
                "would make every confidence exactly zero"
            )

        if not 0.0 <= self.min_confidence <= 100.0:
            raise ConfigurationError(
                f"min_confidence is a 0-100 score; got {self.min_confidence}"
            )
        if not 0.0 <= self.rank_margin <= 100.0:
            raise ConfigurationError(f"rank_margin is a 0-100 score; got {self.rank_margin}")
        if not 1 <= self.deep.max_candidates <= 32:
            raise ConfigurationError(
                f"deep.max_candidates must lie in [1,32]; got {self.deep.max_candidates}"
            )
        if self.matcher is None and self.detector_free is None:
            raise ConfigurationError(
                "no correspondence source: matcher and detector_free are both None. "
                "Set one (the classical default is matcher='flann')."
            )

        self._validate_estimator_backend()

        if self.ransac.method is HomographyMethod.LMEDS:
            _log.warning(
                "ransac.method=lmeds has a 50%% breakdown point and is disqualified for the "
                "~80%%-outlier regime this engine targets. It remains selectable for "
                "comparison runs; it is not the supported configuration."
            )

    def _validate_estimator_backend(self) -> None:
        """Check `estimator_backend` names a registered ESTIMATOR, if the registry can say.

        ★ The registry import is CALL-TIME, never at module scope. `ai_engine.models`
          reaches `torch_guard`, and `_ensure_registered()` imports every module carrying
          a `@register` decorator — so a module-scope import here would make
          `import ai_engine.config` drag in the whole engine, and would cycle
          (models -> ... -> config).

        ★ AND IT FAILS OPEN, DELIBERATELY. This check cannot be the reason an empty
          environment raises. Two cases skip it with a warning rather than a traceback:

            * the registry cannot be imported or queried at all;
            * the registry reports NO estimator specs whatsoever — which is the state of
              a build where the estimator is deferred (see docs/architecture/SCOPE.md).
              Raising there would reject `AiEngineConfig()`'s own default and reproduce
              the exact zero-env boot crash this field was split out to kill (L10, L11).

          It raises only when the registry HAS estimator specs and this one is not among
          them, which is the case the check was actually written for: a typo, reported
          at composition time rather than mid-job.
        """
        try:
            from ai_engine.models import Registry  # noqa: PLC0415 — call-time by design
            from ai_engine.types import ComponentKind

            import ai_engine.models as _models

            registry = next(
                (obj for obj in vars(_models).values() if isinstance(obj, Registry)), None
            )
            if registry is None:
                raise LookupError("no Registry instance is exposed by ai_engine.models")
            names = {spec.name for spec in registry.specs(ComponentKind.ESTIMATOR)}
        except Exception as exc:  # noqa: BLE001 — every failure mode is a skip, never a raise
            _log.warning(
                "Could not consult the component registry to validate "
                "estimator_backend=%r (%s: %s); skipping that check. The configuration is "
                "otherwise valid.",
                self.estimator_backend,
                type(exc).__name__,
                exc,
            )
            return

        if not names:
            _log.warning(
                "The component registry has no estimator backends registered, so "
                "estimator_backend=%r cannot be verified. This is expected in a build "
                "where the estimator is deferred; see %s.",
                self.estimator_backend,
                "docs/architecture/SCOPE.md",
            )
            return

        if self.estimator_backend not in names:
            raise ConfigurationError(
                f"estimator_backend={self.estimator_backend!r} is not a registered "
                f"estimator; known: {sorted(names)}. Note this is a component REGISTRY KEY "
                f"(the only registered one is 'opencv'), not a robust-fit method — the "
                f"method is ransac.method, a HomographyMethod."
            )
