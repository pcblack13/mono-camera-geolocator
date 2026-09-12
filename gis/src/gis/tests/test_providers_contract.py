"""IU-11 · ★ PARAMETRISED OVER EVERY PROVIDER — **THE INTERCHANGEABILITY PROOF**.

This is the suite that makes ADR-002 real. Imagery sits behind one interface so that
swapping a provider changes nothing else; **that claim is only true if every provider
actually honours the interface**, and that is what is asserted here — for all seven, by
construction, with no per-provider special cases in the assertions themselves.

★ **NO NETWORK.** A socket-blocking fixture proves it rather than trusting it. For
**UNCONFIGURED** providers the suite asserts ``__init__`` / ``is_configured`` /
``capabilities`` / ``name`` **only** — it does not fetch. Fetching is exercised only for the
two providers that are configured **offline**: ``fixture`` and ``local_orthophoto``.

★ **A provider that is not in this test does not exist.** New providers are picked up
automatically from the registry — that is deliberate, and it is why the registration list is
the single source of truth.
"""

from __future__ import annotations

import inspect
import socket
from pathlib import Path

import numpy as np
import pytest

from gis import rasterio_shim
from gis.config import GisConfig
from gis.errors import (
    ProviderDisabledError,
    ProviderError,
    ProviderNotConfiguredError,
    TileOutOfRangeError,
)
from gis.imagery.base import PROVIDER_NAMES, ImageryProvider, ProviderCapabilities
from gis.imagery.providers import OFFLINE_PROVIDERS, PROVIDERS
from gis.imagery.registry import ProviderRegistry
from gis.types import BasemapKind, BBox, SatelliteChip

_ORTHO_GT = (500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)
_ORTHO_EPSG = 32633
_ORTHO_SIZE = 64
_FIXTURES = Path(__file__).parent / "fixtures"


# --- The no-network guarantee ------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ Make ANY socket connection an immediate, loud failure.

    Autouse, so it covers every test in this module. This is the fixture that turns "these
    providers must not touch the network at construction" from a claim into a proof — a
    provider that resolved DNS in ``__init__`` would fail here rather than merely being slow
    and flaky in CI.
    """

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a test touched the network. Provider construction, is_configured(), "
            "capabilities() and name must all be pure local operations."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every provider credential, so "unconfigured" means unconfigured.

    ★ Without this the suite would pass or fail depending on the developer's shell.
    """
    for var in (
        "LE_MAPBOX_ACCESS_TOKEN",
        "LE_BING_MAPS_KEY",
        "LE_COPERNICUS_CLIENT_ID",
        "LE_COPERNICUS_CLIENT_SECRET",
        "LE_COPERNICUS_INSTANCE_ID",
        "LE_GOOGLE_MAPS_STATIC_KEY",
        "LE_GOOGLE_TOS_ACKNOWLEDGED",
        "LE_LOCAL_ORTHO_DIR",
        "LE_IMAGERY_PROVIDER",
        "LE_IMAGERY_OFFLINE",
        "LE_IMAGERY_STRICT",
        "LE_ALLOWED_PROVIDERS",
        "LE_IMAGERY_FALLBACK_CHAIN",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def provider(request: pytest.FixtureRequest, clean_env: None) -> ImageryProvider:
    """Construct the parametrised provider with a zero-config ``GisConfig``."""
    return PROVIDERS[request.param](GisConfig())


def _ortho_dir(tmp_path: Path) -> Path:
    """Create a directory holding one 64x64 EPSG:32633 GeoTIFF.

    Prefers IU-14's committed ``synthetic_ortho.tif``; generates an equivalent when absent,
    so IU-11 is verifiable independently of IU-14's landing order.
    """
    committed = _FIXTURES / "synthetic_ortho.tif"
    directory = tmp_path / "orthophotos"
    directory.mkdir(exist_ok=True)
    if committed.is_file():
        (directory / "synthetic_ortho.tif").write_bytes(committed.read_bytes())
        return directory

    gdal = pytest.importorskip("osgeo.gdal", reason="fixture generation needs GDAL")
    osr = pytest.importorskip("osgeo.osr", reason="fixture generation needs GDAL")
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(directory / "synthetic_ortho.tif"), _ORTHO_SIZE, _ORTHO_SIZE, 3, gdal.GDT_Byte
    )
    dataset.SetGeoTransform(_ORTHO_GT)
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(_ORTHO_EPSG)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    rng = np.random.default_rng(99)
    for band_index in range(1, 4):
        # ★ WriteRaster, not WriteArray: osgeo.gdal_array does not import under NumPy 2.
        data = rng.integers(0, 255, (_ORTHO_SIZE, _ORTHO_SIZE), dtype=np.uint8)
        dataset.GetRasterBand(band_index).WriteRaster(
            0, 0, _ORTHO_SIZE, _ORTHO_SIZE, data.tobytes()
        )
    dataset.FlushCache()
    del dataset
    return directory


# =============================================================================
# EVERY provider — construction, identity, capabilities, readiness
# =============================================================================


