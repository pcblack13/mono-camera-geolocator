"""``dem_library_service`` — the surveyor's processed-DEM folder, as an API surface.

★ THE LIBRARY IS A PLAIN FOLDER (``LE_DEM_LIBRARY_DIR``, default
``~/Documents/LandExplorer/DEMs``). Every successful pipeline run drops its output
GeoTIFF there (:meth:`DemService._export_to_library`) with a ``.tif.json`` sidecar
naming what a picker needs (CRS, cell size, source) — so one cropped, metre-projected
tile can serve every project on the same site without re-processing.

★ ADOPTION RUNS THE REAL PIPELINE. "Use this DEM for project X" feeds the library
file back through :meth:`DemService.process` with the project attached — the same
path the setup page's upload takes. An already-metric file skips reprojection; a
stray geographic one gets fixed rather than trusted. There is no second adoption
code path to drift.

★ FILENAMES ARE HOSTILE INPUT — same containment rule as the capture library:
resolve, then require the result inside the folder; a traversal answers 404
exactly like absence.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.exceptions import NotFoundError
from app.services.dem_service import DemService

logger = logging.getLogger(__name__)

__all__ = ["DemLibraryEntry", "DemLibraryService", "DemLibraryFileNotFound"]

_DEM_SUFFIXES: frozenset[str] = frozenset({".tif", ".tiff"})

#: Newest-first cap — same rationale as the capture library's.
_MAX_ENTRIES = 200


class DemLibraryFileNotFound(NotFoundError):
    """No such DEM in the library (or the name tried to escape it)."""


@dataclass(frozen=True)
class DemLibraryEntry:
    filename: str
    size_bytes: int
    modified_at: datetime
    source_name: str | None
    output_crs: str | None
    pixel_size_m: float | None


class DemLibraryService:
    """List and adopt the processed DEMs in the library folder."""

    def __init__(self, dem_service: DemService) -> None:
        self._dems = dem_service
        self._settings = dem_service._settings  # noqa: SLF001 — same composition root

    def root(self) -> Path | None:
        configured = getattr(self._settings, "dem_library_dir", None)
        if not configured:
            return None
        return Path(configured).expanduser()

    def list(self) -> list[DemLibraryEntry]:
        """The library's DEMs, newest first. An absent folder is an empty library."""
        root = self.root()
        if root is None or not root.is_dir():
            return []
        entries: list[DemLibraryEntry] = []
        for path in root.iterdir():
            if not path.is_file() or path.suffix.lower() not in _DEM_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            meta: dict = {}
            sidecar = path.with_suffix(".tif.json")
            try:
                if sidecar.is_file():
                    meta = json.loads(sidecar.read_text())
            except (OSError, ValueError):
                meta = {}  # a broken sidecar hides the metadata, not the DEM
            px = meta.get("output_pixel_size_m")
            entries.append(
                DemLibraryEntry(
                    filename=path.name,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    source_name=meta.get("source_name"),
                    output_crs=meta.get("output_crs"),
                    pixel_size_m=px[0] if isinstance(px, (list, tuple)) and px else None,
                )
            )
        entries.sort(key=lambda e: e.modified_at, reverse=True)
        return entries[:_MAX_ENTRIES]

    def resolve(self, filename: str) -> Path:
        """``filename`` → a real DEM inside the library, or 404 — traversal included."""
        root = self.root()
        if root is None:
            raise DemLibraryFileNotFound("the DEM library is disabled on this server.")
        candidate = (root / filename).resolve()
        if (
            candidate.parent != root.resolve()
            or candidate.suffix.lower() not in _DEM_SUFFIXES
            or not candidate.is_file()
        ):
            raise DemLibraryFileNotFound(f"no DEM named {filename!r} in the library.")
        return candidate

    def delete(self, filename: str) -> None:
        """Remove one DEM (and its metadata sidecar) from the library folder.

        ★ SAFE BY CONSTRUCTION: adoption re-processes the bytes into the project's
        OWN storage (see :meth:`adopt_into_project`), so no project ever references
        the library file — deleting it can strand nothing. :meth:`resolve` supplies
        the containment rule: traversal answers 404 exactly like absence.

        ★ The sidecar goes best-effort AFTER the raster: a raster that lingers
        without metadata still lists (that is `list`'s broken-sidecar rule); a
        sidecar without its raster would be invisible garbage, so the order matters.
        """
        path = self.resolve(filename)
        sidecar = path.with_suffix(".tif.json")
        path.unlink()
        try:
            if sidecar.is_file():
                sidecar.unlink()
        except OSError:
            logger.warning(
                "Deleted %s from the DEM library but its sidecar %s could not be removed.",
                path.name,
                sidecar.name,
            )

    async def adopt_into_project(
        self,
        *,
        project_id: uuid.UUID,
        filename: str,
        image_id: uuid.UUID | None = None,
    ):
        """Make one library DEM the elevation source of a project — or of ONE image.

        ★ With ``image_id`` the adoption targets that single photograph (it overrides
        the project DEM for that image only); without it, the whole project. Same
        pipeline either way — :meth:`DemService.process` routes on the pair.

        Returns the :class:`DemProcessResponse` of the adoption run.
        """
        path = self.resolve(filename)
        with path.open("rb") as fh:
            return await self._dems.process(
                project_id=project_id,
                image_id=image_id,
                filename=path.name,
                stream=fh,
                aoi_corners=None,
                camera=None,
                tolerance=0.0,
                # ★ True is a no-op for an already-metric file (the stage skips
                #   itself) and a FIX for a stray geographic one — never a lie.
                reproject=True,
                target_srid=None,
                resampling="bilinear",
                target_resolution_m=None,
                set_as_elevation_source=True,
            )
