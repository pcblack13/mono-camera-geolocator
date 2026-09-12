"""Detection-data feeds — serial/UART and embedded integrations (2026-09-02).

★ What these pin: a wire line (JSON or CSV) becomes a mark in the SAME shape a
detection session produces (so the map needs no second code path), garbage lines
are counted rather than fatal, out-of-range coordinates are refused, a
pipe-backed "serial port" streams end to end, and the HTTP surface serves the
cursor exactly as ``/detection/sessions/{id}/marks`` does.
"""

from __future__ import annotations

import os
import time
from collections import deque

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import live as live_router
from app.services import live_data_service
from app.services import live_data_service as lds
from app.services.live_data_service import parse_feed_line, start_feed, stop_feed

# ── the parser ──────────────────────────────────────────────────────────────────


def test_json_line_becomes_a_detection_shaped_mark() -> None:
    mark = parse_feed_line(
        '{"lat": 34.1047, "lon": 36.0163, "cls_name": "car", "score": 0.82, "track_id": 3}',
        seq=7,
        t0=time.monotonic(),
    )
    assert mark is not None
    assert (mark["lat"], mark["lon"]) == (34.1047, 36.0163)
    assert mark["cls_name"] == "car"
    assert mark["score"] == 0.82
    assert mark["track_id"] == 3
    # The detection-mark contract the map relies on:
    for key in ("frame_index", "time_s", "u", "v", "predicted", "detected_at"):
        assert key in mark
    assert mark["detected_at"].endswith("Z")


def test_csv_line_with_and_without_optionals() -> None:
    full = parse_feed_line("34.1,36.0,person,0.5,#2", 0, time.monotonic())
    assert full is not None
    assert (full["cls_name"], full["score"], full["track_id"]) == ("person", 0.5, 2)
    bare = parse_feed_line("34.1, 36.0", 0, time.monotonic())
    assert bare is not None
    assert (bare["cls_name"], bare["score"], bare["track_id"]) == ("object", 1.0, None)


def test_garbage_is_refused_not_fatal() -> None:
    t0 = time.monotonic()
    for line in (
        "",
        "# a comment",
        "not,numbers",
        '{"lon": 36.0}',  # no latitude
        "950,36.0",  # not a latitude at all
        "34.1,190",  # not a longitude
        '{"lat": "x", "lon": 36}',
    ):
        assert parse_feed_line(line, 0, t0) is None, line


# ── a serial port, played by a pipe ─────────────────────────────────────────────


def test_pipe_backed_serial_feed_streams_end_to_end(tmp_path) -> None:
    # ★ A FIFO stands in for /dev/ttyUSB0 — same open/read path, no hardware.
    fifo = tmp_path / "ttyTEST"
    os.mkfifo(fifo)
    writer = os.open(fifo, os.O_RDWR)  # RDWR so the reader never sees EOF-close
    try:
        feed = start_feed(str(fifo).replace(str(fifo), f"serial://{fifo}?baud=115200"))
        os.write(writer, b'{"lat": 34.1, "lon": 36.0, "cls_name": "car"}\n')
        os.write(writer, b"garbage line\n")
        os.write(writer, b"34.2,36.1,person,0.9,4\n")
        deadline = time.time() + 5
        while time.time() < deadline and feed.lines_ok < 2:
            time.sleep(0.05)
        assert feed.lines_ok == 2
        assert feed.lines_bad == 1
        assert feed.status == "running"
        assert [m["cls_name"] for m in feed.marks] == ["car", "person"]
        # The cursor: everything, then only what is new.
        total, marks = live_data_service.marks_since(feed.feed_id, 0)
        assert total == 2 and len(marks) == 2
        total2, marks2 = live_data_service.marks_since(feed.feed_id, total)
        assert total2 == 2 and marks2 == []
    finally:
        stop_feed(feed.feed_id)
        os.close(writer)


def test_start_is_idempotent_per_source_and_refuses_nonsense(tmp_path) -> None:
    fifo = tmp_path / "ttyIDEM"
    os.mkfifo(fifo)
    writer = os.open(fifo, os.O_RDWR)
    try:
        a = start_feed(f"serial://{fifo}")
        b = start_feed(f"serial://{fifo}")
        assert a.feed_id == b.feed_id  # one reader per port, never two fighting
    finally:
        stop_feed(a.feed_id)
        os.close(writer)
    with pytest.raises(live_data_service.DataFeedError):
        start_feed("ftp://nope")
    with pytest.raises(live_data_service.DataFeedError):
        start_feed("")


# ── the HTTP surface ────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(live_router.router)
    return TestClient(app)


