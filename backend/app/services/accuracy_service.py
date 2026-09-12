"""``accuracy_service`` — measure a photograph's REAL geolocation error, then correct it.

★ THE BRIDGE, NOT THE ALGORITHM. The maths is ``app.vendor.geo_accuracy`` (the field
tool's core, vendored verbatim — fix bugs in its standalone home and re-copy). This
module only assembles that core's inputs from LandExplorer's own entities, exactly as
``lut_service`` does for the LUT core:

    intrinsics + distortion   ← the photograph's entered camera (`image_cameras`)
    camera station            ← camera lat/lon → DEM CRS; Z = DEM height + mast height
    pose                      ← Stage A solved from the photograph's committed GCPs
    terrain                   ← this photo's DEM override, else the project's
    satellite reference       ← `ImageryService` (allow-list, cache, ledger, offline)

WHAT THE STAGES DO, and why each is its own step:

* **Stage D — measure** (``start_measure``). Rectifies the photo onto the DEM, fetches
  a satellite mosaic on the same metre grid, and phase-correlates overlapping tiles;
  each locked tile's offset IS the geolocation error there. Minutes, and the only step
  that touches the network — so it is a job, and its result is kept on disk.
* **Stage E/F — correct** (``start_correct``). Re-solves the pose from the locked tiles
  as pseudo-GCPs, builds the residual field, then Stage F's per-region base choice and
  SNR-shrunk subtraction. Seconds, and re-runnable with different options against the
  SAME measurement — which is why it does not repeat Stage D.
* **Suggest** (``start_suggest``). Where the next control point would help most.
  Independent of D/E/F: it needs only the pose, the photo and the DEM.

★ HONESTY IS THE POINT OF THIS FEATURE, and the service must never soften it:

* The correction carries an ACCEPTANCE GATE. When the refinement measures WORSE than
  the raw pose, ``accepted`` is false and the reason says so — the service records that
  verdict and never quietly serves the correction as an improvement.
* The winner is chosen by ``solutions.best_key`` on spatially blocked, buffered
  cross-validation, and it is genuinely not the same stage every time — sometimes it is
  ``raw``, meaning correcting would make things worse.
* Every number is measured against the satellite basemap, which carries its own
  few-metre georeferencing error. That caveat travels in the stored report.

★ RUNS IN A THREAD, TRACKED IN MEMORY, RESULT ON DISK — the same reasoning as
``lut_service``: a stateless file computation that owns no DB row, far past any HTTP
timeout, whose durable record is the folder it writes. A run interrupted by a restart is
simply re-run. No Celery job type, no migration.

Framework-free: no FastAPI, no SQLAlchemy, no Celery. The router owns the DB reads and
hands plain data in.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import UUID

import numpy as np

from app.services.lut_service import GcpPoint

log = logging.getLogger(__name__)

__all__ = [
    "ADOPTABLE_STAGES",
    "AccuracyError",
    "AccuracyRun",
    "CorrectInputs",
    "GcpPoint",
    "MeasureInputs",
    "StageDParams",
    "SuggestInputs",
    "adopt",
    "adopted_pose",
    "clear_adoption",
    "get_run",
    "list_history",
    "list_runs",
    "make_mosaic_writer",
    "materialise_photo",
    "query_pixel",
    "history_layer_path",
    "read_adoption",
    "read_solve_options",
    "read_state",
    "set_solve_options",
    "start_correct",
    "start_measure",
    "start_suggest",
    "store_dir",
]

#: Stage A needs four correspondences; so does everything built on it.
REQUIRED_GCPS = 4

#: A mosaic bigger than this is refused at that zoom, which makes the core's own
#: step-down loop try a coarser one. 900 × 512² tiles ≈ a 15 km square at z17 — far
#: past any single photograph's footprint, so hitting it means the pose is wrong.
MAX_MOSAIC_TILES = 900

#: Usage-ledger bucket for tiles this feature pulls (``imagery_usage``), so a Stage D
#: run is distinguishable from map browsing in ``GET /imagery/usage``.
IMAGERY_SOURCE = "accuracy"

#: Concurrent tile fetches for the satellite mosaic. Small on purpose: the work is
#: network wait, not CPU, and the provider's shared token-bucket limiter — not this
#: number — is what enforces the requests-per-second its terms allow.
MOSAIC_FETCH_WORKERS = 8

#: The heat ramp — pale sand → orange → red → dark red. ★ The SAME four stops the
#: vendored ``error_map_html`` embeds, so the in-app overlay and the downloadable
#: offline report cannot disagree about what a colour means.
_HEAT_STOPS = np.array(
    [[255, 247, 236], [253, 187, 132], [227, 74, 51], [127, 0, 0]], dtype=float
)

RunKind = Literal["measure", "correct", "suggest"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]


class AccuracyError(ValueError):
    """A run that cannot proceed — the message names the fix."""


# ─────────────────────────────────────────────────────────────────────────────
# Inputs — plain data, no ORM rows
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageDParams:
    """The measurement's knobs. Defaults are the field tool's, unchanged.

    ``tile``/``stride``/``max_range`` are the three a surveyor actually touches; the
    rest exist so a difficult scene can be argued with rather than silently accepted.
    """

    gsd: float = 1.0
    max_range: float = 1100.0
    tile: int = 128
    stride: int = 64
    sat_zoom: int = 17
    mi_rescue: bool = True
    fine_pass: bool = True
    # ── the grazing-geometry knobs (2026-09-10) ─────────────────────────────────
    # ★ EVERY DEFAULT HERE IS THE CORE'S OWN, so a request that names none of them
    #   measures exactly what it measured before they existed. They matter for the
    #   cameras this product actually watches: a mast looking kilometres out sees a
    #   tile SHEARED by terrain-height error, not merely shifted, and one measured
    #   with a 25 m ceiling has its real 26-30 m errors censored as false locks.
    #: A larger 'match' than this is a false lock. THE ONE DEFAULT THAT IS NOT THE
    #: ENGINE'S: the engine's 25 m suits a drone, and this product watches fixed
    #: masts at grazing incidence, where 25 m censors real 26-30 m errors as false
    #: locks and silently shrinks the measured set. Upstream's own table names 50 m
    #: for a ground camera (2026-09-10, §8). Recorded in every summary's params, so
    #: a run made under the old default is distinguishable from one made under this.
    max_shift: float = 50.0
    #: Raise the reach when it leaves under 85% of the visible ground inside it — a
    #: COVERAGE rule, not a distance. A drone at 94-100% keeps its numbers; a mast
    #: whose 1100 m circle holds 3% of what it sees would otherwise download a
    #: mosaic centred on the wrong ground and lock nothing, an empty canvas that
    #: reads as a broken tool.
    auto_reach: bool = True
    #: Remove basemap cloud from the content before matching (upstream §10's known
    #: gap, built as the switch it prescribes). Off by default: white roofs can
    #: trigger it. The run always REPORTS how many locked tiles sit on cloud, so a
    #: run with this off says when it should have been on.
    cloud_mask: bool = False
    #: Affine (ECC) third chance for tiles both phase correlation and MI rejected.
    #: Rescue only — it never touches a tile that already locked. Off by default
    #: because it changes WHICH ground gets measured, so an existing measurement
    #: and a new one would no longer be comparable.
    ecc_rescue: bool = False
    #: Choose the tile size from the scene's own geometry instead of the request's.
    tile_auto: bool = False
    #: The DTM's 1-sigma height error. Only scales the reported ``sigma_m``; it
    #: gates nothing on its own.
    sigma_dtm: float = 3.0
    #: >0 drops tiles whose expected sigma exceeds this many metres. 0 = report
    #: the number on every tile and drop none, which is the honest default.
    reliability_max: float = 0.0

    def to_core(self) -> Any:
        """→ ``error_map.Params``. Every other field keeps the core's own default."""
        from app.vendor.geo_accuracy.error_map import Params  # noqa: PLC0415

        return Params(
            gsd=float(self.gsd),
            max_range=float(self.max_range),
            tile=int(self.tile),
            stride=int(self.stride),
            sat_zoom=int(self.sat_zoom),
            mi_rescue=bool(self.mi_rescue),
            fine_pass=bool(self.fine_pass),
            max_shift=float(self.max_shift),
            ecc_rescue=bool(self.ecc_rescue),
            tile_auto=bool(self.tile_auto),
            sigma_dtm=float(self.sigma_dtm),
            reliability_max=float(self.reliability_max),
            cloud_mask=bool(self.cloud_mask),
        )


@dataclass(frozen=True)
class PoseInputs:
    """Everything Stage A needs for THIS photograph, already fetched."""

    image_id: UUID
    project_id: UUID
    photo_path: Path
    dem_path: Path
    #: ★ None is lawful in NO-CALIBRATION mode (2026-09-09): the focal is then SOLVED
    #: from the control points, seeded by ``fov_h_deg`` (or the default seed when
    #: that is blank) — the same path the LUT build and auto-GCP picking take.
    fx: float | None
    fy: float | None
    cx: float | None
    cy: float | None
    k1: float = 0.0
    k2: float = 0.0
    p1: float = 0.0
    p2: float = 0.0
    k3: float = 0.0
    cam_lat: float = 0.0
    cam_lon: float = 0.0
    cam_height_m: float = 0.0
    gcps: tuple[GcpPoint, ...] = ()
    output_dir: Path = Path(".")
    #: How many GCPs the photograph HAS, when that differs from how many were passed.
    #: The read is paginated, so a photograph with more than one page of points would
    #: otherwise be solved on a subset without anyone being told.
    gcps_total: int | None = None
    #: GEO-DRIFT C2/C3, finally applied here too: no measured calibration; the
    #: focal is recovered from the points. ``fov_h_deg`` is only where it starts.
    no_calibration: bool = False
    fov_h_deg: float | None = None


@dataclass(frozen=True)
class MeasureInputs:
    """Stage D. ``mosaic_writer`` is the imagery seam — see :func:`make_mosaic_writer`."""

    pose: PoseInputs
    params: StageDParams = StageDParams()
    mosaic_writer: Callable[..., None] | None = None
    provider_name: str = ""


@dataclass(frozen=True)
class CorrectInputs:
    """Stages E + F + the cross-validated comparison, over a stored measurement."""

    pose: PoseInputs
    use_residual_field: bool = True
    free_focal: bool = False


@dataclass(frozen=True)
class SuggestInputs:
    """Where the next control point should go."""

    pose: PoseInputs
    count: int = 4
    criterion: Literal["ground", "dopt"] = "ground"
    box_frac: float | None = None
    #: Below this predicted cut the panel says "converged" — the surveyor's stop rule.
    stop_below_pct: float = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# The run registry — one entry per job, mutated only under the lock or by its thread
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AccuracyRun:
    run_id: str
    kind: RunKind
    image_id: UUID
    project_id: UUID
    status: RunStatus = "queued"
    progress_pct: int = 0
    message: str = "queued"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None


_LOCK = threading.Lock()
_RUNS: dict[str, AccuracyRun] = {}


def get_run(run_id: str) -> AccuracyRun | None:
    with _LOCK:
        return _RUNS.get(run_id)


def list_runs(image_id: UUID | None = None) -> list[AccuracyRun]:
    with _LOCK:
        runs = list(_RUNS.values())
    if image_id is not None:
        runs = [r for r in runs if r.image_id == image_id]
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


def _active_run_for(image_id: UUID) -> AccuracyRun | None:
    """A photograph runs one stage at a time — they write the same folder."""
    with _LOCK:
        for run in _RUNS.values():
            if run.image_id == image_id and run.status in ("queued", "running"):
                return run
    return None


def _start(kind: RunKind, pose: PoseInputs, target: Callable[[AccuracyRun], None]) -> AccuracyRun:
    busy = _active_run_for(pose.image_id)
    if busy is not None:
        raise AccuracyError(
            f"this photograph already has a {busy.kind} run in progress "
            f"({busy.progress_pct}% — {busy.message}). Wait for it to finish."
        )
    run = AccuracyRun(
        run_id=uuid_mod.uuid4().hex[:12],
        kind=kind,
        image_id=pose.image_id,
        project_id=pose.project_id,
    )
    with _LOCK:
        _RUNS[run.run_id] = run
    threading.Thread(
        target=target, args=(run,), name=f"accuracy-{kind}-{run.run_id}", daemon=True
    ).start()
    return run


# ─────────────────────────────────────────────────────────────────────────────
# Disk — the durable record. One folder per photograph.
# ─────────────────────────────────────────────────────────────────────────────


