"""HUD annotation geometry — the targeting-overlay look (2026-09-03, owner ask).

★ WHY. A full rectangle round every object reads as a spreadsheet; the operator
asked for a heads-up-display look — corner brackets that frame the object like a
sensor reticle, and a crosshair on the LOCKED target. This module is pure
geometry (no cv2, no numpy) so both the server burn-in and the client canvas draw
the SAME shapes, and so it can be tested without a frame.

Coordinates are integer pixels in whatever image the caller is drawing on; a
segment is ``((x1, y1), (x2, y2))``.
"""

from __future__ import annotations

Point = tuple[int, int]
Segment = tuple[Point, Point]


def corner_len(width: float, height: float, frac: float = 0.22, lo: int = 6, hi: int = 40) -> int:
    """How long each corner bracket arm is — a fraction of the shorter side, clamped.

    Small boxes get proportionally shorter arms (so the brackets never cross), big
    boxes a fixed maximum (so a huge box is framed, not outlined).
    """
    return int(max(lo, min(hi, round(min(width, height) * frac))))


def corner_segments(x1: int, y1: int, x2: int, y2: int, arm: int) -> list[Segment]:
    """The eight little lines that make the four L-shaped corner brackets."""
    return [
        # top-left
        ((x1, y1), (x1 + arm, y1)),
        ((x1, y1), (x1, y1 + arm)),
        # top-right
        ((x2, y1), (x2 - arm, y1)),
        ((x2, y1), (x2, y1 + arm)),
        # bottom-left
        ((x1, y2), (x1 + arm, y2)),
        ((x1, y2), (x1, y2 - arm)),
        # bottom-right
        ((x2, y2), (x2 - arm, y2)),
        ((x2, y2), (x2, y2 - arm)),
    ]


def crosshair_segments(cx: int, cy: int, gap: int = 4, arm: int = 11) -> list[Segment]:
    """A centre crosshair with a gap in the middle — the LOCKED target reticle."""
    return [
        ((cx - gap - arm, cy), (cx - gap, cy)),
        ((cx + gap, cy), (cx + gap + arm, cy)),
        ((cx, cy - gap - arm), (cx, cy - gap)),
        ((cx, cy + gap), (cx, cy + gap + arm)),
    ]
