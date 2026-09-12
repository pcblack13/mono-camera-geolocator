# Code brief — drift watch field unit

For a developer taking this over. What it does, how it is put together, and the
decisions that are load-bearing. Read [OUTPUT.md](OUTPUT.md) for the contract
and [GUIDE.md](GUIDE.md) to run it.

---

## The problem

A fixed camera with a frozen pixel→world mapping is only correct while it does
not move. When something nudges it — wind, a knock, thermal creep, someone
leaning on the mast — **nothing crashes and no error appears.** The system keeps
reporting confident coordinates that are now wrong. That silent failure is what
this watches for.

## The idea

Freeze, while the aim is trusted, a set of landmarks: small image patches of
static things on the ground, each tagged with where it really is in the world.
Later, find those patches again and ask a single question: *is there one rigid
camera rotation that explains where they all ended up?*

- **Yes, and it is small** → `OK`
- **Yes, and it is large** → `MOVED` — the mount turned
- **No single rotation fits** → `CHANGED` — zoom, focus, lens, or the camera was
  physically shifted
- **Too few landmarks found** → `DEGRADED` — cannot judge

`CHANGED` is the state that earns its keep. A zoom or focal change breaks the
mapping completely while producing **almost zero rotation**. An earlier version
fitted rotation, found ≈0°, and reported `OK` on a camera whose geolocation was
entirely invalid — the most dangerous possible answer. The tell is that the
landmarks disagree *with each other*: a true rotation explains every landmark to
well under a pixel, while a zoom leaves several pixels of irreducible scatter.
That ratio is `snr`.

## Why it fits on an embedded box

`check()` needs **no DEM, no LUT, no terrain model** — the landmarks carry their
world positions, resolved once at freeze time on the PC.

| | |
|---|---|
| Reference (`landmarks.npz`) | ~9 KB |
| Whole delivery incl. code and docs | ~25 KB zipped |
| A LUT bundle, for comparison | 146 MB |

Work per check: 12 template matches over a bounded search window, plus one 3×3
SVD. **Milliseconds, single-threaded, no GPU.**

---

## File map

| File | Role |
|---|---|
| `drift_monitor.py` | **The engine. Do not edit here.** A verbatim copy of `core/drift_monitor/drift_monitor.py`; all the geometry lives in it |
| `drift_daemon.py` | The only code that is specific to the field unit: argument handling, camera capture, the interval loop, and the JSON contract |
| `field_unit.json` | Per-reference settings written by the PC export |
| `selftest.py` | Verifies a bundle before you deploy it |
| `examples/` | A consumer and a systemd unit |

The split matters: **a fix to the maths belongs in the core**, and reaches the
field unit by re-copying. The daemon deliberately holds no geometry beyond the
angle decomposition, which is a presentation concern.

## Flow

```
load npz ──► restore PATCH/SEARCH ──► set threshold from --alert-mrad
                                              │
        ┌─────────────────────────────────────┘
        ▼
   grab frame ──► size == reference?  ──no──► emit error, exit 2
        │                 yes
        ▼
   mon.check(frame)   (12 template matches, fit rotation, cull outliers, refit)
        │
        ├──► axis_angles(R_now)   pan / tilt / roll
        ├──► derived metres, per --range
        ▼
   emit one JSON line ──► sleep to the next interval
```

---

## Decisions that are load-bearing

### The window-size trap

**This is the one thing most likely to bite you.**

`PATCH` (template side) and `SEARCH` (search half-window) are *class attributes*
on `DriftMonitor`, defaulting to 48/40. Those were validated on a **4032-pixel-wide**
frame. The PC scales them to the reference's own width when freezing — 22/19 at
1920 wide — but:

- **`DriftMonitor.load()` does not restore them**, and
- **they are not stored inside the `.npz`.**

Load a 1920-wide reference and leave the defaults, and it reports **~0.74° of
rotation that never happened — against its own frozen frame.** Measured: all
60 of 60 test frames were wrong, steady ones reported as `MOVED`.

**`PATCH` is the one that does the damage, and `SEARCH` is not involved.**
Measured on the frozen frame judged against itself:

| `PATCH` | `SEARCH` | verdict |
|---|---|---|
| 22 | 19 | `OK` 0.00075° |
| 22 | 40 | `OK` 0.00075° |
| **48** | 19 | **`MOVED` 0.73532°** |
| **48** | 40 | **`MOVED` 0.73532°** |

