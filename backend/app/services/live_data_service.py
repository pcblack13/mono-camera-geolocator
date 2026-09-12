"""External detection-data feeds — serial/UART devices and embedded systems.

★ WHY IT EXISTS (2026-09-02, owner ask). Not every integration is a picture. A
sensor on a serial port, or a Pi running its own detector, delivers DATA — the
detections themselves, with coordinates — and the app's job is to put those
points on the map exactly as it does its own detections. This service reads such
a feed, parses each line into the SAME mark shape ``detection_service`` produces,
and hands the frontend a marks cursor it already knows how to poll.

★ WHAT A LINE LOOKS LIKE. Either a JSON object per line::

    {"lat": 34.1047, "lon": 36.0163, "cls_name": "car", "score": 0.82, "track_id": 3}

or bare CSV: ``lat,lon[,cls_name[,score[,track_id]]]``. Anything unparseable is
COUNTED (``lines_bad``) and skipped — a glitchy UART must never kill the feed,
and a silently-swallowed line is a debugging session nobody gets back.

★ THE SENDER'S OWN CLOCK WINS (2026-09-07, before the Raspberry Pi test). A JSON
line may carry ``t`` / ``time`` / ``ts`` / ``time_utc`` / ``detected_at`` /
``timestamp`` — ISO-8601, or epoch seconds or milliseconds — and that becomes the
mark's ``detected_at``. A sender that splits the two, ``{"date": "2026-09-08",
"time": "06:20:31"}``, is understood as the one instant it means. Without it the receiver stamps ARRIVAL, which over a LAN
(and behind any buffering) is not when the detection happened; an attribute table
that misreports time is worse than one that admits it has none. A line may also
carry ``u`` / ``v`` when the sender knows the pixel it measured, and ``id`` when
it numbers its own detections.

★ A DETECTION WITHOUT A POSITION IS STILL A DETECTION (2026-09-08). A sender
that detects on its own places only what its lookup table can place, and sends
``"lat": null`` for the rest. Dropping those lost half of what a board saw and
left the operator with an empty table and no reason for it. Such a line is now a
row with an empty position — never a fabricated zero, never on the map. A line
with no position FIELD AT ALL is still unparseable: absent is not the same as
explicitly none.

★ A RE-SENT LINE IS NOT A NEW DETECTION (2026-09-07). Some devices stream for
ever; others answer each request with the WHOLE table so far, and the reader
reconnects (see ``_run``). Re-reading such an endpoint would otherwise multiply
every row on the map. A line that carries its own identity — an ``id``, or its
own timestamp — is therefore ingested once: the same raw line arriving again is
a repeat, counted (``lines_repeat``) and never re-placed. A line with NEITHER
cannot be told apart from a genuine second detection of the same thing, so it is
always taken at face value.

★ SERIAL ON EVERY PLATFORM (2026-09-02). The port is opened with ``pyserial``
when it is installed (the runtime now ships it — Windows COM ports and Linux
``/dev/tty…`` alike); without it, the POSIX-only stdlib ``termios`` path opens
the device raw at the requested baud, and on a platform with neither the feed
is REFUSED with the pip line named — never a silent "starting" forever.
``serial:///dev/ttyUSB0?baud=115200``, ``serial://COM3?baud=9600`` or a bare
``/dev/tty…`` path all work. http(s) feeds stream line-by-line via urllib.

★ FOUR TRANSPORTS, ONE PARSER (2026-09-11, owner ask: "for the data feed let
him choose how is it websocket or tcp"). A sender that pushes rather than
serves is the normal case for a board on a mast, so ``ws://`` / ``wss://`` and
``tcp://host:port`` join http(s) and serial. Every transport does one job —
turn the wire into LINES — and hands each line to ``_ingest``; the parsing,
the de-duplication, the marks and the ``detection_events`` rows are the same
whichever way the line arrived. A websocket MESSAGE may carry several lines
(a board batching its detections) and is split; a TCP stream is newline
delimited, with a cap on how long a "line" may grow before the sender is
declared broken.

★ A FEED'S MARKS ARE EVIDENCE TOO (2026-09-02). Every parsed line is also
written to ``detection_events`` (``kind='feed'``, batched exactly like a
detection run's rows, best-effort) — the table is THE record of what a camera
saw, and a Pi's detections are no less a record than this machine's.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.core.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "MAX_SEEN",
    "DataFeed",
    "DataFeedError",
    "active_feed_for_source",
    "fetch_source_boxes",
    "send_source_command",
    "get_feed",
    "list_feeds",
    "marks_since",
    "parse_feed_line",
    "start_feed",
    "stop_feed",
]

#: Bounded, like a detection session's marks — a chatty feed evicts, never eats RAM.
MAX_MARKS = 20_000

#: How many line identities a feed remembers for duplicate suppression. Bounded
#: for the same reason the marks are: a device that runs for a week must not grow
#: this without limit. The oldest identities are forgotten first.
MAX_SEEN = 50_000

#: Give up on a source only after repeated failures; a serial cable wiggle is not fatal.
_RETRY_DELAY_S = 3.0
_MAX_CONSECUTIVE_FAILURES = 5

#: Row batching to ``detection_events`` — the same shape as a detection run's.
_DB_FLUSH_ROWS = 50
_DB_FLUSH_S = 2.0

#: The drift words a line may carry — this app's own six, as ``detection_service``
#: defines them (restated here so the hot parse path pays for no import, and so
#: the two sets are visibly the same words).
_DRIFT_FROM_WIRE = frozenset({"unwatched", "pending", "ok", "moved", "changed", "degraded"})
_DRIFT_ALERT = frozenset({"moved", "changed"})

#: The bauds the termios fallback can name; pyserial takes any integer.
_SUPPORTED_BAUDS = (9600, 19200, 38400, 57600, 115200, 230400)


class DataFeedError(Exception):
    """A refusal with a reason — never a bare 500."""


@dataclass
class DataFeed:
    """One running feed. Mutated only by its reader thread or under `_LOCK`."""

    feed_id: str
    source: str
    status: str = "starting"  # starting | running | stopped | failed
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Epoch seconds of the last successfully parsed line — the feed's heartbeat.
    last_mark_at: float = 0.0
    lines_ok: int = 0
    lines_bad: int = 0
    #: Marks placed while the sender's own guard read MOVED or CHANGED.
    marks_under_alert: int = 0
    #: Lines recognised as an already-ingested detection re-sent (see the header).
    lines_repeat: int = 0
    marks: list[dict[str, Any]] = field(default_factory=list)
    marks_dropped: int = 0
    #: The registered camera this feed belongs to, when the page said so.
    camera_id: str | None = None
    camera_name: str = ""
    #: ``detection_events`` bookkeeping — same fields as a detection session.
    db_rows_written: int = 0
    db_rows_failed: int = 0
    db_error: str | None = None
    #: Identities of ingested lines, oldest first, with a set beside it for the
    #: membership test — one structure alone would cost either O(n) lookups or
    #: no eviction order.
    _seen: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_SEEN), repr=False)
    _seen_set: set[str] = field(default_factory=set, repr=False)
    _pending_rows: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _last_flush: float = field(default_factory=time.monotonic, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)


_FEEDS: dict[str, DataFeed] = {}
_LOCK = threading.Lock()


def _iso_z(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _wire_time(value: Any) -> datetime | None:
    """A sender's timestamp — ISO-8601, or epoch seconds/milliseconds — or None.

    ★ A naive ISO string is read as UTC: a device that says
    ``2026-09-07T10:00:00`` means the instant, not the receiver's local reading.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = float(value)
        # Milliseconds, when the number is far too large to be seconds since 1970.
        if seconds > 1e11:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        when = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


