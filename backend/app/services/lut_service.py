"""``lut_service`` — builds pixel→lat/lon lookup tables from a photograph's GCPs.

★ THE BRIDGE, NOT THE ALGORITHM. The maths lives in ``app.vendor.lut_generator``
(vendored verbatim; fix bugs in its standalone home and re-copy). This service
only assembles that core's inputs from LandExplorer's own entities:

    intrinsics + distortion   ← the photograph's entered camera (`image_cameras`)
    camera position seed      ← camera lat/lon → DEM CRS; Z = DEM height + mast height
    pose                      ← solved (SQPnP + LM) from the photograph's committed
                                GCPs: image_px ↔ (lat, lon, elevation_m) → DEM CRS
    terrain                   ← the PROJECT's processed DEM (metric UTM by design)

★ RUNS IN A THREAD, TRACKED IN MEMORY. A full-resolution build ray-casts millions
of pixels (~1–5 min) — far past any HTTP timeout — but it is a stateless file
computation that owns no DB row, so a Celery job type (enum + migration + parity)
would buy durability nothing here needs: the bundle on disk IS the durable result,
and a build interrupted by a restart is simply re-run. The registry therefore
lives in this module, guarded by a lock, one entry per build.

★ HONESTY RULES INHERITED FROM THE CORE: pixels that never meet terrain are NaN
(the reader returns ``(None, None)``, never a fabricated coordinate), and the
bundle records pose, DEM md5 and the validation report in its manifest.

Framework-free: no FastAPI, no SQLAlchemy, no Celery — plain data in, plain
status out. The router owns request parsing and DB reads.
"""

from __future__ import annotations

import json
import math
import logging
import re
import threading
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from gis.crs import get_transformer

log = logging.getLogger(__name__)

__all__ = [
    "GcpPoint",
    "LutBuildInputs",
    "LutBuild",
    "LutBuildError",
    "LutImportError",
    "start_build",
    "get_build",
    "list_builds",
    "import_bundle",
    "manifest_has_pose",
    "manifest_pose_needs_fov",
    "manifest_intrinsics",
]


class LutBuildError(ValueError):
    """A build request that cannot proceed — the message names the fix."""


@dataclass(frozen=True)
class GcpPoint:
    """One committed correspondence, as the pose solver needs it.

    ★ ``elevation_m`` may be None: GCPs placed before a DEM was attached carry no Z.
    The build SAMPLES the project DEM at the point's location instead — same surface,
    same datum as everything else in the solve — and only a point outside the DEM's
    coverage is dropped.
    """

    u: float
    v: float
    lat: float
    lon: float
    elevation_m: float | None


@dataclass(frozen=True)
class LutBuildInputs:
    """Everything a build needs, already fetched — plain data, no ORM rows."""

    image_id: UUID
    project_id: UUID
    site_name: str
    image_width: int
    image_height: int
    # intrinsics — OpenCV pinhole + Brown–Conrady, exactly the entered camera
    fx: float
    fy: float
    cx: float
    cy: float
    k1: float
    k2: float
    p1: float
    p2: float
    k3: float
    # camera position: EPSG:4326 + mast height above bare earth
    cam_lat: float
    cam_lon: float
    cam_height_m: float
    gcps: tuple[GcpPoint, ...]
    dem_path: Path
    output_dir: Path
    target_height_m: float = 0.0
    coord_dtype: str = "float64"
    validation_samples: int = 2000
    #: ★ Where the accuracy check stores its results. When the photograph has an
    #: ADOPTED correction there, the build stands on the refined pose instead of the
    #: one its GCPs alone imply — see :func:`accuracy_service.adopted_pose` for why the
    #: pose travels and the local residual field does not. None = never consult it.
    accuracy_dir: Path | None = None
    # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
    # (Last, because a dataclass cannot put defaulted fields before bare ones.)
    #: When true, ``fx..cy`` above are IGNORED and derived from ``fov_h_deg``
    #: instead, with no distortion. The flag is PROVENANCE: it reaches the
    #: manifest, so every artefact downstream knows the K was derived, not measured.
    no_calibration: bool = False
    fov_h_deg: float | None = None
    #: None with ``no_calibration`` means square pixels (fy = fx).
    fov_v_deg: float | None = None
    # <<< GEO-DRIFT-UPDATE C2 END <<<


@dataclass
class LutBuild:
    """One build's lifecycle. Mutated only under `_LOCK` or by its own thread."""

    build_id: str
    inputs: LutBuildInputs
    status: str = "queued"  # queued | running | succeeded | failed
    progress_done: int = 0
    progress_total: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    report: dict[str, Any] | None = None
    bundle_dir: str | None = None
    #: Set when the build stood on an ADOPTED correction rather than the raw GCP solve.
    #: Travels into the response and into a sidecar in the bundle — a LUT whose pose
    #: came from somewhere other than its own control points must say so.
    adopted: dict[str, Any] | None = None

    @property
    def archive_path(self) -> Path | None:
        return None if self.bundle_dir is None else Path(f"{self.bundle_dir}.zip")


_LOCK = threading.Lock()
_BUILDS: dict[str, LutBuild] = {}

#: The output folder name is `<site>_lut`; keep the site to filesystem-safe chars.
_SITE_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_site_name(raw: str) -> str:
    """`yammone 124 (200m)` → `yammone_124_200m` — never an empty string."""
    cleaned = _SITE_SAFE.sub("_", raw.strip()).strip("_")
    return cleaned[:64] or "site"


