#!/usr/bin/env python3
"""Verify a field-unit bundle BEFORE it goes out — or on the box, before service.

    python3 selftest.py                      # check the bundle
    python3 selftest.py --source /dev/video0 # also check the real camera

★ WHAT THIS IS FOR. The expensive failure is a bundle that looks fine, installs
  fine, and is wrong — most often because `field_unit.json` was left behind and
  the matching windows fell back to the engine's 4032-px defaults. That mistake
  reports a perfectly steady camera as MOVED, and you find out in the field.
  Every check below has actually failed at least once in development.

Exit 0 = safe to deploy. Non-zero = do not deploy; the reason is printed.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
fails: list[str] = []
warns: list[str] = []


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def bad(msg: str, fix: str) -> None:
    print(f"  FAIL  {msg}\n        -> {fix}")
    fails.append(msg)


def warn(msg: str, fix: str) -> None:
    print(f"  warn  {msg}\n        -> {fix}")
    warns.append(msg)


def main(argv: list[str]) -> int:
    source = None
    if "--source" in argv:
        source = argv[argv.index("--source") + 1]

    print("drift watch — bundle self-test")
    print(f"  bundle: {HERE}\n")

    # ── 1. the files ─────────────────────────────────────────────────────────
    print("files")
    for name, required in (
        ("landmarks.npz", True),
        ("drift_monitor.py", True),
        ("drift_daemon.py", True),
        ("field_unit.json", False),
    ):
        if (HERE / name).is_file():
            ok(name)
        elif required:
            bad(f"{name} is missing", "re-export the bundle from the geolocator")
        else:
            warn(
                "field_unit.json is missing — the matching windows must be guessed",
                "re-export the bundle rather than copying landmarks.npz by hand",
            )

    if fails:
        print("\nRESULT: FAIL — cannot continue without the required files.")
        return 1

    # ── 2. dependencies ──────────────────────────────────────────────────────
    print("\ndependencies")
    try:
        import numpy as np  # noqa: PLC0415

        ok(f"numpy {np.__version__}")
    except ImportError:
        bad("numpy is not installed", "pip install -r requirements-embedded.txt")
        return 1
    try:
        import cv2  # noqa: PLC0415

        ok(f"opencv {cv2.__version__}")
    except ImportError:
        bad("opencv is not installed", "pip install -r requirements-embedded.txt")
        return 1

    # ── 3. the reference loads ───────────────────────────────────────────────
    print("\nreference")
    sys.path.insert(0, str(HERE))
    try:
        from drift_monitor import DriftMonitor  # noqa: PLC0415

        mon = DriftMonitor.load(str(HERE / "landmarks.npz"))
    except Exception as exc:  # noqa: BLE001
        bad(f"landmarks.npz will not load: {exc}", "re-export the bundle")
        return 1
    fh, fw = (int(x) for x in mon.frame_shape)
    ok(f"{len(mon.landmarks)} landmarks, frozen at {fw}x{fh}")

    # ── 4. THE WINDOW-SIZE TRAP ──────────────────────────────────────────────
    # The engine's defaults were validated at 4032 px wide. Left alone on a
    # smaller reference they manufacture rotation that never happened.
    print("\nmatching windows (the one that silently breaks everything)")
    side = {}
    sc = HERE / "field_unit.json"
    if sc.is_file():
        try:
            side = json.loads(sc.read_text(encoding="utf-8"))
        except ValueError as exc:
            bad(f"field_unit.json is not valid JSON: {exc}", "re-export the bundle")

    patch_from_template = int(np.asarray(mon.landmarks[0]["template"]).shape[-1])
    derived_search = max(12, int(round(40 * (fw / 4032.0))))
    search = int(side.get("search_px") or derived_search)

    ok(f"patch  {patch_from_template} px (recovered from the template itself)")
    if side.get("search_px"):
        ok(f"search {search} px (from field_unit.json)")
    else:
        warn(
            f"search {search} px was DERIVED, not read from the bundle",
            "compare it against the GUI's search_px for this reference",
        )
    if side.get("patch_px") and int(side["patch_px"]) != patch_from_template:
        bad(
            f"field_unit.json says patch {side['patch_px']} but the stored "
            f"templates are {patch_from_template}",
            "the bundle is inconsistent — re-export it",
        )
    if patch_from_template >= 48 and fw < 3000:
        warn(
            "patch is the engine default on a small frame — suspicious",
            "verify against the GUI before deploying",
        )

    # ── 5. the decisive test: the reference against ITSELF ───────────────────
    # With the right windows this is ~0. With the wrong ones it was 0.735 deg.
    print("\nsanity: judge the frozen frame against itself")
    ref_jpg = HERE / "reference.jpg"
    probe = None
    if ref_jpg.is_file():
        probe = cv2.imread(str(ref_jpg))
    if probe is None:
        warn(
            "no reference.jpg in the bundle — cannot run the self-check",
            "run selftest.py --source <camera> to check against a live frame",
        )
    else:
        mon.PATCH, mon.SEARCH = patch_from_template, search
        v = mon.check(probe)
        rot = v.get("rot_deg")
        if rot is None:
            bad("the reference frame judged itself DEGRADED", "re-export the bundle")
        elif rot > 0.05:
            bad(
                f"the reference frame judged ITSELF as {rot:.3f} deg of rotation "
                f"(state {v['state']}) — it should be ~0",
                "the matching windows are wrong; re-export with field_unit.json",
            )
        else:
            ok(f"{rot:.5f} deg — essentially zero, as it must be")

    # ── 6. the camera, if asked ──────────────────────────────────────────────
    if source:
        print(f"\ncamera: {source}")
        cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
        if not cap.isOpened():
            bad(
                "the source will not open",
                "check the device exists, the user is in the 'video' group, "
                "and nothing else holds the camera",
            )
        else:
            got, frame = cap.read()
            cap.release()
            if not got or frame is None:
                bad("opened, but gave no frame", "check the camera is producing video")
            else:
                gh, gw = frame.shape[:2]
                if (gw, gh) != (fw, fh):
                    bad(
                        f"camera is {gw}x{gh} but the reference is {fw}x{fh}",
                        "match the camera profile, or freeze a new reference for it",
                    )
                else:
                    ok(f"{gw}x{gh} — matches the reference")

    # ── verdict ──────────────────────────────────────────────────────────────
    print()
    if fails:
        print(f"RESULT: FAIL ({len(fails)} problem(s)) — do not deploy this bundle.")
        return 1
    if warns:
        print(f"RESULT: PASS with {len(warns)} warning(s) — read them before deploying.")
        return 0
    print("RESULT: PASS — safe to deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
