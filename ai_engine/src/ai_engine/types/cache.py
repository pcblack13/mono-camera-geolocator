"""Storage Protocols — vocabulary, not implementation.

★ These are declared HERE, in `types/`, and implemented in `ai_engine/runtime/cache.py`.
The rule is the same one `WindowSource` follows: **the side that declares the Protocol
owns the Protocol.**

`types/features.py` must NAME `ImageStore` in `ImageRef.resolve`'s signature. If the
class lived only in `runtime/`, `types` would have to forward-reference a module it is
forbidden to import — `mypy --strict` fails on the unresolved name and any
`typing.get_type_hints()` call raises `NameError` at runtime. Declaring the Protocol in
`types/` costs nothing and makes both real.

Both are `runtime_checkable` so a test can assert conformance with `isinstance`. Note
the standard caveat: `runtime_checkable` checks method *presence*, not signatures —
static checking remains the real proof.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

__all__ = ["CacheBackend", "ImageStore"]


@runtime_checkable
class ImageStore(Protocol):
    """Resolves an `ImageRef.sha256` back to pixels.

    Implemented by `ai_engine.runtime.cache.DictImageStore` and by the backend's
    object-storage adapter. Declared here so `ai_engine.types.features` can name it.

    Implementations MUST return ``None`` for an unknown key rather than raise — a cache
    miss is an ordinary outcome, not an error.
    """

    def get(self, sha256: str) -> np.ndarray | None:
        """Return the (H,W,3) uint8 RGB image for `sha256`, or None if not held."""
        ...

    def put(self, sha256: str, image: np.ndarray) -> None:
        """Store `image` under `sha256`. Overwriting with identical content is a no-op."""
        ...


@runtime_checkable
class CacheBackend(Protocol):
    """Feature/descriptor cache, keyed by an opaque string.

    `MatchContext.cache` is typed on THIS, not on the concrete `DiskCache` — which is
    what lets a test inject `NullCache` with nothing installed and no disk touched.

    Implementations MUST treat a miss as ``None`` and MUST NOT raise on a full or
    unwritable backing store: a cache that fails the job it was meant to speed up is
    worse than no cache. Degrade and warn (L11).
    """

    def get(self, key: str) -> bytes | None:
        """Return the cached blob for `key`, or None on a miss."""
        ...

    def set(self, key: str, value: bytes, *, ttl_s: int | None = None) -> None:
        """Store `value` under `key`. `ttl_s=None` means no expiry."""
        ...