#: The keys a sender may use for its own detection time, in the order they are tried.
_TIME_KEYS = ("detected_at", "time_utc", "timestamp", "time", "ts", "t")


def _wire_time_of(obj: dict[str, Any]) -> datetime | None:
    """A sender's detection time, however it spells it — including split halves.

    ★ ``{"date": "2026-09-08", "time": "06:20:31"}`` is ONE instant written in two
    fields. Read separately, ``time`` alone is not a date and would be discarded,
    silently costing the row its clock.
    """
    date_part = obj.get("date")
    time_part = obj.get("time")
    if date_part and time_part and "T" not in str(time_part):
        joined = _wire_time(f"{str(date_part).strip()}T{str(time_part).strip()}")
        if joined is not None:
            return joined
    for key in _TIME_KEYS:
        if key in obj:
            when = _wire_time(obj[key])
            if when is not None:
                return when
    return None


def _wire_float(value: Any) -> float | None:
    """A number off the wire, or None — never a fabricated zero."""
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def parse_feed_line(line: str, seq: int, t0: float) -> dict[str, Any] | None:
    """One wire line → one mark in ``detection_service``'s shape, or None.

    Returns None for blank/comment/unparseable lines — the caller counts them.
    Bounds are enforced: a "latitude" of 950 is a corrupt line, not a mark.

    ★ ``_identified`` is an INTERNAL marker, stripped by ``_ingest`` and never
    sent to a client: it is true when the line carried its own timestamp or id,
    which is what makes duplicate suppression safe — see the module header.
    """
    text = line.strip().lstrip("﻿")
    if text == "" or text.startswith("#"):
        return None
    lat: float | None = None
    lon: float | None = None
    cls_name = "object"
    score = 1.0
    track_id: int | None = None
    when_wire: datetime | None = None
    u: float | None = None
    v: float | None = None
    identified = False
    #: The sender said "no position" in so many words — the row keeps its place.
    no_position = False
    #: The sender's own frame number, when it numbers them.
    frame_seq: float | None = None
    #: Nobody here watches a feed's device — unless the SENDER says it does.
    drift_status = "unwatched"
    drift_ref: str | None = None
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        # ★ AN EXPLICIT NULL IS A REAL ANSWER (2026-09-08): the sender placed
        #   nothing for this detection. A MISSING pair is not — that line says
        #   nothing about where, and cannot be told from a line that is not a
        #   detection at all.
        if "lat" in obj and "lon" in obj and obj["lat"] is None and obj["lon"] is None:
            no_position = True
        else:
            try:
                lat = float(obj["lat"])
                lon = float(obj["lon"])
            except (KeyError, TypeError, ValueError):
                return None
        cls_name = str(obj.get("cls_name") or obj.get("cls") or "object")
        try:
            score = float(obj.get("score", obj.get("conf", 1.0)))
        except (TypeError, ValueError):
            score = 1.0
        # ★ ``track_id`` when the sender spells it out; otherwise ``id``, which is
        #   what a board numbering its tracks means by it — two objects in ONE
        #   frame carry different ids, so it is the object, not the row.
        raw_track = obj.get("track_id", obj.get("id"))
        if isinstance(raw_track, int | float) and not isinstance(raw_track, bool):
            track_id = int(raw_track)
        when_wire = _wire_time_of(obj)
        frame_seq = _wire_float(obj.get("seq"))
        # A sender that knows the pixel it measured may say so; nothing is invented.
        u = _wire_float(obj.get("u"))
        v = _wire_float(obj.get("v"))
        box = obj.get("bbox")
        if (u is None or v is None) and isinstance(box, list | tuple) and len(box) >= 4:
            # ★ The box's own ground anchor: the midpoint of its bottom edge, which
            #   is where an object meets the ground — the same point this app reads
            #   its own detections from.
            x1, y1, x2, y2 = (_wire_float(box[i]) for i in range(4))
            if None not in (x1, y1, x2, y2):
                u, v = (x1 + x2) / 2.0, max(y1, y2)  # type: ignore[operator]
        identified = (
            when_wire is not None or obj.get("id") is not None or obj.get("det_id") is not None
        )
        # ★ THE SENDER'S OWN DRIFT VERDICT (2026-09-09, owner decision). A board
        #   that runs its own guard says, on every line, whether it could vouch
        #   for the coordinates it sent. That is the stamp a mark deserves — the
        #   verdict that actually gated the fix — and it is taken only when it is
        #   one of the words this app already uses, so a stranger's vocabulary
        #   can never leak into the record as a status nobody defined.
        raw_drift = obj.get("drift")
        if isinstance(raw_drift, str) and raw_drift.strip().lower() in _DRIFT_FROM_WIRE:
            drift_status = raw_drift.strip().lower()
            raw_ref = obj.get("drift_ref")
            drift_ref = str(raw_ref)[:120] if isinstance(raw_ref, str) and raw_ref else None
    else:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2:
            return None
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            return None
        if len(parts) >= 3 and parts[2] != "":
            cls_name = parts[2]
        if len(parts) >= 4 and parts[3] != "":
            try:
                score = float(parts[3])
            except ValueError:
                score = 1.0
        if len(parts) >= 5 and parts[4] != "":
            try:
                track_id = int(float(parts[4].lstrip("#")))
            except ValueError:
                track_id = None
    if not no_position and (lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180):
        return None
    score = min(1.0, max(0.0, score))
    # ★ The SENDER'S clock when it gave one; arrival only as the last resort.
    now = when_wire or datetime.now(UTC)
    return {
        "lat": lat,
        "lon": lon,
        "score": score,
        "cls_name": cls_name,
        "frame_index": int(frame_seq) if frame_seq is not None else seq,
        "time_s": round(time.monotonic() - t0, 2),
        # ★ A feed usually carries no picture: there IS no ground pixel then, and
        #   0.0 would be a fabricated one — the wire model allows null for exactly
        #   this. A sender that DOES know its pixel may say so.
        "u": u,
        "v": v,
        "track_id": track_id,
        "predicted": False,
        "detected_at": now.isoformat().replace("+00:00", "Z"),
        "detected_at_local": now.astimezone().isoformat(),
        # A feed's device is not this app's camera, so nobody HERE watches it —
        # but a sender that watches itself says so, and its word is kept.
        "drift_status": drift_status,
        "drift_ref_id": drift_ref,
        "centre_offset_m": None,
        "_identified": identified,
    }


