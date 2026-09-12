"""``camera_service`` — the server-side camera registry and its DESIRED state.

★ WHY (2026-09-02). The camera registry used to be one browser's ``localStorage``.
This service owns the ``cameras`` table instead: CRUD, a bulk import (the one-time
migration of a browser registry, and the JSON export/import the add-camera dialog
offers), and — the half that makes the monitor a service rather than a page — the
**desired state**: what each camera should be doing (a drift watch, a detection
session, a data feed), recorded when the operator presses Start/Watch/Stop with a
``camera_id`` in hand, and REPLAYED by :func:`reconcile_at_boot` when the API comes
back up. The threads themselves stay in memory by design; this is what brings them
back.

★ INTENT IN, STATUS OUT. Nothing here ever infers ``desired`` from what happens to be
running. The routers write intent; the reconciliation reads it and starts things;
whether they are running is the detection / drift / feed status endpoints' answer.
A camera whose runtime cannot start (no YOLO weights on this machine, a device that
is unplugged) keeps its intent — the log says why it did not come back, and the
next boot tries again.

Framework-free: SQLAlchemy sessions in, ORM rows out; no FastAPI.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import CameraNotFound, ValidationError
from app.core.logging import get_logger
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.cameras import CameraRepository, SyncCameraRepository, desired_of
from app.models.camera import Camera
from app.schemas.camera import (
    CameraCreate,
    CameraDesired,
    CameraImportRequest,
    CameraImportResult,
    CameraImported,
    CameraUpdate,
    desired_from_row,
)

log = get_logger(__name__)

__all__ = [
    "BOOT_RECONCILE_DELAY_S",
    "CameraService",
    "reconcile_at_boot",
    "schedule_boot_reconcile",
    "refreeze_drift_watch",
    "DRIFT_WATCH_INTERVAL_S",
]

#: How long after startup the reconciliation runs. Long enough for the API to be
#: serving (a page opened at boot may already be re-streaming a camera, and the
#: detector's device handover needs the panel to switch), short enough that a
#: camera watched overnight is back within seconds of a restart.
BOOT_RECONCILE_DELAY_S = 5.0


def _row_fields(body: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """A create/import body as ORM column values.

    Ids stay UUIDs; the calibration becomes a plain dict for its JSONB column (or
    None when nothing was entered).
    """
    fields = body.model_dump(exclude=exclude or set())
    calibration = body.calibration
    fields["calibration"] = None if calibration is None else calibration.model_dump()
    return fields


class CameraService:
    """Registry CRUD + desired-state writes, over the request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CameraRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, camera_id: uuid.UUID) -> Camera:
        camera = await self._repo.get(camera_id)
        if camera is None:
            raise CameraNotFound(f"No camera {camera_id}.")
        return camera

    async def list(
        self, *, pagination: PaginationParams, sort: SortParams, q: str | None = None
    ) -> tuple[Sequence[Camera], int]:
        return await self._repo.list_cameras(pagination=pagination, sort=sort, q=q)

    async def all(self) -> Sequence[Camera]:
        return await self._repo.all_cameras()

    # ── writes ────────────────────────────────────────────────────────────────

    async def create(self, body: CameraCreate) -> Camera:
        camera = Camera(**_row_fields(body), desired={})
        self._repo.add(camera)
        await self._repo.flush()
        return camera

    async def update(self, camera_id: uuid.UUID, body: CameraUpdate) -> Camera:
        """``PATCH`` — only the sent fields change, then the MERGED row is re-checked
        with the create rules, so a PATCH cannot leave a video camera without a
        source or a serial line claiming a picture (the CHECKs would refuse it
        anyway, as a 500; here it is a 422 naming the rule)."""
        camera = await self.get(camera_id)
        changes = body.as_changes()
        merged = {
            "name": camera.name,
            "lat": camera.lat,
            "lon": camera.lon,
            "source": camera.source,
            "connection": camera.connection,
            "provides": camera.provides,
            "data_source": camera.data_source,
            "heading_deg": camera.heading_deg,
            "fov_deg": camera.fov_deg,
            "fps": camera.fps,
            "tags": list(camera.tags or []),
            "lut_site": camera.lut_site,
            "project_id": camera.project_id,
            "frame_image_id": camera.frame_image_id,
            "calibration": camera.calibration,
        }
        for key, value in changes.items():
            if key == "name" and value is None:
                continue  # a null name cannot clear; nothing to render
            if key == "tags" and value is None:
                value = []
            if key in ("connection", "provides") and value is None:
                continue
            merged[key] = value
        # ★ Re-validated as a whole, and the refusal is a domain 422 (a bare pydantic
        #   error raised inside a service would surface as a 500).
        try:
            valid = CameraCreate.model_validate(merged)
        except PydanticValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            raise ValidationError(str(first.get("msg") or "invalid camera")) from exc
        for key, value in valid.model_dump(mode="json").items():
            if key in ("project_id", "frame_image_id"):
                # ★ UUID columns take UUIDs; ``mode="json"`` stringified them so the
                #   calibration JSONB is plain — convert the two ids back.
                value = getattr(valid, key)
            setattr(camera, key, value)
        await self._repo.flush()
        # updated_at is trigger-maintained — re-read before anything serialises it
        await self._repo.refresh(camera)
        return camera

    async def delete(self, camera_id: uuid.UUID) -> None:
        """Hard delete. Whatever the camera was asked to do is stopped first — a
        watch or a run on a camera nobody can see any more is a leak, not a
        service — and its ``detection_events`` rows stay (no FK, on purpose)."""
        camera = await self.get(camera_id)
        _stop_everything_for(camera)
        await self._repo.delete(camera)

    async def import_many(self, body: CameraImportRequest) -> CameraImportResult:
        """Bulk create — the browser-registry migration and the JSON import.

        ★ All or nothing: the request is the transaction, so a single bad row rolls
        back the lot (pydantic has already refused it with the row's index in the
        422 details). The result maps each ``client_id`` to its new UUID.
        """
        items: list[CameraImported] = []
        for entry in body.cameras:
            fields = _row_fields(entry, exclude={"client_id"})
            camera = Camera(**fields, desired={})
            self._repo.add(camera)
            await self._repo.flush()
            items.append(CameraImported(client_id=entry.client_id, id=camera.id, name=camera.name))
        return CameraImportResult(created=len(items), items=items)

    # ── desired state ─────────────────────────────────────────────────────────

    async def set_desired(self, camera_id: uuid.UUID, desired: CameraDesired) -> Camera:
        camera = await self.get(camera_id)
        camera.desired = desired.model_dump(mode="json")
        await self._repo.flush()
        await self._repo.refresh(camera)
        return camera

    async def _patch_desired(self, camera_id: uuid.UUID, **changes: Any) -> Camera:
        camera = await self.get(camera_id)
        current = desired_from_row(camera.desired).model_dump(mode="json")
        current.update(changes)
        # a fresh dict, so SQLAlchemy sees the JSONB change
        camera.desired = dict(current)
        await self._repo.flush()
        return camera

    async def record_detect(
        self, camera_id: uuid.UUID, detect: dict[str, Any] | None, *, lut_site: str | None = None
    ) -> Camera:
        """The operator started (dict) or stopped (None) a detection run here."""
        camera = await self._patch_desired(camera_id, detect=detect)
        if lut_site is not None:
            camera.lut_site = lut_site
            await self._repo.flush()
        return camera

    async def record_watch(
        self, camera_id: uuid.UUID, watch: dict[str, Any] | None
    ) -> Camera:
        """The operator started (``{ref_id, interval_s}``) or stopped (None) a drift watch."""
        return await self._patch_desired(camera_id, watch=watch)

    async def record_feed(self, camera_id: uuid.UUID, feed: bool) -> Camera:
        return await self._patch_desired(camera_id, feed=bool(feed))


