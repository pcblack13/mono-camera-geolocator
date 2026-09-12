"""``/live/*`` — live video sources (``app.services.live_stream_service``).

★ NO cv2 HERE (L5): the router owns HTTP and settings; the service owns the grab.
The captured frame lands in the capture-export folder, so it appears in the
capture library instantly and imports into any project via the existing flow.

★ THREE SOURCE FAMILIES, one panel: network cameras (http MJPEG the browser can
render itself; rtsp it cannot), and LOCAL capture hardware — HDMI capture cards
and USB/USB-C cameras, which the OS presents as ``/dev/videoN`` (Linux) or
DirectShow devices (Windows). ``GET /live/stream`` re-serves ANY of them as http
MJPEG, which is what puts rtsp and local devices on the app panel at all.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

import anyio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import Settings
from app.schemas.live import (
    DataFeedMarksRead,
    DataFeedRead,
    DataFeedStartRequest,
    LiveDeviceInfo,
    LiveDeviceList,
    LiveFrameCaptured,
    LiveFrameRequest,
    RecordingLibraryEntry,
    RecordingLibraryList,
    ActiveRecordingRead,
    RecordingRead,
    RecordingStartRequest,
    RecordingTable,
    RecordingTrimRequest,
    SourceBoxes,
    SourceCommandRead,
    SourceCommandRequest,
    SenderCommandRequest,
    SenderList,
    SenderRead,
)
from app.services import geo1_service, live_data_service, live_stream_service
from app.services.camera_service import CameraService

router = APIRouter(prefix="/live", tags=["live"])


@router.get(
    "/devices",
    response_model=LiveDeviceList,
    summary="Local capture devices (HDMI capture cards, USB/USB-C cameras)",
)
async def list_live_devices() -> LiveDeviceList:
    """Probe and list the capture devices THIS machine can open right now.

    ★ Probing opens each candidate briefly, so this runs only when the operator
    asks (the UI's "Scan" button) — never on a timer. A device busy in another
    program is honestly absent from the answer.
    """
    devices = await anyio.to_thread.run_sync(live_stream_service.list_devices)
    return LiveDeviceList(items=[LiveDeviceInfo(id=d.id, label=d.label) for d in devices])


@router.get(
    "/boxes",
    response_model=SourceBoxes,
    summary="The boxes a sender is showing right now (its own detector's, for the overlay)",
)
async def source_boxes(
    src: str = Query(..., min_length=1, max_length=2000),
) -> SourceBoxes:
    """The freshest boxes from a sender that detects on its own hardware.

    ★ POLLED, NOT STREAMED, AND NEVER STORED. This is the picture's annotation:
    the monitor page reads it a few times a second while the operator is looking
    and stops when they are not. The sender's DETECTIONS — the record — arrive
    on its data feed instead, where every one becomes a ``detection_events`` row.

    ★ A SENDER THAT IS QUIET IS NOT AN ERROR. An unreachable or wordless sender
    answers as an empty box list with ``width``/``height`` zero, which the
    overlay reads as "draw nothing". A chip that flickers into an error banner
    every time a cable is nudged would train the operator to ignore banners.
    """
    try:
        payload = await anyio.to_thread.run_sync(
            live_data_service.fetch_source_boxes, src
        )
    except live_data_service.DataFeedError:
        return SourceBoxes()
    try:
        return SourceBoxes.model_validate(payload)
    except ValidationError:
        # The sender answered with something else entirely — same posture as an
        # unparseable feed line: counted as nothing, never a 500 on the page.
        return SourceBoxes()


# ─────────────────────────────────────────────────────────────────────────────
# Senders — cameras that announce themselves on a cable and detect on their own
# hardware. See ``services/geo1_service.py``.
#
# ★ ROUTE ORDER: the literal "/senders" is registered before "/senders/{id}/…",
#   and neither collides with "/data-feeds/{feed_id}" — same rule the cameras
#   router states for /cameras/all.
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/senders",
    response_model=SenderList,
    summary="Cameras heard announcing themselves on the network right now",
)
async def list_senders() -> SenderList:
    """Every sender heard in the last few seconds.

    ★ LISTENING, NOT SCANNING. The app never probes an address range and never
    guesses: a camera either broadcasts or it is not here. Silence for a few
    seconds removes it from the list, so unplugging a cable is visible while the
    operator is still looking at the screen.
    """
    senders = await anyio.to_thread.run_sync(geo1_service.list_senders)
    return SenderList(items=[SenderRead(**vars(s)) for s in senders])


@router.post(
    "/senders/{sender_id}/connect",
    response_model=SourceBoxes,
    summary="Start reading a sender (idempotent)",
    status_code=status.HTTP_200_OK,
)
async def connect_sender(
    sender_id: str,
    _: None = Depends(deps.require_writable),
) -> SourceBoxes:
    """Open the app's own reader for this sender and answer with its first boxes.

    ★ IDEMPOTENT, LIKE A DATA FEED. A second connect returns the running one, so
    a page can simply "ensure" its sender on every entry.
    """
    try:
        await anyio.to_thread.run_sync(geo1_service.connect, sender_id)
    except geo1_service.Geo1Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        return SourceBoxes.model_validate(
            await anyio.to_thread.run_sync(geo1_service.boxes, sender_id)
        )
    except (geo1_service.Geo1Error, ValidationError):
        # Connected, but no frame has arrived yet — an empty answer the overlay
        # already reads as "draw nothing", not an error.
        return SourceBoxes()


@router.delete(
    "/senders/{sender_id}/connect",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop reading a sender",
)
async def disconnect_sender(
    sender_id: str,
    _: None = Depends(deps.require_writable),
) -> Response:
    await anyio.to_thread.run_sync(geo1_service.disconnect, sender_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/senders/{sender_id}/boxes",
    response_model=SourceBoxes,
    summary="The boxes a connected sender is showing right now",
)
async def sender_boxes(sender_id: str) -> SourceBoxes:
    """Polled by the overlay a few times a second. Never stored.

    A sender that is not connected, or has sent no frame, answers as an empty
    box list with zero size — which the overlay reads as "draw nothing".
    """
    try:
        payload = await anyio.to_thread.run_sync(geo1_service.boxes, sender_id)
    except geo1_service.Geo1Error:
        return SourceBoxes()
    try:
        return SourceBoxes.model_validate(payload)
    except ValidationError:
        return SourceBoxes()


@router.get(
    "/senders/{sender_id}/stream",
    summary="A connected sender's pictures, as http MJPEG (the panel's player)",
)
async def sender_stream(sender_id: str) -> StreamingResponse:
    """★ ONE READER, MANY VIEWERS. Served from the frame the link already holds,
    so ten viewers cost the sender no more than one does."""
    try:
        frames = geo1_service.mjpeg_frames(sender_id)
    except geo1_service.Geo1Error as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return StreamingResponse(
        frames,
        media_type=f"multipart/x-mixed-replace; boundary={geo1_service.BOUNDARY}",
        headers={"Cache-Control": "no-store, no-cache, private", "Pragma": "no-cache"},
    )


@router.get(
    "/senders/{sender_id}/detections.ndjson",
    summary="A connected sender's detections, one JSON line each, for ever (the record channel)",
)
async def sender_detections(sender_id: str) -> StreamingResponse:
    """★ THE RECORD CHANNEL, served on our own API so the data-feed reader ingests
    it like any other http NDJSON feed — no new scheme, no migration. Rate-paced
    per track, and every line carries the sender's own drift verdict."""
    # ★ SELF-HEALING (2026-09-10). This URL is a registered camera's data source,
    #   read by the app's own feed reader from the moment the camera exists — long
    #   before anyone opens its page. The reader used to exist only after a
    #   "Connect" click, so after a relaunch the feed answered "not connected" every
    #   3 s for ever. The record channel now opens the reader itself when the
    #   sender is announcing; only a sender that is NOT on the cable is refused.
    try:
        if geo1_service.get_link(sender_id) is None:
            await anyio.to_thread.run_sync(geo1_service.connect, sender_id)
        lines = geo1_service.ndjson_lines(sender_id)
    except geo1_service.Geo1Error as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return StreamingResponse(
        lines,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/senders/{sender_id}/command",
    response_model=SourceCommandRead,
    summary="Carry an operator click to a sender that owns its own tracker",
)
async def sender_command(
    sender_id: str,
    body: SenderCommandRequest,
    _: None = Depends(deps.require_writable),
) -> SourceCommandRead:
    """★ A REFUSAL IS A 200 WITH ``ok: false``. The request reached us and we did
    our whole job — ask the sender, return its answer. "The click hit nothing"
    is information for the operator, not a failure of this API."""
    payload: dict[str, object] = {"op": body.op}
    for field_name in ("u", "v", "id", "on"):
        value = getattr(body, field_name)
        if value is not None:
            payload[field_name] = value
    try:
        answer = await anyio.to_thread.run_sync(
            geo1_service.command, sender_id, payload
        )
    except geo1_service.Geo1Error as exc:
        return SourceCommandRead(ok=False, error=str(exc))
    return SourceCommandRead(
        ok=bool(answer.get("ok")),
        accepted=answer.get("accepted"),
        error=answer.get("error"),
    )


@router.post(
    "/source-command",
    response_model=SourceCommandRead,
    summary="Send an operator command to a sender that detects on its own hardware",
)
async def source_command(
    body: SourceCommandRequest,
    _: None = Depends(deps.require_writable),
) -> SourceCommandRead:
    """Carry one click to the sender and report what it said.

    ★ A REFUSAL IS A 200 WITH ``ok: false``, NOT AN ERROR STATUS. The request
    reached us and we did our whole job -- ask the sender, return its answer.
    The sender saying "nobody is watching this camera" is information for the
    operator, not a failure of the API, and turning it into a 4xx would make
    the page show a broken-request banner over a working system.
    """
    payload: dict[str, object] = {"op": body.op}
    for field in ("u", "v", "id", "on"):
        value = getattr(body, field)
        if value is not None:
            payload[field] = value
    try:
        answer = await anyio.to_thread.run_sync(
            live_data_service.send_source_command, body.url, payload
        )
    except live_data_service.DataFeedError as exc:
        return SourceCommandRead(ok=False, error=str(exc))
    return SourceCommandRead(
        ok=bool(answer.get("ok")),
        accepted=answer.get("accepted"),
        error=answer.get("error"),
    )


@router.get(
    "/stream",
    summary="Re-serve a device or network source as http MJPEG (the panel's player)",
    response_class=StreamingResponse,
)
def stream_live_source(
    src: str = Query(
        ...,
        min_length=1,
        max_length=2000,
        description="A device id from GET /live/devices, or an http(s)/rtsp URL.",
    ),
    # ★ 30, NOT 15 (1.2.6). The old default silently halved every source's frame rate
    #   — the panel's player is paced by THIS number, so a 30 fps camera on its MJPEG
    #   pin still arrived at 15 and looked like the device's own limit. The ceiling
    #   goes to 60 so a 60 fps capture card is not throttled by a constant either.
    fps: float = Query(30.0, gt=0.0, le=60.0, description="Frame-rate cap for the re-stream."),
    quality: int = Query(80, ge=30, le=95, description="JPEG quality of re-encoded frames."),
) -> StreamingResponse:
    """One long-lived ``multipart/x-mixed-replace`` response of JPEG frames.

    ★ Sync endpoint + sync generator on purpose: FastAPI serves both through the
    threadpool, and the grab loop blocks on the device/network. The first frame is
    pulled EAGERLY so a bad source fails as a clean 422 — not as a broken-image
    icon with the reason buried in a stream that never starts.
    """
    try:
        meta, frames = live_stream_service.mjpeg_stream(src, fps=fps, quality=quality)
        first = next(frames)
    except live_stream_service.LiveCaptureError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except StopIteration:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the source opened but produced no frames.",
        ) from None

    def chained():  # noqa: ANN202 — a local generator; the annotation would just restate it
        yield first
        yield from frames

    # ★ The SOURCE's own story, for the stats panel: what codec is being re-encoded
    #   (X-Live-Source-Codec absent = the backend reported no usable FOURCC — shown
    #   as unknown, never guessed) and its native fps. ASCII-only header values.
    headers = {"Cache-Control": "no-store", "X-Live-Restream": "MJPEG"}
    if meta.codec:
        headers["X-Live-Source-Codec"] = meta.codec
    if meta.fps:
        headers["X-Live-Source-Fps"] = str(meta.fps)
    # ★ A device on an uncompressed pin STREAMS — it is explained, never refused
    #   (1.2.6). An earlier build made this a 422 and locked out a working greyscale
    #   camera; the data rate is the risk, not the format, and a slow picture beats
    #   no picture. ASCII-only by construction (see `uncompressed_warning`).
    if meta.uncompressed_note:
        headers["X-Live-Format-Warning"] = meta.uncompressed_note
    return StreamingResponse(
        chained(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers=headers,
    )


@router.post("/frame", response_model=LiveFrameCaptured,
             summary="Capture one frame from a live stream into the capture library")
async def capture_live_frame(
    body: LiveFrameRequest,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> LiveFrameCaptured:
    out_dir = settings.capture_export_dir
    if not out_dir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the capture library is disabled on this server "
            "(LE_CAPTURE_EXPORT_DIR is unset) — captured frames would have no home.",
        )

    source = body.device if body.device is not None else body.url
    assert source is not None  # the schema's exactly-one validator guarantees it
    try:
        # The grab blocks on network/device + decode — never on the event loop.
        frame = await anyio.to_thread.run_sync(
            lambda: live_stream_service.capture_frame(
                source, out_dir.expanduser(), name=body.name
            )
        )
    except live_stream_service.LiveCaptureError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # ★ OPTIONAL EXTRA COPY into a folder the surveyor picked. The capture ALWAYS
    #   lands in the capture library above (that is the referenced live-capture
    #   library); this just also drops a copy where they want it — e.g. straight
    #   into a project's own folder — without a separate export step.
    saved_to: str | None = None
    if body.save_dir:
        dest_dir = Path(body.save_dir).expanduser()
        if not dest_dir.is_dir():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"the save folder does not exist: {body.save_dir!r}.",
            )
        dest = dest_dir / frame.filename
        try:
            await anyio.to_thread.run_sync(lambda: shutil.copyfile(frame.path, dest))
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"could not write the frame to {dest_dir}: {exc}.",
            ) from exc
        saved_to = str(dest)

    prefix = f"{request.scope.get('root_path', '')}/api/v1"
    return LiveFrameCaptured(
        filename=frame.filename,
        width=frame.width,
        height=frame.height,
        size_bytes=frame.size_bytes,
        file_url=f"{prefix}/capture-library/{frame.filename}",
        saved_to=saved_to,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Data feeds — integrations that SEND detections instead of (or beside) video:
# serial/UART sensors, embedded systems (a Pi running its own detector). The
# feed's marks land on the map exactly as the app's own detections do.
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/data-feeds",
    response_model=DataFeedRead,
    summary="Open a detection-data feed (serial/UART or http JSON/CSV lines)",
)
async def start_data_feed(
    body: DataFeedStartRequest,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> DataFeedRead:
    """Open (or find running) the feed for this source.

    ★ Idempotent per source: a second start of the same feed returns the running
    one — the monitor page can simply "ensure" its feed on every entry. With a
    ``camera_id`` the feed is also the camera's recorded intent (restored at boot).
    """
    camera_name: str | None = None
    if body.camera_id is not None:
        camera_name = (await CameraService(db).get(body.camera_id)).name
    try:
        feed = live_data_service.start_feed(
            body.source,
            camera_id=str(body.camera_id) if body.camera_id else None,
            camera_name=camera_name,
        )
    except live_data_service.DataFeedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if body.camera_id is not None:
        await CameraService(db).record_feed(body.camera_id, True)
    return _feed_to_read(feed)


@router.get("/data-feeds/{feed_id}", response_model=DataFeedRead, summary="One feed's status")
async def get_data_feed(feed_id: str) -> DataFeedRead:
    """One feed's status — polled beside the marks."""
    feed = live_data_service.get_feed(feed_id)
    if feed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such data feed.")
    return _feed_to_read(feed)


@router.get(
    "/data-feeds/{feed_id}/marks",
    response_model=DataFeedMarksRead,
    summary="The feed's marks from `since` onward — the map polls incrementally",
)
async def data_feed_marks(feed_id: str, since: int = Query(0, ge=0)) -> DataFeedMarksRead:
    """The marks cursor — identical in shape to a detection session's."""
    try:
        next_index, marks = live_data_service.marks_since(feed_id, since)
    except live_data_service.DataFeedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DataFeedMarksRead(next_index=next_index, marks=marks)


@router.delete("/data-feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop a feed")
async def stop_data_feed(
    feed_id: str,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    """Stop the reader thread; the feed's marks stay readable until restart. A feed
    that belonged to a camera clears that camera's intent — a stop is a decision."""
    feed = live_data_service.get_feed(feed_id)
    try:
        live_data_service.stop_feed(feed_id)
    except live_data_service.DataFeedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if feed is not None and feed.camera_id:
        try:
            await CameraService(db).record_feed(UUID(feed.camera_id), False)
        except Exception:  # noqa: BLE001 — a camera removed meanwhile is not an error here
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _feed_to_read(feed: live_data_service.DataFeed) -> DataFeedRead:
    return DataFeedRead(
        feed_id=feed.feed_id,
        source=feed.source,
        status=feed.status,
        error=feed.error,
        started_at=feed.started_at.isoformat().replace("+00:00", "Z"),
        last_mark_at=feed.last_mark_at,
        lines_ok=feed.lines_ok,
        lines_bad=feed.lines_bad,
        lines_repeat=feed.lines_repeat,
        marks_total=feed.marks_dropped + len(feed.marks),
        camera_id=UUID(feed.camera_id) if feed.camera_id else None,
        marks_under_alert=feed.marks_under_alert,
        db_rows_written=feed.db_rows_written,
        db_rows_failed=feed.db_rows_failed,
        db_error=feed.db_error,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recordings — the live stream + its attribute table, one folder per recording.
# The library lives beside the capture library; a folder holds video.mp4 +
# detections.csv + meta.json (2026-09-02).
# ─────────────────────────────────────────────────────────────────────────────


def _recording_to_read(rec: "object") -> RecordingRead:
    from app.services.recording_service import Recording

    assert isinstance(rec, Recording)
    return RecordingRead(
        recording_id=rec.recording_id,
        source=rec.source,
        camera_name=rec.camera_name,
        folder=rec.folder.name,
        path=str(rec.folder),
        status=rec.status,
        error=rec.error,
        started_at=rec.started_at.isoformat().replace("+00:00", "Z"),
        ended_at=rec.ended_at.isoformat().replace("+00:00", "Z") if rec.ended_at else None,
        frames=rec.frames,
        marks=rec.marks,
        video_bytes=rec.video_bytes,
    )


@router.post(
    "/recordings",
    response_model=RecordingRead,
    summary="Record this source — the stream as watched, plus the run's attribute table",
)
async def start_recording(
    body: RecordingStartRequest,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> RecordingRead:
    """★ Idempotent per source: pressing Record on a source already recording
    returns the running recording rather than forking a second file."""
    from app.services import recording_service

    try:
        return _recording_to_read(
            recording_service.start_recording(body.source, body.camera_name, settings)
        )
    except recording_service.RecordingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/recordings/active",
    response_model=ActiveRecordingRead,
    summary="The active recording of a source, if any — how a re-entered page finds it",
)
async def active_recording(src: str = Query(...)) -> ActiveRecordingRead:
    """The running recording, or ``{"recording": null}``.

    A 200 rather than a 404 when nothing is being recorded: that is the ordinary
    case on every camera page, not a failure.
    """
    from app.services import recording_service

    rec = recording_service.recording_for_source(src)
    return ActiveRecordingRead(recording=None if rec is None else _recording_to_read(rec))


@router.delete(
    "/recordings/{recording_id}",
    response_model=RecordingRead,
    summary="Stop and finalize — returns once video, CSV and meta are on disk",
)
async def stop_recording(
    recording_id: str,
    _: None = Depends(deps.require_writable),
) -> RecordingRead:
    import anyio

    from app.services import recording_service

    try:
        rec = await anyio.to_thread.run_sync(recording_service.stop_recording, recording_id)
    except recording_service.RecordingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _recording_to_read(rec)


@router.get(
    "/recordings",
    response_model=RecordingLibraryList,
    summary="The recordings library — one folder per recording, newest first",
)
async def list_recordings(settings: Settings = Depends(deps.get_settings)) -> RecordingLibraryList:
    from app.services import recording_service

    return RecordingLibraryList(
        items=[RecordingLibraryEntry(**e) for e in recording_service.library_entries(settings)],
        root=str(recording_service.recordings_root(settings)),
    )


def _serve_file(request: Request, path: Path, media_type: str) -> Response:
    """Stream a file on disk, honouring a single ``Range`` request → 200/206.

    ★ Range support is what makes seeking work in a ``<video>`` — the same
    contract ``images._serve_object`` gives stored objects, for a plain path.
    """
    size = path.stat().st_size
    headers: dict[str, str] = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = status.HTTP_200_OK
    if range_header and range_header.startswith("bytes="):
        spec = range_header.split("=", 1)[1].split(",")[0]
        lo, _, hi = spec.partition("-")
        try:
            start = int(lo) if lo else 0
            end = int(hi) if hi else size - 1
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail=f"malformed Range header: {range_header!r}",
            ) from exc
        if start > end or start >= size:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail=f"range {start}-{end} is outside 0-{size - 1}.",
                headers={"Content-Range": f"bytes */{size}"},
            )
        end = min(end, size - 1)
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)

    def body():  # noqa: ANN202 — an iterator of chunks
        remaining = end - start + 1
        with path.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(body(), status_code=status_code, media_type=media_type, headers=headers)