# ── the readers ─────────────────────────────────────────────────────────────────


def _serial_path_and_baud(source: str) -> tuple[str, int]:
    """``(port, baud)`` out of ``serial://<port>?baud=<n>`` or a bare path.

    ``serial:///dev/ttyUSB0`` keeps its leading slash; ``serial://COM3`` (Windows)
    has no path component, so the netloc IS the port. A malformed or missing
    baud falls back to 115200 — and is REPORTED through ``feed.error`` by the
    reader rather than silently accepted, see ``_read_serial``.
    """
    if source.startswith("serial://"):
        parsed = urlparse(source)
        path = parsed.path if parsed.path and parsed.path != "/" else parsed.netloc
        if parsed.netloc and parsed.path and parsed.path != "/":
            # serial:///dev/ttyUSB0 → netloc '' path '/dev/ttyUSB0' (handled above);
            # serial://dev/ttyUSB0 (a common typo) → netloc 'dev' path '/ttyUSB0'
            path = f"/{parsed.netloc}{parsed.path}"
        raw = parse_qs(parsed.query).get("baud", ["115200"])[0]
        try:
            baud = int(raw)
        except ValueError:
            baud = 115200
        return path, baud
    return source, 115200


_BAUD_CONSTANTS = {
    9600: "B9600",
    19200: "B19200",
    38400: "B38400",
    57600: "B57600",
    115200: "B115200",
    230400: "B230400",
}


