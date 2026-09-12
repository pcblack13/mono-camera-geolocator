"""``MapboxSatelliteProvider`` — keyed. ``LE_MAPBOX_ACCESS_TOKEN``.

The best keyed web option: sharp, reliable, clear terms, and the ``@2x`` economics below.
An empty token means the provider is **not offered** — ``is_configured()`` returns False
with a reason and the chain walks past it. **Not a crash** (L11).

Terms: https://www.mapbox.com/legal/tos (reviewed 2026-07-17). Caching is permitted only
within the ToS's limits, which are duration-capped — hence ``LE_MAPBOX_CACHE_TTL_SECONDS``
rather than an assumption that the global 30-day default is compliant.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.errors import ProviderNotConfiguredError
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.imagery.http import HttpConfig, fetch_bytes
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind

__all__ = ["MapboxSatelliteProvider"]

_log = logging.getLogger("gis.imagery.providers.mapbox")

_RASTER_TEMPLATE: Final[str] = (
    "https://api.mapbox.com/v4/{style_id}/{z}/{x}/{y}{retina}.{fmt}"
)
"""Raster Tiles API. ``?access_token=`` is added as a query param, never interpolated —
a token in a format string is a token in a log line."""

_DEFAULT_FORMAT: Final[str] = "jpg90"
"""★ jpg90, deliberately NOT a lower quality.

