"""``GET /lut/library/{site}/lookup`` — the monitoring page's live predict (2026-09-10).

★ WHAT IS PINNED: the cursor reads the SAME arrays a detection is placed through,
with the same media→table scaling; sky answers ``placed: false`` with a reason,
not an error; the elevation comes from the camera project's DEM when asked and
is null — never zero — when nothing answers.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import lut as lut_router

if TYPE_CHECKING:
    from pathlib import Path

H, W = 8, 10


def _bundle(root: Path, site: str = "synthetic") -> Path:
    folder = root / f"{site}_lut"
    folder.mkdir(parents=True)
    lat = np.full((H, W), 34.1)
    lon = np.full((H, W), 36.0)
    lat[0, 0] = np.nan  # sky
    lon[0, 0] = np.nan
    # A gradient so a scaled pixel can be told from an unscaled one.
    lat[4, 5] = 34.5
    np.save(folder / "lat.npy", lat)
    np.save(folder / "lon.npy", lon)
    (folder / "manifest.json").write_text(json.dumps({"site_name": site}), encoding="utf-8")
    return folder


class _Elevation:
    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[float, float]], object]] = []

    def sample_lonlat(self, points: list[tuple[float, float]], *, project_id: object = None) -> list[SimpleNamespace]:
        self.calls.append((list(points), project_id))
        return [SimpleNamespace(available=True, elevation_m=1312.4, source="project_dem")]


@pytest.fixture()
def rig(tmp_path: Path) -> tuple[TestClient, _Elevation]:
    lut_root = tmp_path / "lut"
    _bundle(lut_root)
    settings = SimpleNamespace(lut_output_dir=lut_root)
    elevation = _Elevation()
    app = FastAPI()
    app.include_router(lut_router.router)
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_elevation_service] = lambda: elevation
    return TestClient(app), elevation


def test_a_pixel_is_placed_through_the_table(rig) -> None:
    client, _ = rig
    body = client.get("/lut/library/synthetic/lookup", params={"u": 5, "v": 4}).json()
    assert body["placed"] is True
    assert (body["lat"], body["lon"]) == (34.5, 36.0)
    assert body["elevation_m"] is None  # no project asked — null, not zero
    assert body["reason"] is None


def test_the_media_size_scales_into_the_table(rig) -> None:
    # A 20x16 stream on a 10x8 table: media (10, 8) is table (5, 4).
    client, _ = rig
    body = client.get(
        "/lut/library/synthetic/lookup", params={"u": 10, "v": 8, "w": 20, "h": 16}
    ).json()
    assert (body["lut_u"], body["lut_v"]) == (5.0, 4.0)
    assert body["lat"] == 34.5


def test_sky_and_off_table_are_answers_not_errors(rig) -> None:
    client, _ = rig
    sky = client.get("/lut/library/synthetic/lookup", params={"u": 0, "v": 0})
    assert sky.status_code == 200 and sky.json()["placed"] is False
    assert sky.json()["reason"] == "no_terrain"
    off = client.get("/lut/library/synthetic/lookup", params={"u": 99, "v": 1})
    assert off.status_code == 200 and off.json()["reason"] == "off_table"


def test_the_elevation_comes_from_the_camera_projects_dem(rig) -> None:
    client, elevation = rig
    pid = "00000000-0000-4000-8000-000000000901"
    body = client.get(
        "/lut/library/synthetic/lookup", params={"u": 5, "v": 4, "project_id": pid}
    ).json()
    assert body["elevation_m"] == 1312.4 and body["elevation_source"] == "project_dem"
    # lon first, as the service is spelled; the project id travels through.
    assert elevation.calls[0][0] == [(36.0, 34.5)]
    assert str(elevation.calls[0][1]) == pid


def test_an_unknown_site_is_a_404(rig) -> None:
    client, _ = rig
    assert client.get("/lut/library/nope/lookup", params={"u": 1, "v": 1}).status_code == 404
