# Input / output contract — drift watch field unit

**Contract version 1.0.0** (`__version__` in `drift_daemon.py`, echoed in every
`startup` line).

> **Compatibility promise.** Within a major version, fields are only ever
> **added** — never renamed, removed, or changed in meaning or unit. A reader
> written against `1.0` keeps working on all `1.x` output. Ignore fields you do
> not recognise.

---

## INPUT

### 1. The reference — `landmarks.npz` (required)

The camera's frozen memory of a view it was trusted in. Produced on the PC by
the Mono Camera Geolocator's **Freeze reference**; opaque to the field unit.

Contains 12 template patches, each landmark's pixel position and its real-world
`X/Y/Z`, plus the camera pose (`K`, `dist`, `R_ref`, `C`) and the frame shape.

**It carries no map and no terrain model.** The world positions were resolved at
freeze time, which is why nothing here needs a DEM or a LUT.

### 2. The settings — `field_unit.json` (strongly recommended)

Written by the export beside the npz. Read automatically if present.

```json
{
  "frame_width": 1920, "frame_height": 1080,
  "patch_px": 22, "search_px": 19,
  "confirm_n": 3, "alert_mrad": 3.6079,
  "frozen_ref_range_m": 277.17, "n_landmarks": 12,
  "ref_id": "…", "lut_site": "…", "frozen_utc": "…"
}
```

> **Ship this file.** It keeps the unit's `search_px` identical to the PC's.
> A missing one is not fatal — `PATCH`, the value that actually governs
> correctness, is recovered from the templates themselves, and `SEARCH` falls
> back to the app's own width rule. See [BRIEF.md](BRIEF.md) § *The window-size
> trap* for what each one does and why only one of them can break a verdict.

### 3. The camera — `--source` (required)

| Form | Example |
|---|---|
| device index | `0` |
| device path | `/dev/video0` |
| network stream | `rtsp://cam/s1`, `http://host:8090/stream` |
| video file | `/path/clip.mp4` (testing) |

**The frame size must equal the reference's.** A mismatch is refused, not
rescaled — the templates compare pixel positions. See exit code `2`.

### 4. Options

| Flag | Default | Meaning |
|---|---|---|
| `--interval` | `30` | seconds between checks |
| `--alert-mrad` | from the reference | alert above this rotation, in milliradians — **range-free** |
| `--range M` | none | also report metres at this range; **repeatable** |
| `--confirm-n` | from the reference | consecutive bad readings before `status` flips |
| `--search` | from `field_unit.json` | override the search half-window |
| `--once` | off | one check, then exit |
| `--version` | — | print the contract version |

---

## OUTPUT

**stdout:** one JSON object per line (NDJSON), flushed per line — a reader sees
each verdict the moment it exists. **stderr:** human diagnostics only. Never
parse stderr; never expect anything but NDJSON on stdout.

Every line has `event` and `ts` (ISO-8601 UTC, `Z`).

### `event: "startup"` — once, at launch

```json
{"event":"startup","ts":"2026-09-03T08:52:23Z","version":"1.0.0",
 "reference":"landmarks.npz","n_landmarks":12,"frame_required":[1920,1080],
 "alert_mrad":3.6079,"patch_px":22,"search_px":19,"confirm_n":3,
 "interval_s":30.0,"ranges_m":[200.0,1000.0]}
```

Check `patch_px` / `search_px` against the GUI before trusting a hand-assembled
bundle.

### `event: "drift"` — one per check

```json
{"event":"drift","ts":"2026-09-03T08:52:23Z","seq":1,
 "status":"OK","state":"OK","confirmed":false,
 "rot_deg":0.00075,"rot_mrad":0.0131,"alert_mrad":3.6079,
 "pan_deg":-0.0004,"tilt_deg":0.0002,"roll_deg":-0.0006,
 "resid_mean_px":0.106,"snr":0.035,"mean_conf":1.0,
 "n_matched":12,"n_lost":0,
 "why":"drift 0.001 deg = 0.00 m at 277 m, below the 1.00 m threshold",
 "ground_err_m":{"200":0.0026,"1000":0.0131}}
```

