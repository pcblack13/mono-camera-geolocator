# Mono Camera Geolocator — Install (Desktop)

Download the latest release (v1.3.0):
**https://github.com/Doctor13-st/GEO-1/releases/latest**

No setup, no keys — satellite imagery works out of the box.

## Windows

1. Download **MonoCameraGeolocator-Setup-1.3.0.exe**
2. Double-click it — the app installs itself and opens (first launch takes ~1 min)

## Linux (Ubuntu/Debian)

1. Download **mono-camera-geolocator_1.3.0_amd64.deb**
2. ```bash
   sudo apt install ./mono-camera-geolocator_1.3.0_amd64.deb
   ```
3. Open **Mono Camera Geolocator** from the applications menu

## Enabling the object detector (YOLO)

Video detection and the Live stream's detector are **locked until two things are on the
machine**. The app never downloads them — it works offline — so the pages show a lock with
the exact reason until you do this once:

1. **Install the detection runtime into the app's own Python** (not the system one):

   | Where | Python to use |
   | --- | --- |
   | Installed desktop app, Linux | `~/.local/share/MonoCameraGeolocator/runtime/bin/python` |
   | Installed desktop app, Windows | `%LOCALAPPDATA%\MonoCameraGeolocator\runtime\python.exe` |
   | Developer checkout | `.venv/bin/python` (created by `scripts/bootstrap_dev.sh`) |

   ```bash
   # CPU-only machines first (smaller, no CUDA):
   <python> -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
   <python> -m pip install ultralytics
   ```

2. **Copy a YOLO weights file** (for example `yolo26s.pt`) into the models folder:

   | Where | Models folder |
   | --- | --- |
   | Installed desktop app, Linux | `~/.local/share/MonoCameraGeolocator/work/data/models/` |
   | Installed desktop app, Windows | `%LOCALAPPDATA%\MonoCameraGeolocator\work\data\models\` |
   | Developer checkout | `backend/data/models/` |

   The app's API runs from that `work` folder, so `data/models` resolves there. (Or point
   `LE_DETECTION_MODEL_DIR` at any folder holding `*.pt` files.) `./run-desktop.sh` uses the
   same runtime and data folders as the installed app — one install covers both.

3. **Restart the app** — the API probes what the machine can do once, at start-up.

★ **After** `pip install ultralytics`, put the OpenCV **contrib** wheel back. `ultralytics`
pulls in plain `opencv-python`, which shadows the contrib build the runtime ships (the one
with the CSRT tracker), and the two wheels share one `cv2/` folder — so uninstalling the
plain one alone leaves `cv2` broken. Do it in this order:

```bash
<python> -m pip uninstall -y opencv-python opencv-python-headless
<python> -m pip install --force-reinstall --no-deps opencv-contrib-python-headless
```

Keep exactly one `cv2` wheel installed. Without the contrib build detection still works,
running YOLO on every frame; the tracker (and its speed-up) stays locked.

Check the result from the `backend/` folder — everything should read `available: True`:

```bash
cd backend && PYTHONPATH=. <python> -c "from pathlib import Path; \
from app.services.detection_service import availability; \
print(availability(Path('<models folder>')))"
```

## Updating

Download the newer installer from the same link and install it the same way —
the app refreshes itself and keeps all your projects and data.

## What's new in 1.3.0

The Live stream tab became a **Monitor**: a globe of registered cameras and a
page per camera. The camera list now lives on the server (a browser that ran
1.2.x is asked once to move its cameras across), and whatever you left running
on a camera — a drift watch, a detection run, a data feed — comes back by itself
after a restart. Every geolocated detection records the camera's **drift
verdict** at the instant it was placed, so a coordinate placed after the camera
moved says so. Also: object detection on clips and streams with a durable
record, the drift monitor, lookup-table import, a status page with the live log,
Arabic with a mirrored layout, and a display-size control. Full notes:
`desktop/installer/1.3.0.md`.

## What's new in 1.2.6

Ground control points now name themselves and commit with F1, and adjusting one
keeps the photograph and the satellite map in step. A photograph can use its own
elevation model, projects have their own settings page, and the DEM library can
be tidied up. Live streaming runs at full frame rate and says clearly when a
camera disconnects. Full notes: `desktop/installer/1.2.6.md`.