def store_dir(output_dir: Path, image_id: UUID) -> Path:
    return Path(output_dir) / str(image_id)


#: What lives in a photograph's folder. Named here so the router's download routes and
#: the reader below cannot drift apart.
LAYER_FILES = {
    "ortho": "ortho.jpg",
    "satellite": "satellite.jpg",
    # One name per layer — an alias would make the same file appear twice in the
    # `layers` list the client uses to decide what it may draw.
    "heat_raw": "heat_raw.png",
    "heat_pose": "heat_pose.png",
    "heat_field": "heat_field.png",
    "heat_stagef": "heat_stagef.png",
    # ★ THE SAME HEAT, WARPED TO WEB MERCATOR. The layers above are on the ortho grid
    #   (the DEM's projected CRS); these are the ones the SATELLITE PANE draws, and a
    #   slippy map places an overlay by its lat/lon corners. A UTM-aligned rectangle is
    #   NOT a lat/lon rectangle — dropping the ortho PNG straight onto Leaflet would
    #   shear and rotate it by the meridian convergence, misplacing an ERROR map by
    #   tens of metres. Warping first is what makes the overlay mean what it shows.
    "heat_web_raw": "heat_web_raw.png",
    "heat_web_pose": "heat_web_pose.png",
    "heat_web_field": "heat_web_field.png",
    "heat_web_stagef": "heat_web_stagef.png",
}
_MEASURE_JSON = "measurement.json"
_INSIDE_NPY = "inside.npy"
_CORRECTION_JSON = "correction.json"
_STAGEF_NPZ = "stage_f.npz"
_SOLUTIONS_JSON = "solutions.json"
_SUGGEST_JSON = "suggestions.json"
_ADOPTION_JSON = "adopted.json"
#: ★ How the RAW pose is solved from the control points. Per photograph, on disk,
#: because the loop runs unattended: a choice that lived only in a request body would
#: apply to whichever run the surveyor happened to press and to none of the automatic
#: ones. Currently one flag — see :func:`read_solve_options`.
_SOLVE_OPTIONS_JSON = "solve_options.json"
#: ★ EVERY DEPLOYED HEAT MAP IS KEPT. The loop re-measures after each control point, so
#: the interesting question stops being "how wrong is it" and becomes "is it getting
#: better, and where". That needs the earlier runs still to exist. Each measurement is
#: archived under `history/<version>/` with the layers it produced and the numbers that
#: describe it; the live files stay where they were so nothing else has to change.
_HISTORY_DIR = "history"
#: Versions kept per photograph, pruned oldest-first. Each carries its heat layers and
#: the satellite base they were measured against — ~700 kB a version, so a survey that
#: placed forty points keeps the last twenty rather than all of them.
MAX_HISTORY_VERSIONS = 20
#: ★ THE POSE THIS PHOTOGRAPH'S MEASUREMENTS ARE TAKEN FROM. Written when a refined
#: stage is adopted; absent means the pose solved from the control points. It
#: deliberately SURVIVES a re-measurement (unlike the correction and the comparison,
#: which the new measurement invalidates) — that is what makes the loop iterative:
#: measure → correct → adopt → measure again, each round starting where the last
#: one finished and reporting what is LEFT rather than the same error again.
_BASE_POSE_JSON = "base_pose.json"
_REPORT_HTML = "error_map.html"

#: The stages a surveyor may adopt. ``raw`` is one of them on purpose — "I looked at
#: the comparison and chose to correct nothing" is a decision worth recording, not an
#: absence of one.
ADOPTABLE_STAGES = ("raw", "pose", "field", "stagef")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def materialise_photo(storage: Any, key: str, output_dir: Path, image_id: UUID) -> Path:  # noqa: ANN401
    """A filesystem path OpenCV can open for the stored photograph.

    ★ Fast path: the local backend exposes ``local_path`` — hand back the real file, no
    copy. Any other backend (S3): stream it into the photograph's own accuracy folder.
    Feature-detected, never assumed, exactly as ``video_service._local_file`` does.

    ★ The copy is NOT a temp file, deliberately: a run outlives the request that started
    it, so a ``tempfile`` context manager would delete the photo out from under the
    thread. The folder is this feature's durable record anyway.
    """
    local_path = getattr(storage, "local_path", None)
    if callable(local_path):
        return Path(local_path(key))

    import shutil  # noqa: PLC0415

    folder = store_dir(output_dir, image_id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(key).suffix or ".bin"
    destination = folder / f"photo{suffix}"
    with storage.open(key) as src, destination.open("wb") as out:
        shutil.copyfileobj(src, out)
    return destination


def layer_path(output_dir: Path, image_id: UUID, name: str) -> Path | None:
    filename = LAYER_FILES.get(name)
    if filename is None:
        return None
    path = store_dir(output_dir, image_id) / filename
    return path if path.is_file() else None


def artifact_path(output_dir: Path, image_id: UUID, which: str) -> Path | None:
    """The two downloadable artifacts: the correction JSON and the offline report."""
    names = {"correction": _CORRECTION_JSON, "report": _REPORT_HTML}
    filename = names.get(which)
    if filename is None:
        return None
    path = store_dir(output_dir, image_id) / filename
    return path if path.is_file() else None


# ─────────────────────────────────────────────────────────────────────────────
# Adoption — the surveyor chooses which answer this photograph stands on
# ─────────────────────────────────────────────────────────────────────────────


def read_adoption(output_dir: Path, image_id: UUID) -> dict[str, Any] | None:
    return _read_json(store_dir(output_dir, image_id) / _ADOPTION_JSON)


def _version_id(measured_at: str) -> str:
    """`2026-08-18T15:34:12.123456+00:00` → `20260818T153412` — sortable, path-safe."""
    keep = "".join(ch for ch in measured_at if ch.isdigit())
    return f"{keep[:8]}T{keep[8:14]}" if len(keep) >= 14 else keep or "unknown"


def _archive_version(folder: Path, measurement: dict[str, Any]) -> str:
    """Snapshot the CURRENT layers and numbers as a history version.

    ★ A COPY, not a move. The live files are what every other surface reads; the archive
    exists so an earlier run can still be drawn beside a later one. Called after a
    measurement, and again after a correction adds its per-stage layers to the same
    version — the version is identified by WHEN IT WAS MEASURED, so the correction lands
    in the run it belongs to instead of creating a phantom second entry.
    """
    import shutil  # noqa: PLC0415

    version = _version_id(str(measurement.get("measured_at", "")))
    target = folder / _HISTORY_DIR / version
    target.mkdir(parents=True, exist_ok=True)

    summary = {k: v for k, v in measurement.items() if k != "tiles"}
    summary["version"] = version
    solutions = _read_json(folder / _SOLUTIONS_JSON)
    if solutions is not None:
        best = solutions.get("best")
        entry = next((e for e in solutions.get("entries", []) if e.get("key") == best), None)
        summary["corrected"] = {
            "best": best,
            "label": entry.get("label") if entry else None,
            "all_m": entry.get("all_m") if entry else None,
            "p95_m": entry.get("p95_m") if entry else None,
            "worst20_share": entry.get("worst20_share") if entry else None,
            "corrected_at": solutions.get("corrected_at"),
            "warnings": solutions.get("warnings", []),
        }
        correction = _read_json(folder / _CORRECTION_JSON) or {}
        report = correction.get("report", {})
        summary["gate"] = {
            "accepted": report.get("accepted"),
            "reason": report.get("gate_reason"),
        }
    _write_json(target / "summary.json", summary)

    # ★ THE SATELLITE BASE TRAVELS WITH THE VERSION. It is tempting to skip it — the
    #   ground does not change between runs — but the ORTHO GRID does: a different max
    #   range or GSD produces a different rectangle, and pairing an old heat layer with
    #   a newer base would misalign the very thing the comparison is for. The ortho is
    #   still skipped; nothing draws it.
    for name, filename in LAYER_FILES.items():
        if name == "ortho":
            continue
        source = folder / filename
        if source.is_file():
            shutil.copyfile(source, target / filename)

    _prune_history(folder)
    return version


def _prune_history(folder: Path) -> None:
    import shutil  # noqa: PLC0415

    root = folder / _HISTORY_DIR
    if not root.is_dir():
        return
    versions = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    for stale in versions[:-MAX_HISTORY_VERSIONS]:
        shutil.rmtree(stale, ignore_errors=True)


def list_history(output_dir: Path, image_id: UUID) -> list[dict[str, Any]]:
    """Every archived measurement, newest first — the heat-map version history."""
    root = store_dir(output_dir, image_id) / _HISTORY_DIR
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True):
        summary = _read_json(d / "summary.json")
        if summary is None:
            continue  # a version that cannot state what it measured is not offered
        summary["layers"] = sorted(
            name for name, f in LAYER_FILES.items() if (d / f).is_file()
        )
        out.append(summary)
    return out


def history_layer_path(
    output_dir: Path, image_id: UUID, version: str, name: str
) -> Path | None:
    """One archived layer. Traversal-proof: the version must be one we listed."""
    filename = LAYER_FILES.get(name)
    if filename is None:
        return None
    root = store_dir(output_dir, image_id) / _HISTORY_DIR
    candidate = root / version / filename
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _base_pose_summary(folder: Path) -> dict[str, Any]:
    """What the client needs to know about the base pose — never the matrices."""
    base = _read_json(folder / _BASE_POSE_JSON)
    if base is None:
        return {"source": "gcps", "from_stage": None, "adopted_at": None, "generation": 0}
    return {
        "source": "adopted",
        "from_stage": base.get("from_stage"),
        "adopted_at": base.get("adopted_at"),
        "generation": int(base.get("generation", 1)),
    }


def read_solve_options(output_dir: Path, image_id: UUID) -> dict[str, Any]:
    """How Stage A solves this photograph's pose from its control points.

    ``free_focal`` — solve ONE focal scale alongside the pose (fy follows fx at the
    entered ratio) instead of trusting the calibration's fx/fy exactly.

    ★ OFF BY DEFAULT, and that is not timidity. At grazing geometry focal length trades
    off against tilt: the solver can shorten the lens and tip the camera and fit the
    same control points about as well, so a freed focal can wander a long way from the
    calibrated value while the reprojection barely moves. It is worth freeing when the
    calibration is suspect — a different lens, a zoom that moved, a focal copied from a
    spec sheet — and worth leaving alone when it is not.
    """
    stored = _read_json(store_dir(output_dir, image_id) / _SOLVE_OPTIONS_JSON) or {}
    return {"free_focal": bool(stored.get("free_focal", False))}


def set_solve_options(output_dir: Path, image_id: UUID, *, free_focal: bool) -> dict[str, Any]:
    """Change how the raw pose is solved, and retire everything derived from the old one.

    ★ EVERYTHING DOWNSTREAM IS INVALIDATED, deliberately. The measurement, the
    correction, the comparison and any adopted pose were all computed against a pose
    this flag changes — keeping them would leave numbers on screen that describe a solve
    that no longer exists. They are cleared so the next cycle measures the pose actually
    in force.
    """
    folder = store_dir(output_dir, image_id)
    current = read_solve_options(output_dir, image_id)
    options = {"free_focal": bool(free_focal)}
    if current == options:
        return options

    _write_json(folder / _SOLVE_OPTIONS_JSON, options)
    for stale in (
        _MEASURE_JSON, _INSIDE_NPY, _CORRECTION_JSON, _SOLUTIONS_JSON,
        _STAGEF_NPZ, _ADOPTION_JSON, _BASE_POSE_JSON, _SUGGEST_JSON, _REPORT_HTML,
    ):
        (folder / stale).unlink(missing_ok=True)
    for name in LAYER_FILES.values():
        (folder / name).unlink(missing_ok=True)
    return options


def read_base_pose(output_dir: Path, image_id: UUID) -> dict[str, Any] | None:
    """The pose measurements are taken from, or None for the control-point solve."""
    return _read_json(store_dir(output_dir, image_id) / _BASE_POSE_JSON)


def clear_adoption(output_dir: Path, image_id: UUID) -> None:
    """Stop standing on a correction — and stop measuring from it.

    ★ The base pose goes too. Leaving it behind would mean the surveyor had "cleared"
    the adoption while every future measurement still silently started from it.
    """
    folder = store_dir(output_dir, image_id)
    (folder / _ADOPTION_JSON).unlink(missing_ok=True)
    (folder / _BASE_POSE_JSON).unlink(missing_ok=True)


