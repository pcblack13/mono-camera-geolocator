"""Tests for ``gis.accuracy`` (§13.1 IU-09, §4.20).

★ THE DIRECTION GOLDEN lives here. It fails under EITHER wrong sign of the cos
correction, which is the property that makes it worth having: both directions are
plausible on inspection and only one is safe.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gis.accuracy import (
    CE90_FROM_SIGMA_2D,
    CE95_FROM_SIGMA_2D,
    DEFAULT_CLICK_SIGMA_PX,
    AccuracyEstimate,
    combine_accuracy,
    manual_gcp_accuracy,
    pixel_cov_to_metres,
    rmse_px_to_ce90_m,
)
from gis.tiles import resolution_at


class TestConstants:
    def test_ce90_and_ce95(self) -> None:
        """The 2-D circular radii, in units of sigma. Recorded so nobody re-derives 2.0."""
        assert CE90_FROM_SIGMA_2D == 2.1460
        assert CE95_FROM_SIGMA_2D == 2.4477

    def test_two_sigma_is_not_95_percent(self) -> None:
        """★ The mistake the constants exist to prevent.

        2-sigma on a 2-D error ellipse's semi-major is ~86.5%, NOT 95%. The 2-D 95%
        radius is 2.448 sigma. A "+/-0.3 m at 95%" that is really 86.5% is a claim a
        surveyor may file against.
        """
        # Rayleigh CDF: P(r <= k*sigma) = 1 - exp(-k^2/2).
        assert 1.0 - math.exp(-(2.0**2) / 2.0) == pytest.approx(0.8647, abs=1e-4)
        assert 1.0 - math.exp(-(CE90_FROM_SIGMA_2D**2) / 2.0) == pytest.approx(0.90, abs=1e-4)
        assert 1.0 - math.exp(-(CE95_FROM_SIGMA_2D**2) / 2.0) == pytest.approx(0.95, abs=1e-4)


class TestDirectionGolden:
    """★★ THE ACCURACY DIRECTION GOLDEN (§13.1 IU-09)."""

    def test_direction_golden(self) -> None:
        """``cov_px = I2`` at z=18, phi=55 => ``sqrt(lambda_max(Sigma_true)) == 0.34251936163340246``.

        This is exactly ``resolution_at(18, 55.0)``. It fails under EITHER wrong sign of
        the cos correction:
          * multiplying by 1/cos    -> 0.597 (over-conservative: hides the real accuracy)
          * multiplying by 1/cos^2  -> 1.04  (the same error compounded)
          * omitting the correction -> 0.597 (measuring in Mercator metres)
        """
        gsd = resolution_at(18, 55.0)
        sigma = pixel_cov_to_metres(np.eye(2), gsd)
        lam_max = float(np.max(np.linalg.eigvalsh(sigma)))
        assert math.sqrt(lam_max) == 0.34251936163340246

    def test_golden_equals_the_resolution_exactly(self) -> None:
        """A unit pixel covariance must be exactly one GSD of ground error. No slack."""
        gsd = resolution_at(18, 55.0)
        sigma = pixel_cov_to_metres(np.eye(2), gsd)
        assert math.sqrt(float(np.max(np.linalg.eigvalsh(sigma)))) == gsd

    def test_wrong_direction_would_be_caught(self) -> None:
        """Demonstrate the magnitude of the bug the golden guards: 3.04x at 55N."""
        gsd = resolution_at(18, 55.0)
        cos_phi = math.cos(math.radians(55.0))
        wrong = gsd / cos_phi  # the naive "multiply by the quoted 1/cos(phi)"
        assert wrong / gsd == pytest.approx(1.0 / cos_phi, rel=1e-9)
        assert wrong / gsd > 1.7  # linear error inflated by 74% ...
        assert (wrong / gsd) ** 2 > 3.0  # ... and variance by 3.04x


class TestPixelCovToMetres:
    def test_default_path_scales_by_gsd_squared(self) -> None:
        cov = np.array([[4.0, 1.0], [1.0, 9.0]])
        out = pixel_cov_to_metres(cov, 0.5)
        # Variances scale by gsd^2; the y-flip negates the off-diagonal.
        assert out[0, 0] == pytest.approx(4.0 * 0.25)
        assert out[1, 1] == pytest.approx(9.0 * 0.25)
        assert out[0, 1] == pytest.approx(-1.0 * 0.25)

    def test_y_flip_into_enu(self) -> None:
        """★ Window v grows SOUTH; ENU Y grows NORTH. The flip negates the covariance.

        Without it, an error trending NE in the window is reported as trending SE — a
        mirrored ellipse, plausible in magnitude and wrong in direction.
        """
        cov = np.array([[1.0, 0.5], [0.5, 1.0]])  # positive correlation: x and v rise together
        out = pixel_cov_to_metres(cov, 1.0)
        assert out[0, 1] < 0, "east/north correlation must invert relative to east/south"

    def test_eigenvalues_are_invariant_under_the_flip(self) -> None:
        """The flip is a reflection: it cannot change magnitudes, only bearings.

        This is why the direction golden and the y-flip cannot conflict.
        """
        cov = np.array([[4.0, 1.5], [1.5, 2.0]])
        flipped = pixel_cov_to_metres(cov, 1.0)
        assert np.allclose(
            np.linalg.eigvalsh(flipped), np.linalg.eigvalsh(cov)
        )

    def test_geotransform_path_multiplies_by_cos_squared(self) -> None:
        """★ MULTIPLY by cos^2 — the projected metre is INFLATED by 1/cos(phi)."""
        lat = 55.0
        res_3857 = resolution_at(18, 0.0)  # a 3857 gt's coefficient is the un-corrected one
        gt = (0.0, res_3857, 0.0, 0.0, 0.0, -res_3857)
        out = pixel_cov_to_metres(np.eye(2), 0.0, gt=gt, lat=lat)
        got = math.sqrt(float(np.max(np.linalg.eigvalsh(out))))
        # The gt path must land on the same answer as the preferred path.
        assert got == pytest.approx(resolution_at(18, lat), rel=1e-12)

    def test_gt_path_agrees_with_default_path(self) -> None:
        """The two paths are two routes to one number. They must not disagree."""
        lat = 55.0
        res_3857 = resolution_at(18, 0.0)
        gt = (0.0, res_3857, 0.0, 0.0, 0.0, -res_3857)
        cov = np.array([[2.0, 0.3], [0.3, 5.0]])
        via_gt = pixel_cov_to_metres(cov, 0.0, gt=gt, lat=lat)
        via_gsd = pixel_cov_to_metres(cov, resolution_at(18, lat))
        assert np.allclose(via_gt, via_gsd, rtol=1e-9)

    def test_requires_both_gt_and_lat(self) -> None:
        """★ A gt without a lat would silently return PROJECTED metres."""
        gt = (0.0, 0.6, 0.0, 0.0, 0.0, -0.6)
        with pytest.raises(ValueError, match="BOTH"):
            pixel_cov_to_metres(np.eye(2), 1.0, gt=gt)
        with pytest.raises(ValueError, match="BOTH"):
            pixel_cov_to_metres(np.eye(2), 1.0, lat=55.0)

    def test_rejects_bad_covariance(self) -> None:
        with pytest.raises(ValueError, match=r"\(2,2\)"):
            pixel_cov_to_metres(np.eye(3), 1.0)
        with pytest.raises(ValueError, match="non-finite"):
            pixel_cov_to_metres(np.array([[np.nan, 0.0], [0.0, 1.0]]), 1.0)

    def test_rejects_bad_gsd(self) -> None:
        with pytest.raises(ValueError, match="gsd_m"):
            pixel_cov_to_metres(np.eye(2), 0.0)
        with pytest.raises(ValueError, match="gsd_m"):
            pixel_cov_to_metres(np.eye(2), -1.0)

    def test_symmetrises(self) -> None:
        """Rounding-asymmetric input must not silently use one triangle."""
        cov = np.array([[1.0, 0.5], [0.5000000001, 1.0]])
        out = pixel_cov_to_metres(cov, 1.0)
        assert out[0, 1] == pytest.approx(out[1, 0])


class TestCombineAccuracy:
    def test_every_field_is_ce90(self) -> None:
        est = combine_accuracy(np.zeros((2, 2)), 0.5, 2.0, 3.0)
        assert est.confidence_level == "ce90"
        assert isinstance(est, AccuracyEstimate)

    def test_click_and_fit_are_disjoint(self) -> None:
        """``Sigma_win = cov_px + click^2 * I``. The two inputs must not double-count."""
        gsd = 1.0
        fit = np.array([[4.0, 0.0], [0.0, 4.0]])
        both = combine_accuracy(fit, gsd, 0.0, 3.0)
        expected_sigma = math.sqrt(4.0 + 9.0)
        assert both.relative_ce90_m == pytest.approx(CE90_FROM_SIGMA_2D * expected_sigma)

    def test_total_is_quadrature_of_same_level_terms(self) -> None:
        est = combine_accuracy(np.zeros((2, 2)), 0.5, 3.0, 2.0)
        assert est.total_ce90_m == pytest.approx(
            math.hypot(est.relative_ce90_m, est.georef_ce90_m)
        )

    def test_anisotropy_is_kept(self) -> None:
        """★ Collapsing the ellipse throws away the most actionable part of the estimate."""
        cov = np.array([[100.0, 0.0], [0.0, 1.0]])  # 10x more uncertain east-west
        est = combine_accuracy(cov, 1.0, 0.0, 0.0)
        assert est.semi_major_ce90_m > est.semi_minor_ce90_m
        assert est.semi_major_ce90_m / est.semi_minor_ce90_m == pytest.approx(10.0, rel=1e-6)

    def test_azimuth_of_an_east_west_ellipse_is_90(self) -> None:
        """Major axis along EAST => bearing 90 (0 = North, clockwise)."""
        cov = np.array([[100.0, 0.0], [0.0, 1.0]])
        est = combine_accuracy(cov, 1.0, 0.0, 0.0)
        assert est.azimuth_deg == pytest.approx(90.0, abs=1e-6)

    def test_azimuth_of_a_north_south_ellipse_is_0(self) -> None:
        cov = np.array([[1.0, 0.0], [0.0, 100.0]])
        est = combine_accuracy(cov, 1.0, 0.0, 0.0)
        assert est.azimuth_deg == pytest.approx(0.0, abs=1e-6)

    def test_azimuth_respects_the_y_flip(self) -> None:
        """★ A window-frame NE-trending error must report a NE bearing, not SE.

        In window pixels (+x east, +y SOUTH) a POSITIVE xy correlation points south-east.
        Its ENU bearing is therefore in the SE quadrant... which, folded into [0,180),
        is 90..180. A missing y-flip reports the mirror image, 0..90.
        """
        cov = np.array([[10.0, 8.0], [8.0, 10.0]])  # +x with +v => east and SOUTH
        est = combine_accuracy(cov, 1.0, 0.0, 0.0)
        assert 90.0 < est.azimuth_deg < 180.0, "the y-flip is missing or reversed"

    def test_dominant_term_georeference(self) -> None:
        est = combine_accuracy(np.zeros((2, 2)), 0.1, 10.0, 1.0)
        assert est.dominant_term == "georeference"

    def test_dominant_term_landmark_click(self) -> None:
        est = combine_accuracy(np.zeros((2, 2)), 1.0, 0.1, 5.0)
        assert est.dominant_term == "landmark_click"

    def test_dominant_term_match(self) -> None:
        est = combine_accuracy(np.array([[100.0, 0.0], [0.0, 100.0]]), 1.0, 0.1, 1.0)
        assert est.dominant_term == "match"

    def test_rejects_negative_inputs(self) -> None:
        with pytest.raises(ValueError, match="georef_ce90_m"):
            combine_accuracy(np.zeros((2, 2)), 1.0, -1.0, 1.0)
        with pytest.raises(ValueError, match="click_sigma_px"):
            combine_accuracy(np.zeros((2, 2)), 1.0, 1.0, -1.0)


class TestManualGcpAccuracy:
    """★ SCOPE.md §5: the first-class path in this build.

    A manual GCP is a DIRECT OBSERVATION. Its accuracy is imagery GSD + click precision —
    a real, defensible number — never a match score and never a homography covariance.
    """

    def test_matches_the_closed_form(self) -> None:
        gsd = resolution_at(18, 55.0)
        est = manual_gcp_accuracy(gsd_m=gsd, georef_ce90_m=0.0, click_sigma_px=3.0)
        assert est.relative_ce90_m == pytest.approx(CE90_FROM_SIGMA_2D * 3.0 * gsd)

    def test_is_isotropic(self) -> None:
        """A click has no preferred axis, and the estimate says so honestly."""
        est = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=1.0)
        assert est.semi_major_ce90_m == pytest.approx(est.semi_minor_ce90_m)
        assert est.azimuth_deg == 0.0

    def test_default_click_sigma(self) -> None:
        # ★ 1 px landmark pointing precision — the product's stance (see the constant's docstring).
        assert DEFAULT_CLICK_SIGMA_PX == 1.0
        a = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=1.0)
        b = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=1.0, click_sigma_px=1.0)
        assert a == b

    def test_agrees_with_rmse_helper(self) -> None:
        """Two routes to the relative term must not disagree."""
        gsd = 0.3
        est = manual_gcp_accuracy(gsd_m=gsd, georef_ce90_m=0.0, click_sigma_px=3.0)
        assert est.relative_ce90_m == pytest.approx(rmse_px_to_ce90_m(3.0, gsd))

    def test_realistic_esri_z18_case(self) -> None:
        """The number this product actually reports for a manual GCP on Esri at 55N.

        Esri World Imagery's georeferencing is a few metres, which DOMINATES a careful
        3 px click at z18 (~0.34 m/px). That is the honest headline: the imagery, not the
        surveyor, is the limiting factor — and `dominant_term` says so. Pins ``click_sigma_px``
        explicitly so this stays a formula regression independent of the default (now 1 px).
        """
        est = manual_gcp_accuracy(gsd_m=resolution_at(18, 55.0), georef_ce90_m=3.0, click_sigma_px=3.0)
        assert est.relative_ce90_m == pytest.approx(2.205, abs=0.01)
        assert est.total_ce90_m == pytest.approx(3.723, abs=0.01)
        assert est.dominant_term == "georeference"

    def test_authoritative_ortho_case(self) -> None:
        """With a survey-grade local orthophoto the CLICK becomes the limit — as it should."""
        est = manual_gcp_accuracy(gsd_m=0.05, georef_ce90_m=0.02, click_sigma_px=3.0)
        assert est.dominant_term == "landmark_click"
        assert est.total_ce90_m < 0.4

    def test_finer_imagery_is_more_accurate(self) -> None:
        """Monotonicity: a smaller GSD must never report a worse relative accuracy."""
        coarse = manual_gcp_accuracy(gsd_m=1.0, georef_ce90_m=0.0)
        fine = manual_gcp_accuracy(gsd_m=0.1, georef_ce90_m=0.0)
        assert fine.relative_ce90_m < coarse.relative_ce90_m

    def test_a_more_careful_click_is_more_accurate(self) -> None:
        sloppy = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=0.0, click_sigma_px=10.0)
        careful = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=0.0, click_sigma_px=1.0)
        assert careful.relative_ce90_m < sloppy.relative_ce90_m

    def test_does_not_invent_a_confidence(self) -> None:
        """★ Manual-mode confidence is SURVEYOR-DECLARED and is never computed.

        AccuracyEstimate carries no confidence field at all — the type makes the mistake
        unrepresentable rather than merely discouraged.
        """
        est = manual_gcp_accuracy(gsd_m=0.3, georef_ce90_m=1.0)
        assert not hasattr(est, "confidence")
        assert not hasattr(est, "score")


class TestRmseHelper:
    def test_formula(self) -> None:
        assert rmse_px_to_ce90_m(2.0, 0.5) == pytest.approx(CE90_FROM_SIGMA_2D * 1.0)

    def test_zero_rmse_is_allowed(self) -> None:
        assert rmse_px_to_ce90_m(0.0, 0.5) == 0.0

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError, match="rmse_px"):
            rmse_px_to_ce90_m(-1.0, 0.5)
        with pytest.raises(ValueError, match="gsd_m"):
            rmse_px_to_ce90_m(1.0, 0.0)


class TestNoDegreesNoMercator:
    """★ "The module that must never see a degree or a 3857 metre.""" ""

    def test_signature_takes_no_crs(self) -> None:
        """Nothing here accepts a CRS or a lon/lat — except the gt path's `lat`, which
        exists solely to supply cos(phi) and is documented as such."""
        import inspect

        for fn in (combine_accuracy, manual_gcp_accuracy, rmse_px_to_ce90_m):
            params = set(inspect.signature(fn).parameters)
            assert "crs" not in params
            assert "lon" not in params
