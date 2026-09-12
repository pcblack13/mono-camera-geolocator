"""Tests for ``gis.elevation`` (§4.27) — the mandated third coordinate.

★ The rule under test is HONESTY. The client brief mandates lat/lon/elevation/confidence,
and the failure this layer exists to prevent is shipping ``elevation_m = NULL`` beside a
POPULATED ``elevation_source`` — a survey deliverable that claims a third coordinate it
does not have.

(Not named in §13.1's IU-09 list, which predates §4.27. §13.4 rule 8 is explicit that new
elevation providers must appear in a parametrised contract test, so here it is.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gis.elevation import (
    ELEVATION_PROVIDER_NAMES,
    ELEVATION_PROVIDERS,
    CopernicusDemProvider,
    ElevationProvider,
    ElevationSample,
    LocalDemProvider,
    NullElevationProvider,
    get_elevation_provider,
)
from gis.errors import ProviderNotConfiguredError, UnknownProviderError
from gis.types import LonLat

_POINTS = [LonLat(15.0, 55.0), LonLat(15.1, 55.1), LonLat(-3.0, 51.5)]


class TestSampleHonesty:
    """★ ``elevation_source`` may NEVER name a source that did not run."""

    def test_a_source_without_an_elevation_is_rejected(self) -> None:
        """The type makes the lie unrepresentable rather than merely discouraged.

        This mirrors the DB's ck_gcps_elevation_source_consistent, in Python, at the layer
        that produces the value — so the constraint cannot be the first thing to notice.
        """
        with pytest.raises(ValueError, match="produced no elevation"):
            ElevationSample(elevation_m=None, source="srtm", vertical_ce90_m=None)

    def test_an_empty_sample_is_legal(self) -> None:
        s = ElevationSample(None, None, None)
        assert s.elevation_m is None
        assert s.source is None
        assert s.vertical_ce90_m is None

    def test_a_real_sample_is_legal(self) -> None:
        s = ElevationSample(123.4, "local_dem", 3.0)
        assert s.elevation_m == 123.4

    def test_vertical_error_may_be_none_but_should_not_be_a_fake_zero(self) -> None:
        """★ 'Honest, or None. Never a fabricated 0.'

        None means "we do not know". 0.0 would be a claim of perfect vertical accuracy.
        """
        s = ElevationSample(100.0, "manual", None)
        assert s.vertical_ce90_m is None


class TestRegistry:
    def test_the_default_is_none(self) -> None:
        """★ L2/L10: keyless, offline, terminal, zero-config."""
        provider = get_elevation_provider()
        assert isinstance(provider, NullElevationProvider)
        assert provider.name == "none"

    def test_registered_names(self) -> None:
        assert ELEVATION_PROVIDER_NAMES == ("none", "dem_run", "local_dem", "copernicus_dem")

    def test_unknown_name_fails_loud(self) -> None:
        """★ A typo must NOT quietly resolve to 'no elevation' — that looks identical to a
        correct configuration of the default."""
        with pytest.raises(UnknownProviderError, match="unknown elevation provider"):
            get_elevation_provider("srtm_typo")

    def test_every_registered_provider_is_an_elevation_provider(self) -> None:
        for name, cls in ELEVATION_PROVIDERS.items():
            assert issubclass(cls, ElevationProvider)
            assert cls.name == name


@pytest.mark.parametrize("name", list(ELEVATION_PROVIDER_NAMES))
class TestProviderContract:
    """★ Parametrised over EVERY registered provider (§13.4 rule 8).

    A component that is not in the contract test does not exist.
    """

    def test_construction_never_raises(self, name: str) -> None:
        """★ __init__ must not touch the network, read a key, or raise.

        A provider that throws in its constructor takes down the registry, the
        capabilities endpoint, and the UI that would have told you the key was missing.
        """
        provider = get_elevation_provider(name)
        assert isinstance(provider, ElevationProvider)

    def test_is_configured_is_a_pure_local_check_that_never_raises(self, name: str) -> None:
        provider = get_elevation_provider(name)
        assert isinstance(provider.is_configured(), bool)

    def test_name_is_a_registered_key(self, name: str) -> None:
        assert get_elevation_provider(name).name in ELEVATION_PROVIDER_NAMES

    def test_unconfigured_providers_report_rather_than_crash(self, name: str) -> None:
        """★ L11: unavailable is a report, not a traceback."""
        provider = get_elevation_provider(name)
        if provider.is_configured():
            return
        with pytest.raises(ProviderNotConfiguredError):
            provider.sample(_POINTS)


class TestNullProvider:
    """★★ THE DEFAULT. Its job is to say 'I don't know' correctly."""

    def test_is_always_configured(self) -> None:
        """Being unable to produce an elevation is its FUNCTION, not its failure."""
        assert NullElevationProvider().is_configured() is True

    def test_returns_one_empty_sample_per_point(self) -> None:
        out = NullElevationProvider().sample(_POINTS)
        assert len(out) == len(_POINTS)
        assert all(s == ElevationSample(None, None, None) for s in out)

    def test_source_is_none_not_the_string_none(self) -> None:
        """★ No source RAN, so naming one — even 'none' — would be a lie the DB rejects."""
        out = NullElevationProvider().sample(_POINTS)
        assert out[0].source is None
        assert out[0].source != "none"

    def test_never_fabricates_a_zero(self) -> None:
        """★ 0 m is sea level — a real, wrong, plausible answer. None is the truth."""
        out = NullElevationProvider().sample(_POINTS)
        assert all(s.elevation_m is None for s in out)
        assert not any(s.elevation_m == 0.0 for s in out)

    def test_empty_input(self) -> None:
        assert NullElevationProvider().sample([]) == []

    def test_never_raises(self) -> None:
        assert NullElevationProvider().sample(_POINTS * 100) is not None


