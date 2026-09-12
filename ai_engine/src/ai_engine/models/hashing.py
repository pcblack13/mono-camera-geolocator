"""★ THE NORMATIVE `params_hash` — one implementation, shared by every component.

§4.14.1 makes this function normative and says why in one line: *"Same config ⇒ same hash
⇒ same cache key, in every unit, forever."*

★ WHY IT LIVES IN `models/` AND NOT IN `pipeline/compose.py`, WHERE §4.14.1 SHOWS IT.
The hash is consumed by two layers that cannot both see `pipeline`:

* `pipeline.compose` needs it to build cache keys — it can import anything.
* **Every component** needs it for its own `params_hash()` method — and §10.2 confines
  `extractors`, `matchers`, `semantics` and `scoring` to `ai_engine.{types,errors,models}`.
  An extractor importing `ai_engine.pipeline` inverts the layer stack and fails
  `.importlinter`'s `layers` contract.

`models/` is the only layer both sides can see, so the single implementation lives here
and `pipeline.compose` re-exports it under the name §4.14.1 gives it. Two implementations
of a cache key is cache poisoning across a package boundary — which is exactly the failure
§4.14.1 was written to prevent, so solving it with a second copy would be perverse.

**A file added to the canonical tree.** §2.2 does not list it; §2's rule is to add in the
spirit of the tree and flag it, which this docstring and the unit report do.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = ["params_hash"]


def params_hash(mapping: Mapping[str, Any]) -> str:
    """Return the stable sha256 hex digest of a component's parameter mapping.

    ★ NORMATIVE, and identical in every component::

        sha256(json.dumps(mapping, sort_keys=True, default=str).encode()).hexdigest()

    computed over **exactly** the key set §4.14.1 defines for that `ComponentKind` — which
    is what `pipeline.compose.component_config` produces and nothing else. Two components
    that hash different key sets for the same configuration would mint different cache
    keys for identical work; two that hash the same keys differently would collide across
    a version boundary. Hence: one function, no options.

    `sort_keys=True` makes the digest independent of insertion order. `default=str` lets
    `Path`, `StrEnum` and the other non-JSON scalars in the normative key sets serialise
    to their stable text form.

    ★ DO NOT PUT UNSTABLE OBJECTS IN THE MAPPING. `default=str` will happily serialise an
    arbitrary object as ``<Foo object at 0x7f...>``, and the address changes every run —
    silently salting the key so the cache never hits and two workers never agree. That is
    why `resolve_with_fallback` takes its `WeightManifest` as a parameter rather than as a
    config key. Everything in the normative key sets has a stable `str()`.

    Args:
        mapping: The component config mapping for one `ComponentKind`.

    Returns:
        A 64-character lowercase hex digest.
    """
    payload = json.dumps(dict(mapping), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
