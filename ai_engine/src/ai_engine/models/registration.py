"""★ THE REGISTRATION MANIFEST. Its sole job is to import every `@register` site.

Imported **only** by `models._ensure_registered()`, lazily, at the first registry lookup —
never at `ai_engine.models` import time, which would cycle (`models` → `extractors` →
`models`). See `_ensure_registered`'s docstring for why every other placement is wrong.

**Explicit, not autodiscovered.** No entry-point scanning, no `pkgutil.walk_packages`.
Registration order and membership are visible in this file, greppable, and reviewable in a
diff. The failure mode being avoided is specific and was real: with twelve agents working
in parallel, nothing imported the decorators, `Registry.specs()` was empty at composition
time, and every resolution fell through to `ComponentUnavailable`. This file is the fix,
and it mirrors `gis/imagery/providers/__init__.py`.

★ **Adding a component means adding a line here.** If it is not imported, it does not
exist, and `GET /capabilities` will not list it.

★ Every module below registers a component whose implementation is DEFERRED
(``docs/architecture/SCOPE.md``). They are imported and registered anyway, and that is
deliberate: `/capabilities` must be able to enumerate truthfully what the engine KNOWS
ABOUT as distinct from what it can RUN, and the fallback chains must be real and walked
now rather than first exercised on the day the engine is re-enabled. None of these
imports pulls in cv2, torch or a weight file — the stub bodies raise before touching
anything, which is precisely what keeps this import cheap enough to do lazily.
"""

from __future__ import annotations

# --- extractors (ComponentKind.EXTRACTOR) --------------------------------------------
from ai_engine.extractors import (  # noqa: F401
    akaze,
    asift,
    brisk,
    dinov2,
    orb,
    sift,
    superpoint,
)

# --- geometry (ComponentKind.ESTIMATOR) ----------------------------------------------
from ai_engine.geometry import homography  # noqa: F401

# --- landmarks (ComponentKind.SUGGESTER) ---------------------------------------------
from ai_engine.landmarks import suggest  # noqa: F401

# --- matchers (ComponentKind.MATCHER, ComponentKind.DETECTOR_FREE) -------------------
from ai_engine.matchers import (  # noqa: F401
    bruteforce,
    flann,
    lightglue,
    loftr,
    superglue,
)

# --- scoring (ComponentKind.SCORER) --------------------------------------------------
from ai_engine.scoring import composite  # noqa: F401

# --- semantics (ComponentKind.SEGMENTER) ---------------------------------------------
from ai_engine.semantics import classical, dinov2_seg, sam  # noqa: F401

#: Every module imported for its side effect, named once more so the list is assertable.
#: `test_registry_fallback.py` checks that each of these carries at least one registered
#: spec — an import that silently stopped registering anything would otherwise look
#: exactly like a working one.
REGISTRATION_MODULES: tuple[str, ...] = (
    "ai_engine.extractors.sift",
    "ai_engine.extractors.orb",
    "ai_engine.extractors.akaze",
    "ai_engine.extractors.brisk",
    "ai_engine.extractors.asift",
    "ai_engine.extractors.superpoint",
    "ai_engine.extractors.dinov2",
    "ai_engine.matchers.bruteforce",
    "ai_engine.matchers.flann",
    "ai_engine.matchers.superglue",
    "ai_engine.matchers.lightglue",
    "ai_engine.matchers.loftr",
    "ai_engine.geometry.homography",
    "ai_engine.semantics.classical",
    "ai_engine.semantics.sam",
    "ai_engine.semantics.dinov2_seg",
    "ai_engine.scoring.composite",
    "ai_engine.landmarks.suggest",
)
