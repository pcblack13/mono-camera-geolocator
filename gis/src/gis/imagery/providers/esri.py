"""``EsriWorldImageryProvider`` — ★★ THE KEYLESS DEFAULT (L2).

**L2: ``docker compose up`` with an empty ``.env`` yields a working satellite search.**
This provider is how that law is kept: no key, no account, no configuration, global
coverage at ~0.3-1 m. ``is_configured()`` is unconditionally True, which is the entire
point — every keyed provider self-skips the chain and the zero-config machine lands here
with no branching.

> ### ★ Keyless is NOT licence-free. Read this before shipping paid work.
>
> Esri World Imagery is not public domain. The tile endpoint is reachable without
> authentication and the basemap is broadly used, but access is governed by Esri's terms
> and by the terms of the upstream vendors (Maxar and others) whose imagery it aggregates.
> **Reachable is not licensed.** Commercial redistribution, bulk caching, and use as a
> source for **derived survey deliverables** are exactly the uses most likely to exceed
> what is permitted — and a derived survey deliverable is precisely what LandExplorer
> produces.
>
> **Default = zero-config bootstrap. It is NOT a determination that your production use is
> licensed.** An operator delivering paid survey products must read the terms, and will
> likely need either an ArcGIS subscription with appropriate rights, or a different
> provider. For real surveying, ``local_ortho.py`` is the correct answer on both accuracy
> and licence grounds.
>
> This caveat is repeated in ``README.md``, in the first-run log banner, in the UI provider
> picker and on every PDF export. The repetition is deliberate: the product refuses to let
> a convenient default read as a recommendation.
"""

from __future__ import annotations

import logging
import os
from typing import Final

import numpy as np

from gis.config import GisConfig
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    composite_over,
    decode_rgb,
    decode_rgba,
)
from gis.imagery.http import HttpConfig, fetch_bytes
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind

__all__ = ["EsriWorldImageryProvider"]

_log = logging.getLogger("gis.imagery.providers.esri")

_SATELLITE_TEMPLATE: Final[str] = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
    "tile/{z}/{y}/{x}"
)
"""★★ NOTE THE AXIS ORDER: ``{z}/{y}/{x}`` — ROW BEFORE COLUMN.

**This is the single most common integration bug against this endpoint**, because it is
visually one character from the near-universal ``{z}/{x}/{y}`` and — crucially — it does
not 404. It returns *plausible imagery of the wrong place*, which a matcher will happily
match and a surveyor will happily export. ``tile_url()`` is the ONLY place the ordering is
expressed, and ``test_providers_contract`` pins a known ``(z, x, y)`` to a known URL.
"""

_REFERENCE_TEMPLATE: Final[str] = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/"
    "World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
)
"""The labels/boundaries overlay composited over imagery to serve ``kind=hybrid``."""

_TERRAIN_TEMPLATE: Final[str] = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/"
    "MapServer/tile/{z}/{y}/{x}"
)

_DEFAULT_MAX_ZOOM: Final[int] = 19
"""0-19 global; 20-23 in selected metros. ★ 19 is the honest global answer: promising 23
would make ``choose_zoom`` pick a level that 404s outside a handful of cities."""

_ESRI_GEOREF_CE90_M: Final[float] = 8.0
"""★ AN ESTIMATE, NAMED RATHER THAN HIDDEN. Esri publishes no per-tile georegistration
accuracy for World Imagery, and the mosaic aggregates many vendors' products with
different control. 8 m is a conservative middle for the Maxar-sourced high-resolution
areas this product targets; the honest statement is that **nobody outside Esri knows this
number**, which is itself an argument for ``local_orthophoto`` on real survey work. It is
deliberately NOT flattering: this value propagates into ``total_ce90_m`` on every exported
GCP, and understating it would understate a survey claim.
"""


