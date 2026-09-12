"""Component provenance — WHICH backend actually produced a result, and why.

★ THIS MODULE LIVES IN `types/` AND NOT IN `models/`, AND THAT PLACEMENT IS LOAD-BEARING.
`types/results.py` needs `ResolutionReport` (every `MatchJobResult` carries one), and
**the types package may never import the models package**: `ai_engine.types` must stay
importable with only numpy + stdlib, because that property is the entire justification
for the one permitted cross-package import (`gis.candidates` -> `ai_engine.types`), and
`models/` reaches `torch_guard`. So the value objects live here and the *behaviour*
lives on the models side; `models/spec.py` is a re-export shim that keeps
`from ai_engine.models.spec import ComponentSpec` reading naturally at the registration
sites.

The point of all of this: a user who configured SuperPoint and silently got SIFT must
be able to discover that. `Resolution.chain` and `Resolution.reason` are how.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ai_engine.types.enums import Device

__all__ = [
    "ComponentKind",
    "ComponentSpec",
    "PreflightReport",
    "Resolution",
    "ResolutionReport",
]


class ComponentKind(StrEnum):
    """The swappable slots in the engine. One registry, one namespace per kind."""

    EXTRACTOR = "extractor"
    MATCHER = "matcher"
    DETECTOR_FREE = "detector_free"
    SEGMENTER = "segmenter"
    ESTIMATOR = "estimator"
    SCORER = "scorer"
    SUGGESTER = "suggester"


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """A registry entry: how to build one backend, and what it needs first.

    ★ `is_terminal` is a promise the registry ASSERTS at registration time, not a hint:
      a terminal spec must have no `requires_weights` and no `requires_packages` beyond
      the base install, and no `fallback`. That is what makes every fallback chain
      PROVABLY terminate at something that always constructs — which is L1 stated as a
      data structure rather than as a hope.
    """

    name: str
    kind: ComponentKind
    factory: Callable[[Mapping[str, Any]], Any]
    requires_weights: tuple[str, ...] = ()  # WeightManifest KEYS, not paths
    requires_packages: tuple[str, ...] = ()  # importable module names; probed with find_spec
    device_preference: Device = Device.AUTO
    fallback: str | None = None  # None => TERMINAL
    is_terminal: bool = False


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the registry actually gave you when you asked for `requested`."""

    requested: str
    resolved: str
    instance: Any
    chain: tuple[str, ...]  # e.g. ("superpoint", "sift")
    reason: str | None  # "weights missing: superpoint_v1.pth"
    degraded: bool
    device: Device


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    """Every component resolution for one composition, keyed by kind."""

    resolutions: Mapping[ComponentKind, Resolution]
    any_degraded: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialise for `GET /api/v1/capabilities` and for `match_results` provenance.

        Keys are the `ComponentKind` values; `Resolution.instance` is deliberately
        omitted — it is a live object, not wire data.
        """
        return {
            "any_degraded": self.any_degraded,
            "resolutions": {
                str(kind): {
                    "requested": res.requested,
                    "resolved": res.resolved,
                    "chain": list(res.chain),
                    "reason": res.reason,
                    "degraded": res.degraded,
                    "device": str(res.device),
                }
                for kind, res in self.resolutions.items()
            },
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """The boot-time capability snapshot.

    ★ Built ONCE in `main.py`'s lifespan and cached on `app.state`. `GET /capabilities`
      READS the cache and never re-resolves: re-sha256'ing a 2.4 GB checkpoint per
      request is not a health check, it is an outage.

    `any_degraded` is INFORMATIONAL. It must never fail readiness — a box with no
    weight files is the *supported* configuration (L1), not a sick one.
    """

    resolutions: ResolutionReport
    weights_dir: str | None
    device_selected: Device
    cuda_available: bool
    missing_weights: tuple[str, ...]
    any_degraded: bool
    checked_at: float  # time.time() at the moment preflight ran
    messages: tuple[str, ...]  # e.g. "Classical CV pipeline is fully operational."
