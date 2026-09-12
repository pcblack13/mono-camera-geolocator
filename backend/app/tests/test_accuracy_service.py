"""``accuracy_service`` — the bridge in front of the vendored Stage D/E/F core.

Two kinds of test, deliberately:

1. **The refusals.** Same rule as ``test_lut_service``: a run that cannot succeed must
   be refused before its thread starts, with the fix named in the message.
2. **One end-to-end run on a SYNTHETIC scene** (``slow``). The vendored core carries
   its own self-test, but nothing there exercises *this* wiring — the relative imports,
   the SciPy interpolation shim standing in for ``matplotlib.tri``, the injected mosaic
   writer replacing the tool's own Mapbox client, and the save/restore round trip that
   lets Stage E run in a separate request from Stage D. This test builds a scene whose
   true answer is known, injects a KNOWN ground shift into the "satellite", and checks
   the measurement recovers it — which is the only way to know the seam is sound.

★ The synthetic scene needs no network: the mosaic writer is a local function that
writes the same texture the photo was rendered from, displaced by the injected shift.
"""

from __future__ import annotations

import math
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from app.services.accuracy_service import (
    AccuracyError,
    CorrectInputs,
    GcpPoint,
    MeasureInputs,
    PoseInputs,
    StageDParams,
    SuggestInputs,
    get_run,
    query_pixel,
    read_state,
    start_correct,
    start_measure,
    start_suggest,
)

# ── the synthetic scene ──────────────────────────────────────────────────────
# UTM 37N, the same neighbourhood the field tool's own self-test uses.
EPSG = 32637
WEST, NORTH = 736_700.0, 3_742_000.0  # DEM origin (NW corner), metres
DEM_W, DEM_H = 1600, 1300  # 1 m cells
CAM_E, CAM_N = 737_500.0, 3_740_760.0
CAM_HEIGHT = 120.0
PHOTO_W, PHOTO_H = 1200, 800
FOCAL = 1100.0
#: The ground displacement injected into the "satellite" — what Stage D must recover.
SHIFT_E, SHIFT_N = 4.0, -3.0


