"""Project export — one self-contained folder gathering everything a project owns.

★ WHY (2026-09-03, owner ask). The app stores files by TYPE (images/, dem/,
accuracy/, lut/) keyed by UUID, and stitches "which belongs to which" together
only in the database. There is no per-project folder on disk, so a project's
photo, its GCPs, its DEM and its solve outputs live scattered across four trees.
This writes them back into ONE human-browsable folder inside the visible
LandExplorer directory::

    <LandExplorer>/projects/<name>-<YYYYmmdd-HHMMSS>/
        project.json          what this folder is — the manifest
        gcps.csv              every GCP, with its image, pixel and world coords
        images/<file>         each source photo
        dem/<id>.tif          the project DEM (+ its .json sidecar)
        accuracy/<image>/     the GCP-solve outputs (heatmaps, correction.json)
        lut/<site>_lut/       the LUT bundle(s) this project produced
        videos/<file>         videos ASSIGNED to the project (usually none)

★ IT IS A COPY, NOT A MOVE. The app's own storage is untouched; this is a
snapshot the operator can browse, archive, or hand off. Missing pieces are
recorded in ``project.json`` rather than failing the export — a project with no
DEM yet still exports its photo and GCPs.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

__all__ = ["ProjectExportError", "export_project", "exports_root"]

#: The GCP attribute table, in order — image + click pixel + world coordinate +
#: the headline accuracy, plus whether the point is exported/stale.
_GCP_COLUMNS = [
    "image",
    "code",
    "name",
    "source",
    "pixel_x",
    "pixel_y",
    "lon",
    "lat",
    "elevation_m",
    "confidence",
    "total_ce90_m",
    "included_in_export",
    "is_stale",
]


class ProjectExportError(Exception):
    """A refusal with a reason — never a bare 500."""


def exports_root(settings: Settings) -> Path:
    """The projects-export folder, inside the visible LandExplorer directory."""
    base = settings.capture_export_dir
    root = (Path(base) if base else Path("~/Pictures/LandExplorer")).expanduser() / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slug(name: str) -> str:
    # Strip leading/trailing dots too, so a name of only dots can never become
    # a "." / ".." / "..." folder.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip("-.")
    return cleaned[:60] or "project"


def _copy_file(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree(src: Path, dst: Path) -> bool:
    if not src.is_dir():
        return False
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return True


def export_project(project_id: str, settings: Settings) -> dict[str, Any]:
    """Assemble ``<LandExplorer>/projects/<name>-<ts>/`` for one project.

    Returns a summary dict (folder, path, counts, and what was missing). Raises
    :class:`ProjectExportError` only when the project itself cannot be read.
    """
    from sqlalchemy import text

    from app.db.session import sync_session
    from app.storage import get_storage

    with sync_session() as db:
        row = db.execute(
            text("SELECT name FROM projects WHERE id = :p AND deleted_at IS NULL"),
            {"p": project_id},
        ).first()
        if row is None:
            raise ProjectExportError("no such project.")
        project_name = str(row[0] or "project")

        images = db.execute(
            text(
                "SELECT id, filename, storage_path FROM images "
                "WHERE project_id = :p AND deleted_at IS NULL ORDER BY created_at"
            ),
            {"p": project_id},
        ).all()
        videos = db.execute(
            text(
                "SELECT id, filename, storage_path FROM videos "
                "WHERE project_id = :p AND deleted_at IS NULL ORDER BY created_at"
            ),
            {"p": project_id},
        ).all()
        gcp_rows: list[dict[str, Any]] = []
        for img in images:
            for g in db.execute(
                text(
                    "SELECT code, name, source, pixel_x, pixel_y, "
                    "ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, "
                    "elevation_m, confidence, accuracy_total_ce90_m, "
                    "is_included_in_export, is_stale "
                    "FROM gcps WHERE image_id = :i ORDER BY code"
                ),
                {"i": img.id},
            ).mappings():
                gcp_rows.append({"image": img.filename, **dict(g)})

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = exports_root(settings) / f"{_slug(project_name)}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []

    # ── the source photos ────────────────────────────────────────────────────
    storage = get_storage()
    local_path = getattr(storage, "local_path", None)
    copied_images = 0
    for img in images:
        if not callable(local_path):
            missing.append("images (storage has no local files — S3 backend)")
            break
        if _copy_file(Path(local_path(img.storage_path)), folder / "images" / img.filename):
            copied_images += 1
        else:
            missing.append(f"image file for {img.filename}")

    # ── the GCP attribute table ──────────────────────────────────────────────
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_GCP_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for g in gcp_rows:
        writer.writerow(g)
    (folder / "gcps.csv").write_text(buf.getvalue(), encoding="utf-8")

    # ── the DEM (project-level, plus any per-image DEMs) ──────────────────────
    dem_dir = Path(settings.project_dem_dir)
    has_dem = _copy_file(dem_dir / f"{project_id}.tif", folder / "dem" / f"{project_id}.tif")
    _copy_file(dem_dir / f"{project_id}.json", folder / "dem" / f"{project_id}.json")
    for extra in dem_dir.glob(f"{project_id}__*.tif"):
        _copy_file(extra, folder / "dem" / extra.name)
    if not has_dem:
        missing.append("project DEM (none built yet)")

    # ── the GCP-solve outputs, one folder per image ──────────────────────────
    acc_dir = Path(settings.accuracy_output_dir)
    solves = 0
    for img in images:
        if _copy_tree(acc_dir / str(img.id), folder / "accuracy" / str(img.id)):
            solves += 1

    # ── the LUT bundle(s) this project produced (matched by the DEM) ──────────
    luts = _copy_project_luts(Path(settings.lut_output_dir), project_id, folder / "lut")

    # ── videos ASSIGNED to the project (usually none — they are often loose) ──
    copied_videos = 0
    for vid in videos:
        if callable(local_path) and _copy_file(
            Path(local_path(vid.storage_path)), folder / "videos" / vid.filename
        ):
            copied_videos += 1

    manifest = {
        "project_id": project_id,
        "project_name": project_name,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "counts": {
            "images": copied_images,
            "gcps": len(gcp_rows),
            "gcp_solves": solves,
            "luts": luts,
            "videos": copied_videos,
        },
        "has_dem": has_dem,
        "missing": missing,
        "contents": {
            "project.json": "this manifest",
            "gcps.csv": "every GCP with image, pixel and world coordinates",
            "images/": "the source photos",
            "dem/": "the project DEM (+ .json sidecar)",
            "accuracy/": "GCP-solve outputs per image (heatmaps, correction.json)",
            "lut/": "the LUT bundle(s) built from this project",
            "videos/": "videos assigned to the project",
        },
    }
    (folder / "project.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info(
        "project.exported",
        project=project_name,
        folder=str(folder),
        images=copied_images,
        gcps=len(gcp_rows),
    )
    return {
        "folder": folder.name,
        "path": str(folder),
        "root": str(exports_root(settings)),
        **manifest["counts"],
        "has_dem": has_dem,
        "missing": missing,
    }


def _copy_project_luts(lut_root: Path, project_id: str, dst: Path) -> int:
    """Copy every LUT bundle whose manifest was solved against this project's DEM."""
    if not lut_root.is_dir():
        return 0
    copied = 0
    for manifest_path in lut_root.glob("*_lut/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dem_file = str((manifest.get("dem") or {}).get("file") or "")
        if dem_file == f"{project_id}.tif":
            bundle = manifest_path.parent
            if _copy_tree(bundle, dst / bundle.name):
                copied += 1
    return copied
