"""``geo1_service`` — cameras that announce themselves on a cable, and the app's
own reader for the pictures and detections they send.

★ WHY THIS IS INSIDE THE APP (2026-09-09). It began as a separate bridge process
on the operator's machine: it read the sender's stream and re-served it as an
ordinary MJPEG camera. That worked, and it cost two debugging sessions in one
day — a stale bridge answered 404 for an endpoint it predated, and a restarted
app talked to a bridge nobody had restarted. Every one of those failures was the
same failure: a second process with its own lifetime that nothing owned. So the
reader lives here now. There is no port to remember, nothing to start first, and
"is the bridge running?" is not a question anyone can be asked again.

★ WHAT A SENDER IS. A board with a camera that does its own detection and
announces itself once a second on UDP 5001:

    {"service": "geo1-pi-camera", "host": "10.10.10.1", "port": 5000,
     "control_port": 5002, "name": "cog-rpi5", "w": 1280, "h": 720,
     "lat": 33.893791, "lon": 35.501871, "manual": true,
     "classes": ["person", "car", ...], "lut_placeholder": true}

Hearing that is the whole of discovery. The app never scans, never probes a
range, and never guesses an address: a camera either says it is there or it is
not there as far as this app is concerned.

★ HEARING IS NOT REACHING. A sender broadcasts to its own subnet AND to
255.255.255.255, so a machine with no address on its network still hears it.
That case is reported as a sender that is `reachable: false` with the subnet it
wants, because "there is a camera on this cable and you are not on its network"
is a far more useful thing to tell an operator than an empty list.

★ ONE READER PER SENDER, MANY VIEWERS. A connected sender is read by exactly one
thread here, which keeps only the newest frame; every viewer, every box poll and
every detection run is served from that. A viewer that falls behind skips to the
present rather than replaying a backlog, which is what keeps a slow client
harmless to a fast one.

Framework-free: no FastAPI, no SQLAlchemy. The router owns HTTP concerns.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.vendor.geo1 import ProtocolError, read_message

log = get_logger(__name__)

__all__ = [
    "BEACON_PORT",
    "Geo1Error",
    "Sender",
    "boxes",
    "command",
    "connect",
    "disconnect",
    "get_link",
    "list_senders",
    "mjpeg_frames",
    "ndjson_lines",
    "drift_stamp",
    "snapshot",
    "start_discovery",
    "status",
]

#: Where senders announce themselves. Chosen by the sender, mirrored here.
BEACON_PORT = 5001
BEACON_SERVICE = "geo1-pi-camera"

#: A sender unheard for this long is gone from the list. Three missed beacons:
#: long enough to ride out a dropped datagram, short enough that unplugging a
#: cable removes the camera while the operator is still looking at the screen.
SENDER_TTL_S = 3.5

#: Socket timeouts for the frame connection. Generous enough for a busy sender,
#: short enough that a dead one is noticed rather than waited on.
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 10.0
RECONNECT_WAIT_S = 1.0

#: A command is a thing the operator meant a moment ago. It is answered quickly
#: or it has failed; nothing about it is worth retrying later.
COMMAND_TIMEOUT_S = 3.0

BOUNDARY = "frame"

#: How often one track may become a MARK, per second. Ethernet carries thirty
#: headers a second; six tracked objects would be 180 marks a second, and the
#: app's mark table would turn over in two minutes of standing still. A ground
#: fix does not change thirty times a second in any useful way.
DEFAULT_FIX_RATE_HZ = 1.0

#: The sender's guard speaks the same four words as this app's own drift monitor
#: — it is built on the same DriftMonitor class — so the mapping is one-to-one.
#: Anything else it might say is "pending": the guard exists but has no verdict.
_DRIFT_WORDS = frozenset({"ok", "moved", "changed", "degraded"})


class Geo1Error(Exception):
    """A refusal with a reason — never a bare 500."""


# ─────────────────────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Sender:
    """One camera that has announced itself, as it described itself."""

    #: host:port — stable for as long as the camera keeps its address, which is
    #: what makes it usable as a handle in a URL.
    id: str
    host: str
    port: int
    control_port: int
    name: str
    #: Epoch seconds of the last beacon.
    last_seen: float
    #: Where the SENDER says it is on the ground, from its own lookup table.
    lat: float | None = None
    lon: float | None = None
    width: int | None = None
    height: int | None = None
    #: The classes it is detecting, or None when it keeps everything.
    classes: list[str] | None = None
    #: True when it waits for an operator click before following anything.
    manual: bool | None = None
    lut: str | None = None
    #: The sender is running on a placeholder table: its coordinates are
    #: believable and wrong. Passed on so nobody trusts a mark that has not
    #: earned it.
    lut_placeholder: bool = False
    #: False when this machine has no address on the sender's subnet — we heard
    #: its limited broadcast but cannot open a socket to it.
    reachable: bool = True
    #: Set when `reachable` is false: the address this machine would need.
    needs_subnet: str | None = None


_SEEN: dict[str, Sender] = {}
_SEEN_LOCK = threading.Lock()
_DISCOVERY: threading.Thread | None = None
_DISCOVERY_LOCK = threading.Lock()


def _local_addresses() -> set[str]:
    """Every IPv4 address this machine holds, for the reachability test."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    # getaddrinfo misses addresses with no reverse name, which a hand-configured
    # point-to-point link usually has none of. Ask the routing table too, by
    # seeing which local address the kernel would use to reach a given host.
    return found


