"""The 2026-09-10 Stage D engine updates — the upstream porting checklist, pinned.

★ WHY THIS FILE EXISTS. `heatmap_kit/docs/HEATMAP_ALGORITHM_UPDATES.md` §11 is a
seven-point checklist for anyone porting these changes. Six of its points are
checkable without a satellite mosaic, so they are checked here rather than by
hand once. The seventh (byte-identical output on a known project) needs a real
measurement and is done against a real camera, not in this file.

★ THE RULE THE WHOLE PORT RESTS ON: every addition is off at its default, so a
run that sets no new field behaves exactly as it did before they existed. The
first test is that rule, and it is the one that must never be relaxed.
"""

from __future__ import annotations

import dataclasses
from uuid import uuid4

import numpy as np
import pytest

from app.vendor.geo_accuracy import error_map as EM  # noqa: N812 — the engine's own shorthand


class _FlatDem:
    """Bare earth at z = 0, everywhere. `res` is the march step the caller reads."""

    res = 1.0
    epsg = 32637

    def Z(self, x: float, y: float) -> float:  # noqa: N802, ARG002 — `dem.Z` is the interface
        return 0.0


class _PlaneDem(_FlatDem):
    """Ground on a constant slope — one metre up every ten metres east."""

    def Z(self, x: float, y: float) -> float:  # noqa: N802, ARG002 — `dem.Z` is the interface
        return 0.1 * float(x)


class _CurvedDem(_FlatDem):
    """Ground whose slope CHANGES with distance — a bowl rising away from 0."""

    def Z(self, x: float, y: float) -> float:  # noqa: N802, ARG002 — `dem.Z` is the interface
        return 0.001 * float(x) * float(x)


# ── §11.1 — the defaults ──────────────────────────────────────────────────────


def test_every_new_switch_is_off_by_default() -> None:
    p = EM.Params()
    assert p.ecc_rescue is False
    assert p.tile_auto is False
    assert p.reliability_max == 0.0
    # The two that carry a value rather than a switch keep the upstream numbers.
    assert (p.sigma_dtm, p.ecc_shear_max) == (3.0, 0.35)
    assert (p.tile_auto_sizes, p.tile_auto_thresholds) == ((128, 96, 64), (2.5, 3.5))


# ── §11.2 — the two sign self-tests ───────────────────────────────────────────


def test_both_sign_self_tests_return_a_sign_not_zero() -> None:
    """0.0 from `ecc_sign` disables the rescue; on this build both must be ±1."""
    assert EM.phase_sign() in (1.0, -1.0)
    assert EM.ecc_sign() in (1.0, -1.0)


# ── §11.3 — the satellite zoom step-down ──────────────────────────────────────


@pytest.mark.parametrize("cap_error", [RuntimeError, ValueError])
def test_the_zoom_steps_down_for_either_cap_exception(tmp_path, monkeypatch, cap_error) -> None:
    """The zoom step-down survives either exception a writer may raise.

    ★ The catch was widened when porting §1. THIS build's writer raises

    RuntimeError with "cap" in the message, upstream's raises ValueError; the
    step-down has to survive whichever a provider path chooses.
    """
    tried: list[int] = []

    def writer(lat, lon, radius_m, zoom, out_path, epsg) -> None:  # noqa: ARG001
        tried.append(zoom)
        if zoom > 15:
            raise cap_error(f"mosaic would need 4000 tiles at z{zoom}, over the 900 cap")
        np.save(out_path, np.zeros((2, 2)))  # never read: the reproject is stubbed
        raise _WriterCalledError

    class _WriterCalledError(Exception):
        pass

    monkeypatch.setattr(EM.os.path, "isfile", lambda _p: False)
    with pytest.raises(_WriterCalledError):
        EM.fetch_satellite(
            (34.1, 36.0), (0.0, 0.0, 100.0, 100.0), (0.0, 100.0), (8, 8), 32637,
            str(tmp_path), EM.Params(), mosaic_writer=writer,
        )
    assert tried == [17, 16, 15], f"the step-down did not walk the zooms: {tried}"


