"""★ A RE-EXPORT SHIM. It declares nothing of its own.

The provenance value objects live in :mod:`ai_engine.types.provenance`, and that
placement is load-bearing rather than stylistic: `types/results.py` needs
`ResolutionReport` on every `MatchJobResult`, and **the types package may never import
the models package** — `ai_engine.types` must stay importable on numpy + stdlib alone,
because that property is the entire justification for the one permitted cross-package
import (`gis.candidates` → `ai_engine.types`), and `models/` reaches the torch guard.

This module exists so that ``from ai_engine.models.spec import ComponentSpec`` still
reads naturally at the registration sites, where a spec is a *registry* concept. Value
objects belong to the vocabulary layer; behaviour belongs here.
"""

from __future__ import annotations

from ai_engine.types.provenance import (
    ComponentKind,
    ComponentSpec,
    PreflightReport,
    Resolution,
    ResolutionReport,
)

__all__ = [
    "ComponentKind",
    "ComponentSpec",
    "PreflightReport",
    "Resolution",
    "ResolutionReport",
]
