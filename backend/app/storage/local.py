"""``LocalObjectStorage`` — ★ THE DEFAULT. Zero config (CONTRACT.md §2.4, §9.5).

``LE_STORAGE_LOCAL_ROOT`` defaults to ``./data/storage`` and nothing else is
required: no bucket, no key, no endpoint. This is the backend a surveyor runs on a
laptop and the one every test uses.

★ **It must be a volume shared across api + workers.** The API writes the upload; a
worker reads it back to thumbnail it. Two separate container filesystems here is the
classic "works on my machine, ``FileNotFoundError`` in compose" — and it fails on the
*second* step, after the upload has already reported success.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, ClassVar, Iterable, Iterator, Mapping

from app.core.exceptions import ArtifactReadFailed, ArtifactWriteFailed
from app.core.logging import get_logger
from app.storage.base import CHUNK_SIZE, ObjectStorage, StorageStat, StoredObject
from app.storage.keys import KEY_SEPARATOR, validate_key

__all__ = ["LocalObjectStorage"]

log = get_logger(__name__)


class LocalObjectStorage(ObjectStorage):
    """Object storage on the local filesystem."""

    backend: ClassVar[str] = "local"

    def __init__(self, root: Path | str) -> None:
        """
        Args:
            root: ``LE_STORAGE_LOCAL_ROOT``. Created if absent — the zero-config
                promise is hollow if the first upload fails on a missing directory.
        """
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        """Resolve a key to a path, refusing anything that escapes the root.

        Two independent checks, and both are load-bearing. ``validate_key`` rejects
        the *syntax* of a traversal; the ``is_relative_to`` check rejects the
        *outcome*, which also catches a symlink inside the root pointing out of it —
        something no amount of string validation can see. Defence in depth is
        warranted here because the failure is arbitrary file read/write.
        """
        validate_key(key)
        path = (self._root / key.replace(KEY_SEPARATOR, os.sep)).resolve()
        if not path.is_relative_to(self._root):
            raise ArtifactWriteFailed(f"Refusing a storage key that escapes the storage root: {key!r}")
        return path

    def local_path(self, key: str) -> Path:
        """The absolute filesystem path for ``key``.

        ★ Backend-specific and deliberately not on the ABC. It exists for
        ``LE_USE_SENDFILE=true``, where ``images.py`` hands nginx an
        ``X-Accel-Redirect`` and nginx serves the bytes — a real optimisation for a
        500 MB original that would otherwise be copied through Python.

        Callers must feature-detect (``isinstance``/``getattr``), never assume: on S3
        there is no such path, and a service that reaches for one has smuggled a
        backend assumption into a layer that must not have one.
        """
        return self._path(key)

    def put(
        self,
        key: str,
        data: bytes | BinaryIO | Iterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        import hashlib

        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        total = 0
        tmp_path: Path | None = None

        try:
            # Write to a temp file in the SAME directory, then os.replace.
            #
            # Same directory because os.replace is only atomic within a filesystem,
            # and /tmp is very often a different one (tmpfs, or a different mount in
            # a container) — where the "atomic" rename silently becomes a copy, and
            # the atomicity this whole dance exists for is gone.
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "wb") as fh:
                for chunk in _iter_chunks(data):
                    hasher.update(chunk)
                    total += len(chunk)
                    fh.write(chunk)
                fh.flush()
                # fsync before the rename: os.replace is atomic with respect to the
                # directory entry, but without an fsync the file's *contents* may
                # still be in the page cache when the machine loses power, leaving a
                # correctly-named zero-length original. This costs milliseconds and
                # buys the durability the atomicity was for.
                os.fsync(fh.fileno())

            os.replace(tmp_path, path)
            tmp_path = None
        except OSError as exc:
            raise ArtifactWriteFailed(f"Could not write {key!r} to local storage.") from exc
        finally:
            if tmp_path is not None and tmp_path.exists():
                # Never leave a .part behind on failure: the retention sweep does not
                # know about them and they are indistinguishable from an upload in
                # flight.
                tmp_path.unlink(missing_ok=True)

        return StoredObject(
            key=key,
            size_bytes=total,
            checksum_sha256=hasher.hexdigest(),
            content_type=content_type,
        )

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactReadFailed(f"No stored object at {key!r}.") from exc
        except OSError as exc:
            raise ArtifactReadFailed(f"Could not read {key!r} from local storage.") from exc

    @contextmanager
    def _open(self, key: str) -> Iterator[BinaryIO]:
        try:
            handle = self._path(key).open("rb")
        except FileNotFoundError as exc:
            raise ArtifactReadFailed(f"No stored object at {key!r}.") from exc
        except OSError as exc:
            raise ArtifactReadFailed(f"Could not open {key!r} from local storage.") from exc
        try:
            yield handle
        finally:
            handle.close()

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        return self._open(key)

    def delete(self, key: str) -> bool:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ArtifactWriteFailed(f"Could not delete {key!r} from local storage.") from exc

        # Prune now-empty parent directories up to (never including) the root. Without
        # this, deleting a project's images leaves its directory skeleton behind
        # forever, and `ls` in the storage root stops being a useful thing to do.
        parent = path.parent
        while parent != self._root and parent.is_relative_to(self._root):
            try:
                parent.rmdir()
            except OSError:
                break  # not empty, or a race with a concurrent write. Either is fine.
            parent = parent.parent
        return True

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except (ArtifactWriteFailed, ValueError):
            # An invalid key does not exist. Saying so beats raising from a predicate
            # whose whole purpose is to be safe to ask.
            return False

    def stat(self, key: str) -> StorageStat | None:
        try:
            info = self._path(key).stat()
        except (FileNotFoundError, ArtifactWriteFailed, ValueError):
            return None
        except OSError as exc:
            raise ArtifactReadFailed(f"Could not stat {key!r}.") from exc
        return StorageStat(
            key=key,
            size_bytes=info.st_size,
            modified_at=datetime.fromtimestamp(info.st_mtime, tz=timezone.utc),
        )

    def url_for(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        download_name: str | None = None,
    ) -> str | None:
        """Always None: local storage has no URL space.

        The API serves these bytes itself through ``GET /images/{id}/file``. Returning
        a ``file://`` URL would be worse than useless — it would be a path the browser
        cannot fetch and an invitation to leak the storage layout, which §5.5
        explicitly forbids.
        """
        return None

    def free_bytes(self) -> int | None:
        try:
            return shutil.disk_usage(self._root).free
        except OSError as exc:
            log.warning("storage.free_bytes_failed", root=str(self._root), error=str(exc))
            # None means "no reason to refuse". Failing an upload because we could not
            # measure the disk would be a self-inflicted outage; the write itself will
            # report ENOSPC honestly if it comes to that.
            return None

    def list_prefix(self, prefix: str) -> Iterator[str]:
        base = (self._root / prefix.replace(KEY_SEPARATOR, os.sep)).resolve()
        if not base.is_relative_to(self._root) or not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.endswith(".part"):
                yield path.relative_to(self._root).as_posix()


def _iter_chunks(data: bytes | BinaryIO | Iterable[bytes]) -> Iterator[bytes]:
    """Normalise bytes / a file object / an iterable of bytes into a chunk stream."""
    if isinstance(data, bytes):
        yield data
        return
    read = getattr(data, "read", None)
    if callable(read):
        while chunk := read(CHUNK_SIZE):
            yield chunk
        return
    for chunk in data:  # type: ignore[union-attr]
        yield chunk
