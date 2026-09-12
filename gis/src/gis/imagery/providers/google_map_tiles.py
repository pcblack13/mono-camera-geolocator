"""``GoogleMapTilesProvider`` — ★ RESTRICTED. NEVER DEFAULT. DOUBLE OPT-IN.

> ## ⚠️ The warning on ``google_static`` applies here in full.
>
> This is the same commercial service under the same agreement — Google Maps Platform —
> reached through a different endpoint. Everything ``google_static``'s header says about
> caching, derivative creation, use outside a Google Map and attribution applies
> identically, and is enforced here by the identical capability flags. Read that module's
> header; it is not repeated at length here so that the two cannot drift apart.
>
> **This is not legal advice.** The burden is the operator's, deliberately.

# ★ WHY THIS EXISTS ALONGSIDE ``google_maps_static``.
#   The Static Maps API returns a *picture of a map*, and Google burns the "Google"
#   wordmark and the data-provider credits ("Airbus, Landsat / Copernicus, Maxar
#   Technologies") into the bottom of EVERY image it returns. That is correct behaviour
#   for its intended use — one map image on one page — but LandExplorer synthesizes a
#   slippy grid by making one request per 256px tile, so the credit strip is baked into
#   every tile and the viewport ends up tiled with repeated text. It cannot be cropped:
#   removing or obscuring Google attribution is prohibited by the terms, and the pixels
#   arrive that way regardless.
#
#   The Map Tiles API is the product Google publishes FOR tiled use. It serves genuine
#   z/x/y raster tiles with NO credits burned in, and returns the required attribution
#   text SEPARATELY — which this application already renders exactly once, in
#   `ProviderAttribution`, as a non-dismissible element. So the obligation is met more
#   faithfully than by the Static API, not less: the credit is legible instead of being
#   repeated twenty times in 9px type across the imagery.
#
#   Tile geometry is IDENTICAL to every other slippy provider (256px, EPSG:3857, z/x/y),
#   which is the reason this is a new provider rather than a mode of the old one. Nothing
#   downstream — chip stitching, GSD readouts, the match pipeline — changes by one pixel.

# ★ WHAT THIS PROVIDER IS NOT.
#   As with ``google_static``: this is Google Maps Platform, a documented commercial API
#   with a key and a contract. It is a DIFFERENT SERVICE from the desktop globe
#   application the brief excludes, which remains an ABSENCE here, not a disabled feature.
#   It is likewise NOT the undocumented ``mt{0-3}.google.com/vt`` tile endpoint, which is
#   categorically forbidden (docs/legal/imagery-terms.md §1) and is not reachable from
#   this module by any flag.

**Enforcement is STRUCTURAL, identical to ``google_static``**: absent from every default
chain; requires BOTH ``LE_GOOGLE_MAPS_STATIC_KEY`` AND ``LE_GOOGLE_TOS_ACKNOWLEDGED=true``;
``allows_caching=False`` and ``allows_derivative_export=False`` mechanically block disk
persistence and PDF embedding.

★ **The key is shared with ``google_maps_static`` deliberately** — it is one credential on
one Google project under one agreement, and inventing a second variable would imply a
second contract that does not exist. The Map Tiles API must be enabled on that key
separately in the Cloud console; when it is not, Google answers 403 and
:meth:`get_tile` surfaces that as a configuration error rather than a transport blip.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Final

import numpy as np

from gis.config import GisConfig
from gis.errors import ProviderNotConfiguredError, TileOutOfRangeError
from gis.imagery import attribution as attr
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
    decode_rgb,
)
from gis.imagery.http import HttpConfig, fetch_bytes, post_json
from gis.imagery.ratelimit import get_limiter
from gis.types import BasemapKind

__all__ = ["GoogleMapTilesProvider"]

_log = logging.getLogger("gis.imagery.providers.google_map_tiles")

_SESSION_URL: Final[str] = "https://tile.googleapis.com/v1/createSession"
_TILE_URL: Final[str] = "https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}"

_GOOGLE_GEOREF_CE90_M: Final[float] = 5.0
"""★ AN ESTIMATE, and the SAME estimate ``google_static`` uses — it is the same imagery
behind both endpoints, so claiming a different accuracy for one of them would be a
fabrication. Google publishes no georegistration accuracy for its satellite basemap.
Conservative and deliberately not flattering — it propagates into ``total_ce90_m``."""

_SESSION_SAFETY_MARGIN_S: Final[float] = 300.0
"""Renew a session this long before Google's stated expiry. ★ A token that expires
mid-viewport turns every in-flight tile into a 403, which the user reads as "the map
broke". Five minutes costs one extra handshake a fortnight and removes that failure."""


