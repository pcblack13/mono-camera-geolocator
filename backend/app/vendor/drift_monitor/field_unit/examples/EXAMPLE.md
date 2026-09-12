# A worked example — what goes in, what comes out

Real input, real output. `sample-output.jsonl` beside this file is the verbatim
run, not a mock-up: three checks against a clip, recorded with the command below.

---

## The inputs

Two, and only two.

### 1. The reference — `landmarks.npz`

Made once on the PC, by **Freeze reference** in the Mono Camera Geolocator.
Opaque to the field unit; ~9 KB.

Inside it: 12 template patches, each landmark's pixel position and its real-world
`X/Y/Z`, the camera pose (`K`, `dist`, `R_ref`, `C`), and the frame shape. **No
map and no terrain model** — every world position was resolved at freeze time,
which is the whole reason this runs on a box with no DEM.

### 2. The camera — `--source`

| form | example |
|---|---|
| device index | `0` |
| device path | `/dev/video0` |
| network stream | `rtsp://cam/s1`, `http://host:8090/stream` |
| video file | `clip.mp4` (testing; `--seek` picks a second) |

**Its frames must be the size the reference was frozen at** — here 1920×1080.
The monitor compares pixel positions, so a different size is refused, not
rescaled.

### Alongside them: `field_unit.json`

Written by the export. Carries the settings that must match the PC — `patch_px`,
`search_px`, the frame profile, and the threshold as an angle. Read
automatically. Ship it: see `BRIEF.md` § *The window-size trap* for what it
prevents.

---

## The command that produced `sample-output.jsonl`

```bash
python3 drift_daemon.py \
  --landmarks landmarks.npz \
  --source clip.mp4 --seek 1 \
  --alert-mrad 3.6 \
  --range 277 --range 1000
```

`--seek` is the testing path; on a mast you leave it off and set `--interval 30`.
`--alert-mrad` is the threshold as an **angle**, so it holds at any distance.
`--range` is optional and repeatable — ask for metres at the distances you care
about, and each figure comes back labelled with the range it is true at.

---

## The outputs

One JSON object per line on stdout, flushed per line. Diagnostics go to stderr,
so `| jq` never chokes.

### Line 1 — `startup`, once

```jsonc
{"event":"startup","version":"1.0.0","n_landmarks":12,
 "frame_required":[1920,1080],          // what the camera must deliver
 "patch_px":22,"search_px":19,          // CHECK THESE against the GUI
 "alert_mrad":3.6,"confirm_n":3,"ranges_m":[277,1000]}
```

### Then one `drift` line per check

At **1 s** — steady:

```jsonc
{"event":"drift","seq":1,"status":"OK","state":"OK","confirmed":false,
 "rot_deg":0.0295,"rot_mrad":0.5153,"alert_mrad":3.6,
 "pan_deg":0.0104,"tilt_deg":-0.0266,"roll_deg":-0.0059,
 "resid_mean_px":0.434,"snr":1.4,"mean_conf":0.9999,
 "n_matched":12,"n_lost":0,
 "why":"drift 0.030 deg = 0.14 m at 277 m, below the 1.00 m threshold",
 "ground_err_m":{"277":0.1427,"1000":0.5153}}
```

At **20 s** and **38 s** the camera has turned:

| second | `state` | `rot_deg` | ground error @ 277 m | @ 1 km |
|---|---|---|---|---|
| 1 s | `OK` | 0.02952 | 0.14 m | 0.52 m |
| 20 s | `MOVED` | 0.26726 | 1.29 m | 4.66 m |
| 38 s | `MOVED` | 0.76611 | 3.70 m | 13.37 m |

Note the same rotation costs **9× more** at 1 km than at 277 m. That is the whole
argument for publishing the angle and deriving metres per range, rather than
baking one range into the output.

> This clip is from a **drone**, so it genuinely moves — `MOVED` here is the
> monitor being right, not a fault. On a fixed mast the same bundle should read
> `OK` all day.

### Reading a line

| field | |
|---|---|
| **`status`** | the confirmed verdict — **alert on this** |
| **`state`** | this frame's raw reading — **log this** |
| `confirmed` | `true` on the check that promotes a non-OK status |
| `rot_deg` / `rot_mrad` | how far it moved |
| `pan` / `tilt` / `roll` | **which way** — signed, about the camera's own axes. Their vector norm equals `rot_deg`, so the parts can never disagree with the whole. |
| `snr` | claimed shift ÷ landmark disagreement — the tell that separates a turn from a zoom |
| `why` | a sentence safe to show an operator verbatim |

Two other events: `no_frame` when a look got no picture — a **service fault,
never a verdict** — and `error` for a fatal refusal, which exits.

Full field list, types, nulls and exit codes: **`OUTPUT.md`**.

---

## Acting on it

```bash
# alerts only
python3 drift_daemon.py --landmarks landmarks.npz --source /dev/video0 \
  | jq -c 'select(.event=="drift" and .status!="OK")'

# or hand each line to your own handler
python3 drift_daemon.py ... | python3 examples/consume.py
```

`consume.py` is a working consumer: it logs everything, calls `on_alert` when the
camera is **confirmed** moved, and — deliberately — does **not** let a
`DEGRADED` reading or a missed look clear a standing alert.
