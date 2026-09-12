"""The focal solve's seed (2026-09-09, owner ask): a typed field of view, or the
DEFAULT when it is left blank — and either way the focal is SOLVED, not assumed.

★ What these pin: ``seed_fov`` hands back the typed angle with the study's
bracket, or the 60° default with the wide one; the free-focal search started
from the default seed recovers the true focal of a synthetic camera whose real
field of view (43.6°) is nowhere near 60°; the library entry says which seed a
bundle was built from and what it solved to.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.intrinsics import (
    DEFAULT_FOV_H_DEG,
    DEFAULT_SEED_SPAN,
    TYPED_SEED_SPAN,
    k_from_fov,
    seed_fov,
)
from app.services.lut_service import manifest_intrinsics
from app.tests.test_drift_service import C, H, K, R_REF, W


class TestSeed:
    def test_a_typed_angle_is_used_as_given_with_the_studys_bracket(self) -> None:
        assert seed_fov(72.0) == (72.0, TYPED_SEED_SPAN, False)

    def test_a_blank_angle_becomes_the_default_with_the_wide_bracket(self) -> None:
        fov, span, defaulted = seed_fov(None)
        assert fov == DEFAULT_FOV_H_DEG and span == DEFAULT_SEED_SPAN and defaulted is True

    def test_the_default_bracket_spans_telephoto_to_wide(self) -> None:
        # fx range → equivalent field-of-view range, at the synthetic frame width
        fx0 = W / (2 * np.tan(np.radians(DEFAULT_FOV_H_DEG / 2)))
        lo = 2 * np.degrees(np.arctan(W / (2 * fx0 * (1 + DEFAULT_SEED_SPAN))))
        hi = 2 * np.degrees(np.arctan(W / (2 * fx0 * (1 - DEFAULT_SEED_SPAN))))
        assert lo < 40.0 and hi > 120.0


class TestSolveFromTheDefaultSeed:
    """The synthetic camera (drift tests): fx = 800 at 640 px → a 43.6° true field
    of view. Seeded at 60° the search must still land on 800."""

    @pytest.fixture()
    def correspondences(self) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(3)
        obj = []
        uv = []
        # ground points (Z = 0) spread across the view, projected through the truth
        while len(obj) < 12:
            u, v = rng.uniform(40, W - 40), rng.uniform(H * 0.45, H - 20)
            n = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
            d = R_REF.T @ (n / np.linalg.norm(n))
            if d[2] >= 0:
                continue
            t = -C[2] / d[2]
            p = C + t * d
            obj.append((p[0], p[1], 0.0))
            uv.append((u, v))
        return np.array(obj, float), np.array(uv, float)

    def test_the_true_focal_is_recovered_from_the_default_seed(
        self, correspondences: tuple[np.ndarray, np.ndarray]
    ) -> None:
        from app.vendor.lut_generator.pose import solve_pose_free_focal

        obj, uv = correspondences
        fov, span, defaulted = seed_fov(None)
        assert defaulted
        k_seed, dist, _ = k_from_fov(W, H, fov)
        assert abs(k_seed[0, 0] - 800.0) > 200  # the seed is genuinely far off
        _r, _c, rep, k_solved = solve_pose_free_focal(obj, uv, k_seed, dist, C, span=span)
        assert abs(k_solved[0, 0] - 800.0) / 800.0 < 0.01
        assert float(np.mean(rep)) < 0.5

    def test_the_typed_bracket_would_not_reach_it(
        self, correspondences: tuple[np.ndarray, np.ndarray]
    ) -> None:
        # ★ Why the DEFAULT seed gets a wider bracket: 800 sits at 1.44× the 60°
        #   seed's fx — inside 0.30–1.70 (default), outside a bracket that is
        #   narrower than ±44 %. Freeze the seed and the solve cannot reach it.
        from app.vendor.lut_generator.pose import solve_pose_free_focal

        obj, uv = correspondences
        k_seed, dist, _ = k_from_fov(W, H, DEFAULT_FOV_H_DEG)
        _r, _c, _rep, k_narrow = solve_pose_free_focal(obj, uv, k_seed, dist, C, span=0.2)
        assert abs(k_narrow[0, 0] - 800.0) / 800.0 > 0.05


class TestLibraryProvenance:
    def test_a_no_calibration_bundle_names_its_seed_and_its_solved_angle(self) -> None:
        manifest = {
            "pose": {
                "intrinsics_mode": "fov",
                "fov": {
                    "fov_h_seed_deg": 60.0,
                    "seed_defaulted": True,
                    "focal_solved": True,
                    "fx_solved": 812.3,
                    "fov_h_deg": 43.1,
                },
            }
        }
        info = manifest_intrinsics(manifest)
        assert info == {
            "mode": "fov",
            "fov_h_seed_deg": 60.0,
            "seed_defaulted": True,
            "focal_solved": True,
            "fov_h_solved_deg": 43.1,
            "fx_solved": 812.3,
        }

    def test_a_calibrated_bundle_has_no_intrinsics_story(self) -> None:
        assert manifest_intrinsics({"pose": {"K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}) is None
        assert manifest_intrinsics({}) is None
