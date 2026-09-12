"""``app.services.detection`` — the detection-to-map core, OWNED by this codebase.

★ FORMERLY ``app.vendor.object_geolocator`` (2026-09-02). It arrived as a verbatim
copy of the teammate's standalone tool and was then edited in place five times
(rescue on loss, periodic correction, stale-lock reaping, jitter damping,
parallel locks). A copy with five behavioural edits is a fork, and the
"vendored verbatim — fix it in its home" rule had become a lie that also left the
header docstrings describing an algorithm the code no longer ran. It now lives
under ``services`` with the tests beside it; fix bugs HERE. The bridge that
feeds it LandExplorer's entities is ``app.services.detection_service``.

What it does — the pipeline, minus I/O:

    frame ──► YOLO26s ──► box ──► ground point ──► LUT ──► lat/lon mark
                 ▲          (bottom-edge midpoint;    (drift status stamped by
              tiling        opt-in centre offset)     the bridge — Part F)
              locks: seeded at the handoff, updated in between, YOLO returns
              on a loss and on a clock

===================  =====================================================
Module               What it owns
===================  =====================================================
models               settings + plain data (Box, Detection), class tables
detector             YOLO26 + THE algorithm (detector ⇄ visual locks)
locked_tracking      the locks: acquire / update / correct / reap
tiling               the rotating tile pass and box merging
ground               box → ground-contact pixel; opt-in centre offset
lut                  ground pixel → lat/lon through a LUT bundle
===================  =====================================================

Dropped on the move because nothing called it: ``route.py`` (paths from marks —
no endpoint), ``GeoLut.check_gcps``, ``Mark``/``MediaInfo``/``RunResult``,
``TRACKER_CATALOG``/``YOLO_DEFAULTS``, and the settings the run loop accepted
and ignored (``tracker_confidence``, ``start_frame``, ``end_frame``,
``pace_realtime``).

★ RUNTIME DEPENDENCIES ARE OPTIONAL, AND ABSENCE IS REPORTED, NEVER PAPERED OVER:
``ultralytics`` (and torch) is imported lazily inside ``detector.Detector.load``;
the visual trackers live in **opencv-contrib** — the bridge feature-detects both
and refuses, with the fix named, rather than silently downgrading.

★ HONESTY, which the bridge must not soften: nothing below the confidence floor
exists anywhere; ground pixels with no terrain under them are counted and
skipped, never guessed; a tracker box is always marked ``predicted`` (orange).
"""

from __future__ import annotations

__all__ = [
    "detector",
    "ground",
    "locked_tracking",
    "lut",
    "models",
    "tiling",
]