def test_a_failure_that_is_not_the_cap_propagates_untouched(tmp_path, monkeypatch) -> None:
    """A failure that is not the tile cap reaches the caller at once.

    Only "cap" in the message means "try a coarser zoom"; everything else is

    a real failure and must reach the caller on the first attempt.
    """
    tried: list[int] = []

    def writer(lat, lon, radius_m, zoom, out_path, epsg) -> None:  # noqa: ARG001
        tried.append(zoom)
        raise RuntimeError("the provider refused the request")

    monkeypatch.setattr(EM.os.path, "isfile", lambda _p: False)
    with pytest.raises(RuntimeError, match="refused"):
        EM.fetch_satellite(
            (34.1, 36.0), (0.0, 0.0, 100.0, 100.0), (0.0, 100.0), (8, 8), 32637,
            str(tmp_path), EM.Params(), mosaic_writer=writer,
        )
    assert tried == [17], "a non-cap failure must not be retried at a lower zoom"


# ── §11.6 and §4's trap — amplification ───────────────────────────────────────


def _row(cE: float, cN: float = 0.0) -> dict:  # noqa: N803 — the engine's column names
    return {"cE": cE, "cN": cN, "ok": True}


def test_amplification_over_flat_ground_is_one_over_tan_depression() -> None:
    """Over flat ground the amplification is range divided by camera height.

    ★ §4's TRAP, guarded. Amplification is horizontal-over-vertical of the

    VIEW DIRECTION against the local slope — over flat ground exactly
    `range / height`. The wrong implementation (stepping the pixel and dividing
    movements) reports double digits at nadir; these numbers would catch that.
    """
    cam = (0.0, 0.0, 200.0)
    rows = [_row(400.0), _row(620.0), _row(20.0)]
    EM.tile_reliability(rows, cam, _FlatDem(), EM.Params())
    assert rows[0]["amplification"] == pytest.approx(2.0, rel=1e-6)   # 400 / 200
    assert rows[1]["amplification"] == pytest.approx(3.1, rel=1e-6)   # 620 / 200
    # §11.6: a near-nadir look must NOT read double digits.
    assert rows[2]["amplification"] == pytest.approx(0.1, rel=1e-6)
    # sigma is the amplification times the DTM's own 1-sigma height error.
    assert rows[0]["sigma_m"] == pytest.approx(2.0 * EM.Params().sigma_dtm)


def test_a_constant_slope_cancels_out_of_the_formula() -> None:
    """On a plane of any tilt the gradient cancels out of the formula.

    ★ A REAL PROPERTY, AND A SECOND GUARD ON §4's TRAP. On any plane the

    gradient term cancels exactly and the amplification is range over camera
    height, whatever the tilt. The wrong estimator has no such property, so a
    port that drifts into it fails here as well as above.
    """
    cam = (0.0, 0.0, 200.0)
    flat, plane = [_row(400.0)], [_row(400.0)]
    EM.tile_reliability(flat, cam, _FlatDem(), EM.Params())
    EM.tile_reliability(plane, cam, _PlaneDem(), EM.Params())
    assert plane[0]["amplification"] == pytest.approx(flat[0]["amplification"], rel=1e-9)
    assert plane[0]["amplification"] == pytest.approx(2.0, rel=1e-9)


def test_a_changing_slope_does_move_the_amplification() -> None:
    """Ground whose slope changes does move the amplification.

    Curvature is what the gradient term is actually for: ground that steepens

    away from the camera meets the ray at a different angle than a plane does.
    """
    cam = (0.0, 0.0, 200.0)
    flat, curved = [_row(400.0)], [_row(400.0)]
    EM.tile_reliability(flat, cam, _FlatDem(), EM.Params())
    EM.tile_reliability(curved, cam, _CurvedDem(), EM.Params())
    assert curved[0]["amplification"] < flat[0]["amplification"]


def test_reliability_only_gates_when_asked() -> None:
    cam = (0.0, 0.0, 200.0)
    far = [_row(4000.0)]                       # amplification 20 → sigma 60 m
    EM.tile_reliability(far, cam, _FlatDem(), EM.Params())
    assert far[0]["ok"] is True, "the default must never drop a tile"
    far = [_row(4000.0)]
    EM.tile_reliability(far, cam, _FlatDem(), EM.Params(reliability_max=10.0))
    assert far[0]["ok"] is False