def _reachable_from_here(host: str) -> bool:
    """Would a socket to `host` have a source address? No route, no reach.

    ★ A UDP CONNECT SENDS NOTHING. It only asks the kernel to pick a route and a
    source address, which is exactly the question being asked — and it answers
    without a packet, a timeout or a permission.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))          # discard port; nothing is sent
        local = probe.getsockname()[0]
    except OSError:
        return False
    finally:
        probe.close()
    if local in ("0.0.0.0", ""):
        return False
    # A route via a DIFFERENT subnet is not reachability for a point-to-point
    # cable: the packet would leave through the default gateway and never
    # arrive. Same /24 is the honest test for the link this product uses.
    return local.rsplit(".", 1)[0] == host.rsplit(".", 1)[0]


def _remember(body: dict[str, Any]) -> None:
    host = str(body.get("host") or "").strip()
    if not host:
        return
    try:
        port = int(body.get("port", 5000))
    except (TypeError, ValueError):
        return
    classes = body.get("classes")
    if classes is not None and not isinstance(classes, list):
        classes = None
    reachable = _reachable_from_here(host)
    sender = Sender(
        id=f"{host}:{port}",
        host=host,
        port=port,
        control_port=int(body.get("control_port") or 5002),
        name=str(body.get("name") or host),
        last_seen=time.time(),
        lat=_as_float(body.get("lat")),
        lon=_as_float(body.get("lon")),
        width=_as_int(body.get("w")),
        height=_as_int(body.get("h")),
        classes=[str(c) for c in classes] if classes else None,
        manual=bool(body["manual"]) if isinstance(body.get("manual"), bool) else None,
        lut=str(body["lut"]) if body.get("lut") else None,
        lut_placeholder=bool(body.get("lut_placeholder")),
        reachable=reachable,
        needs_subnet=None if reachable else f"{host.rsplit('.', 1)[0]}.0/24",
    )
    with _SEEN_LOCK:
        _SEEN[sender.id] = sender


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _discovery_loop() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", BEACON_PORT))
    except OSError as exc:
        # Another listener owns the port — most likely an old bridge. Say so
        # once and stop, rather than a silent camera list nobody can explain.
        log.warning("geo1.discovery.bind_failed", port=BEACON_PORT, error=str(exc))
        sock.close()
        return
    sock.settimeout(1.0)
    log.info("geo1.discovery.listening", port=BEACON_PORT)
    heard: set[str] = set()
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            if addr[0] not in heard:
                # Said once per source: an operator staring at an empty list
                # deserves to know whether anything is arriving at all.
                heard.add(addr[0])
                log.info("geo1.discovery.first_beacon", source=addr[0])
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            body = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue                     # not ours; the wire is shared
        if not isinstance(body, dict) or body.get("service") != BEACON_SERVICE:
            continue
        try:
            _remember(body)
        except Exception as exc:  # noqa: BLE001 — see below
            # ★ ONE BAD BEACON MUST NOT END DISCOVERY. This thread is the only
            #   thing listening, and an exception here would kill it silently:
            #   the camera list would go empty and stay empty, with the port
            #   still held so nothing else could take over either. A sender
            #   sending nonsense is a sender to ignore, not a reason to stop
            #   hearing every other camera on the wire.
            log.warning("geo1.discovery.bad_beacon", error=str(exc))
    sock.close()


def start_discovery() -> None:
    """Begin listening for beacons. Idempotent; safe to call on every request."""
    global _DISCOVERY
    with _DISCOVERY_LOCK:
        if _DISCOVERY is not None and _DISCOVERY.is_alive():
            return
        _DISCOVERY = threading.Thread(
            target=_discovery_loop, name="geo1-discovery", daemon=True
        )
        _DISCOVERY.start()


def list_senders() -> list[Sender]:
    """Every sender heard recently, newest beacon first.

    Starts the listener if it is not running, so a page that asks does not have
    to know whether anyone asked before it.
    """
    start_discovery()
    cutoff = time.time() - SENDER_TTL_S
    with _SEEN_LOCK:
        alive = [s for s in _SEEN.values() if s.last_seen >= cutoff]
        for stale in [k for k, v in _SEEN.items() if v.last_seen < cutoff]:
            _SEEN.pop(stale, None)
    return sorted(alive, key=lambda s: s.last_seen, reverse=True)


def get_sender(sender_id: str) -> Sender | None:
    for sender in list_senders():
        if sender.id == sender_id:
            return sender
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The reader
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Link:
    """One connected sender: a reader thread and the newest frame it produced."""

    sender_id: str
    host: str
    port: int
    control_port: int
    cond: threading.Condition = field(default_factory=threading.Condition)
    jpeg: bytes | None = None
    header: dict[str, Any] | None = None
    #: Bumped once per frame; a viewer diffs it to know something is new.
    count: int = 0
    frames_total: int = 0
    connected: bool = False
    error: str | None = None
    arrivals: deque = field(default_factory=lambda: deque(maxlen=90))
    started: float = field(default_factory=time.monotonic)
    viewers: int = 0
    stop: threading.Event = field(default_factory=threading.Event)

    # -- producer

    def publish(self, header: dict[str, Any], jpeg: bytes) -> None:
        with self.cond:
            self.header, self.jpeg = header, jpeg
            self.count += 1
            self.frames_total += 1
            self.arrivals.append(time.monotonic())
            self.cond.notify_all()

    def set_state(self, connected: bool, error: str | None = None) -> None:
        with self.cond:
            self.connected = connected
            self.error = error
            if not connected:
                # Otherwise the rate window straddles the outage and the fps
                # after a reconnect reads as a fraction of the real rate.
                self.arrivals.clear()
            self.cond.notify_all()

    # -- consumer

    def fps(self) -> float:
        with self.cond:
            if len(self.arrivals) < 2:
                return 0.0
            span = self.arrivals[-1] - self.arrivals[0]
            return round((len(self.arrivals) - 1) / span, 1) if span > 0 else 0.0

    def snapshot(self) -> tuple[dict[str, Any] | None, bytes | None]:
        with self.cond:
            return self.header, self.jpeg

    def wait_frame(self, last: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self.cond:
            while self.count == last and not self.stop.is_set():
                if not self.cond.wait(timeout=timeout):
                    return last, None      # nothing new; the caller decides
            return self.count, self.jpeg

    # -- the thread

    def run(self) -> None:
        while not self.stop.is_set():
            sock = None
            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=CONNECT_TIMEOUT_S
                )
                sock.settimeout(READ_TIMEOUT_S)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.set_state(True)
                log.info("geo1.link.connected", sender=self.sender_id)
                while not self.stop.is_set():
                    message = read_message(sock)
                    if message is None:
                        raise ConnectionError("the sender closed the connection")
                    self.publish(*message)
            except ProtocolError as exc:
                # A corrupt frame means the stream is no longer trustworthy: drop
                # it rather than show a plausible picture with the wrong boxes.
                log.warning("geo1.link.corrupt", sender=self.sender_id, error=str(exc))
                self.set_state(False, str(exc))
            except (OSError, ConnectionError) as exc:
                self.set_state(False, f"{type(exc).__name__}: {exc}")
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if not self.stop.is_set():
                self.stop.wait(RECONNECT_WAIT_S)


_LINKS: dict[str, Link] = {}
_LINKS_LOCK = threading.Lock()


def get_link(sender_id: str) -> Link | None:
    with _LINKS_LOCK:
        return _LINKS.get(sender_id)


def connect(sender_id: str) -> Link:
    """Start reading a sender. Idempotent — a second connect returns the first.

    Raises:
        Geo1Error: The sender has not announced itself, or this machine has no
            address on its network. Both name what the operator must fix.
    """
    with _LINKS_LOCK:
        existing = _LINKS.get(sender_id)
        if existing is not None and not existing.stop.is_set():
            return existing

    sender = get_sender(sender_id)
    if sender is None:
        raise Geo1Error(
            f"no camera is announcing itself as {sender_id} — check the cable, "
            "and that the sender is running."
        )
    if not sender.reachable:
        raise Geo1Error(
            f"{sender.name} is on {sender.needs_subnet} and this machine has no "
            "address on that network, so it can be heard but not reached."
        )

    link = Link(
        sender_id=sender.id,
        host=sender.host,
        port=sender.port,
        control_port=sender.control_port,
    )
    with _LINKS_LOCK:
        _LINKS[sender_id] = link
    threading.Thread(
        target=link.run, name=f"geo1-{sender_id}", daemon=True
    ).start()
    return link


def disconnect(sender_id: str) -> bool:
    """Stop reading a sender. Returns False if it was not connected."""
    with _LINKS_LOCK:
        link = _LINKS.pop(sender_id, None)
    if link is None:
        return False
    link.stop.set()
    with link.cond:
        link.cond.notify_all()
    log.info("geo1.link.disconnected", sender=sender_id)
    return True


def _require(sender_id: str) -> Link:
    link = get_link(sender_id)
    if link is None:
        raise Geo1Error(f"not connected to {sender_id}.")
    return link


def status(sender_id: str) -> dict[str, Any]:
    """Link health, for the page's own readout."""
    link = _require(sender_id)
    header, jpeg = link.snapshot()
    return {
        "sender_id": sender_id,
        "connected": link.connected,
        "fps": link.fps(),
        "frames": link.frames_total,
        "viewers": link.viewers,
        "uptime_s": round(time.monotonic() - link.started, 1),
        "last_error": link.error,
        "seq": (header or {}).get("seq"),
        "width": (header or {}).get("w"),
        "height": (header or {}).get("h"),
        "geo_valid": (header or {}).get("geo_valid"),
        "objects": len((header or {}).get("objects", [])),
        "jpeg_bytes": len(jpeg) if jpeg else None,
        "uart": (header or {}).get("uart"),
        "drift": (header or {}).get("drift"),
    }


