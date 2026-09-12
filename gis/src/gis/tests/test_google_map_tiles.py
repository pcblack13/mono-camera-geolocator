"""``GoogleMapTilesProvider`` — gating, session handling and tile geometry.

★ The point of this module is that the RESTRICTIONS are tested, not just the happy path.
A provider whose licence enforcement is only documented is not enforced, so the capability
flags that mechanically block caching and export are asserted here as facts.
"""

from __future__ import annotations

import numpy as np
import pytest

from gis.errors import ProviderNotConfiguredError, TileOutOfRangeError
from gis.imagery.base import PROVIDER_NAMES
from gis.imagery.providers import PROVIDERS
from gis.imagery.providers.google_map_tiles import GoogleMapTilesProvider, _lease_seconds
from gis.imagery.registry import _NEVER_IN_A_CHAIN
from gis.types import BasemapKind


def _provider(**kw: object) -> GoogleMapTilesProvider:
    kw.setdefault("api_key", "test-key")
    kw.setdefault("tos_acknowledged", True)
    return GoogleMapTilesProvider(**kw)  # type: ignore[arg-type]


class TestRegistration:
    def test_is_in_the_canonical_name_tuple(self) -> None:
        assert "google_map_tiles" in PROVIDER_NAMES

    def test_is_in_the_registry(self) -> None:
        assert PROVIDERS["google_map_tiles"] is GoogleMapTilesProvider

    def test_is_never_reachable_by_fallback(self) -> None:
        """★ The whole point of the restriction: no chain may land here by accident."""
        assert "google_map_tiles" in _NEVER_IN_A_CHAIN


class TestDoubleOptIn:
    def test_key_alone_is_not_enough(self) -> None:
        p = GoogleMapTilesProvider(api_key="k", tos_acknowledged=False)
        assert p.is_configured() is False
        reason = p.configuration_reason() or ""
        assert "LE_GOOGLE_TOS_ACKNOWLEDGED" in reason

    def test_acknowledgement_alone_is_not_enough(self) -> None:
        p = GoogleMapTilesProvider(api_key="", tos_acknowledged=True)
        assert p.is_configured() is False
        assert "LE_GOOGLE_MAPS_STATIC_KEY" in (p.configuration_reason() or "")

    def test_both_together_configure_it(self) -> None:
        assert _provider().is_configured() is True
        assert _provider().configuration_reason() is None

    def test_construction_never_touches_the_network(self) -> None:
        """★ The registry constructs every provider merely to ask if it is configured.
        A handshake there would bill the operator for a question."""
        p = _provider()
        assert p._sessions == {}


class TestCapabilities:
    def test_licence_flags_are_restrictive(self) -> None:
        """★ These two Falses ARE the enforcement — the cache and the export writers
        gate on them. If this test ever goes green with True, compliance is gone."""
        c = _provider().capabilities()
        assert c.allows_caching is False
        assert c.allows_derivative_export is False

    def test_tile_geometry_matches_every_other_slippy_provider(self) -> None:
        """★ The reason this is a separate provider rather than a mode of the Static one:
        nothing downstream changes by a pixel."""
        c = _provider().capabilities()
        assert c.tile_size_px == 256
        assert c.native_crs == "EPSG:3857"

    def test_does_not_claim_a_native_bbox_endpoint(self) -> None:
        assert _provider().capabilities().supports_static_bbox is False

    def test_georef_matches_the_static_provider(self) -> None:
        """Same imagery behind both endpoints — a different figure would be invented."""
        from gis.imagery.providers.google_static import GoogleStaticProvider

        other = GoogleStaticProvider(api_key="k", tos_acknowledged=True)
        assert (
            _provider().capabilities().georef_ce90_m == other.capabilities().georef_ce90_m
        )


class TestGating:
    def test_unconfigured_tile_raises_before_any_request(self) -> None:
        p = GoogleMapTilesProvider(api_key="", tos_acknowledged=False)
        with pytest.raises(ProviderNotConfiguredError):
            p.get_tile(10, 1, 1)

    def test_unsupported_kind_is_refused(self) -> None:
        with pytest.raises(TileOutOfRangeError):
            _provider().get_tile(10, 1, 1, kind=BasemapKind.TERRAIN)

    def test_out_of_range_tile_is_refused(self) -> None:
        with pytest.raises(TileOutOfRangeError):
            _provider().get_tile(2, 99, 0)