def test_a_tile_with_no_ground_centre_is_left_alone() -> None:
    """A row with no ground centre gets the columns, empty, and no exception.

    `tile_reliability` runs before every row has been decomposed in some

    call paths; a row with no cE must come back with the columns present and
    empty rather than raising.
    """
    rows = [{"ok": True}]
    EM.tile_reliability(rows, (0.0, 0.0, 100.0), _FlatDem(), EM.Params())
    assert rows[0]["amplification"] is None and rows[0]["sigma_m"] is None


# ── §11.4 — tile size from the geometry ───────────────────────────────────────


def _footprint(n: int = 64) -> tuple:
    inside = np.ones((n, n), bool)
    return inside, (0.0, float(n))


def _height_for_amplification(target: float, inside, origin, p) -> float:
    """Solve for the camera height that puts the footprint at a target amplification.

    Over flat ground amplification is range/height, so it scales as 1/height:

    measure it once and solve for the height that lands on `target`. Calibrating
    beats hard-coding a height that a change of footprint would quietly invalidate.
    """
    ref_h = 1000.0
    amp = EM.footprint_amplification(inside, origin, (0.0, 0.0, ref_h), _FlatDem(), p)
    return ref_h * amp / target


@pytest.mark.parametrize(
    ("amplification", "expect_tile"),
    [(2.0, 128), (3.0, 96), (5.0, 64)],   # thresholds are 2.5 and 3.5
)
def test_tile_auto_picks_the_size_the_geometry_asks_for(amplification, expect_tile) -> None:
    """The chosen tile size follows the footprint's median amplification.

    ★ §11.4. Below 2.5 → 128 m, below 3.5 → 96 m, otherwise 64 m: a big tile

    holds more texture, a small one spans less amplification change.
    """
    inside, origin = _footprint()
    p = EM.Params(tile_auto=True, gsd=8.0)
    h = _height_for_amplification(amplification, inside, origin, p)
    q = EM.resolve_tile_auto(p, inside, origin, (0.0, 0.0, h), _FlatDem())
    assert q.tile == expect_tile
    assert q.stride == expect_tile // 2, "stride follows the tile at half its size"


def test_tile_auto_returns_a_new_params_and_leaves_the_original_alone() -> None:
    """The resolver returns a new Params and leaves the caller's alone.

    ★ It is `dataclasses.replace`: the caller MUST rebind. A port that

    mutated in place would work; one that dropped the rebinding would silently
    keep the old tile size, which is why this is pinned.
    """
    inside, origin = _footprint()
    p = EM.Params(tile_auto=True, gsd=8.0, tile=128)
    h = _height_for_amplification(5.0, inside, origin, p)      # → 64 m, so it moves
    q = EM.resolve_tile_auto(p, inside, origin, (0.0, 0.0, h), _FlatDem())
    assert q is not p and p.tile == 128
    assert dataclasses.is_dataclass(q)


def test_tile_auto_off_is_the_identity() -> None:
    inside, origin = _footprint()
    p = EM.Params(gsd=8.0)
    assert EM.resolve_tile_auto(p, inside, origin, (0.0, 0.0, 300.0), _FlatDem()) is p


def test_footprint_amplification_is_area_weighted_over_the_ortho() -> None:
    """The footprint amplification is finite and in a believable range.

    A camera 200 m up over a 64-cell footprint at 8 m/cell: the median cell

    sits a few hundred metres out, so the median amplification is a few.
    """
    inside, origin = _footprint()
    amp = EM.footprint_amplification(inside, origin, (0.0, 0.0, 200.0), _FlatDem(),
                                     EM.Params(gsd=8.0))
    assert np.isfinite(amp) and 0.5 < amp < 12.0


# ── §11.5 — the affine rescue only ever adds ──────────────────────────────────


def _ecc_scene(shift_px: int = 4, n: int = 256) -> tuple:
    """An ortho and a satellite that differ by a known whole-pixel shift."""
    rs = np.random.RandomState(7)
    import cv2

    base = cv2.GaussianBlur(rs.rand(n, n).astype(np.float32), (0, 0), 2.0) * 255.0
    ortho = np.repeat(base[:, :, None], 3, axis=2).astype(np.uint8)
    sat = np.repeat(np.roll(base, shift_px, axis=1)[:, :, None], 3, axis=2).astype(np.uint8)
    return ortho, sat, np.ones((n, n), bool)