JPEG artefacts are a real matcher hazard: block-boundary ringing manufactures spurious
keypoints along an 8x8 grid, and those false features are **spatially regular** — which is
worse than noise, because a geometric verifier can lock onto the grid itself. The bandwidth
saved by jpg70 is paid for in fabricated correspondences.
"""

_MAPBOX_GEOREF_CE90_M: Final[float] = 5.0
"""★ AN ESTIMATE. Mapbox does not publish a georegistration accuracy for its satellite
layer, which aggregates Maxar and other vendors. 5 m is a conservative figure for the
high-resolution areas; the honest statement is that it is **unstated by the vendor**.
Deliberately not flattering — it propagates into every exported GCP's ``total_ce90_m``.
``capabilities().accuracy_status`` says ``"estimated"`` for exactly this reason.
"""

_MAPBOX_NATIVE_MAX_ZOOM: Final[int] = 19
"""★ AN ESTIMATE, like the CE90 above. Mapbox SERVES to z22 but native detail typically
ends around z18–19; above that the tiles are overzoomed (upsampled). Unpublished by the
vendor, hence ``native_resolution_status="estimated"`` — the UI warns past this zoom
rather than letting a surveyor place a GCP on interpolated pixels unawares."""

_DEFAULT_RATE_LIMIT_RPS: Final[float] = 10.0

#: ★ THE PRODUCT'S BUILT-IN PUBLIC TOKEN, so a fresh install has working Mapbox
#: imagery with zero configuration. A `pk.` token is DESIGNED to ship inside client
#: applications (every public web map embeds one); it grants tile reads only, and
#: usage counts against the product's shared Mapbox account. Any explicitly
#: configured token — `LE_MAPBOX_ACCESS_TOKEN` in the environment or a `.env` —
#: still wins: this is a fallback of last resort, not an override.
_DEFAULT_PUBLIC_TOKEN: Final[str] = (
    "pk.eyJ1Ijoic21hcnR0ZWNoMTMiLCJhIjoiY21zY3p0eDloMHJyYjJ4czVtZzh0MXg0aCJ9"
    ".GE9eE-ybKBz_-DZ_KzjoEw"
)
"""Self-imposed default; override with ``LE_MAPBOX_RATE_LIMIT_RPS``."""

#: A Mapbox token's shape: three dot-separated base64url parts, ``pk./sk./tk.`` first.
_TOKEN_SHAPE: Final = re.compile(r"^(?:pk|sk|tk)\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _usable_env_token(raw: str) -> str:
    """The explicit env token when it is USABLE; else the built-in default — loudly.

    ★ THE FIELD BUG THIS PREVENTS: a ``work/.env`` carrying ``pk.pk.eyJ…`` — a paste
    landing after the placeholder's own ``pk.`` prefix — overrode the WORKING
    built-in token, and every tile died with 401: a blank map while a healthy token
    sat unused, and the reason lived only in a log nobody was reading. An explicit
    token still wins when it is well-formed (that is the override contract); a
    MALFORMED one cannot be what anyone intended, so it is ignored with a warning
    that names the exact mistake and the file to fix, and the map keeps working.
    """
    token = (raw or "").strip()
    if not token:
        return _DEFAULT_PUBLIC_TOKEN
    if _TOKEN_SHAPE.match(token):
        return token
    if token.startswith(("pk.pk.", "sk.sk.", "tk.tk.")):
        reason = f"the '{token[:2]}.' prefix is doubled — delete one"
    else:
        reason = "a Mapbox token is three dot-separated parts, like pk.eyJ….…"
    _log.warning(
        "LE_MAPBOX_ACCESS_TOKEN is malformed (%s); IGNORING it and using the app's "
        "built-in token so the map keeps working. Fix or delete the "
        "LE_MAPBOX_ACCESS_TOKEN line — packaged app: <app-data>/work/.env; "
        "dev: backend/.env.",
        reason,
    )
    return _DEFAULT_PUBLIC_TOKEN


class MapboxSatelliteProvider(TileProviderMixin, ImageryProvider):
    """Mapbox Satellite raster tiles.

    Args:
        config: Shared imagery settings.
        access_token: Overrides ``LE_MAPBOX_ACCESS_TOKEN``. For tests.
    """

    def __init__(self, config: GisConfig | None = None, *, access_token: str | None = None) -> None:
        """Construct the provider. ★ NEVER raises on a missing token, NEVER fetches."""
        cfg = config or GisConfig()
        env = os.environ
        if access_token is not None:
            # An explicitly constructed token (tests, embedding callers) is verbatim.
            self._token = access_token.strip() or _DEFAULT_PUBLIC_TOKEN
        else:
            # ★ The env token is validated for SHAPE first — see _usable_env_token.
            self._token = _usable_env_token(env.get("LE_MAPBOX_ACCESS_TOKEN", ""))
        self._style_id = env.get("LE_MAPBOX_STYLE_ID", "").strip() or "mapbox.satellite"
        self._cache_ttl_s = _int_env(env, "LE_MAPBOX_CACHE_TTL_SECONDS", 2_592_000)
        self._negative_ttl_s = _int_env(env, "LE_MAPBOX_NEGATIVE_CACHE_TTL_SECONDS", 86_400)
        self._rate_limit_rps = _float_env(
            env, "LE_MAPBOX_RATE_LIMIT_RPS", _DEFAULT_RATE_LIMIT_RPS
        )
        self._use_2x = True
        # ★ @2x by default. A 512px retina tile is ONE request covering the same ground as
        #   a 256px tile at 4x the pixels: it bills as one request while roughly doubling
        #   linear resolution. Strictly better economics for feature matching, where
        #   keypoint density is the currency.
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = cfg.search.max_static_tiles * 16

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "mapbox_satellite"

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        """22 served. ★ Native detail typically runs to ~18-19; above that Mapbox
        overzooms. See ``capabilities().typical_gsd_m`` — ``max_zoom`` is what the provider
        SERVES, not where the detail stops."""
        return 22

    @property
    def attribution(self) -> str:
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    @property
    def cache_ttl_seconds(self) -> int:
        """★ The ToS-capped cache TTL (``LE_MAPBOX_CACHE_TTL_SECONDS``). Consulted by
        ``ImageryService`` on every cache write, so the global 30-day default is never
        *assumed* compliant for Mapbox. The cap is a term the operator must confirm,
        which is why it is explicit and configurable."""
        return self._cache_ttl_s

    @property
    def negative_cache_ttl_seconds(self) -> int:
        """``LE_MAPBOX_NEGATIVE_CACHE_TTL_SECONDS`` — how long "no imagery here" sticks."""
        return self._negative_ttl_s

    def cache_variant(self, kind: BasemapKind = BasemapKind.SATELLITE) -> str:
        """Fingerprint the rendering config into the cache key.

        ★ Style id, ``@2x`` scale and format all change the PIXELS a ``(z, x, y)`` names.
        Without them in the variant, switching ``LE_MAPBOX_STYLE_ID`` or ``_use_2x``
        would silently serve the OLD configuration's cached bytes under the new one.
        """
        scale = "@2x" if self._use_2x else "@1x"
        return f"{kind.value}.{self._style_id}.{scale}.{_DEFAULT_FORMAT}"

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """True iff an access token is present. ★ PURE LOCAL CHECK. Never raises."""
        return bool(self._token)

    def configuration_reason(self) -> str | None:
        if not self._token:
            return "requires LE_MAPBOX_ACCESS_TOKEN (a Mapbox public or secret token)"
        return None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=512 if self._use_2x else 256,
            typical_gsd_m=0.3,
            georef_ce90_m=_MAPBOX_GEOREF_CE90_M,
            imagery_date_known=False,
            rate_limit_rps=self._rate_limit_rps,
            requires_attribution=True,
            allows_caching=True,
            # ★ FROM THE ToS: permitted, but DURATION-CAPPED. See cache_ttl_seconds.
            allows_derivative_export=True,
            max_static_px=(4096, 4096),
            kinds=(BasemapKind.SATELLITE,),
            supports_multispectral=False,
            bands=("R", "G", "B"),
            # ★ HONEST METADATA. max_zoom=22 is what Mapbox SERVES; native detail ends
            #   around z19 (an estimate — unpublished by the vendor). The CE90 and GSD are
            #   likewise estimates, and the status fields say so — an estimate presented
            #   as a vendor fact would be a false survey claim.
            native_max_zoom=_MAPBOX_NATIVE_MAX_ZOOM,
            native_resolution_status="estimated",
            gsd_status="estimated",
            accuracy_status="estimated",
        )

    # ---- imagery -----------------------------------------------------------

    def tile_url(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> str:
        """Return the upstream tile URL, WITHOUT the access token.

        ★ The token is NOT in this string, deliberately. ``tile_url()`` is used for cache
        keys, debug logs and — under ``LE_IMAGERY_DIRECT_TILE_URLS`` — is handed to the
        browser. A secret in any of those is a leaked secret. The token travels as a query
        parameter on the actual request, in ``_fetch``.
        """
        return _RASTER_TEMPLATE.format(
            style_id=self._style_id,
            z=z,
            x=x,
            y=y,
            retina="@2x" if self._use_2x else "",
            fmt=_DEFAULT_FORMAT,
        )

    def _require_token(self) -> str:
        """Return the token or raise.

        Raises:
            ProviderNotConfiguredError: No token. ★ Raised at FETCH time, never at
                construction.
        """
        if not self._token:
            raise ProviderNotConfiguredError(
                self.configuration_reason() or "no Mapbox token", provider=self.name
            )
        return self._token

    def _fetch(self, url: str) -> tuple[bytes, str]:
        """Rate-limit and fetch, passing the token as a query parameter."""
        token = self._require_token()
        get_limiter(self.name, rate=self._rate_limit_rps).acquire()
        return fetch_bytes(
            url, provider=self.name, config=self._http, params={"access_token": token}
        )

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch one tile. See ``ImageryProvider.get_tile``."""
        self._check_tile_range(z, x, y, kind)
        data, _mime = self._fetch(self.tile_url(z, x, y, kind=kind))
        return decode_rgb(
            data, provider=self.name, expect_size=self.capabilities().tile_size_px
        )

    def get_tile_bytes(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> tuple[bytes, str]:
        """Return raw upstream bytes, skipping the decode/re-encode round trip."""
        self._check_tile_range(z, x, y, kind)
        data, mime = self._fetch(self.tile_url(z, x, y, kind=kind))
        return (data, mime or "image/jpeg")


def _int_env(env: "os._Environ[str] | dict[str, str]", key: str, default: int) -> int:
    """Read an int env var. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key, "")
    try:
        return int(raw) if raw.strip() else default
    except (AttributeError, ValueError):
        _log.warning("%s=%r is not an integer; using %d", key, raw, default)
        return default


def _float_env(env: "os._Environ[str] | dict[str, str]", key: str, default: float) -> float:
    """Read a float env var. Unparseable means the default, never a crash (L10)."""
    raw = env.get(key, "")
    try:
        return float(raw) if raw.strip() else default
    except (AttributeError, ValueError):
        _log.warning("%s=%r is not a number; using %s", key, raw, default)
        return default