def test_endpoints_roundtrip(client: TestClient, tmp_path) -> None:
    fifo = tmp_path / "ttyAPI"
    os.mkfifo(fifo)
    writer = os.open(fifo, os.O_RDWR)
    feed_id = ""
    try:
        res = client.post("/live/data-feeds", json={"source": f"serial://{fifo}?baud=9600"})
        assert res.status_code == 200
        feed_id = res.json()["feed_id"]
        os.write(writer, b"34.5,36.5,bus,0.7,1\n")
        deadline = time.time() + 5
        while time.time() < deadline:
            body = client.get(f"/live/data-feeds/{feed_id}").json()
            if body["lines_ok"] >= 1:
                break
            time.sleep(0.05)
        assert body["lines_ok"] == 1
        marks = client.get(f"/live/data-feeds/{feed_id}/marks?since=0").json()
        assert marks["next_index"] == 1
        assert marks["marks"][0]["cls_name"] == "bus"
        assert client.delete(f"/live/data-feeds/{feed_id}").status_code == 204
    finally:
        if feed_id:
            import contextlib

            with contextlib.suppress(live_data_service.DataFeedError):
                live_data_service.stop_feed(feed_id)
        os.close(writer)
    assert client.get("/live/data-feeds/nope").status_code == 404


# ── before the Raspberry Pi test (2026-09-07) ────────────────────────────────


def test_the_senders_own_clock_becomes_the_marks_time() -> None:
    """★ A Pi says WHEN it detected; the receiver's arrival time is a fallback."""
    iso = lds.parse_feed_line('{"lat": 34.1, "lon": 36.0, "t": "2026-09-07T10:00:00Z"}', 0, 0.0)
    assert iso is not None and iso["detected_at"] == "2026-09-07T10:00:00Z"
    # every spelling the contract names, and a naive string read as UTC
    for key in ("detected_at", "time_utc", "timestamp", "time", "ts", "t"):
        line = f'{{"lat": 1, "lon": 2, "{key}": "2026-09-07T10:00:00"}}'
        mark = lds.parse_feed_line(line, 0, 0.0)
        assert mark is not None and mark["detected_at"] == "2026-09-07T10:00:00Z", key
    # epoch seconds AND milliseconds — a device sends whichever its clock speaks
    secs = lds.parse_feed_line('{"lat": 1, "lon": 2, "ts": 1789012800}', 0, 0.0)
    ms = lds.parse_feed_line('{"lat": 1, "lon": 2, "ts": 1789012800500}', 0, 0.0)
    assert secs is not None and ms is not None
    assert secs["detected_at"].startswith("2026-09-10T04:00:00")
    assert ms["detected_at"].startswith("2026-09-10T04:00:00.5")
    # an unreadable time is NOT a reason to drop the detection — arrival stands in
    broken = lds.parse_feed_line('{"lat": 1, "lon": 2, "t": "half past ten"}', 0, 0.0)
    assert broken is not None and broken["detected_at"].endswith("Z")
    assert broken["_identified"] is False
    # a line with no time at all is stamped on arrival, and claims no identity
    bare = lds.parse_feed_line("34.1,36.0,car", 0, 0.0)
    assert bare is not None and bare["_identified"] is False


def test_a_sender_that_knows_its_pixel_may_say_so() -> None:
    """u/v travel when given, stay null when not — never a fabricated zero."""
    with_px = lds.parse_feed_line('{"lat": 1, "lon": 2, "u": 640.5, "v": 360}', 0, 0.0)
    assert with_px is not None and (with_px["u"], with_px["v"]) == (640.5, 360.0)
    without = lds.parse_feed_line('{"lat": 1, "lon": 2}', 0, 0.0)
    assert without is not None and without["u"] is None and without["v"] is None
    assert with_px["_identified"] is False  # a pixel is not an identity


def test_a_resent_line_is_ingested_once() -> None:
    """★ A device that answers with its WHOLE table each time must not multiply.

    The reader reconnects to an http feed that ends (see ``_run``), so the same
    rows arrive again. A line carrying its own identity — an id, or its own
    timestamp — is placed once; one carrying neither cannot be told from a
    genuine second detection, and is taken at face value.
    """
    feed = lds.DataFeed(feed_id="dedup-test", source="http://pi/detections")
    identified = '{"lat": 34.1, "lon": 36.0, "cls_name": "car", "t": "2026-09-07T10:00:00Z"}'
    by_id = '{"lat": 34.2, "lon": 36.1, "id": 7}'
    anonymous = "34.3,36.2,person"
    for _ in range(3):  # three reads of the same table
        lds._ingest(feed, identified, 0.0)
        lds._ingest(feed, by_id, 0.0)
        lds._ingest(feed, anonymous, 0.0)
    # the two identified rows landed ONCE each; the anonymous one every time
    assert [m["cls_name"] for m in feed.marks] == ["car", "object", "person", "person", "person"]
    assert feed.lines_ok == 5
    assert feed.lines_repeat == 4
    # …and a DIFFERENT detection at another second is not mistaken for a repeat
    lds._ingest(feed, '{"lat": 34.1, "lon": 36.0, "cls_name": "car", "t": "2026-09-07T10:00:01Z"}', 0.0)
    assert len(feed.marks) == 6 and feed.lines_repeat == 4


