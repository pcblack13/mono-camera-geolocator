"""Detecting on crops of the frame as well as the whole of it.

A 4K frame handed to a 1280-pixel network is shrunk 3x before the model ever
sees it, and a car 60 pixels across arrives 20 pixels across. Running the model
again on a QUARTER of the frame gives that same car 40 pixels — the object gets
bigger without the network getting slower.

The cost is that tiles are extra work. Measured on this project's 4K clip
(RTX 3060, yolo26s, 100 frames):

    full frame @1280                17.3 ms   2.32x real time    93 detections
    full + ONE rotating tile @960   33.5 ms   1.19x real time   100 detections
    all four tiles @960             44.0 ms   0.91x real time   103 detections

All four tiles every frame buys ten more detections than the rotating one and
costs real time to get them — and it also LOST two the full frame had, because
an object lying across a seam is cut in half in both tiles. The rotating tile
is the configuration that pays for itself: one extra crop per frame, a
different quadrant each time, so the whole frame is covered every four frames
and nothing the full-frame pass found is ever lost.
"""
from __future__ import annotations

from typing import Sequence

from .models import Box, Detection

# how far tiles reach into their neighbours. An object sitting exactly on a
# seam is whole in at least one tile only if the tiles overlap by more than
# the object's size; 15% of a 1920x1080 quadrant is ~290x160 px, comfortably
# larger than anything this camera sees.
OVERLAP = 0.15
GRID = 2                           # 2 -> a 2x2 grid of four cells


def tile_rects(width: int, height: int, grid: int = GRID,
               overlap: float = OVERLAP) -> list[tuple[int, int, int, int]]:
    """The crop rectangles, left to right then top to bottom, as (x0, y0, x1, y1)."""
    n = max(2, int(grid))
    tw, th = width // n, height // n
    ox, oy = int(tw * overlap), int(th * overlap)
    out = []
    for row in range(n):
        for col in range(n):
            out.append((max(0, col * tw - ox),
                        max(0, row * th - oy),
                        min(width, (col + 1) * tw + ox),
                        min(height, (row + 1) * th + oy)))
    return out


def suggest_overlap(box_sizes: Sequence[tuple[float, float]],
                    width: int, height: int, grid: int = GRID,
                    margin: float = 1.35) -> dict:
    """How much overlap this footage needs, worked out from what is in it.

    An object lying across a seam is split between two cells and whole in
    neither, which is why tiling.drop_clipped throws such boxes away. It is
    only whole in one of them if the cells reach into each other by MORE than
    the object is wide. So the overlap is not a taste setting — it follows
    from how big things actually look in this view:

        overlap >= object size / cell size = object size * grid / frame size

    The 95th percentile is used rather than the largest box, so one lorry
    parked in the foreground does not set the figure for the whole clip, and a
    margin is added on top because the percentile is an estimate.

    Bigger cells need proportionally less overlap, so the answer depends on
    the grid as well as the objects — which is why it is recomputed whenever
    either changes.
    """
    if not box_sizes:
        return {"overlap": OVERLAP, "n": 0,
                "reason": "nothing was detected to measure"}
    n = max(2, int(grid))
    ws = sorted(w for w, _ in box_sizes)
    hs = sorted(h for _, h in box_sizes)
    p95 = lambda xs: xs[min(len(xs) - 1, int(0.95 * len(xs)))]
    ow, oh = p95(ws), p95(hs)
    need = max(ow * n / max(1, width), oh * n / max(1, height)) * margin
    val = max(0.02, min(0.45, need))
    return {
        "overlap": round(val, 3),
        "n": len(box_sizes),
        "p95_w": round(ow, 1),
        "p95_h": round(oh, 1),
        "capped": need > 0.45,
        "reason": (f"{len(box_sizes)} objects, 95th percentile {ow:.0f}x{oh:.0f} px "
                   f"against {width // n}x{height // n} px cells"),
    }


def tile_for_frame(frame_index: int, stride: int, n_tiles: int) -> int:
    """Which tile this frame's extra pass should cover.

    Keyed off the frame index rather than a call counter so that re-running a
    frame examines the same tile, and so a stride of 5 still advances one tile
    per DETECTED frame instead of skipping four of them.
    """
    return (frame_index // max(1, stride)) % max(1, n_tiles)


# Labels that are alternatives for ONE physical thing. A detector that cannot
# decide between car and truck emits both, and ultralytics' NMS is class-aware
# so neither suppresses the other — one vehicle, two boxes, two map marks a few
# centimetres apart. Person is deliberately its own family: somebody standing
# beside a car overlaps it heavily from above, and they are genuinely two
# objects that both belong on the map.
VEHICLE_IDS = frozenset({2, 3, 5, 7})       # car, motorcycle, bus, truck


def _same_thing(a: Detection, b: Detection) -> bool:
    """Could these two boxes be labels for the same physical object?"""
    if a.cls_id == b.cls_id:
        return True
    return a.cls_id in VEHICLE_IDS and b.cls_id in VEHICLE_IDS


def _overlap(a: Box, b: Box) -> float:
    """How much two boxes coincide, in [0, 1].

    IoU, except when one box sits INSIDE the other — a small box nested in a
    large one scores low on IoU while plainly being the same object, so the
    share of the smaller box that is covered is taken instead.
    """
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    aa, ab = a.width * a.height, b.width * b.height
    union = aa + ab - inter
    iou = inter / union if union > 0 else 0.0
    smaller = min(aa, ab)
    return max(iou, inter / smaller if smaller > 0 else 0.0)


def merge(detections: Sequence[Detection], iou_thr: float = 0.55,
          nested_thr: float = 0.7) -> list[Detection]:
    """One box per object.

    Two passes over the same ground (the full frame and a tile) return the same
    car twice, and even a single pass returns it twice when the detector cannot
    choose between two labels for it. Highest score wins.
    """
    kept: list[Detection] = []
    for d in sorted(detections, key=lambda d: -d.score):
        if all(not _same_thing(d, k) or _overlap(d.box, k.box) < min(iou_thr, nested_thr)
               for k in kept):
            kept.append(d)
    return kept


def offset(detections: Sequence[Detection], dx: float, dy: float) -> list[Detection]:
    """Tile-local boxes moved back into whole-frame pixels."""
    for d in detections:
        d.box = Box(d.box.x1 + dx, d.box.y1 + dy, d.box.x2 + dx, d.box.y2 + dy)
    return list(detections)


def drop_clipped(detections: Sequence[Detection], rect: tuple[int, int, int, int],
                 frame_w: int, frame_h: int, tol: float = 2.0) -> list[Detection]:
    """Discard tile detections that the crop cut in half.

    This matters more here than it would in a plain detector. The mark this app
    places is read from the BOTTOM EDGE of the box — where the object meets the
    ground — so a car whose bottom edge is really the tile's lower seam gets its
    position read at the seam, and lands somewhere it has never been. A box
    touching the edge of the whole FRAME is kept: that object genuinely is at
    the edge of what the camera can see, and its edge is the truth.

    Losing a seam-clipped object costs little, because the tile rotates: within
    four frames a tile that contains it whole comes round.
    """
    x0, y0, x1, y1 = rect
    kept = []
    for d in detections:
        b = d.box
        if ((x0 > 0 and b.x1 <= x0 + tol) or (y0 > 0 and b.y1 <= y0 + tol) or
                (x1 < frame_w and b.x2 >= x1 - tol) or
                (y1 < frame_h and b.y2 >= y1 - tol)):
            continue
        kept.append(d)
    return kept
