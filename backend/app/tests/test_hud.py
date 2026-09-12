"""HUD annotation geometry — corner brackets and the locked-target reticle.

★ What these pin: corner arms scale with the box and clamp both ways, each of
the four corners is an L of two segments anchored AT the corner, and the
crosshair leaves a gap in the middle (so it never blots the object).
"""

from __future__ import annotations

from app.services.detection import hud


def test_corner_length_scales_and_clamps() -> None:
    # A mid-size box: 22% of the shorter side.
    assert hud.corner_len(200, 100) == 22
    # Tiny box: clamped up to the floor so the arms are visible.
    assert hud.corner_len(10, 8) == 6
    # Huge box: clamped down so it is framed, not outlined.
    assert hud.corner_len(4000, 3000) == 40


def test_four_corners_each_an_l_anchored_at_the_corner() -> None:
    segs = hud.corner_segments(10, 20, 110, 80, arm=15)
    assert len(segs) == 8  # 4 corners, 2 segments each
    corners = {(10, 20), (110, 20), (10, 80), (110, 80)}
    # Every segment starts at one of the four box corners...
    assert all(s[0] in corners for s in segs)
    # ...and each arm is exactly `arm` long, horizontal or vertical.
    for (ax, ay), (bx, by) in segs:
        assert (abs(bx - ax), abs(by - ay)) in {(15, 0), (0, 15)}


def test_crosshair_leaves_a_centre_gap() -> None:
    segs = hud.crosshair_segments(100, 100, gap=4, arm=10)
    assert len(segs) == 4
    # No segment touches the exact centre — the gap keeps the object visible.
    for (ax, ay), (bx, by) in segs:
        assert (ax, ay) != (100, 100) and (bx, by) != (100, 100)
    # The left arm ends 4 px short of centre on the correct side.
    left = min(segs, key=lambda s: min(s[0][0], s[1][0]))
    assert max(left[0][0], left[1][0]) == 96