def _read_serial(feed: DataFeed) -> None:
    """Serial reader: pyserial when installed, raw termios otherwise."""
    try:
        import serial as pyserial  # noqa: PLC0415 — optional, bound at call time
    except ImportError:
        pyserial = None
    if pyserial is not None:
        path, _ = _serial_path_and_baud(feed.source)
        # ★ pyserial opens REAL ports (COM3, /dev/ttyUSB0). A FIFO or a pty standing
        #   in for a port (the tests, a bench rig piping a log file) is not a tty to
        #   pyserial and is refused at open; on POSIX the raw path below reads it
        #   anyway, so the fall-through keeps the bench rig working.
        try:
            _read_serial_pyserial(feed, pyserial)
            return
        except pyserial.SerialException as exc:
            if os.name != "posix":
                raise
            log.info("data_feed.pyserial_declined", feed=feed.feed_id, path=path, error=str(exc))
    elif os.name != "posix":
        raise DataFeedError(
            "serial feeds on this platform need pyserial — in the app's Python "
            "runtime run: pip install pyserial — and restart the app."
        )
    _read_serial_termios(feed)


def _read_serial_pyserial(feed: DataFeed, pyserial: Any) -> None:
    """The cross-platform reader. 8N1, the requested baud, a short read timeout
    so the stop event is honoured within a fraction of a second."""
    path, baud = _serial_path_and_baud(feed.source)
    t0 = time.monotonic()
    buf = b""
    with pyserial.Serial(path, baudrate=baud, timeout=0.2) as port:
        while not feed._stop.is_set():
            chunk = port.read(4096)
            if not chunk:
                _maybe_flush(feed)
                continue
            feed.status = "running"
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                _ingest(feed, raw.decode("utf-8", "replace"), t0)


