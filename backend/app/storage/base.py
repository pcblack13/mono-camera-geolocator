"""``ObjectStorage`` — the bytes-in/bytes-out ABC (CONTRACT.md §2.4).

``put · get · open · delete · exists · url_for``, plus ``stat`` and ``free_bytes``,
which the upload path needs and which no caller can portably do for itself.

The abstraction earns its keep in exactly one place: ``LE_STORAGE_BACKEND=local`` is
the zero-config default a surveyor runs on a laptop, and ``s3`` is what a deployment
with two API replicas and three workers needs — and no service should contain an
``if backend == "s3"``.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, ClassVar, Iterable, Iterator, Mapping

__all__ = ["ObjectStorage", "StorageStat", "StoredObject", "sha256_of"]

#: 1 MiB. Large enough that a 500 MB upload is 500 reads rather than 128,000, small
#: enough that eight concurrent uploads do not add a gigabyte of resident memory.
CHUNK_SIZE: int = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The receipt for a successful ``put``."""

    key: str
    size_bytes: int
    #: Hex sha256 of the stored bytes. Not optional: ``images.checksum_sha256`` backs
    #: the ``uq_images_project_checksum`` dedupe index and ``exports.checksum_sha256``
    #: is served as ``X-Checksum-SHA256`` so a surveyor can verify a download they may
    #: file against. Computing it during the write costs one pass over bytes already
    #: in cache; computing it later costs a full re-read.
    checksum_sha256: str
    content_type: str | None = None
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class StorageStat:
    """What ``stat`` reports about an existing object."""

    key: str
    size_bytes: int
    modified_at: datetime | None = None
    content_type: str | None = None
    etag: str | None = None


def sha256_of(chunks: Iterable[bytes]) -> tuple[str, int]:
    """Hash and measure a stream in one pass. Returns ``(hex_digest, byte_count)``."""
    hasher = hashlib.sha256()
    total = 0
    for chunk in chunks:
        hasher.update(chunk)
        total += len(chunk)
    return hasher.hexdigest(), total


class ObjectStorage(ABC):
    """Where the bytes live.

    Implementations are **synchronous**. Both callers — a Celery worker and a FastAPI
    route — can use a sync interface (the route runs it in a threadpool), whereas an
    async interface would be unusable from the worker without an event loop per task.
    The asymmetry favours the runtime that has no choice.
    """

    #: The ``LE_STORAGE_BACKEND`` value this class implements.
    backend: ClassVar[str]

    @abstractmethod
    def put(
        self,
        key: str,
        data: bytes | BinaryIO | Iterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        """Store ``data`` at ``key``, overwriting any existing object.

        Accepts a stream, not just bytes, because a 500 MB upload must never be
        materialised whole (``LE_UPLOAD_MAX_BYTES`` is 500 MB and four concurrent
        uploads would be 2 GB of RSS).

        **Must be atomic**: a reader either sees the complete object or no object.
        A half-written original that a worker then tries to decode produces a
        corrupt-image error for what is really a race, and the surveyor is told their
        photo is broken when it is not.

        Raises:
            ArtifactWriteFailed: the write did not complete.
        """

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read an entire object into memory.

        For small objects only — thumbnails, exports, manifests. Use ``open`` for
        anything that might be an original.

        Raises:
            ArtifactReadFailed: missing or unreadable.
        """

    @abstractmethod
    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Open an object for streaming reads.

        A context manager, so the caller cannot leak the handle::

            with storage.open(key) as fh:
                image = Image.open(fh)

        Raises:
            ArtifactReadFailed: missing or unreadable.
        """

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an object. Returns True if it existed.

        Idempotent: deleting a missing object is not an error. Deletes are driven by
        retention sweeps and hard-delete endpoints, both of which can and will run
        twice, and neither should fail the second time.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether an object exists. Never raises for a missing key."""

    @abstractmethod
    def stat(self, key: str) -> StorageStat | None:
        """Metadata for an object, or None if it does not exist.

        Backs ``Range`` support on ``GET /images/{id}/file`` (endpoint 12), which
        needs the size before it can validate the requested range.
        """

    @abstractmethod
    def url_for(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        download_name: str | None = None,
    ) -> str | None:
        """A directly-fetchable URL for the object, or None if the backend has none.

        ``None`` is a legitimate answer and the *default* backend's answer: local
        storage has no URL space of its own, so the API serves the bytes itself. The
        caller must handle None rather than assume a URL — which is why this returns
        an Optional instead of raising.
        """

    @abstractmethod
    def free_bytes(self) -> int | None:
        """Free space in bytes, or None when the backend cannot know.

        Checked against ``LE_STORAGE_MIN_FREE_BYTES`` **before** an upload is streamed
        (§9.5) — discovering the disk is full after writing 400 MB of a 500 MB file
        helps nobody, and the partial write then has to be cleaned up under an error
        path that is itself running out of disk.

        None for object stores, which are effectively unbounded and whose capacity is
        not a question this process can answer. Callers treat None as "no reason to
        refuse".
        """

    def list_prefix(self, prefix: str) -> Iterator[str]:
        """Yield every key under ``prefix``.

        Concrete default: not abstract, because only the delete paths need it and an
        implementation without it is still useful.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support prefix listing")

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``. Returns the count deleted."""
        count = 0
        for key in list(self.list_prefix(prefix)):
            if self.delete(key):
                count += 1
        return count
