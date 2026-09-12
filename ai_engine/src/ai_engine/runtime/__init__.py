"""Runtime: caches, process fan-out, structured events.

★ THIS PACKAGE IS REAL, not deferred. None of it is computer vision — it is a dict, a
directory, a process pool and three dataclasses — and all of it is exercised by tests today.

The `CacheBackend` and `ImageStore` **Protocols** live in `ai_engine.types.cache`; the
implementations live here. The side that declares the Protocol owns the Protocol.
"""

from __future__ import annotations

from ai_engine.runtime.cache import DictImageStore, DiskCache, NullCache, resolve_ref
from ai_engine.runtime.events import ComponentFallback, DegeneracyTripped, StepTiming
from ai_engine.runtime.parallel import process_map

__all__ = [
    "ComponentFallback",
    "DegeneracyTripped",
    "DictImageStore",
    "DiskCache",
    "NullCache",
    "StepTiming",
    "process_map",
    "resolve_ref",
]