def snapshot(sender_id: str) -> tuple[dict[str, Any] | None, bytes | None]:
    """The freshest (header, jpeg) — the header verbatim as the sender sent it."""
    return _require(sender_id).snapshot()


def boxes(sender_id: str) -> dict[str, Any]:
    """The freshest frame's boxes, in this app's own detection shape.

    ★ THE SENDER'S VOCABULARY TRANSLATED ONCE, HERE. `cls` becomes `cls_name`
    and `conf` becomes `score` at the boundary, so nothing downstream — not the
    overlay, not a session, not an export — has to know a second dialect.
    """
    link = _require(sender_id)
    header, _ = link.snapshot()
    if header is None:
        return {"seq": 0, "frame_index": 0, "time_s": 0.0, "width": 0, "height": 0,
                "geo_valid": False, "boxes": []}
    geo_ok = bool(header.get("geo_valid"))
    out = []
    for obj in header.get("objects", []):
        box = obj.get("bbox")
        if not (isinstance(box, (list, tuple)) and len(box) >= 4):
            continue
        placed = bool(geo_ok and obj.get("lat") is not None)
        out.append({
            "x1": float(box[0]), "y1": float(box[1]),
            "x2": float(box[2]), "y2": float(box[3]),
            "score": float(obj.get("conf") or 0.0),
            "cls_name": str(obj.get("cls") or "object"),
            "track_id": obj.get("id"),
            # The sender says how it knows: only "tracking" is its tracker
            # carrying a box between detector passes. Everything else is a
            # sighting, and an untracked detection is drawn as one.
            "predicted": obj.get("state") == "tracking",
            "placed": placed,
        })
    return {
        "seq": header.get("seq") or 0,
        "frame_index": header.get("seq") or 0,
        "time_s": round(time.monotonic() - link.started, 2),
        "width": header.get("w") or 0,
        "height": header.get("h") or 0,
        "geo_valid": geo_ok,
        "boxes": out,
    }