def adopt(output_dir: Path, image_id: UUID, stage: str) -> dict[str, Any]:
    """Record which stage this photograph's downstream products should stand on.

    ★ DELIBERATELY NARROW. Adopting changes what a LUT BUILD stands on and nothing
    else. The GCPs a surveyor already placed, the coordinates already exported and
    every Auto GCP estimate keep using the pose solved from their own control points —
    a correction measured against a basemap must not silently rewrite coordinates that
    were recorded and signed off against something else. The LUT is the one artefact
    built fresh, on demand, and shipped out of the app, so it is the one that can honour
    a choice made after the fact.

    ★ THE CHOICE IS THE SURVEYOR'S, and it is allowed to disagree with the comparison.
    ``best`` is a recommendation computed on held-out tiles; local knowledge (a feature
    they can see is in the right place) beats it. So any AVAILABLE stage may be adopted
    — including ``raw`` — and the record keeps the numbers as they stood at the time,
    plus whether the choice matched the recommendation. A decision whose provenance is
    unrecorded is indistinguishable from a mistake six months later.

    Raises:
        AccuracyError: Unknown stage, no comparison yet, or a stage that is not
            available for this photograph.
    """
    if stage not in ADOPTABLE_STAGES:
        raise AccuracyError(
            f"'{stage}' is not a stage — choose one of {', '.join(ADOPTABLE_STAGES)}."
        )
    folder = store_dir(output_dir, image_id)
    solutions = _read_json(folder / _SOLUTIONS_JSON)
    if solutions is None:
        raise AccuracyError(
            "there is nothing to adopt yet — measure this photograph and run the "
            "correction first, so there is a comparison to choose from."
        )
    entries = {e["key"]: e for e in solutions.get("entries", [])}
    entry = entries.get(stage)
    if entry is None or not entry.get("available", False):
        available = [k for k, e in entries.items() if e.get("available")]
        raise AccuracyError(
            f"'{stage}' is not available for this photograph "
            f"(available: {', '.join(available) or 'none'})."
        )

    correction = _read_json(folder / _CORRECTION_JSON) or {}
    report = correction.get("report", {})
    best = solutions.get("best", "raw")
    record = {
        "stage": stage,
        "label": entry.get("label", stage),
        "adopted_at": datetime.now(UTC).isoformat(),
        "corrected_at": solutions.get("corrected_at"),
        # The numbers AS THEY STOOD when the choice was made — a later re-measurement
        # clears the adoption rather than quietly re-pointing it at new figures.
        "all_m": entry.get("all_m"),
        "p95_m": entry.get("p95_m"),
        "worst20_share": entry.get("worst20_share"),
        "held_out": bool(entry.get("held_out", False)),
        "recommended": best,
        "matches_recommendation": stage == best,
        # ★ Carried so nothing downstream has to re-derive it: a refused correction can
        #   still be adopted (it is the surveyor's call), but every surface that shows
        #   the adoption shows the refusal with it.
        "gate_accepted": bool(report.get("accepted", stage == "raw")),
        "gate_reason": report.get("gate_reason"),
        "uses_refined_pose": stage != "raw",
    }
    _write_json(folder / _ADOPTION_JSON, record)

    # ── the adopted pose becomes what the NEXT measurement starts from ───────
    # ★ THIS IS WHAT MAKES THE LOOP CONVERGE. Re-measuring from the pose you just
    #   adopted asks a different question from the first run: not "how wrong is the
    #   solve?" but "how much is LEFT after the correction?". Without it, pressing
    #   Measure again would rectify from the control points once more and report the
    #   same error, and adopting would change nothing a surveyor could see.
    if record["uses_refined_pose"]:
        correction_pose = _read_json(folder / _CORRECTION_JSON)
        previous = _read_json(folder / _BASE_POSE_JSON) or {}
        if correction_pose is not None:
            _write_json(
                folder / _BASE_POSE_JSON,
                {
                    "R": correction_pose["R"],
                    "C": correction_pose["C"],
                    "K": correction_pose["K"],
                    "dist": correction_pose["dist"],
                    "from_stage": stage,
                    "adopted_at": record["adopted_at"],
                    "all_m": record["all_m"],
                    # How many refinements deep this pose is. A surveyor reading "3rd
                    # generation" knows the number beside it is a residual, not the
                    # error their control points alone produce.
                    "generation": int(previous.get("generation", 0)) + 1,
                },
            )
    else:
        # Adopting `raw` is a decision to go back to the control points — so the base
        # goes with it, and the next measurement starts where the very first one did.
        (folder / _BASE_POSE_JSON).unlink(missing_ok=True)
    return record


def adopted_pose(output_dir: Path, image_id: UUID) -> dict[str, Any] | None:
    """The refined pose a LUT build should use, or None to use the GCP-solved one.

    ★ POSE ONLY, AND THAT IS A DECISION. ``pose``, ``field`` and ``stagef`` all share
    the same refined R/C/K; what separates them is a GROUND-SPACE correction that
    exists only inside the measured area and is never extrapolated beyond it. A LUT
    covers the whole frame, so baking that part in would correct the middle of the
    scene and not its edges — a discontinuity inside a deliverable that no field unit
    could see or reason about. The refined POSE, by contrast, is six parameters that
    apply everywhere. So the pose travels and the local field does not, and the caller
    is told exactly that (``ground_correction_applied: False``).
    """
    # ★ READ THE BASE POSE, NOT THE ADOPTION RECORD. They can disagree: re-measuring
    #   clears the record (its numbers described the previous run) while the pose it
    #   installed survives, because that pose is what the new measurement was taken
    #   from. The base pose is therefore the honest answer to "what does this
    #   photograph stand on" — and reading the record instead would silently drop a
    #   LUT back onto the control-point solve after a re-measure.
    base = read_base_pose(output_dir, image_id)
    if base is None:
        return None
    record = read_adoption(output_dir, image_id) or {}
    return {
        "stage": base.get("from_stage"),
        "R": np.asarray(base["R"], dtype=float),
        "C": np.asarray(base["C"], dtype=float),
        "K": np.asarray(base["K"], dtype=float),
        "dist": np.asarray(base["dist"], dtype=float),
        "adopted_at": base.get("adopted_at"),
        "all_m": base.get("all_m"),
        "generation": int(base.get("generation", 1)),
        "gate_accepted": record.get("gate_accepted"),
        "ground_correction_applied": False,
        "ground_correction_note": (
            "The refined POSE was used. The local residual field / Stage F subtraction "
            "was not baked in: it is defined only inside the measured area and is never "
            "extrapolated, so applying it would correct part of the frame and not the "
            "rest."
        ),
    }


def read_state(output_dir: Path, image_id: UUID) -> dict[str, Any]:
    """Everything stored for one photograph, assembled for the UI.

    ★ DISK IS THE RECORD, not the in-memory registry: a measurement outlives an API
    restart, so the page a surveyor comes back to tomorrow still has its result.
    """
    folder = store_dir(output_dir, image_id)
    measurement = _read_json(folder / _MEASURE_JSON)
    state: dict[str, Any] = {
        "image_id": str(image_id),
        "measurement": measurement,
        "correction": None,
        "solutions": _read_json(folder / _SOLUTIONS_JSON),
        "suggestions": _read_json(folder / _SUGGEST_JSON),
        "adoption": _read_json(folder / _ADOPTION_JSON),
        "solve_options": {
            "free_focal": bool(
                (_read_json(folder / _SOLVE_OPTIONS_JSON) or {}).get("free_focal", False)
            )
        },
        # ★ Survives a re-measurement, unlike the adoption record — so the UI can keep
        #   saying which pose the numbers on screen are relative to.
        "base_pose": _base_pose_summary(folder),
        "layers": sorted(
            {name for name, f in LAYER_FILES.items() if (folder / f).is_file()}
        ),
        "report_available": (folder / _REPORT_HTML).is_file(),
        "correction_available": (folder / _CORRECTION_JSON).is_file(),
    }
    correction = _read_json(folder / _CORRECTION_JSON)
    if correction is not None:
        # ★ The report is the honest half — gate verdict, before/after per band. The
        #   pose matrices stay in the file for a LUT rebuild or an external script;
        #   the UI has no use for them.
        state["correction"] = correction.get("report")
    return state


# ─────────────────────────────────────────────────────────────────────────────
# The satellite seam — a mosaic writer backed by the app's own imagery service
# ─────────────────────────────────────────────────────────────────────────────


def make_mosaic_writer(imagery: Any, provider_name: str) -> Callable[..., None]:  # noqa: ANN401
    """A ``mosaic_writer`` for ``error_map.fetch_satellite``, fed by ``ImageryService``.

    ★ WHY NOT CALL A PROVIDER DIRECTLY (as the standalone tool does): routing through
    the service is what keeps ``LE_ALLOWED_PROVIDERS``, the disk tile cache, the usage
    ledger and offline mode in force for this stage. A Stage D run over a 1 km scene is
    hundreds of tiles — precisely the traffic those mechanisms exist to govern.

    ★ LICENCE GATE. The mosaic is written to disk, which is exactly what
    ``allows_caching`` governs (``ProviderCapabilities``: "False makes the cache REFUSE
    the write"). A provider whose terms forbid storing tiles is therefore refused here
    by the same flag, with the fix named — not quietly worked around.

    Raises:
        AccuracyError: The provider forbids storing its tiles.
    """
    caps = imagery.capabilities(provider_name)
    if not caps.allows_caching:
        raise AccuracyError(
            f"'{provider_name}' does not permit its tiles to be stored, and the "
            "measurement writes a satellite mosaic to disk. Choose a provider that "
            "allows caching (Mapbox or Esri) for the accuracy check."
        )
    tile_size = int(caps.tile_size_px)

    def write(lat: float, lon: float, *, radius_m: float, zoom: int, out_path: str, epsg: int) -> None:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        import cv2  # noqa: PLC0415 — heavy; only a run needs them
        import rasterio  # noqa: PLC0415
        from affine import Affine  # noqa: PLC0415
        from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: PLC0415

        from gis.tiles import (  # noqa: PLC0415
            bbox_to_tile_range,
            lonlat_to_meters,
            meters_to_lonlat,
            stitch_tiles,
            tile_range_count,
        )
        from gis.types import BBox, TileRef  # noqa: PLC0415

        # ── ground radius → a lon/lat box ────────────────────────────────────
        # ★ Web-Mercator metres are inflated by 1/cos(lat); converting a GROUND
        #   radius as if it were mercator metres would under-cover the scene by that
        #   factor (30% at 40° N) and the far tiles would come back black.
        mx, my = lonlat_to_meters(lon, lat)
        span = float(radius_m) / max(math.cos(math.radians(lat)), 1e-6)
        west, south = meters_to_lonlat(mx - span, my - span)
        east, north = meters_to_lonlat(mx + span, my + span)
        rng = bbox_to_tile_range(BBox(west=west, south=south, east=east, north=north), zoom)

        count = tile_range_count(rng)
        if count > MAX_MOSAIC_TILES:
            # ★ "cap" in the message is the core's step-down protocol — it retries a
            #   zoom coarser rather than failing the run.
            raise RuntimeError(
                f"satellite mosaic would need {count} tiles at z{zoom}, over the "
                f"{MAX_MOSAIC_TILES} cap"
            )

        # ★ FETCHED CONCURRENTLY, AND THAT IS THE DIFFERENCE BETWEEN A USABLE FEATURE
        #   AND AN ABANDONED ONE. Each tile is a TLS round trip to the provider —
        #   measured at ~2 s apiece — and a 1 km scene at z17 needs on the order of a
        #   hundred. Serially that is four minutes with the progress bar apparently
        #   frozen; the work is entirely network wait, so a small pool collapses it to
        #   seconds. The provider's own shared token-bucket limiter still governs the
        #   REQUEST RATE (`get_limiter` in `gis.imagery.ratelimit`), so this raises
        #   concurrency without raising the rate past what its terms allow.
        refs = [
            TileRef(z=zoom, x=x, y=y)
            for x in range(rng.min_x, rng.max_x + 1)
            for y in range(rng.min_y, rng.max_y + 1)
        ]
        report = getattr(write, "on_tile_progress", None)

        def fetch(ref: Any) -> tuple[Any, np.ndarray | None]:  # noqa: ANN401
            try:
                raw, _mime = imagery.get_tile_bytes(
                    provider_name, ref.z, ref.x, ref.y, source=IMAGERY_SOURCE
                )
            except Exception:  # noqa: BLE001 — one dead tile must not kill the run
                return ref, None
            decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if decoded is None or decoded.shape[0] != tile_size:
                return ref, None
            return ref, cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)

        tiles: dict[Any, np.ndarray] = {}
        missing = 0
        done = 0
        with ThreadPoolExecutor(max_workers=MOSAIC_FETCH_WORKERS) as pool:
            for ref, image in pool.map(fetch, refs):
                done += 1
                if image is None:
                    missing += 1
                else:
                    tiles[ref] = image
                if report is not None and (done % 5 == 0 or done == len(refs)):
                    # A run that looks stalled gets abandoned. Counting tiles is the
                    # only honest way to say "still working" during the one step whose
                    # duration the app does not control.
                    report(done, len(refs))

        if not tiles:
            raise AccuracyError(
                f"no satellite tiles could be fetched from '{provider_name}' — check "
                "the provider's configuration, or the network if this run is online."
            )
        if missing:
            # ★ Never silent: a hole in the mosaic becomes tiles that cannot lock, and
            #   the match rate would be blamed on the flight instead of the imagery.
            log.warning(
                "accuracy mosaic: %d of %d tiles missing from %s at z%d",
                missing, count, provider_name, zoom,
            )

        mosaic, gt = stitch_tiles(tiles, rng, tile_size=tile_size)

        # ── EPSG:3857 mosaic → a GeoTIFF in the DEM's CRS ────────────────────
        # The core's `_covers` check compares the cached file's EPSG with the DEM's, so
        # writing it already reprojected is what makes the per-flight cache reusable.
        src_transform = Affine.from_gdal(*gt)
        height, width = mosaic.shape[:2]
        src_crs = "EPSG:3857"
        dst_crs = f"EPSG:{int(epsg)}"
        bounds = rasterio.transform.array_bounds(height, width, src_transform)
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src_crs, dst_crs, width, height, *bounds
        )
        out = np.zeros((3, dst_h, dst_w), np.uint8)
        for band in range(3):
            reproject(
                source=np.ascontiguousarray(mosaic[:, :, band]),
                destination=out[band],
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            out_path, "w", driver="GTiff", height=dst_h, width=dst_w, count=3,
            dtype="uint8", crs=dst_crs, transform=dst_transform, compress="deflate",
        ) as dst:
            dst.write(out)

    return write


