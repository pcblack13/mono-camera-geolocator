"""``SentinelCopernicusProvider`` — free, fully open, and **10 m**.

> ### ★ Honest suitability assessment: Sentinel-2 is nearly useless for the core GCP task,
> ### and it is in the product anyway for reasons that are not GCP accuracy.
>
> The argument is arithmetic, not taste. **A GCP's positional error cannot beat the
> imagery's ground sample distance.** At 10 m/px a landmark localised to a *perfect* +/-1 px
> is +/-10 m on the ground. Realistic sub-pixel work at +/-0.5 px is still ~+/-5 m *before*
> provider georegistration error (Sentinel-2 L1C/L2A is specified at roughly 10-12 m at
> 95%) and terrain effects. Compounded: **+/-10-20 m.**
>
> For agricultural GCP work that is a category error. A field-boundary corner, a gate post,
> an irrigation valve, a pivot centre — the actual GCP targets — are 0.3-3 m objects. **At
> 10 m/px they occupy less than one pixel. There is nothing to match.** Survey-grade GCPs
> are specified at centimetre-to-decimetre accuracy; this would be off by **2-3 orders of
> magnitude**.
>
> It ships because it earns its place at three *other* jobs:
> 1. **Coarse-to-fine anchor.** z13-14 is exactly the coarse stage — narrowing a 5 km
>    radius to a ~500 m candidate before a *keyed* provider is asked for a single
>    high-zoom tile.
> 2. **The only fully-open, commercial-safe web source.** When licensing forbids
>    Esri/Mapbox/Bing for a deliverable and no orthophotos exist, this is the legally
>    unambiguous fallback. **Coarse and legal beats sharp and prohibited.**
> 3. **Temporal context.** ~5-day revisit plus NIR gives NDVI-style crop-state layers —
>    genuinely valuable agricultural context, sitting *beside* the GCP result rather than
>    producing it.

★ **The provider REFUSES ``zoom > LE_SENTINEL_MAX_ZOOM`` (default 15) with
``TileOutOfRangeError``** rather than serving upsampled mush that *looks* like detail. **A
provider must not manufacture the appearance of resolution it does not have** — an
interpolated z18 Sentinel tile is a lie that a matcher will confidently act on.

Terms: https://dataspace.copernicus.eu/terms-and-conditions (reviewed 2026-07-17).
Licence: free, full, open — genuinely permissive, including commercial use.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.errors import (
    ProviderNotConfiguredError,
    ProviderTransportError,
    TileOutOfRangeError,
)
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.imagery.http import HttpConfig, fetch_bytes, post_form
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind

__all__ = ["SentinelCopernicusProvider"]

_log = logging.getLogger("gis.imagery.providers.sentinel")

_TOKEN_URL: Final[str] = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
_WMTS_URL: Final[str] = "https://sh.dataspace.copernicus.eu/ogc/wmts/{instance_id}"

_DEFAULT_MAX_ZOOM: Final[int] = 15
"""★ 15, and the REFUSAL above it is the point.

