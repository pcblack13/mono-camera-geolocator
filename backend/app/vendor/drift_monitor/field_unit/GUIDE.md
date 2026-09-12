# Guide — drift watch field unit

Install, run, integrate, tune, troubleshoot, deploy.
See [OUTPUT.md](OUTPUT.md) for the exact contract, [BRIEF.md](BRIEF.md) for how
it works inside.

---

## 1. What you need

| | |
|---|---|
| A bundle | the zip exported from the Mono Camera Geolocator, ~25 KB |
| Python | 3.8 or newer |
| Two packages | `numpy`, `opencv-python-headless` |
| A camera | at **exactly** the resolution the reference was frozen at |

Nothing else. No internet at run time, no map data, no GPU.

---

## 2. Get the bundle

On the PC running the geolocator, with the reference already frozen:

```bash
curl -o field-unit.zip \
  "http://127.0.0.1:8123/api/v1/drift/references/<REF_ID>/field-unit"
```

`<REF_ID>` comes from `GET /api/v1/drift/references`, or the Drift monitor tab.

Copy it across and unpack:

```bash
mkdir -p /opt/driftwatch && unzip field-unit.zip -d /opt/driftwatch
```

> **Use the export rather than hand-assembling a bundle.** A lone
> `landmarks.npz` has no `field_unit.json`, so the daemon falls back to deriving
> `search_px` instead of reading the PC's. It is not fatal — `selftest.py` will
> tell you — but there is no reason to run on a guess. See
> [BRIEF.md](BRIEF.md) § *The window-size trap*.

---

## 3. Install

```bash
cd /opt/driftwatch
python3 -m venv venv
venv/bin/pip install -r requirements-embedded.txt
```

### On a Raspberry Pi, use the OS packages instead

Building numpy or OpenCV from source on a Pi takes hours. The prebuilt ones are
fine:

```bash
sudo apt install python3-numpy python3-opencv
```

Then either skip the venv entirely, or make one that can see them:

```bash
python3 -m venv --system-site-packages venv
```

---

## 4. Check the bundle before deploying

```bash
venv/bin/python selftest.py
```

It confirms the reference loads, the windows resolve to the values the PC froze
with, and a check runs — before you discover a problem in the field.

Add `--source /dev/video0` to also test the real camera.

---

## 4b. Check it still agrees with itself

`selftest.py` proves the bundle is *sound*. To prove it still *computes the same
numbers* — after a library upgrade, a rebuilt reference, or a copy between
machines — replay a clip against recorded verdicts:

```bash
venv/bin/python examples/run_testcase.py --bundle . --clip clip.mp4 --record   # once, when built
venv/bin/python examples/run_testcase.py --bundle . --clip clip.mp4            # ever after
```

Exit 0 = unchanged; exit 1 = something moved, and it is not safe to deploy. It
needs a CLIP, not a camera: a live source cannot be replayed, so its verdicts can
never be compared against anything. `--seek` on the daemon is what makes a given
second repeatable.

## 5. Run it

```bash
venv/bin/python drift_daemon.py \
  --landmarks landmarks.npz \
  --source /dev/video0 \
  --interval 30
```

The first line tells you what it is about to do. **Read it:**

```json
{"event":"startup","version":"1.0.0","frame_required":[1920,1080],
 "patch_px":22,"search_px":19,"alert_mrad":3.6079,"confirm_n":3,...}
```

Check `patch_px` and `search_px` against the GUI's reference. If they disagree,
stop — your bundle is wrong and every verdict will be wrong with it.

### Cadence

| Situation | `--interval` |
|---|---|
| validating, watching for a nudge you are making | `10` |
| normal service | `30`–`60` |

Checks cost milliseconds. The camera is the expensive part, not the maths.

---

## 6. Set the threshold

The threshold is an **angle**, so it holds at any distance:

```bash
--alert-mrad 3.6
```

To pick a number, take the ground error you can tolerate and divide by the range
you care about:

```
alert_mrad = 1000 × (tolerable_error_m ÷ range_m)

1 m at 277 m  → 1000 × 1/277  = 3.6 mrad
1 m at 1 km   → 1000 × 1/1000 = 1.0 mrad
5 m at 5 km   → 1000 × 5/5000 = 1.0 mrad
```

Omit the flag and it uses whatever the reference was frozen with.

### Want metres in the output too?

Ask for the ranges you care about — as many as you like:

```bash
--range 200 --range 1000 --range 5000
```

Each line then carries `"ground_err_m":{"200":…,"1000":…,"5000":…}`, every value
labelled with the range it is true at.

### Transients

`--confirm-n` is how many consecutive bad readings are needed before `status`
flips. `3` absorbs a bird landing on the housing or a gust. Raise it if you get
false alarms; lower it if honest alerts arrive too slowly.

---

## 7. Read the output

One JSON object per line on stdout. Alerts only:

```bash
venv/bin/python drift_daemon.py --landmarks landmarks.npz --source /dev/video0 \
  | jq -c 'select(.event=="drift" and .status!="OK")'
```

Log everything, act on alerts — see [`examples/consume.py`](examples/consume.py):

```bash
venv/bin/python drift_daemon.py ... | venv/bin/python examples/consume.py
```

**Alert on `status`, log `state`.** And read [OUTPUT.md](OUTPUT.md) on the known
`status` issue before you wire an alarm to it.

---

## 8. Deploy as a service

Copy [`examples/driftwatch.service`](examples/driftwatch.service) to
`/etc/systemd/system/`, edit the paths, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now driftwatch
journalctl -u driftwatch -f
```

`SupplementaryGroups=video` is **not optional** for a `/dev/video*` source.

---

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `stream is AxB but the reference was frozen at CxD` | The camera profile does not match. Set the camera to the reference's resolution, or freeze a new reference for this profile. Never rescale. |
| `cannot open source` | Device busy (something else holds it), user not in the `video` group, or the stream is down. |
| Everything reads `MOVED` from the very first check | Almost certainly the window-size trap. Compare the `startup` line's `patch_px`/`search_px` against the GUI. Re-export the bundle rather than patching it. |
| Constant `DEGRADED` | Night, fog, or a scene that mostly moves (water, foliage, traffic). It is saying "I cannot tell" — that is not a fault. |
| Alerts fire and clear repeatedly | Either genuine wobble (wind, thermal) — raise `--alert-mrad` to what the structure can hold — or the known `status` issue in [OUTPUT.md](OUTPUT.md). |
| `no_frame` lines | The camera gave nothing: unplugged, busy, or the stream dropped. A service fault, not a verdict. |
| Verdicts disagree with the GUI | Compare `patch_px`/`search_px` first. Then confirm both are looking at the same frame. |

---

## 10. After an alert

The daemon **never repairs the pose** — deliberately. What to do depends on the
state:

| State | Remedy |
|---|---|
| `MOVED` | Re-aim the camera, verify geolocation, then **freeze a new reference** on the PC and re-export. |
| `CHANGED` | Zoom, focus, lens or a shifted mount. Re-aiming will not fix it — re-solve the pose and rebuild the LUT, then freeze again. |
| `DEGRADED` | Wait. If it persists in good conditions, the scene may have changed enough to need a new reference. |

Any reference you replace means a **new bundle** on the field unit. The old
`landmarks.npz` describes a view that no longer exists.