# ─────────────────────────────────────────────────────────────────────────────
# The camera's drift watch — frozen on its frame, running in the background
# ─────────────────────────────────────────────────────────────────────────────

#: How often the background watch looks, in seconds. "Live" to an operator
#: reading the pill, and light on the camera: one template match per landmark.
DRIFT_WATCH_INTERVAL_S = 10.0


def refreeze_drift_watch(
    settings: Settings,
    *,
    camera_id: str,
    name: str,
    source: str,
    lut_site: str | None,
    image_path: Path | None,
    image_label: str | None,
    fov_deg: float | None,
    previous_ref_id: str | None,
) -> dict[str, Any]:
    """Freeze the camera's drift reference on ITS FRAME, and watch it from now on.

    ★ THE FRAME THE CONTROL POINTS SIT ON IS THE FROZEN FRAME (2026-09-08, owner
    decision). The lookup table's pose was solved on that photograph, so the
    reference belongs on it — freezing a later grab would bake any shift between
    capture and freeze into "trusted". The monitoring page therefore no longer
    freezes anything: the reference exists the moment the table is built from the
    frame, and RE-FREEZING is done in the camera settings by choosing a new frame.

    ★ THE WATCH IS THE CAMERA'S BACKGROUND STATE. It starts here, is recorded as
    the camera's desired ``watch`` by the router, and comes back at boot. An older
    watch on this camera is retired first (``freeze_reference`` retires any other
    watch on the same source as well).

    Raises ``DriftError`` naming the missing piece — a table, a frame, or a pose.
    """
    from app.services import drift_service, lut_service  # noqa: PLC0415

    if not source or source.startswith("video:"):
        raise drift_service.DriftError(
            "the drift watch needs a live camera — this camera has no video source."
        )
    if not lut_site:
        raise drift_service.DriftError(
            "the drift watch starts once the lookup table is built from the frame."
        )
    lut_dir = _lut_dir_for(settings.lut_output_dir, lut_site)
    if lut_dir is None:
        raise drift_service.DriftError(
            f"no lookup table named '{lut_site}' in the library — build it first."
        )
    if image_path is None:
        raise drift_service.DriftError(
            "the drift watch freezes on the camera's frame — capture one and place "
            "its control points first."
        )
    # ★ A table with no intrinsics (built in no-calibration mode) takes K from the
    #   camera's own field of view — the same seed its focal was solved from.
    no_calibration = False
    try:
        manifest = json.loads((lut_dir / "manifest.json").read_text(encoding="utf-8"))
        no_calibration = lut_service.manifest_pose_needs_fov(manifest)
    except (OSError, ValueError):
        manifest = {}
    if no_calibration and (fov_deg is None or fov_deg <= 0):
        raise drift_service.DriftError(
            "this lookup table carries no intrinsics — give the camera's horizontal "
            "field of view in its settings so the drift watch can derive them."
        )

    if previous_ref_id:
        drift_service.stop_monitor(previous_ref_id)
    record = drift_service.freeze_reference(
        settings.drift_output_dir,
        lut_dir,
        name=name,
        source=source,
        source_label=name,
        image_path=image_path,
        image_label=image_label,
        confirm_n=3,
        n_landmarks=drift_service.DRIFT_LANDMARKS,
        no_calibration=no_calibration,
        fov_h_deg=fov_deg if no_calibration else None,
        square_pixels=True,
    )
    ref_id = str(record["ref_id"])
    run = drift_service.start_monitor(
        settings.drift_output_dir,
        ref_id,
        interval_s=DRIFT_WATCH_INTERVAL_S,
        source=source,
    )
    log.info(
        "camera.drift_refrozen",
        camera=camera_id,
        ref_id=ref_id,
        landmarks=record.get("n_landmarks"),
        frame=image_label,
    )
    return {
        "ref_id": ref_id,
        "interval_s": DRIFT_WATCH_INTERVAL_S,
        "n_landmarks": int(record.get("n_landmarks") or 0),
        "frozen_from_label": record.get("frozen_from_label") or image_label,
        "created_utc": str(record.get("created_utc") or ""),
        "intrinsics_mode": record.get("intrinsics_mode") or "calibration",
        "intrinsics_warning": record.get("intrinsics_warning"),
        "watching": run.status == "running",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Boot reconciliation — intent in, threads out
# ─────────────────────────────────────────────────────────────────────────────


def _lut_dir_for(lut_output_dir: Path, site: str | None) -> Path | None:
    """The library bundle folder for a site name, or None — the same traversal-proof
    resolution ``/detection/sessions`` applies."""
    if not site:
        return None
    from app.services import lut_service  # noqa: PLC0415

    candidate = lut_output_dir / f"{lut_service.sanitize_site_name(site)}_lut"
    return candidate if (candidate / "manifest.json").is_file() else None


def _stop_everything_for(camera: Camera) -> None:
    """Stop the run, the watch and the feed a camera was asked for (best-effort)."""
    from app.services import detection_service, drift_service, live_data_service  # noqa: PLC0415

    desired = desired_of(camera)
    try:
        if camera.source:
            active = detection_service._active_for_source(camera.source)  # noqa: SLF001
            if active is not None and active.camera_id == str(camera.id):
                detection_service.stop_session(active.session_id)
        watch = desired.get("watch")
        if isinstance(watch, dict) and watch.get("ref_id"):
            drift_service.stop_monitor(str(watch["ref_id"]))
        if camera.data_source:
            feed = live_data_service.active_feed_for_source(camera.data_source)
            if feed is not None:
                live_data_service.stop_feed(feed.feed_id)
    except Exception as exc:  # noqa: BLE001 — a delete must not fail on a thread
        log.warning("camera.stop_everything_failed", camera=str(camera.id), error=str(exc))


def _restore_one(settings: Settings, row: dict[str, Any]) -> dict[str, str]:
    """Bring one camera's desired state back. Returns ``{aspect: outcome}``."""
    from app.services import detection_service, drift_service, live_data_service  # noqa: PLC0415

    out: dict[str, str] = {}
    camera_id, name = row["id"], row["name"]
    source, data_source = row["source"], row["data_source"]
    desired = row["desired"]

    # ── feed ──────────────────────────────────────────────────────────────────
    if desired.get("feed") and data_source:
        try:
            feed = live_data_service.start_feed(
                data_source, camera_id=camera_id, camera_name=name
            )
            out["feed"] = f"started {feed.feed_id}"
        except Exception as exc:  # noqa: BLE001 — one camera's failure is one line
            out["feed"] = f"failed: {exc}"

    # ── detection (before the watch: the detector should own the device, the
    #    watch then taps its frames instead of fighting for the camera) ─────────
    detect = desired.get("detect")
    if isinstance(detect, dict) and source:
        if detection_service._active_for_source(source) is not None:  # noqa: SLF001
            out["detect"] = "already running"
        else:
            site = detect.get("lut_site") or row.get("lut_site")
            lut_dir = _lut_dir_for(settings.lut_output_dir, site)
            if site and lut_dir is None:
                out["detect"] = f"failed: LUT bundle '{site}' is not in the library"
            else:
                values = {
                    "conf": detect.get("conf"),
                    "imgsz": detect.get("imgsz"),
                    "tile": detect.get("tile"),
                    # ★ Manual tracking (2026-09-03): the monitoring workspace no
                    #   longer auto-locks by frame. A camera whose desired state was
                    #   recorded BEFORE that change may still carry a nonzero handoff
                    #   (yamouneh tracked on its own after a restart); force 0 so a
                    #   reconciled run never resurrects the auto-tracker.
                    "tracker_start_frame": 0,
                    "locked_tracker_type": detect.get("tracker_type"),
                    "tracker_refresh_every": detect.get("tracker_refresh_every"),
                    "model": detect.get("model"),
                    "classes": detect.get("classes"),
                    "centre_marks": detect.get("centre_marks"),
                    "steady_boxes": detect.get("steady_boxes"),
                }
                try:
                    session = detection_service.start_session(
                        source=source,
                        model_dir=settings.detection_model_dir,
                        lut_dir=lut_dir,
                        settings_values={k: v for k, v in values.items() if v is not None},
                        source_label=name,
                        camera_id=camera_id,
                    )
                    out["detect"] = f"started {session.session_id}"
                except Exception as exc:  # noqa: BLE001
                    out["detect"] = f"failed: {exc}"

    # ── watch ─────────────────────────────────────────────────────────────────
    watch = desired.get("watch")
    if isinstance(watch, dict) and watch.get("ref_id") and source:
        ref_id = str(watch["ref_id"])
        run = drift_service.get_monitor(ref_id)
        if run is not None and run.status == "running":
            out["watch"] = "already running"
        else:
            try:
                drift_service.start_monitor(
                    settings.drift_output_dir,
                    ref_id,
                    interval_s=float(watch.get("interval_s") or 30.0),
                    source=source,
                )
                out["watch"] = f"started {ref_id[:8]}"
            except Exception as exc:  # noqa: BLE001
                out["watch"] = f"failed: {exc}"
    return out


def reconcile_at_boot(settings: Settings) -> dict[str, dict[str, str]]:
    """Walk ``cameras.desired`` and start what it records. Never raises.

    Returns ``{camera_id: {aspect: outcome}}`` — logged, and returned for tests.
    """
    from app.db.session import sync_session  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    try:
        with sync_session() as db:
            for camera in SyncCameraRepository(db).list_with_desire():
                rows.append(
                    {
                        "id": str(camera.id),
                        "name": camera.name,
                        "source": camera.source,
                        "data_source": camera.data_source,
                        "lut_site": camera.lut_site,
                        "desired": desired_of(camera),
                    }
                )
    except Exception as exc:  # noqa: BLE001 — no database, nothing to restore
        log.warning("cameras.reconcile_skipped", error=f"{type(exc).__name__}: {exc}")
        return {}

    results: dict[str, dict[str, str]] = {}
    for row in rows:
        outcome = _restore_one(settings, row)
        results[row["id"]] = outcome
        if outcome:
            log.info("cameras.reconciled", camera=row["id"], name=row["name"], **outcome)
    # One line per boot even when there was nothing to do — an operator reading the
    # status log must be able to tell "ran, nothing recorded" from "never ran".
    all_outcomes = [v for out in results.values() for v in out.values()]
    log.info(
        "cameras.reconcile_done",
        cameras_with_intent=len(rows),
        started=sum(1 for v in all_outcomes if v.startswith("started")),
        failed=sum(1 for v in all_outcomes if v.startswith("failed")),
    )
    return results


def schedule_boot_reconcile(
    settings: Settings, *, delay_s: float = BOOT_RECONCILE_DELAY_S
) -> threading.Thread:
    """Run :func:`reconcile_at_boot` on a daemon thread after ``delay_s``."""

    def run() -> None:
        time.sleep(delay_s)
        try:
            reconcile_at_boot(settings)
        except Exception:  # noqa: BLE001 — must never take the app down
            log.exception("cameras.reconcile_failed")

    thread = threading.Thread(target=run, name="cameras-reconcile", daemon=True)
    thread.start()
    return thread
