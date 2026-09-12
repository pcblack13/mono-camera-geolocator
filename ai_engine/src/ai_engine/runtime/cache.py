"""Cache implementations — ★ REAL, and real on purpose.

These are **not** deferred. They are plain infrastructure: a dict, a directory, and a
sha256. Nothing here is computer vision, nothing here needs a weight file, and every line
is exercised by this unit's own tests. Deferring them would have cost the same effort and
delivered nothing (SCOPE §6's principle: keep what is real and costs nothing now).

★ THE PROTOCOLS LIVE IN `types/cache.py`, THE IMPLEMENTATIONS LIVE HERE. Same rule as
`WindowSource`: **the side that declares the Protocol owns the Protocol.** `types/features.py`
must name `ImageStore` in `ImageRef.resolve`'s signature, and `types` may not import
`runtime` — so the vocabulary lives there and the behaviour lives here. That is also what
lets `MatchContext.cache` be typed on `CacheBackend` rather than on `DiskCache`, which is
what lets a test inject `NullCache` with nothing installed and no disk touched.

★ A CACHE MUST NEVER BREAK THE JOB IT WAS MEANT TO SPEED UP. Every method here degrades:
a full disk, an unwritable directory, a corrupt entry, a permissions error — all become a
miss and a warning, never an exception. That is L11 applied to the least important
component in the system, which is exactly where it matters most, because nobody is watching
it.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path

import numpy as np

from ai_engine.logging import get_logger
from ai_engine.types import ImageRef, ImageStore

__all__ = ["DictImageStore", "DiskCache", "NullCache", "resolve_ref"]

_log = get_logger(__name__)

#: Entries are written to a temp file and atomically renamed, so a crash mid-write leaves
#: no half-file that would later read back as a corrupt hit.
_TMP_SUFFIX = ".tmp"

#: Sharding depth: `ab/cd/abcdef...` — a flat directory with a million entries is slow to
#: stat on most filesystems and unpleasant to inspect on all of them.
_SHARD_CHARS = 2


class NullCache:
    """A `CacheBackend` that stores nothing and returns nothing.

    The default, and the right default: caching is an optimisation, and a job must be
    correct without one. It is also what a test injects to prove the engine touches no disk.
    """

    def get(self, key: str) -> bytes | None:
        """Always a miss."""
        return None

    def set(self, key: str, value: bytes, *, ttl_s: int | None = None) -> None:
        """Discard `value`."""
        return None

    def __repr__(self) -> str:
        return "NullCache()"


class DiskCache:
    """A `CacheBackend` over a directory. Atomic writes, optional TTL, degrades to a miss.

    Keys are hashed before they touch the filesystem, so an arbitrary key string cannot
    escape the cache root via ``../`` or collide with a reserved filename. That is a
    correctness property as much as a security one: cache keys are built from component
    names and parameter digests, and nothing guarantees they are path-safe.
    """

    def __init__(self, root: Path | str, *, default_ttl_s: int | None = None) -> None:
        """Bind the cache root.

        Args:
            root: The directory to store entries under. Created lazily on first write, not
                here — constructing a cache must not have a filesystem side effect, and a
                cache that is never written to should not leave a directory behind.
            default_ttl_s: The TTL applied when `set` is called without one. None means
                entries never expire.
        """
        self.root = Path(root)
        self.default_ttl_s = default_ttl_s

    def _path_for(self, key: str) -> Path:
        """Map `key` to a sharded path under the root, via its digest."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:_SHARD_CHARS] / digest[_SHARD_CHARS:]

    def get(self, key: str) -> bytes | None:
        """Return the cached blob for `key`, or None on a miss.

        A miss covers: absent, expired, unreadable, and any OSError at all. **Never
        raises** — see the module docstring.
        """
        path = self._path_for(key)
        try:
            if not path.is_file():
                return None
            if self.default_ttl_s is not None:
                age = time.time() - path.stat().st_mtime
                if age > self.default_ttl_s:
                    self._discard(path)
                    return None
            return path.read_bytes()
        except OSError as exc:
            _log.warning(
                "DiskCache: could not read %s (%s); treating as a miss. The job is "
                "unaffected — a cache that breaks the work it was meant to speed up is "
                "worse than no cache.",
                path,
                exc,
            )
            return None

    def set(self, key: str, value: bytes, *, ttl_s: int | None = None) -> None:
        """Store `value` under `key`. **Never raises.**

        The write is atomic: a temp file in the target directory, then `os.replace`. A crash
        or a full disk mid-write therefore leaves either the old entry or none — never a
        truncated one that would read back later as a plausible, corrupt hit. That is the
        same reasoning `weights.py` applies to a half-downloaded checkpoint, for the same
        reason.

        Args:
            key: The cache key.
            value: The blob to store.
            ttl_s: Currently advisory — expiry is enforced on read against
                `default_ttl_s`. Accepted so the `CacheBackend` Protocol is satisfied
                exactly and a per-entry TTL can be added without a signature change.
        """
        path = self._path_for(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name, suffix=_TMP_SUFFIX
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(value)
                os.replace(tmp_name, path)
            except BaseException:
                # Includes KeyboardInterrupt/SystemExit: an interrupted write must not
                # leave a stray temp file behind either.
                _discard_quietly(Path(tmp_name))
                raise
        except OSError as exc:
            _log.warning(
                "DiskCache: could not write %s (%s); continuing without caching this "
                "entry.",
                path,
                exc,
            )

    def _discard(self, path: Path) -> None:
        """Remove an expired entry, quietly."""
        _discard_quietly(path)

    def __repr__(self) -> str:
        return f"DiskCache(root={str(self.root)!r}, default_ttl_s={self.default_ttl_s!r})"


def _discard_quietly(path: Path) -> None:
    """Unlink `path`, swallowing every OSError. Used only on cleanup paths."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class DictImageStore:
    """An in-memory `ImageStore`. Content-addressed, bounded by insertion order.

    Backs `ImageRef.resolve()`. The bound matters: a match job holds one query image and
    iterates dozens of windows, and an unbounded store would keep every window's pixels
    alive for the whole job — hundreds of megabytes, retained by a cache nobody asked for.
    """

    def __init__(self, *, max_entries: int = 32) -> None:
        """Create an empty store.

        Args:
            max_entries: How many images to retain. The oldest is evicted first (dicts
                preserve insertion order). Must be >= 1.

        Raises:
            ValueError: `max_entries` < 1 — a store that can hold nothing would silently
                turn every `ImageRef.resolve()` into a miss, and a detector-free matcher
                would then report "requires images" forever.
        """
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1; got {max_entries}")
        self.max_entries = max_entries
        self._store: dict[str, np.ndarray] = {}

    def get(self, sha256: str) -> np.ndarray | None:
        """Return the image for `sha256`, or None if not held.

        None rather than an exception: a miss is an ordinary outcome, and the caller who
        actually needs the pixels has `DetectorFreeRequiresImages` for the case where it
        matters.
        """
        return self._store.get(sha256)

    def put(self, sha256: str, image: np.ndarray) -> None:
        """Store `image` under `sha256`, evicting the oldest entry if full.

        Re-putting an existing key refreshes nothing and overwrites nothing: the store is
        **content-addressed**, so the same digest means the same pixels, and rewriting them
        would be pure cost.
        """
        if sha256 in self._store:
            return
        while len(self._store) >= self.max_entries:
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[sha256] = image

    def __len__(self) -> int:
        """How many images are currently held."""
        return len(self._store)

    def __contains__(self, sha256: object) -> bool:
        return sha256 in self._store

    def clear(self) -> None:
        """Drop every entry."""
        self._store.clear()

    def __repr__(self) -> str:
        return f"DictImageStore(entries={len(self._store)}, max_entries={self.max_entries})"


def resolve_ref(ref: ImageRef, store: ImageStore) -> np.ndarray | None:
    """Resolve an `ImageRef` to pixels, verifying what the ref promised.

    Args:
        ref: The content-addressed handle.
        store: The store to resolve against.

    Returns:
        The `(H,W,3)` uint8 RGB image, or None on a miss.

    ★ It checks the returned image's shape against `ref.width`/`ref.height` and treats a
    mismatch as a **miss with a warning**, not as a hit. A store holding different pixels
    under the same digest is a store that has been corrupted or misused, and the failure it
    would otherwise cause — keypoints computed against one image and matched against
    another — is silent, plausible and untraceable. A miss is recoverable; that is not.
    """
    image = store.get(ref.sha256)
    if image is None:
        return None

    if image.ndim < 2:
        _log.warning(
            "resolve_ref: store returned a %d-D array for %s; treating as a miss.",
            image.ndim,
            ref.sha256[:12],
        )
        return None

    height, width = int(image.shape[0]), int(image.shape[1])
    if (width, height) != (ref.width, ref.height):
        _log.warning(
            "resolve_ref: store holds a %dx%d image under %s but the ref says %dx%d. "
            "Treating as a miss rather than returning pixels that are not the ones the "
            "ref names — matching against the wrong image fails silently.",
            width,
            height,
            ref.sha256[:12],
            ref.width,
            ref.height,
        )
        return None

    return image
