"""Camera export — everything one registered camera is, in one downloadable folder.

★ WHY (2026-09-12, owner ask). Setting a camera up is eight steps — name it, say
how it connects, place it, attach a DEM, enter calibration, capture the frame and
place control points on it, build the lookup table, freeze the drift reference —
and the results of those steps land in five different trees on disk, keyed by
UUIDs, stitched together only by the ``cameras`` row. Nothing let an operator take
a configured camera with them: to a second machine, to an archive, to a colleague.
This is that: ONE folder holding the whole of one camera::

    <camera>-<YYYYmmdd-HHMMSS>/
        camera.json        the registry row — name, connection, location, tags,
                           calibration, desired state, and what everything points to
        README.txt         what each folder below is
        frame/             the frame captured and used, + the pose row solved on it
        gcps/              the control points, as CSV and as GeoJSON
        dem/               the DEM this camera resolves ground height against
        calibration/       the GCP-solve outputs — the processed DEM calibration
        lut/               the lookup-table bundle the camera places marks with
        drift/             the frozen drift reference (its picture and its pose)

★ IT IS A COPY, NOT A MOVE, and a PARTIAL camera still exports. A camera with no
frame yet exports its name, its connection and its position; every step that has
not happened is named in ``camera.json``'s ``missing`` rather than failing the
download. What the operator gets is always a true account of how far the camera
got — that is more useful than a refusal.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

__all__ = ["CameraExportError", "export_camera"]


class CameraExportError(Exception):
    """A refusal with a reason — never a bare 500."""


#: The control-point table, in order. The same columns the project export writes,
#: so a camera's GCPs and its project's open identically.
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

_README = """This folder is one camera from LandExplorer, exported whole.

  camera.json     the registry row: name, how it connects, where it stands,
                  its tags, the calibration entered on it, the state it is
                  meant to be in, and what each folder below belongs to.
                  Its "missing" list names every setup step not done yet.
  frame/          the frame captured from this camera and used for setup, and
                  frame.json — the pose and intrinsics solved on that frame.
  gcps/           the control points placed on the frame, as CSV and GeoJSON.
  dem/            the elevation model the camera resolves ground height against,
                  with its .json sidecar.
  calibration/    the GCP-solve outputs for the frame: correction.json and the
                  error heatmaps. This is the DEM calibration, once processed.
  lut/            the lookup-table bundle — the per-pixel ground mapping the
                  camera places its detections with.
  drift/          the frozen drift reference: the trusted picture and the pose
                  it was frozen on, which later checks measure movement against.

An empty or absent folder means that step had not been done when this was
exported. camera.json says so explicitly rather than leaving you to guess.
"""


def _slug(name: str) -> str:
    """A folder-safe camera name — never "." or ".." however it is spelled."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip("-.")
    return cleaned[:60] or "camera"


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


def _jsonable(value: Any) -> Any:
    """Rows carry UUIDs and datetimes; a manifest carries strings."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _read_camera(db: Any, camera_id: str) -> dict[str, Any]:
    from sqlalchemy import text

    row = db.execute(
        text(
            "SELECT id, name, lat, lon, source, connection, provides, data_source, "
            "heading_deg, fov_deg, fps, tags, lut_site, desired, project_id, "
            "frame_image_id, calibration, created_at, updated_at "
            "FROM cameras WHERE id = :c"
        ),
        {"c": camera_id},
    ).mappings().first()
    if row is None:
        raise CameraExportError("no such camera.")
    return dict(row)


def _read_frame(db: Any, frame_image_id: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The frame's image row and the pose row solved on it — either may be absent."""
    from sqlalchemy import text

    if frame_image_id is None:
        return None, None
    image = db.execute(
        text(
            "SELECT id, filename, storage_path, project_id, width, height "
            "FROM images WHERE id = :i AND deleted_at IS NULL"
        ),
        {"i": frame_image_id},
    ).mappings().first()
    pose = db.execute(
        text(
            "SELECT fx, fy, cx, cy, k1, k2, p1, p2, k3, img_w, img_h, no_calibration, "
            "fov_h_deg, fov_v_deg, mast_offset_m, tilt_deg, auto_gcp_enabled, "
            "ST_Y(position::geometry) AS lat, ST_X(position::geometry) AS lon "
            "FROM image_cameras WHERE image_id = :i"
        ),
        {"i": frame_image_id},
    ).mappings().first()
    return (dict(image) if image else None), (dict(pose) if pose else None)


