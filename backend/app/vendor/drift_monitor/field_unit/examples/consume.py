#!/usr/bin/env python3
"""Minimal consumer for the drift watch stream — copy this and edit `on_alert`.

    drift_daemon.py --landmarks landmarks.npz --source /dev/video0 | consume.py

Reads NDJSON on stdin, logs every line, and calls a handler when the camera is
confirmed to have moved. Standard library only — nothing to install.

★ WHY A SEPARATE PROCESS. The daemon's only job is to judge frames; what to DO
  about a verdict (raise a ticket, flip a flag, page someone, stop publishing
  coordinates) is site-specific and changes far more often than the maths. A
  pipe keeps the two apart, so you can restart or rewrite this half without
  touching a monitor that is working.
"""

import json
import sys


def on_alert(v: dict) -> None:
    """The camera is confirmed to have moved. Put your action here.

    ★ `MOVED` and `CHANGED` both mean STOP TRUSTING THE COORDINATES. They are
      separate because the remedy differs: `MOVED` needs a re-aim, `CHANGED`
      needs a full re-solve — re-aiming will not fix a zoom.
    """
    print(
        f"!! {v['status']}  {v['rot_deg']:.3f}deg "
        f"(pan {v['pan_deg']:+.3f} tilt {v['tilt_deg']:+.3f} roll {v['roll_deg']:+.3f})\n"
        f"   {v['why']}",
        file=sys.stderr,
        flush=True,
    )
    # e.g. mark_coordinates_untrusted(v["why"]) / notify() / set_gpio(ALARM, 1)


def on_recovered() -> None:
    """Back to OK after an alert — a human re-aimed it, or it was transient."""
    print("-- steady again", file=sys.stderr, flush=True)


def main() -> int:
    alerting = False
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            v = json.loads(raw)
        except ValueError:
            # ★ Never die on one malformed line — a monitor that stops watching
            #   because of a parse error is worse than one that skips a reading.
            print(f"?? unparseable: {raw[:120]}", file=sys.stderr, flush=True)
            continue

        event = v.get("event")

        if event == "startup":
            print(
                f"-- watching: {v['n_landmarks']} landmarks, frames "
                f"{v['frame_required'][0]}x{v['frame_required'][1]}, "
                f"alert above {v['alert_mrad']} mrad "
                f"(patch {v['patch_px']} / search {v['search_px']})",
                file=sys.stderr,
                flush=True,
            )
            continue

        if event == "no_frame":
            # ★ A missed look is a SERVICE fault, never a verdict. Do not let it
            #   clear an alert, and do not count it as steady.
            print(f"?? no frame (seq {v.get('seq')})", file=sys.stderr, flush=True)
            continue

        if event == "error":
            print(f"!! fatal: {v.get('why')}", file=sys.stderr, flush=True)
            return 2

        if event != "drift":
            continue

        # Alert on `status`, log `state` — see OUTPUT.md.
        status = v.get("status")
        if status in ("MOVED", "CHANGED"):
            if not alerting:
                alerting = True
            on_alert(v)
        elif status == "OK":
            if alerting:
                alerting = False
                on_recovered()
        # `DEGRADED` and null are deliberately neither: the monitor is saying
        # "I cannot tell", which must not clear a standing alert.

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
