#!/usr/bin/env python3
"""GEO-DRIFT-UPDATE B3 — run a bundle against a clip and check it still agrees.

    python3 examples/run_testcase.py --record     # write expected.json
    python3 examples/run_testcase.py              # check against it

★ WHAT THIS IS FOR. A field unit is judged on a mast, offline, weeks after
  anyone looked at it. Before it goes out you want to know that THIS bundle on
  THIS machine produces the numbers it produced when it was built — a different
  OpenCV, a different numpy, a rebuilt reference, a half-copied npz all change
  the answer quietly. Recording a handful of verdicts and re-checking them is
  the cheapest way to catch that.

★ IT IS A REGRESSION CHECK, NOT AN ACCURACY CHECK. It proves the code still
  computes what it computed, not that what it computes is true. Accuracy comes
  from the field-validation runbook, and from the fact that the reference was
  frozen on a mapping someone had verified.

★ A CLIP IS USED DELIBERATELY. A live camera cannot be replayed, so its verdicts
  can never be compared against anything. A stored clip gives the same frames
  every time, which is what makes a fixture possible at all — and the drift
  monitor's own frame-size contract means the clip must match the reference's
  resolution, so this doubles as a check that the bundle and the footage belong
  together.

Layout it expects (the folder this script is run from, or --bundle):

    bundle/landmarks.npz, drift_daemon.py, drift_monitor.py, field_unit.json
    clip.mp4                (or --clip)
    expected.json           (written by --record)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: Verdicts drift a little with library versions; these are the tolerances a
#: PASS is allowed. Tight enough that a wrong reference or a half-copied npz
#: fails loudly, loose enough that a numpy point release does not.
TOL_DEG = 0.02
TOL_PX = 0.5


def run_at(bundle: Path, clip: Path, second: float, python: str) -> dict:
    """One check at one second, straight through the daemon's own CLI."""
    out = subprocess.run(
        [python, str(bundle / "drift_daemon.py"),
         "--landmarks", str(bundle / "landmarks.npz"),
         "--source", str(clip), "--once", "--seek", str(second)],
        capture_output=True, text=True, timeout=300,
    )
    for line in out.stdout.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("event") == "drift":
            return rec
        if rec.get("event") == "error":
            raise SystemExit(f"  daemon refused at {second}s: {rec.get('why')}")
    raise SystemExit(f"  no verdict at {second}s.\n{out.stdout[-500:]}\n{out.stderr[-500:]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent.parent
    ap.add_argument("--bundle", default=str(here), help="folder holding the daemon and the npz")
    ap.add_argument("--clip", default=None, help="the video to replay (default: clip.mp4 beside it)")
    ap.add_argument("--expected", default=None, help="default: expected.json beside the clip")
    ap.add_argument("--seconds", default="1,5,20,38,55",
                    help="which seconds to judge (comma separated)")
    ap.add_argument("--record", action="store_true", help="write expected.json instead of checking")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)

    bundle = Path(a.bundle).resolve()
    root = bundle.parent if (bundle / "landmarks.npz").is_file() else bundle
    clip = Path(a.clip) if a.clip else root / "clip.mp4"
    expected = Path(a.expected) if a.expected else root / "expected.json"
    if not (bundle / "landmarks.npz").is_file():
        raise SystemExit(f"no landmarks.npz under {bundle}")
    if not clip.is_file():
        raise SystemExit(f"no clip at {clip} — pass --clip")

    seconds = [float(s) for s in a.seconds.split(",") if s.strip()]
    got = {f"{s:g}": run_at(bundle, clip, s, a.python) for s in seconds}

    if a.record:
        keep = ("state", "rot_deg", "pan_deg", "tilt_deg", "roll_deg",
                "resid_mean_px", "n_matched", "n_lost")
        expected.write_text(json.dumps(
            {k: {f: v.get(f) for f in keep} for k, v in got.items()}, indent=2))
        print(f"  recorded {len(got)} verdicts -> {expected}")
        for k, v in got.items():
            print(f"    {k:>4}s  {v['state']:9s} rot {v['rot_deg']:.5f} deg")
        return 0

    if not expected.is_file():
        raise SystemExit(f"no {expected} — run with --record first")
    want = json.loads(expected.read_text())

    bad = []
    print(f"  {'sec':>5} {'state':>10} {'rot_deg':>22} {'resid_px':>18}")
    for k, exp in want.items():
        v = got.get(k)
        if v is None:
            bad.append(f"{k}s: not run"); continue
        d_rot = abs((v["rot_deg"] or 0) - (exp["rot_deg"] or 0))
        d_res = abs((v["resid_mean_px"] or 0) - (exp["resid_mean_px"] or 0))
        ok = v["state"] == exp["state"] and d_rot <= TOL_DEG and d_res <= TOL_PX
        print(f"  {k:>5} {v['state']:>10} {v['rot_deg']:>10.5f} vs {exp['rot_deg']:<9.5f} "
              f"{v['resid_mean_px']:>8.3f} vs {exp['resid_mean_px']:<7.3f}  {'ok' if ok else 'FAIL'}")
        if not ok:
            bad.append(f"{k}s: state {v['state']} vs {exp['state']}, "
                       f"rot d={d_rot:.5f}, resid d={d_res:.3f}")

    print()
    if bad:
        print(f"  FAIL — {len(bad)} of {len(want)} verdicts moved:")
        for b in bad:
            print(f"    {b}")
        print("\n  A bundle that no longer agrees with itself is not safe to deploy.\n"
              "  Check field_unit.json's patch_px/search_px against the GUI first —\n"
              "  that is the one mismatch that changes every verdict silently.")
        return 1
    print(f"  PASS — all {len(want)} verdicts within tolerance "
          f"({TOL_DEG} deg, {TOL_PX} px).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