@router.get(
    "/recordings/files/{folder}/{file}",
    summary="One file of a recording: video.mp4, detections.csv, meta.json — preview.mp4 to watch it, poster.jpg for its picture",
)
async def recording_file(
    request: Request,
    folder: str,
    file: str,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    """Serve one of the folder's files; ``preview.mp4`` is derived on the first ask."""
    from app.services import recording_service

    try:
        if file == recording_service.PLAYABLE:
            # ★ Derived on the first ask (ffmpeg; seconds for a short clip) — off
            #   the event loop — then streamed with Range support, so the player
            #   can seek.
            path = await anyio.to_thread.run_sync(
                recording_service.ensure_preview, settings, folder
            )
            return _serve_file(request, path, "video/mp4")
        if file == recording_service.POSTER:
            path = await anyio.to_thread.run_sync(recording_service.ensure_poster, settings, folder)
            return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
        path = recording_service.library_file(settings, folder, file)
    except recording_service.RecordingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media = "video/mp4" if file.endswith(".mp4") else "text/csv" if file.endswith(".csv") else "application/json"
    return FileResponse(
        path,
        media_type=media,
        filename=f"{folder}-{file}",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/recordings/package/{folder}",
    summary="The whole session as one zip — video/, map/ and table/ in one folder",
)
async def recording_package(
    folder: str,
    background: BackgroundTasks,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    """One button, one folder: the video, the satellite map and the attribute table.

    ★ The satellite map is stitched at STOP, so this is normally a zip of files
      already on disk. A recording made before the map existed (or one stopped
      while imagery was unreachable) has its map built here, once, on the first
      download — see ``ensure_satellite_map``.
    """
    from app.services import recording_service

    try:
        path, filename = await anyio.to_thread.run_sync(
            recording_service.package_path, settings, folder
        )
    except recording_service.RecordingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # The zip is a temporary file; it goes once the response has been sent.
    background.add_task(lambda: Path(path).unlink(missing_ok=True))
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=background,
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/recordings/table/{folder}",
    response_model=RecordingTable,
    summary="A recording's attribute table as rows on its own clock — what the player follows",
)
async def recording_table(
    folder: str,
    settings: Settings = Depends(deps.get_settings),
) -> RecordingTable:
    """The CSV as rows, each with ``t`` = seconds since the recording started."""
    from app.services import recording_service

    try:
        data = await anyio.to_thread.run_sync(recording_service.recording_table, settings, folder)
    except recording_service.RecordingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RecordingTable(**data)


@router.post(
    "/recordings/trim/{folder}",
    response_model=RecordingLibraryEntry,
    summary="Cut a window of a recording into a NEW recording — the original is untouched",
)
async def trim_recording(
    folder: str,
    body: RecordingTrimRequest,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> RecordingLibraryEntry:
    """Write the window into a new folder and answer with its library entry."""
    from app.services import recording_service

    try:
        entry = await anyio.to_thread.run_sync(
            recording_service.trim_recording, settings, folder, body.start_s, body.end_s
        )
    except recording_service.RecordingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RecordingLibraryEntry(**entry)


@router.delete(
    "/recordings/library/{folder}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one recording folder from the library",
)
async def delete_recording_entry(
    folder: str,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> Response:
    from app.services import recording_service

    try:
        recording_service.delete_library_entry(settings, folder)
    except recording_service.RecordingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