def _bool_env(env: dict[str, str] | os._Environ[str], name: str, default: bool) -> bool:
    """Parse a boolean environment variable. ★ Mirrors ``google_static`` exactly."""
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class GoogleMapTilesProvider(TileProviderMixin, ImageryProvider):
    """Google Map Tiles API satellite imagery. ★ Off by default, behind a double opt-in.

    Args:
        config: Shared imagery settings.
        api_key: Overrides ``LE_GOOGLE_MAPS_STATIC_KEY``. For tests.
        tos_acknowledged: Overrides ``LE_GOOGLE_TOS_ACKNOWLEDGED``. For tests.
        clock: Monotonic seconds source, for testing session expiry.
    """

    def __init__(
        self,
        config: GisConfig | None = None,
        *,
        api_key: str | None = None,
        tos_acknowledged: bool | None = None,
        clock: Any = None,
    ) -> None:
        """Construct the provider. ★ NEVER raises, NEVER fetches.

        Constructing this provider is NOT enabling it, and in particular does NOT open a
        session — the registry constructs every provider merely to ask whether it is
        configured, and a handshake there would bill the operator for a question.
        """
        import time  # noqa: PLC0415

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
        self._http = HttpConfig(
            user_agent=cfg.imagery.user_agent,
            timeout_seconds=cfg.imagery.request_timeout_seconds,
            max_retries=cfg.imagery.max_retries,
        )
        self._max_concurrent_fetches = cfg.imagery.max_concurrent_fetches
        self._max_tiles_per_chip = 64
        self._warned = False
        self._clock = clock or time.monotonic
        # ★ Session state is guarded: Celery's worker pool calls get_tile concurrently,
        #   and an unguarded refresh would open one session per in-flight tile — billable,
        #   and each one invalidating the last.
        self._session_lock = threading.Lock()
        self._sessions: dict[BasemapKind, tuple[str, float]] = {}

    # ---- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "google_map_tiles"

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        return 22

    @property
    def attribution(self) -> str:
        """★ Rendered ONCE by ``ProviderAttribution``, non-dismissible.

        Unlike the Static API this endpoint does not burn credits into the pixels, so this
        string is the ONLY place the obligation is met. It is therefore not decorative:
        suppressing it would put the deployment in breach.
        """
        return attr.attribution_for(self.name)

    @property
    def terms_url(self) -> str:
        return attr.terms_url_for(self.name)

    # ---- readiness ---------------------------------------------------------

    def is_configured(self) -> bool:
        """★ THE DOUBLE OPT-IN. Requires a key AND an explicit ToS acknowledgement.

        PURE LOCAL CHECK — never opens a session, never raises. Whether the *Map Tiles
        API* is enabled on the key is NOT knowable without a network call, so it is
        deliberately not asserted here; that failure surfaces at first tile with Google's
        own message attached.
        """
        return bool(self._key) and self._tos_acknowledged

    def configuration_reason(self) -> str | None:
        if not self._key and not self._tos_acknowledged:
            return "requires BOTH LE_GOOGLE_MAPS_STATIC_KEY and LE_GOOGLE_TOS_ACKNOWLEDGED=true"
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
        """★ The two False flags below are the enforcement mechanism, not documentation.

        They are copied from ``google_static`` rather than relaxed: a different endpoint
        against the same contract does not earn different licence terms.
        """
        return ProviderCapabilities(
            supports_tiles=True,
            # ★ False, unlike google_static. There is no native bbox endpoint here; the
            #   mixin stitches tiles instead. Claiming True would promise a single-request
            #   path that does not exist.
            supports_static_bbox=False,
            supports_offline=False,
            native_crs="EPSG:3857",
            tile_size_px=256,
            typical_gsd_m=0.3,
            georef_ce90_m=_GOOGLE_GEOREF_CE90_M,
            imagery_date_known=False,
            rate_limit_rps=10.0,
            requires_attribution=True,
            # ★★ FROM THE ToS. False makes DiskTileCache and RedisTileCache REFUSE the
            #    write and hard-fall to an in-process LRU.
            allows_caching=False,
            # ★★ FROM THE ToS. False makes ExportContext.chip = None, so the PDF omits the
            #    map figure and says so in ExportBundle.warnings. Coordinates still
            #    export; the pixels do not travel into a deliverable.
            allows_derivative_export=False,
            max_static_px=None,
            kinds=(BasemapKind.SATELLITE, BasemapKind.HYBRID),
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

    def _session_token(self, kind: BasemapKind, key: str) -> str:
        """Return a live session token for ``kind``, opening or renewing one if needed.

        ★ Tokens are per basemap kind: a session is bound to the ``mapType`` and
        ``layerTypes`` it was created with, so reusing a satellite token for hybrid
        silently returns satellite tiles. Keying the cache by kind makes that
        unrepresentable rather than merely discouraged.

        Raises:
            ProviderNotConfiguredError: Google rejected the credential, or the Map Tiles
                API is not enabled on this key.
        """
        with self._session_lock:
            cached = self._sessions.get(kind)
            if cached is not None and self._clock() < cached[1]:
                return cached[0]

            body: dict[str, Any] = {
                "mapType": "satellite",
                "language": "en-US",
                "region": "US",
            }
            if kind is BasemapKind.HYBRID:
                # Roads and labels over the imagery — Google's own composition, which is
                # what "use inside a Google Map" means here.
                body["layerTypes"] = ["layerRoadmap"]

            try:
                payload = post_json(
                    _SESSION_URL,
                    body,
                    provider=self.name,
                    config=self._http,
                    params={"key": key},
                )
            except ProviderNotConfiguredError as exc:
                # ★ A 403 HERE HAS ONE OVERWHELMINGLY LIKELY CAUSE, and the generic
                #   "check your key" text sends the operator to re-verify a key that is
                #   fine. The key is shared with google_maps_static; if that provider
                #   works, the key is valid and the Map Tiles API simply is not enabled
                #   on it. Say that, with the two console steps, rather than making them
                #   rediscover it.
                raise ProviderNotConfiguredError(
                    f"{self.name}: Google rejected the session request ({exc}). The key "
                    "itself is probably fine - it is the same key google_maps_static "
                    "uses. Two things must BOTH be true in the Google Cloud console: "
                    "(1) the Map Tiles API is ENABLED for the project, and (2) it is "
                    "listed in this key's API restrictions. Until then, select "
                    "'Google (Static API)' instead - same imagery, but Google burns a "
                    "credit strip into every tile.",
                    provider=self.name,
                ) from exc
            token = str(payload.get("session", "")).strip()
            if not token:
                raise ProviderNotConfiguredError(
                    f"{self.name}: createSession returned no session token. The Map Tiles "
                    "API is most likely not enabled on this key - enable it in the Google "
                    "Cloud console and add it to the key's API restrictions.",
                    provider=self.name,
                )

            # ★ `expiry` is a UNIX timestamp as a STRING, while our clock is monotonic —
            #   they are not comparable. Convert to a duration first. A malformed or
            #   missing expiry falls back to a short lease rather than an eternal one: a
            #   token we wrongly believe is valid forever fails every tile after it dies.
            ttl = _lease_seconds(payload)
            self._sessions[kind] = (token, self._clock() + ttl)
            return token

    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch a 256px slippy tile from the Map Tiles API.

        ★ A genuine z/x/y endpoint — no centre/zoom synthesis, and no credits burned into
        the pixels. Attribution travels through :attr:`attribution` instead.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: SATELLITE or HYBRID.

        Returns:
            ``(256, 256, 3)`` uint8 RGB, C-contiguous.

        Raises:
            TileOutOfRangeError: Out-of-range coordinates or an unsupported kind.
            ProviderNotConfiguredError: Missing key, missing ToS acknowledgement, or the
                Map Tiles API is not enabled on the key.
        """
        self._check_tile_range(z, x, y, kind)
        key = self._require_config()
        self._warn_once()
        session = self._session_token(kind, key)

        get_limiter(self.name).acquire()
        data, _mime = fetch_bytes(
            _TILE_URL.format(z=z, x=x, y=y),
            provider=self.name,
            config=self._http,
            params={"session": session, "key": key},
        )
        return decode_rgb(data, provider=self.name, expect_size=256)

    def _check_tile_range(self, z: int, x: int, y: int, kind: BasemapKind) -> None:
        """Validate the tile address and kind before spending a request.

        ★ Overrides the mixin only to widen the accepted kinds to HYBRID; the range
        arithmetic is delegated so the two cannot diverge.
        """
        if kind not in self.capabilities().kinds:
            raise TileOutOfRangeError(
                f"{self.name} serves {', '.join(k.value for k in self.capabilities().kinds)}, "
                f"not {kind.value}",
                provider=self.name,
            )
        super()._check_tile_range(z, x, y, BasemapKind.SATELLITE)


def _lease_seconds(payload: Any) -> float:
    """Seconds until a returned session should be renewed.

    ★ Google returns ``expiry`` as a UNIX timestamp in a string. Converting it against
    wall-clock time and then comparing to a monotonic clock is a classic way to get a
    token that is either always expired or never expired, so the absolute instant is
    turned into a duration HERE, once, next to the parsing.
    """
    import time  # noqa: PLC0415

    raw = payload.get("expiry") if isinstance(payload, dict) else None
    try:
        remaining = float(str(raw)) - time.time()
    except (TypeError, ValueError):
        remaining = 0.0
    # A two-week lease is Google's documented norm; anything unparseable or already past
    # gets a conservative 15 minutes rather than being trusted.
    if remaining <= _SESSION_SAFETY_MARGIN_S:
        return 900.0
    return remaining - _SESSION_SAFETY_MARGIN_S