def mjpeg_frames(sender_id: str) -> Iterator[bytes]:
    """The connected sender's pictures as multipart parts, for the player.

    ★ NOT A SECOND READER. This is served from the one frame the link already
    holds, so ten viewers cost the sender nothing beyond what one costs. A
    viewer that falls behind skips to the present; it never replays a backlog.

    ★ REFUSED BEFORE THE FIRST BYTE, NOT AFTER THE HEADERS (2026-09-10). This
    used to be one generator, so "not connected" was only discovered on the
    first ``next()`` — inside the streaming body, after the router had already
    sent ``200`` and after its ``except Geo1Error`` had already been skipped.
    Every unconnected sender then became a 500 with a full traceback, and a
    monitor page that retries a refused source printed one every second. The
    check now runs when the function is CALLED; only the loop is a generator.
    """
    link = _require(sender_id)
    return _mjpeg_frames(link)


def _mjpeg_frames(link: Link) -> Iterator[bytes]:
    with link.cond:
        link.viewers += 1
    last = 0
    try:
        while not link.stop.is_set():
            last, jpeg = link.wait_frame(last)
            if jpeg is None:
                # Nothing new. Do NOT resend the last frame: a stalled sender
                # must look stalled, or the page cannot tell live from frozen.
                continue
            yield (
                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                + jpeg
                + b"\r\n"
            )
    finally:
        with link.cond:
            link.viewers -= 1


