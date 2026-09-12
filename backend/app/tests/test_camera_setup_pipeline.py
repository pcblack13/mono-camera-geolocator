"""The camera setup pipeline (2026-09-04): a registry row that owns its setup.

★ What these pin: the connection vocabulary (UTP/LAN, USB,
BNC, serial, UART, embedded) with serial AND uart carrying data only; the
optional calibration blob (round-trips, an all-null one is dropped, bounds
hold); the backing-project and frame ids ride every response; and a PATCH merge
keeps the ids as UUIDs while the calibration lands as a plain dict for JSONB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.camera import (
    DATA_ONLY_CONNECTIONS,
    CameraCalibration,
    CameraCreate,
    CameraUpdate,
)


class TestConnectionVocabulary:
    @pytest.mark.parametrize("kind", ["lan", "usb"])
    def test_video_kinds_take_a_stream_or_device(self, kind: str) -> None:
        cam = CameraCreate(name="Gate", lat=34.1, lon=36.0, connection=kind, source="rtsp://x/1")
        assert cam.connection == kind and cam.provides == "camera"

    @pytest.mark.parametrize("kind", sorted(DATA_ONLY_CONNECTIONS))
    def test_the_serial_kind_carries_data_not_pictures(self, kind: str) -> None:
        with pytest.raises(ValidationError, match="carries no picture"):
            CameraCreate(
                name="S", lat=0, lon=0, connection=kind, provides="camera", source="rtsp://x"
            )
        ok = CameraCreate(
            name="S", lat=0, lon=0, connection=kind, provides="data", data_source="serial://COM3"
        )
        assert ok.connection == kind and ok.source is None

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CameraCreate(name="X", lat=0, lon=0, connection="wifi", source="rtsp://x")


class TestCalibration:
    def test_round_trips_and_is_optional(self) -> None:
        cam = CameraCreate(
            name="Roof",
            lat=1,
            lon=2,
            source="http://pi/stream",
            calibration={"fx": 1200.5, "fy": 1198.0, "cx": 960, "cy": 540, "tilt_deg": 12.5},
        )
        assert cam.calibration is not None
        assert cam.calibration.fx == 1200.5 and cam.calibration.k1 is None
        assert CameraCreate(name="Bare", lat=1, lon=2, source="rtsp://x").calibration is None

    def test_an_all_null_calibration_is_dropped_not_stored(self) -> None:
        cam = CameraCreate(name="Roof", lat=1, lon=2, source="rtsp://x", calibration={})
        assert cam.calibration is None
        assert CameraCalibration().is_empty()

    def test_bounds_hold(self) -> None:
        with pytest.raises(ValidationError):
            CameraCalibration(fx=0)
        with pytest.raises(ValidationError):
            CameraCalibration(tilt_deg=91)

    def test_the_patch_body_takes_the_pipeline_fields(self) -> None:
        pid, iid = uuid.uuid4(), uuid.uuid4()
        patch = CameraUpdate.model_validate(
            {"project_id": str(pid), "frame_image_id": str(iid), "calibration": {"fx": 10, "fy": 10}}
        )
        assert patch.project_id == pid and patch.frame_image_id == iid
        assert patch.changed_fields() == {"project_id", "frame_image_id", "calibration"}


class TestPresenterAndMerge:
    def _row(self, **over: object) -> SimpleNamespace:
        now = datetime.now(UTC)
        base: dict[str, object] = {
            "id": uuid.uuid4(),
            "name": "Gate",
            "lat": 34.1,
            "lon": 36.0,
            "source": "rtsp://cam/1",
            # ★ A kind RETIRED in 0023 — the read must fold it, never refuse it.
            "connection": "stream",
            "provides": "camera",
            "data_source": None,
            "heading_deg": None,
            "fov_deg": None,
            "fps": None,
            "tags": [],
            "lut_site": None,
            "project_id": None,
            "frame_image_id": None,
            "calibration": None,
            "desired": {},
            "created_at": now,
            "updated_at": now,
        }
        base.update(over)
        return SimpleNamespace(**base)

    def test_every_response_carries_the_pipeline_fields(self) -> None:
        from app.api.v1.cameras import to_camera_read

        pid = uuid.uuid4()
        read = to_camera_read(self._row(project_id=pid, calibration={"fx": 5, "fy": 5}))
        assert read.project_id == pid and read.frame_image_id is None
        assert read.connection == "lan"  # 'stream' folded, see RETIRED_CONNECTIONS
        assert read.calibration is not None and read.calibration.fx == 5
        # a bare row reads as bare — no invented calibration
        assert to_camera_read(self._row()).calibration is None

    def test_a_stored_row_always_reads_even_when_its_source_shape_is_retired(self) -> None:
        """★ 2026-09-08: one row whose source scheme the server no longer accepts
        made ``GET /cameras`` 500 for EVERY camera. The rules guard what comes in;
        what is stored must list."""
        from app.api.v1.cameras import to_camera_read

        row = self._row()
        row.source = "geo1://10.10.10.1:5000"
        row.provides = "both"
        row.data_source = "geo1://10.10.10.1:5000"
        read = to_camera_read(row)
        assert read.source == "geo1://10.10.10.1:5000" and read.provides == "both"
        # …while the same shape is still refused on the way IN
        with pytest.raises(ValidationError, match="the source must be"):
            CameraCreate(name="Pi", lat=0, lon=0, source="geo1://10.10.10.1:5000")

    @pytest.mark.asyncio
    async def test_a_patch_merge_keeps_uuids_and_stores_a_plain_dict(self) -> None:
        from app.models.camera import Camera
        from app.services.camera_service import CameraService

        camera = Camera(
            id=uuid.uuid4(),
            name="Gate",
            lat=34.1,
            lon=36.0,
            source="rtsp://cam/1",
            connection="lan",
            provides="camera",
            tags=[],
            desired={},
        )

        class FakeRepo:
            async def get(self, _id: uuid.UUID) -> Camera:
                return camera

            async def flush(self) -> None:
                return None

            async def refresh(self, _camera: Camera) -> None:
                return None

        service = CameraService.__new__(CameraService)
        service._repo = FakeRepo()
        pid, iid = uuid.uuid4(), uuid.uuid4()
        body = CameraUpdate.model_validate(
            {
                "connection": "serial",
                "provides": "data",
                "data_source": "serial:///dev/ttyUSB0?baud=115200",
                "project_id": str(pid),
                "frame_image_id": str(iid),
                "calibration": {"fx": 1000, "fy": 1000, "cx": 640, "cy": 360},
            }
        )
        merged = await service.update(camera.id, body)
        assert merged.connection == "serial" and merged.provides == "data"
        assert isinstance(merged.project_id, uuid.UUID) and merged.project_id == pid
        assert merged.frame_image_id == iid
        assert merged.calibration == {
            "fx": 1000.0,
            "fy": 1000.0,
            "cx": 640.0,
            "cy": 360.0,
            "k1": None,
            "k2": None,
            "p1": None,
            "p2": None,
            "k3": None,
            "mast_offset_m": None,
            "tilt_deg": None,
        }

    @pytest.mark.asyncio
    async def test_a_uart_line_claiming_video_is_a_422_not_a_500(self) -> None:
        from app.core.exceptions import ValidationError as DomainValidationError
        from app.models.camera import Camera
        from app.services.camera_service import CameraService

        camera = Camera(
            id=uuid.uuid4(), name="G", lat=0, lon=0, source="rtsp://x", connection="lan",
            provides="camera", tags=[], desired={},
        )

        class FakeRepo:
            async def get(self, _id: uuid.UUID) -> Camera:
                return camera

        service = CameraService.__new__(CameraService)
        service._repo = FakeRepo()
        with pytest.raises(DomainValidationError, match="carries no picture"):
            await service.update(camera.id, CameraUpdate.model_validate({"connection": "serial"}))


def test_migration_0021_widens_the_vocabulary_and_adds_the_pipeline_columns() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0021_camera_setup_pipeline.py"
    spec = importlib.util.spec_from_file_location("migration_0021", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0021" and mod.down_revision == "0020"
    for kind in ("stream", "usb", "bnc", "uart"):
        assert f"'{kind}'" in mod._NEW_CONNECTIONS
    assert "NOT IN ('serial', 'uart')" in mod._NEW_SERIAL_IS_DATA


def test_migration_0023_narrows_the_vocabulary_and_folds_every_old_kind() -> None:
    """★ The fold keeps what each old kind NEEDED: an address, a device, a port.

    Every retired kind must be named in an UPDATE — a row left on 'bnc' would
    fail the new CHECK on upgrade, which is a migration that stops halfway.
    """
    import importlib.util
    from pathlib import Path

    from app.models.camera import CAMERA_CONNECTIONS

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0023_camera_connection_vocabulary.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0023", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0023" and mod.down_revision == "0022"
    # The CHECK the model declares is the CHECK the migration installs.
    for kind in CAMERA_CONNECTIONS:
        assert f"'{kind}'" in mod._NEW_CONNECTIONS
    for gone in ("stream", "hdmi", "bnc", "uart", "embedded"):
        assert f"'{gone}'" not in mod._NEW_CONNECTIONS
    assert mod._NEW_SERIAL_IS_DATA == "connection <> 'serial' OR provides = 'data'"

    source = path.read_text()
    folds = source.split("def upgrade()")[1].split("def downgrade()")[0]
    for gone, into in (
        ("stream", "lan"),
        ("embedded", "lan"),
        ("hdmi", "usb"),
        ("bnc", "usb"),
        ("uart", "serial"),
    ):
        assert f"'{gone}'" in folds, f"{gone} is not folded — its rows would fail the CHECK"
        assert f"connection = '{into}'" in folds


class TestRetiredConnections:
    """★ A database one migration behind must still LIST (2026-09-11).

    The 2026-09-08 scar was a stored ``source`` scheme the server had retired,
    which made ``GET /cameras`` 500 for every camera. A retired ``connection``
    is the same shape of bug, so the read folds it exactly as the SQL does.
    """

    def test_every_retired_kind_reads_as_what_it_became(self) -> None:
        from app.schemas.camera import RETIRED_CONNECTIONS, CameraRead
        from app.models.camera import CAMERA_CONNECTIONS

        now = datetime.now(UTC)
        for old, new in RETIRED_CONNECTIONS.items():
            row = CameraRead(
                id=uuid.uuid4(), name="x", lat=1.0, lon=2.0, connection=old,
                provides="data", data_source="serial://COM3", desired={},
                created_at=now, updated_at=now,
            )
            assert row.connection == new, old
            assert new in CAMERA_CONNECTIONS

    def test_the_fold_is_the_migrations_fold(self) -> None:
        """One statement of the rule: the SQL and the read cannot disagree."""
        import importlib.util
        from pathlib import Path

        from app.schemas.camera import RETIRED_CONNECTIONS

        path = (
            Path(__file__).resolve().parents[2]
            / "alembic" / "versions" / "0023_camera_connection_vocabulary.py"
        )
        source = path.read_text()
        folds = source.split("def upgrade()")[1].split("def downgrade()")[0]
        for old, new in RETIRED_CONNECTIONS.items():
            # the UPDATE that names this old kind must set exactly the same new one
            statement = next(ln for ln in folds.splitlines() if f"'{old}'" in ln)
            assert f"connection = '{new}'" in statement, (old, statement)

    def test_a_retired_kind_is_an_ALIAS_on_the_way_in_too(self) -> None:
        """★ A client that has not reloaded keeps working through the upgrade.

        The fold is lossless — 'bnc' asked for a capture device and so does 'usb'
        — so an old caller gets a camera that works rather than a 422.
        """
        cam = CameraCreate(name="X", lat=0, lon=0, connection="bnc", source="device:0")
        assert cam.connection == "usb"
        pi = CameraCreate(
            name="Pi", lat=0, lon=0, connection="embedded", provides="both",
            source="http://pi/stream", data_source="http://pi/feed",
        )
        assert pi.connection == "lan"

    def test_a_kind_that_never_existed_is_still_refused(self) -> None:
        """Aliasing what was retired is kindness; inventing what never was is a guess."""
        with pytest.raises(ValidationError):
            CameraCreate(name="X", lat=0, lon=0, connection="wifi", source="rtsp://x")