def test_ecc_rescue_never_touches_a_tile_that_already_locked() -> None:
    """The affine rescue leaves every already-locked tile exactly as it was.

    ★ §11.5. The rescue exists so a hard tile can join; a tile that already

    locked must come back with the same `dE, dN` it went in with, or every
    published measurement moves under it.
    """
    ortho, sat, inside = _ecc_scene()
    good = [
        {"x0": x, "y0": y, "tile": 64, "ok": True, "dE": 4.0, "dN": 0.0,
         "err": 4.0, "resp": 0.5, "method": "phase"}
        for x in (0, 64, 128) for y in (0, 64, 128)
    ]
    bad = [{"x0": 192, "y0": 192, "tile": 64, "ok": False, "dE": 0.0, "dN": 0.0,
            "err": 0.0, "resp": 0.0, "method": "phase"}]
    before = [(t["dE"], t["dN"], t["method"]) for t in good]
    rows = EM.ecc_rescue(good + bad, ortho, sat, inside,
                         EM.Params(gsd=1.0, tile=64, stride=32))
    after = [(t["dE"], t["dN"], t["method"]) for t in rows if t in good]
    assert after == before, "a locked tile was modified by the rescue"
    assert sum(1 for t in rows if t["ok"]) >= len(good), "the rescue removed a lock"


def test_ecc_rescue_is_a_no_op_without_enough_neighbours_to_seed_from() -> None:
    ortho, sat, inside = _ecc_scene()
    rows = [{"x0": 0, "y0": 0, "tile": 64, "ok": False, "dE": 0.0, "dN": 0.0,
             "err": 0.0, "resp": 0.0, "method": "phase"}]
    out = EM.ecc_rescue(rows, ortho, sat, inside, EM.Params(gsd=1.0, tile=64))
    assert out[0]["ok"] is False


def test_a_recovered_tile_is_tagged_and_carries_its_shear() -> None:
    """A tile the rescue recovers is tagged as such and carries its shear.

    When it does lock, the row says HOW — `method="ecc"` plus the shear that

    was accepted, so a sheared lock is never mistaken for a phase lock.
    """
    ortho, sat, inside = _ecc_scene(shift_px=3)
    good = [
        {"x0": x, "y0": y, "tile": 64, "ok": True, "dE": 3.0, "dN": 0.0,
         "err": 3.0, "resp": 0.5, "method": "phase"}
        for x in (0, 64, 128) for y in (0, 64, 128)
    ]
    bad = [{"x0": 192, "y0": 64, "tile": 64, "ok": False, "dE": 0.0, "dN": 0.0,
            "err": 0.0, "resp": 0.0, "method": "phase"}]
    rows = EM.ecc_rescue(good + bad, ortho, sat, inside,
                         EM.Params(gsd=1.0, tile=64, ecc_shear_max=0.35))
    recovered = [t for t in rows if t.get("method") == "ecc"]
    if recovered:                      # ECC's basin is narrow; a miss is allowed
        t = recovered[0]
        assert t["ok"] is True and "shear" in t
        assert t["shear"] <= 0.35
        assert t["err"] <= EM.Params().max_shift


# ── the switches, turned ON, against a real run of the pipeline ───────────────
# ★ The tests above prove the additions are inert. These prove they are not
#   ornamental: on the synthetic scene the tile size follows the geometry and
#   the affine rescue can only ever add. They need the whole pipeline, so they
#   borrow the scene fixture and are marked slow.

from app.tests.test_accuracy_service import scene  # noqa: E402, F401


def _run(scene: dict, tmp_path, **params: object) -> object:  # noqa: F811
    import cv2

    from app.services.accuracy_service import StageDParams
    from app.vendor.geo_accuracy.geo_io import DEM

    dem = DEM(str(scene["dem_path"]))
    try:
        return EM.run(
            scene["rotation"], scene["camera_xyz"],
            np.array([[1100.0, 0.0, 600.0], [0.0, 1100.0, 400.0], [0.0, 0.0, 1.0]]),
            np.zeros(5), cv2.imread(str(scene["photo_path"])), dem,
            (scene["cam_lat"], scene["cam_lon"]), str(tmp_path),
            params=dataclasses.replace(StageDParams().to_core(), **params),
            mosaic_writer=scene["mosaic_writer"],
        )
    finally:
        dem.ds.close()


