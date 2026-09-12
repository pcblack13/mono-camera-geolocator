"""Carrying control points onto a new frame of the same camera (2026-09-09).

★ What these pin: each point is recreated THROUGH ``create_manual`` on the target
image at the same pixel and the same spot, with the surveyor's judgement, code,
name, export flag and the original click's basemap/zoom kept; a point with no
recorded zoom gets the copy default; a point with no geometry is skipped.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services import gcp_service as module
from app.services.gcp_service import GcpService


class _Repo:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    async def list_for_image(self, image_id: uuid.UUID, **_kw: object) -> tuple[list, int]:
        return [r for r in self.rows if r.image_id == image_id], len(self.rows)


def _row(image_id: uuid.UUID, **over: object) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(), image_id=image_id, pixel_x=412.5, pixel_y=300.25, geom="POINT",
        confidence=80.0, code="GCP-07", name="fence corner", is_included_in_export=True,
        reference_imagery={"provider": "esri_world_imagery", "zoom": 19},
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> tuple[GcpService, list]:
    created: list = []
    svc = GcpService.__new__(GcpService)

    async def fake_create_manual(image, body):  # noqa: ANN001, ANN202
        created.append((image, body))
        return SimpleNamespace(id=uuid.uuid4(), image_id=image.id, body=body)

    svc.create_manual = fake_create_manual  # type: ignore[method-assign]
    monkeypatch.setattr(module, "as_lonlat", lambda geom: None if geom is None else (36.0172, 34.1053), raising=False)
    return svc, created


class TestCopyTo:
    @pytest.mark.asyncio
    async def test_each_point_is_recreated_on_the_target_at_the_same_pixel_and_spot(
        self, service: tuple[GcpService, list], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc, created = service
        src = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4())
        dst = SimpleNamespace(id=uuid.uuid4(), project_id=src.project_id)
        svc._gcps = _Repo([_row(src.id), _row(src.id, code="GCP-08", confidence=60.0, reference_imagery=None)])
        import app.db.types as types_mod

        monkeypatch.setattr(types_mod, "as_lonlat", lambda geom: (36.0172, 34.1053))
        out = await svc.copy_to(src, dst)
        assert len(out) == 2 and len(created) == 2
        image, body = created[0]
        assert image is dst
        assert (body.image_px.x, body.image_px.y) == (412.5, 300.25)
        assert (body.lat, body.lon) == (34.1053, 36.0172)
        assert int(getattr(body.declared_confidence, "value", body.declared_confidence)) == 4  # 80 → band 4
        assert body.map_zoom == 19 and getattr(body.provider, "value", body.provider) == "esri_world_imagery"
        assert body.code == "GCP-07" and body.name == "fence corner" and body.is_included_in_export
        # no recorded click: the copy default zoom, no provider named
        _image, second = created[1]
        assert second.map_zoom == module._COPY_DEFAULT_ZOOM and second.provider is None
        assert int(getattr(second.declared_confidence, "value", second.declared_confidence)) == 3  # 60 → band 3

    @pytest.mark.asyncio
    async def test_a_basemap_this_build_does_not_know_does_not_stop_the_point(
        self, service: tuple[GcpService, list], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc, created = service
        src = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4())
        dst = SimpleNamespace(id=uuid.uuid4(), project_id=src.project_id)
        svc._gcps = _Repo([_row(src.id, reference_imagery={"provider": "retired_basemap", "zoom": 17})])
        import app.db.types as types_mod

        monkeypatch.setattr(types_mod, "as_lonlat", lambda geom: (36.0, 34.0))
        out = await svc.copy_to(src, dst)
        assert len(out) == 1 and created[0][1].provider is None and created[0][1].map_zoom == 17

    @pytest.mark.asyncio
    async def test_a_point_without_geometry_is_skipped_not_invented(
        self, service: tuple[GcpService, list], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc, created = service
        src = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4())
        dst = SimpleNamespace(id=uuid.uuid4(), project_id=src.project_id)
        svc._gcps = _Repo([_row(src.id, geom=None)])
        import app.db.types as types_mod

        monkeypatch.setattr(types_mod, "as_lonlat", lambda geom: None if geom is None else (1.0, 2.0))
        out = await svc.copy_to(src, dst)
        assert out == [] and created == []

    def test_the_declared_band_is_the_nearest_score(self) -> None:
        from app.schemas.gcp import SURVEYOR_CONFIDENCE_TO_SCORE

        for band, score in SURVEYOR_CONFIDENCE_TO_SCORE.items():
            assert GcpService._declared_for(score) == band
            assert GcpService._declared_for(score + 3.0) == band
