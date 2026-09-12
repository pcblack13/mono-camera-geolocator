"""``/accuracy/*`` — the ROUTER's own work, exercised as a real request.

★ WHY THIS FILE EXISTS. ``test_accuracy_service`` covers the stages; it cannot cover
``_pose_inputs``, which is router code that needs a DB session and therefore only ever
ran in production. It shipped with ``PaginationParams(limit=500)`` — above the shared
``MAX_LIMIT`` of 200, which that class rejects in ``__post_init__`` — so the very first
press of "Measure" raised ``ValueError`` before anything else happened and the surveyor
was told only "an unexpected error occurred".

The fix was to read ``MAX_LIMIT`` instead of typing a number. The guard against the next
one is here: the route's gathering runs for real against stubbed dependencies, so a
value the shared validators reject fails a test instead of a field session.

No database and no threads: the dependencies are overridden, and the stage entry points
are stubbed — what is under test is everything the router does BEFORE handing over.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import accuracy as accuracy_router
from app.core.config import Settings
from app.services import accuracy_service

IMAGE_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()

#: Captured at import, BEFORE any fixture patches the module — the one test that wants
#: the real validator has to restore this, not the already-stubbed attribute.
_REAL_START_MEASURE = accuracy_service.start_measure


class _Camera:
    """The WIRE model's shape — what `to_image_camera_read` returns."""

    fx, fy, cx, cy = 2800.0, 2800.0, 2016.0, 1134.0
    k1 = k2 = p1 = p2 = k3 = 0.0
    lat, lon = 34.113, 36.020
    mast_offset_m = 2.5
    img_w, img_h = 4032, 2268
    no_calibration = False
    fov_h_deg = None


class _NoCalCamera(_Camera):
    """★ Yamouneh2's station (2026-09-09): no fx/fy, no-calibration mode, seed blank."""

    fx = fy = None
    no_calibration = True
    fov_h_deg = None


class _HoleyCamera(_Camera):
    """A CALIBRATED station missing its focal — still a refusal."""

    fx = fy = None


#: Which station the fake camera service hands out — a test swaps it with monkeypatch.
CAMERA: dict[str, type] = {"cls": _Camera}


class _Gcp:
    def __init__(self, n: int) -> None:
        self.pixel_x, self.pixel_y = 100.0 * n, 80.0 * n
        self.elevation_m = 1380.0 + n
        self.geom = None  # `as_lonlat` is stubbed below


class _Image:
    id = IMAGE_ID
    project_id = PROJECT_ID
    filename = "DJI_0124.JPG"
    storage_path = "images/dji_0124.jpg"
    width, height = 4032, 2268


class _Caps:
    allows_caching = True
    tile_size_px = 512


class _Imagery:
    def capabilities(self, _name: str) -> _Caps:
        return _Caps()

    def default_provider_name(self) -> str:
        return "mapbox_satellite"


class _DemService:
    def __init__(self, path: Path) -> None:
        self._path = path

    def elevation_dem_path(self, _project_id: uuid.UUID, _image_id: uuid.UUID) -> Path:
        return self._path


class _Storage:
    def local_path(self, key: str) -> str:
        return f"/tmp/{key}"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    started: dict[str, Any] = {}

    async def fake_get_image(image_id: uuid.UUID, **_kw: Any) -> _Image:
        assert image_id == IMAGE_ID
        return _Image()

    async def fake_list_gcps(_db: Any, _image_id: uuid.UUID, **kwargs: Any):
        # ★ THE ASSERTION THAT WOULD HAVE CAUGHT THE BUG: the router builds a real
        #   `PaginationParams`, so an out-of-range limit raises before reaching here.
        assert kwargs["pagination"].limit <= 200
        return [_Gcp(n) for n in range(1, 5)], 4

    class _CameraService:
        def __init__(self, _db: Any) -> None: ...

        async def get(self, _image_id: uuid.UUID) -> _Camera:
            return CAMERA["cls"]()

    def fake_start(kind: str):
        def _start(inputs: Any) -> accuracy_service.AccuracyRun:
            started["kind"] = kind
            started["inputs"] = inputs
            return accuracy_service.AccuracyRun(
                run_id="test", kind=kind, image_id=IMAGE_ID, project_id=PROJECT_ID  # type: ignore[arg-type]
            )

        return _start

    monkeypatch.setattr(accuracy_router.deps, "get_image", fake_get_image)
    monkeypatch.setattr(accuracy_router.deps, "list_gcps_for_image", fake_list_gcps)
    monkeypatch.setattr(accuracy_router, "ImageCameraService", _CameraService)
    monkeypatch.setattr(accuracy_router, "to_image_camera_read", lambda row, **_k: row)
    monkeypatch.setattr(accuracy_router, "as_lonlat", lambda _geom: (36.02, 34.11))
    monkeypatch.setattr(accuracy_service, "start_measure", fake_start("measure"))
    monkeypatch.setattr(accuracy_service, "start_suggest", fake_start("suggest"))
    monkeypatch.setattr(
        accuracy_service, "make_mosaic_writer", lambda _imagery, _provider: (lambda *a, **k: None)
    )

    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"tif")
    settings = Settings(accuracy_output_dir=tmp_path / "accuracy")

    app = FastAPI()
    app.include_router(accuracy_router.router)
    app.dependency_overrides[deps.get_db] = lambda: None
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_dem_service] = lambda: _DemService(dem)
    app.dependency_overrides[deps.get_imagery_service] = lambda: _Imagery()
    app.dependency_overrides[deps.get_storage] = lambda: _Storage()
    app.dependency_overrides[deps.require_writable] = lambda: None

    test_client = TestClient(app)
    test_client.started = started  # type: ignore[attr-defined]
    return test_client