class EsriWorldImageryProvider(TileProviderMixin, ImageryProvider):
    """Esri World Imagery. Keyless, global, the zero-config default.

    Terms: https://www.esri.com/en-us/legal/terms/full-master-agreement (reviewed
    2026-07-17). See this module's docstring before using it for a deliverable.
    """

    def __init__(self, config: GisConfig | None = None) -> None:
        """Construct the provider. ★ NEVER raises, NEVER touches the network.

        Args:
            config: Shared imagery settings. Defaults apply when None.
        """
        cfg = config or GisConfig()
        env = os.environ
        self._satellite_template = (
            env.get("LE_ESRI_IMAGERY_TILE_URL_TEMPLATE", "").strip() or _SATELLITE_TEMPLATE
        )
        self._reference_template = (
            env.get("LE_ESRI_REFERENCE_TILE_URL_TEMPLATE", "").strip() or _REFERENCE_TEMPLATE
        )
        self._terrain_template = (
            env.get("LE_ESRI_TERRAIN_TILE_URL_TEMPLATE", "").strip() or _TERRAIN_TEMPLATE
        )
        self._max_zoom = _int_env(env, "LE_ESRI_MAX_ZOOM", _DEFAULT_MAX_ZOOM)
        self._rate_limit_rps = _float_env(env, "LE_ESRI_RATE_LIMIT_RPS", 8.0)
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = cfg.search.max_static_tiles * 16
        self._warned_caveat = False

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "esri_world_imagery"

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        return self._max_zoom

    @property
    def attribution(self) -> str:
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """Always True. ★ THIS IS L2.

        No key, no account, no path. That is what makes an empty ``.env`` produce a working
        satellite search, and what lets every keyed provider self-skip the chain without
        any special-casing anywhere.
        """
        return True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tiles=True,
            supports_static_bbox=True,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=256,
            typical_gsd_m=0.3,
            georef_ce90_m=_ESRI_GEOREF_CE90_M,
            imagery_date_known=False,
            # ★ False: the per-pixel date lives in a companion World Imagery Metadata
            #   layer, not in the tile response. Claiming True and returning None would
            #   make captured_at look like "not captured" rather than "not known".
            rate_limit_rps=self._rate_limit_rps,
            requires_attribution=True,
            allows_caching=True,
            # ★ FROM THE ToS, and the honest reading is "verify". True here reflects that
            #   Esri's terms do not flatly forbid caching the way Google's do — it is NOT a
            #   determination that YOUR caching is licensed. See LE_IMAGERY_TILE_CACHE_TTL_SECONDS
            #   and docs/legal/imagery-terms.md.
            allows_derivative_export=True,
            max_static_px=(4096, 4096),
            kinds=(BasemapKind.SATELLITE, BasemapKind.HYBRID, BasemapKind.TERRAIN),
            supports_multispectral=False,
            bands=("R", "G", "B"),
        )

    # ---- imagery -----------------------------------------------------------

    def tile_url(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> str:
        """Return the upstream tile URL.

        ★ THE ONLY PLACE THE ``{z}/{y}/{x}`` AXIS ORDER IS EXPRESSED. See
        ``_SATELLITE_TEMPLATE``: getting this wrong yields plausible imagery of the wrong
        place, not a 404.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: Which basemap rendering. HYBRID resolves to the imagery URL, since the
                overlay is composited on top of it.

        Returns:
            The absolute upstream URL.
        """
        template = {
            BasemapKind.SATELLITE: self._satellite_template,
            BasemapKind.HYBRID: self._satellite_template,
            BasemapKind.TERRAIN: self._terrain_template,
        }.get(kind, self._satellite_template)
        return template.format(z=z, y=y, x=x)

    def _log_caveat_once(self) -> None:
        """Emit the keyless-is-not-licence-free banner on first use, once per process."""
        if self._warned_caveat:
            return
        self._warned_caveat = True
        _log.warning("%s in use. %s", self.name, attr.ESRI_KEYLESS_CAVEAT)

    def _fetch(self, url: str) -> bytes:
        """Rate-limit and fetch one URL's bytes."""
        get_limiter(self.name, rate=self._rate_limit_rps).acquire()
        data, _mime = fetch_bytes(url, provider=self.name, config=self._http)
        return data

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch one tile. See ``ImageryProvider.get_tile``."""
        self._check_tile_range(z, x, y, kind)
        self._log_caveat_once()

        base = decode_rgb(
            self._fetch(self.tile_url(z, x, y, kind=kind)), provider=self.name, expect_size=256
        )
        if kind is not BasemapKind.HYBRID:
            return base

        # ★ Hybrid is composited SERVER-SIDE, here, so the browser and the exports get one
        #   consistent image and the overlay can never be missing from a PDF because a
        #   second layer failed to load. A failed overlay degrades to plain imagery with a
        #   warning (L11) — a hybrid tile without labels is imagery; a failed request is a
        #   blank map.
        try:
            overlay = decode_rgba(
                self._fetch(self._reference_template.format(z=z, y=y, x=x)), provider=self.name
            )
        except Exception as exc:  # noqa: BLE001 - labels are cosmetic; imagery is not
            _log.warning(
                "%s: reference overlay unavailable for z=%d x=%d y=%d (%s); serving "
                "imagery without labels",
                self.name,
                z,
                x,
                y,
                exc,
            )
            return base
        return composite_over(base, overlay)

    def get_tile_bytes(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> tuple[bytes, str]:
        """Return the raw upstream tile bytes, for the proxy.

        ★ Overridden to skip the decode/re-encode round trip: Esri serves JPEG, and the
        proxy's job is to pass bytes through, not to re-compress them. Re-encoding would
        add latency AND a generation of JPEG loss to every browser tile.
        """
        self._check_tile_range(z, x, y, kind)
        self._log_caveat_once()
        get_limiter(self.name, rate=self._rate_limit_rps).acquire()
        data, mime = fetch_bytes(
            self.tile_url(z, x, y, kind=kind), provider=self.name, config=self._http
        )
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