@pytest.mark.parametrize("provider", PROVIDER_NAMES, indirect=True)
class TestEveryProvider:
    """The invariants that hold for all seven, configured or not."""

    def test_init_never_raises_and_never_touches_the_network(
        self, provider: ImageryProvider
    ) -> None:
        """★ Construction ALWAYS succeeds.

        A provider that throws in its constructor takes down the registry, the capabilities
        endpoint, and the UI that would have told you the key was missing. The autouse
        socket block proves the "no network" half.
        """
        assert provider is not None

    def test_name_is_a_member_of_PROVIDER_NAMES(self, provider: ImageryProvider) -> None:
        """★ ``gis`` cannot see the ``imagery_provider`` PG enum (it may not import
        sqlalchemy), so it tests against ``PROVIDER_NAMES`` — and a **backend** test pins
        that tuple to the enum. The constraint is enforced from the package that can see it.
        """
        assert provider.name in PROVIDER_NAMES

    def test_name_matches_its_registry_key(self, provider: ImageryProvider) -> None:
        """A provider registered under one key that reports another is unresolvable."""
        assert PROVIDERS[provider.name] is type(provider)

    def test_is_configured_never_raises_and_is_a_bool(
        self, provider: ImageryProvider
    ) -> None:
        """★ Total. It is called for every provider on every ``GET /capabilities``."""
        assert isinstance(provider.is_configured(), bool)

    def test_an_unconfigured_provider_reports_a_reason(
        self, provider: ImageryProvider
    ) -> None:
        """★ §11.3/§11.4: every unconfigured component **reports its reason**.

        ``GET /imagery/providers`` lists it with ``configured: false`` **and a reason**. A
        provider that is simply missing, with no explanation, is a provider nobody can
        discover they need to configure.
        """
        if provider.is_configured():
            assert provider.configuration_reason() is None
        else:
            reason = provider.configuration_reason()
            assert reason and reason.strip(), f"{provider.name} gave no reason"

    def test_capabilities_is_total(self, provider: ImageryProvider) -> None:
        """★ Never raises, never fetches, and every field is populated."""
        caps = provider.capabilities()

        assert isinstance(caps, ProviderCapabilities)
        assert caps.tile_size_px in (256, 512)
        assert caps.native_crs
        assert isinstance(caps.allows_caching, bool)
        assert isinstance(caps.allows_derivative_export, bool)
        assert caps.kinds and all(isinstance(k, BasemapKind) for k in caps.kinds)
        assert BasemapKind.SATELLITE in caps.kinds, "matching always uses satellite"
        assert caps.bands == tuple(dict.fromkeys(caps.bands)), "band names must be unique"

    def test_georef_ce90_is_present_and_not_flattering(
        self, provider: ImageryProvider
    ) -> None:
        """★ MANDATORY, and it must be honest.

        ``georef_ce90_m`` flows into ``CandidateWindow`` -> ``PixelAccuracy`` ->
        ``GcpAccuracy.total_ce90_m``. It is the term that makes ``dominant_term`` honest,
        and a flattering number here becomes a **false survey claim** on an exported GCP.

        Only ``fixture`` may be 0 — its pixels are DEFINED by the slippy grid, so there is
        genuinely no registration error. Every real provider must declare a positive one.
        """
        ce90 = provider.capabilities().georef_ce90_m

        assert ce90 >= 0.0
        assert np.isfinite(ce90)
        if provider.name != "fixture":
            assert ce90 > 0.0, (
                f"{provider.name} claims perfect georeferencing. No real imagery source has "
                "zero absolute error; this number is exported as a survey claim."
            )

    def test_zoom_range_is_coherent(self, provider: ImageryProvider) -> None:
        """``min_zoom <= max_zoom``, and both are plausible slippy levels."""
        assert 0 <= provider.min_zoom <= provider.max_zoom <= 24

    def test_attribution_and_terms_are_present_where_the_licence_requires_them(
        self, provider: ImageryProvider
    ) -> None:
        """★ ATTRIBUTION IS A LICENCE CONDITION, and a missing one is a test failure.

        ``local_orthophoto`` and ``fixture`` are the two honest exemptions from
        ``terms_url``: the operator's own imagery is governed by the operator's own rights,
        and the fixture's pixels are synthetic and carry no third-party licence at all. An
        invented URL would be worse than an empty one.
        """
        caps = provider.capabilities()

        assert isinstance(provider.attribution, str)
        assert isinstance(provider.terms_url, str)
        if caps.requires_attribution:
            assert provider.attribution.strip(), f"{provider.name} requires attribution"
        if provider.name not in ("local_orthophoto", "fixture"):
            assert provider.terms_url.startswith("https://"), (
                f"{provider.name} must publish a canonical ToS URL"
            )

    def test_requires_api_key_agrees_with_configuredness(
        self, provider: ImageryProvider
    ) -> None:
        """★ A keyless provider must be configured out of the box — this is L2's mechanism.

        ``local_orthophoto`` is the deliberate exception: keyless, but it needs *files*, and
        it self-skips when it has none. That self-skip is what lands the zero-config machine
        on Esri with no branching.
        """
        if not provider.requires_api_key and provider.name != "local_orthophoto":
            assert provider.is_configured(), (
                f"{provider.name} needs no key but is not configured; L2 requires a keyless "
                "provider to work with an empty environment"
            )

    def test_offline_capability_is_truthful(self, provider: ImageryProvider) -> None:
        """★ ``supports_offline`` must agree with ``OFFLINE_PROVIDERS``.

        ``LE_IMAGERY_OFFLINE=true`` gates on the list; the capability flag advertises it to
        the UI. If they disagreed, the air-gapped mode would either hide a working provider
        or offer a dead one.
        """
        assert provider.capabilities().supports_offline == (
            provider.name in OFFLINE_PROVIDERS
        )

    def test_methods_have_the_contract_signature(self, provider: ImageryProvider) -> None:
        """``kind`` is keyword-only on both fetch methods, for every provider."""
        for method_name in ("get_tile", "get_static_bbox"):
            params = inspect.signature(getattr(provider, method_name)).parameters
            assert "kind" in params
            assert params["kind"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_health_never_raises(self, provider: ImageryProvider) -> None:
        """★ A health check that raises is not a health check. It returns a STATUS."""
        health = provider.health()

        assert health.name == provider.name
        assert health.status in ("up", "degraded", "down")
        assert isinstance(health.configured, bool)
        assert health.checked_at > 0


# =============================================================================
# UNCONFIGURED providers — no fetching, only honest refusal
# =============================================================================

_KEYED = tuple(
    name
    for name, provider_cls in PROVIDERS.items()
    if provider_cls(GisConfig()).requires_api_key
    # ★ mapbox_satellite EXCLUDED deliberately: it requires a key, but the product
    #   ships a BUILT-IN public token as its fallback (see the provider's
    #   `_DEFAULT_PUBLIC_TOKEN`), so it is never unconfigured on a bare machine —
    #   that is the feature, and `test_mapbox_ships_a_builtin_public_token` pins it.
    and name != "mapbox_satellite"
)
"""The providers that genuinely need a credential the operator must supply.

★ Derived from ``requires_api_key`` itself, NOT by excluding ``OFFLINE_PROVIDERS``. Those
are different sets and conflating them is a real trap: **``esri_world_imagery`` is online
but KEYLESS** (that is L2), so an exclusion-based list would sweep it in here and assert
that the zero-config default needs a key — and would then try to *fetch* from it under the
socket block.

Constructing a provider to read the property is safe by the ABC's own contract:
``__init__`` never raises and never touches the network, which
``TestEveryProvider.test_init_never_raises_and_never_touches_the_network`` asserts.
"""


def test_mapbox_ships_a_builtin_public_token() -> None:
    """★ THE ZERO-CONFIG PROMISE: Mapbox works on a bare machine.

    The provider falls back to the product's embedded `pk.` token (public by
    design — it grants tile reads only), so a fresh install draws the product's
    chosen imagery with no `.env`. An explicitly supplied token still wins.
    """
    from gis.imagery.providers.mapbox import MapboxSatelliteProvider

    bare = MapboxSatelliteProvider(GisConfig())
    assert bare.is_configured() is True

    override = MapboxSatelliteProvider(GisConfig(), access_token="pk.operator-supplied")
    assert override._token == "pk.operator-supplied"  # noqa: SLF001 — the seam under test


@pytest.mark.parametrize("provider", _KEYED, indirect=True)
def test_keyed_providers_are_unconfigured_with_no_credentials(
    provider: ImageryProvider,
) -> None:
    """★ A keyed provider with no key is **REGISTERED but reports unavailable**.

    Not absent, not a crash: listed, with ``configured: false`` and a reason.
    """
    assert provider.requires_api_key is True
    assert provider.is_configured() is False
    assert provider.configuration_reason()


@pytest.mark.parametrize("provider", _KEYED, indirect=True)
def test_unconfigured_fetch_raises_a_typed_provider_error(
    provider: ImageryProvider,
) -> None:
    """★ Fetching without a key raises a ``ProviderError``, never a bare httpx/ImportError.

    The socket block guarantees this cannot reach the network even if a provider tried; the
    assertion is that the refusal is *typed*, so callers never learn our stack.
    """
    z = max(provider.min_zoom, 10)

    with pytest.raises(ProviderError) as exc_info:
        provider.get_tile(z, 1, 1)

    # It must be a *refusal to serve*, not an argument complaint — the tile requested is
    # perfectly legal for every provider here.
    assert not isinstance(exc_info.value, TileOutOfRangeError), (
        f"{provider.name} rejected a valid tile instead of reporting its missing credential"
    )


# =============================================================================
# Esri — ★ THE KEYLESS DEFAULT (L2) and its famous axis-order trap
# =============================================================================


def test_esri_is_keyless_and_always_configured(clean_env: None) -> None:
    """★★ THIS IS L2. ``compose up`` with an empty ``.env`` yields working imagery."""
    esri = PROVIDERS["esri_world_imagery"](GisConfig())

    assert esri.requires_api_key is False
    assert esri.is_configured() is True
    assert esri.configuration_reason() is None


def test_esri_tile_url_is_z_y_x_not_z_x_y(clean_env: None) -> None:
    """★★ THE AXIS-ORDER TEST. ``{z}/{y}/{x}`` — **row before column**.

    This is the single most common integration bug against this endpoint, because
    ``{z}/{y}/{x}`` is visually one character from the near-universal ``{z}/{x}/{y}`` and
    **does not 404**: it returns *plausible imagery of the wrong place*, which a matcher
    will happily match and a surveyor will happily export.

    A known ``(z, x, y)`` is pinned to a known URL, which is the only way to catch it.
    """
    esri = PROVIDERS["esri_world_imagery"](GisConfig())

    url = esri.tile_url(18, 137452, 89234)

    assert url.endswith("/18/89234/137452"), f"axis order is wrong: {url}"
    assert not url.endswith("/18/137452/89234"), "that is {z}/{x}/{y} — the classic bug"
    assert "services.arcgisonline.com" in url
    assert "World_Imagery" in url


def test_esri_serves_the_three_basemap_kinds(clean_env: None) -> None:
    """The BasemapSwitcher's kinds must map to genuinely different upstream layers."""
    esri = PROVIDERS["esri_world_imagery"](GisConfig())

    assert set(esri.capabilities().kinds) == {
        BasemapKind.SATELLITE,
        BasemapKind.HYBRID,
        BasemapKind.TERRAIN,
    }
    satellite = esri.tile_url(10, 1, 2, kind=BasemapKind.SATELLITE)
    terrain = esri.tile_url(10, 1, 2, kind=BasemapKind.TERRAIN)
    assert satellite != terrain, "a kind that returns identical tiles is a lie in the UI"


# =============================================================================
# Google Static — ★ the double opt-in
# =============================================================================


def test_google_static_needs_both_a_key_and_an_acknowledgement(clean_env: None) -> None:
    """★★ THE DOUBLE OPT-IN. **The key alone is insufficient.**

    ``LE_GOOGLE_TOS_ACKNOWLEDGED`` has no technical function whatsoever. It exists so that
    enabling a provider whose terms plausibly forbid this product's core use — deriving
    survey coordinates from the imagery and exporting them — is an **affirmative, auditable
    act by a human who read the warning**, rather than a side effect of a key sitting in a
    shared environment.
    """
    cls = PROVIDERS["google_maps_static"]

    assert cls(GisConfig(), api_key="", tos_acknowledged=False).is_configured() is False
    assert cls(GisConfig(), api_key="AIzaKEY", tos_acknowledged=False).is_configured() is False
    assert cls(GisConfig(), api_key="", tos_acknowledged=True).is_configured() is False
    assert cls(GisConfig(), api_key="AIzaKEY", tos_acknowledged=True).is_configured() is True

    key_only = cls(GisConfig(), api_key="AIzaKEY", tos_acknowledged=False)
    assert "LE_GOOGLE_TOS_ACKNOWLEDGED" in (key_only.configuration_reason() or "")


def test_google_static_is_capability_blocked_from_caching_and_export(
    clean_env: None,
) -> None:
    """★★ THE ENFORCEMENT MECHANISM, asserted.

    These two flags are not documentation — they mechanically gate the cache and the PDF
    writer. Flipping either to True without a terms change is how this product would start
    violating a licence, so the flags are pinned here.
    """
    caps = PROVIDERS["google_maps_static"](GisConfig()).capabilities()

    assert caps.allows_caching is False
    assert caps.allows_derivative_export is False


def test_google_static_is_unreachable_by_fallback(clean_env: None) -> None:
    """★ NEVER DEFAULT, NEVER IN A CHAIN — enforced structurally, not by documentation.

    Even when an operator explicitly puts it in ``LE_IMAGERY_FALLBACK_CHAIN``, it is
    stripped. Only an explicit ``LE_IMAGERY_PROVIDER=google_maps_static`` can select it.
    """
    config = GisConfig.from_env(
        {"LE_IMAGERY_FALLBACK_CHAIN": "google_maps_static,esri_world_imagery"}
    )
    registry = ProviderRegistry(config)

    assert "google_maps_static" not in registry.default_chain()
    assert registry.resolve().name == "esri_world_imagery"


# =============================================================================
# Sentinel — ★ refuses to manufacture resolution
# =============================================================================


def test_sentinel_refuses_zoom_above_its_real_resolution(clean_env: None) -> None:
    """★★ THE REFUSAL IS THE FEATURE.

    Sentinel-2 is 10 m/px. **The provider must not manufacture the appearance of resolution
    it does not have** — an interpolated z18 Sentinel tile is a lie that a matcher will
    confidently act on and a surveyor will export.

    Note this raises *before* the missing-credentials check: an out-of-range zoom is a
    caller bug regardless of whether a key is present.
    """
    sentinel = PROVIDERS["sentinel_copernicus"](GisConfig())

    assert sentinel.max_zoom == 15
    assert sentinel.capabilities().typical_gsd_m == 10.0

    with pytest.raises(TileOutOfRangeError, match="10 m/px|exceeds"):
        sentinel.get_tile(18, 1, 1)


# =============================================================================
# CONFIGURED-OFFLINE providers — the only ones that fetch here
# =============================================================================


@pytest.fixture
def offline_providers(tmp_path: Path, clean_env: None) -> dict[str, ImageryProvider]:
    """The two providers that are configured with no network and no keys."""
    if not rasterio_shim.is_available():
        pytest.skip("no raster backend; local_orthophoto cannot be exercised")
    config = GisConfig.from_env({"LE_LOCAL_ORTHO_DIR": str(_ortho_dir(tmp_path))})
    return {
        "fixture": PROVIDERS["fixture"](config),
        "local_orthophoto": PROVIDERS["local_orthophoto"](config),
    }


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_offline_provider_is_configured(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """★ Both offline providers work with no keys, no env and no network."""
    assert offline_providers[name].is_configured() is True


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_get_tile_returns_contiguous_rgb_uint8(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """★★ ``(S, S, 3)`` uint8 **RGB — not BGR, no alpha, C-contiguous**.

    Channel order is asserted because a provider that hands OpenCV-flavoured BGR to a
    matcher produces plausible, confidently-wrong results rather than an error. Contiguity
    is asserted because a non-contiguous array silently copies in every downstream cv2 call.
    """
    provider = offline_providers[name]
    size = provider.capabilities().tile_size_px
    z, x, y = _a_tile_for(provider)

    tile = provider.get_tile(z, x, y)

    assert isinstance(tile, np.ndarray)
    assert tile.shape == (size, size, 3), "no alpha channel; square tiles"
    assert tile.dtype == np.uint8, "no float, no uint16"
    assert tile.flags["C_CONTIGUOUS"]


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_get_static_bbox_returns_a_chip_with_non_empty_attribution(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """★★ ATTRIBUTION TRAVELS WITH THE PIXELS. That is why this returns a ``SatelliteChip``
    and not a bare ``(ndarray, geotransform)`` tuple: a tuple lets pixels travel naked, and
    the type must make the licence obligation **unforgeable** rather than reviewer-dependent.
    """
    provider = offline_providers[name]
    bbox, zoom = _a_bbox_for(provider)

    chip = provider.get_static_bbox(bbox, zoom)

    assert isinstance(chip, SatelliteChip)
    assert chip.attribution.strip(), "pixels may not travel without their credit"
    assert chip.provider_name == provider.name
    assert chip.image.ndim == 3
    assert chip.image.shape[2] == 3
    assert chip.image.dtype == np.uint8
    assert chip.image.flags["C_CONTIGUOUS"]
    assert chip.crs
    assert chip.gsd_m > 0
    assert 0.0 <= chip.placeholder_fraction <= 1.0


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_chip_geotransform_is_exact_for_the_returned_pixels(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """★★ The geotransform describes the pixels RETURNED, not the tiles fetched.

    Crop offsets are **folded into the origin**, never approximated and never dropped.
    Cropping without updating the origin is the defect that produces coordinates wrong by
    up to a whole tile (~108 m at z18/45N) while crashing nothing and looking plausible.

    The check: the chip's own geotransform, run forward over its own pixel extent, must
    reproduce the chip's footprint — and that footprint must contain the requested bbox
    (the crop is outward, so containment rather than equality is the correct assertion).
    """
    provider = offline_providers[name]
    bbox, zoom = _a_bbox_for(provider)

    chip = provider.get_static_bbox(bbox, zoom)
    gt = chip.geotransform
    height, width = chip.image.shape[:2]

    assert gt[1] > 0, "pixel width is positive"
    assert gt[5] < 0, "north-up chips have a negative pixel height"

    from gis.crs import pixel_to_lonlat

    try:
        west, north = pixel_to_lonlat(gt, chip.crs, 0, 0)
        east, south = pixel_to_lonlat(gt, chip.crs, width, height)
    except Exception as exc:  # noqa: BLE001 - a CRS backend may be missing
        pytest.skip(f"no CRS backend for {chip.crs}: {exc}")

    tolerance = chip.gsd_m / 111_320.0 * 2.0  # ~2 px, in degrees
    assert west <= bbox.west + tolerance
    assert east >= bbox.east - tolerance
    assert south <= bbox.south + tolerance
    assert north >= bbox.north - tolerance


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_out_of_range_zoom_raises_TileOutOfRangeError(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """★ A caller bug, and NEVER retryable — which is why it is its own type."""
    provider = offline_providers[name]

    with pytest.raises(TileOutOfRangeError):
        provider.get_tile(provider.max_zoom + 1, 0, 0)


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_out_of_range_tile_coordinates_raise(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """``x``/``y`` outside ``2**z`` is a caller bug, not a coverage gap."""
    provider = offline_providers[name]
    z = max(provider.min_zoom, 4)

    with pytest.raises(TileOutOfRangeError):
        provider.get_tile(z, 1 << z, 0)


@pytest.mark.parametrize("name", OFFLINE_PROVIDERS)
def test_an_unsupported_kind_raises(
    name: str, offline_providers: dict[str, ImageryProvider]
) -> None:
    """A provider must refuse a kind it does not declare, rather than silently substituting."""
    provider = offline_providers[name]
    unsupported = [k for k in BasemapKind if k not in provider.capabilities().kinds]
    if not unsupported:
        pytest.skip(f"{name} serves every kind")
    z, x, y = _a_tile_for(provider)

    with pytest.raises(TileOutOfRangeError):
        provider.get_tile(z, x, y, kind=unsupported[0])


def test_fixture_provider_is_deterministic(clean_env: None) -> None:
    """★★ THE PROPERTY THE FIXTURE PROVIDER EXISTS FOR.

    Byte-identical in every process, on every machine, forever. This is why the seed is a
    SHA-256 and not ``hash()`` — Python salts str hashing per process, so a ``hash()``-seeded
    provider would produce different imagery in every worker and every test run. **A fixture
    that is not reproducible is not a fixture.**
    """
    a = PROVIDERS["fixture"](GisConfig())
    b = PROVIDERS["fixture"](GisConfig())

    first = a.get_tile(18, 137452, 89234)
    second = b.get_tile(18, 137452, 89234)

    assert np.array_equal(first, second)
    assert np.array_equal(first, a.get_tile(18, 137452, 89234))
    assert not np.array_equal(first, a.get_tile(18, 137453, 89234)), (
        "different tiles must differ, or the fixture is a flat colour"
    )


def test_fixture_tiles_are_textured(clean_env: None) -> None:
    """A featureless fixture would make every downstream test vacuous."""
    tile = PROVIDERS["fixture"](GisConfig()).get_tile(18, 137452, 89234)
    assert tile.std() > 5.0, "the fixture must have real texture, not a flat fill"


def test_local_ortho_self_skips_on_an_empty_directory(
    tmp_path: Path, clean_env: None
) -> None:
    """★★ THE SELF-SKIP THAT KEEPS L2 INTACT.

    This is what lets ``local_orthophoto`` sit FIRST in the default chain harmlessly: on a
    machine with no orthophotos it reports unconfigured, and the zero-config path lands on
    Esri **with no branching anywhere**.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    provider = PROVIDERS["local_orthophoto"](
        GisConfig.from_env({"LE_LOCAL_ORTHO_DIR": str(empty)})
    )

    assert provider.is_configured() is False
    assert provider.configuration_reason()


def test_local_ortho_ignores_a_plain_tiff(tmp_path: Path, clean_env: None) -> None:
    """★ A TIFF with no georeferencing is not an orthophoto.

    Indexing one would place it at 0N 0E via GDAL's identity transform and offer its pixels
    as survey-grade imagery. ``detect_georeferencing`` is what stops it, and this is that
    guarantee asserted at the provider level.
    """
    gdal = pytest.importorskip("osgeo.gdal")
    directory = tmp_path / "plain_only"
    directory.mkdir()
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(directory / "scan.tif"), 16, 16, 3, gdal.GDT_Byte
    )
    dataset.FlushCache()
    del dataset

    provider = PROVIDERS["local_orthophoto"](
        GisConfig.from_env({"LE_LOCAL_ORTHO_DIR": str(directory)})
    )

    assert provider.is_configured() is False


def test_local_ortho_reports_the_files_native_crs(
    offline_providers: dict[str, ImageryProvider],
) -> None:
    """★ ``native_crs`` is PER-FILE — typically a UTM zone, NOT EPSG:3857.

    Hardcoding 3857 would make the contract's own highest-accuracy provider unstorable, and
    is exactly why ``match_results.sat_geotransform_srid`` exists.
    """
    caps = offline_providers["local_orthophoto"].capabilities()

    assert caps.native_crs == f"EPSG:{_ORTHO_EPSG}"
    assert caps.native_crs != "EPSG:3857"


def test_local_ortho_is_the_only_authoritative_provider(
    offline_providers: dict[str, ImageryProvider],
) -> None:
    """★ ``is_authoritative`` means survey-grade georeferencing.

    Only the operator's own controlled orthomosaic may claim it — they controlled it, and
    they know its RMSE. Nobody knows Esri's.
    """
    provider = offline_providers["local_orthophoto"]
    bbox, zoom = _a_bbox_for(provider)
    assert provider.get_static_bbox(bbox, zoom).is_authoritative is True

    fixture = offline_providers["fixture"]
    fbox, fzoom = _a_bbox_for(fixture)
    assert fixture.get_static_bbox(fbox, fzoom).is_authoritative is False


def test_local_ortho_max_zoom_is_derived_from_its_gsd(
    offline_providers: dict[str, ImageryProvider],
) -> None:
    """★ Derived per-file, never fixed.

    Advertising z22 for a 0.5 m mosaic would invite ``choose_zoom`` to request detail that
    does not exist, and the provider would answer with upsampled mush that a matcher would
    treat as real.
    """
    provider = offline_providers["local_orthophoto"]
    from gis.tiles import resolution_at

    achieved = resolution_at(provider.max_zoom, 45.15, 256)
    assert achieved <= _ORTHO_GT[1] * 1.5, "max_zoom must reflect the file's real GSD"


def test_gsd_is_true_ground_metres_not_a_web_mercator_metre(
    offline_providers: dict[str, ImageryProvider],
) -> None:
    """★★ ``gsd_m`` is cos(phi)-corrected TRUE ground metres — **not** ``geotransform[1]``.

    A Web Mercator "metre" is inflated by ``1/cos(phi)``: ~1.41x at 45 degrees, ~2x at 60.
    Reporting it as a ground metre would inflate every derived accuracy number by the same
    factor. This is the whole reason ``gsd_m`` is a field rather than something callers
    derive from the geotransform themselves.
    """
    provider = offline_providers["fixture"]
    bbox = BBox(west=8.5, south=47.3, east=8.51, north=47.31)

    chip = provider.get_static_bbox(bbox, 16)

    assert chip.crs == "EPSG:3857"
    expected_ratio = np.cos(np.radians(bbox.center()[1]))
    assert chip.gsd_m / chip.geotransform[1] == pytest.approx(expected_ratio, rel=1e-3)
    assert chip.gsd_m < chip.geotransform[1], "true metres are smaller than 3857 metres"


# =============================================================================
# The registry — ★ the `auto` preference walk (§11.4)
# =============================================================================


def test_auto_with_an_empty_ortho_dir_resolves_to_mapbox(
    tmp_path: Path, clean_env: None
) -> None:
    """★★ ZERO-CONFIG PRESERVED — and it lands on the PRODUCT'S imagery.

    ``auto`` walks the chain, ``local_orthophoto`` self-skips because the dir is empty,
    and the machine lands on Mapbox via the built-in public token **with no branching
    and no warning**. Keyless Esri stays last in the chain as the imagery of last
    resort, so L2's bare-machine guarantee survives even a revoked token.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    registry = ProviderRegistry(GisConfig.from_env({"LE_LOCAL_ORTHO_DIR": str(empty)}))

    assert registry.resolve().name == "mapbox_satellite"


def test_auto_with_a_populated_ortho_dir_resolves_to_local_orthophoto(
    tmp_path: Path, clean_env: None
) -> None:
    """★★ THE RATIONALE BECOMES REAL — and this is the test that proves it.

    The chain's stated reason for putting ``local_orthophoto`` first is that mounted
    orthophotos are *definitionally better than any web tile source*. But if the chain were
    walked only when the NAMED provider is unconfigured, and the default name is keyless
    Esri, then ``is_configured()`` would always be True, the chain would **never be
    consulted**, and an operator who dropped GeoTIFFs into ``./data/orthophotos`` would
    still get Esri tiles **and never learn why**.

    ``auto`` as a PREFERENCE walk is what makes the ordering's rationale true. With a
    populated dir and zero other env vars: ``local_orthophoto`` wins.
    """
    if not rasterio_shim.is_available():
        pytest.skip("no raster backend; local_orthophoto cannot be configured")
    registry = ProviderRegistry(
        GisConfig.from_env({"LE_LOCAL_ORTHO_DIR": str(_ortho_dir(tmp_path))})
    )

    assert registry.resolve().name == "local_orthophoto"


def test_an_unknown_provider_name_fails_loud(clean_env: None) -> None:
    """★ A typo'd config must NOT quietly resolve to something that works.

    A silently-substituted provider is a silently-wrong provenance on a survey coordinate.
    """
    from gis.errors import UnknownProviderError

    with pytest.raises(UnknownProviderError, match="unknown imagery provider"):
        ProviderRegistry(GisConfig()).resolve("esri_wrold_imagery")


def test_explicitly_requesting_an_unconfigured_provider_under_strict_raises(
    clean_env: None,
) -> None:
    """★ ``LE_IMAGERY_STRICT=true`` -> ``ProviderNotConfiguredError`` -> **503**.

    *Dev is forgiving; prod is loud.* Silently serving 10 m Sentinel when the operator paid
    for and expected 0.3 m Mapbox is a **worse** failure than a 503, because it changes the
    answer's provenance rather than only its accuracy.
    """
    registry = ProviderRegistry(GisConfig.from_env({"LE_IMAGERY_STRICT": "true"}))

    # bing_aerial: keyed with NO built-in fallback (mapbox now ships one, so it can
    # never play the "unconfigured" role in this test again).
    with pytest.raises(ProviderNotConfiguredError, match="LE_IMAGERY_STRICT"):
        registry.resolve("bing_aerial")


def test_explicitly_requesting_an_unconfigured_provider_without_strict_falls_back(
    tmp_path: Path, clean_env: None
) -> None:
    """★ Not strict -> WARN and fall back. And ``chip.provider_name`` tells the truth.

    Falling back is only acceptable *because* the provenance travels with the pixels — so a
    downstream report can never misattribute imagery.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    registry = ProviderRegistry(
        GisConfig.from_env({"LE_IMAGERY_STRICT": "false", "LE_LOCAL_ORTHO_DIR": str(empty)})
    )

    resolved = registry.resolve("bing_aerial")

    # ★ The fallback chain now lands on MAPBOX (built-in token) before Esri.
    assert resolved.name == "mapbox_satellite"
    assert resolved.name != "bing_aerial", "the fallback must not lie about identity"


def test_the_allow_list_is_a_hard_stop(clean_env: None) -> None:
    """★ ``LE_ALLOWED_PROVIDERS`` -> ``ProviderDisabledError`` -> **403**.

    The operator's blunt instrument: an org that has decided only certain providers are
    licensed for their work sets the list, and **no misconfiguration, no fallback and no UI
    selection can reach anything else**.
    """
    registry = ProviderRegistry(
        GisConfig.from_env({"LE_ALLOWED_PROVIDERS": "fixture"})
    )

    with pytest.raises(ProviderDisabledError, match="LE_ALLOWED_PROVIDERS"):
        registry.resolve("esri_world_imagery")
    assert registry.resolve("fixture").name == "fixture"


def test_offline_mode_permits_only_the_offline_providers(
    tmp_path: Path, clean_env: None
) -> None:
    """★ ``LE_IMAGERY_OFFLINE=true`` — air-gapped mode, a FIRST-CLASS SUPPORTED MODE.

    Not a test flag. This is what makes ``make seed && make up`` work with the NIC unplugged.
    """
    registry = ProviderRegistry(GisConfig.from_env({"LE_IMAGERY_OFFLINE": "true"}))

    for name in PROVIDER_NAMES:
        allowed, reason = registry.is_allowed(name)
        assert allowed == (name in OFFLINE_PROVIDERS), name
        if not allowed:
            assert "LE_IMAGERY_OFFLINE" in (reason or "")

    with pytest.raises(ProviderDisabledError):
        registry.resolve("esri_world_imagery")
    assert registry.resolve("fixture").name == "fixture"


def test_available_lists_every_provider_with_a_reason(clean_env: None) -> None:
    """★ ``GET /imagery/providers`` lists unconfigured providers, it does not hide them.

    A provider that vanishes because its key is missing is a provider nobody can discover
    they need to configure.
    """
    listings = ProviderRegistry(GisConfig()).available()

    assert {listing.name for listing in listings} == set(PROVIDER_NAMES)
    for listing in listings:
        assert isinstance(listing.configured, bool)
        assert isinstance(listing.allowed, bool)
        if not listing.usable:
            assert listing.reason, f"{listing.name} is unusable with no reason"


def test_registry_caches_provider_instances(clean_env: None) -> None:
    """★ A provider holds a connection pool, a metadata cache and an ortho index.

    Rebuilding it per request would throw all three away — and would re-walk the orthophoto
    directory on every tile.
    """
    registry = ProviderRegistry(GisConfig())
    assert registry.get("fixture") is registry.get("fixture")

    registry.clear()
    assert registry.get("fixture") is not None


def test_provider_names_matches_the_registration_list() -> None:
    """★ The four-places rule, enforced from the one place gis can see.

    A provider registered but absent from ``PROVIDER_NAMES`` would have a name that **cannot
    be persisted** — an integration-time failure in a Celery worker, after a job has run.
    """
    assert set(PROVIDERS) == set(PROVIDER_NAMES)
    assert len(PROVIDER_NAMES) == len(set(PROVIDER_NAMES)), "no duplicate names"


def test_there_is_no_provider_for_the_excluded_application() -> None:
    """★★ THE LEGAL BOUNDARY, ASSERTED.

    The client's constraint is honoured as an **absence, not a disabled flag**: no provider,
    no scaffolding, no enum member, no scraper, no "advanced" option. This test fails if
    anyone ever adds one. See ``docs/legal/imagery-terms.md``.

    ``google_maps_static`` is a different service — Google Maps Platform, a documented
    commercial API with a key and a contract — and is separately gated by the double opt-in
    above.
    """
    for name in PROVIDER_NAMES:
        assert "earth" not in name.lower()
    assert "google_maps_static" in PROVIDER_NAMES, "the Maps Platform provider is separate"


# --- Helpers -----------------------------------------------------------------


def _a_tile_for(provider: ImageryProvider) -> tuple[int, int, int]:
    """Return a tile this provider can serve, covering the ortho fixture where relevant."""
    if provider.name == "local_orthophoto":
        from gis.tiles import lonlat_to_tile

        bbox, zoom = _a_bbox_for(provider)
        ref = lonlat_to_tile(*bbox.center(), zoom)
        return (ref.z, ref.x, ref.y)
    return (18, 137452, 89234)


def _a_bbox_for(provider: ImageryProvider) -> tuple[BBox, int]:
    """Return a bbox this provider covers, and a zoom it serves."""
    if provider.name == "local_orthophoto":
        from gis.crs import transform_point

        west, north = transform_point(_ORTHO_GT[0], _ORTHO_GT[3], f"EPSG:{_ORTHO_EPSG}", "EPSG:4326")
        east, south = transform_point(
            _ORTHO_GT[0] + _ORTHO_SIZE * _ORTHO_GT[1],
            _ORTHO_GT[3] + _ORTHO_SIZE * _ORTHO_GT[5],
            f"EPSG:{_ORTHO_EPSG}",
            "EPSG:4326",
        )
        # Inset slightly so the window sits strictly inside the raster.
        inset_x = (east - west) * 0.05
        inset_y = (north - south) * 0.05
        bbox = BBox(
            west=west + inset_x,
            south=south + inset_y,
            east=east - inset_x,
            north=north - inset_y,
        )
        return (bbox, provider.max_zoom)
    return (BBox(west=8.5, south=47.3, east=8.505, north=47.305), 16)
