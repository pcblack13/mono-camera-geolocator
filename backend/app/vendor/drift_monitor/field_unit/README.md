# Drift watch — field unit

> **GEO-DRIFT-UPDATE B1/B2.** The embedded half of the camera drift monitor.
> Standalone: it needs nothing from the geolocator at run time.

A fixed camera that has quietly moved keeps reporting confident coordinates that
are now wrong — nothing crashes, no error appears. This watches for that on the
device itself, with no PC, no network and no terrain data, and prints one JSON
line per check.

```
{"event":"drift","status":"OK","state":"OK","rot_deg":0.0008,"rot_mrad":0.013,
 "pan_deg":-0.0004,"tilt_deg":0.0002,"roll_deg":-0.0006,"n_lost":0,...}
```

---

## Start here

| I want to… | Read |
|---|---|
| see what goes in and what comes out | **[examples/EXAMPLE.md](examples/EXAMPLE.md)** — a real run |
| install and run it | **[GUIDE.md](GUIDE.md)** |
| check a bundle still computes what it did | `examples/run_testcase.py` |
| write software that consumes it | **[OUTPUT.md](OUTPUT.md)** — the contract |
| understand or modify the code | **[BRIEF.md](BRIEF.md)** |
| check a bundle is sound | `python3 selftest.py` |

---

## Quickstart

```bash
unzip field-unit.zip -d /opt/driftwatch && cd /opt/driftwatch
python3 -m venv venv
venv/bin/pip install -r requirements-embedded.txt
venv/bin/python selftest.py                     # verify before deploying
venv/bin/python drift_daemon.py \
  --landmarks landmarks.npz --source /dev/video0 --interval 30
```

On a Raspberry Pi use `sudo apt install python3-numpy python3-opencv` instead of
pip — building either from source takes hours. See [GUIDE.md](GUIDE.md) § 3.

---

## In / out at a glance

**In:** a reference file (`landmarks.npz`, ~9 KB) and a camera. Nothing else —
no map, no DEM, no lookup table, no internet.

**Out:** one JSON object per line on stdout, one per check.

- **`status`** — the alarm: `OK` · `MOVED` (re-aim it) · `CHANGED` (zoom/lens —
  needs a full re-solve) · `DEGRADED` (fog/night — *cannot tell*, not an alarm)
- **`rot_deg` / `rot_mrad`** — how far it moved
- **`pan` / `tilt` / `roll`** — which way, so you know how to turn it back

Full field list, types, nulls and exit codes: [OUTPUT.md](OUTPUT.md).

### Distance is yours to choose

The daemon reports the **angle**, because ground error is `angle × range` and
the same tilt is 1 m of error at 250 m but 4 m at 1 km. The threshold is
range-free:

```bash
--alert-mrad 3.6
```

If you want metres, name the ranges you care about — as many as you like:

```bash
--range 200 --range 1000 --range 5000
```

**Nothing anywhere assumes 1 km, or any other distance.**

---

## Why it is this small

`check()` needs no terrain model: each landmark's real-world position was
resolved once, on the PC, when the reference was frozen.

| | |
|---|---|
| `landmarks.npz` | ~9 KB |
| Whole bundle, code + docs + frozen frame | ~370 KB |
| A LUT bundle, for comparison | 146 MB |

Per check: 12 template matches plus one 3×3 SVD — **milliseconds, single
threaded, no GPU**. Two dependencies, `numpy` and `opencv-python-headless`.

If the unit must also turn **pixels into lat/lon**, that is a different job
needing the LUT bundle and `pi_lookup.py`. This one answers only *"has the
camera moved?"* — which is what tells you whether to trust that LUT at all.

---

## What is in the bundle

| File | |
|---|---|
| `landmarks.npz` | the frozen reference — this camera, this view |
| `field_unit.json` | settings that keep the unit identical to the PC — ship it; see [BRIEF.md](BRIEF.md) § *The window-size trap* |
| `reference.jpg` | the frozen frame, so `selftest.py` can verify offline |
| `drift_monitor.py` | the engine, byte-identical to `core/drift_monitor/` |
| `drift_daemon.py` | the loop and the JSON contract |
| `selftest.py` | pre-deployment check |
| `examples/EXAMPLE.md` | a worked example: the inputs, the command, the output |
| `examples/sample-output.jsonl` | that run, verbatim — startup plus three verdicts |
| `examples/consume.py` | a consumer that acts on confirmed alerts |
| `examples/run_testcase.py` | replay a clip and check the bundle still agrees with itself |
| `examples/driftwatch.service` | systemd unit |
| `*.md` | this, the guide, the contract, the brief |

---

## Two things to know before you trust it

**It measures change, never correctness.** If the mapping was already wrong when
the reference was frozen, this reports `OK` forever. Freeze only after verifying
geolocation, and pair it with an absolute check.

**Validation to date is synthetic.** The geometry was proven against exact
homography warps of one photograph. It has **not** been tested on two real frames
of the same scene taken hours apart, where lighting, shadows and sensor noise all
shift together. Run `docs/guides/drift-validation.md` Part B on your camera
before relying on it. Full list in [BRIEF.md](BRIEF.md) § *Limits*.

---

## Provenance

The engine is unmodified. Verified: `core/drift_monitor/drift_monitor.py`, the
app's vendored copy, and the copy in this bundle are byte-identical, and over 60
frames this bundle produced **verdicts identical on all 11 fields** to the
original engine and to the GUI (`rot_deg` difference: `0.0`).

**Fix bugs in `core/drift_monitor/`, not in a copy.** The app and this bundle
both carry verbatim copies; re-copy after a change, then re-run the equivalence
check.
