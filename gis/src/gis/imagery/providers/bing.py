"""``BingAerialProvider`` — keyed, quadkey-addressed, metadata handshake required.

★ **BING MUST NOT BE INTEGRATED BY HARDCODING THE TILE URL.** The terms require resolving
the template via the Metadata API, and there are three independent reasons this is not
pedantry:

1. The ``{subdomain}`` list and the ``g=`` version **change**. A hardcoded URL rots.
2. The ``ImageryProviders`` block returns **per-bbox, per-zoom attribution strings** that
   are **legally required to be displayed for the specific area being viewed**. Static Bing
   attribution is non-compliant.
3. Hardcoding is a terms violation in itself.

So: one metadata call at first use, cached for 24 h, and attribution derived **per request**
from the ``coverageAreas`` bboxes and zoom ranges.

★ The quadkey math lives in ``gis.tiles``, not here — the quadkey scheme is tile math, not
a Bing implementation detail, and it is round-trip property-tested there.

Terms: https://www.microsoft.com/maps/product/terms.html (reviewed 2026-07-17).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from gis.config import GisConfig
from gis.errors import ProviderNotConfiguredError, ProviderTransportError
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.imagery.http import HttpConfig, fetch_bytes, fetch_json
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind, BBox

__all__ = ["BingAerialProvider"]

_log = logging.getLogger("gis.imagery.providers.bing")

_METADATA_URL: Final[str] = (
    "https://dev.virtualearth.net/REST/v1/Imagery/Metadata/{imagery_set}"
)
_METADATA_TTL_S: Final[float] = 86_400.0
"""24 h. The template and the vendor list change, but not per request."""

_BING_MIN_ZOOM: Final[int] = 1
"""★ NOTE: Bing's zoom starts at 1, NOT 0. There is no z0 Bing tile, and the quadkey of a
z0 tile is the empty string — which is not addressable."""

_BING_GEOREF_CE90_M: Final[float] = 6.0
"""★ AN ESTIMATE. Microsoft publishes no georegistration accuracy for Aerial, which
aggregates many vendors. Conservative, and deliberately not flattering — it propagates into
every exported GCP's ``total_ce90_m``."""


@dataclass(frozen=True, slots=True)
class _CoverageArea:
    """One ``ImageryProviders[].coverageAreas[]`` entry from the metadata response."""

    attribution: str
    bbox: BBox
    zoom_min: int
    zoom_max: int

    def applies(self, bbox: BBox, zoom: int) -> bool:
        """True iff this vendor's credit must be displayed for ``bbox`` at ``zoom``."""
        if not (self.zoom_min <= zoom <= self.zoom_max):
            return False
        if self.bbox.south > bbox.north or bbox.south > self.bbox.north:
            return False
        return not (self.bbox.east < bbox.west or bbox.east < self.bbox.west)


@dataclass(frozen=True, slots=True)
class _Metadata:
    """The resolved metadata handshake."""

    url_template: str
    subdomains: tuple[str, ...]
    tile_size: int
    zoom_min: int
    zoom_max: int
    coverage: tuple[_CoverageArea, ...]
    fetched_at: float


