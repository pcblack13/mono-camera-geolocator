#!/usr/bin/env python3
"""GEO-DRIFT-UPDATE B1 — the field unit's drift watch.

Load a frozen reference, look at the camera on an interval, and print one JSON
object per line to stdout. Nothing else. No LUT, no DEM, no network, no server.

    python3 drift_daemon.py --landmarks landmarks.npz --source /dev/video0

★ WHY THIS FITS ON AN EMBEDDED BOX AT ALL. `check()` needs no terrain model.
  The landmarks carry their own world positions, baked in when the reference was
  frozen on the PC, so the whole payload is ONE npz of a few kilobytes — against
  the 146 MB of a LUT bundle. If this unit also has to turn pixels into lat/lon
  it needs that LUT as well (see `pi_lookup.py` beside it); if it only has to
  know whether the camera moved, this file and the npz are the entire delivery.

★ THE ANGLE IS THE PRODUCT, NOT THE METRES. Ground error is `angle × range` —
  one multiplication. Publishing metres at a range chosen here would bake that
  range into every consumer; publishing the ANGLE lets each one convert to the
  range it actually cares about. So `--alert-mrad` is the threshold (range-free)
  and `--range` is an optional convenience that adds derived metres for as many
  ranges as you like. Nothing here assumes 1 km, or any other distance.

★ STDOUT IS THE PRODUCT TOO. One JSON object per line, flushed on every line, so
  a reader sees each verdict the moment it exists rather than when a 4 KB buffer
  happens to fill. Diagnostics go to stderr, so `... | jq` never chokes.

★ ALERT ON `status`, LOG `state` (the vendored README's rule). Both are on every
  line. A missed look is `event:"no_frame"` — a service fault, never a verdict:
  reporting a camera as steady because nobody looked is exactly the lie the
  four-state design exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# The monitor itself — shipped alongside this file, not installed from PyPI.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drift_monitor import DriftMonitor  # noqa: E402


#: Bumped when the OUTPUT CONTRACT changes — not for every code edit. A consumer
#: can pin on the major: fields are only ever ADDED within a major version, never
#: renamed or removed, so `1.x` output stays readable by a `1.0` reader.
__version__ = "1.0.0"

_STOP = False


def _stop(_signum: int, _frame: object) -> None:
    """SIGTERM/SIGINT land here so the loop finishes its line before exiting —
    a half-written JSON object is worse than no object."""
    global _STOP
    _STOP = True


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict) -> None:
    """One JSON object, one line, flushed. The whole output contract."""
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), default=float) + "\n")
    sys.stdout.flush()


def note(msg: str) -> None:
    sys.stderr.write(f"[drift-daemon] {msg}\n")
    sys.stderr.flush()


# ─────────────────────────────────────────────────────────────────────────────
# The angles — which way, not just how far
# ─────────────────────────────────────────────────────────────────────────────


def axis_angles(mon: DriftMonitor, r_now: object) -> dict | None:
    """`R_now·R_refᵀ` as a rotation VECTOR: rotations about the camera's own
    right / down / forward axes.

    Order-free (no Euler convention to argue about) and its norm is exactly the
    `rot_deg` the monitor reports, so the parts can never disagree with the
    whole. Mirrors `_axis_angles` in the app's drift_service — same maths, same
    signs, so the GUI and the field unit never tell different stories.
    """
    if r_now is None:
        return None
    import cv2

    r_rel = np.asarray(r_now, float) @ np.asarray(mon.R_ref, float).T
    tilt, pan, roll = (float(np.degrees(a)) for a in cv2.Rodrigues(r_rel)[0].reshape(3))
    return {
        "tilt_deg": round(tilt, 4),
        "pan_deg": round(pan, 4),
        "roll_deg": round(roll, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Capture
# ─────────────────────────────────────────────────────────────────────────────


def open_capture(source: str):
    """A device index ("0"), a device path (/dev/video0), or a URL (rtsp://…)."""
    import cv2

    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(
            f"cannot open source {source!r}. A device needs its user in the "
            f"'video' group; a URL needs the stream to be up."
        )
    return cap


def main(argv: list[str] | None = None) -> int:
    import cv2  # noqa: PLC0415 — kept local, like open_capture's
    ap = argparse.ArgumentParser(
        prog="drift_daemon.py",
        description="Watch a fixed camera for drift; one JSON line per check on stdout.",
    )
    ap.add_argument("--landmarks", required=True, help="the frozen reference (landmarks.npz)")
    ap.add_argument("--source", required=True, help="/dev/video0 · 0 · rtsp://… · http://…")
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between checks")
    ap.add_argument(
        "--alert-mrad",
        type=float,
        default=None,
        help=(
            "alert above this much rotation, in milliradians — RANGE-FREE. "
            "Default: whatever the reference was frozen with."
        ),
    )
    ap.add_argument(
        "--range",
        type=float,
        action="append",
        default=None,
        metavar="M",
        help=(
            "also report ground error in metres at this range; repeatable, so "
            "one daemon can serve 200 m and 5 km at once. Omit for angle only."
        ),
    )
    ap.add_argument("--confirm-n", type=int, default=None, help="override the temporal filter")
    ap.add_argument(
        "--search",
        type=int,
        default=None,
        help=(
            "search half-window, px. Default: the same width-scaled rule the app "
            "froze with. Only set this if the GUI reports a different search_px."
        ),
    )
    ap.add_argument("--once", action="store_true", help="one check, then exit (for testing)")
    ap.add_argument(
        "--seek",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "FILE SOURCES ONLY: judge the frame at this second instead of reading "
            "from the start. What makes a clip repeatable, and therefore what makes "
            "a regression fixture possible — see examples/run_testcase.py."
        ),
    )
    ap.add_argument("--version", action="version", version=f"drift_daemon {__version__}")
    args = ap.parse_args(argv)

    npz = Path(args.landmarks).expanduser()
    if not npz.is_file():
        raise SystemExit(f"no reference at {npz}")

    mon = DriftMonitor.load(str(npz))
    if args.confirm_n is not None:
        mon.confirm_n = int(args.confirm_n)

    # ★ RESTATE THE WINDOW SIZES, OR EVERY VERDICT IS WRONG. `PATCH`/`SEARCH`
    #   are class attributes whose defaults (48/40) were validated on a 4032-wide
    #   frame; they are TUNING, and `load()` does not restore the values the
    #   reference was actually frozen with. Leave them and a 1920-wide reference
    #   judged against its OWN frozen frame reports ~0.74° of rotation that never
    #   happened — the field unit would disagree with the GUI on identical
    #   pictures, and disagree in the alarming direction.
    #
    #   PATCH is recovered EXACTLY: the stored templates are (n, PATCH, PATCH),
    #   so the array's own shape is the authority, not a recomputation.
    #   SEARCH is not derivable from the npz, so it follows the same rule the app
    #   uses (`_window_sizes` in drift_service): 40 px at 4032, scaled linearly,
    #   floored at 12 so NCC stays meaningful.
    #
    #   Best of all is not to guess: an export from the GUI drops a
    #   `field_unit.json` beside the npz carrying the exact `search_px` the
    #   reference was frozen with. Read it when it is there; fall back to the
    #   rule when someone hand-copies a bare npz.
    mon.PATCH = int(np.asarray(mon.landmarks[0]["template"]).shape[-1])
    sidecar = npz.with_name("field_unit.json")
    side = {}
    if sidecar.is_file():
        try:
            side = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            note(f"ignoring unreadable {sidecar.name}: {exc}")
    if args.search is not None:
        mon.SEARCH = int(args.search)
    elif side.get("search_px"):
        mon.SEARCH = int(side["search_px"])
    else:
        mon.SEARCH = max(12, int(round(40 * (int(mon.frame_shape[1]) / 4032.0))))

    # ★ THE THRESHOLD, STATED AS AN ANGLE. The vendor holds it as
    #   `alert_ground_m` at `ref_range`, i.e. an angle in disguise
    #   (`rad = m / range`). Setting the pair from a mrad figure makes the angle
    #   the thing the operator actually chose, and keeps `ref_range` free to be
    #   whatever the reference was frozen at — it no longer defines the alarm.
    if args.alert_mrad is not None:
        mon.alert_ground_m = float(args.alert_mrad) / 1000.0 * float(mon.ref_range)
    alert_mrad = float(mon.alert_ground_m) / float(mon.ref_range) * 1000.0

    fh, fw = (int(x) for x in mon.frame_shape)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    emit(
        {
            "event": "startup",
            "ts": _utc(),
            "version": __version__,
            "reference": str(npz),
            "n_landmarks": len(mon.landmarks),
            "frame_required": [fw, fh],
            "alert_mrad": round(alert_mrad, 4),
            # auditable: these MUST match the GUI's patch_px/search_px for the
            # field unit and the PC to agree on the same picture
            "patch_px": int(mon.PATCH),
            "search_px": int(mon.SEARCH),
            "confirm_n": mon.confirm_n,
            "interval_s": args.interval,
            "ranges_m": args.range or [],
        }
    )
    note(f"watching {args.source} every {args.interval}s; frames must be {fw}x{fh}")

    cap = open_capture(args.source)
    seq = 0
    try:
        while not _STOP:
            started = time.monotonic()
            seq += 1
            # ★ Seek before every read, not once: --once exits after one frame,
            #   and a loop over a clip would otherwise walk away from the second
            #   that was asked for.
            if args.seek is not None:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(args.seek) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                # ★ A missed look is NOT a verdict. Say so and move on.
                emit({"event": "no_frame", "ts": _utc(), "seq": seq})
                if args.once:
                    return 1
                _sleep_until(started + args.interval)
                continue

            got_h, got_w = frame.shape[:2]
            if (got_w, got_h) != (fw, fh):
                # ★ FRAME SIZE IS A CONTRACT — the templates were cut at the
                #   freeze resolution and compare pixel positions. Refuse loudly
                #   rather than silently judging a rescaled picture.
                emit(
                    {
                        "event": "error",
                        "ts": _utc(),
                        "seq": seq,
                        "why": (
                            f"stream is {got_w}x{got_h} but the reference was frozen at "
                            f"{fw}x{fh}. Match the camera profile, or freeze a new "
                            f"reference for this one."
                        ),
                    }
                )
                return 2

            v = dict(mon.check(frame))
            r_now = v.pop("R_now", None)
            ang = axis_angles(mon, r_now)
            rot_deg = v.get("rot_deg")
            rot_mrad = None if rot_deg is None else np.radians(rot_deg) * 1000.0

            line = {
                "event": "drift",
                "ts": _utc(),
                "seq": seq,
                # alert on this
                "status": v.get("status"),
                # log this
                "state": v.get("state"),
                "confirmed": bool(v.get("confirmed")),
                "rot_deg": rot_deg,
                "rot_mrad": None if rot_mrad is None else round(float(rot_mrad), 4),
                "alert_mrad": round(alert_mrad, 4),
                "pan_deg": None if ang is None else ang["pan_deg"],
                "tilt_deg": None if ang is None else ang["tilt_deg"],
                "roll_deg": None if ang is None else ang["roll_deg"],
                "resid_mean_px": v.get("resid_mean_px"),
                "snr": v.get("snr"),
                "mean_conf": v.get("mean_conf"),
                "n_matched": v.get("n_matched"),
                "n_lost": v.get("n_lost"),
                "why": v.get("why"),
            }
            # ★ Derived only if asked for, and always labelled with its range so
            #   a number can never be read at the wrong distance.
            if args.range and rot_mrad is not None:
                line["ground_err_m"] = {
                    f"{r:g}": round(float(rot_mrad) / 1000.0 * float(r), 4) for r in args.range
                }
            emit(line)

            if args.once:
                return 0
            _sleep_until(started + args.interval)
    finally:
        cap.release()
        note("stopped")
    return 0


def _sleep_until(deadline: float) -> None:
    """Sleep in short slices so a SIGTERM is answered promptly, not one whole
    interval later."""
    while not _STOP and time.monotonic() < deadline:
        time.sleep(min(0.25, deadline - time.monotonic()))


if __name__ == "__main__":
    raise SystemExit(main())