class TestLocalDemProvider:
    def test_empty_dir_is_unconfigured_not_a_crash(self, tmp_path: Path = Path("/nonexistent")) -> None:
        """★ An empty dir self-skips the chain — no branching, no crash (L11)."""
        assert LocalDemProvider("/nonexistent/dem/dir").is_configured() is False

    def test_sample_on_unconfigured_raises_a_typed_error(self) -> None:
        with pytest.raises(ProviderNotConfiguredError, match="LE_LOCAL_DEM_DIR"):
            LocalDemProvider("/nonexistent/dem/dir").sample(_POINTS)

    def test_empty_points_short_circuits(self) -> None:
        assert LocalDemProvider("/nonexistent").sample([]) == []

    def test_construction_with_a_missing_dir_never_raises(self) -> None:
        LocalDemProvider("/definitely/not/here")

    def test_vertical_error_is_configurable_and_never_zero_by_default(self) -> None:
        provider = LocalDemProvider("/tmp", vertical_ce90_m=0.15)
        assert provider._vertical_ce90_m == 0.15


class TestCopernicusProvider:
    def test_no_url_is_unconfigured(self) -> None:
        assert CopernicusDemProvider().is_configured() is False

    def test_no_url_sample_raises_a_typed_error(self) -> None:
        with pytest.raises(ProviderNotConfiguredError, match="LE_COPERNICUS_DEM_URL"):
            CopernicusDemProvider().sample(_POINTS)

    def test_construction_never_touches_the_network(self) -> None:
        """★ Constructing a keyed provider with no key must be free and silent."""
        CopernicusDemProvider("https://example.invalid/dem", api_key="")

    def test_empty_points_short_circuits(self) -> None:
        assert CopernicusDemProvider("https://example.invalid/dem").sample([]) == []


class TestImportPurity:
    def test_importing_elevation_does_not_import_httpx_or_a_raster_backend(self) -> None:
        """★ §11.3: the registry imports every provider eagerly, so none of them may bind
        an optional dependency at module scope."""
        import subprocess
        import sys

        code = (
            "import sys, importlib\n"
            "importlib.import_module('gis.elevation')\n"
            "for m in ('httpx', 'rasterio', 'osgeo'):\n"
            "    assert m not in sys.modules, m + ' imported at module scope'\n"
            "print('clean')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "clean" in result.stdout