class BingAerialProvider(TileProviderMixin, ImageryProvider):
    """Bing Maps Aerial imagery.

    Args:
        config: Shared imagery settings.
        api_key: Overrides ``LE_BING_MAPS_KEY``. For tests.
    """

    def __init__(self, config: GisConfig | None = None, *, api_key: str | None = None) -> None:
        """Construct the provider. ★ NEVER raises, NEVER performs the handshake here.

        The metadata call happens on first FETCH, not at construction — the registry
        constructs every provider merely to ask each one whether it is configured, and a
        network round trip there would make ``GET /capabilities`` slow, flaky and, on an
        air-gapped box, hung.
        """
        cfg = config or GisConfig()
        env = os.environ
        self._key = (
            api_key if api_key is not None else env.get("LE_BING_MAPS_KEY", "")
        ).strip()
        self._imagery_set = env.get("LE_BING_IMAGERY_SET", "").strip() or "Aerial"
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = cfg.search.max_static_tiles * 16
        self._metadata: _Metadata | None = None
        self._lock = threading.Lock()
        self._subdomain_index = 0

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "bing_aerial"

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def min_zoom(self) -> int:
        meta = self._cached_metadata()
        return meta.zoom_min if meta else _BING_MIN_ZOOM

    @property
    def max_zoom(self) -> int:
        meta = self._cached_metadata()
        return meta.zoom_max if meta else 19

    @property
    def attribution(self) -> str:
        """The invariant Microsoft credit.

        ★ THIS IS NOT A COMPLIANT STANDALONE STRING. Bing's terms require the per-region
        vendor credits too; ``attribution_for_bbox()`` composes them, and
        ``get_static_bbox`` puts the composed string on the chip. This property exists
        because the ABC requires it and because it is the correct answer when no area is
        in hand.
        """
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """True iff a key is present. ★ PURE LOCAL CHECK — no handshake. Never raises."""
        return bool(self._key)

    def configuration_reason(self) -> str | None:
        if not self._key:
            return "requires LE_BING_MAPS_KEY (a Bing Maps API key)"
        return None

    def capabilities(self) -> ProviderCapabilities:
        """Report capabilities. ★ Total; never performs the handshake."""
        meta = self._cached_metadata()
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=meta.tile_size if meta else 256,
            typical_gsd_m=0.3,
            georef_ce90_m=_BING_GEOREF_CE90_M,
            imagery_date_known=False,
            rate_limit_rps=10.0,
            requires_attribution=True,
            allows_caching=True,
            allows_derivative_export=True,
            max_static_px=(4096, 4096),
            kinds=(BasemapKind.SATELLITE,),
            supports_multispectral=False,
            bands=("R", "G", "B"),
        )

    # ---- the metadata handshake --------------------------------------------

    def _cached_metadata(self) -> _Metadata | None:
        """Return cached metadata if fresh, else None. ★ NEVER fetches, never raises."""
        meta = self._metadata
        if meta is None:
            return None
        if (time.monotonic() - meta.fetched_at) > _METADATA_TTL_S:
            return None
        return meta

    def _require_metadata(self) -> _Metadata:
        """Return metadata, performing the handshake at most once per 24 h.

        Raises:
            ProviderNotConfiguredError: No key.
            ProviderTransportError: The handshake failed or returned an unusable body.
        """
        cached = self._cached_metadata()
        if cached is not None:
            return cached
        if not self._key:
            raise ProviderNotConfiguredError(
                self.configuration_reason() or "no Bing key", provider=self.name
            )
        with self._lock:
            cached = self._cached_metadata()
            if cached is not None:
                return cached
            meta = self._fetch_metadata()
            self._metadata = meta
            return meta

    def _fetch_metadata(self) -> _Metadata:
        """Perform the Metadata API handshake and parse it.

        Raises:
            ProviderTransportError: The response is missing the fields the terms require.
        """
        get_limiter(self.name).acquire()
        payload = fetch_json(
            _METADATA_URL.format(imagery_set=self._imagery_set),
            provider=self.name,
            config=self._http,
            params={
                "output": "json",
                "include": "ImageryProviders",
                "key": self._key,
            },
        )
        try:
            resource = payload["resourceSets"][0]["resources"][0]
            url_template = str(resource["imageUrl"])
            subdomains = tuple(str(s) for s in resource.get("imageUrlSubdomains", ()) or ())
            tile_size = int(resource.get("imageWidth", 256) or 256)
            zoom_min = int(resource.get("zoomMin", _BING_MIN_ZOOM))
            zoom_max = int(resource.get("zoomMax", 19))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderTransportError(
                f"Bing metadata response is missing the fields we need ({exc}); the "
                "Metadata API contract may have changed",
                provider=self.name,
            ) from exc

        coverage = _parse_coverage(resource.get("imageryProviders") or ())
        _log.info(
            "%s: metadata handshake ok (%d subdomain(s), %d vendor coverage area(s), "
            "z%d-%d)",
            self.name,
            len(subdomains),
            len(coverage),
            zoom_min,
            zoom_max,
        )
        return _Metadata(
            url_template=url_template,
            subdomains=subdomains,
            tile_size=tile_size,
            zoom_min=zoom_min,
            zoom_max=zoom_max,
            coverage=coverage,
            fetched_at=time.monotonic(),
        )

    def _next_subdomain(self, meta: _Metadata) -> str:
        """Round-robin the subdomains, as Bing's template intends."""
        if not meta.subdomains:
            return ""
        with self._lock:
            subdomain = meta.subdomains[self._subdomain_index % len(meta.subdomains)]
            self._subdomain_index += 1
        return subdomain

    def attribution_for_bbox(self, bbox: BBox, zoom: int) -> str:
        """Return the COMPLIANT attribution for a specific area and zoom.

        ★ This is the method that makes Bing legal to display. The terms require the vendor
        credits that apply to the **area being viewed**, so a static string is
        non-compliant. Degrades to the Microsoft-only credit when the handshake has not
        happened — never raises, because an attribution lookup must not fail a render.

        Args:
            bbox: The area being displayed.
            zoom: The zoom being displayed.

        Returns:
            ``"(c) {year} Microsoft Corporation - {vendor} - ..."``.
        """
        meta = self._cached_metadata()
        if meta is None:
            return self.attribution
        vendors = [c.attribution for c in meta.coverage if c.applies(bbox, zoom)]
        return attr.bing_attribution(vendors)

    # ---- imagery -----------------------------------------------------------

    def tile_url(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> str:
        """Return the upstream tile URL, resolved from the metadata template.

        ★ Requires the handshake — by design. There is no hardcoded fallback URL, because
        a hardcoded Bing URL is a terms violation and produces wrong attribution.

        Raises:
            ProviderNotConfiguredError: No key.
            ProviderTransportError: The handshake failed.
        """
        from gis.tiles import tile_to_quadkey  # noqa: PLC0415 - pure math, in gis.tiles

        meta = self._require_metadata()
        return (
            meta.url_template.replace("{subdomain}", self._next_subdomain(meta))
            .replace("{quadkey}", tile_to_quadkey(z, x, y))
            .replace("{culture}", "en-GB")
        )

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch one tile. See ``ImageryProvider.get_tile``."""
        self._check_tile_range(z, x, y, kind)
        meta = self._require_metadata()
        get_limiter(self.name).acquire()
        data, _mime = fetch_bytes(
            self.tile_url(z, x, y, kind=kind), provider=self.name, config=self._http
        )
        return decode_rgb(data, provider=self.name, expect_size=meta.tile_size)

    def get_tile_bytes(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> tuple[bytes, str]:
        """Return raw upstream bytes, skipping the decode/re-encode round trip."""
        self._check_tile_range(z, x, y, kind)
        self._require_metadata()
        get_limiter(self.name).acquire()
        data, mime = fetch_bytes(
            self.tile_url(z, x, y, kind=kind), provider=self.name, config=self._http
        )
        return (data, mime or "image/jpeg")

    def get_static_bbox(
        self, bbox: BBox, zoom: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> "Any":
        """Stitch a chip, then attach the PER-REGION attribution the terms require.

        ★ The only reason this overrides the mixin: ``TileProviderMixin`` puts
        ``self.attribution`` on the chip, which for Bing is only the Microsoft prefix.
        Compliance needs the vendor credits for *this bbox at this zoom*, and the chip is
        where attribution becomes permanent — it travels into ``match_results``, the CSV
        and every PDF from there, never by re-resolving the provider later.
        """
        import dataclasses  # noqa: PLC0415

        chip = super().get_static_bbox(bbox, zoom, kind=kind)
        return dataclasses.replace(chip, attribution=self.attribution_for_bbox(bbox, zoom))


def _parse_coverage(providers: object) -> tuple[_CoverageArea, ...]:
    """Parse the ``imageryProviders`` block into coverage areas. Never raises.

    A malformed entry is skipped rather than fatal: losing one vendor's credit is bad, and
    losing every tile because one entry was odd is worse. Skips are logged.
    """
    areas: list[_CoverageArea] = []
    if not isinstance(providers, (list, tuple)):
        return ()
    for entry in providers:
        try:
            text = str(entry["attribution"]).strip()
            for area in entry.get("coverageAreas") or ():
                # Bing's bbox order is [south, west, north, east].
                south, west, north, east = (float(v) for v in area["bbox"])
                areas.append(
                    _CoverageArea(
                        attribution=text,
                        bbox=BBox(west=west, south=south, east=east, north=north),
                        zoom_min=int(area.get("zoomMin", 1)),
                        zoom_max=int(area.get("zoomMax", 22)),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("bing: skipping a malformed imageryProviders entry: %s", exc)
    return tuple(areas)
