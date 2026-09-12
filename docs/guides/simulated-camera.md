# Testing the monitor without a real camera

Two simulators, for two different questions.

| You want to test… | Use | What is real |
| --- | --- | --- |
| The whole pipeline — stream → YOLO → LUT placement → tracking → drift → capture — with no hardware | `scripts/simulate_camera.py` | everything: the backend, the app; only the camera is fake |
| The monitor UI alone, with no backend running | `frontend/scripts/fake-api/server.cjs` | only the frontend; the server is fake |

## 1. A simulated camera (real backend)

The script is an MJPEG server the app cannot tell from an IP camera. Run it with the
backend's Python (it needs OpenCV + numpy — the venv, or the desktop runtime):

```bash
# a synthetic scene: a road with moving vehicles and a landmark grid
desktop/runtime-build/env/bin/python scripts/simulate_camera.py

# or loop one of your own clips as the camera (drone footage works well)
desktop/runtime-build/env/bin/python scripts/simulate_camera.py --file ~/Desktop/MonoDEMO/Videos/input.mp4 --fps 15
```

It prints `http://127.0.0.1:8090/stream`. In the app: **Monitor → Add camera**, give
it a name and coordinates (the coordinates of the camera the clip was shot from, if you
have a LUT for it), and paste that URL as the source. Open it. From here on nothing is
simulated: the player measures the FPS, **Start detection** runs YOLO on it, a lookup
table places the marks on the map, the tracker hands off, the drift watch freezes a
reference and checks against it, Capture writes a frame to the library.

### Making things go wrong on purpose

The simulator has control endpoints — open them in a second browser tab or with `curl`
while the page is open:

| Call | What the app must do |
| --- | --- |
| `curl 'http://127.0.0.1:8090/control/stall?s=8'` | frames stop for 8 s → after 6 s the header pill reads **lost · stalled 6 s**, Capture and Start disable, the Events deck logs it; when frames resume, **Reconnect** brings it back |
| `curl 'http://127.0.0.1:8090/control/drop'` | every open stream is closed mid-run → a disconnect (not a refusal) |
| `curl 'http://127.0.0.1:8090/control/refuse?on=1'` | new connections get 503 → **REFUSED** with the server's own sentence; `?on=0` allows again |
| `curl 'http://127.0.0.1:8090/control/shift?px=40'` | the picture shifts 40 px → freeze a reference first, then Check now reports **MOVED**; `?px=0` puts it back |
| `curl http://127.0.0.1:8090/control/status` | clients, frames served, current state |

`/snapshot.jpg` serves a single frame — register that URL instead to test a
"snapshot endpoint" camera (the player says *JPEG snapshot*, and ending is not a
disconnect).

### A fake `/dev/video` device (optional, Linux)

To test the **local device** path (Scan local devices → a capture card) without a card,
`v4l2loopback` turns a file into a device:

```bash
sudo modprobe v4l2loopback video_nr=9 card_label="SimCam"
ffmpeg -re -stream_loop -1 -i ~/Videos/input.mp4 -f v4l2 -pix_fmt yuyv422 /dev/video9
```

`/dev/video9` then appears under Scan local devices and the backend opens it with
OpenCV like any capture card — including the uncompressed-format warning, since YUYV
is what a real card often offers.

## 2. A fake API (frontend only)

For layout and interaction work when no backend is available:

```bash
node frontend/scripts/fake-api/server.cjs     # answers on :8000
cd frontend && npm run dev                     # /api is proxied to :8000
```

Register a camera whose source is `http://localhost:5173/api/v1/live/stream?src=any`
(same origin, so the player runs in measured mode). You get: a live 10 fps stream,
the detector reported available, one lookup table (`yammone_124`, with a pose), 204
imagery tiles (the offline case), and **Start detection** refused with a verbatim
message — the three states the monitor's screenshots were taken in. It has no
detection sessions, marks or drift references; those need the real backend.