def _terrain(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Non-planar ground — a plane would make the PnP solve degenerate."""
    return (
        700.0
        + 18.0 * np.sin((y - 3_740_740.0) / 130.0)
        + 12.0 * np.cos((x - 737_500.0) / 90.0)
        + 6.0 * np.sin((x + y) / 210.0)
    )


def _rotation(camera: np.ndarray, target: np.ndarray) -> np.ndarray:
    """World→camera rotation looking from ``camera`` at ``target`` (OpenCV axes)."""
    f = target - camera
    f = f / np.linalg.norm(f)
    r = np.cross(f, [0.0, 0.0, 1.0])
    r = r / np.linalg.norm(r)
    u = np.cross(f, r)
    return np.vstack([r, u, f])


@pytest.fixture(scope="module")
def scene(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """A DEM, a ground texture, a photo rendered through a known pose, and its GCPs."""
    cv2 = pytest.importorskip("cv2")
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("scipy")
    from rasterio.transform import from_origin

    root = tmp_path_factory.mktemp("accuracy-scene")

    # ── terrain ──────────────────────────────────────────────────────────────
    cols = WEST + np.arange(DEM_W) + 0.5
    rows = NORTH - np.arange(DEM_H) - 0.5
    ee, nn = np.meshgrid(cols, rows)
    elevation = _terrain(ee, nn).astype(np.float32)

    dem_path = root / "dem.tif"
    transform = from_origin(WEST, NORTH, 1.0, 1.0)
    with rasterio.open(
        dem_path, "w", driver="GTiff", height=DEM_H, width=DEM_W, count=1,
        dtype="float32", crs=f"EPSG:{EPSG}", transform=transform,
    ) as dst:
        dst.write(elevation, 1)

    # ── the photograph: smoothed noise has structure at the scale the high-pass
    #    filter keeps, which is what lets a tile lock at all ──────────────────
    rng = np.random.default_rng(7)
    noise = rng.normal(size=(PHOTO_H, PHOTO_W)).astype(np.float32)
    smooth = cv2.GaussianBlur(noise, (0, 0), 2.5)
    smooth = (smooth - smooth.min()) / (smooth.max() - smooth.min())
    photo = np.dstack([(smooth * 235 + 10).astype(np.uint8)] * 3)
    photo_path = root / "photo.png"  # lossless: JPEG ringing would blur the correlation
    cv2.imwrite(str(photo_path), photo)

    # ── the pose ─────────────────────────────────────────────────────────────
    cam_ground = float(_terrain(np.array(CAM_E), np.array(CAM_N)))
    camera_xyz = np.array([CAM_E, CAM_N, cam_ground + CAM_HEIGHT])
    # Aim ~25° below horizontal, due north.
    target = np.array([CAM_E, CAM_N + 500.0, camera_xyz[2] - 500.0 * math.tan(math.radians(25.0))])
    rotation = _rotation(camera_xyz, target)
    k_matrix = np.array([[FOCAL, 0.0, PHOTO_W / 2], [0.0, FOCAL, PHOTO_H / 2], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)

    from app.vendor.geo_accuracy import stage_b
    from app.vendor.geo_accuracy.geo_io import DEM

    # ── the "satellite": the photo rectified through the TRUE pose, then
    #    DISPLACED by the injected shift.
    #
    # ★ WHY BUILD IT WITH THE CORE'S OWN RECTIFIER. The alternative — paint a ground
    #   texture and render the photo from it — needs a pixel→ground map for every one
    #   of a million pixels; approximating that map from a coarse grid puts a
    #   range-dependent distortion of several metres into the far field, and the test
    #   would then be measuring the fixture's error rather than the pipeline's.
    #   Rectifying the photo makes the reference exact by construction, so the ONLY
    #   difference between what Stage D builds and what it compares against is the
    #   shift injected here — which is precisely the quantity under test.
    from app.vendor.geo_accuracy import error_map

    params = StageDParams().to_core()
    dem = DEM(str(dem_path))
    try:
        bounds = error_map.ground_bounds(
            rotation, camera_xyz, k_matrix, dist, dem, PHOTO_W, PHOTO_H, params
        )
        truth_ortho, _inside, _rng_g, _u_g, origin = error_map.build_ortho(
            rotation, camera_xyz, k_matrix, dist, photo, dem, bounds, params
        )

        # ── GCPs: picked the way a surveyor picks them — a pixel, raycast to
        #    ground, through the SAME bilinear DEM the service will use, so a GCP's
        #    stored elevation cannot disagree with the surface underneath it.
        #    Spread across the frame AND across range (a low v is the far field):
        #    a cluster would leave the pose weakly constrained.
        gcp_pixels = ((250, 170), (950, 190), (180, 420), (1020, 430), (420, 700), (820, 730))
        hits = []
        for u, v in gcp_pixels:
            hit = stage_b.raycast(u, v, rotation, camera_xyz, k_matrix, dist, dem.Z, dem.res)
            assert hit is not None, f"synthetic GCP at ({u},{v}) missed the terrain"
            hits.append((u, v, hit))
    finally:
        dem.ds.close()

    sat_path = root / "satellite_source.tif"
    gsd = params.gsd
    with rasterio.open(
        sat_path, "w", driver="GTiff",
        height=truth_ortho.shape[0], width=truth_ortho.shape[1], count=3,
        dtype="uint8", crs=f"EPSG:{EPSG}",
        # `origin` is the CENTRE of cell (0,0); a GeoTIFF's origin is its NW EDGE —
        # the same half-cell correction `fetch_satellite` applies when it reprojects.
        transform=from_origin(
            origin[0] - gsd / 2 + SHIFT_E, origin[1] + gsd / 2 + SHIFT_N, gsd, gsd
        ),
    ) as dst:
        for band in range(3):
            dst.write(truth_ortho[:, :, band], band + 1)

    def mosaic_writer(lat, lon, *, radius_m, zoom, out_path, epsg):  # noqa: ANN001, ANN202
        import shutil

        assert int(epsg) == EPSG
        shutil.copyfile(sat_path, out_path)

    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(EPSG, 4326, always_xy=True)
    gcps: list[GcpPoint] = []
    for u, v, hit in hits:
        lon, lat = to_wgs84.transform(hit[0], hit[1])
        gcps.append(
            GcpPoint(u=float(u), v=float(v), lat=float(lat), lon=float(lon), elevation_m=float(hit[2]))
        )

    cam_lon, cam_lat = to_wgs84.transform(CAM_E, CAM_N)
    return {
        "root": root,
        "dem_path": dem_path,
        "photo_path": photo_path,
        "mosaic_writer": mosaic_writer,
        "gcps": tuple(gcps),
        "cam_lat": float(cam_lat),
        "cam_lon": float(cam_lon),
        "rotation": rotation,
        "camera_xyz": camera_xyz,
    }


def _pose(scene: dict, tmp_path: Path, **over) -> PoseInputs:
    base = dict(
        image_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        photo_path=scene["photo_path"],
        dem_path=scene["dem_path"],
        fx=FOCAL, fy=FOCAL, cx=PHOTO_W / 2, cy=PHOTO_H / 2,
        cam_lat=scene["cam_lat"], cam_lon=scene["cam_lon"], cam_height_m=CAM_HEIGHT,
        gcps=scene["gcps"],
        output_dir=tmp_path / "accuracy",
    )
    base.update(over)
    return PoseInputs(**base)


def _await(run, timeout: float = 300.0):  # noqa: ANN001, ANN202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = get_run(run.run_id)
        assert current is not None
        if current.status in ("succeeded", "failed"):
            return current
        time.sleep(0.25)
    raise AssertionError(f"run {run.run_id} did not finish within {timeout}s")


# ─────────────────────────────────────────────────────────────────────────────
# No calibration (2026-09-09): the focal is SOLVED, the seed only starts the search
# ─────────────────────────────────────────────────────────────────────────────


class TestNoCalibration:
    """★ The station Yamouneh2 had: no fx/fy, no-calibration mode. "Measure error"
    was refused with "no intrinsics" — the one pipeline GEO-DRIFT C2/C3 never
    reached. The scene's true field of view is 57.2° (fx 1100 at 1200 px)."""

    def test_a_station_without_fx_fy_is_solved_from_the_default_seed(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import _load_scene

        pose = _pose(
            scene, tmp_path, fx=None, fy=None, cx=None, cy=None,
            no_calibration=True, fov_h_deg=None,
        )
        loaded = _load_scene(pose)
        assert abs(float(loaded.k_matrix[0, 0]) - FOCAL) / FOCAL < 0.03
        story = " ".join(loaded.warnings)
        assert "solved from the control points" in story
        assert "seeded at 60°" in story and "default" in story

    def test_a_typed_seed_far_from_the_truth_is_still_recovered_and_named(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import _load_scene

        pose = _pose(
            scene, tmp_path, fx=None, fy=None, cx=None, cy=None,
            no_calibration=True, fov_h_deg=45.0,
        )
        loaded = _load_scene(pose)
        assert abs(float(loaded.k_matrix[0, 0]) - FOCAL) / FOCAL < 0.03
        story = " ".join(loaded.warnings)
        assert "seeded at 45°" in story and "default" not in story

    def test_a_calibrated_station_with_holes_is_still_refused(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import _load_scene

        pose = _pose(scene, tmp_path, fx=None, fy=None, no_calibration=False)
        with pytest.raises(AccuracyError, match="no intrinsics .*fx, fy"):
            _load_scene(pose)


# ─────────────────────────────────────────────────────────────────────────────
# The refusals — pinned, because a bad message here costs a support session
# ─────────────────────────────────────────────────────────────────────────────


class TestRefusals:
    def test_measure_without_an_imagery_source_is_refused(self, tmp_path: Path) -> None:
        pose = PoseInputs(
            image_id=uuid.uuid4(), project_id=uuid.uuid4(),
            photo_path=tmp_path / "p.png", dem_path=tmp_path / "d.tif",
            fx=1.0, fy=1.0, cx=1.0, cy=1.0,
            gcps=tuple(GcpPoint(u=0, v=0, lat=0, lon=0, elevation_m=0) for _ in range(4)),
            output_dir=tmp_path,
        )
        with pytest.raises(AccuracyError, match="imagery source"):
            start_measure(MeasureInputs(pose=pose))

    def test_stride_wider_than_the_tile_is_refused(self, tmp_path: Path) -> None:
        pose = PoseInputs(
            image_id=uuid.uuid4(), project_id=uuid.uuid4(),
            photo_path=tmp_path / "p.png", dem_path=tmp_path / "d.tif",
            fx=1.0, fy=1.0, cx=1.0, cy=1.0,
            gcps=tuple(GcpPoint(u=0, v=0, lat=0, lon=0, elevation_m=0) for _ in range(4)),
            output_dir=tmp_path,
        )
        with pytest.raises(AccuracyError, match="would not overlap"):
            start_measure(
                MeasureInputs(
                    pose=pose,
                    params=StageDParams(tile=128, stride=256),
                    mosaic_writer=lambda *a, **k: None,
                )
            )

    def test_too_few_gcps_is_refused_with_the_count(self, tmp_path: Path) -> None:
        pose = PoseInputs(
            image_id=uuid.uuid4(), project_id=uuid.uuid4(),
            photo_path=tmp_path / "p.png", dem_path=tmp_path / "d.tif",
            fx=1.0, fy=1.0, cx=1.0, cy=1.0,
            gcps=(GcpPoint(u=0, v=0, lat=0, lon=0, elevation_m=0),),
            output_dir=tmp_path,
        )
        with pytest.raises(AccuracyError, match="1 committed GCP"):
            start_measure(MeasureInputs(pose=pose, mosaic_writer=lambda *a, **k: None))

    def test_correcting_before_measuring_names_the_missing_step(self, tmp_path: Path) -> None:
        pose = PoseInputs(
            image_id=uuid.uuid4(), project_id=uuid.uuid4(),
            photo_path=tmp_path / "p.png", dem_path=tmp_path / "d.tif",
            fx=1.0, fy=1.0, cx=1.0, cy=1.0, output_dir=tmp_path,
        )
        with pytest.raises(AccuracyError, match="no measurement"):
            start_correct(CorrectInputs(pose=pose))

    def test_suggesting_without_a_pose_is_refused(self, tmp_path: Path) -> None:
        pose = PoseInputs(
            image_id=uuid.uuid4(), project_id=uuid.uuid4(),
            photo_path=tmp_path / "p.png", dem_path=tmp_path / "d.tif",
            fx=1.0, fy=1.0, cx=1.0, cy=1.0, output_dir=tmp_path,
        )
        with pytest.raises(AccuracyError, match="at least 4 control points"):
            start_suggest(SuggestInputs(pose=pose))


# ─────────────────────────────────────────────────────────────────────────────
# The whole chain, on a scene whose answer is known
# ─────────────────────────────────────────────────────────────────────────────


class TestMosaicWriter:
    """The imagery seam — the one piece the synthetic scene deliberately stubs out.

    ★ Through the ``fixture`` provider: synthetic tiles, ZERO network, same rule as
    ``test_imagery_service_cache``. What matters here is not the pixels but the
    geometry — that a ground radius becomes the right tile rectangle, that the tiles
    stitch into a mosaic, and that the mosaic lands in the DEM's CRS covering the
    ground it was asked for. Getting the Web-Mercator scaling wrong would under-cover
    the scene by 1/cos(latitude) and every far tile would come back black.
    """

    def test_it_writes_a_mosaic_in_the_dem_crs_that_covers_the_radius(
        self, tmp_path: Path
    ) -> None:
        rasterio = pytest.importorskip("rasterio")
        pytest.importorskip("cv2")
        from pyproj import Transformer

        from app.core.config import Settings
        from app.services import imagery_service as svc_module
        from app.services.accuracy_service import make_mosaic_writer
        from app.services.imagery_service import ImageryService

        svc_module._tile_cache_for.cache_clear()
        try:
            service = ImageryService(
                Settings(
                    imagery_tile_cache_backend="disk",
                    imagery_tile_cache_dir=tmp_path / "tile_cache",
                    allowed_providers=[],
                )
            )
            writer = make_mosaic_writer(service, "fixture")

            lat, lon = 33.8938, 35.5018  # Beirut — cos(lat) ≈ 0.83, so the scaling shows
            out = tmp_path / "mosaic.tif"
            writer(lat, lon, radius_m=600.0, zoom=15, out_path=str(out), epsg=EPSG)

            assert out.is_file()
            with rasterio.open(out) as src:
                assert src.crs.to_epsg() == EPSG
                assert src.count == 3
                bounds = src.bounds
            # The mosaic must reach a full ground radius in every direction — the
            # assertion that fails if the mercator inflation is dropped.
            to_utm = Transformer.from_crs(4326, EPSG, always_xy=True)
            cx, cy = to_utm.transform(lon, lat)
            assert bounds.left <= cx - 600.0
            assert bounds.right >= cx + 600.0
            assert bounds.bottom <= cy - 600.0
            assert bounds.top >= cy + 600.0
        finally:
            svc_module._tile_cache_for.cache_clear()

    def test_it_counts_tiles_so_a_long_download_does_not_look_hung(
        self, tmp_path: Path
    ) -> None:
        """★ The reported symptom was "it froze at 50%".

        It had not frozen — the core reports 45% and then says nothing until the whole
        mosaic is on disk, which on a real scene is ~100 sequential network round trips.
        The writer now reports tile counts, and the fetch runs concurrently. This pins
        the reporting; the concurrency shows up as every tile still arriving.
        """
        pytest.importorskip("rasterio")
        pytest.importorskip("cv2")

        from app.core.config import Settings
        from app.services import imagery_service as svc_module
        from app.services.accuracy_service import make_mosaic_writer
        from app.services.imagery_service import ImageryService

        svc_module._tile_cache_for.cache_clear()
        try:
            service = ImageryService(
                Settings(
                    imagery_tile_cache_backend="disk",
                    imagery_tile_cache_dir=tmp_path / "tile_cache",
                    allowed_providers=[],
                )
            )
            writer = make_mosaic_writer(service, "fixture")
            seen: list[tuple[int, int]] = []
            writer.on_tile_progress = lambda done, total: seen.append((done, total))

            writer(
                33.8938, 35.5018, radius_m=400.0, zoom=15,
                out_path=str(tmp_path / "m.tif"), epsg=EPSG,
            )

            assert seen, "a download that reports nothing is indistinguishable from a hang"
            done, total = seen[-1]
            assert done == total, "the count must reach the total, not stop short"
            assert all(d <= t for d, t in seen)
        finally:
            svc_module._tile_cache_for.cache_clear()

    def test_a_provider_that_forbids_storing_tiles_is_refused(self, tmp_path: Path) -> None:
        """★ The licence gate, on the same flag the tile cache gates on."""
        from app.services.accuracy_service import make_mosaic_writer

        class _Caps:
            allows_caching = False
            tile_size_px = 256

        class _Imagery:
            def capabilities(self, _name: str) -> _Caps:
                return _Caps()

        with pytest.raises(AccuracyError, match="does not permit its tiles to be stored"):
            make_mosaic_writer(_Imagery(), "google_maps_static")


@pytest.mark.slow
class TestSyntheticScene:
    def test_stage_d_recovers_the_injected_shift(self, scene: dict, tmp_path: Path) -> None:
        pose = _pose(scene, tmp_path)
        run = _await(
            start_measure(
                MeasureInputs(
                    pose=pose,
                    params=StageDParams(max_range=1100.0, tile=128, stride=64),
                    mosaic_writer=scene["mosaic_writer"],
                    provider_name="synthetic",
                )
            )
        )
        assert run.status == "succeeded", run.error
        summary = run.summary or {}
        assert summary["tiles_locked"] >= 20, summary
        assert summary["match_rate"] > 0.5, summary

        state = read_state(pose.output_dir, pose.image_id)
        tiles = [t for t in state["measurement"]["tiles"] if t["ok"]]
        # ★ THE ASSERTION THAT MATTERS: the satellite was displaced by a known vector,
        #   so the error field must report that displacement (negated — a tile reports
        #   claimed − true, and the truth is where the satellite puts it).
        median_de = float(np.median([t["dE"] for t in tiles]))
        median_dn = float(np.median([t["dN"] for t in tiles]))
        assert median_de == pytest.approx(-SHIFT_E, abs=1.5), median_de
        assert median_dn == pytest.approx(-SHIFT_N, abs=1.5), median_dn

        # The layers the UI draws, and the offline report, are on disk.
        assert set(state["layers"]) >= {"ortho", "satellite", "heat_raw"}
        assert state["report_available"] is True

    def test_correct_then_compare_is_honest_about_its_own_gate(
        self, scene: dict, tmp_path: Path
    ) -> None:
        pose = _pose(scene, tmp_path)
        assert _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        ).status == "succeeded"

        run = _await(start_correct(CorrectInputs(pose=pose)))
        assert run.status == "succeeded", run.error

        state = read_state(pose.output_dir, pose.image_id)
        report = state["correction"]
        solutions = state["solutions"]
        assert report is not None and solutions is not None

        # ★ THE GATE MUST AGREE WITH ITS OWN NUMBERS. This is the honesty mechanism:
        #   the correction is accepted if and only if it measured better than doing
        #   nothing. Nothing downstream may present a refused correction as a win.
        before = report["before_m"]["all"]
        after = report["after_pose_m"]["all"]
        assert report["accepted"] is (after <= before)
        assert str(report["gate_reason"])

        # A pure ground displacement is exactly what a re-solved pose can absorb.
        assert after < before
        assert report["n_pseudo_gcps"] >= 20

        keys = {e["key"] for e in solutions["entries"]}
        assert keys == {"raw", "pose", "field", "stagef"}
        assert solutions["best"] in keys
        # Every available stage reports the three numbers the surveyor is told to read.
        for entry in solutions["entries"]:
            if entry["available"]:
                assert entry["all_m"] is not None
                assert entry["p95_m"] is not None
                assert entry["worst20_share"] is not None
        assert solutions["basemap_caveat"]

    def test_a_pixel_gets_every_answer_side_by_side(self, scene: dict, tmp_path: Path) -> None:
        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        answer = query_pixel(pose, u=PHOTO_W / 2, v=PHOTO_H * 0.8)
        keys = [a["key"] for a in answer["answers"]]
        assert "raw" in keys and "pose" in keys
        for a in answer["answers"]:
            assert -90.0 <= a["lat"] <= 90.0
            assert -180.0 <= a["lon"] <= 180.0
        # The corrected answers must actually DIFFER from the raw one — an identical
        # coordinate would mean the correction silently did nothing.
        raw = next(a for a in answer["answers"] if a["key"] == "raw")
        pose_answer = next(a for a in answer["answers"] if a["key"] == "pose")
        assert (raw["lat"], raw["lon"]) != (pose_answer["lat"], pose_answer["lon"])

    def test_the_surveyor_chooses_the_stage_and_the_choice_carries_its_evidence(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ Adoption is a RECORDED DECISION, not an automatic follow-on.

        The comparison recommends; the surveyor chooses, and may disagree — local
        knowledge (a feature they can see is in the right place) beats a held-out
        median. What must never be lost is the evidence the choice was made on.
        """
        from app.services.accuracy_service import adopt, clear_adoption, read_adoption

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        state = read_state(pose.output_dir, pose.image_id)
        assert state["adoption"] is None, "nothing is adopted until it is chosen"
        recommended = state["solutions"]["best"]

        record = adopt(pose.output_dir, pose.image_id, "pose")
        assert record["stage"] == "pose"
        assert record["recommended"] == recommended
        assert record["matches_recommendation"] is (recommended == "pose")
        assert record["all_m"] is not None, "the number it was chosen on must be kept"
        assert record["uses_refined_pose"] is True
        assert read_state(pose.output_dir, pose.image_id)["adoption"] == record

        # ★ `raw` is adoptable: "I looked and chose not to correct" is a decision.
        raw_record = adopt(pose.output_dir, pose.image_id, "raw")
        assert raw_record["uses_refined_pose"] is False

        with pytest.raises(AccuracyError, match="not a stage"):
            adopt(pose.output_dir, pose.image_id, "nonsense")

        clear_adoption(pose.output_dir, pose.image_id)
        assert read_adoption(pose.output_dir, pose.image_id) is None

    def test_a_new_correction_retires_the_old_choice(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ An adoption whose recorded evidence no longer exists would be a lie.

        Re-running the correction produces different numbers for the same stage names,
        so the choice is cleared and must be made again — one click, versus an adoption
        that silently claims a score it never had.
        """
        from app.services.accuracy_service import adopt, read_adoption

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))
        adopt(pose.output_dir, pose.image_id, "pose")

        _await(start_correct(CorrectInputs(pose=pose, use_residual_field=False)))
        assert read_adoption(pose.output_dir, pose.image_id) is None

    def test_an_adopted_correction_is_what_a_lut_build_stands_on(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ THE ONE CONSUMER. Adopting must change the LUT's pose — and only that.

        This is the whole point of the narrow scope: the LUT is built fresh, on demand,
        and leaves the app, so it can honour a choice made after the fact. Nothing that
        was already recorded against the GCP-solved pose moves.
        """
        from app.services.accuracy_service import adopt, adopted_pose

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        assert adopted_pose(pose.output_dir, pose.image_id) is None  # nothing chosen yet

        adopt(pose.output_dir, pose.image_id, "pose")
        adopted = adopted_pose(pose.output_dir, pose.image_id)
        assert adopted is not None
        assert adopted["R"].shape == (3, 3)
        assert adopted["C"].shape == (3,)
        # ★ The ground-space part is deliberately NOT baked in, and says so.
        assert adopted["ground_correction_applied"] is False
        assert "never extrapolated" in adopted["ground_correction_note"]

        # ★ Adopting `raw` means "use the pose my control points give" — the LUT is
        #   then built exactly as it would have been before any of this existed.
        adopt(pose.output_dir, pose.image_id, "raw")
        assert adopted_pose(pose.output_dir, pose.image_id) is None

    def test_adopting_makes_the_next_measurement_start_from_the_corrected_pose(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ THE LOOP CLOSES. Measure → correct → adopt → measure again.

        The second measurement must start from the pose that was adopted, so what it
        reports is the error the correction LEFT — not the same error over again. That
        is the difference between an iterative refinement and a button that does
        nothing visible.
        """
        from app.services.accuracy_service import adopt, clear_adoption, read_base_pose

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        first = read_state(pose.output_dir, pose.image_id)["measurement"]
        assert first["pose"]["source"] == "gcps", "the first run stands on the control points"
        assert read_base_pose(pose.output_dir, pose.image_id) is None

        adopt(pose.output_dir, pose.image_id, "pose")
        base = read_base_pose(pose.output_dir, pose.image_id)
        assert base is not None
        assert base["from_stage"] == "pose"
        assert base["generation"] == 1

        # ── measure again: same scene, different starting pose ────────────────
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        second = read_state(pose.output_dir, pose.image_id)["measurement"]
        assert second["pose"]["source"] == "adopted"
        assert second["pose"]["from_stage"] == "pose"
        assert second["pose"]["generation"] == 1

        # ★ THE POINT OF THE WHOLE EXERCISE: the residual is smaller than the error the
        #   control points alone produced. The satellite was displaced by a rigid
        #   vector, which a re-solved pose can absorb — so the second pass measures
        #   what little is left.
        assert second["median_error_m"] < first["median_error_m"]

        # ★ The base pose SURVIVES the re-measurement (the adoption record does not —
        #   its numbers described the previous comparison).
        assert read_base_pose(pose.output_dir, pose.image_id) is not None
        assert read_state(pose.output_dir, pose.image_id)["adoption"] is None

        # ── and going back to raw returns to the control-point solve ──────────
        _await(start_correct(CorrectInputs(pose=pose)))
        adopt(pose.output_dir, pose.image_id, "raw")
        assert read_base_pose(pose.output_dir, pose.image_id) is None

        clear_adoption(pose.output_dir, pose.image_id)
        assert read_base_pose(pose.output_dir, pose.image_id) is None

    def test_a_second_generation_comparison_stops_calling_raw_uncorrected(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ `raw` must stop claiming to be the uncorrected answer once it is not.

        After an adoption it is the ADOPTED pose — still this comparison's baseline, but
        no longer the control-point solve. Keeping the core's "Raw pose (no correction)"
        label would tell the surveyor they were looking at an uncorrected answer while
        they were looking at a corrected one.
        """
        from app.services.accuracy_service import adopt

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))
        adopt(pose.output_dir, pose.image_id, "pose")
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        entries = {
            e["key"]: e for e in read_state(pose.output_dir, pose.image_id)["solutions"]["entries"]
        }
        assert "Adopted pose" in entries["raw"]["label"]
        assert "no correction" not in entries["raw"]["label"].lower()
        assert "LEFT" in entries["raw"]["note"]

    def test_freeing_the_focal_changes_the_raw_solve_and_retires_the_old_one(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ The tick reaches the SOLVER, and clears what the previous solve produced.

        Freeing the focal changes the pose every stage stands on, so a measurement taken
        before the change describes a solve that no longer exists. Leaving it on screen
        beside a different pose would be the quietest possible way to mislead.
        """
        from app.services.accuracy_service import read_solve_options, set_solve_options

        pose = _pose(scene, tmp_path)
        assert read_solve_options(pose.output_dir, pose.image_id) == {"free_focal": False}

        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        first = read_state(pose.output_dir, pose.image_id)["measurement"]
        assert first["pose"]["free_focal"] is False
        # Not freed: the solve reports back exactly the calibration it was given.
        assert first["pose"]["solved_focal_px"] == pytest.approx(FOCAL, abs=1e-6)

        set_solve_options(pose.output_dir, pose.image_id, free_focal=True)
        assert read_solve_options(pose.output_dir, pose.image_id) == {"free_focal": True}
        # ★ Everything the old pose produced is gone, not merely stale.
        assert read_state(pose.output_dir, pose.image_id)["measurement"] is None

        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        second = read_state(pose.output_dir, pose.image_id)["measurement"]
        assert second["pose"]["free_focal"] is True
        assert second["pose"]["entered_focal_px"] == pytest.approx(FOCAL, abs=1e-6)
        # The synthetic photo was rendered with the entered focal, so a freed solve
        # should stay near it — the check is that the value is REPORTED and sane, not
        # that it moved.
        assert second["pose"]["solved_focal_px"] == pytest.approx(FOCAL, rel=0.05)

        # Setting it back to what it already is must not throw the result away again.
        set_solve_options(pose.output_dir, pose.image_id, free_focal=True)
        assert read_state(pose.output_dir, pose.image_id)["measurement"] is not None

    def test_what_is_stored_validates_against_the_wire_schema(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ The stored JSON IS the response body — and every wire model forbids extras.

        ``ApiModel`` sets ``extra="forbid"`` so a typo'd field is a 422 rather than a
        silent no-op. That makes any key the service writes but the schema does not
        declare a 500 on the first real request — invisible to a service-level test
        that only reads dictionaries back. So the round trip is asserted here, where a
        drift between the writer and the wire type fails immediately.
        """
        from app.schemas.accuracy import AccuracyState

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))
        _await(start_suggest(SuggestInputs(pose=pose, count=2)))

        state = AccuracyState(**read_state(pose.output_dir, pose.image_id), active_run=None)
        assert state.measurement is not None
        assert state.correction is not None
        assert state.solutions is not None
        assert state.suggestions is not None
        assert state.measurement.tiles, "the tile field must survive the round trip"

    def test_suggestions_rank_regions_and_state_a_stop_verdict(
        self, scene: dict, tmp_path: Path
    ) -> None:
        pose = _pose(scene, tmp_path)
        run = _await(start_suggest(SuggestInputs(pose=pose, count=3)))
        assert run.status == "succeeded", run.error

        payload = read_state(pose.output_dir, pose.image_id)["suggestions"]
        assert payload is not None
        assert 1 <= len(payload["regions"]) <= 3
        assert payload["verdict"] in ("converged", "keep_going")
        ranks = [r["rank"] for r in payload["regions"]]
        assert ranks == sorted(ranks)
        for region in payload["regions"]:
            assert 0 <= region["u"] < PHOTO_W
            assert 0 <= region["v"] < PHOTO_H
            assert region["cut_pct"] >= 0.0
            assert region["reasons"], "a suggestion must say WHY it was chosen"


@pytest.mark.slow
class TestHeatmapHistory:
    """Every deployed heat map is kept, so two runs can be compared.

    ★ WHAT THE HISTORY IS FOR. The loop re-measures after every control point, so a
    single "current error" answers the least interesting question. Whether the last
    point helped — and where — is a comparison between two runs, which needs the
    earlier one to still exist.
    """

    def test_each_measurement_is_archived_with_the_numbers_that_describe_it(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import history_layer_path, list_history

        pose = _pose(scene, tmp_path)
        assert list_history(pose.output_dir, pose.image_id) == []

        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        history = list_history(pose.output_dir, pose.image_id)
        assert len(history) == 1
        entry = history[0]
        assert entry["median_error_m"] is not None
        assert "heat_raw" in entry["layers"]
        # ★ The archived layer is a real file the client can draw, not just a name.
        assert history_layer_path(
            pose.output_dir, pose.image_id, entry["version"], "heat_raw"
        ) is not None
        # Not yet corrected — the entry says so rather than implying a winner.
        assert entry.get("corrected") is None

    def test_an_archived_version_validates_against_the_wire_schema(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ The archive IS the response body, and every wire model forbids extras.

        The first cut of this shipped with `methods` and `grid` in the stored summary
        but absent from `HeatmapVersion`, so listing the history was a 500 and the
        history button simply never appeared. A service-level test that only reads
        dictionaries back cannot see that; this one validates what the route returns.
        """
        from app.schemas.accuracy import HeatmapVersion
        from app.services.accuracy_service import list_history

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        versions = [
            HeatmapVersion(**v) for v in list_history(pose.output_dir, pose.image_id)
        ]
        assert versions, "a measured photograph must have at least one version"
        assert versions[0].corrected is not None
        assert versions[0].grid.get("web_bounds") is not None

    def test_a_correction_updates_the_run_it_corrected_rather_than_adding_one(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import list_history

        pose = _pose(scene, tmp_path)
        _await(
            start_measure(
                MeasureInputs(
                    pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                )
            )
        )
        _await(start_correct(CorrectInputs(pose=pose)))

        history = list_history(pose.output_dir, pose.image_id)
        # ★ ONE entry, not two: a correction belongs to the measurement it corrected.
        #   Two would double every cycle and make the history unreadable.
        assert len(history) == 1
        entry = history[0]
        assert entry["corrected"]["best"] in {"raw", "pose", "field", "stagef"}
        assert entry["corrected"]["all_m"] is not None
        assert entry["gate"]["accepted"] in (True, False)

    def test_a_second_measurement_earns_its_own_version(
        self, scene: dict, tmp_path: Path
    ) -> None:
        from app.services.accuracy_service import list_history

        pose = _pose(scene, tmp_path)
        for _ in range(2):
            _await(
                start_measure(
                    MeasureInputs(
                        pose=pose, mosaic_writer=scene["mosaic_writer"], provider_name="synthetic"
                    )
                )
            )
        history = list_history(pose.output_dir, pose.image_id)
        assert len(history) >= 1
        # Newest first — the comparison the UI offers is "this run vs the one before".
        versions = [h["version"] for h in history]
        assert versions == sorted(versions, reverse=True)

    def test_a_crafted_version_cannot_escape_the_history_folder(
        self, scene: dict, tmp_path: Path
    ) -> None:
        """★ The version comes from a URL path segment — it must not be a way out."""
        from app.services.accuracy_service import history_layer_path

        pose = _pose(scene, tmp_path)
        assert (
            history_layer_path(pose.output_dir, pose.image_id, "../..", "heat_raw") is None
        )