def _read_serial_termios(feed: DataFeed) -> None:
    """Raw termios serial reader — stdlib only, POSIX only."""
    import termios  # noqa: PLC0415 — POSIX-only, imported where it is used

    path, baud = _serial_path_and_baud(feed.source)
    if baud not in _SUPPORTED_BAUDS:
        # ★ Reported, not swallowed: the old code silently opened at 115200.
        feed.error = f"baud {baud} is not available without pyserial; using 115200"
        baud = 115200
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        try:
            attrs = termios.tcgetattr(fd)
            speed = getattr(termios, _BAUD_CONSTANTS[baud])
            # cfmakeraw-equivalent: no echo, no canonical mode, 8N1.
            attrs[0] = 0  # iflag
            attrs[1] = 0  # oflag
            attrs[2] = termios.CREAD | termios.CLOCAL | termios.CS8  # cflag
            attrs[3] = 0  # lflag
            attrs[4] = speed  # ispeed
            attrs[5] = speed  # ospeed
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except termios.error:
            # A pipe or pty used in tests is not a tty; read it anyway.
            pass
        buf = b""
        t0 = time.monotonic()
        while not feed._stop.is_set():
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                _maybe_flush(feed)
                time.sleep(0.05)
                continue
            if chunk == b"":
                _maybe_flush(feed)
                time.sleep(0.1)
                continue
            feed.status = "running"
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                _ingest(feed, raw.decode("utf-8", "replace"), t0)
    finally:
        os.close(fd)


#: Every transport this feed can open. ``/dev/tty`` is a bare serial path.
_FEED_SCHEMES = ("serial://", "/dev/tty", "http://", "https://", "ws://", "wss://", "tcp://")

#: A TCP sender that never sends a newline must not eat memory: past this many
#: bytes without one, the connection is declared broken rather than buffered.
_TCP_MAX_LINE_BYTES = 1 << 20
#: How long a blocking read waits before the stop flag is checked again.
_POLL_S = 1.0


def _tcp_host_and_port(source: str) -> tuple[str, int]:
    """``(host, port)`` out of ``tcp://host:port``.

    Raises:
        DataFeedError: No host, or a port that is missing or not a number — the
            operator typed an address this can never open, and is told which part.
    """
    parsed = urlparse(source)
    host = parsed.hostname
    if not host:
        raise DataFeedError("the TCP feed needs a host — tcp://192.168.1.20:9000.")
    try:
        port = parsed.port
    except ValueError as exc:  # a port that is not a number at all
        raise DataFeedError(f"the TCP feed's port is not a number: {exc}") from exc
    if port is None:
        raise DataFeedError("the TCP feed needs a port — tcp://192.168.1.20:9000.")
    return host, port


def _read_tcp(feed: DataFeed) -> None:
    """Read newline-delimited lines from a raw TCP sender.

    ★ The socket is polled rather than blocked on, so Stop is honoured within a
    second instead of at the sender's convenience. A clean close ENDS the read
    (``_run`` reconnects); a sender that streams forever never returns from here.
    """
    import socket  # stdlib, call-local like the other readers

    host, port = _tcp_host_and_port(feed.source)
    t0 = time.monotonic()
    buffer = bytearray()
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(_POLL_S)
        feed.status = "running"
        while not feed._stop.is_set():
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                return  # the sender closed: a finished batch, _run reconnects
            buffer.extend(chunk)
            while True:
                cut = buffer.find(b"\n")
                if cut < 0:
                    break
                line = bytes(buffer[:cut])
                del buffer[: cut + 1]
                _ingest(feed, line.decode("utf-8", "replace"), t0)
            if len(buffer) > _TCP_MAX_LINE_BYTES:
                raise DataFeedError(
                    f"the TCP sender sent {len(buffer)} bytes with no newline — "
                    "this feed reads NEWLINE-DELIMITED JSON or CSV lines."
                )


def _read_ws(feed: DataFeed) -> None:
    """Read a websocket sender: one message, one or more lines.

    ★ Messages, not a byte stream: a board that batches its detections into one
    frame is the normal case, so a message is split on newlines and each line
    ingested. Binary frames are decoded as UTF-8 like every other transport.
    """
    try:
        from websockets.sync.client import connect  # heavy, call-local
    except ImportError as exc:  # pragma: no cover — the runtime ships it
        raise DataFeedError(
            "websocket feeds need the 'websockets' package. In the app's Python "
            "runtime run: pip install websockets"
        ) from exc

    t0 = time.monotonic()
    with connect(feed.source, open_timeout=10, close_timeout=5) as ws:
        feed.status = "running"
        while not feed._stop.is_set():
            try:
                message = ws.recv(timeout=_POLL_S)
            except TimeoutError:
                continue
            if isinstance(message, bytes | bytearray):
                message = bytes(message).decode("utf-8", "replace")
            for line in str(message).splitlines():
                _ingest(feed, line, t0)


