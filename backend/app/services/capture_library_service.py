"""``capture_library_service`` — the surveyor's own capture folder, as an API surface.

★ THE LIBRARY IS A PLAIN FOLDER (``LE_CAPTURE_EXPORT_DIR``, default
``~/Pictures/LandExplorer``). Every video-frame capture drops a JPEG there
(:meth:`VideoService._export_local_copy`) precisely so the same photograph can serve
several projects. This service is the read side: list what is there, stream one
file, and import one into a project — which simply feeds the file through
:meth:`ImageService.upload`, so an import is indistinguishable from an upload
(dedupe, ingest, thumbnails all included) and re-importing the same file into the
same project dedupes instead of duplicating.

★ FILENAMES ARE HOSTILE INPUT. Every path from the wire is resolved and then
required to sit INSIDE the export folder — a ``../`` or an absolute path answers
404, not a file. The folder may also contain files the app never wrote (users are
told it is theirs); only image extensions are listed or served.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

__all__ = ["CaptureLibraryEntry", "CaptureLibraryService", "LibraryFileNotFound"]

#: What counts as a photo in the folder. The folder is the user's; anything else
#: (videos, sidecars, stray downloads) is invisible to the picker, not an error.
_IMAGE_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})

#: Newest-first cap. The picker is for "that photo from a recent flight", not an
#: unbounded archive browser; a cap keeps one directory scan from shipping megabytes
#: of JSON when the folder has years of captures in it.
_MAX_ENTRIES = 500


class LibraryFileNotFound(NotFoundError):
    """No such photo in the capture library (or the name tried to escape it)."""


@dataclass(frozen=True)
class CaptureLibraryEntry:
    filename: str
    size_bytes: int
    modified_at: datetime


class CaptureLibraryService:
    """List, stream and import the photos in the capture-export folder."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ── the folder ─────────────────────────────────────────────────────────────

    def root(self) -> Path | None:
        """The expanded library folder, or None when the feature is disabled."""
        configured = getattr(self._settings, "capture_export_dir", None)
        if not configured:
            return None
        return Path(configured).expanduser()

    def list(self) -> list[CaptureLibraryEntry]:
        """The library's photos, newest first. An absent folder is an empty library.

        ★ Empty ≠ error: before the first capture the folder does not exist yet, and
        the picker's empty state ("capture frames and they appear here") is the
        honest answer — a 404 would read as a broken feature.
        """
        root = self.root()
        if root is None or not root.is_dir():
            return []
        entries: list[CaptureLibraryEntry] = []
        for path in root.iterdir():
            if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:  # deleted between iterdir and stat — not an event
                continue
            entries.append(
                CaptureLibraryEntry(
                    filename=path.name,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )
        entries.sort(key=lambda e: e.modified_at, reverse=True)
        return entries[:_MAX_ENTRIES]

    def resolve(self, filename: str) -> Path:
        """``filename`` → a real file inside the library, or :class:`LibraryFileNotFound`.

        Raises:
            LibraryFileNotFound: unknown name, non-image, or a path that escapes the
                folder (traversal answers exactly like absence — no oracle).
        """
        root = self.root()
        if root is None:
            raise LibraryFileNotFound("the capture library is disabled on this server.")
        candidate = (root / filename).resolve()
        if (
            candidate.parent != root.resolve()
            or candidate.suffix.lower() not in _IMAGE_SUFFIXES
            or not candidate.is_file()
        ):
            raise LibraryFileNotFound(f"no photo named {filename!r} in the capture library.")
        return candidate

    # ── import into a project ──────────────────────────────────────────────────

    async def import_into_project(
        self,
        images: "ImageServiceLike",
        *,
        project_id: uuid.UUID,
        filename: str,
        owner_id: str | None,
    ):
        """Feed one library file through the normal upload path.

        Returns the same ``UploadResult`` the upload endpoint produces — dedupe and
        ingest behave identically, because it IS the same path.
        """
        path = self.resolve(filename)
        with path.open("rb") as fh:
            return await images.upload(
                project_id=project_id,
                filename=path.name,
                content_type="image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else None,
                data=fh,
                owner_id=owner_id,
            )


class ImageServiceLike:
    """Structural stand-in for :class:`ImageService` (typing only, no import cycle)."""

    async def upload(self, **kwargs): ...  # pragma: no cover