def _read_gcps(db: Any, image_ids: list[Any], names: dict[Any, str]) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows: list[dict[str, Any]] = []
    for image_id in image_ids:
        for g in db.execute(
            text(
                "SELECT code, name, source, pixel_x, pixel_y, "
                "ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, "
                "elevation_m, confidence, accuracy_total_ce90_m AS total_ce90_m, "
                # ★ The column is is_included_in_export; aliased so the CSV header
                #   stays the plain word the attribute table has always used.
                "is_included_in_export AS included_in_export, is_stale "
                "FROM gcps WHERE image_id = :i ORDER BY code"
            ),
            {"i": image_id},
        ).mappings():
            rows.append({"image": names.get(image_id, str(image_id)), **dict(g)})
    return rows


def _gcps_geojson(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The control points as points — WGS84, the one CRS a GeoJSON may be in.

    A GCP with no world coordinate yet (picked on the picture, not yet placed) has
    no geometry to write, so it is left out of the vectors. It stays in the CSV,
    which is the complete record.
    """
    features = []
    for row in rows:
        lon, lat = row.get("lon"), row.get("lat")
        if lon is None or lat is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    k: _jsonable(v) for k, v in row.items() if k not in ("lon", "lat")
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _drift_reference_for(settings: Settings, source: str | None, desired: dict[str, Any]) -> str | None:
    """The camera's frozen reference id.

    ★ RESOLVED THE WAY THE PAGES RESOLVE IT: the desired watch's own ``ref_id``
    when the row carries one, else the reference frozen on the same SOURCE. The
    settings page and the monitoring page already agree this way; an export that
    used only the first would silently ship no drift folder for a camera whose
    watch was started from the drift page instead.
    """
    from app.services import drift_service

    watch = (desired or {}).get("watch") or {}
    ref_id = watch.get("ref_id") if isinstance(watch, dict) else None
    if isinstance(ref_id, str) and ref_id:
        return ref_id
    if not source:
        return None
    try:
        for ref in drift_service.scan_references(Path(settings.drift_output_dir)):
            if str(ref.get("source") or "") == source:
                return str(ref.get("ref_id") or "") or None
    except Exception as exc:  # the drift library is a courtesy, not the export
        log.warning("camera.export_drift_scan_failed", error=str(exc))
    return None


def _assemble(camera_id: str, settings: Settings, into: Path) -> dict[str, Any]:
    """Write the whole camera into ``into``; returns the manifest that describes it."""
    from sqlalchemy import text

    from app.db.session import sync_session
    from app.storage import get_storage

    missing: list[str] = []

    with sync_session() as db:
        camera = _read_camera(db, camera_id)
        project_id = camera.get("project_id")
        image, pose = _read_frame(db, camera.get("frame_image_id"))
        if camera.get("frame_image_id") is not None and image is None:
            missing.append("the chosen frame (its image row is gone)")

        # ★ The control points that matter are the ones on the FRAME. A project
        #   with other photographs contributes theirs too, named by image, so the
        #   folder is the whole truth rather than a convenient slice.
        image_rows: list[Any] = []
        if project_id is not None:
            image_rows = db.execute(
                text(
                    "SELECT id, filename FROM images WHERE project_id = :p "
                    "AND deleted_at IS NULL ORDER BY created_at"
                ),
                {"p": project_id},
            ).all()
        names = {r.id: r.filename for r in image_rows}
        gcp_rows = _read_gcps(db, [r.id for r in image_rows], names)

        project_name = None
        if project_id is not None:
            row = db.execute(
                text("SELECT name FROM projects WHERE id = :p AND deleted_at IS NULL"),
                {"p": project_id},
            ).first()
            project_name = str(row[0]) if row else None

    if project_id is None:
        missing.append("a backing project (no DEM, frame or control points yet)")

    # ── the frame captured and used ──────────────────────────────────────────
    storage = get_storage()
    local_path = getattr(storage, "local_path", None)
    has_frame = False
    if image is not None:
        if callable(local_path):
            has_frame = _copy_file(
                Path(local_path(image["storage_path"])), into / "frame" / image["filename"]
            )
        if not has_frame:
            missing.append(f"the frame file for {image['filename']}")
        (into / "frame").mkdir(parents=True, exist_ok=True)
        (into / "frame" / "frame.json").write_text(
            json.dumps(
                {
                    "image": _jsonable({k: v for k, v in image.items() if k != "storage_path"}),
                    # ★ The pose SOLVED on this frame — not the calibration typed on
                    #   the camera. They can differ: the solve is what the lookup
                    #   table was actually built from.
                    "solved_pose": _jsonable(pose) if pose else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        missing.append("a captured frame")

    # ── the control points ───────────────────────────────────────────────────
    if gcp_rows:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_GCP_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for g in gcp_rows:
            writer.writerow(g)
        (into / "gcps").mkdir(parents=True, exist_ok=True)
        (into / "gcps" / "gcps.csv").write_text(buf.getvalue(), encoding="utf-8")
        (into / "gcps" / "gcps.geojson").write_text(
            json.dumps(_gcps_geojson(gcp_rows), indent=2), encoding="utf-8"
        )
    else:
        missing.append("control points")

    # ── the DEM this camera resolves ground height against ───────────────────
    has_dem = False
    if project_id is not None:
        dem_dir = Path(settings.project_dem_dir)
        has_dem = _copy_file(dem_dir / f"{project_id}.tif", into / "dem" / f"{project_id}.tif")
        _copy_file(dem_dir / f"{project_id}.json", into / "dem" / f"{project_id}.json")
        for extra in dem_dir.glob(f"{project_id}__*.tif"):
            _copy_file(extra, into / "dem" / extra.name)
    if not has_dem:
        missing.append("a DEM")

    # ── the DEM calibration: the GCP-solve outputs for the frame ─────────────
    has_calibration_run = False
    if image is not None:
        has_calibration_run = _copy_tree(
            Path(settings.accuracy_output_dir) / str(image["id"]), into / "calibration"
        )
    if not has_calibration_run:
        missing.append("a processed DEM calibration (the GCP solve has not run)")

    # ── the lookup table ─────────────────────────────────────────────────────
    lut_site = camera.get("lut_site")
    has_lut = False
    if lut_site:
        bundle = Path(settings.lut_output_dir) / f"{lut_site}_lut"
        has_lut = _copy_tree(bundle, into / "lut" / bundle.name)
        if not has_lut:
            missing.append(f"the lookup-table bundle '{lut_site}' (named, but not on disk)")
    else:
        missing.append("a lookup table")

    # ── the frozen drift reference ───────────────────────────────────────────
    ref_id = _drift_reference_for(settings, camera.get("source"), camera.get("desired") or {})
    has_drift = False
    if ref_id:
        has_drift = _copy_tree(Path(settings.drift_output_dir) / ref_id, into / "drift" / ref_id)
        if not has_drift:
            missing.append(f"the drift reference '{ref_id}' (named, but not on disk)")
    else:
        missing.append("a frozen drift reference")

    manifest = {
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "camera": _jsonable(
            {k: v for k, v in camera.items() if k not in ("project_id", "frame_image_id")}
        ),
        "links": _jsonable(
            {
                "project_id": project_id,
                "project_name": project_name,
                "frame_image_id": camera.get("frame_image_id"),
                "lut_site": lut_site,
                "drift_ref_id": ref_id,
            }
        ),
        "has": {
            "frame": has_frame,
            "gcps": len(gcp_rows) > 0,
            "dem": has_dem,
            "dem_calibration": has_calibration_run,
            "lut": has_lut,
            "drift_reference": has_drift,
            "camera_calibration": camera.get("calibration") is not None,
        },
        "counts": {"gcps": len(gcp_rows), "images_in_project": len(image_rows)},
        #: ★ Every setup step that had not happened when this was exported. A
        #: partial camera is a normal camera; this is how the folder says so.
        "missing": missing,
        "contents": {
            "camera.json": "this manifest — the registry row and what it points to",
            "frame/": "the frame captured and used, and the pose solved on it",
            "gcps/": "the control points, as CSV and GeoJSON",
            "dem/": "the elevation model, with its sidecar",
            "calibration/": "the GCP-solve outputs — the processed DEM calibration",
            "lut/": "the lookup-table bundle",
            "drift/": "the frozen drift reference",
        },
    }
    (into / "camera.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (into / "README.txt").write_text(_README, encoding="utf-8")
    return manifest


def export_camera(camera_id: str, settings: Settings) -> tuple[Path, str]:
    """The whole camera as one zip. Returns ``(zip path, filename)``.

    The caller owns the file and must delete it — the router does that in a
    background task once the response has been sent.

    Raises:
        CameraExportError: Only when the camera itself cannot be read. Every
            missing SETUP STEP is reported in ``camera.json``, never raised.
    """
    with tempfile.TemporaryDirectory(prefix="camera-export-") as staging:
        work = Path(staging) / "bundle"
        work.mkdir()
        manifest = _assemble(camera_id, settings, work)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        folder = f"{_slug(str(manifest['camera'].get('name') or ''))}-{stamp}"

        handle, tmp = tempfile.mkstemp(prefix="camera-", suffix=".zip")
        os.close(handle)
        path = Path(tmp)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(work.rglob("*")):
                if not item.is_file():
                    continue
                # ★ A JPEG and a PNG are already compressed; deflating the frame
                #   and the drift picture burns CPU to save nothing.
                stored = item.suffix.lower() in (".jpg", ".jpeg", ".png")
                zf.write(
                    item,
                    f"{folder}/{item.relative_to(work).as_posix()}",
                    compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                )

    log.info(
        "camera.exported",
        camera=camera_id,
        folder=folder,
        gcps=manifest["counts"]["gcps"],
        missing=len(manifest["missing"]),
    )
    return path, f"{folder}.zip"
