"""Live stream frame capture — wire types for ``/live/*``.

★ A live source is not an entity here — the app persists nothing about it. The
browser remembers the operator's saved stream URLs (client state), and this
surface does exactly one thing: grab a frame NOW and drop it into the capture
library, where it becomes an ordinary photograph.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from .common import ApiModel

__all__ = [
    "LiveFrameRequest",
    "LiveFrameCaptured",
    "LiveDeviceInfo",
    "LiveDeviceList",
    "SourceBox",
    "SourceBoxes",
    "SourceCommandRequest",
    "SourceCommandRead",
    "SenderRead",
    "SenderList",
    "SenderCommandRequest",
]


class LiveFrameRequest(ApiModel):
    """``POST /live/frame`` — capture one frame from a camera. Exactly one source.

    ★ Two lanes into the same grab: ``url`` for network cameras (http/https/rtsp),
    ``device`` for LOCAL capture hardware — ``/dev/videoN`` on Linux, a DirectShow
    index on Windows (HDMI capture cards and USB/USB-C cameras both live there).
    """

    #: http(s) (MJPEG/snapshot) or rtsp. Anything else is refused by scheme.
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    #: A local device id from ``GET /live/devices`` — ``/dev/video0`` or ``"0"``.
    device: str | None = Field(default=None, min_length=1, max_length=100)
    #: The surveyor's name for this capture. Baked into the saved filename
    #: (sanitised); blank falls back to the source label + timestamp.
    name: str | None = Field(default=None, max_length=120)
    #: ★ Optional: also save a copy into THIS absolute folder on the API's machine
    #: (the desktop "Save to folder…" picker). The capture always lands in the
    #: capture library regardless — this is an extra copy where the surveyor wants it.
    save_dir: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "LiveFrameRequest":
        if (self.url is None) == (self.device is None):
            raise ValueError("send exactly one of `url` (network camera) or `device` (local capture device).")
        return self


class LiveDeviceInfo(ApiModel):
    """One local capture device — HDMI capture card or USB/USB-C camera."""

    #: ``/dev/video0`` (Linux) or ``"0"`` (a Windows DirectShow index).
    id: str
    label: str


class LiveDeviceList(ApiModel):
    """``GET /live/devices`` — every local capture device the server can open."""

    items: list[LiveDeviceInfo]


class LiveFrameCaptured(ApiModel):
    """The frame, now sitting in the capture library."""

    filename: str
    width: int
    height: int
    size_bytes: int
    #: Ready-made URL of the file — ``/capture-library/{filename}``.
    file_url: str
    #: Where the extra copy landed when ``save_dir`` was given, else null.
    saved_to: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Data feeds — serial/UART devices and embedded systems that SEND detections
# (2026-09-02). See ``services/live_data_service.py``.
# ─────────────────────────────────────────────────────────────────────────────


class DataFeedStartRequest(ApiModel):
    """``POST /live/data-feeds`` — open a detection-data feed.

    ``source``: ``serial:///dev/ttyUSB0?baud=115200`` (or a bare ``/dev/tty…``
    path), or an http(s) URL streaming JSON/CSV detection lines.
    """

    source: str
    #: The registered camera this feed belongs to. When given, the feed is recorded
    #: as the camera's DESIRED state and re-opened after an API restart; a stop
    #: clears it. Its rows in ``detection_events`` carry the camera's id.
    camera_id: UUID | None = None


class DataFeedRead(ApiModel):
    """One feed's status — the monitor page polls this beside the marks."""

    feed_id: str
    source: str
    status: str = Field(description="starting | running | stopped | failed.")
    error: str | None = None
    started_at: str
    #: Epoch seconds of the last parsed line; 0 = nothing received yet.
    last_mark_at: float
    lines_ok: int
    #: Unparseable lines, counted — a glitchy UART shows up here, not in a crash.
    lines_bad: int
    #: Lines recognised as an already-ingested detection re-sent (2026-09-07) —
    #: what a device that answers with its whole table each time produces.
    lines_repeat: int = 0
    marks_total: int
    #: Marks placed while the SENDER'S own guard read MOVED or CHANGED — placed,
    #: never hidden; the count is the page's warning, as for a detection run.
    marks_under_alert: int = 0
    camera_id: UUID | None = None
    #: ``detection_events`` rows written / refused (a feed is evidence too, 2026-09-02).
    db_rows_written: int = 0
    db_rows_failed: int = 0
    db_error: str | None = None


class DataFeedMarksRead(ApiModel):
    """Marks from ``since`` onward — the same cursor shape a detection session serves."""

    next_index: int
    marks: list[dict]