def validate_inputs(inputs: LutBuildInputs) -> None:
    """Reject an impossible build BEFORE the thread starts, with the fix named.

    Raises:
        LutBuildError: Missing camera fields, too few usable GCPs, or no DEM.
    """
    # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
    # ★ TWO WAYS TO HAVE INTRINSICS, and exactly two. Either a measured
    #   calibration, or a stated field of view. Neither is not a build.
    if inputs.no_calibration:
        # ★ A blank field of view is NOT a refusal (2026-09-09, owner ask): the
        #   solve starts from ``intrinsics.DEFAULT_FOV_H_DEG`` with a wide bracket.
        #   Only a typed angle outside (0, 180) is refused.
        if inputs.fov_h_deg is not None and not 0.0 < float(inputs.fov_h_deg) < 180.0:
            raise LutBuildError(
                f"the horizontal field of view must be between 0 and 180 degrees, "
                f"got {inputs.fov_h_deg}."
            )
    else:
        missing = [
            name
            for name, value in (
                ("fx", inputs.fx), ("fy", inputs.fy), ("cx", inputs.cx), ("cy", inputs.cy),
            )
            if value is None
        ]
        if missing:
            raise LutBuildError(
                "the photograph's camera has no intrinsics "
                f"({', '.join(missing)} unset) — enter the calibration on the camera's "
                "settings page first, or choose 'no calibration' there and give the "
                "field of view instead."
            )
    # <<< GEO-DRIFT-UPDATE C2 END <<<
    if inputs.cam_lat is None or inputs.cam_lon is None:
        raise LutBuildError(
            "the photograph's camera has no position — set lat/lon on the camera's settings "
            "page first."
        )
    if len(inputs.gcps) < 4:
        raise LutBuildError(
            f"the photograph has only {len(inputs.gcps)} committed GCP(s); the pose "
            "solve needs at least 4. Place more GCPs in the editor and try again."
        )
    if not inputs.dem_path.is_file():
        raise LutBuildError(
            "there is no DEM under this photograph — attach one on the camera's settings "
            "page (the LUT is ray-cast against it)."
        )


def start_build(inputs: LutBuildInputs) -> LutBuild:
    """Validate, register, and launch a build thread. Returns the tracked build."""
    validate_inputs(inputs)

    build = LutBuild(
        build_id=uuid_mod.uuid4().hex[:12],
        inputs=inputs,
        progress_total=inputs.image_width * inputs.image_height,
    )
    with _LOCK:
        _BUILDS[build.build_id] = build

    thread = threading.Thread(target=_run, args=(build,), name=f"lut-build-{build.build_id}", daemon=True)
    thread.start()
    return build


def get_build(build_id: str) -> LutBuild | None:
    with _LOCK:
        return _BUILDS.get(build_id)


