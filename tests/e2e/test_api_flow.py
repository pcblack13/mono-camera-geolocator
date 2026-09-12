"""★ The API-driven end-to-end: upload -> annotate -> correspond -> export over HTTP.

*"`tests/e2e/` — upload -> annotate -> match -> export using the `fixture` provider, with no
network, no weights and no GPU."* (§13.1 IU-31.) SCOPE.md §1 replaces `match` with the manual
correspondence, so the HTTP chain proved here is:

    POST /images (upload the field photo)
      -> POST /images/{id}/annotations (mark a landmark)
      -> POST /gcps (commit a photo-pixel <-> map-click correspondence, source='manual')
      -> POST /exports (CSV/GeoJSON), 200
    and, for the deferred seam:
      -> POST /images/{id}/match -> 501 with feature: "deferred", NOT 404, NOT a fake result.

**Why this skips on the dev machine.** It drives the real ASGI app over httpx's in-process
transport (no live server — §13.1 IU-21), which needs `fastapi`, `pydantic`, `sqlalchemy`
and a database. None of those exist here (§0.1), and `backend/app/main.py` / `backend/app/api`
are not built yet (IU-21). So this module imports the app behind guards and skips cleanly.
Its offline sibling, `test_manual_gcp_offline.py`, exercises the same chain at the library
level and **runs today** — between them the flow is covered from both ends.

★ `@pytest.mark.db`: even once the app exists, this needs PostGIS. Auto-skips unless
`LE_DATABASE_URL` is set (`tests/conftest.py`).
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

pytestmark = pytest.mark.db

# The whole module needs the backend stack. Guard at collection so a machine without it
# skips rather than errors — importorskip raises Skipped, which pytest treats as a skip for
# the entire module.
pytest.importorskip("fastapi", reason="the API e2e needs fastapi (§0.1: not installed here)")
pytest.importorskip("httpx", reason="the API e2e drives the app over httpx ASGI transport")
pytest.importorskip("sqlalchemy", reason="the API e2e needs the ORM")


def _load_app() -> Any:
    """Import the FastAPI app, skipping if IU-21 has not landed it yet."""
    try:
        from app.main import app  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - any import failure means "not ready to drive"
        pytest.skip(f"backend app is not importable yet: {exc}")
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """An httpx client bound to the ASGI app in-process. ★ No live server (§13.1 IU-21).

    Forces the `fixture` imagery provider so the flow is offline end to end — the same
    provider `make seed && make up` uses, so this test drives the demonstrable product.
    """
    # ★ TestClient, not httpx.Client(transport=ASGITransport): ASGITransport is
    #   async-only in httpx ≥ 0.28, and a sync Client over it dies on __enter__.
    #   TestClient IS an httpx.Client (starlette drives the ASGI app through an
    #   anyio portal), so every call site keeps the same API.
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LE_IMAGERY_PROVIDER", "fixture")
    monkeypatch.setenv("LE_IMAGERY_OFFLINE", "true")
    # The dev box's backend/.env sets a hard operator allow-list that (correctly)
    # does not include the test fixture provider; a GCP click on it would 403.
    monkeypatch.setenv("LE_ALLOWED_PROVIDERS", "fixture,local_orthophoto")

    app = _load_app()
    with TestClient(app, base_url="http://testserver") as http:
        yield http


@pytest.fixture
def project_id(client: Any) -> str:
    """A project to upload into — every image belongs to one since the workspace rework."""
    response = client.post("/api/v1/projects", json={"name": f"e2e-{uuid.uuid4().hex[:8]}"})
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


@pytest.fixture
def uploaded_image(client: Any, field_photo: Path, project_id: str) -> str:
    """Upload the committed field photo and return its id."""
    with field_photo.open("rb") as handle:
        response = client.post(
            "/api/v1/images",
            data={"project_id": project_id},
            files={"file": ("field_photo.jpg", io.BytesIO(handle.read()), "image/jpeg")},
        )
    # 202: upload responds immediately with an {image, job} envelope; the ingest
    # job runs on (or without) the worker while the image is already addressable.
    assert response.status_code in (200, 201, 202), response.text
    return str(response.json()["image"]["id"])


# =============================================================================
# The built path — the manual product over HTTP
# =============================================================================


def test_upload_stores_the_photo_and_its_metadata(
    client: Any, field_photo: Path, project_id: str
) -> None:
    """★ Upload succeeds and the stored metadata reflects the file (§3: BUILD, in full)."""
    with field_photo.open("rb") as handle:
        response = client.post(
            "/api/v1/images",
            data={"project_id": project_id},
            files={"file": ("field_photo.jpg", io.BytesIO(handle.read()), "image/jpeg")},
        )
    assert response.status_code in (200, 201, 202), response.text
    body = response.json()["image"]
    assert body["width"] == 640
    assert body["height"] == 480


def test_a_manual_gcp_round_trips_as_a_direct_observation(
    client: Any, uploaded_image: str, scene_lonlat: tuple[float, float]
) -> None:
    """★★ SCOPE.md §5 over the wire: a committed correspondence is `source='manual'`.

    The pixel coordinate is in original image space; the map click is EPSG:4326. The GCP that
    comes back records `source='manual'` and the surveyor's own confidence — never a computed
    one. snake_case on the wire (L9), both directions.
    """
    lon, lat = scene_lonlat
    response = client.post(
        f"/api/v1/images/{uploaded_image}/gcps",
        json={
            "image_px": {"x": 412.0, "y": 331.0},
            "lon": lon,
            "lat": lat,
            "declared_confidence": 4,
            "map_zoom": 18,
        },
    )
    assert response.status_code in (200, 201), response.text
    gcp = response.json()
    assert gcp["source"] == "manual", "★ a manual GCP is a direct observation"
    assert gcp["declared_confidence"] == 4, "★ the surveyor's declared confidence, unaltered"


def test_export_returns_a_survey_deliverable(client: Any, uploaded_image: str) -> None:
    """★ CSV export over HTTP is accepted as a job with a downloadable result URL."""
    response = client.post(f"/api/v1/images/{uploaded_image}/export", json={"format": "csv"})
    assert response.status_code in (200, 201, 202), response.text
    job = response.json()
    assert job["type"] == "export"
    assert job["result_url"], "the job must name where the deliverable will be downloadable"


# =============================================================================
# The deferred seam — 501, not 404, not a fake result (SCOPE.md §4 rule 3)
# =============================================================================


@pytest.mark.parametrize(
    ("path_suffix", "method"),
    [
        ("match", "post"),
        ("suggest-landmarks", "post"),
        ("segment", "post"),
        ("camera-pose", "get"),  # a reading, not an action — registered as GET
        ("heatmap", "get"),
    ],
)
def test_deferred_endpoints_return_501_feature_deferred(
    client: Any, uploaded_image: str, path_suffix: str, method: str
) -> None:
    """★★ Every deferred endpoint is REGISTERED and returns 501 `feature: "deferred"`.

    Not 404 — the feature is planned, not absent (SCOPE.md §4 rule 3). Not a fabricated
    result — a confidently-wrong coordinate is this system's worst failure mode. The uniform
    error envelope carries `feature: "deferred"` so the UI can grey the control out with an
    honest tooltip rather than spinning forever.
    """
    url = f"/api/v1/images/{uploaded_image}/{path_suffix}"
    response = client.post(url, json={}) if method == "post" else client.get(url)
    assert response.status_code == 501, (
        f"{path_suffix} returned {response.status_code}, not 501. A deferred feature is "
        "present-but-refusing; 404 would say it does not exist and break the re-enabling "
        "story (SCOPE.md §7)."
    )
    body = response.json()
    # The marker grew up: `feature` is now a structured object carrying status,
    # name, reason and docs_url. Accept the old bare-string form too — the UI's
    # question is only "is this deferral or breakage?".
    feature = body.get("feature") or body.get("error", {}).get("feature")
    marker = feature.get("status") if isinstance(feature, dict) else feature
    assert marker == "deferred", (
        f"{path_suffix}: 501 without the feature-deferred marker — the UI cannot tell this "
        "apart from an ordinary server error"
    )
    if isinstance(feature, dict):
        assert feature.get("reason"), "a deferral must say WHY, in words, for the tooltip"