def _read_http(feed: DataFeed) -> None:
    """Stream an http(s) NDJSON/CSV feed line by line — stdlib urllib."""
    from urllib.request import Request, urlopen

    req = Request(feed.source, headers={"User-Agent": "landexplorer-data-feed"})
    t0 = time.monotonic()
    with urlopen(req, timeout=10) as resp:  # the operator's own URL
        feed.status = "running"
        for raw in resp:
            if feed._stop.is_set():
                return
            _ingest(feed, raw.decode("utf-8", "replace"), t0)


def _ingest(feed: DataFeed, line: str, t0: float) -> None:
    mark = parse_feed_line(line, feed.lines_ok, t0)
    if mark is None:
        if line.strip() != "":
            feed.lines_bad += 1
        return
    # ★ A line that carries its own identity is ingested ONCE — see the header.
    #   The marker is internal: it never leaves this function.
    if mark.pop("_identified", False):
        key = line.strip()
        if key in feed._seen_set:
            feed.lines_repeat += 1
            return
        if feed._seen.maxlen is not None and len(feed._seen) == feed._seen.maxlen:
            feed._seen_set.discard(feed._seen[0])
        feed._seen.append(key)
        feed._seen_set.add(key)
    feed.lines_ok += 1
    feed.last_mark_at = time.time()
    if mark["drift_status"] in _DRIFT_ALERT:
        # Placed, never hidden — the detection happened; what is in doubt is
        # where. The count is the page's warning, exactly as for a run.
        feed.marks_under_alert += 1
    feed.marks.append(mark)
    if len(feed.marks) > MAX_MARKS:
        overflow = len(feed.marks) - MAX_MARKS
        del feed.marks[:overflow]
        feed.marks_dropped += overflow
    # ★ EVERY parsed line becomes a durable row — see the module header.
    feed._pending_rows.append(
        {
            "kind": "feed",
            "session_id": feed.feed_id,
            "source": feed.source,
            "camera_id": feed.camera_id,
            "camera_name": feed.camera_name,
            "lut_site": None,
            "track_id": mark["track_id"],
            "cls_name": mark["cls_name"],
            "score": float(mark["score"]),
            "predicted": False,
            "frame_index": int(mark["frame_index"]),
            "time_s": float(mark["time_s"]),
            "u": None,
            "v": None,
            "lat": mark["lat"],
            "lon": mark["lon"],
            "detected_at": datetime.now(UTC),
            "detected_at_local": mark["detected_at_local"],
            "drift_status": mark["drift_status"],
            "drift_ref_id": mark["drift_ref_id"],
            "centre_offset_m": None,
        }
    )
    _maybe_flush(feed)


def _maybe_flush(feed: DataFeed, force: bool = False) -> None:
    """Batched, best-effort persistence — a dead database costs the record, not
    the feed; the failure is counted and shown in ``db_error``."""
    rows = feed._pending_rows
    if not rows:
        return
    if not force and len(rows) < _DB_FLUSH_ROWS and time.monotonic() - feed._last_flush < _DB_FLUSH_S:
        return
    batch, rows[:] = list(rows), []
    feed._last_flush = time.monotonic()
    try:
        from app.services.detection_service import write_detection_rows  # noqa: PLC0415

        feed.db_rows_written += write_detection_rows(batch)
        feed.db_error = None
    except Exception as exc:  # noqa: BLE001 — a DB failure is a report, not a death
        feed.db_rows_failed += len(batch)
        feed.db_error = f"{type(exc).__name__}: {exc}"