Native Sentinel-2 detail is ~z13-14 (z14 ~= 9.55 m/px at the equator). 15 is one level of
honest headroom. Above it the provider raises rather than interpolating — see this module's
docstring.
"""

_SENTINEL_GEOREF_CE90_M: Final[float] = 11.0
"""★ PUBLISHED, not estimated — the one provider here where that is true. Sentinel-2
L1C/L2A geolocation is specified at roughly 10-12 m at 95% confidence; 11 m is the middle
of the published band. Documented source: ESA's Sentinel-2 products specification.
"""

_TOKEN_SKEW_S: Final[float] = 60.0
"""Refresh a token this long before it actually expires, so an in-flight chip's last tile
does not 401 on a boundary."""


class SentinelCopernicusProvider(TileProviderMixin, ImageryProvider):
    """Sentinel-2 imagery via Copernicus Data Space (Sentinel Hub WMTS).

    Args:
        config: Shared imagery settings.
        client_id: Overrides ``LE_COPERNICUS_CLIENT_ID``. For tests.
        client_secret: Overrides ``LE_COPERNICUS_CLIENT_SECRET``. For tests.
    """

    def __init__(
        self,
        config: GisConfig | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        """Construct the provider. ★ NEVER raises, NEVER authenticates here."""
        cfg = config or GisConfig()
        env = os.environ
        self._client_id = (
            client_id if client_id is not None else env.get("LE_COPERNICUS_CLIENT_ID", "")
        ).strip()
        self._client_secret = (
            client_secret
            if client_secret is not None
            else env.get("LE_COPERNICUS_CLIENT_SECRET", "")
        ).strip()
        self._instance_id = env.get("LE_COPERNICUS_INSTANCE_ID", "").strip()
        self._max_cloud_pct = _int_env(env, "LE_COPERNICUS_MAX_CLOUD_PCT", 20)
        self._max_zoom = _int_env(env, "LE_SENTINEL_MAX_ZOOM", _DEFAULT_MAX_ZOOM)
        self._layer = env.get("LE_COPERNICUS_LAYER", "").strip() or "TRUE-COLOR-S2L2A"
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = cfg.search.max_static_tiles * 16
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "sentinel_copernicus"

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        """★ 15 by default, and it is a REFUSAL boundary, not a hint. See the module
        docstring: serving z18 Sentinel would be manufacturing the appearance of a
        resolution that does not exist."""
        return self._max_zoom

    @property
    def attribution(self) -> str:
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    @property
    def variant(self) -> str:
        """The cache variant for the current mosaic window.

        ★ THIS FIELD PREVENTS THE NASTIEST CACHE BUG IN THIS DOMAIN. An L2A June composite
        and an October composite are the SAME ``(z, x, y)`` and utterly different pixels.
        Without the variant in the cache key, a re-run silently matches against the wrong
        season's imagery and produces **confidently wrong coordinates**.
        """
        return f"{self._layer.lower()}-cloud{self._max_cloud_pct}"

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """True iff OAuth2 credentials and an instance id are present.

        ★ PURE LOCAL CHECK — no token request. Never raises.
        """
        return bool(self._client_id and self._client_secret and self._instance_id)

    def configuration_reason(self) -> str | None:
        missing = [
            var
            for var, value in (
                ("LE_COPERNICUS_CLIENT_ID", self._client_id),
                ("LE_COPERNICUS_CLIENT_SECRET", self._client_secret),
                ("LE_COPERNICUS_INSTANCE_ID", self._instance_id),
            )
            if not value
        ]
        if not missing:
            return None
        return (
            f"requires {', '.join(missing)} (a free Copernicus Data Space account with "
            "Sentinel Hub OAuth2 client credentials)"
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=256,
            typical_gsd_m=10.0,
            # ★ 10 m, stated plainly. This is the number that makes Sentinel unsuitable as
            #   a GCP source, and every export carries it with an explicit accuracy caveat.
            georef_ce90_m=_SENTINEL_GEOREF_CE90_M,
            imagery_date_known=True,
            rate_limit_rps=5.0,
            requires_attribution=True,
            allows_caching=True,
            # ★ FROM THE ToS: genuinely unrestricted. The one provider where this is a fact
            #   rather than a "verify".
            allows_derivative_export=True,
            max_static_px=(2500, 2500),
            kinds=(BasemapKind.SATELLITE,),
            supports_multispectral=False,
            # ★ False for THIS layer. The true-colour WMTS layer returns RGB only. NIR/SWIR
            #   (which ndwi/mndwi need) would come from a different layer configuration, and
            #   claiming multispectral here would make gis.semantics' indices read bands
            #   that are not in the response.
            bands=("R", "G", "B"),
        )

    # ---- OAuth2 ------------------------------------------------------------

    def _require_token(self) -> str:
        """Return a valid access token, refreshing when near expiry.

        Raises:
            ProviderNotConfiguredError: Credentials are missing or were rejected.
            ProviderTransportError: The token endpoint failed or returned no token.
        """
        now = time.monotonic()
        token = self._token
        if token is not None and now < (self._token_expires_at - _TOKEN_SKEW_S):
            return token
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                self.configuration_reason() or "no Copernicus credentials",
                provider=self.name,
            )
        with self._lock:
            now = time.monotonic()
            if self._token is not None and now < (self._token_expires_at - _TOKEN_SKEW_S):
                return self._token
            payload = post_form(
                _TOKEN_URL,
                {
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                provider=self.name,
                config=self._http,
            )
            try:
                access_token = str(payload["access_token"])
                expires_in = float(payload.get("expires_in", 600))
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderTransportError(
                    f"Copernicus token response carried no usable access_token ({exc})",
                    provider=self.name,
                ) from exc
            self._token = access_token
            self._token_expires_at = time.monotonic() + expires_in
            _log.info("%s: obtained an access token (expires in %.0fs)", self.name, expires_in)
            return access_token

    # ---- imagery -----------------------------------------------------------

    def tile_url(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> str:
        """Return the upstream WMTS tile URL, WITHOUT the bearer token.

        ★ The token is a header, not a query parameter, and never appears in this string —
        which is used for cache keys and debug logs.
        """
        return _WMTS_URL.format(instance_id=self._instance_id)

    def _check_zoom(self, z: int) -> None:
        """Refuse a zoom Sentinel cannot honestly serve.

        Raises:
            TileOutOfRangeError: ``z > max_zoom``. ★ The refusal is the feature. An
                interpolated z18 Sentinel tile looks like detail and is not; a matcher would
                act on it confidently and a surveyor would export the result.
        """
        if z > self._max_zoom:
            raise TileOutOfRangeError(
                f"Sentinel-2 is a 10 m/px source: zoom {z} exceeds LE_SENTINEL_MAX_ZOOM="
                f"{self._max_zoom}. Serving it would mean upsampling, which manufactures "
                "the appearance of resolution that does not exist. Use a higher-resolution "
                "provider, or a local orthophoto, for zoom > "
                f"{self._max_zoom}.",
                provider=self.name,
            )

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch one tile. See ``ImageryProvider.get_tile``.

        Raises:
            TileOutOfRangeError: ``z`` above ``LE_SENTINEL_MAX_ZOOM``. See ``_check_zoom``.
        """
        self._check_zoom(z)
        self._check_tile_range(z, x, y, kind)
        token = self._require_token()
        get_limiter(self.name).acquire()
        data, _mime = fetch_bytes(
            self.tile_url(z, x, y, kind=kind),
            provider=self.name,
            config=self._http,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "service": "WMTS",
                "request": "GetTile",
                "version": "1.0.0",
                "layer": self._layer,
                "style": "default",
                "format": "image/png",
                "tilematrixset": "PopularWebMercator256",
                "tilematrix": str(z),
                "tilecol": str(x),
                "tilerow": str(y),
                "maxcc": str(self._max_cloud_pct),
            },
        )
        return decode_rgb(data, provider=self.name, expect_size=256)


def _int_env(env: "os._Environ[str] | dict[str, str]", key: str, default: int) -> int:
    """Read an int env var. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key, "")
    try:
        return int(raw) if raw.strip() else default
    except (AttributeError, ValueError):
        _log.warning("%s=%r is not an integer; using %d", key, raw, default)
        return default
