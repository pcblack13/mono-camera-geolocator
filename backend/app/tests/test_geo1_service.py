"""``geo1_service`` — the sender reader's refusals happen before any byte is sent.

★ WHY THIS FILE EXISTS (2026-09-10). ``mjpeg_frames`` and ``ndjson_lines`` were
plain generators, so "not connected to X" surfaced on the FIRST ``next()`` —
inside the streaming body, after the router had answered ``200`` and after its
``except Geo1Error`` had been skipped. Every unconnected sender was a 500 with a
traceback, once per retry, for ever. These tests pin the refusal to the call.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import live as live_router
from app.services import geo1_service

UNKNOWN = "10.10.10.1:5000"


def test_mjpeg_frames_refuses_when_called_not_when_iterated() -> None:
    with pytest.raises(geo1_service.Geo1Error, match="not connected"):
        geo1_service.mjpeg_frames(UNKNOWN)


def test_ndjson_lines_refuses_when_called_not_when_iterated() -> None:
    with pytest.raises(geo1_service.Geo1Error, match="not connected"):
        geo1_service.ndjson_lines(UNKNOWN)


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(live_router.router)
    return TestClient(app)


@pytest.mark.parametrize("path", ["stream", "detections.ndjson"])
def test_unconnected_sender_is_a_409_not_a_500(client: TestClient, path: str) -> None:
    res = client.get(f"/live/senders/{UNKNOWN}/{path}")
    assert res.status_code == 409, res.text
    # The stream says "not connected"; the record channel tries to connect first
    # (2026-09-10) and, with nobody announcing, says so — both name the sender.
    assert UNKNOWN in res.json()["detail"]


def test_connected_sender_streams_the_frame_it_holds() -> None:
    link = geo1_service.Link(sender_id="t:1", host="127.0.0.1", port=1, control_port=2)
    with geo1_service._LINKS_LOCK:
        geo1_service._LINKS["t:1"] = link
    try:
        link.publish({"seq": 1, "w": 4, "h": 3, "objects": []}, b"\xff\xd8jpeg")
        frames = geo1_service.mjpeg_frames("t:1")  # held: dropping it ends the viewer
        part = next(frames)
        assert part.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
        assert part.endswith(b"\xff\xd8jpeg\r\n")
        assert link.viewers == 1
    finally:
        geo1_service.disconnect("t:1")