def _run(feed: DataFeed) -> None:
    """The reader loop: reconnects on failure, gives up only after a streak."""
    failures = 0
    while not feed._stop.is_set():
        try:
            if feed.source.startswith(("http://", "https://")):
                _read_http(feed)
            elif feed.source.startswith(("ws://", "wss://")):
                _read_ws(feed)
            elif feed.source.startswith("tcp://"):
                _read_tcp(feed)
            else:
                _read_serial(feed)
            failures = 0
            if feed._stop.is_set():
                break
            # An http stream that ENDED cleanly is a finished batch: reconnect.
            time.sleep(_RETRY_DELAY_S)
        except DataFeedError as exc:
            # a platform that cannot open this source at all — say so and stop
            feed.error = str(exc)
            feed.status = "failed"
            _maybe_flush(feed, force=True)
            return
        except Exception as exc:  # the feed reports, never dies silently
            failures += 1
            message = f"{type(exc).__name__}: {exc}"
            # ★ Said ONCE per distinct failure, not once per retry (2026-09-10): a
            #   sender off the cable answered 409 every 3 s, and the operator's
            #   terminal filled with the same line for as long as it stayed off.
            #   The feed's status still carries the error; the log names a change.
            if message != feed.error:
                log.warning("data_feed.read_failed", feed=feed.feed_id, error=message)
            feed.error = message
            if failures >= _MAX_CONSECUTIVE_FAILURES:
                feed.status = "failed"
                _maybe_flush(feed, force=True)
                return
            feed.status = "starting"  # honest: reconnecting, no data flowing
            if feed._stop.wait(_RETRY_DELAY_S):
                break
    _maybe_flush(feed, force=True)
    feed.status = "stopped"


# ── the API the router calls ────────────────────────────────────────────────────


def start_feed(
    source: str, *, camera_id: str | None = None, camera_name: str | None = None
) -> DataFeed:
    """Start (or return the already-running) feed for ``source`` — one per source."""
    spec = source.strip()
    if spec == "":
        raise DataFeedError("a data source is required.")
    if not spec.startswith(_FEED_SCHEMES):
        raise DataFeedError(
            "the data source must be serial://<port>?baud=… (serial:///dev/ttyUSB0, "
            "serial://COM3), a /dev/tty… path, an http(s) URL, a ws(s):// websocket, "
            "or tcp://host:port."
        )
    if spec.startswith("tcp://"):
        _tcp_host_and_port(spec)  # a bad address is refused HERE, not in the thread
    with _LOCK:
        for feed in _FEEDS.values():
            if feed.source == spec and feed.status in ("starting", "running"):
                if camera_id and not feed.camera_id:
                    feed.camera_id, feed.camera_name = camera_id, camera_name or ""
                return feed
        feed = DataFeed(
            feed_id=uuid.uuid4().hex[:12],
            source=spec,
            camera_id=camera_id,
            camera_name=camera_name or "",
        )
        _FEEDS[feed.feed_id] = feed
    thread = threading.Thread(
        target=_run, args=(feed,), name=f"data-feed-{feed.feed_id}", daemon=True
    )
    thread.start()
    log.info("data_feed.started", feed=feed.feed_id, source=spec)
    return feed


def active_feed_for_source(source: str) -> DataFeed | None:
    """The starting/running feed on ``source``, or None — the desired-state
    reconciliation asks this before starting one."""
    spec = source.strip()
    with _LOCK:
        for feed in _FEEDS.values():
            if feed.source == spec and feed.status in ("starting", "running"):
                return feed
    return None


def get_feed(feed_id: str) -> DataFeed | None:
    """The feed, or None — the router turns None into a 404."""
    with _LOCK:
        return _FEEDS.get(feed_id)


def list_feeds() -> list[DataFeed]:
    """Every feed this process knows, newest first."""
    with _LOCK:
        return sorted(_FEEDS.values(), key=lambda f: f.started_at, reverse=True)


def marks_since(feed_id: str, since: int) -> tuple[int, list[dict[str, Any]]]:
    """The marks cursor, shaped exactly like a detection session's."""
    feed = get_feed(feed_id)
    if feed is None:
        raise DataFeedError("no such data feed.")
    total = feed.marks_dropped + len(feed.marks)
    start = max(0, since - feed.marks_dropped)
    return total, feed.marks[start:]


def stop_feed(feed_id: str) -> None:
    """Signal the reader thread to stop; refuses an unknown id."""
    feed = get_feed(feed_id)
    if feed is None:
        raise DataFeedError("no such data feed.")
    feed._stop.set()
    feed.status = "stopped"
    log.info("data_feed.stopped", feed=feed.feed_id)


# ── the sender's own boxes, for the overlay ─────────────────────────────────────


#: A box snapshot is small and must never hold the page up; a sender that has
#: gone quiet should read as "no boxes", not as a spinner.
_BOXES_TIMEOUT_S = 2.0

