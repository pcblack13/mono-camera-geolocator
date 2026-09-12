"""``GoogleStaticProvider`` — ★ RESTRICTED. NEVER DEFAULT. DOUBLE OPT-IN.

> ## ⚠️ Read this before enabling.
>
> Google Maps Platform terms place restrictions that sit **directly athwart what
> LandExplorer does**. Terms of this kind commonly restrict: caching or persistent storage
> of imagery beyond narrow limits; creating derivative products from the imagery; using the
> content outside a Google Map; bulk or automated retrieval; and removing or obscuring
> Google attribution.
>
> **Extracting GCPs from Google satellite imagery and exporting them as a Shapefile
> deliverable is plausibly all of: derivative creation, use outside a Google Map, and
> prohibited caching — simultaneously.**
>
> **This provider exists for the narrow case where the operator has their own agreement
> with Google that permits their specific use. It is not a general-purpose option, and
> enabling it because it "looks sharper" is very likely a terms violation.**
>
> **This is not legal advice.** Terms change; only the operator knows their agreement. The
> burden is the operator's, deliberately.

# ★ WHAT THIS PROVIDER IS NOT.
#   This is Google Maps Platform - a documented commercial API, with a key and a contract.
#   It is a DIFFERENT SERVICE from the desktop globe application that the client's brief
#   excludes on both legal and technical grounds. That application is not a provider here,
#   has no scaffolding, no flag, no enum member and no scraper; it is an ABSENCE, not a
#   disabled feature, and this module is not a partial concession on it. It is a narrow
#   accommodation for operators with their own Maps Platform agreement.
#   See docs/legal/imagery-terms.md.

**Enforcement here is STRUCTURAL, not advisory** — documentation that relies on people
remembering it is not a control:

* **Absent from every default chain**, and unreachable by fallback. Only an explicit
  ``LE_IMAGERY_PROVIDER=google_maps_static`` selects it.
* ``is_configured()`` requires **BOTH** ``LE_GOOGLE_MAPS_STATIC_KEY`` **AND**
  ``LE_GOOGLE_TOS_ACKNOWLEDGED=true``. **The key alone is insufficient.** The second var has
  no technical function whatsoever — it exists to make enabling this an affirmative,
  auditable act by a human who read the paragraph above, rather than a side effect of
  having a key in the environment.
* ``capabilities().allows_caching = False`` -> the cache layer **refuses to persist** these
  tiles to disk or Redis, hard-falling to in-process LRU.
* ``capabilities().allows_derivative_export = False`` -> the export layer **refuses to
  embed this imagery in PDF map figures**. Coordinates still export; the *pixels* do not
  travel into a deliverable.
* First use logs a WARNING with the terms URL; the UI shows a non-dismissible banner.

That is what "the abstraction honours the legal constraint" means concretely: the
restriction is expressed as capability flags that **mechanically** gate caching and export,
so violating it requires editing capability code, not merely forgetting a rule.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.errors import AreaTooLargeError, ProviderNotConfiguredError, TileOutOfRangeError
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.imagery.http import HttpConfig, fetch_bytes
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind, BBox, GeoTransform, SatelliteChip

__all__ = ["GoogleStaticProvider"]

_log = logging.getLogger("gis.imagery.providers.google_static")

_STATIC_URL: Final[str] = "https://maps.googleapis.com/maps/api/staticmap"
_MAX_STATIC_EDGE: Final[int] = 640
"""640x640 per request; ``scale=2`` delivers 1280x1280 pixels for the same 640 map units."""

_GOOGLE_GEOREF_CE90_M: Final[float] = 5.0
"""★ AN ESTIMATE. Google publishes no georegistration accuracy for its satellite basemap.
Conservative and deliberately not flattering — it propagates into ``total_ce90_m``."""


class GoogleStaticProvider(TileProviderMixin, ImageryProvider):
    """Google Maps Static API satellite imagery. ★ Off by default, behind a double opt-in.

    Args:
        config: Shared imagery settings.
        api_key: Overrides ``LE_GOOGLE_MAPS_STATIC_KEY``. For tests.
        tos_acknowledged: Overrides ``LE_GOOGLE_TOS_ACKNOWLEDGED``. For tests.
    """

    def __init__(
        self,
        config: GisConfig | None = None,
        *,
        api_key: str | None = None,
        tos_acknowledged: bool | None = None,
    ) -> None:
        """Construct the provider. ★ NEVER raises, NEVER fetches.

        Constructing this provider is NOT enabling it. The registry constructs every
        provider just to ask whether it is configured, and this one answers False unless a
        human has affirmatively said otherwise.
        """
        cfg = config or GisConfig()
        env = os.environ
        self._key = (
            api_key if api_key is not None else env.get("LE_GOOGLE_MAPS_STATIC_KEY", "")
        ).strip()
        self._tos_acknowledged = (
            tos_acknowledged
            if tos_acknowledged is not None
            else _bool_env(env, "LE_GOOGLE_TOS_ACKNOWLEDGED", False)
        )
        self._scale = 2
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = 64
        self._warned = False

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "google_maps_static"

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        return 21

    @property
    def attribution(self) -> str:
        """★ The logo must render AS DELIVERED — not cropped, restyled or recomposed.

        Since ``allows_derivative_export=False`` blocks the figure from exports anyway,
        that requirement constrains only the live view.
        """
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """★ THE DOUBLE OPT-IN. Requires a key AND an explicit ToS acknowledgement.

        The key alone is insufficient, by design. ``LE_GOOGLE_TOS_ACKNOWLEDGED`` has **no
        technical function** — it exists so that enabling a provider whose terms plausibly
        forbid this product's core use is an affirmative, auditable act by a human who read
        the warning, and not a side effect of a key sitting in a shared environment.

        PURE LOCAL CHECK. Never raises.
        """
        return bool(self._key) and self._tos_acknowledged

    def configuration_reason(self) -> str | None:
        if not self._key and not self._tos_acknowledged:
            return (
                "requires BOTH LE_GOOGLE_MAPS_STATIC_KEY and LE_GOOGLE_TOS_ACKNOWLEDGED=true"
            )
        if not self._key:
            return "requires LE_GOOGLE_MAPS_STATIC_KEY"
        if not self._tos_acknowledged:
            return (
                "a key is present but LE_GOOGLE_TOS_ACKNOWLEDGED is not true. This is "
                "deliberate: Google Maps Platform terms plausibly forbid deriving and "
                "exporting survey coordinates from this imagery. Set it to true only if "
                "YOUR OWN agreement with Google permits your specific use. See "
                "docs/legal/imagery-terms.md."
            )
        return None

    def capabilities(self) -> ProviderCapabilities:
        """★ The two False flags below are the enforcement mechanism, not documentation."""
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=256,
            typical_gsd_m=0.3,
            georef_ce90_m=_GOOGLE_GEOREF_CE90_M,
            imagery_date_known=False,
            rate_limit_rps=10.0,
            requires_attribution=True,
            allows_caching=False,
            # ★★ FROM THE ToS. False makes DiskTileCache and RedisTileCache REFUSE the
            #    write and hard-fall to an in-process LRU. Compliance is enforced by the
            #    cache, not by developer memory: a background job cannot accidentally build
            #    a permanent on-disk copy of this imagery.
            allows_derivative_export=False,
            # ★★ FROM THE ToS. False makes ExportContext.chip = None, so the PDF omits the
            #    map figure and says so in ExportBundle.warnings. Coordinates still export;
            #    the pixels do not travel into a deliverable.
            max_static_px=(_MAX_STATIC_EDGE * 2, _MAX_STATIC_EDGE * 2),
            kinds=(BasemapKind.SATELLITE,),
            supports_multispectral=False,
            bands=("R", "G", "B"),
        )

    # ---- imagery -----------------------------------------------------------

    def _require_config(self) -> str:
        """Return the key, or raise.

        Raises:
            ProviderNotConfiguredError: No key, or no ToS acknowledgement.
        """
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                self.configuration_reason() or "not configured", provider=self.name
            )
        return self._key

    def _warn_once(self) -> None:
        """Log the terms warning on first use, once per process."""
        if self._warned:
            return
        self._warned = True
        _log.warning(
            "%s is ACTIVE. Google Maps Platform terms plausibly restrict caching, "
            "derivative creation and use outside a Google Map - which is what this product "
            "does. Persistent caching and PDF embedding are blocked mechanically. Verify "
            "your own agreement: %s",
            self.name,
            self.terms_url,
        )

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Synthesize a 256px slippy tile from the Static Maps API.

        ★ The Static Maps API is centre+zoom+size, not z/x/y — so the tile's centre is
        computed from the slippy grid and a 256px image is requested about it. This keeps
        the frontend's tile layer working through the same proxy route as any other
        provider.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: Must be SATELLITE.

        Returns:
            ``(256, 256, 3)`` uint8 RGB, C-contiguous.

        Raises:
            TileOutOfRangeError: Out-of-range coordinates or a non-SATELLITE kind.
            ProviderNotConfiguredError: Missing key or ToS acknowledgement.
        """
        from gis.tiles import tile_to_lonlat_center  # noqa: PLC0415

        self._check_tile_range(z, x, y, kind)
        key = self._require_config()
        self._warn_once()
        lon, lat = tile_to_lonlat_center(z, x, y)

        get_limiter(self.name).acquire()
        data, _mime = fetch_bytes(
            _STATIC_URL,
            provider=self.name,
            config=self._http,
            params={
                "center": f"{lat},{lon}",
                "zoom": str(z),
                "size": "256x256",
                "scale": "1",
                "maptype": "satellite",
                "format": "png",
                "key": key,
            },
        )
        return decode_rgb(data, provider=self.name, expect_size=256)

    def get_static_bbox(
        self, bbox: BBox, zoom: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> SatelliteChip:
        """Fetch a chip NATIVELY from the Static Maps API — no stitching.

        ★ Overrides the mixin because this provider HAS a native bbox endpoint, and because
        stitching would mean N requests where one suffices — which, on a metered API whose
        terms restrict bulk retrieval, is both a cost and a compliance problem.

        Args:
            bbox: EPSG:4326 target extent.
            zoom: Zoom level.
            kind: Must be SATELLITE.

        Returns:
            A ``SatelliteChip`` in EPSG:3857.

        Raises:
            AreaTooLargeError: The bbox needs more than 640x640 map pixels at ``zoom``.
                ★ A hard API limit, not a policy choice.
            TileOutOfRangeError: Non-SATELLITE kind, or a zoom out of range.
            ProviderNotConfiguredError: Missing key or ToS acknowledgement.
        """
        from gis.tiles import lonlat_to_meters, resolution_at  # noqa: PLC0415

        if kind is not BasemapKind.SATELLITE:
            raise TileOutOfRangeError(
                f"{self.name} serves only kind='satellite'", provider=self.name
            )
        if not (self.min_zoom <= zoom <= self.max_zoom):
            raise TileOutOfRangeError(
                f"zoom {zoom} outside [{self.min_zoom}, {self.max_zoom}]", provider=self.name
            )
        key = self._require_config()
        self._warn_once()

        # Web Mercator pixel span of the bbox at this zoom.
        mercator_mpp = (2.0 * 20037508.342789244) / (256.0 * float(1 << zoom))
        west_m, south_m = lonlat_to_meters(bbox.west, bbox.south)
        east_m, north_m = lonlat_to_meters(bbox.east, bbox.north)
        width_px = int(math.ceil((east_m - west_m) / mercator_mpp))
        height_px = int(math.ceil((north_m - south_m) / mercator_mpp))
        if width_px > _MAX_STATIC_EDGE or height_px > _MAX_STATIC_EDGE:
            raise AreaTooLargeError(
                f"bbox is {width_px}x{height_px} px at z={zoom}; the Static Maps API caps "
                f"a request at {_MAX_STATIC_EDGE}x{_MAX_STATIC_EDGE}. Request a smaller "
                "bbox or a lower zoom.",
                provider=self.name,
            )
        width_px = max(1, width_px)
        height_px = max(1, height_px)

        centre_lon, centre_lat = bbox.center()
        get_limiter(self.name).acquire()
        data, _mime = fetch_bytes(
            _STATIC_URL,
            provider=self.name,
            config=self._http,
            params={
                "center": f"{centre_lat},{centre_lon}",
                "zoom": str(zoom),
                "size": f"{width_px}x{height_px}",
                "scale": str(self._scale),
                "maptype": "satellite",
                "format": "png",
                "key": key,
            },
        )
        image = decode_rgb(data, provider=self.name)

        # ★ The geotransform is derived from what was ACTUALLY returned. scale=2 delivers
        #   twice the pixels for the same ground, so the delivered pixel size is the map
        #   pixel size divided by the delivered/requested ratio — read off the array rather
        #   than assumed, because the API silently clamps odd sizes.
        delivered_h, delivered_w = image.shape[0], image.shape[1]
        pixel_size = mercator_mpp * (width_px / delivered_w)
        centre_x, centre_y = lonlat_to_meters(centre_lon, centre_lat)
        gt: GeoTransform = (
            centre_x - (delivered_w / 2.0) * pixel_size,
            pixel_size,
            0.0,
            centre_y + (delivered_h / 2.0) * pixel_size,
            0.0,
            -pixel_size,
        )
        return SatelliteChip(
            image=image,
            geotransform=gt,
            crs="EPSG:3857",
            provider_name=self.name,
            attribution=self.attribution,
            terms_url=self.terms_url,
            zoom=zoom,
            captured_at=None,
            gsd_m=resolution_at(zoom, centre_lat, 256) * (width_px / delivered_w),
            georef_ce90_m=_GOOGLE_GEOREF_CE90_M,
            is_authoritative=False,
            kind=BasemapKind.SATELLITE,
            placeholder_fraction=0.0,
            bands=("R", "G", "B"),
            extra_bands=None,
        )


def _bool_env(env: "os._Environ[str] | dict[str, str]", key: str, default: bool) -> bool:
    """Read a bool env var. Anything unrecognised means the default (L10).

    ★ For ``LE_GOOGLE_TOS_ACKNOWLEDGED`` the default is False, so anything other than an
    explicit affirmative leaves this provider off. That asymmetry is the point.
    """
    raw = env.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default