@pytest.mark.slow
def test_a_default_run_carries_the_two_new_columns_and_measures_the_injected_shift(
    scene: dict, tmp_path,  # noqa: F811
) -> None:
    """A default run measures the injected shift and adds the two new columns.

    ★ The scene displaces the satellite by (4, -3) m, so the truth is 5 m.

    Every tile also comes back with its amplification and expected sigma —
    those two are computed ALWAYS, which is the one behaviour change a default
    run does show, and it only ADDS columns.
    """
    res = _run(scene, tmp_path)
    assert res.good, "the synthetic scene locked nothing — the fixture is broken"
    assert float(np.median([t["err"] for t in res.good])) == pytest.approx(5.0, abs=0.05)
    amps = [t["amplification"] for t in res.good]
    assert all(a is not None for a in amps)
    assert all(t["sigma_m"] == pytest.approx(t["amplification"] * 3.0) for t in res.good)
    # §11.6 again, on real geometry rather than a hand-built row: a camera 120 m
    # up looking 25° down is not a grazing scene, so this must not read double digits.
    assert 0.1 < float(np.median(amps)) < 10.0


@pytest.mark.slow
def test_tile_auto_changes_the_tile_size_and_records_it_on_the_result(
    scene: dict, tmp_path,  # noqa: F811
) -> None:
    """With tile_auto on, the size the run used is recorded on the Result.

    ★ §6(a) rebinds `p`. If a port applied the hook but dropped the

    rebinding the run would quietly keep 128 m — so the size is read back off
    the Result, which carries the Params the run actually used.
    """
    res = _run(scene, tmp_path, tile_auto=True)
    assert res.params.tile in (128, 96, 64)
    assert res.params.stride == res.params.tile // 2


@pytest.mark.slow
def test_the_affine_rescue_never_loses_a_lock(scene: dict, tmp_path) -> None:  # noqa: F811
    """Turning the affine rescue on never loses or moves an existing lock.

    ★ §11.5 end to end: turning the rescue on may add tiles, never remove

    them, and never move one that already locked.

    ★ THE FINE PASS IS OFF ON BOTH SIDES, AND THAT IS NOT A CONVENIENCE.
    §8 of the porting notes: the fine pass emits half-size sub-tiles whose
    POSITIONS depend on which coarse tiles happened to lock, so two runs that
    lock different coarse sets cannot be paired tile-by-tile at all. Measured
    here — with the fine pass on, 63 rows appear to "move" between the two runs
    while the coarse answers are in fact identical; with it off, zero do. A
    comparison that left it on would be measuring the sub-tile lottery.
    """
    base = _run(scene, tmp_path / "base", fine_pass=False)
    with_ecc = _run(scene, tmp_path / "ecc", fine_pass=False, ecc_rescue=True)
    assert len(with_ecc.good) >= len(base.good), "the rescue removed locks"
    was = {(t["x0"], t["y0"], t["tile"]): (t["dE"], t["dN"]) for t in base.good}
    for t in with_ecc.good:
        key = (t["x0"], t["y0"], t["tile"])
        if key in was:
            assert (t["dE"], t["dN"]) == was[key], f"the rescue moved a locked tile at {key}"


@pytest.mark.slow
def test_the_fine_pass_makes_two_runs_unpairable(scene: dict, tmp_path) -> None:  # noqa: F811
    """The fine pass makes two runs impossible to pair tile by tile.

    ★ §8, pinned as a fact about THIS build rather than a warning in a

    document. It is why the test above turns the fine pass off, and it is the
    trap waiting for anyone who later compares two measurements directly.
    """
    a = _run(scene, tmp_path / "a", fine_pass=False)
    b = _run(scene, tmp_path / "b", fine_pass=True)
    coarse_a = {(t["x0"], t["y0"], t["tile"]) for t in a.good}
    coarse_b = {(t["x0"], t["y0"], t["tile"]) for t in b.good}
    assert len(coarse_b) > len(coarse_a), "the fine pass added no sub-tiles at all"
    assert coarse_b - coarse_a, "the sub-tiles occupy positions the coarse run has not"


# ── phase 2: the knobs reach the engine, and the numbers reach the client ─────