class TestMeasureRoute:
    def test_pressing_measure_gathers_the_pose_and_starts_a_run(self, client: TestClient) -> None:
        """★ The regression: this returned 500 before `MAX_LIMIT` was read properly."""
        response = client.post("/accuracy/measure", json={"image_id": str(IMAGE_ID)})
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["kind"] == "measure"
        assert body["image_id"] == str(IMAGE_ID)

        inputs = client.started["inputs"]  # type: ignore[attr-defined]
        assert len(inputs.pose.gcps) == 4
        assert inputs.pose.gcps_total == 4
        assert inputs.pose.fx == _Camera.fx
        assert inputs.pose.cam_height_m == _Camera.mast_offset_m
        # Defaults reach the core unchanged.
        assert (inputs.params.tile, inputs.params.stride) == (128, 64)
        assert inputs.provider_name == "mapbox_satellite"

    def test_a_no_calibration_station_is_measured_not_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """★ 2026-09-09: "Measure error" on Yamouneh2 was refused with "no intrinsics
        (fx, fy unset)" — the station is in no-calibration mode, which every other
        pipeline already accepts. The focal is solved server-side from the points."""
        monkeypatch.setitem(CAMERA, "cls", _NoCalCamera)
        response = client.post("/accuracy/measure", json={"image_id": str(IMAGE_ID)})
        assert response.status_code == 202, response.text
        inputs = client.started["inputs"]  # type: ignore[attr-defined]
        assert inputs.pose.no_calibration is True
        assert inputs.pose.fx is None and inputs.pose.fov_h_deg is None

    def test_a_calibrated_station_with_holes_still_names_them(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(CAMERA, "cls", _HoleyCamera)
        response = client.post("/accuracy/measure", json={"image_id": str(IMAGE_ID)})
        assert response.status_code == 422
        assert "fx, fy unset" in response.json()["error"]["message"] if "error" in response.json() else "fx, fy unset" in response.text

    def test_the_measurement_parameters_travel(self, client: TestClient) -> None:
        response = client.post(
            "/accuracy/measure",
            json={"image_id": str(IMAGE_ID), "tile": 256, "stride": 128, "max_range": 800},
        )
        assert response.status_code == 202, response.text
        params = client.started["inputs"].params  # type: ignore[attr-defined]
        assert (params.tile, params.stride, params.max_range) == (256, 128, 800.0)

    def test_a_stride_wider_than_the_tile_is_a_422_that_names_the_fix(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The service's refusal must surface as an actionable 422, not a 500."""
        monkeypatch.setattr(accuracy_service, "start_measure", _REAL_START_MEASURE)
        response = client.post(
            "/accuracy/measure",
            json={"image_id": str(IMAGE_ID), "tile": 64, "stride": 256},
        )
        assert response.status_code == 422
        assert "overlap" in response.text

    def test_suggest_gathers_the_same_pose(self, client: TestClient) -> None:
        response = client.post("/accuracy/suggest", json={"image_id": str(IMAGE_ID), "count": 3})
        assert response.status_code == 202, response.text
        inputs = client.started["inputs"]  # type: ignore[attr-defined]
        assert inputs.count == 3
        assert len(inputs.pose.gcps) == 4


class TestStateRoute:
    def test_an_unmeasured_photograph_reports_empty_rather_than_failing(
        self, client: TestClient
    ) -> None:
        response = client.get(f"/accuracy/images/{IMAGE_ID}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["measurement"] is None
        assert body["correction"] is None
        assert body["adoption"] is None
        assert body["layers"] == []

    def test_a_layer_that_does_not_exist_yet_404s_with_what_is_available(
        self, client: TestClient
    ) -> None:
        response = client.get(f"/accuracy/images/{IMAGE_ID}/layers/heat_raw")
        assert response.status_code == 404
        assert "measure it first" in response.text