class SourceBox(ApiModel):
    """One box a SENDER already found, in the shape this app draws its own.

    ★ Deliberately the frontend's ``DetectionBox``, field for field. The overlay
    canvas is source-agnostic — it draws whatever boxes it is handed — so the
    honest thing is to speak its vocabulary at the boundary rather than invent a
    parallel one and translate in the browser.
    """

    #: SOURCE-MEDIA pixels, top-left origin — the same units a run's boxes use,
    #: which is why ``SourceBoxes`` must carry the size they were measured in.
    x1: float
    y1: float
    x2: float
    y2: float
    score: float = Field(ge=0.0, le=1.0)
    cls_name: str
    track_id: int | None = None
    #: The sender's tracker carrying a box between detector passes, not a fresh
    #: sighting — drawn differently, exactly as our own predicted boxes are.
    predicted: bool = False
    #: The sender placed a coordinate for it. False is not a failure: a sender
    #: whose own drift guard has stopped vouching says so rather than guessing.
    placed: bool = False


class SourceBoxes(ApiModel):
    """``GET /live/boxes`` — the freshest boxes a sender is showing right now.

    ★ NOT EVIDENCE, AND NOT STORED. A data feed's marks are the record (they are
    written to ``detection_events``); this is the picture's annotation, fetched
    fresh and forgotten. The two must not be served from one channel: an overlay
    wants a few reads a second of what is on screen NOW, and the record wants
    every detection exactly once.
    """

    #: The sender's own frame counter, so a stale answer is visible as one.
    seq: int = 0
    frame_index: int = 0
    time_s: float = 0.0
    #: The frame size the boxes are measured in. Zero means "do not draw" — the
    #: overlay cannot letterbox a box without knowing the picture it came from.
    width: int = 0
    height: int = 0
    #: The sender's own verdict on whether its coordinates can be trusted.
    geo_valid: bool = False
    source: str | None = None
    boxes: list[SourceBox] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Recordings — the live stream + its attribute table, one folder per recording
# (2026-09-02). See ``services/recording_service.py``.
# ─────────────────────────────────────────────────────────────────────────────


class RecordingStartRequest(ApiModel):
    """``POST /live/recordings`` — start recording a source."""

    source: str
    camera_name: str = ""


class RecordingRead(ApiModel):
    """One recording's state — polled while it runs, final after stop."""

    recording_id: str
    source: str
    camera_name: str
    #: The folder's name inside the library (also the download key).
    folder: str
    #: The folder's absolute path — shown to the operator, copyable.
    path: str
    status: str = Field(description="recording | done | failed.")
    error: str | None = None
    started_at: str
    ended_at: str | None = None
    frames: int
    marks: int
    video_bytes: int


class ActiveRecordingRead(ApiModel):
    """``GET /live/recordings/active`` — the source's running recording, or none.

    ★ "NOT RECORDING" IS AN ANSWER, NOT AN ERROR (2026-09-10). This used to be a
    404, and every camera page opened with a red "Failed to load resource" in
    the console for the ordinary case of nothing being recorded — the browser
    logs any 4xx, whatever the page does with it. A normal 200 with ``null``
    says the same thing without crying wolf.
    """

    recording: RecordingRead | None = None


class RecordingLibraryEntry(ApiModel):
    """One saved folder in the recordings library."""

    folder: str
    path: str
    camera_name: str = ""
    source: str = ""
    started_at: str = ""
    ended_at: str | None = None
    duration_s: float = 0.0
    frames: int = 0
    marks: int = 0
    video_bytes: int = 0
    has_video: bool = False
    has_csv: bool = False
    #: ``satellite.png`` exists — the folder carries the scene's map (2026-09-12).
    #: False on a no-LUT recording (nothing was placed to draw) and on one made
    #: before the map existed, until its first package download builds one.
    has_map: bool = False
    #: ``preview.mp4`` (H.264) exists — the recording has been watched in the app once.
    playable: bool = False
    #: The folder this one was trimmed out of, when it is a cut (2026-09-07).
    trimmed_from: str | None = None


class RecordingLibraryList(ApiModel):
    """``GET /live/recordings`` — the library, newest first."""

    items: list[RecordingLibraryEntry]
    #: The library's root folder on this machine.
    root: str


class RecordingTableRow(ApiModel):
    """One row of a recording's attribute table, placed on the recording's clock."""

    index: int
    #: Seconds since the recording started — what the player seeks to; None when
    #: the row's ``time_utc`` could not be read.
    t: float | None = None
    time_utc: str = ""
    class_name: str = ""
    score: float | None = None
    lat: float | None = None
    lon: float | None = None
    frame: int | None = None
    track_id: int | None = None
    predicted: bool | None = None
    drift: str | None = None
    #: Metres the mark may be off on the ground from the measured drift (2026-09-09).
    drift_shift_m: float | None = None
    centre_m: float | None = None
    mark_id: int | None = None


