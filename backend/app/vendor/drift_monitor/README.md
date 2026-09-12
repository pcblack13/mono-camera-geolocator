# Camera Drift Monitor

Detects that a **fixed camera has moved** — the failure mode that silently
invalidates any frozen pixel→world mapping. Nothing crashes, no error appears;
the system just keeps reporting confident coordinates that are now wrong.

**Standalone and engine-agnostic.** Two dependencies (`numpy`, `opencv-python`),
no imports from any geolocation package. You supply your own pixel→world
function, so it sits on top of *any* engine — PnP, PTZ/affine, a lookup table,
a homography.

```python
from drift_monitor import DriftMonitor
```

---

## The 30-second version

```python
mon = DriftMonitor(K, dist, ref_range=1000.0, alert_ground_m=1.0)

# once, while the mapping is known good
mon.setup(reference_frame, world_of, C, R_ref)
mon.save("landmarks.npz")

# later, forever
mon = DriftMonitor.load("landmarks.npz")
r = mon.check(new_frame)
if r["status"] in ("MOVED", "CHANGED"):
    mark_coordinates_untrusted(r["why"])
```

---

## What you must supply

| Argument | What it is |
|---|---|
| `K` | 3×3 intrinsics of the camera the frames come from |
| `dist` | `[k1,k2,p1,p2,k3]`, or `None` if you don't model distortion |
| `world_of(u, v)` | **your** engine: pixel → `(X, Y, Z)` metric, or `None` if the ray misses |
| `C` | camera position `(X, Y, Z)`, same coordinate frame as `world_of` returns |
| `R_ref` | 3×3 world→camera rotation of the trusted pose (rows = camera right/down/forward axes in world coords) |

`world_of` is called **only during `setup()`**. After that the landmarks carry
their own world positions, so `check()` needs no terrain model, no DEM, no
elevation data — it runs on a field unit that has none.

If your engine doesn't expose `R_ref` as a matrix, build it from heading/tilt/roll
with any standard convention — the monitor only ever compares it against
rotations it derives itself, so a self-consistent convention is enough.

---

## The four states

Collapsing any of these into `OK` is how a monitor lies.

| State | Meaning | What to do |
|---|---|---|
| `OK` | Landmarks matched; any rigid rotation is below threshold | Nothing |
| `MOVED` | **Coherent rotation above threshold** — mount drift | Re-aim, or re-solve the pose |
| `CHANGED` | Landmarks moved but **no rigid rotation explains it** — zoom, focus/focal change, translated mount, swapped lens | Full re-solve; re-aiming won't fix it |
| `DEGRADED` | Too few or too weak matches (fog, night, scene change) | Wait. **Not** an alert — the monitor is saying "I can't tell" |

`MOVED` and `CHANGED` both mean *stop trusting the coordinates*. They're kept
apart because the remedy differs.

### Why `CHANGED` exists

A zoom or focal change breaks the mapping completely while producing **almost
zero rotation**. An earlier version of this code fitted rotation, found ≈0°,
and reported `OK` on a camera whose geolocation was entirely invalid — the most
dangerous possible answer. The tell is that the landmarks disagree with *each
other*: a rigid rotation explains every landmark to well under a pixel, while a
zoom leaves several pixels of irreducible scatter.

Measured on a 4032×2268 frame at f≈2800:

| Injected | Verdict | rotation | residual | SNR |
|---|---|---|---|---|
| Rotation 0.15° | `MOVED` | 0.150° (exact) | 0.38 px | 14.7 |
| Rotation 0.05° | `OK` | 0.048° | 0.36 px | 4.7 |
| **Zoom +0.5%** | **`CHANGED`** | 0.011° | **5.54 px** | **0.1** |
| **Zoom +2%** | **`CHANGED`** | 0.043° | **22.08 px** | **0.1** |
| Image shift 8 px | `MOVED` | 0.146° | 1.01 px | 7.1 |
| Fog | `DEGRADED` | — | — | — |

SNR (claimed shift ÷ landmark disagreement) separates the cases cleanly.

---

## Setting the threshold

State it in **metres of ground error at the range you care about**, not pixels:

```python
DriftMonitor(K, dist, ref_range=1000.0, alert_ground_m=1.0)
```

The conversion the monitor uses internally:

```
ground error ≈ rotation_rad × range
1 px of drift ≈ (1 / f) rad  →  at f=2800, range=1000 m: 0.36 m
```