def list_builds() -> list[LutBuild]:
    with _LOCK:
        return sorted(_BUILDS.values(), key=lambda b: b.started_at, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# The library — bundles on DISK, the durable record
# ─────────────────────────────────────────────────────────────────────────────


#: What travels in an export, in zip order. The arrays and the manifest are the
#: bundle's identity and MUST be present; the field-unit helpers ride along
#: when the bundle has them.
_ARCHIVE_REQUIRED = ("lat.npy", "lon.npy", "manifest.json")
_ARCHIVE_OPTIONAL = ("pi_lookup.py", "README_PI.txt", "adopted_correction.json")


def _write_export_archive(bundle_dir: Path) -> Path:
    """Write ``{bundle_dir}.zip`` — the COMPLETE bundle at the zip root.

    ★ The export carries the manifest (2026-09-03, owner ask). The payload-only
    zip lost the solved camera pose on every re-import — that is exactly how a
    bundle comes back "no pose in its manifest" and stops serving the drift
    monitor. Now the arrays, ``manifest.json`` and, when present, the field
    unit's own reader travel together, so an exported bundle re-imports as
    deployable as it left. Same path the core's own zip used, so
    ``archive_path`` and ``library_archive_path`` are untouched.
    """
    import zipfile  # noqa: PLC0415 — used only at build completion

    archive = Path(f"{bundle_dir}.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for name in _ARCHIVE_REQUIRED:
            zf.write(bundle_dir / name, name)
        for name in _ARCHIVE_OPTIONAL:
            if (bundle_dir / name).is_file():
                zf.write(bundle_dir / name, name)
    return archive


def manifest_center(manifest: dict[str, Any]) -> tuple[float, float] | None:
    """Where on Earth this bundle looks from — ``(lat, lon)``, or None.

    ★ FROM THE MANIFEST ALONE. The obvious answer, ``GeoLut.center()``, loads both
    coordinate arrays — hundreds of megabytes for a full-resolution bundle — which is
    far too much for listing a library or opening a map. The manifest already records
    the solved camera centre (``pose.C``) in the DEM's projected CRS and the CRS
    itself (``dem.epsg``); pyproj turns that pair into WGS84 for the cost of reading
    one small JSON file.

    Any missing piece answers None rather than a guessed point: a map that opens on
    the wrong site is worse than one that says it does not know where to open.
    """
    try:
        c = (manifest.get("pose") or {}).get("C")
        epsg = (manifest.get("dem") or {}).get("epsg")
        if not c or not epsg or len(c) < 2:
            return None
        from pyproj import Transformer  # noqa: PLC0415

        lon, lat = Transformer.from_crs(int(epsg), 4326, always_xy=True).transform(
            float(c[0]), float(c[1])
        )
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return None
        return (round(lat, 8), round(lon, 8))
    except Exception:  # noqa: BLE001 — a manifest is user data; absence is an answer
        return None


def scan_library(output_dir: Path) -> list[dict[str, Any]]:
    """Every bundle under ``output_dir``, newest first, read from its own manifest.

    ★ DISK IS THE RECORD, not the in-memory registry: builds outlive API restarts as
    folders, and a bundle copied in by hand is as real as one built here. A folder
    whose manifest is missing or unreadable is skipped — a library row that cannot
    state its provenance would be a bundle nobody should deploy.
    """
    entries: list[dict[str, Any]] = []
    if not output_dir.is_dir():
        return entries
    for manifest_path in output_dir.glob("*_lut/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # ★ ONE row shape, built in one place (`_entry_for`) — the import route
        #   answers with a row for the bundle it just wrote, and a row that differed
        #   from the ones the scan produces would make the library lie for one
        #   refresh. `center` lets the map open on the site BEFORE anything runs;
        #   `has_pose` says whether the drift monitor can use it at all.
        entries.append(_entry_for(manifest_path.parent, manifest))
    entries.sort(key=lambda e: str(e.get("built_utc") or ""), reverse=True)
    return entries


def library_archive_path(output_dir: Path, site_name: str) -> Path | None:
    """The ``.zip`` for one library entry, or None — traversal-proof by construction.

    The site name is re-sanitised to the same safe alphabet the writer used, so a
    crafted ``../`` can never leave ``output_dir``.
    """
    safe = sanitize_site_name(site_name)
    bundle = output_dir / f"{safe}_lut"
    # ★ Regenerate the archive from the bundle when it is complete: entries
    #   whose on-disk zip predates the manifest-included export policy
    #   (2026-09-03) get the full bundle in the download too. Only a
    #   bundle-less orphan zip is served as-is.
    if all((bundle / name).is_file() for name in _ARCHIVE_REQUIRED):
        return _write_export_archive(bundle)
    archive = output_dir / f"{safe}_lut.zip"
    return archive if archive.is_file() else None


# ─────────────────────────────────────────────────────────────────────────────
# The build itself — runs on the build's own thread
# ─────────────────────────────────────────────────────────────────────────────


def _adopted_pose(inputs: LutBuildInputs) -> dict[str, Any] | None:
    """The photograph's adopted correction, if it has one.

    Imported locally: ``accuracy_service`` imports :class:`GcpPoint` from this module,
    so a module-level import here would close the cycle.
    """
    if inputs.accuracy_dir is None:
        return None
    from app.services import accuracy_service  # noqa: PLC0415 — breaks an import cycle

    try:
        return accuracy_service.adopted_pose(inputs.accuracy_dir, inputs.image_id)
    except Exception:  # noqa: BLE001 — an unreadable adoption must not fail the build
        log.exception("lut: the adopted correction could not be read; using the GCP pose")
        return None


def _reprojection(obj: np.ndarray, img: np.ndarray, R, C, K, dist) -> tuple[float, float]:  # noqa: ANN001
    """(mean, max) reprojection of the control points under an arbitrary pose, in px."""
    import cv2  # noqa: PLC0415

    R = np.asarray(R, dtype=float)
    C = np.asarray(C, dtype=float)
    in_front = ((obj - C) @ R[2]) > 0
    if not np.any(in_front):
        return float("nan"), float("nan")
    projected, _ = cv2.projectPoints(
        obj[in_front].reshape(-1, 1, 3),
        cv2.Rodrigues(R)[0],
        (-R @ C).reshape(3, 1),
        np.asarray(K, dtype=float),
        np.asarray(dist, dtype=float),
    )
    residuals = np.linalg.norm(projected.reshape(-1, 2) - img[in_front], axis=1)
    return float(np.mean(residuals)), float(np.max(residuals))


def _run(build: LutBuild) -> None:
    inp = build.inputs
    build.status = "running"
    try:
        # Local imports: the vendored core pulls cv2/rasterio, which nothing else
        # in the API needs at startup.
        from app.vendor.lut_generator.api import build_from_live_pose
        from app.vendor.lut_generator.dem import DEM
        from app.vendor.lut_generator.pose import solve_pose

        dem = DEM(str(inp.dem_path))
        try:
            # ★ ONE transformer for the camera seed and every GCP — mixing datums
            #   between the two would poison the solve invisibly. `gis.crs` owns
            #   CRS work in this codebase; the vendored core's own transformer is
            #   only used internally for its output arrays.
            tr = get_transformer("EPSG:4326", f"EPSG:{dem.epsg}")

            # `gis.crs` returns shape-(1,) arrays for scalar input — `.item()` them.
            cam_xa, cam_ya = tr.transform(inp.cam_lon, inp.cam_lat)
            cam_x, cam_y = float(np.ravel(cam_xa)[0]), float(np.ravel(cam_ya)[0])
            ground = float(dem.z(cam_x, cam_y))
            if not np.isfinite(ground):
                raise LutBuildError(
                    "the camera position falls outside the project DEM's coverage — "
                    "the DEM cannot supply the camera's ground height."
                )
            cam_c = np.array([cam_x, cam_y, ground + inp.cam_height_m])

            lons = np.array([g.lon for g in inp.gcps])
            lats = np.array([g.lat for g in inp.gcps])
            xs, ys = tr.transform(lons, lats)
            # ★ Fill missing Z from the project DEM itself — the same surface the LUT
            #   is ray-cast against, so a sampled Z cannot disagree with the terrain.
            #   Points outside the DEM's coverage are dropped, and the drop is COUNTED:
            #   quietly solving on fewer points than the surveyor placed would misstate
            #   what the pose stands on.
            zs = np.array(
                [
                    g.elevation_m if g.elevation_m is not None else float(dem.z(x, y))
                    for g, x, y in zip(inp.gcps, xs, ys)
                ],
                dtype=float,
            )
            usable = np.isfinite(zs)
            if int(np.sum(usable)) < 4:
                dropped = len(inp.gcps) - int(np.sum(usable))
                raise LutBuildError(
                    f"only {int(np.sum(usable))} of {len(inp.gcps)} GCPs have a usable "
                    f"elevation ({dropped} fall outside the project DEM's coverage); "
                    "the pose solve needs at least 4 inside the DEM."
                )
            obj = np.column_stack([xs[usable], ys[usable], zs[usable]]).astype(float)
            img = np.array([[g.u, g.v] for g, ok in zip(inp.gcps, usable) if ok], dtype=float)

            # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
            # ★ ONE MODEL, ONE PLACE. The derivation is the geolocation GUI's own,
            #   shared with the drift freeze via `app.services.intrinsics`, so a LUT
            #   built here and a reference frozen there cannot drift apart.
            #
            # ★ AND THIS IS THE PAIRING THAT ACTUALLY WORKS. A LUT built from a FOV
            #   encodes that K in its own arrays, so a drift reference frozen on it
            #   later agrees by construction — the freeze-time reprojection check
            #   stays near zero. (Substituting a derived K onto a LUT built from a
            #   real calibration is the mismatched case, and it reads 5.26 px.)
            fov_h_seed: float | None = None
            seed_span = 0.0
            seed_defaulted = False
            if inp.no_calibration:
                from app.services.intrinsics import k_from_fov, seed_fov  # noqa: PLC0415

                # ★ Typed → the study's bracket; blank → the default seed, wide bracket.
                fov_h_seed, seed_span, seed_defaulted = seed_fov(inp.fov_h_deg)
                K, dist, fov_v_used = k_from_fov(
                    inp.image_width, inp.image_height, fov_h_seed, inp.fov_v_deg
                )
                log.info(
                    "lut.intrinsics_from_fov site=%s fov_h=%.4f%s fov_v=%.4f fx=%.2f",
                    inp.site_name, fov_h_seed, " (default seed)" if seed_defaulted else "",
                    fov_v_used, K[0, 0],
                )
            else:
                K = np.array([[inp.fx, 0.0, inp.cx], [0.0, inp.fy, inp.cy], [0.0, 0.0, 1.0]])
                dist = np.array([inp.k1, inp.k2, inp.p1, inp.p2, inp.k3], dtype=float)
                fov_v_used = None
            # <<< GEO-DRIFT-UPDATE C2 END <<<

            # >>> GEO-DRIFT-UPDATE C3 BEGIN — no calibration SOLVES the focal >>>
            # ★ THE TYPED FIELD OF VIEW IS A SEED, NOT AN INPUT. Freezing the focal
            #   at whatever angle was typed is the failure mode the calibration
            #   study measured: 37 m of ground error from a 60 deg guess, 61 m from
            #   84 deg, against 2.08 m when the focal is SOLVED — from any seed.
            #   The principal point and distortion stay assumed (they are absorbed
            #   by the pose at this geometry); the focal is the one intrinsic that
            #   is not, so it is the one recovered.
            if inp.no_calibration:
                from app.vendor.lut_generator.pose import (  # noqa: PLC0415
                    solve_pose_free_focal,
                )

                seeded_fx = float(K[0, 0])
                R, C, rep, K = solve_pose_free_focal(obj, img, K, dist, cam_c, span=seed_span)
                solved_fx = float(K[0, 0])
                fov_h_solved = float(
                    2 * np.degrees(np.arctan(inp.image_width / (2 * solved_fx)))
                )
                log.info(
                    "lut.focal_solved site=%s seed_fx=%.2f -> fx=%.2f (fov_h %.3f deg)",
                    inp.site_name, seeded_fx, solved_fx, fov_h_solved,
                )
            else:
                R, C, rep = solve_pose(obj, img, K, dist, cam_c)
                solved_fx = fov_h_solved = None
            # <<< GEO-DRIFT-UPDATE C3 END <<<
            finite = rep[np.isfinite(rep)]
            reproj_mean = float(np.mean(finite)) if finite.size else float("nan")
            reproj_max = float(np.max(finite)) if finite.size else float("nan")
            shift = float(np.linalg.norm(C - cam_c))
            log.info(
                "lut %s: pose solved on %d GCPs — reproj mean %.2f px, max %.2f px, "
                "position shift %.1f m",
                build.build_id, len(obj), reproj_mean, reproj_max, shift,
            )

            # ── an ADOPTED correction replaces the pose (and only the pose) ───────
            adopted = _adopted_pose(inp)
            if adopted is not None:
                R, C, K = adopted["R"], adopted["C"], adopted["K"]
                # ★ RE-STATE THE FIT, never inherit it. The numbers above describe how
                #   well the GCP-solved pose fits the GCPs; the refined pose fits the
                #   SATELLITE instead, and typically reprojects the control points a
                #   little worse. Carrying the old figures into the manifest would
                #   describe a pose that is not in the bundle. This is also a useful
                #   truth in itself: the trade the surveyor accepted, in pixels.
                reproj_mean, reproj_max = _reprojection(obj, img, R, C, K, dist)
                shift = float(np.linalg.norm(np.asarray(C) - cam_c))
                build.adopted = {
                    k: v for k, v in adopted.items() if k not in ("R", "C", "K", "dist")
                }
                build.adopted["reproj_mean_px"] = reproj_mean
                build.adopted["reproj_max_px"] = reproj_max
                log.info(
                    "lut %s: built on the ADOPTED '%s' correction — reproj against the "
                    "GCPs is now mean %.2f px, max %.2f px",
                    build.build_id, adopted["stage"], reproj_mean, reproj_max,
                )
        finally:
            dem.close()

        def progress(done: int, total: int) -> None:
            build.progress_done = int(done)
            build.progress_total = int(total)

        inp.output_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir, report = build_from_live_pose(
            site_name=inp.site_name,
            dem_path=str(inp.dem_path),
            output_dir=str(inp.output_dir),
            R=R, C=C, K=K, dist=dist,
            width=inp.image_width, height=inp.image_height,
            target_height_m=inp.target_height_m,
            coord_dtype=inp.coord_dtype,
            validation_samples=inp.validation_samples,
            # ★ make_zip=False: the zip is OURS to write. `_write_export_archive`
            #   below archives the complete bundle — arrays, manifest (with the
            #   pose the drift monitor needs), and the field-unit files — so an
            #   export re-imports as deployable as it left (owner ask 2026-09-03).
            make_zip=False,
            progress_cb=progress,
            reproj_mean_px=reproj_mean,
            reproj_max_px=reproj_max,
            n_gcps_used=len(obj),
            position_shift_m=shift,
        )
        # >>> GEO-DRIFT-UPDATE C2 BEGIN — the manifest says how K was obtained >>>
        # ★ AMENDING THE MANIFEST, NOT A SIDECAR. `adopted_correction.json` next
        #   door is a sidecar because it describes something OUTSIDE the pose; this
        #   describes the pose itself, `pose.K` is already in the manifest, and the
        #   drift monitor reads exactly that block. A second file would mean a
        #   second read path in the freeze, the field-unit export and the library.
        #
        # ★ Best-effort by design: a bundle whose provenance note failed to write
        #   is still a valid bundle, and failing the whole build over it would
        #   throw away minutes of ray-casting for a metadata line.
        try:
            man_path = Path(bundle_dir) / "manifest.json"
            man = json.loads(man_path.read_text(encoding="utf-8"))
            if inp.no_calibration:
                man.setdefault("pose", {})["intrinsics_mode"] = "fov"
                man["pose"]["fov"] = {
                    # ★ Both, deliberately: what was TYPED and what was SOLVED. The
                    #   seed is provenance (it is what the operator asserted); the
                    #   solved value is what the bundle actually stands on, and a
                    #   large gap between them is worth seeing.
                    "fov_h_seed_deg": round(float(fov_h_seed), 4),
                    #: ★ True when nothing was typed and the DEFAULT seed started the
                    #:   search — provenance the library shows beside the solved angle.
                    "seed_defaulted": bool(seed_defaulted),
                    "fov_v_seed_deg": None if fov_v_used is None else round(float(fov_v_used), 4),
                    "square_pixels": inp.fov_v_deg is None,
                    "focal_solved": solved_fx is not None,
                    "fx_solved": None if solved_fx is None else round(solved_fx, 4),
                    "fov_h_deg": None if fov_h_solved is None else round(fov_h_solved, 4),
                }
            # ★ GEO-DRIFT-UPDATE D1 — WHICH PHOTOGRAPH THIS POSE BELONGS TO.
            #   The build has always known (it solved from that image's GCPs) and
            #   has never written it down. Recording it lets the drift monitor
            #   freeze its reference on the very picture the pose was solved on,
            #   instead of a fresh grab taken who-knows-how-long afterwards —
            #   which is the difference between a reference that shares an instant
            #   with its pose and one that may already have drift baked in.
            man["source_image_id"] = str(inp.image_id)
            man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            log.warning("could not record build provenance in %s", bundle_dir)
        # <<< GEO-DRIFT-UPDATE C2 END <<<
        if build.adopted is not None:
            # ★ PROVENANCE TRAVELS WITH THE BUNDLE. The manifest describes the pose that
            #   was used, truthfully — but not that it came from a correction the
            #   surveyor adopted rather than from this photograph's control points.
            #   Whoever deploys this LUT to a field unit is entitled to know that, in
            #   the folder, without access to the app that built it.
            (Path(bundle_dir) / "adopted_correction.json").write_text(
                json.dumps(build.adopted, indent=1), encoding="utf-8"
            )
        _write_export_archive(Path(bundle_dir))
        build.bundle_dir = bundle_dir
        build.report = report
        build.progress_done = build.progress_total
        # ★ The core writes the bundle even when validation fails (so it can be
        #   inspected) — but a failed validation is a FAILED build here: a bundle
        #   that missed its own tolerance must not be handed out as a success.
        if report.get("passed", False):
            build.status = "succeeded"
        else:
            build.status = "failed"
            build.error = (
                "validation exceeded tolerance "
                f"(max {report.get('max_error_m', '?')} m) — the bundle was written "
                "for inspection but must not be deployed."
            )
    except LutBuildError as exc:
        build.status = "failed"
        build.error = str(exc)
    except Exception as exc:  # noqa: BLE001 — the thread must never die silently
        log.exception("lut build %s failed", build.build_id)
        build.status = "failed"
        build.error = f"{type(exc).__name__}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Importing a bundle the app did not build
# ─────────────────────────────────────────────────────────────────────────────
#
# ★ WHY THIS EXISTS AT ALL. ``scan_library`` has always said that "a bundle copied
#   in by hand is as real as one built here" — but copying by hand needs a shell on
#   the API's machine, which the surveyor with the LUT on a USB stick does not have.
#   Import is that same copy, done through the app, with the checks a hand-copy
#   never gets: that the arrays are really a lat/lon table of the shape they claim,
#   and that the folder ends up with the manifest every consumer reads.
#
# ★ WHAT IS ACCEPTED. Both halves of this app's own export story:
#     • the payload-only ``.zip`` this app hands out (``lat.npy`` + ``lon.npy``), and
#     • a FULL bundle — folder or ``.zip``, with or without a wrapping ``<site>_lut/``
#       directory — as written by the generator or carried off a field unit.
#   A payload-only import gets a SYNTHESISED manifest: enough for the detection
#   pages (which need the arrays and the image size), honestly short of a pose,
#   which is why the library entry reports ``has_pose`` and the drift monitor can
#   refuse it up front instead of at freeze time.


class LutImportError(ValueError):
    """A bundle that cannot be filed — the message names what is wrong with it."""


#: The ONLY names ever written out of an uploaded archive. A whitelist, not a
#: sanitiser: a member called ``../../etc/passwd`` is not cleaned up, it is simply
#: never a candidate, so zip-slip has nowhere to land by construction.
_BUNDLE_FILES = (
    "lat.npy",
    "lon.npy",
    "manifest.json",
    "pi_lookup.py",
    "README_PI.txt",
    "gcps.csv",
    "adopted_correction.json",
)
#: Without these two there is no lookup table, whatever else the archive holds.
_PAYLOAD_FILES = ("lat.npy", "lon.npy")


def manifest_has_pose(manifest: dict[str, Any]) -> bool:
    """True when the manifest carries everything the DRIFT monitor needs.

    ★ Mirrors ``drift_service._pose_from_manifest`` exactly. Detection only needs
    the arrays; drift re-solves geometry and needs ``pose.R/C/K``, the image size
    and the DEM's CRS. Surfacing this on the library entry lets the drift page say
    "this bundle cannot be frozen" while the surveyor is still choosing, rather
    than after they press Freeze.
    """
    pose = manifest.get("pose") or {}
    if any(not pose.get(k) for k in ("R", "C", "K", "image_width", "image_height")):
        return False
    return bool((manifest.get("dem") or {}).get("epsg"))


# >>> GEO-DRIFT-UPDATE C1 BEGIN — a bundle that only lacks intrinsics >>>
def manifest_pose_needs_fov(manifest: dict[str, Any]) -> bool:
    """True when the ONLY thing missing is the camera's intrinsics.

    ★ WHY THIS IS SEPARATE FROM ``has_pose``. ``K`` is the one part of the pose a
    surveyor can supply after the fact, from the field of view — ``R``, ``C``,
    the image size and the DEM's CRS cannot be guessed. Folding that into
    ``has_pose`` would either bar the bundles this mode exists for, or claim a
    calibration the bundle does not have. So it gets its own answer: *freezable,
    but you must state the field of view.*
    """
    pose = manifest.get("pose") or {}
    if any(not pose.get(k) for k in ("R", "C", "image_width", "image_height")):
        return False
    if not (manifest.get("dem") or {}).get("epsg"):
        return False
    return not pose.get("K")


# <<< GEO-DRIFT-UPDATE C1 END <<<


def _read_manifest(bundle: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _zip_bundle_root(zf: Any) -> tuple[str, dict[str, Any]]:
    """Find the one directory inside the archive that IS a bundle.

    Returns ``(prefix, {basename: ZipInfo})``. Members are grouped by their parent
    directory and only whitelisted basenames are considered, so the answer is
    driven by where ``lat.npy`` and ``lon.npy`` actually sit — root for this app's
    payload export, ``<site>_lut/`` for a full bundle zipped with its folder.

    Raises:
        LutImportError: No bundle inside, or more than one.
    """
    groups: dict[str, dict[str, Any]] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        # Normalise separators (zips written on Windows) and take the LAST segment.
        parts = info.filename.replace("\\", "/").split("/")
        name = parts[-1]
        if name not in _BUNDLE_FILES:
            continue
        groups.setdefault("/".join(parts[:-1]), {})[name] = info

    candidates = {
        prefix: members
        for prefix, members in groups.items()
        if all(n in members for n in _PAYLOAD_FILES)
    }
    if not candidates:
        raise LutImportError(
            "the archive holds no LUT bundle — it must contain lat.npy and lon.npy, "
            "either at its root (the export this app produces) or inside a single "
            "<site>_lut folder."
        )
    if len(candidates) > 1:
        names = ", ".join(sorted(p or "<root>" for p in candidates))
        raise LutImportError(
            f"the archive holds {len(candidates)} bundles ({names}) — import one at a time."
        )
    return next(iter(candidates.items()))


def _extract_zip(archive: Path, dest: Path, max_bytes: int) -> None:
    """Copy the whitelisted members of one bundle out of ``archive`` into ``dest``.

    ★ Never ``ZipFile.extract``: that honours the member's own path. Each member is
    opened as a stream and written to ``dest / <basename>`` — a path this function
    built — and the running total is checked as it goes, so a zip bomb is refused
    part-way rather than after it has filled the disk.
    """
    import zipfile  # noqa: PLC0415 — import only used by the import path

    try:
        with zipfile.ZipFile(archive) as zf:
            _prefix, members = _zip_bundle_root(zf)
            declared = sum(m.file_size for m in members.values())
            if max_bytes and declared > max_bytes:
                raise LutImportError(
                    f"the bundle unpacks to {declared / 1e6:.0f} MB, beyond the "
                    f"{max_bytes / 1e6:.0f} MB limit."
                )
            written = 0
            for name, info in members.items():
                target = dest / name
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(1024 * 1024):
                        written += len(chunk)
                        if max_bytes and written > max_bytes:
                            raise LutImportError(
                                f"the bundle unpacks to more than the {max_bytes / 1e6:.0f} MB limit."
                            )
                        out.write(chunk)
    except zipfile.BadZipFile as exc:
        raise LutImportError("that file is not a readable .zip archive.") from exc


def _copy_dir(source: Path, dest: Path, max_bytes: int) -> None:
    """Copy one bundle FOLDER's whitelisted files — the desktop's zero-copy route.

    Accepts either the bundle folder itself or a folder holding exactly one.
    """
    import shutil  # noqa: PLC0415

    root = source
    if not all((root / n).is_file() for n in _PAYLOAD_FILES):
        nested = [
            child
            for child in sorted(source.iterdir())
            if child.is_dir() and all((child / n).is_file() for n in _PAYLOAD_FILES)
        ]
        if len(nested) != 1:
            raise LutImportError(
                f"{source.name} is not a LUT bundle folder — it must contain lat.npy and "
                "lon.npy, or a single sub-folder that does."
            )
        root = nested[0]

    total = sum((root / n).stat().st_size for n in _PAYLOAD_FILES)
    if max_bytes and total > max_bytes:
        raise LutImportError(
            f"the bundle's payload is {total / 1e6:.0f} MB, beyond the "
            f"{max_bytes / 1e6:.0f} MB limit."
        )
    try:
        for name in _BUNDLE_FILES:
            src = root / name
            if src.is_file():
                shutil.copyfile(src, dest / name)
    except OSError as exc:
        # A path the surveyor picked but the API cannot read (a permission, an
        # unmounted stick) is THEIR problem to fix — name it, do not 500.
        raise LutImportError(f"{source.name} could not be read: {exc}") from exc


def _validate_payload(bundle: Path) -> tuple[int, int, float]:
    """Prove the two arrays really are a lat/lon table. Returns ``(h, w, payload_mb)``.

    ★ THE CHECK THAT MATTERS. A LUT is believed absolutely downstream — every mark
    on the map is one array read — so an array of the wrong shape, the wrong dtype
    or the wrong UNITS would not fail, it would place detections somewhere plausible
    and wrong. Loading is ``allow_pickle=False`` (an .npy is untrusted input here),
    and the finite range is checked against real latitude/longitude bounds.
    """
    try:
        lat = np.load(bundle / "lat.npy", mmap_mode="r", allow_pickle=False)
        lon = np.load(bundle / "lon.npy", mmap_mode="r", allow_pickle=False)
    except Exception as exc:  # noqa: BLE001 — anything numpy refuses is a bad upload
        raise LutImportError(f"lat.npy / lon.npy could not be read as numpy arrays: {exc}") from exc

    for name, arr in (("lat.npy", lat), ("lon.npy", lon)):
        if arr.ndim != 2:
            raise LutImportError(
                f"{name} is {arr.ndim}-dimensional; a LUT is a 2-D table indexed [v, u]."
            )
        if arr.dtype.kind != "f":
            raise LutImportError(
                f"{name} holds {arr.dtype} values; a LUT stores floating-point degrees "
                "(NaN where the ray met no terrain)."
            )
    if lat.shape != lon.shape:
        raise LutImportError(
            f"lat.npy is {lat.shape[1]}x{lat.shape[0]} and lon.npy is "
            f"{lon.shape[1]}x{lon.shape[0]} — the two tables must describe the same view."
        )
    height, width = int(lat.shape[0]), int(lat.shape[1])
    if height < 2 or width < 2:
        raise LutImportError(f"the table is {width}x{height} pixels — that is not a camera view.")

    for name, arr, limit in (("lat.npy", lat, 90.0), ("lon.npy", lon, 180.0)):
        finite = np.asarray(arr[np.isfinite(arr)], dtype=float)
        if finite.size == 0:
            raise LutImportError(
                f"every value in {name} is NaN — this table maps no pixel to the ground."
            )
        lo, hi = float(finite.min()), float(finite.max())
        if lo < -limit or hi > limit:
            raise LutImportError(
                f"{name} ranges {lo:.3f}…{hi:.3f}, outside ±{limit:g} — these are not "
                "decimal degrees. A LUT stores WGS84 latitude and longitude, not "
                "projected metres."
            )

    payload = sum((bundle / n).stat().st_size for n in _PAYLOAD_FILES)
    return height, width, round(payload / 1e6, 2)


def _settle_manifest(
    bundle: Path, *, site: str, height: int, width: int, payload_mb: float, origin: str
) -> dict[str, Any]:
    """Give the folder the manifest every consumer reads, and say where it came from.

    ★ A bundle carrying its own manifest KEEPS it — the pose, the DEM checksum and the
    validation report are the provenance that makes it deployable, and this function
    must not invent or overwrite any of them. Only the three facts the FOLDER now
    owns are set: the site name (which is the folder's identity here), the image size
    (measured from the arrays, not trusted from the file) and the payload size.

    ★ A payload-only import gets a manifest that is honest about being thin: no pose,
    no validation, and an ``imported`` block that says so. Absent validation reads as
    "not validated" in the library, never as "passed".
    """
    manifest = _read_manifest(bundle) or {}
    synthesised = not manifest

    stated = manifest.get("image") or {}
    mismatch = (
        stated.get("width") not in (None, width) or stated.get("height") not in (None, height)
    )

    manifest["site_name"] = site
    manifest["image"] = {"width": width, "height": height}
    arrays = dict(manifest.get("arrays") or {})
    arrays.setdefault("layout", "row-major [v, u]; index as lat[v, u]")
    arrays["payload_mb"] = payload_mb
    manifest["arrays"] = arrays
    manifest.setdefault("built_utc", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    manifest.setdefault("schema_version", "1.0")

    manifest["imported"] = {
        "at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": origin,
        "manifest": "synthesised" if synthesised else "from the bundle",
        # ★ Stated plainly because it decides what the bundle can be USED for: the
        #   detection pages need only the arrays; the drift monitor needs the pose.
        "has_pose": manifest_has_pose(manifest),
        # GEO-DRIFT-UPDATE C1 — freezable once a field of view is supplied
        "pose_needs_fov": manifest_pose_needs_fov(manifest),
    }
    if synthesised:
        manifest["generator"] = "imported (payload only — no manifest in the source)"
        manifest["imported"]["note"] = (
            "No manifest travelled with this bundle, so it carries no pose, no DEM "
            "checksum and no validation report. It can place detections; it cannot "
            "serve the drift monitor, and its accuracy is whatever the machine that "
            "built it achieved."
        )
    elif mismatch:
        # ★ The arrays are the table. A manifest that disagrees with them about the
        #   image size would silently mis-scale every detection made on a resized
        #   stream (`GeoLut.scale_from`), so the measured size wins and says so.
        manifest["imported"]["note"] = (
            f"The source manifest declared a different image size than the arrays hold; "
            f"the measured {width}x{height} was kept."
        )

    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _entry_for(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """One library row for a bundle already on disk — the shape ``scan_library`` emits."""
    validation = manifest.get("validation") or {}
    return {
        "site_name": str(manifest.get("site_name") or bundle.name.removesuffix("_lut")),
        "built_utc": manifest.get("built_utc"),
        "image": manifest.get("image") or {},
        "payload_mb": (manifest.get("arrays") or {}).get("payload_mb"),
        "validation_passed": validation.get("passed"),
        "max_error_m": validation.get("max_error_m"),
        "bundle_dir": str(bundle),
        "archive_available": Path(f"{bundle}.zip").is_file(),
        "center": manifest_center(manifest),
        "has_pose": manifest_has_pose(manifest),
        # GEO-DRIFT-UPDATE C1 — freezable once a field of view is supplied
        "pose_needs_fov": manifest_pose_needs_fov(manifest),
        "intrinsics": manifest_intrinsics(manifest),
        # ★ WHICH FRAME THE POSE WAS SOLVED ON (2026-09-09): lets the camera settings
        #   say when a table predates the camera's current frame.
        "source_image_id": manifest.get("source_image_id"),
        "imported": manifest.get("imported"),
    }


def manifest_intrinsics(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """How the bundle got its K — so the settings page can say "solved from the
    points: 68.2° (seed 60°, default)" instead of leaving the surveyor to guess
    whether the focal solve ran (2026-09-09).

    None for a bundle built from a measured calibration or one with no pose.
    """
    pose = manifest.get("pose") or {}
    if pose.get("intrinsics_mode") != "fov":
        return None
    fov = pose.get("fov") or {}
    return {
        "mode": "fov",
        "fov_h_seed_deg": fov.get("fov_h_seed_deg"),
        "seed_defaulted": bool(fov.get("seed_defaulted", False)),
        "focal_solved": bool(fov.get("focal_solved", False)),
        "fov_h_solved_deg": fov.get("fov_h_deg"),
        "fx_solved": fov.get("fx_solved"),
    }


def import_bundle(
    *,
    output_dir: Path,
    source: Path,
    origin_name: str,
    site_name: str | None,
    overwrite: bool = False,
    max_bytes: int = 0,
) -> dict[str, Any]:
    """File an uploaded/loose bundle into the library. Returns its library entry.

    Args:
        output_dir: The library folder (``settings.lut_output_dir``).
        source: A ``.zip`` or a bundle FOLDER on the API's own filesystem.
        origin_name: What the surveyor picked, for the provenance record.
        site_name: The name to file it under; defaults to the bundle's own, then
            to the file name. Sanitised either way — the folder is the identity.
        overwrite: Replace an existing bundle of that name instead of refusing.
        max_bytes: Ceiling on the unpacked payload; 0 disables.

    Raises:
        LutImportError: Not a bundle, not a lat/lon table, or the name is taken.

    ★ STAGED THEN SWAPPED. Everything lands in a sibling ``.importing-*`` folder and
    is validated there; only a bundle that passed is moved onto its final name. A
    failed import therefore cannot leave a half-written folder in the library, and
    an overwrite cannot destroy a working bundle in exchange for a broken one.
    """
    import shutil  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / f".importing-{uuid_mod.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        if source.is_dir():
            _copy_dir(source, staging, max_bytes)
        elif source.is_file():
            _extract_zip(source, staging, max_bytes)
        else:
            raise LutImportError(f"{origin_name} is neither a file nor a folder.")

        height, width, payload_mb = _validate_payload(staging)

        # Name: what was asked for → what the bundle calls itself → the file name.
        from_manifest = (_read_manifest(staging) or {}).get("site_name")
        raw = (
            site_name
            or (str(from_manifest) if from_manifest else "")
            or Path(origin_name).stem.removesuffix("_lut")
        )
        site = sanitize_site_name(raw)
        destination = output_dir / f"{site}_lut"
        if destination.exists() and not overwrite:
            raise LutImportError(
                f"the library already holds a bundle named '{site}' — choose another "
                "name, or confirm the replacement."
            )

        manifest = _settle_manifest(
            staging,
            site=site,
            height=height,
            width=width,
            payload_mb=payload_mb,
            origin=origin_name,
        )
        # ★ The field-unit reader travels with every bundle this library holds, so an
        #   imported folder is as deployable as a built one.
        if not (staging / "pi_lookup.py").is_file():
            from app.vendor.lut_generator.bundle import PI_LOOKUP_SRC  # noqa: PLC0415

            (staging / "pi_lookup.py").write_text(PI_LOOKUP_SRC, encoding="utf-8")

        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
        staging = destination  # nothing left to clean up in `finally`
    except Exception:
        if staging.is_dir() and staging.name.startswith(".importing-"):
            shutil.rmtree(staging, ignore_errors=True)
        raise

    # The export zip, so Export works on an imported row like any other.
    # ★ Best-effort: the BUNDLE is the import's product and it is already complete
    #   and in place. `library_archive_path` regenerates this zip on download anyway,
    #   so a failure here must not turn a successful import into an error.
    try:
        _write_export_archive(destination)
    except OSError:
        log.warning("lut: imported '%s' but its export .zip could not be written", site)
    log.info("lut: imported '%s' (%dx%d, %.1f MB) from %s", site, width, height, payload_mb, origin_name)
    return _entry_for(destination, manifest)