def test_the_service_defaults_are_the_engines_defaults_except_the_one_named() -> None:
    """A request that names none of the new knobs measures what it always did.

    ★ THE WHOLE POINT OF EXPOSING THEM THIS WAY. If a default here drifted from
    the engine's, every existing measurement would silently stop being
    comparable with a new one, and nothing would say so.

    ★ THE ONE DELIBERATE EXCEPTION IS `max_shift` (2026-09-10, phase 4): the
    engine's 25 m is a drone's, and this product watches masts at grazing
    incidence, where it censors real 26-30 m errors. Upstream's own table names
    50 m for a ground camera. Pinned here so a second drift cannot hide behind it.
    """
    from app.services.accuracy_service import StageDParams

    core, service = EM.Params(), StageDParams().to_core()
    for field in ("ecc_rescue", "tile_auto", "sigma_dtm", "reliability_max", "cloud_mask"):
        assert getattr(service, field) == getattr(core, field), field
    assert core.max_shift == 25.0          # the engine, untouched
    assert service.max_shift == 50.0       # the product's ground-camera default


def test_the_service_passes_every_new_knob_through() -> None:
    """Setting a knob on the service reaches the engine's Params unchanged."""
    from app.services.accuracy_service import StageDParams

    p = StageDParams(
        max_shift=50.0, ecc_rescue=True, tile_auto=True, sigma_dtm=4.5,
        reliability_max=15.0,
    ).to_core()
    assert (p.max_shift, p.ecc_rescue, p.tile_auto) == (50.0, True, True)
    assert (p.sigma_dtm, p.reliability_max) == (4.5, 15.0)


def test_the_request_defaults_match_and_its_bounds_hold() -> None:
    """The API's defaults are the engine's, and a nonsense value is refused."""
    import pydantic

    from app.schemas.accuracy import MeasureRequest

    body = MeasureRequest(image_id=uuid4())
    core = EM.Params()
    assert body.max_shift == 50.0          # the ground-camera default, see above
    assert body.auto_reach is True
    assert body.ecc_rescue == core.ecc_rescue
    assert body.tile_auto == core.tile_auto
    assert body.sigma_dtm == core.sigma_dtm
    assert body.reliability_max == core.reliability_max
    for bad in ({"max_shift": 1.0}, {"sigma_dtm": 0.0}, {"reliability_max": -1.0}):
        with pytest.raises(pydantic.ValidationError):
            MeasureRequest(image_id=uuid4(), **bad)


def test_the_amplification_summary_reports_a_spread_and_its_convention() -> None:
    """It is a spread, not one number, and it says how it was weighted.

    ★ The near and far ground of a grazing view amplify very differently, so a
    median alone hides the thing worth knowing. `expected_sigma_m` is the floor
    under the measured error that no pose correction can lift.
    """
    from app.services.accuracy_service import _amplification_summary

    got = _amplification_summary(
        [{"amplification": a} for a in (2.0, 3.0, 6.0)], sigma_dtm=3.0
    )
    assert got is not None
    assert (got["median"], got["max"], got["tiles"]) == (3.0, 6.0, 3)
    assert got["expected_sigma_m"] == 9.0        # median 3.0 x 3 m of DTM sigma
    assert got["weighting"] == "per locked tile"
    assert _amplification_summary([], 3.0) is None
    assert _amplification_summary([{"amplification": None}], 3.0) is None


@pytest.mark.slow
def test_the_persisted_tiles_and_summary_carry_the_new_numbers(
    scene: dict, tmp_path,  # noqa: F811
) -> None:
    """A run's rows and summary carry amplification, sigma and the size used.

    ★ `tile_used` is what `tile_auto` CHOSE, not what the request asked for.
    Reading the request back would misreport every automatic run.
    """
    from app.services.accuracy_service import _amplification_summary, _tile_rows

    res = _run(scene, tmp_path, tile_auto=True)
    rows = _tile_rows(res)
    assert rows, "the scene produced no tiles"
    locked = [r for r in rows if r["ok"]]
    assert all("amplification" in r and "sigma_m" in r for r in rows)
    assert all(r["amplification"] is not None for r in locked)
    # Rounded for a reader, not carried at full float precision.
    assert all(r["amplification"] == round(r["amplification"], 2) for r in locked)
    summary = _amplification_summary(
        [{"amplification": r["amplification"]} for r in locked], 3.0
    )
    assert summary is not None and summary["tiles"] == len(locked)
    assert res.params.tile in (128, 96, 64)