def drift_stamp(header: dict[str, Any] | None) -> tuple[str, str | None]:
    """The sender's drift verdict in THIS app's vocabulary: (status, ref id).

    ★ TWO GUARDS, ONE VOCABULARY (2026-09-09, owner decision). The app's own
    drift monitor stamps every mark it places with ``ok`` / ``moved`` /
    ``changed`` / ``degraded``; a sender that runs its own guard reports the
    same four words, because both are the same ``DriftMonitor`` class under
    different roofs. So a mark placed from a sender's fix carries the SENDER'S
    verdict — the thing that actually gated whether that fix was sent at all —
    and the record can later answer "were these coordinates trustworthy?"
    with the same word it would use for a mark of its own.

    ``unwatched``: the header carries no drift block at all (a sender with
    ``--no-drift``). ``pending``: a guard exists but has not judged yet.
    """
    if not isinstance(header, dict):
        return "unwatched", None
    drift = header.get("drift")
    if not isinstance(drift, dict):
        return "unwatched", None
    # ``status`` is the temporally-filtered verdict, the one that gates lat/lon;
    # ``state`` is the raw per-check reading. Prefer the one that mattered.
    raw = drift.get("status") if drift.get("status") is not None else drift.get("state")
    if raw is None:
        return "pending", f"sender:{header.get('source') or '?'}"
    word = str(raw).strip().lower()
    return (word if word in _DRIFT_WORDS else "pending"), f"sender:{header.get('source') or '?'}"


