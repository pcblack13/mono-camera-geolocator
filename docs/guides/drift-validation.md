# Drift monitor — field validation (Phase 4)

**★ Why this exists:** the drift monitor's geometry is proven synthetically (exact
homography warps, `app/tests/test_drift_service.py`) and against real footage, but
its own README is blunt: *it has not been tested on two real frames of the same
scene taken hours apart*. This runbook is that test. Until it passes on your
camera, treat verdicts as advisory.

---

## What is already proven — do not spend field time on it

| Claim | Evidence |
|---|---|
| 0.3° nudge → `MOVED`, solved to ±0.001° | synthetic warp tests; real 1080p footage |
| Zoom/focal change → `CHANGED`, not `OK` | synthetic zoom tests (the dangerous case) |
| Global lighting shifts do **not** false-alarm | γ 0.6–2.2, ±45 % exposure, ISO noise on a real frame → all `OK`, conf ≥ 0.95 |
| True night → `DEGRADED` ("cannot judge"), not an alarm | signal-below-noise test |
| One transient never fires the alert | `confirm_n` temporal filter tests |

**What only the field can prove:** shadows *crawling across the landmarks* as the
sun moves (a local change, unlike a global lighting shift), scene changes
(parked vehicles, vegetation), wind/thermal motion of the real mount, and your
camera's own auto-exposure/focus behaviour.

---

## Part A — the nudge test (the ticket's DONE-WHEN)

1. Aim the camera; build/choose its LUT; confirm geolocation is currently good.
2. Live stream page → apply the LUT → **Freeze reference**. Expect the strip to
   report ~12 landmarks; a "too featureless" refusal means the view needs more
   textured static ground.
3. Press **Watch** with a **10 s** interval (validation only — 30–60 s in service).
4. Let it sit 2 minutes. Expected: solid-green **Camera steady**, rotation ≤ a
   few hundredths of a degree.
5. **Tap the mount once** (a knock, not a re-aim). Expected: at most one dashed
   `MOVED…` reading, then back to steady — the confirm filter absorbing a transient.
6. **Nudge the mount for real** (loosen/turn a fraction of a degree). Expected:
   three consecutive checks later the pill goes dashed **Camera moved**
   (confirmed) and the amber banner appears over the map with the rotation and
   metres named. *This is the pass.*
7. If you can: touch the **zoom or focus** instead. Expected: double-border red
   **Optics changed** — not `OK` (that would be the dangerous failure) and not `MOVED`.
8. Recover: re-aim properly, verify geolocation, press **Re-freeze**. Steady again.

**Fail conditions:** the nudge never confirms (threshold too loose → lower
`alert_ground_m`, or the nudge was smaller than your accuracy budget cares
about); or `OK` after a zoom change (report immediately — that is the failure
mode the CHANGED state exists to prevent).

## Part B — the lighting soak (a full day)

1. Morning: freeze a fresh reference, **Watch** at **60 s**. Do not touch the
   camera all day. Keep the app running (monitor state is in memory; the log
   survives restarts but the loop must be restarted by hand).
2. Evening (or next morning, to include night): read the report:

```bash
curl -s http://127.0.0.1:8000/api/v1/drift/references/<ref_id>/report | python3 -m json.tool
```

(`ref_id` from `GET /api/v1/drift/references`, or Swagger at `/docs` → drift.)

### Reading the report — pass criteria

- **`confirmed_alerts` is empty**, or every entry has a physical explanation you
  can name (someone bumped it, the mount was adjusted). An unexplained confirmed
  `MOVED`/`CHANGED` in calm conditions = a false alarm; note its hour.
- **`hourly`**: `DEGRADED` rows line up with night/fog only. A `MOVED`/`CHANGED`
  bump shaped like sunrise or sunset = shadow crawl across a landmark —
  re-freeze with landmarks on shadow-free structure, or raise `confirm_n`.
- **`rot_ok_p95_deg`** well under the alert angle (`alert_ground_m / ref_range_m`
  in radians). If p95 crowds the threshold, the mount genuinely wobbles (wind,
  thermal) — raise `alert_ground_m` to what the structure can hold.
- **`episodes`**: brief (1–2 check) non-OK runs that never confirmed are the
  filter doing its job; long ones deserve an explanation.
- **`no_frame`** counts looks that got no picture (device busy, unplugged) — a
  service problem, never a verdict.

## Knobs (all set at freeze / watch time)

| Knob | Default | Change it when |
|---|---|---|
| `alert_ground_m` | 1.0 m | your accuracy budget is tighter/looser at `ref_range_m` |
| `ref_range_m` | median landmark range | you care about a specific working distance |
| `confirm_n` | 3 | false alarms from short transients → raise; slow honest alerts → lower |
| interval | 30 s | validation 10 s; service 30–60 s (checks cost milliseconds; the camera does not) |

## Standing limitations (by design — re-read before trusting a quiet report)

- The monitor measures **change, not correctness**: a reference frozen on a bad
  mapping reports `OK` forever. Freeze only after verifying geolocation.
- Digital stabilisation reads as `MOVED` (the mapping *is* broken; the cause
  label is wrong). Disable stabilisation on the camera if it has it.
- A mostly-moving scene (water, foliage, traffic) cannot be monitored this way —
  expect the freeze to refuse or the day to be `DEGRADED`-heavy.
- It never repairs the pose; after any confirmed alert the remedy is human:
  re-aim + re-freeze (`MOVED`) or re-solve/rebuild the LUT (`CHANGED`).