The reason is structural: the stored templates *are* 22×22, so a `PATCH` of 48
compares the wrong-sized thing. `SEARCH` only sets how far out it looks for a
landmark — a wrong value costs robustness and a little time, not correctness on
a static frame.

So the defence is structural too: **`PATCH` is recovered exactly from the stored
template's own shape** (`landmarks[0]["template"].shape[-1]`). The array is the
authority, not a recomputation or a sidecar, which means the trap stays closed
even for a hand-copied bare npz.

`SEARCH` is not derivable from the npz, so it is read from `field_unit.json`,
falling back to the app's own width rule (`max(12, round(40 × width/4032))`).
Ship the sidecar so the unit and the PC match exactly — but a missing one is a
warning, not a broken bundle.

Both values are echoed in the `startup` line so a bundle can be audited against
the GUI.

### The angle is the product, not the metres

Ground error is `angle × range` — one multiplication. Publishing metres at a
range chosen here would bake that range into every downstream consumer forever.
So the daemon publishes the **angle**, `--alert-mrad` is the threshold, and
`--range` is an optional convenience that can serve several ranges at once, each
labelled. **Nothing assumes 1 km, or any distance.**

### Alert on `status`, log `state`

`state` is this frame's raw reading. `status` only flips after `confirm_n`
consecutive identical bad readings — which kills transients (a bird on the
housing, a gust, an autofocus hunt). `OK` takes effect immediately: being quick
to trust again is safe, being quick to alarm is not.

> ⚠️ **Known open issue.** In a 60-check sweep on the PC, `status` came back `OK`
> on 15 frames whose raw `state` was `MOVED`, contradicting the documented latch.
> Reading the engine's `_finish()` does not explain it, and it predates this
> daemon. **Both fields are published on every line** so the discrepancy stays
> visible. If you alert on `status` alone you may see an alarm clear and re-fire
> while the camera is still moved — consider alerting on a short window of
> `state` as well.

### A missed look is not a verdict

`no_frame` is its own event. Reporting a camera steady because nobody looked is
the same lie the four states exist to prevent.

### Frame size is refused, never rescaled

The templates compare pixel positions. A same-aspect rescale would need `K`
restated and the windows re-derived; a different aspect is a crop or another
stream profile and no restatement makes the mapping true. Refusing (exit 2) is
the honest answer.

### It never repairs the pose

The monitor computes a perfectly good corrected rotation and deliberately does
not apply it. Adopting it would create a feedback loop — the reference
re-anchoring to landmarks derived from itself, drifting freely with nothing
holding it. **Detect, report, let a human or an absolute check decide.**

---

## Modifying it safely

| You want to… | Do this |
|---|---|
| change the maths | edit `core/drift_monitor/drift_monitor.py`, re-copy to the vendored locations, re-run the equivalence test |
| add an output field | **add only** — never rename or remove within a major; bump the minor in `__version__`; update `OUTPUT.md` |
| change an output field's meaning or unit | bump the **major**; that breaks every consumer |
| add a transport (MQTT, HTTP, serial) | keep stdout NDJSON as the source of truth and tee from it — do not replace it |
| tune matching | `PATCH`/`SEARCH`/`MIN_CONF`/`MIN_SNR` are class attributes; **anything affecting matching must also change at freeze time**, or the unit and the PC will disagree |

## Verifying a change

`selftest.py` checks a bundle end to end on this machine. Beyond that, the
strongest check is differential: run the original engine and the bundle over the
same frames in the same order and compare every verdict field. The current build
passes at **60/60 frames identical on all 11 fields**, and matches the GUI to
`0.0` difference in `rot_deg`.

---

## Limits — do not let a quiet log fool you

1. **It measures change, never correctness.** If the mapping was already wrong
   when frozen, this reports `OK` forever. Pair it with an absolute check
   (surveyed points, or matching against satellite imagery).
2. **Digital stabilisation is indistinguishable from a small pan/tilt.** Reported
   as `MOVED`, which is the right verdict even though the cause label is wrong.
   Disable stabilisation on the camera.
3. **Camera translation is detected but not named** — it inflates the residual
   and surfaces as `CHANGED`.
4. **The scene must be mostly static.** Water, foliage in wind, or a busy road
   will be culled as outliers; a scene where most of the frame moves cannot be
   monitored this way.
5. **Validation to date is synthetic** — exact homography warps of one real
   photograph. It has **not** been tested on two real frames of the same scene
   taken hours apart, where lighting, shadows and sensor noise all shift
   together. Do that before relying on it in the field.
