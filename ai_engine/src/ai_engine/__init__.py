"""LandExplorer's computer-vision engine: pixels in, pixels out.

It begins at pixels and ends at pixels. It does not know what a coordinate reference
system is, it cannot reach a network or a database, and it has no opinion about HTTP.
Handing it a patch of imagery and getting back a pixel-space fix is the whole interface;
turning that fix into a coordinate is `gis`'s job, and the fact that nothing in here
*can* do that is what keeps the boundary real (L3).

Public surface — deliberately five names::

    run_match_job(ctx) -> MatchJobResult      # the primary entry point
    suggest_landmarks(image, ...)             # the second entry point
    AiEngineConfig                            # what you configure it with
    Registry                                  # what resolves the backends
    version()                                 # what produced your result

★ THIS MODULE IS `__getattr__`-LAZY (PEP 562), AND THAT IS LOAD-BEARING.

`gis.candidates` is permitted exactly one cross-package import, `ai_engine.types`, and
the justification is that `ai_engine.types` costs only numpy + stdlib. But
``from ai_engine.types import CandidateWindow`` executes THIS module first — package
`__init__` always runs before a submodule import. So if this file imported the pipeline
at module scope, that sanctioned import would drag in cv2, scipy and every extractor,
destroying the exact property that permits it and breaking `cd gis && pytest`.

Hence: no heavy import at module scope. The names above bind on first ATTRIBUTE ACCESS,
so `import ai_engine` stays cheap and `ai_engine.run_match_job(...)` still works.
`tests/test_types_import_cheap.py` pins this on a fresh interpreter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_engine.version import ENGINE_VERSION, version

if TYPE_CHECKING:
    # Import-time-free for the type checker: these resolve statically and cost nothing at
    # runtime, so `mypy --strict` sees the real types while the module stays cheap.
    from ai_engine.config import AiEngineConfig
    from ai_engine.landmarks.suggest import suggest_landmarks
    from ai_engine.models import Registry
    from ai_engine.pipeline.orchestrator import run_match_job

__version__ = ENGINE_VERSION

__all__ = [
    "AiEngineConfig",
    "ENGINE_VERSION",
    "Registry",
    "__version__",
    "run_match_job",
    "suggest_landmarks",
    "version",
]

#: name -> (module, attribute). The single table PEP 562 resolves against.
_LAZY: dict[str, tuple[str, str]] = {
    "AiEngineConfig": ("ai_engine.config", "AiEngineConfig"),
    "Registry": ("ai_engine.models", "Registry"),
    "run_match_job": ("ai_engine.pipeline.orchestrator", "run_match_job"),
    "suggest_landmarks": ("ai_engine.landmarks.suggest", "suggest_landmarks"),
}


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access (PEP 562).

    Deliberately does NOT cache into `globals()`: the import system already caches the
    module in `sys.modules`, so a second access costs one dict lookup, and keeping this
    module's namespace free of heavy objects is exactly the point.
    """
    try:
        module_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    from importlib import import_module

    return getattr(import_module(module_name), attr)


def __dir__() -> list[str]:
    """Make the lazy names discoverable to `dir()`, tab-completion and `help()`."""
    return sorted(__all__)