def ndjson_lines(sender_id: str, fix_rate_hz: float = DEFAULT_FIX_RATE_HZ) -> Iterator[bytes]:
    """The sender's detections as one JSON line per object, for ever.

    ★ THIS IS THE RECORD CHANNEL. ``boxes()`` is what is on screen right now and
    is kept nowhere; this is what becomes a mark, a row in ``detection_events``
    and a point on the map. It is paced for evidence — at most ``fix_rate_hz``
    lines per track per second — and every line carries the sender's own drift
    verdict, so the record says whether the coordinates were trustworthy when
    they were written, not merely what they were.

    ★ SERVED ON THIS APP'S OWN API so the existing data-feed reader ingests it
    with no new source scheme, no new validator rule and no migration: to
    ``live_data_service`` it is an http NDJSON feed like any other. The field
    names are the sender's (``cls``, ``conf``, ``id``, ``bbox``, ``seq``,
    ``ts``) because the feed parser already accepts them; ``drift`` and
    ``drift_ref`` are the two additions.

    ★ NO FIX IS SENT AS null, NEVER AS A ZERO. When the guard says the camera
    moved, or an anchor found no ground, the line carries explicit nulls, which
    the parser records as a detection with no position rather than a point at
    sea.

    Refuses when called, not on the first line — see ``mjpeg_frames``.
    """
    link = _require(sender_id)
    return _ndjson_lines(link, fix_rate_hz)


def _ndjson_lines(link: Link, fix_rate_hz: float) -> Iterator[bytes]:
    period = (1.0 / fix_rate_hz) if fix_rate_hz > 0 else 0.0
    last_count = 0
    sent_at: dict[Any, float] = {}
    while not link.stop.is_set():
        count, _ = link.wait_frame(last_count)
        if count == last_count:
            continue                      # timed out; the link may be down
        last_count = count
        header, _ = link.snapshot()
        if header is None:
            continue
        now = time.monotonic()
        geo_ok = bool(header.get("geo_valid"))
        status, ref = drift_stamp(header)
        lines: list[str] = []
        for index, obj in enumerate(header.get("objects", [])):
            track = obj.get("id")
            key = track if track is not None else f"#{index}"
            if period > 0 and now - sent_at.get(key, -1e9) < period:
                continue
            sent_at[key] = now
            placed = geo_ok and obj.get("lat") is not None
            lines.append(json.dumps({
                "id": track,
                "cls": obj.get("cls"),
                "conf": obj.get("conf"),
                "lat": obj.get("lat") if placed else None,
                "lon": obj.get("lon") if placed else None,
                "bbox": obj.get("bbox"),
                "seq": header.get("seq"),
                "ts": header.get("ts"),
                "tracked": bool(obj.get("tracked", True)),
                "drift": status,
                "drift_ref": ref,
            }, separators=(",", ":")))
        if lines:
            yield ("\n".join(lines) + "\n").encode("utf-8")
        if len(sent_at) > 512:            # tracks die; their keys should not linger
            sent_at = {k: t for k, t in sent_at.items() if now - t < 60.0}


def command(sender_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one operator command to the sender and return its answer verbatim.

    ★ THE APP DOES NOT DECIDE WHAT A CLICK MEANS. The sender owns its tracker,
    so this carries the instruction and reports what came back — including a
    refusal, in the sender's own words. "The click hit nothing" and "no viewer
    is connected" are different facts and the operator is entitled to both.
    """
    link = _require(sender_id)
    line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with socket.create_connection(
            (link.host, link.control_port), timeout=COMMAND_TIMEOUT_S
        ) as sock:
            sock.settimeout(COMMAND_TIMEOUT_S)
            sock.sendall(line)
            buf = b""
            while b"\n" not in buf and len(buf) < 8192:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError as exc:
        return {"ok": False,
                "error": f"{link.host}:{link.control_port}: "
                         f"{type(exc).__name__}: {exc}"}
    if not buf:
        return {"ok": False, "error": "the sender closed without answering"}
    try:
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
    except ValueError as exc:
        return {"ok": False, "error": f"the sender did not answer with JSON: {exc}"}