# ─────────────────────────────────────────────────────────────────────────────
# Shared front half — prerequisites → the solved pose (mirrors AutoGcpService._solve)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Scene:
    """The photograph, its terrain and its solved pose — what every stage starts from."""

    photo: np.ndarray
    dem: Any
    rotation: np.ndarray
    camera_xyz: np.ndarray
    k_matrix: np.ndarray
    dist: np.ndarray
    cam_lat: float
    cam_lon: float
    gcps_used: int
    reproj_mean_px: float
    reproj_max_px: float
    warnings: list[str]
    #: Where the geometry above came from — the control points, or a pose the surveyor
    #: adopted. Travels into the measurement so no number is read as answering a
    #: question it does not.
    base_pose: dict[str, Any] | None = None
    #: How the raw solve was run, and what it did to the lens. When ``free_focal`` is
    #: on, ``solved_focal_px`` is what the solver chose and ``entered_focal_px`` is the
    #: calibration it was allowed to leave — the gap between them is the whole reason
    #: the option is worth a tick rather than a default.
    free_focal: bool = False
    solved_focal_px: float = 0.0
    entered_focal_px: float = 0.0


def _reproject(
    obj: np.ndarray, img: np.ndarray, rotation: np.ndarray, camera_xyz: np.ndarray,
    k_matrix: np.ndarray, dist: np.ndarray,
) -> np.ndarray:
    """Per-point reprojection error, px, of the control points under any pose."""
    import cv2  # noqa: PLC0415

    out = np.full(len(obj), np.nan)
    in_front = ((obj - camera_xyz) @ rotation[2]) > 0
    if not np.any(in_front):
        return out
    projected, _ = cv2.projectPoints(
        obj[in_front].reshape(-1, 1, 3),
        cv2.Rodrigues(rotation)[0],
        (-rotation @ camera_xyz).reshape(3, 1),
        k_matrix,
        dist,
    )
    out[in_front] = np.linalg.norm(projected.reshape(-1, 2) - img[in_front], axis=1)
    return out