def test_the_identity_memory_is_bounded(monkeypatch) -> None:
    """A device running for a week must not grow the memory without limit."""
    monkeypatch.setattr(lds, "MAX_SEEN", 4)
    feed = lds.DataFeed(feed_id="bounded", source="http://pi/x")
    feed._seen = deque(maxlen=4)
    for i in range(10):
        lds._ingest(feed, f'{{"lat": 1, "lon": 2, "id": {i}}}', 0.0)
    assert len(feed._seen) == 4 and len(feed._seen_set) == 4
    assert feed.lines_ok == 10 and feed.lines_repeat == 0
    # the oldest identity was forgotten, so its line would be taken again
    lds._ingest(feed, '{"lat": 1, "lon": 2, "id": 0}', 0.0)
    assert feed.lines_ok == 11
    # …while a still-remembered one is refused
    lds._ingest(feed, '{"lat": 1, "lon": 2, "id": 9}', 0.0)
    assert feed.lines_ok == 11 and feed.lines_repeat == 1


def test_a_pi_over_http_streams_end_to_end(client: TestClient) -> None:
    """★ THE PI TEST, in miniature: an http NDJSON feed → marks on the cursor.

    A tiny server stands in for the Pi: same transport (http over the LAN), same
    wire (one JSON object per line, with the sender's own clock). What the page
    polls is what the map draws.
    """
    import http.server
    import threading as th

    lines = [
        '{"lat": 34.1047, "lon": 36.0163, "cls_name": "car", "score": 0.82, "track_id": 3, "t": "2026-09-07T10:00:00Z"}',
        '{"lat": 34.1050, "lon": 36.0170, "cls_name": "person", "score": 0.7, "t": "2026-09-07T10:00:01Z"}',
        "# a comment the Pi logs are allowed to contain",
        "not a detection at all",
    ]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(("\n".join(lines) + "\n").encode())

        def log_message(self, *_a: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    th.Thread(target=server.serve_forever, daemon=True).start()
    source = f"http://127.0.0.1:{server.server_port}/detections"
    try:
        started = client.post("/live/data-feeds", json={"source": source}).json()
        feed_id = started["feed_id"]
        deadline = time.time() + 6
        marks: list[dict] = []
        while time.time() < deadline and len(marks) < 2:
            page = client.get(f"/live/data-feeds/{feed_id}/marks?since=0").json()
            marks = page["marks"]
            time.sleep(0.1)
        assert [m["cls_name"] for m in marks] == ["car", "person"]
        assert marks[0]["detected_at"] == "2026-09-07T10:00:00Z"
        assert marks[0]["track_id"] == 3
        # a feed's mark has no pixel unless the sender gave one
        assert marks[0]["u"] is None
        # ★ The server keeps re-reading a feed that ENDS — and must not multiply
        #   the table. Give it two reconnect windows.
        time.sleep(lds._RETRY_DELAY_S * 2 + 1)
        again = client.get(f"/live/data-feeds/{feed_id}/marks?since=0").json()["marks"]
        assert len(again) == 2, [m["cls_name"] for m in again]
        status = client.get(f"/live/data-feeds/{feed_id}").json()
        assert status["lines_ok"] == 2
        assert status["lines_bad"] >= 1  # the unparseable line was counted
        assert status["lines_repeat"] >= 2  # the second read was recognised
    finally:
        client.delete(f"/live/data-feeds/{feed_id}")
        server.shutdown()


def test_the_boards_packet_shape_of_2026_09_08() -> None:
    """★ The exact lines the Raspberry Pi now sends, both halves of the pair.

    ``id`` is the TRACK (two objects share one ``seq`` and differ by it), the
    instant is split across ``date`` and ``time``, the ground pixel is the box's
    own bottom-centre, and an explicit null position is a real answer.
    """
    placed = lds.parse_feed_line(
        '{"seq":1234,"id":7,"date":"2026-09-08","time":"06:20:31","lat":33.893791,'
        '"lon":35.501871,"bbox":[412,300,486,540],"cls":"person","rgb":[231,76,60]}',
        0,
        0.0,
    )
    assert placed is not None
    assert (placed["lat"], placed["lon"]) == (33.893791, 35.501871)
    assert placed["cls_name"] == "person" and placed["track_id"] == 7
    assert placed["frame_index"] == 1234
    assert placed["detected_at"] == "2026-09-08T06:20:31Z"
    # the box's ground anchor: mid-x of the bottom edge
    assert (placed["u"], placed["v"]) == (449.0, 540.0)

    unplaced = lds.parse_feed_line(
        '{"seq":1234,"id":9,"date":"2026-09-08","time":"06:20:31","lat":null,"lon":null,'
        '"bbox":[900,250,1120,430],"cls":"car","rgb":[46,204,113]}',
        1,
        0.0,
    )
    assert unplaced is not None, "an explicitly unplaced detection is still a detection"
    assert unplaced["lat"] is None and unplaced["lon"] is None
    assert unplaced["cls_name"] == "car" and unplaced["track_id"] == 9
    assert (unplaced["u"], unplaced["v"]) == (1010.0, 430.0)
    assert unplaced["detected_at"] == "2026-09-08T06:20:31Z"
    # both halves carry an identity, so a re-sent table cannot multiply them
    assert placed["_identified"] and unplaced["_identified"]


def test_a_line_with_no_position_field_at_all_is_still_refused() -> None:
    """Absent is not the same as explicitly none: that line says nothing about where."""
    assert lds.parse_feed_line('{"seq":1,"id":3,"cls":"van"}', 0, 0.0) is None
    assert lds.parse_feed_line('{"lat":34.1}', 0, 0.0) is None
    # …and a half-null pair is not an answer either
    assert lds.parse_feed_line('{"lat":34.1,"lon":null}', 0, 0.0) is None


def test_an_unplaced_row_reaches_the_cursor_and_is_counted_once() -> None:
    """The row lands in the table; a re-sent copy of it does not land twice."""
    feed = lds.DataFeed(feed_id="shape-test", source="http://pi/detections")
    line = (
        '{"seq":7,"id":9,"date":"2026-09-08","time":"06:20:31","lat":null,"lon":null,'
        '"bbox":[900,250,1120,430],"cls":"car"}'
    )
    for _ in range(3):
        lds._ingest(feed, line, 0.0)
    assert len(feed.marks) == 1 and feed.lines_repeat == 2
    assert feed.marks[0]["lat"] is None and feed.marks[0]["cls_name"] == "car"


# ── websocket and TCP senders (2026-09-11, owner ask) ───────────────────────


def test_a_tcp_sender_streams_end_to_end() -> None:
    """★ A board that PUSHES over a raw socket → marks on the cursor.

    Newline-delimited, exactly like the serial and http transports, and split
    across packets on purpose: a line that arrives in two `recv`s is one line.
    """
    import socket
    import threading as th

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve() -> None:
        conn, _addr = server.accept()
        with conn:
            conn.sendall(b'{"lat": 34.1, "lon": 36.0, "cls_name": "car"}\n')
            conn.sendall(b"garbage\n34.2,36.1,pers")  # a line split across packets
            time.sleep(0.2)
            conn.sendall(b"on,0.9,4\n")
            time.sleep(0.5)

    th.Thread(target=serve, daemon=True).start()
    feed = start_feed(f"tcp://127.0.0.1:{port}")
    try:
        deadline = time.time() + 5
        while time.time() < deadline and feed.lines_ok < 2:
            time.sleep(0.05)
        assert feed.lines_ok == 2, feed.error
        assert feed.lines_bad == 1
        assert [m["cls_name"] for m in feed.marks] == ["car", "person"]
    finally:
        stop_feed(feed.feed_id)
        server.close()


def test_a_websocket_sender_streams_end_to_end() -> None:
    """★ One MESSAGE may carry several lines — a board batching its detections."""
    import threading as th

    serve_module = pytest.importorskip("websockets.sync.server")

    def handler(ws: object) -> None:
        ws.send('{"lat": 34.1, "lon": 36.0, "cls_name": "car"}')
        # one frame, three lines: two detections and a comment
        ws.send(
            '{"lat": 34.2, "lon": 36.1, "cls_name": "person"}\n'
            "# a log line the board is allowed to send\n"
            '{"lat": 34.3, "lon": 36.2, "cls_name": "truck"}'
        )
        time.sleep(1.0)

    server = serve_module.serve(handler, "127.0.0.1", 0)
    port = server.socket.getsockname()[1]
    th.Thread(target=server.serve_forever, daemon=True).start()
    feed = start_feed(f"ws://127.0.0.1:{port}")
    try:
        deadline = time.time() + 5
        while time.time() < deadline and feed.lines_ok < 3:
            time.sleep(0.05)
        assert feed.lines_ok == 3, feed.error
        assert [m["cls_name"] for m in feed.marks] == ["car", "person", "truck"]
    finally:
        stop_feed(feed.feed_id)
        server.shutdown()


def test_a_tcp_address_with_no_port_is_refused_at_the_call() -> None:
    """★ Refused where the operator can see it, not inside the reader thread."""
    with pytest.raises(live_data_service.DataFeedError):
        start_feed("tcp://192.168.1.20")
    with pytest.raises(live_data_service.DataFeedError):
        start_feed("tcp://:9000")