| Field | Type | Meaning |
|---|---|---|
| `seq` | int | check counter since launch, from 1 |
| **`status`** | enum\|null | **the confirmed verdict — ALERT ON THIS.** `null` until the first promotion |
| **`state`** | enum | this frame's raw reading — **LOG THIS** |
| `confirmed` | bool | `true` on the check that promotes a non-OK status |
| `rot_deg` / `rot_mrad` | float\|null | how far the camera turned |
| `alert_mrad` | float | the threshold in force, repeated on every line so a log is self-describing |
| `pan_deg` | float\|null | turned left / right (about the camera's down axis) |
| `tilt_deg` | float\|null | rose / fell (about the right axis) |
| `roll_deg` | float\|null | horizon tipped (about the forward axis) |
| `resid_mean_px` | float\|null | how badly one rigid rotation fails to explain the landmarks |
| `snr` | float\|null | claimed shift ÷ landmark disagreement — **the tell that separates a turn from a zoom** |
| `mean_conf` | float\|null | mean template match confidence, 0–1 |
| `n_matched` / `n_lost` | int | landmarks found / lost this frame |
| `why` | string | a sentence safe to show an operator verbatim |
| `ground_err_m` | object | present only with `--range`; keys are the ranges as strings |

**Signs:** `pan/tilt/roll` follow the right-hand rule about the camera's own
right / down / forward axes. Their vector norm equals `rot_deg` exactly, so the
parts can never disagree with the whole.

**Nulls:** every solve figure is `null` on `DEGRADED` — nothing was solved.
Do not read `null` as zero.

### The four states

| `state` | Meaning | What to do |
|---|---|---|
| `OK` | matched; any rotation is below threshold | nothing |
| `MOVED` | coherent rotation above threshold — mount drift | re-aim, or re-solve the pose |
| `CHANGED` | landmarks moved but **no rigid rotation explains it** — zoom, focus, lens, translated mount | full re-solve; re-aiming will not fix it |
| `DEGRADED` | too few or too weak matches (fog, night, scene change) | wait — **not an alert**, it means "I cannot tell" |

> `MOVED` and `CHANGED` both mean *stop trusting the coordinates*. They are kept
> apart because the remedy differs. Collapsing any state into `OK` is how a
> monitor lies.

### `event: "no_frame"` — a look that got no picture

```json
{"event":"no_frame","ts":"…","seq":7}
```

A **service fault, never a verdict.** Device busy, unplugged, stream dropped.
Reporting a camera steady because nobody looked is exactly the failure the four
states exist to prevent — so this is not `OK`, and it is not `DEGRADED` either.
The daemon keeps running.

### `event: "error"` — fatal, the daemon exits

```json
{"event":"error","ts":"…","seq":1,
 "why":"stream is 1280x720 but the reference was frozen at 1920x1080. …"}
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | clean stop (SIGINT/SIGTERM, or `--once` succeeded) |
| `1` | `--once` and the camera gave no frame |
| `2` | frame size does not match the reference — fatal, will not self-correct |
| `SystemExit` with a message | the source could not be opened, or the npz is missing |

---

## Reading it

```bash
# alerts only
drift_daemon.py --landmarks landmarks.npz --source /dev/video0 \
  | jq -c 'select(.event=="drift" and .status!="OK")'
```

See [`examples/consume.py`](examples/consume.py) for a consumer that reads the
stream and calls your own handler on confirmed alerts.

---

## What this does NOT output

- **No coordinates.** This unit answers *"has the camera moved?"*, not *"where
  is that object?"*. Pixel→lat/lon needs the LUT bundle (146 MB) and
  `pi_lookup.py`.
- **No images.** Verdicts only.
- **No corrected pose.** The monitor computes one but never applies it —
  adopting it would let the reference re-anchor to itself and drift freely with
  nothing holding it. Detect, report, let a human decide.