#: What a runaway sender could otherwise make us buffer for a 2 Hz poll.
_BOXES_MAX_BYTES = 1_000_000


def fetch_source_boxes(url: str) -> dict[str, Any]:
    """GET ``url`` and return the boxes a sender is showing RIGHT NOW.

    ★ A SECOND CHANNEL, ON PURPOSE (2026-09-08). A feed's NDJSON is the record:
    every line becomes a mark and a ``detection_events`` row, so it is paced for
    evidence, not for drawing. An overlay wants the opposite — the current frame,
    a few times a second, kept nowhere. Serving both from one stream would force
    one rate to do two jobs: fast enough to draw is fast enough to turn the mark
    table over in minutes.

    ★ NOTHING IS STORED AND NOTHING IS INVENTED. The answer is passed through as
    the sender gave it; a sender that reports no frame size gets zero, and the
    overlay declines to draw rather than guessing where a box belongs.

    Raises:
        DataFeedError: Bad scheme, unreachable sender, oversized or non-JSON
            answer. The message names which — the page shows it beside the chip.
    """
    from urllib.error import URLError  # noqa: PLC0415 — stdlib, call-local like _read_http
    from urllib.request import Request, urlopen  # noqa: PLC0415

    from app.services.live_stream_service import (  # noqa: PLC0415
        LiveCaptureError,
        validate_stream_url,
    )

    # ★ The same allow-list the video lane uses. This endpoint fetches a URL on
    #   the operator's behalf, so it gets the same refusal-by-type posture — a
    #   file:// or gopher:// "sender" is refused by scheme, not by luck.
    try:
        checked = validate_stream_url(url)
    except LiveCaptureError as exc:
        raise DataFeedError(str(exc)) from exc

    req = Request(checked, headers={"User-Agent": "landexplorer-source-boxes"})
    try:
        with urlopen(req, timeout=_BOXES_TIMEOUT_S) as resp:  # the operator's own URL
            raw = resp.read(_BOXES_MAX_BYTES + 1)
    except (URLError, OSError, ValueError) as exc:
        raise DataFeedError(
            f"could not read boxes from the sender: {type(exc).__name__}: {exc}"
        ) from exc
    if len(raw) > _BOXES_MAX_BYTES:
        raise DataFeedError("the sender's answer is implausibly large for a box list.")

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise DataFeedError(f"the sender did not answer with JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataFeedError("the sender's answer is not a JSON object.")
    return payload


def send_source_command(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST one operator command to a sender's bridge and return its answer.

    ★ THE APP DOES NOT DECIDE WHAT A CLICK MEANS. It carries the click to the
    thing holding the tracker and reports what came back. A sender that refuses
    -- because nobody is watching it, because the click hit nothing -- has said
    something true, and passing that through unedited is the whole value of
    asking rather than assuming.

    ★ SHORT AND UNRETRIED. A command is a thing the operator meant a moment
    ago; a retry three seconds later is a click they never made.

    Raises:
        DataFeedError: Bad scheme, unreachable sender, or a non-JSON answer.
    """
    from urllib.error import HTTPError, URLError  # noqa: PLC0415
    from urllib.request import Request, urlopen  # noqa: PLC0415

    from app.services.live_stream_service import (  # noqa: PLC0415
        LiveCaptureError,
        validate_stream_url,
    )

    try:
        checked = validate_stream_url(url)
    except LiveCaptureError as exc:
        raise DataFeedError(str(exc)) from exc

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        checked,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "landexplorer-source-command",
        },
    )
    try:
        with urlopen(req, timeout=_BOXES_TIMEOUT_S) as resp:  # the operator's own URL
            raw = resp.read(_BOXES_MAX_BYTES + 1)
    except HTTPError as exc:
        # ★ A REFUSAL IS AN ANSWER. The bridge replies 502 with the sender's own
        #   words when the sender said no; throwing that body away would leave
        #   the operator with "it did not work" and no reason.
        raw = exc.read(_BOXES_MAX_BYTES + 1) if exc.fp is not None else b""
        if not raw:
            raise DataFeedError(f"the sender refused: HTTP {exc.code}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise DataFeedError(
            f"could not reach the sender: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        answer = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise DataFeedError(f"the sender did not answer with JSON: {exc}") from exc
    if not isinstance(answer, dict):
        raise DataFeedError("the sender's answer is not a JSON object.")
    return answer