def _load_scene(pose: PoseInputs) -> _Scene:
    """Photo + DEM + Stage A, with 422-grade messages naming what is missing.

    ★ The SAME image-overrides-project DEM rule and the same solve as
    ``AutoGcpService`` — the router resolves which DEM applies and passes the path, so
    a measurement can never be taken against a different surface from the one Auto GCP
    raycasts.
    """
    import cv2  # noqa: PLC0415

    from app.vendor.geo_accuracy import geo_io, stage_a  # noqa: PLC0415

    # ★ NO CALIBRATION IS NOT NO INTRINSICS (2026-09-09). A station in that mode
    #   has no fx/fy on purpose — the focal is solved from the points below, so the
    #   only thing to refuse is a calibrated station with holes in it.
    missing = (
        []
        if pose.no_calibration
        else [n for n in ("fx", "fy", "cx", "cy") if getattr(pose, n) is None]
    )
    if missing:
        raise AccuracyError(
            "the photograph's camera has no intrinsics ("
            + ", ".join(missing)
            + " unset) — fill them in on its setup page, or switch on no-calibration mode."
        )
    if len(pose.gcps) < REQUIRED_GCPS:
        raise AccuracyError(
            f"the photograph has {len(pose.gcps)} committed GCP(s); the pose solve "
            f"needs at least {REQUIRED_GCPS}. Place more in the editor and try again."
        )
    if not pose.photo_path.is_file():
        raise AccuracyError("the photograph's image file is missing from storage.")
    if not pose.dem_path.is_file():
        raise AccuracyError(
            "there is no DEM for this photograph — attach one for this image, or a "
            "project DEM, first. Every stage here rectifies the photo onto the terrain."
        )

    bgr = cv2.imread(str(pose.photo_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise AccuracyError("the photograph could not be decoded as an image.")
    photo = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    try:
        dem = geo_io.DEM(str(pose.dem_path))
    except ValueError as exc:  # the core names the fix (geographic CRS, odd pixel size)
        raise AccuracyError(str(exc)) from exc

    warnings: list[str] = []
    if pose.gcps_total is not None and pose.gcps_total > len(pose.gcps):
        warnings.append(
            f"this photograph has {pose.gcps_total} control points but the solve used "
            f"the first {len(pose.gcps)} — the read is paginated. The measurement is "
            "still valid, but it does not stand on every point you placed."
        )

    # ── correspondences, in the DEM's CRS ────────────────────────────────────
    obj: list[tuple[float, float, float]] = []
    img: list[tuple[float, float]] = []
    for g in pose.gcps:
        x, y = dem.lonlat_to_xy(g.lon, g.lat)
        z = g.elevation_m if g.elevation_m is not None else dem.Z(x, y)
        if z is None or not np.isfinite(z):
            continue
        obj.append((float(x), float(y), float(z)))
        img.append((float(g.u), float(g.v)))
    if len(obj) < REQUIRED_GCPS:
        raise AccuracyError(
            f"only {len(obj)} of {len(pose.gcps)} GCPs have a usable elevation (the "
            "rest fall outside this photograph's DEM); the pose solve needs at least "
            f"{REQUIRED_GCPS} inside it."
        )
    if len(obj) < len(pose.gcps):
        warnings.append(
            f"{len(pose.gcps) - len(obj)} GCP(s) fall outside the DEM and were left "
            "out of the solve."
        )

    # ── the entered station: ground + mast, in the DEM's CRS ─────────────────
    x0, y0 = dem.lonlat_to_xy(pose.cam_lon, pose.cam_lat)
    ground = dem.Z(x0, y0)
    if not np.isfinite(ground):
        raise AccuracyError(
            "the camera position falls outside this photograph's DEM — check its "
            "latitude/longitude on the setup page."
        )
    cam_c = np.array([x0, y0, float(ground) + float(pose.cam_height_m)])

    if pose.no_calibration:
        # ★ THE SEED IS WHERE THE SEARCH STARTS, NOT THE ANSWER (the calibration
        #   study: 37–61 m of ground error with a frozen guessed focal, 2 m solved).
        #   K is seeded from the field of view — typed, or the default when blank —
        #   and the focal is recovered by the bounded search the LUT build uses, so
        #   the measurement stands on the same lens the table does. The principal
        #   point sits at the image centre and distortion is zero, as in that mode.
        from app.services.intrinsics import k_from_fov, seed_fov  # noqa: PLC0415
        from app.vendor.lut_generator.pose import solve_pose_free_focal  # noqa: PLC0415

        fov_seed, seed_span, seed_defaulted = seed_fov(pose.fov_h_deg)
        h_px, w_px = photo.shape[:2]
        k_seed, dist, _fov_v = k_from_fov(int(w_px), int(h_px), fov_seed)
        try:
            _r, _c, _rep, k_matrix = solve_pose_free_focal(
                np.array(obj), np.array(img), k_seed, dist, cam_c, span=seed_span
            )
        except Exception as exc:  # noqa: BLE001 — the seed stands when the search cannot improve it
            k_matrix = k_seed
            warnings.append(f"the focal solve fell back to the field-of-view seed ({exc}).")
        fov_solved = 2.0 * math.degrees(math.atan(w_px / (2.0 * float(k_matrix[0, 0]))))
        warnings.append(
            "no calibration: the focal was solved from the control points "
            f"({fov_solved:.1f}° field of view, fx {float(k_matrix[0, 0]):.1f} px), seeded at "
            f"{fov_seed:.0f}°" + (" — the default, no field of view is set" if seed_defaulted else "")
            + "."
        )
    else:
        k_matrix = np.array(
            [[pose.fx, 0.0, pose.cx], [0.0, pose.fy, pose.cy], [0.0, 0.0, 1.0]], dtype=float
        )
        dist = np.array([pose.k1, pose.k2, pose.p1, pose.p2, pose.k3], dtype=float)

    options = read_solve_options(pose.output_dir, pose.image_id)
    try:
        sol = stage_a.solve_pose(
            np.array(obj), np.array(img), k_matrix, dist, cam_c,
            free_focal=options["free_focal"],
        )
    except Exception as exc:  # noqa: BLE001 — the core raises RuntimeError/cv2.error
        raise AccuracyError(
            f"the camera pose could not be solved from these GCPs ({exc}). Spread the "
            "points out — clustered or collinear points are degenerate."
        ) from exc

    reproj = np.asarray(sol["reproj"], dtype=float)
    rotation = np.asarray(sol["R"], dtype=float)
    # ★ With a freed focal the SOLVED K is what everything downstream uses, and the
    #   residuals above are already measured through it (the core recomputes them).
    #   Carrying the entered fx here instead would describe a lens that was not used.
    solved_focal = float(np.asarray(sol["K"], dtype=float)[0, 0])
    camera_xyz = np.asarray(sol["C"], dtype=float)
    k_matrix = np.asarray(sol["K"], dtype=float)

    # ── an adopted pose supersedes the control-point solve ───────────────────
    # ★ The solve above still runs, and its reprojection numbers still travel: they say
    #   how the adopted pose fits the surveyor's OWN points, which is the trade they
    #   accepted when they adopted it. What changes is the geometry every stage then
    #   uses — so a re-measurement reports what is LEFT after the correction, not the
    #   error the control points alone produce.
    base = read_base_pose(pose.output_dir, pose.image_id)
    base_meta: dict[str, Any] | None = None
    if base is not None:
        rotation = np.asarray(base["R"], dtype=float)
        camera_xyz = np.asarray(base["C"], dtype=float)
        k_matrix = np.asarray(base["K"], dtype=float)
        # ★ RE-STATE THE FIT AGAINST THE POSE ACTUALLY IN USE. Carrying the solve's own
        #   residuals here would describe a pose that is not the one anything below
        #   uses. Measured against the surveyor's control points, the adopted pose
        #   usually fits them a little worse — it was fitted to the basemap — and that
        #   is the trade they accepted, so it is reported rather than hidden.
        reproj = _reproject(np.array(obj), np.array(img), rotation, camera_xyz, k_matrix, dist)
        base_meta = {
            "source": "adopted",
            "from_stage": base.get("from_stage"),
            "adopted_at": base.get("adopted_at"),
            "generation": int(base.get("generation", 1)),
        }
    else:
        base_meta = {"source": "gcps", "from_stage": None, "adopted_at": None, "generation": 0}

    return _Scene(
        photo=photo,
        dem=dem,
        rotation=rotation,
        camera_xyz=camera_xyz,
        k_matrix=k_matrix,
        dist=dist,
        cam_lat=float(pose.cam_lat),
        cam_lon=float(pose.cam_lon),
        gcps_used=len(obj),
        # nan-aware: a point behind the adopted camera has no reprojection, and one
        # such point must not turn the whole diagnostic into NaN.
        reproj_mean_px=float(np.nanmean(reproj)) if np.any(np.isfinite(reproj)) else float("nan"),
        reproj_max_px=float(np.nanmax(reproj)) if np.any(np.isfinite(reproj)) else float("nan"),
        warnings=warnings,
        base_pose=base_meta,
        free_focal=bool(options["free_focal"]),
        solved_focal_px=solved_focal,
        entered_focal_px=float(k_matrix[0, 0]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers — the layers the UI draws
# ─────────────────────────────────────────────────────────────────────────────


def _write_jpg(path: Path, rgb: np.ndarray, quality: int = 88) -> None:
    import cv2  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])


def _write_heat_png(path: Path, grid: np.ndarray | None, vmax: float) -> bool:
    """The heat overlay as a transparent PNG — same ramp as the offline report.

    ★ ONE SHARED SCALE. ``vmax`` is always the RAW error's, for every stage, so
    switching from raw to a correction visibly shrinks the colour rather than
    re-normalising and looking identical.
    """
    import cv2  # noqa: PLC0415

    if grid is None:
        return False
    t = np.clip(np.nan_to_num(grid, nan=0.0) / max(vmax, 1e-6), 0, 1)
    idx = np.clip(t * 3, 0, 2.999)
    lo = np.floor(idx).astype(int)
    fr = (idx - lo)[..., None]
    rgb = (_HEAT_STOPS[lo] * (1 - fr) + _HEAT_STOPS[lo + 1] * fr).astype(np.uint8)
    alpha = np.where(np.isnan(grid), 0, 165).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return True


def _write_heat_web(
    path: Path,
    grid: np.ndarray | None,
    vmax: float,
    *,
    origin: tuple[float, float],
    cell_m: float,
    epsg: int,
) -> dict[str, float] | None:
    """The same heat, warped to Web Mercator, with the lat/lon corners to place it by.

    ★ WHY WARP AT ALL. A slippy map positions an overlay by its lat/lon corners and
    stretches it linearly between them. The heat grid is north-up in the DEM's
    PROJECTED CRS, and a UTM rectangle is not a lat/lon rectangle: dropping it straight
    on would rotate it by the meridian convergence and stretch it by the scale factor —
    misplacing an ERROR map by tens of metres, which is worse than not drawing one.
    Warping to EPSG:3857 first makes the corners exact, because the map itself is 3857.

    Returns the bounds as ``{south, west, north, east}`` in degrees, or None.
    """
    import cv2  # noqa: PLC0415
    import rasterio  # noqa: PLC0415
    from affine import Affine  # noqa: PLC0415
    from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: PLC0415

    from gis.tiles import meters_to_lonlat  # noqa: PLC0415

    if grid is None:
        return None
    t = np.clip(np.nan_to_num(grid, nan=0.0) / max(vmax, 1e-6), 0, 1)
    idx = np.clip(t * 3, 0, 2.999)
    lo = np.floor(idx).astype(int)
    fr = (idx - lo)[..., None]
    rgb = (_HEAT_STOPS[lo] * (1 - fr) + _HEAT_STOPS[lo + 1] * fr).astype(np.uint8)
    alpha = np.where(np.isnan(grid), 0, 165).astype(np.uint8)
    bands = np.dstack([rgb, alpha]).astype(np.uint8)

    height, width = grid.shape[:2]
    # `origin` is the ortho grid's cell CENTRE; a raster's origin is its NW EDGE.
    src_transform = Affine.from_gdal(
        origin[0] - cell_m / 2, cell_m, 0.0, origin[1] + cell_m / 2, 0.0, -cell_m
    )
    src_crs = f"EPSG:{int(epsg)}"
    dst_crs = "EPSG:3857"
    src_bounds = rasterio.transform.array_bounds(height, width, src_transform)
    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, dst_crs, width, height, *src_bounds
    )
    out = np.zeros((4, dst_h, dst_w), np.uint8)
    for band in range(4):
        reproject(
            source=np.ascontiguousarray(bands[:, :, band]),
            destination=out[band],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            # ★ NEAREST for the alpha channel would hard-edge the coverage mask, but
            #   bilinear on all four keeps the overlay's edge as soft as the data.
            resampling=Resampling.bilinear,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.moveaxis(out, 0, 2)
    cv2.imwrite(str(path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))

    west_m, south_m, east_m, north_m = rasterio.transform.array_bounds(
        dst_h, dst_w, dst_transform
    )
    west, south = meters_to_lonlat(west_m, south_m)
    east, north = meters_to_lonlat(east_m, north_m)
    return {
        "south": float(south), "west": float(west),
        "north": float(north), "east": float(east),
    }


def _amplification_summary(locked: list[dict[str, Any]], sigma_dtm: float) -> dict[str, Any] | None:
    """How much this scene's geometry multiplies terrain-height error.

    ★ WHY IT IS REPORTED AS A SPREAD AND NOT ONE NUMBER. The near ground and the
    far ground of a grazing view amplify very differently, and the median alone
    would hide that. The p90 is the one to read when deciding whether a scene is
    measurable at all: it is what the worst usable tiles are carrying.

    ★ PIXEL-WEIGHTED, over the locked tiles — one tile, one vote. An area-weighted
    figure over ground cells reads higher on the same scene, so the convention is
    stated here and in the field's name rather than left for a reader to guess.
    """
    values = [t["amplification"] for t in locked if t.get("amplification") is not None]
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    return {
        "median": round(median, 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "max": round(float(arr.max()), 2),
        "tiles": int(arr.size),
        "weighting": "per locked tile",
        #: What the median amplification implies at this DTM's 1-sigma — the floor
        #: under the measured error that no pose correction can lift.
        "expected_sigma_m": round(median * float(sigma_dtm), 2),
        "sigma_dtm_m": float(sigma_dtm),
    }


def _round_or_none(value: Any, digits: int) -> float | None:
    """Round a number the core may not have computed, keeping null as null.

    ★ A tile whose ground centre could not be read carries ``None`` rather than a
    zero: 0 amplification is a claim (an exactly vertical view), and absence is not.
    """
    return None if value is None else round(float(value), digits)


def _tile_rows(result: Any) -> list[dict[str, Any]]:  # noqa: ANN401 — the core's Result
    """Per-tile vectors for the UI's arrows, rounded to what a surveyor can read.

    ★ REJECTED TILES TRAVEL TOO (``ok: false``). A map that showed only the locks would
    imply the unmeasured ground was fine; the UI greys them instead.
    """
    return [
        {
            "x": round(t["x0"] + t["tile"] / 2, 1),
            "y": round(t["y0"] + t["tile"] / 2, 1),
            "tile_px": int(t["tile"]),
            "dE": round(float(t["dE"]), 2),
            "dN": round(float(t["dN"]), 2),
            "err": round(float(t["err"]), 2),
            "radial": round(float(t.get("radial", 0.0)), 2),
            "tangential": round(float(t.get("tangential", 0.0)), 2),
            "range_m": round(float(t["range"])),
            "response": round(float(t["resp"]), 3),
            "method": str(t.get("method", "phase")),
            "ok": bool(t["ok"]),
            # ★ HOW MUCH THIS TILE'S NUMBER IS WORTH (2026-09-10). `amplification`
            #   is how far a metre of DTM height error moves this tile's ground
            #   intersection; `sigma_m` is that times the DTM's own 1-sigma. Two
            #   tiles reading 8 m are not equal evidence when one amplifies 2x and
            #   the other 6x. Null on a tile whose ground centre could not be read.
            "amplification": _round_or_none(t.get("amplification"), 2),
            "sigma_m": _round_or_none(t.get("sigma_m"), 2),
        }
        for t in result.tiles
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Stage D — measure
# ─────────────────────────────────────────────────────────────────────────────


#: Under this many locked tiles a zone reports "no data", never a colour. A
#: confident colour resting on two tiles would be a lie.
ZONE_MIN_TILES = 5

#: A locked tile with more than this share of its footprint on basemap cloud is
#: counted as "on cloud" — upstream's own cut when it measured the contamination.
CLOUD_TILE_FRACTION = 0.25


def cloud_report(result: Any, core_params: Any) -> dict[str, Any]:  # noqa: ANN401
    """How much of the basemap content is cloud, and how many locked tiles sit on it.

    ★ COMPUTED WHETHER OR NOT THE MASK RAN. With the switch off this is the signal to
    turn it on; with it on, `locked_tiles_on_cloud` is what slipped past the mask's
    `min_valid` gate (a tile a quarter on cloud is still three-quarters content).
    The fraction is over the content the photograph covers, so it reads the same
    whichever way the switch was set: when the mask ran, `result.inside` already
    excludes the cloud, and the content is put back for the denominator.
    """
    from app.vendor.geo_accuracy import error_map  # noqa: PLC0415

    masked = bool(core_params.cloud_mask)
    if masked and result.cloud is not None:
        cloud = np.asarray(result.cloud, bool)
        content = np.asarray(result.inside, bool) | cloud
    else:
        content = np.asarray(result.inside, bool)
        cloud = error_map.cloud_mask(result.sat, content, core_params)
    on_cloud = 0
    for t in result.good:
        y0, x0, size = int(t["y0"]), int(t["x0"]), int(t["tile"])
        patch = cloud[y0:y0 + size, x0:x0 + size]
        if patch.size and float(patch.mean()) > CLOUD_TILE_FRACTION:
            on_cloud += 1
    return {
        "masked": masked,
        "content_fraction": round(float(cloud.sum()) / max(float(content.sum()), 1.0), 4),
        "locked_tiles_on_cloud": on_cloud,
        "tile_fraction_threshold": CLOUD_TILE_FRACTION,
    }


#: The share of the visible ground the reach must contain before it is left alone.
REACH_MIN_COVERAGE = 0.85
#: The reach is never raised past this — the request schema's own ceiling, and the
#: point past which a mosaic is a download the surveyor did not ask for.
REACH_CAP_M = 5000.0
#: Rays are traced no further than this when sampling the view. A pixel whose ray
#: hits nothing within it is sky, or ground no reach could contain.
_VIEW_SAMPLE_RANGE_M = REACH_CAP_M
_VIEW_SAMPLE_GRID = (32, 18)


def view_ranges(scene: _Scene, grid: tuple[int, int] = _VIEW_SAMPLE_GRID) -> np.ndarray:
    """Ground range at a grid of frame pixels — the ranges of the ground the camera SEES.

    ★ SAMPLED, NOT EXHAUSTIVE: a ray per pixel of a 1920x1080 frame is two million
    marches through the DEM. A 32x18 grid answers "what share of the view is inside
    the reach" to within a per cent, which is all the rule needs. Pixels whose ray
    misses the terrain (sky, or ground beyond the cap) are left out: they are not
    ground the reach could contain.
    """
    from app.vendor.geo_accuracy import stage_b  # noqa: PLC0415

    height, width = scene.photo.shape[:2]
    camera = scene.camera_xyz
    out: list[float] = []
    for v in np.linspace(2.0, height - 3.0, grid[1]):
        for u in np.linspace(2.0, width - 3.0, grid[0]):
            hit = stage_b.raycast(
                float(u), float(v), scene.rotation, camera, scene.k_matrix, scene.dist,
                scene.dem.Z, scene.dem.res, max_range=_VIEW_SAMPLE_RANGE_M,
            )
            if hit is not None:
                out.append(float(np.hypot(hit[0] - camera[0], hit[1] - camera[1])))
    return np.asarray(out, dtype=float)


def coverage_at(ranges: np.ndarray, reach_m: float) -> float:
    """The share of the visible ground inside ``reach_m``. 0 when nothing is visible."""
    if ranges.size == 0:
        return 0.0
    return float(np.mean(ranges <= reach_m))


def resolve_reach(ranges: np.ndarray, requested_m: float) -> dict[str, Any]:
    """Apply the coverage rule to a requested reach.

    ★ RAISED ONLY WHEN THE RULE SAYS SO, AND THEN TO THE SCENE'S OWN FAR EDGE. Under
    85% coverage the reach becomes the 98th percentile of the visible ground's range
    — the farthest ray with the handful of horizon pixels dropped, so one sliver of
    sky-line at 4 km does not fetch a 4 km mosaic — rounded up to the next 100 m and
    capped. At or above 85% the request stands untouched, which is what keeps a
    drone flight's published numbers where they were.
    """
    requested = float(requested_m)
    before = coverage_at(ranges, requested)
    used = requested
    raised = False
    if ranges.size and before < REACH_MIN_COVERAGE:
        far = float(np.percentile(ranges, 98))
        candidate = min(REACH_CAP_M, float(np.ceil(far / 100.0) * 100.0))
        if candidate > requested:
            used, raised = candidate, True
    return {
        "requested_m": requested,
        "used_m": used,
        "coverage_requested": round(before, 3),
        "coverage_used": round(coverage_at(ranges, used), 3),
        "raised": raised,
        "min_coverage": REACH_MIN_COVERAGE,
        "cap_m": REACH_CAP_M,
        "visible_samples": int(ranges.size),
    }


def _photo_zones(scene: _Scene, result: Any, log: Any = None) -> dict[str, Any] | None:  # noqa: ANN401
    """The nine range zones on the photograph, and the error measured in each.

    ★ THE MEASUREMENT PUT BACK IN THE FRAME. Stage D's tiles live on the ground; the
    surveyor's question is asked at the photograph — "is the far left of what I see
    trustworthy?". Three range bands x three image columns, each carrying the median
    error of the locked tiles inside it and how many tiles that number rests on.

    ★ THE BAND EDGES BEND. For a sample of columns the ray from the camera is marched
    through the terrain from the bottom row upward and bisected for the row where the
    ground range crosses each edge; joining those points gives an iso-range contour
    that follows the terrain. A straight horizontal line would be wrong by hundreds
    of metres on any real slope.

    ★ BANDS ARE THIRDS OF THE FARTHEST LOCK, cut from the scene rather than fixed in
    metres, so a drone at 300 m and a mast at 3 km both get three populated bands.

    ★ NEVER FAILS THE RUN. It needs the DEM still open, so it is called inside the
    measurement's own try; a scene where the tracing finds nothing returns None and
    the measurement stands without it.
    """
    from app.vendor.geo_accuracy import stage_b, zone_overlay  # noqa: PLC0415

    tiles = [
        t for t in result.good
        if t.get("cE") is not None and t.get("cN") is not None
        and np.isfinite(float(t.get("range", np.nan)))
    ]
    if not tiles:
        return None
    height, width = scene.photo.shape[:2]
    rmax = max(float(t["range"]) for t in tiles)
    bands = [rmax / 3.0, 2.0 * rmax / 3.0, rmax]
    rotation, camera, k_matrix, dist = (
        scene.rotation, scene.camera_xyz, scene.k_matrix, scene.dist
    )
    dem = scene.dem

    def range_at(u: float, v: float) -> float | None:
        hit = stage_b.raycast(
            float(u), float(v), rotation, camera, k_matrix, dist, dem.Z, dem.res,
            max_range=1.2 * rmax,
        )
        if hit is None:
            return None
        return float(np.hypot(hit[0] - camera[0], hit[1] - camera[1]))

    if log is not None:
        log("tracing the range zones on the photograph...")
    curves = zone_overlay.iso_range_curves(bands, range_at, width, height)
    if not curves:
        return None

    xyz = np.array([[float(t["cE"]), float(t["cN"]), float(dem.Z(t["cE"], t["cN"]))] for t in tiles])
    ok = np.isfinite(xyz[:, 2])
    tiles = [t for t, k in zip(tiles, ok, strict=True) if k]
    if not tiles:
        return None
    uv = zone_overlay.project_uv(xyz[ok], rotation, camera, k_matrix, dist)
    stats, rng = zone_overlay.zone_stats(
        [{"range": float(t["range"]), "err": float(t["err"])} for t in tiles],
        bands, uv, width, min_tiles=ZONE_MIN_TILES,
    )
    cells = []
    for bi in range(len(bands)):
        for ci, col in enumerate(zone_overlay.COLS):
            n, med = stats.get((bi, ci), (0, float("nan")))
            cells.append({
                "band": bi,
                "column": col,
                "tiles": int(n),
                # ★ Null, not 0 and not the median of two tiles: under the floor the
                #   zone has no number, and the client draws a wash rather than a
                #   colour that reads as one.
                "median_error_m": round(float(med), 2) if n >= ZONE_MIN_TILES else None,
            })
    return {
        "width": int(width),
        "height": int(height),
        "bands_m": [round(b, 1) for b in bands],
        "min_tiles": ZONE_MIN_TILES,
        # One entry per band, in band order; null where the edge never crosses the
        # frame (the far edge of a scene the photograph does not reach).
        "curves": [
            [[round(float(u), 1), round(float(v), 1)] for (u, v) in curves[b]]
            if b in curves else None
            for b in bands
        ],
        "cells": cells,
        # The colour scale's two ends, over the zones that have data. Null when none
        # does — nothing to normalise, so nothing is coloured.
        "range_m": [round(rng[0], 2), round(rng[1], 2)] if rng else None,
    }


def start_measure(inputs: MeasureInputs) -> AccuracyRun:
    """Validate, register and launch the measurement thread."""
    if inputs.mosaic_writer is None:
        raise AccuracyError("no imagery source was supplied for the measurement.")
    if inputs.params.stride > inputs.params.tile:
        raise AccuracyError(
            f"stride ({inputs.params.stride} m) is larger than the tile "
            f"({inputs.params.tile} m) — the tiles would not overlap and most of the "
            "scene would go unmeasured."
        )
    if len(inputs.pose.gcps) < REQUIRED_GCPS:
        raise AccuracyError(
            f"the photograph has {len(inputs.pose.gcps)} committed GCP(s); the "
            f"measurement needs a pose, which needs at least {REQUIRED_GCPS}."
        )
    return _start("measure", inputs.pose, lambda run: _run_measure(run, inputs))


def _run_measure(run: AccuracyRun, inputs: MeasureInputs) -> None:
    pose = inputs.pose
    folder = store_dir(pose.output_dir, pose.image_id)
    run.status = "running"
    try:
        from app.vendor.geo_accuracy import error_map, error_map_html  # noqa: PLC0415

        def progress(pct: float, msg: str) -> None:
            run.progress_pct = int(pct)
            run.message = str(msg)

        # ★ THE ONE STEP WHOSE DURATION WE DO NOT CONTROL gets its own progress. The
        #   core reports 45 → "loading satellite reference" and then says nothing until
        #   the mosaic is complete; on a 1 km scene that is a hundred tiles of network
        #   wait, and a bar parked at 50% reads as a hang. The writer counts tiles into
        #   the 45–68 band so the run visibly advances while it downloads.
        writer = inputs.mosaic_writer
        if writer is not None:
            writer.on_tile_progress = lambda done, total: progress(  # type: ignore[attr-defined]
                45 + 23.0 * done / max(total, 1),
                f"downloading satellite imagery — {done}/{total} tiles",
            )

        progress(2, "loading the photograph, its terrain and its pose...")
        scene = _load_scene(pose)
        try:
            core_params = inputs.params.to_core()
            reach: dict[str, Any] | None = None
            if inputs.params.auto_reach:
                # ★ THE COVERAGE RULE (upstream §8). Decided here, before the mosaic
                #   is fetched, because the reach is also the mosaic's radius: a
                #   reach that holds 3% of the view downloads a mosaic centred on
                #   ground the photograph barely shows and locks nothing.
                progress(4, "checking how much of the view the reach covers...")
                reach = resolve_reach(view_ranges(scene), inputs.params.max_range)
                if reach["raised"]:
                    import dataclasses  # noqa: PLC0415

                    core_params = dataclasses.replace(core_params, max_range=reach["used_m"])
            result = error_map.run(
                scene.rotation,
                scene.camera_xyz,
                scene.k_matrix,
                scene.dist,
                scene.photo,
                scene.dem,
                (scene.cam_lat, scene.cam_lon),
                str(folder),
                params=core_params,
                progress=progress,
                mosaic_writer=inputs.mosaic_writer,
            )
            # ★ Here and not after: the zones trace rays through the DEM, which the
            #   `finally` below closes. A failure here is logged and the measurement
            #   stands without its zones — the overlay explains the run, it is not
            #   the run.
            try:
                zones = _photo_zones(scene, result, log=lambda m: progress(96, m))
            except Exception:  # noqa: BLE001
                log.exception("accuracy: the photo zones could not be traced")
                zones = None
        finally:
            scene.dem.ds.close()

        locked = result.good
        total = len(result.tiles)
        rate = (len(locked) / total) if total else 0.0
        try:
            cloud = cloud_report(result, core_params)
        except Exception:  # noqa: BLE001 — a report that failed must not fail the run
            log.exception("accuracy: the cloud report could not be computed")
            cloud = None

        run.message = "writing the result..."
        folder.mkdir(parents=True, exist_ok=True)
        _write_jpg(folder / LAYER_FILES["ortho"], result.ortho)
        _write_jpg(folder / LAYER_FILES["satellite"], result.sat)
        np.save(folder / _INSIDE_NPY, np.packbits(result.inside, axis=None))

        vmax = (
            max(6.0, float(np.ceil(np.percentile([t["err"] for t in locked], 98))))
            if locked
            else 8.0
        )
        heat, heat_step = error_map.heat_grid(result)
        _write_heat_png(folder / LAYER_FILES["heat_raw"], heat, vmax)
        # The satellite pane's copy — warped, with the corners it must be placed by.
        web_bounds = _write_heat_web(
            folder / LAYER_FILES["heat_web_raw"],
            heat,
            vmax,
            origin=(float(result.origin[0]), float(result.origin[1])),
            cell_m=float(result.params.gsd) * float(heat_step),
            epsg=int(scene.dem.epsg),
        )

        try:
            error_map_html.write_interactive_html(
                result,
                (float(scene.camera_xyz[0]), float(scene.camera_xyz[1])),
                str(folder / _REPORT_HTML),
                title=f"Error map — {pose.image_id}",
            )
        except Exception:  # noqa: BLE001 — a viewer that failed must not fail the run
            log.exception("accuracy: interactive report could not be written")

        warnings = list(scene.warnings)
        # ★ A FREED FOCAL THAT MOVED A LONG WAY IS A FINDING. At grazing geometry focal
        #   trades off against tilt, so the solver can shorten the lens, tip the camera
        #   and fit the same points — a large shift usually means the calibration is
        #   wrong OR that the geometry could not separate the two. Either way the
        #   surveyor should know it happened rather than read a quietly different lens.
        if scene.free_focal and scene.entered_focal_px > 0:
            drift = 100.0 * abs(scene.solved_focal_px - scene.entered_focal_px) / scene.entered_focal_px
            if drift >= 2.0:
                warnings.append(
                    f"the freed focal solved to {scene.solved_focal_px:.0f} px from an "
                    f"entered {scene.entered_focal_px:.0f} px ({drift:.1f}% away). At "
                    "grazing angles focal and tilt trade off against each other, so "
                    "check the calibration before trusting this pose."
                )
        # ★ THE MATCH RATE IS THE TRUST SIGNAL. Under ~50% the comparison is not
        #   reliable (a very low flight stretches the rectified photo until it stops
        #   matching the basemap) — the field tool's own guidance, stated here rather
        #   than left for the surveyor to infer from a number.
        if rate < 0.5:
            warnings.append(
                f"only {100 * rate:.0f}% of tiles locked onto the satellite imagery. "
                "Below about 50% the measurement is unreliable — usually a very low "
                "flight, or a DEM that does not cover the scene."
            )
        # ★ A LOCK ON CLOUD IS A NUMBER THAT IS NOT AN ERROR. The consistency filter
        #   cannot catch it — a cloud edge is a continuous line, so neighbouring
        #   false locks agree with each other — which is why the run says so here.
        if cloud is not None and cloud["locked_tiles_on_cloud"] > 0:
            n = cloud["locked_tiles_on_cloud"]
            warnings.append(
                f"{n} locked tile{'s' if n != 1 else ''} sit{'s' if n == 1 else ''} more "
                f"than {100 * CLOUD_TILE_FRACTION:.0f}% on cloud in the satellite imagery "
                f"({100 * cloud['content_fraction']:.1f}% of the content is cloud). A match "
                "on a cloud edge is not a geolocation error"
                + (
                    " — turn on the cloud mask and re-measure."
                    if not cloud["masked"] else
                    "; these slipped past the mask because most of each tile is ground."
                )
            )
        # ★ A RAISED REACH IS A FINDING, not housekeeping: it says the requested
        #   setting did not contain the scene, and it changes what was measured.
        if reach is not None and reach["raised"]:
            warnings.append(
                f"the reach was raised from {reach['requested_m']:.0f} m to "
                f"{reach['used_m']:.0f} m: only {100 * reach['coverage_requested']:.0f}% "
                f"of the visible ground was inside {reach['requested_m']:.0f} m, and "
                f"{100 * reach['coverage_used']:.0f}% is inside the reach that ran."
            )
        elif reach is not None and reach["coverage_used"] < REACH_MIN_COVERAGE:
            warnings.append(
                f"only {100 * reach['coverage_used']:.0f}% of the visible ground is "
                f"inside the {reach['used_m']:.0f} m reach, and it cannot be raised "
                f"past {REACH_CAP_M:.0f} m. Ground beyond it is unmeasured."
            )

        summary = {
            "measured_at": datetime.now(UTC).isoformat(),
            "provider": inputs.provider_name,
            "params": {
                "gsd": inputs.params.gsd,
                "max_range": inputs.params.max_range,
                "tile": inputs.params.tile,
                "stride": inputs.params.stride,
                "sat_zoom": inputs.params.sat_zoom,
                "mi_rescue": inputs.params.mi_rescue,
                "fine_pass": inputs.params.fine_pass,
                "max_shift": inputs.params.max_shift,
                "ecc_rescue": inputs.params.ecc_rescue,
                "tile_auto": inputs.params.tile_auto,
                "sigma_dtm": inputs.params.sigma_dtm,
                "reliability_max": inputs.params.reliability_max,
                "auto_reach": inputs.params.auto_reach,
                "cloud_mask": inputs.params.cloud_mask,
                # ★ What the coverage rule DID with `max_range`: the reach that ran.
                "max_range_used": float(result.params.max_range),
                # ★ What `tile_auto` actually CHOSE. The request's `tile` is what was
                #   asked for; this is what ran, and the two differ exactly when the
                #   switch is on. Reading the request would misreport the run.
                "tile_used": int(result.params.tile),
                "stride_used": int(result.params.stride),
            },
            "tiles_total": total,
            "tiles_locked": len(locked),
            "match_rate": round(rate, 4),
            "median_error_m": (
                round(float(np.median([t["err"] for t in locked])), 3) if locked else None
            ),
            "bands": [
                {
                    "band": z[0], "tiles": int(z[1]), "median_error_m": round(z[2], 2),
                    "dE": round(z[3], 2), "dN": round(z[4], 2),
                    "radial": round(z[5], 2), "tangential": round(z[6], 2),
                }
                for z in result.zone_summary()
            ],
            "methods": {
                m: sum(1 for t in locked if t.get("method") == m)
                for m in ("phase", "mi", "fine", "ecc")
            },
            # ★ THE NUMBER THAT EXPLAINS THE OTHERS (2026-09-10). Amplification is
            #   how far a metre of DTM height error moves the ground intersection.
            #   A nadir flight reads about 2; a mast looking kilometres out reads
            #   several times that, and its median error is larger for that reason
            #   alone — no amount of re-solving the pose moves it. Reported over the
            #   LOCKED tiles, with the expected sigma it implies at this DTM.
            "amplification": _amplification_summary(locked, inputs.params.sigma_dtm),
            # ★ THE NINE ZONES ON THE PHOTOGRAPH (2026-09-10) — the measurement put
            #   back in the frame the surveyor is actually looking at. Curves in
            #   ORIGINAL photo pixels, the same convention the suggestion boxes use.
            "zones": zones,
            # ★ THE COVERAGE RULE'S OWN RECORD. Null when the switch was off.
            "reach": reach,
            # ★ BASEMAP CLOUD, reported whether or not it was masked.
            "cloud": cloud,
            "grid": {
                "width": int(result.sat.shape[1]),
                "height": int(result.sat.shape[0]),
                "gsd": float(result.params.gsd),
                "origin_e": float(result.origin[0]),
                "origin_n": float(result.origin[1]),
                "heat_step": int(heat_step),
                "vmax_m": vmax,
                #: Lat/lon corners of the WARPED heat layer — what the satellite pane
                #: places `heat_web_*` by. Null when too few tiles locked to draw one.
                "web_bounds": web_bounds,
                "camera_x": (float(scene.camera_xyz[0]) - float(result.origin[0]))
                / float(result.params.gsd),
                "camera_y": (float(result.origin[1]) - float(scene.camera_xyz[1]))
                / float(result.params.gsd),
            },
            "pose": {
                "gcps_used": scene.gcps_used,
                "reproj_mean_px": round(scene.reproj_mean_px, 3),
                "reproj_max_px": round(scene.reproj_max_px, 3),
                "free_focal": scene.free_focal,
                "entered_focal_px": round(scene.entered_focal_px, 2),
                "solved_focal_px": round(scene.solved_focal_px, 2),
                # ★ WHICH POSE THIS WAS MEASURED FROM. After an adoption the number
                #   above is a RESIDUAL — what the previous correction left — not the
                #   error the control points alone produce. Two readings of "4 m" that
                #   mean different things must be distinguishable.
                **(scene.base_pose or {}),
            },
            "warnings": warnings,
            "tiles": _tile_rows(result),
        }
        _write_json(folder / _MEASURE_JSON, summary)

        # A fresh measurement invalidates whatever was corrected against the old one —
        # including an adoption, whose recorded numbers described the previous run.
        for stale in (_CORRECTION_JSON, _SOLUTIONS_JSON, _STAGEF_NPZ, _ADOPTION_JSON):
            (folder / stale).unlink(missing_ok=True)
        for key in (
            "heat_pose", "heat_field", "heat_stagef",
            "heat_web_pose", "heat_web_field", "heat_web_stagef",
        ):
            (folder / LAYER_FILES[key]).unlink(missing_ok=True)

        # ★ Archive AFTER the stale sweep: the version must carry this run's layers,
        #   not the previous correction's, which the sweep has just removed.
        _archive_version(folder, summary)

        run.summary = {k: v for k, v in summary.items() if k != "tiles"}
        run.progress_pct = 100
        run.message = f"{len(locked)}/{total} tiles locked"
        run.status = "succeeded"
    except AccuracyError as exc:
        run.status = "failed"
        run.error = str(exc)
    except Exception as exc:  # noqa: BLE001 — the thread must never die silently
        log.exception("accuracy measure %s failed", run.run_id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.finished_at = datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# Stages E + F + the comparison — correct
# ─────────────────────────────────────────────────────────────────────────────


def _restore_result(folder: Path, measurement: dict[str, Any]) -> Any:  # noqa: ANN401
    """Rebuild the core's ``Result`` from disk — enough of it for E/F/solutions.

    ★ WHAT IS AND IS NOT RESTORED. Stages E/F and the comparison read the tiles, the
    params, and (for drawing) the grid's shape and coverage mask. They never read the
    ortho or satellite PIXELS, so those are not reloaded: a full-scene pair is ~20 MB
    of arrays that would be decoded only to be ignored. ``sat`` is therefore a
    zero-cost shape stand-in, and ``inside`` — which ``heat_from_points`` genuinely
    uses to blank uncovered ground — is restored for real.
    """
    from app.vendor.geo_accuracy.error_map import Params, Result  # noqa: PLC0415

    stored = measurement["params"]
    params = Params(
        gsd=float(stored["gsd"]),
        max_range=float(stored["max_range"]),
        tile=int(stored["tile"]),
        stride=int(stored["stride"]),
        sat_zoom=int(stored["sat_zoom"]),
        mi_rescue=bool(stored["mi_rescue"]),
        fine_pass=bool(stored["fine_pass"]),
    )
    grid = measurement["grid"]
    height, width = int(grid["height"]), int(grid["width"])
    packed = np.load(folder / _INSIDE_NPY)
    inside = np.unpackbits(packed, count=height * width).astype(bool).reshape(height, width)

    gsd = float(grid["gsd"])
    origin = (float(grid["origin_e"]), float(grid["origin_n"]))
    tiles = []
    for row in measurement["tiles"]:
        tile_px = int(row["tile_px"])
        x0 = float(row["x"]) - tile_px / 2
        y0 = float(row["y"]) - tile_px / 2
        tiles.append(
            {
                "x0": x0, "y0": y0, "tile": tile_px,
                "dE": float(row["dE"]), "dN": float(row["dN"]), "err": float(row["err"]),
                "resp": float(row["response"]), "range": float(row["range_m"]),
                "u": 0.0, "method": row["method"], "sector": 0, "ok": bool(row["ok"]),
                "radial": float(row["radial"]), "tangential": float(row["tangential"]),
                # The tile CENTRE in world metres — what `pseudo_gcps` reads. Recomputed
                # from the grid rather than stored twice, so the two cannot disagree.
                "cE": origin[0] + (x0 + tile_px / 2) * gsd,
                "cN": origin[1] - (y0 + tile_px / 2) * gsd,
            }
        )
    return Result(
        ortho=np.zeros((0, 0, 3), np.uint8),
        sat=np.zeros((height, width, 0), np.uint8),
        inside=inside,
        rng_g=None,
        origin=origin,
        tiles=tiles,
        params=params,
    )


def start_correct(inputs: CorrectInputs) -> AccuracyRun:
    folder = store_dir(inputs.pose.output_dir, inputs.pose.image_id)
    if not (folder / _MEASURE_JSON).is_file():
        raise AccuracyError(
            "there is no measurement for this photograph yet — run the Stage D "
            "measurement first; the correction is built from the tiles it locked."
        )
    return _start("correct", inputs.pose, lambda run: _run_correct(run, inputs))


def _run_correct(run: AccuracyRun, inputs: CorrectInputs) -> None:
    pose = inputs.pose
    folder = store_dir(pose.output_dir, pose.image_id)
    run.status = "running"
    try:
        from app.vendor.geo_accuracy import error_correction, solutions as sol_mod  # noqa: PLC0415
        from app.vendor.geo_accuracy.stage_f import StageF  # noqa: PLC0415

        def progress(pct: float, msg: str) -> None:
            run.progress_pct = int(pct)
            run.message = str(msg)

        measurement = _read_json(folder / _MEASURE_JSON)
        if measurement is None:
            raise AccuracyError("the stored measurement could not be read — re-measure.")

        progress(3, "loading the photograph's pose...")
        scene = _load_scene(pose)
        try:
            result = _restore_result(folder, measurement)
            raw_pose = (scene.rotation, scene.camera_xyz, scene.k_matrix, scene.dist)

            corr = error_correction.build_correction(
                result,
                scene.dem,
                *raw_pose,
                use_residual_field=inputs.use_residual_field,
                free_focal=inputs.free_focal,
                progress=lambda pct, msg: progress(5 + 0.45 * pct, msg),
            )
            corr.save(str(folder / _CORRECTION_JSON))

            # ── Stage F: the same tiles measured under BOTH poses ────────────
            progress(55, "building Stage F (base choice + local subtraction)...")
            uv, xyz_true, _tiles = error_correction.pseudo_gcps(result, scene.dem, *raw_pose)
            raw_vec = error_correction._tile_errors(uv, xyz_true, *raw_pose, scene.dem)
            cor_vec = error_correction._tile_errors(
                uv, xyz_true, corr.R, corr.C, corr.K, corr.dist, scene.dem
            )
            ok = np.isfinite(raw_vec).all(axis=1) & np.isfinite(cor_vec).all(axis=1)
            pts = xyz_true[ok, :2]
            raw_vec, cor_vec = raw_vec[ok], cor_vec[ok]
            stage_f = StageF(pts, raw_vec, pts, cor_vec)
            np.savez(
                folder / _STAGEF_NPZ, pts=pts, raw_vec=raw_vec, cor_vec=cor_vec
            )

            progress(62, "scoring every stage on the same tiles...")
            sols = sol_mod.build(
                result,
                scene.dem,
                raw_pose,
                corr,
                progress=lambda pct, msg: progress(62 + 0.3 * pct, msg),
            )
            rows = sol_mod.table(sols, result.params)
            best = sol_mod.best_key(sols, result.params)

            # ── the heat layer per stage, all on the RAW scale ───────────────
            progress(94, "drawing the comparison layers...")
            grid_meta = measurement.get("grid", {})
            vmax = float(grid_meta.get("vmax_m") or 8.0)
            geo = dict(
                origin=(float(grid_meta["origin_e"]), float(grid_meta["origin_n"])),
                cell_m=float(grid_meta["gsd"]) * float(grid_meta.get("heat_step", 4)),
                epsg=int(scene.dem.epsg),
            )
            for key in ("raw", "pose", "field", "stagef"):
                s = sols.get(key)
                if s is None or not s.available or not len(s.err):
                    continue
                grid, _step = s.heat(result)
                _write_heat_png(folder / LAYER_FILES[f"heat_{key}"], grid, vmax)
                # Every stage gets a warped twin, so switching stages on the satellite
                # pane shows that stage's error and not the previous one's.
                _write_heat_web(folder / LAYER_FILES[f"heat_web_{key}"], grid, vmax, **geo)
        finally:
            scene.dem.ds.close()

        report = dict(corr.report)
        entries = []
        for key in sol_mod.ORDER:
            s = sols.get(key)
            if s is None:
                continue
            bands = s.bands(result.params) if s.available and len(s.err) else {}
            entries.append(
                {
                    "key": key,
                    "label": s.label,
                    "colour": s.colour,
                    "available": bool(s.available),
                    "held_out": bool(s.held_out),
                    "note": s.note,
                    "tiles": len(s.tiles) if s.available else 0,
                    "all_m": _finite(bands.get("all")),
                    "p95_m": _finite(s.p95) if s.available and len(s.err) else None,
                    "worst20_share": _finite(s.worst20) if s.available and len(s.err) else None,
                    "bands": {k: _finite(v) for k, v in bands.items() if k != "all"},
                }
            )

        # ★ `raw` STOPS MEANING "NO CORRECTION" ONCE A POSE HAS BEEN ADOPTED. It then
        #   means "the adopted pose, not refined again" — still the baseline of this
        #   comparison, but no longer the control-point solve. Leaving the core's label
        #   would tell the surveyor they were looking at an uncorrected answer while
        #   they were looking at a corrected one.
        base_meta = scene.base_pose or {}
        if base_meta.get("source") == "adopted":
            for entry in entries:
                if entry["key"] == "raw":
                    generation = base_meta.get("generation", 1)
                    entry["label"] = (
                        f"Adopted pose ({base_meta.get('from_stage')}, generation {generation})"
                    )
                    entry["note"] = (
                        "the measurement itself — what the correction you adopted has "
                        "LEFT, not the error your control points alone produce"
                    )

        by_key = {e["key"]: e for e in entries}
        warnings: list[str] = []
        # ★ THE WARNING THE FIELD TOOL INSISTS ON: a correction can halve the typical
        #   error and still make the WORST places worse. The median alone cannot say
        #   that, so p95 and the worst-20% share are compared explicitly.
        raw_entry, best_entry = by_key.get("raw"), by_key.get(best)
        if best != "raw" and raw_entry and best_entry:
            if _worse(best_entry["p95_m"], raw_entry["p95_m"]):
                warnings.append(
                    f"{best_entry['label']} wins on the median but its p95 is worse "
                    f"({best_entry['p95_m']:.1f} m vs {raw_entry['p95_m']:.1f} m) — it "
                    "improves most of the scene and makes the worst places worse."
                )
            if _worse(best_entry["worst20_share"], raw_entry["worst20_share"]):
                warnings.append(
                    "the worst fifth of the scene carries a LARGER share of the total "
                    "error after this correction than before it."
                )
        if not report.get("accepted", False):
            warnings.append(str(report.get("gate_reason", "the correction was refused.")))

        payload = {
            "corrected_at": datetime.now(UTC).isoformat(),
            "use_residual_field": inputs.use_residual_field,
            "free_focal": inputs.free_focal,
            "best": best,
            "rows": [
                {"band": band, "values": {k: _finite(v) for k, v in vals.items()}}
                for band, vals in rows
            ],
            "entries": entries,
            "stage_f": stage_f.summary(),
            "warnings": warnings,
            "basemap_caveat": (
                "Every number here is measured against the satellite basemap, which "
                "carries its own georeferencing error of a few metres. Breaking that "
                "floor needs GNSS-surveyed checkpoints."
            ),
        }
        _write_json(folder / _SOLUTIONS_JSON, payload)
        # ★ A new comparison retires the old choice rather than silently re-pointing it
        #   at different numbers: the surveyor adopted a stage that scored 3.02 m, and
        #   after a re-run that same stage may score anything. Re-adopting is one click;
        #   an adoption whose recorded evidence no longer exists is a lie.
        clear_adoption(pose.output_dir, pose.image_id)
        # ★ The SAME version, updated in place — a correction belongs to the run it
        #   corrected, not to a new entry that would double every cycle in the history.
        if measurement is not None:
            _archive_version(folder, measurement)

        run.summary = {
            "best": best,
            "accepted": bool(report.get("accepted", False)),
            "gate_reason": report.get("gate_reason"),
            "warnings": warnings,
        }
        run.progress_pct = 100
        run.message = f"winner: {by_key.get(best, {}).get('label', best)}"
        run.status = "succeeded"
    except AccuracyError as exc:
        run.status = "failed"
        run.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("accuracy correct %s failed", run.run_id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.finished_at = datetime.now(UTC)


def _finite(value: Any) -> float | None:  # noqa: ANN401
    """A NaN is not a number the UI may print — it is a missing measurement."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if math.isfinite(f) else None


def _worse(candidate: float | None, reference: float | None) -> bool:
    return candidate is not None and reference is not None and candidate > reference


# ─────────────────────────────────────────────────────────────────────────────
# Query — the four answers for one pixel, side by side
# ─────────────────────────────────────────────────────────────────────────────


def query_pixel(pose: PoseInputs, u: float, v: float, target_height_m: float = 0.0) -> dict[str, Any]:
    """``raw`` / ``pose`` / ``field`` / ``stagef`` for one photo pixel.

    ★ ALL OF THEM, ALWAYS — never just the winner. The whole point of the comparison
    is that the surveyor can drop one pin per answer on a feature they recognise and
    see which one lands on it. Collapsing that to a single "best" coordinate would hide
    the disagreement that makes the check meaningful.
    """
    from app.vendor.geo_accuracy.error_correction import Correction, CorrectedGeolocator  # noqa: PLC0415
    from app.vendor.geo_accuracy.stage_f import StageF  # noqa: PLC0415

    folder = store_dir(pose.output_dir, pose.image_id)
    scene = _load_scene(pose)
    try:
        correction = None
        stage_f = None
        if (folder / _CORRECTION_JSON).is_file():
            correction = Correction.load(str(folder / _CORRECTION_JSON))
            if (folder / _STAGEF_NPZ).is_file():
                with np.load(folder / _STAGEF_NPZ) as z:
                    stage_f = StageF(z["pts"], z["raw_vec"], z["pts"], z["cor_vec"])

        if correction is None:
            from app.vendor.geo_accuracy import stage_b  # noqa: PLC0415

            hit = stage_b.raycast(
                u, v, scene.rotation, scene.camera_xyz, scene.k_matrix, scene.dist,
                scene.dem.Z, scene.dem.res, height_offset=target_height_m,
            )
            if hit is None:
                raise AccuracyError(_NO_HIT)
            lat, lon = scene.dem.xy_to_latlon(hit[0], hit[1])
            return {
                "answers": [
                    {"key": "raw", "lat": float(lat), "lon": float(lon),
                     "elevation_m": float(hit[2])}
                ],
                "best": "raw",
            }

        geolocator = CorrectedGeolocator(
            (scene.rotation, scene.camera_xyz, scene.k_matrix, scene.dist),
            correction,
            scene.dem,
            stage_f=stage_f,
        )
        out = geolocator.query(u, v, target_h=target_height_m)
        if not out:
            raise AccuracyError(_NO_HIT)
    finally:
        scene.dem.ds.close()

    stored = _read_json(folder / _SOLUTIONS_JSON) or {}
    answers = []
    for key in ("raw", "pose", "field", "stagef"):
        got = out.get(key)
        if got is None:
            continue
        lat, lon = float(got["lat"]), float(got["lon"])
        answers.append(
            {
                "key": key,
                "lat": lat,
                "lon": lon,
                "elevation_m": float(got["Z"]),
                "base": got.get("base"),
            }
        )
    return {"answers": answers, "best": stored.get("best", "raw")}


_NO_HIT = (
    "the ray through this pixel never meets the terrain — it points at the sky, past "
    "the DEM's edge, or beyond its reach. Pick a point on the ground inside the DEM."
)


# ─────────────────────────────────────────────────────────────────────────────
# Suggestions — where the next control point should go
# ─────────────────────────────────────────────────────────────────────────────


def start_suggest(inputs: SuggestInputs) -> AccuracyRun:
    if len(inputs.pose.gcps) < REQUIRED_GCPS:
        raise AccuracyError(
            f"place at least {REQUIRED_GCPS} control points and solve first — there is "
            "no pose to improve on yet."
        )
    return _start("suggest", inputs.pose, lambda run: _run_suggest(run, inputs))


def _run_suggest(run: AccuracyRun, inputs: SuggestInputs) -> None:
    pose = inputs.pose
    folder = store_dir(pose.output_dir, pose.image_id)
    run.status = "running"
    try:
        from app.vendor.geo_accuracy import gcp_suggest  # noqa: PLC0415

        def progress(frac: float, msg: str) -> None:
            run.progress_pct = int(100 * float(frac))
            run.message = str(msg)

        progress(0.02, "loading the photograph's pose...")
        scene = _load_scene(pose)
        try:
            # The measured error field, when there is one, weights the score toward
            # where the error actually IS rather than where the geometry is weakest.
            stage_d = None
            measurement = _read_json(folder / _MEASURE_JSON)
            if measurement is not None and (folder / _INSIDE_NPY).is_file():
                try:
                    stage_d = _restore_result(folder, measurement)
                except Exception:  # noqa: BLE001 — an unusable measurement is not fatal
                    log.exception("accuracy suggest: stored measurement unusable")

            points = []
            for g in pose.gcps:
                x, y = scene.dem.lonlat_to_xy(g.lon, g.lat)
                z = g.elevation_m if g.elevation_m is not None else scene.dem.Z(x, y)
                if z is None or not np.isfinite(z):
                    continue
                points.append({"u": g.u, "v": g.v, "X": float(x), "Y": float(y), "Z": float(z)})

            picked = gcp_suggest.suggest(
                points,
                scene.photo,
                scene.dem,
                scene.rotation,
                scene.camera_xyz,
                scene.k_matrix,
                scene.dist,
                n=int(inputs.count),
                stage_d=stage_d,
                criterion=inputs.criterion,
                box_frac=inputs.box_frac,
                progress=progress,
            )
        finally:
            scene.dem.ds.close()

        regions = [
            {
                "rank": int(c["rank"]),
                "u": round(float(c["u"]), 1),
                "v": round(float(c["v"]), 1),
                "half_px": int(c["half"]),
                "cut_pct": round(100.0 * float(c["cut"]), 2),
                "score": float(c["score"]),
                "range_m": round(float(c["range"])),
                "slope": round(float(c["slope"]), 4),
                "reasons": list(c["reasons"]),
                "short": str(c["short"]),
            }
            for c in picked
        ]
        best_cut = max((r["cut_pct"] for r in regions), default=0.0)
        converged = best_cut < float(inputs.stop_below_pct)

        payload = {
            "suggested_at": datetime.now(UTC).isoformat(),
            "criterion": inputs.criterion,
            "gcps_used": scene.gcps_used,
            "measured": bool(picked and picked[0].get("measured")),
            "max_range_m": round(float(picked[0]["max_range"])) if picked else None,
            "best_cut_pct": round(best_cut, 2),
            "stop_below_pct": float(inputs.stop_below_pct),
            # ★ THE ACTIONABLE OUTPUT is not the boxes, it is this verdict: the boxes
            #   are a direction, the percentage is what says whether adding points has
            #   stopped mattering.
            "verdict": "converged" if converged else "keep_going",
            "regions": regions,
        }
        _write_json(folder / _SUGGEST_JSON, payload)

        run.summary = {
            "verdict": payload["verdict"],
            "best_cut_pct": payload["best_cut_pct"],
            "regions": len(regions),
        }
        run.progress_pct = 100
        run.message = (
            f"converged — the best region would cut only {best_cut:.0f}%"
            if converged
            else f"{len(regions)} region(s); the best would cut {best_cut:.0f}%"
        )
        run.status = "succeeded"
    except AccuracyError as exc:
        run.status = "failed"
        run.error = str(exc)
    except RuntimeError as exc:  # the core's own "place 4 points first" / "no candidates"
        run.status = "failed"
        run.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("accuracy suggest %s failed", run.run_id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.finished_at = datetime.now(UTC)