class TestSessionLease:
    """★ A token believed valid after it dies turns every tile into a 403."""

    def test_far_future_expiry_yields_a_lease_short_of_it(self) -> None:
        import time

        ttl = _lease_seconds({"expiry": str(int(time.time()) + 14 * 86400)})
        assert 13 * 86400 < ttl < 14 * 86400

    def test_missing_expiry_falls_back_to_a_short_lease(self) -> None:
        assert _lease_seconds({}) == 900.0

    def test_unparseable_expiry_falls_back_rather_than_trusting_forever(self) -> None:
        assert _lease_seconds({"expiry": "not-a-number"}) == 900.0

    def test_already_expired_falls_back(self) -> None:
        import time

        assert _lease_seconds({"expiry": str(int(time.time()) - 10)}) == 900.0


class TestSessionReuse:
    def test_a_session_is_opened_once_and_reused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, object]] = []

        def fake_post_json(url, body, *, provider, config=None, params=None):  # type: ignore[no-untyped-def]
            calls.append(dict(body))
            import time

            return {"session": "tok", "expiry": str(int(time.time()) + 14 * 86400)}

        def fake_fetch_bytes(url, *, provider, config=None, headers=None, params=None):  # type: ignore[no-untyped-def]
            return b"png", "image/png"

        def fake_decode(data, *, provider, expect_size):  # type: ignore[no-untyped-def]
            return np.zeros((expect_size, expect_size, 3), dtype=np.uint8)

        import gis.imagery.providers.google_map_tiles as mod

        monkeypatch.setattr(mod, "post_json", fake_post_json)
        monkeypatch.setattr(mod, "fetch_bytes", fake_fetch_bytes)
        monkeypatch.setattr(mod, "decode_rgb", fake_decode)

        p = _provider()
        for _ in range(3):
            p.get_tile(12, 100, 100)
        assert len(calls) == 1, "session re-opened per tile — that is billable and wrong"

    def test_hybrid_gets_its_own_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """★ A session is bound to the mapType/layerTypes it was created with. Reusing a
        satellite token for hybrid silently returns satellite tiles."""
        bodies: list[dict[str, object]] = []

        def fake_post_json(url, body, *, provider, config=None, params=None):  # type: ignore[no-untyped-def]
            bodies.append(dict(body))
            import time

            return {"session": f"tok{len(bodies)}", "expiry": str(int(time.time()) + 86400)}

        import gis.imagery.providers.google_map_tiles as mod

        monkeypatch.setattr(mod, "post_json", fake_post_json)
        monkeypatch.setattr(
            mod, "fetch_bytes", lambda *a, **k: (b"png", "image/png")
        )
        monkeypatch.setattr(
            mod, "decode_rgb", lambda d, *, provider, expect_size: np.zeros((256, 256, 3), np.uint8)
        )

        p = _provider()
        p.get_tile(12, 100, 100, kind=BasemapKind.SATELLITE)
        p.get_tile(12, 100, 100, kind=BasemapKind.HYBRID)
        assert len(bodies) == 2
        assert "layerTypes" not in bodies[0]
        assert bodies[1]["layerTypes"] == ["layerRoadmap"]

    def test_empty_session_token_names_the_likely_cause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import gis.imagery.providers.google_map_tiles as mod

        monkeypatch.setattr(mod, "post_json", lambda *a, **k: {"session": ""})
        with pytest.raises(ProviderNotConfiguredError, match="Map Tiles API"):
            _provider().get_tile(12, 100, 100)

    def test_rejected_credential_points_at_the_console_not_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """★ The generic message sends the operator to re-verify a key that is fine."""
        import gis.imagery.providers.google_map_tiles as mod

        def boom(*a, **k):  # type: ignore[no-untyped-def]
            raise ProviderNotConfiguredError("HTTP 403", provider="google_map_tiles")

        monkeypatch.setattr(mod, "post_json", boom)
        with pytest.raises(ProviderNotConfiguredError, match="API restrictions"):
            _provider().get_tile(12, 100, 100)


class TestAttribution:
    def test_attribution_is_present_and_year_stamped(self) -> None:
        """★ This endpoint burns no credit into the pixels, so this string is the ONLY
        place the licence obligation is met."""
        text = _provider().attribution
        assert "Google" in text
        assert text.strip() != ""

    def test_terms_url_is_the_maps_platform_terms(self) -> None:
        assert "cloud.google.com" in _provider().terms_url
