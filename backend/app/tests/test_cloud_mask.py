"""Basemap cloud (upstream §10, the known gap) — the mask, the gate, and the report.

A lock on a cloud edge is a number that is not an error, and the consistency filter
cannot catch it: an edge is a continuous line, so neighbouring false locks agree with
each other. The mask is off by default because white roofs can trigger it; the run
reports what it found either way.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from app.vendor.geo_accuracy import error_map as EM  # noqa: N812 — the engine's own shorthand


def _ground(h: int = 160, w: int = 160) -> np.ndarray:
    """A green field, with a little texture so a matcher has something to hold."""
    rng = np.random.default_rng(3)
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = 90, 120, 60
    return np.clip(img.astype(int) + rng.integers(-20, 20, (h, w, 1)), 0, 255).astype(np.uint8)


class TestTheMask:
    def test_a_bright_grey_patch_is_cloud_and_a_thin_gap_in_it_is_closed(self) -> None:
        sat = _ground()
        sat[20:70, 20:70] = 235          # cloud
        sat[45, 20:70] = 140             # a one-pixel dark line through it
        cloud = EM.cloud_mask(sat, np.ones(sat.shape[:2], bool), EM.Params())
        assert cloud[20:70, 20:70].all()  # the line did not survive the close
        assert not cloud[90:, 90:].any()  # the field is not cloud

    def test_bright_but_saturated_ground_is_not_cloud(self) -> None:
        """Yellow stubble is as bright as cloud and nothing like it in colour."""
        sat = _ground()
        sat[20:70, 20:70] = (255, 220, 60)
        cloud = EM.cloud_mask(sat, np.ones(sat.shape[:2], bool), EM.Params())
        assert not cloud[20:70, 20:70].any()

    def test_a_white_roof_is_taken_for_cloud_which_is_why_the_switch_is_off(self) -> None:
        """Pinned as a fact, not fixed: it is the documented reason for the default."""
        sat = _ground()
        sat[100:112, 100:112] = 200      # a flat white roof
        cloud = EM.cloud_mask(sat, np.ones(sat.shape[:2], bool), EM.Params())
        assert cloud[100:112, 100:112].all()
        assert EM.Params().cloud_mask is False

    def test_only_content_can_be_cloud(self) -> None:
        sat = np.full((40, 40, 3), 240, np.uint8)
        content = np.zeros((40, 40), bool)
        content[:, :20] = True
        cloud = EM.cloud_mask(sat, content, EM.Params())
        assert cloud[:, :20].all() and not cloud[:, 20:].any()


class TestTheGate:
    def test_a_tile_mostly_on_cloud_is_never_matched(self) -> None:
        """Cloud leaves the content mask, so `min_valid` refuses the tile.

        ★ This is the whole mechanism: nothing is matched and then thrown away —
        a cloud edge is never a texture the matcher gets to see.
        """
        rng = np.random.default_rng(7)
        h = w = 256
        tex = rng.integers(0, 255, (h, w, 3)).astype(np.uint8)
        p = dataclasses.replace(EM.Params(), gsd=1.0, tile=64, stride=64)
        inside = np.ones((h, w), bool)
        rng_g = np.full((h, w), 500.0)
        u_g = np.full((h, w), 100.0)
        before = EM.match_tiles(tex, tex, inside, rng_g, u_g, 1000, p)
        # a 64x64 "cloud" exactly on one tile, plus a strip through a second
        cloud = np.zeros((h, w), bool)
        cloud[0:64, 0:64] = True
        cloud[64:128, 0:24] = True       # 37% of the tile below it
        after = EM.match_tiles(tex, tex, inside & ~cloud, rng_g, u_g, 1000, p)
        keys_before = {(t["x0"], t["y0"]) for t in before}
        keys_after = {(t["x0"], t["y0"]) for t in after}
        assert (0, 0) in keys_before and (0, 0) not in keys_after
        assert (0, 64) in keys_before and (0, 64) not in keys_after   # 63% valid < 0.75
        assert (64, 64) in keys_after                                   # untouched


class TestTheReport:
    @staticmethod
    def _result(sat: np.ndarray, tiles: list, cloud: np.ndarray | None = None) -> EM.Result:
        return EM.Result(
            ortho=sat, sat=sat, inside=np.ones(sat.shape[:2], bool), rng_g=None,
            origin=(0.0, 0.0), tiles=tiles, params=EM.Params(), cloud=cloud,
        )

    def test_with_the_mask_off_it_counts_the_locks_that_sit_on_cloud(self) -> None:
        from app.services.accuracy_service import CLOUD_TILE_FRACTION, cloud_report

        sat = _ground()
        sat[0:64, 0:64] = 235
        tiles = [
            {"x0": 0, "y0": 0, "tile": 64, "ok": True},      # fully on cloud
            {"x0": 48, "y0": 0, "tile": 64, "ok": True},     # 25% on cloud — at the cut, not over
            {"x0": 96, "y0": 96, "tile": 64, "ok": True},    # clean
            {"x0": 0, "y0": 0, "tile": 64, "ok": False},     # on cloud but not locked
        ]
        got = cloud_report(self._result(sat, tiles), EM.Params())
        assert got["masked"] is False
        assert got["locked_tiles_on_cloud"] == 1
        assert got["tile_fraction_threshold"] == CLOUD_TILE_FRACTION
        assert got["content_fraction"] == pytest.approx(64 * 64 / (160 * 160), abs=0.01)

    def test_with_the_mask_on_the_fraction_is_over_the_content_before_masking(self) -> None:
        """`result.inside` already excludes the cloud; the report puts it back."""
        from app.services.accuracy_service import cloud_report

        sat = _ground()
        sat[0:64, 0:64] = 235
        cloud = EM.cloud_mask(sat, np.ones(sat.shape[:2], bool), EM.Params())
        res = self._result(sat, [], cloud=cloud)
        res.inside = ~cloud
        got = cloud_report(res, dataclasses.replace(EM.Params(), cloud_mask=True))
        assert got["masked"] is True
        assert got["content_fraction"] == pytest.approx(64 * 64 / (160 * 160), abs=0.01)


# ── on the synthetic scene ────────────────────────────────────────────────────

from app.tests.test_accuracy_service import scene  # noqa: E402, F401
from app.tests.test_error_map_updates import _run  # noqa: E402


@pytest.mark.slow
def test_the_mask_only_removes_and_leaves_no_lock_on_what_it_calls_cloud(
    scene: dict, tmp_path,  # noqa: F811
) -> None:
    """With the mask on, the locked set is a subset of the mask-off set, and clean.

    ★ THE FIXTURE IS A LESSON, NOT A BUG. Its basemap is the photograph itself,
    whose texture is grey noise — and to a brightness-and-saturation test every
    bright grey speckle is cloud: about 8% of the content, in hundreds of blobs.
    That is the white-roof caveat in its extreme form, and it is why the switch is
    off by default. What must hold regardless is the mask's contract: it never
    ADDS a lock, and whatever it calls cloud carries no lock once it has run.
    """
    from app.services.accuracy_service import cloud_report

    off = _run(scene, tmp_path / "off")
    on = _run(scene, tmp_path / "on", cloud_mask=True)
    assert off.cloud is None and on.cloud is not None
    keys_off = {(t["x0"], t["y0"], t["tile"]) for t in off.good}
    keys_on = {(t["x0"], t["y0"], t["tile"]) for t in on.good}
    assert keys_on <= keys_off
    report_off = cloud_report(off, EM.Params())
    report_on = cloud_report(on, dataclasses.replace(EM.Params(), cloud_mask=True))
    # The same content is called cloud whichever way the switch was set ...
    assert report_on["content_fraction"] == pytest.approx(report_off["content_fraction"], abs=0.005)
    # ... the mask-off run reports locks on it, and the mask-on run has none.
    assert report_off["locked_tiles_on_cloud"] > 0
    assert report_on["locked_tiles_on_cloud"] == 0