So ~3 px of coherent shift ≈ 1 m at 1 km. Pick `alert_ground_m` from your
accuracy budget and let the geometry convert it back.

⚠️ On steep terrain viewed at a grazing angle, true ground error is further
amplified by roughly `1/sin(depression angle)`. `ref_range` assumes a
perpendicular-ish view; set `alert_ground_m` tighter if you're looking along
a shallow slope.

---

## Temporal confirmation

`confirm_n=3` (default) requires **three consecutive identical non-OK verdicts**
before `status` changes. This kills transients — a bird on the housing, a gust,
an autofocus hunt, someone walking through frame.

```
frame   raw       status    confirmed
clean   OK        OK        False
BUMP    MOVED     OK        False    ← one-frame transient, suppressed
clean   OK        OK        False
drift   MOVED     OK        False
drift   MOVED     OK        False
drift   MOVED     MOVED     True     ← sustained, promoted
```

`OK` takes effect immediately — being quick to trust again is safe; being quick
to alarm is not. **Alert on `r["status"]`, log `r["state"]`.**

---

## Integration example

```python
import cv2, time
from drift_monitor import DriftMonitor, OK, DEGRADED

mon = DriftMonitor.load("landmarks.npz")
cap = cv2.VideoCapture("rtsp://camera/stream")

last = 0
while True:
    ok, frame = cap.read()
    if not ok:
        continue
    render(frame)                       # your normal pipeline, untouched

    if time.time() - last > 60:         # once a minute is plenty
        last = time.time()
        r = mon.check(frame)            # BGR or grayscale both fine
        publish_status(r["status"], r["why"])
        if r["confirmed"]:
            alert(r["why"])
```

`check()` never modifies your pose or your coordinates — it is read-only by
design. Everything it reports is advisory; **you** decide what to do.

### The verdict dict

| Key | |
|---|---|
| `state` | this frame's raw verdict |
| `status` | confirmed verdict after the temporal filter — **alert on this** |
| `confirmed` | `True` on the frame a non-OK status is promoted |
| `why` | human-readable sentence, safe to show an operator |
| `rot_deg`, `ground_err_at_ref` | magnitude of drift |
| `resid_mean_px`, `snr`, `mean_conf` | evidence quality |
| `n_matched`, `n_inliers`, `n_lost`, `outlier_ids` | landmark bookkeeping |

---

## Performance

N template matches over a bounded window plus one 3×3 SVD — **milliseconds**,
single-threaded, no GPU. Frames must be the **same resolution** as the
reference (it compares pixel positions); `check()` raises if they differ.

Tuning constants are class attributes (`PATCH`, `SEARCH`, `MIN_CONF`,
`MIN_SNR`, …) — subclass or assign to change them. Defaults were validated at
4032×2268, f≈2800; for much smaller frames reduce `PATCH` and `SEARCH`
proportionally.

---

## Limitations — read before trusting it

1. **It measures *change*, never *correctness*.** The landmarks' world
   positions came from your mapping at `setup()`. If that mapping was already
   wrong, this reports `OK` forever. Pair it with an absolute check (surveyed
   points, or matching against satellite imagery); the two cover different
   failure modes and neither covers both.

2. **It never repairs the pose**, though it computes a perfectly good corrected
   rotation. Adopting it would create a feedback loop — the reference would
   re-anchor to landmarks derived from itself and drift freely with nothing
   holding it. Detect, report, let a human or an absolute check decide.

3. **Digital image stabilisation is geometrically indistinguishable** from a
   small pan/tilt. Reported as `MOVED`, which is the right verdict (the mapping
   *is* broken) even though the attributed cause may be wrong.

4. **Camera translation** is detected but not named: a 2 m shift moves near
   landmarks ~2.8× more than far ones, whereas rotation moves all equally. That
   gradient inflates the residual, so it surfaces as `CHANGED`.

5. **The scene must be mostly static.** Landmarks on water, foliage in wind,
   parked vehicles or a busy road will be culled as outliers — fine in small
   numbers, but a scene where most of the frame moves cannot be monitored this
   way.

6. **Validation to date is synthetic** — exact homographies warping one real
   photograph, which is how the geometry was verified against known ground
   truth. It has **not** been tested on two real photographs of the same scene
   taken hours apart, where lighting, shadows and sensor noise all shift
   together. Do that before relying on it in the field.