class RecordingTable(ApiModel):
    """``GET /live/recordings/table/{folder}`` — the CSV as rows the player can follow."""

    folder: str
    camera_name: str = ""
    source: str = ""
    started_at: str = ""
    ended_at: str | None = None
    duration_s: float = 0.0
    table: str = Field(description="marks (LUT-placed, full columns) | detections (no LUT).")
    columns: list[str] = Field(default_factory=list)
    rows: list[RecordingTableRow] = Field(default_factory=list)
    has_video: bool = False
    trimmed_from: str | None = None


class RecordingTrimRequest(ApiModel):
    """``POST /live/recordings/trim/{folder}`` — the window to cut into a new recording."""

    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)


class SourceCommandRequest(ApiModel):
    """``POST /live/source-command`` — one operator instruction to a sender.

    ★ THE APP IS THE MESSENGER, NOT THE TRACKER. A sender that detects on its
    own hardware also owns the decision of what it follows; this carries the
    operator's click to it and nothing more. What the ops mean is the sender's
    vocabulary, not ours, which is why ``op`` is a plain string here.
    """

    #: The sender's command endpoint (its bridge). http(s) only, allow-listed
    #: by the same check the video lane uses.
    url: str = Field(min_length=1, max_length=2000)
    #: "track" | "untrack" | "clear" | "auto" — whatever the sender understands.
    op: str = Field(min_length=1, max_length=40)
    #: SOURCE-MEDIA pixels, for "track": the point the operator clicked.
    u: float | None = None
    v: float | None = None
    #: The object to release, for "untrack".
    id: int | None = None
    #: For "auto": on = the sender promotes detections by itself again.
    on: bool | None = None


class SourceCommandRead(ApiModel):
    """The sender's own answer, passed through.

    ★ NOT REWRITTEN. "no viewer is connected to this camera" and "the click hit
    nothing" are different facts and the operator is entitled to both; the app
    flattening them into a shrug would be the app lying about what it knows.
    """

    ok: bool = False
    #: Present when the sender accepted: the op it queued.
    accepted: str | None = None
    #: Present when it did not, in the sender's own words.
    error: str | None = None


class SenderRead(ApiModel):
    """A camera that announced itself on the wire, as IT described itself.

    ★ EVERY FIELD IS THE SENDER'S CLAIM, NOT OUR MEASUREMENT. The app has not
    opened a socket to it at this point — it has only heard a broadcast. That is
    enough to list it and to fill in a registration form, and not enough to
    assert anything about it, which is why `reachable` is stated separately.
    """

    #: host:port — stable while the camera keeps its address, so it works as a
    #: handle in a URL.
    id: str
    host: str
    port: int
    control_port: int
    name: str
    #: Epoch seconds of the last beacon heard.
    last_seen: float
    #: Where the sender says it stands, from its own lookup table — so a
    #: registration form arrives filled in rather than asking for coordinates.
    lat: float | None = None
    lon: float | None = None
    width: int | None = None
    height: int | None = None
    classes: list[str] | None = None
    #: True when it waits for an operator click before following anything.
    manual: bool | None = None
    lut: str | None = None
    #: Its table is a placeholder: coordinates will be believable and wrong.
    lut_placeholder: bool = False
    #: ★ HEARD IS NOT REACHED. A sender broadcasts to 255.255.255.255 as well as
    #: its own subnet, so a machine with no address on its network still hears
    #: it. False here means exactly that, and `needs_subnet` says what is
    #: missing — which is a far better thing to show than an empty list.
    reachable: bool = True
    needs_subnet: str | None = None


class SenderList(ApiModel):
    """Everything heard in the last few seconds. Silence removes a camera."""

    items: list[SenderRead] = Field(default_factory=list)


class SenderCommandRequest(ApiModel):
    """One operator instruction for a connected sender.

    ★ NO URL HERE, unlike :class:`SourceCommandRequest`. The sender is named in
    the path and the app already holds its connection, so an address on the wire
    would be a second source of truth about where to send this — and the one the
    caller could get wrong.
    """

    #: "track" | "untrack" | "clear" | "auto" — the sender's own vocabulary.
    op: str = Field(min_length=1, max_length=40)
    #: Source-media pixels, for "track": the point the operator clicked.
    u: float | None = None
    v: float | None = None
    #: The object to release, for "untrack".
    id: int | None = None
    #: For "auto": on = the sender promotes detections by itself again.
    on: bool | None = None
