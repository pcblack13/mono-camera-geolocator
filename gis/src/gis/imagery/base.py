"""``ImageryProvider`` — the interchangeable satellite imagery interface (§4.16).

★ **THIS IS THE LEGAL BOUNDARY OF THE PRODUCT.** The client's hard constraint concerns
Google's desktop globe application: its imagery cannot legally or technically be searched
or processed via that app or its API. LandExplorer honours that by construction — imagery
sits behind this interface, and swapping a provider must not change anything else in the
system. See ``gis.imagery``'s package docstring and ``docs/legal/imagery-terms.md`` for the
full statement of the constraint and its two independently disqualifying reasons.

★ **A grep-gate note, so nobody "improves" the prose here and reddens CI.** §10.5's boundary
gate greps this subtree, case-insensitively, for that application's name — and it pipes
``grep -n`` output (``path:lineno:content``) through the comment stripper, so a full-line
comment does NOT survive as an empty line and is NOT dropped. **Any line in ``gis/src/gis/``
naming both words trips the gate, comment or not.** The prose therefore never places them
together on one line. This is a real constraint of the gate as specified, not squeamishness.

Two rules that every implementor must obey, and that the parametrised contract test
enforces for every registered provider:

1. **``__init__`` never raises and never touches the network.** Construction ALWAYS
   succeeds; ``is_configured()`` reports readiness. A provider that throws in its
   constructor takes down the registry, the capabilities endpoint, and the UI that would
   have told you the key was missing.
2. **Optional dependencies bind at CALL time** (§11.3). ``gis/imagery/providers/__init__``
   imports every provider eagerly, so a module-scope ``import httpx`` makes the whole
   suite die at collection.
"""

from __future__ import annotations

import abc
import concurrent.futures
import io
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np

from gis.errors import AreaTooLargeError, TileNotAvailableError, TileOutOfRangeError
from gis.tiles import bbox_to_tile_range, crop_to_bbox, resolution_at, stitch_tiles
from gis.types import BasemapKind, BBox, GeoTransform, SatelliteChip, TileRange, TileRef

__all__ = [
    "PROVIDER_NAMES",
    "ImageryProvider",
    "ProviderCapabilities",
    "ProviderHealth",
    "TileProviderMixin",
    "composite_over",
    "decode_rgb",
    "decode_rgba",
]

_log = logging.getLogger("gis.imagery.base")


PROVIDER_NAMES: Final[tuple[str, ...]] = (
    "esri_world_imagery",
    "local_orthophoto",
    "fixture",
    "mapbox_satellite",
    "bing_aerial",
    "sentinel_copernicus",
    "google_maps_static",
    "google_map_tiles",
)
"""★ THE CANONICAL PROVIDER NAME TUPLE, owned by the layer that owns providers.

``gis`` may not import sqlalchemy (§10.2, and the ``gis-purity`` import-linter contract),
so ``gis`` cannot see the ``imagery_provider`` PG enum that these names must match.
Therefore: **gis tests against THIS tuple**, and a BACKEND test asserts
``set(PROVIDER_NAMES) == {e.value for e in models.enums.ImageryProvider}``. The backend may
import gis; gis may not import the backend. The dependency points the way it already
points.

★ Note what is absent, and always will be: the excluded desktop globe application has no
member here and none in the PG enum — **unrepresentable in the type system**, so the
database itself cannot store a row claiming it as a source. An absence, not a disabled flag.
"""


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can do, declared without touching the network.

    ★ ``allows_caching`` and ``allows_derivative_export`` are read from the provider's
    TERMS, never from convenience. They are the mechanism by which a licence obligation is
    enforced structurally: a restrictive provider cannot accidentally accumulate a
    permanent on-disk copy or leak pixels into a client deliverable, because the cache and
    the export writers gate on these flags. Violating the terms requires editing
    capability code, not merely forgetting a rule.
    """

    supports_tiles: bool
    """``get_tile()`` is meaningful."""
    supports_static_bbox: bool
    """``get_static_bbox()`` is native rather than stitched."""
    supports_offline: bool
    """Works with the NIC unplugged."""
    native_crs: str
    """★ Authority string of the geotransform this provider returns. ``EPSG:3857`` for
    every slippy provider; **PER-FILE (typically a UTM zone) for local_orthophoto**. IT IS
    NOT FIXED — ``match_results.sat_geotransform_srid`` exists because of that."""
    tile_size_px: int
    """256 or 512. ★ Read it; never hardcode it at a call site."""
    typical_gsd_m: float | None
    """Best-case ground sample distance at ``max_zoom``, metres."""
    georef_ce90_m: float
    """★ The provider's own ABSOLUTE georeferencing error, CE90 metres. MANDATORY: it
    flows into ``CandidateWindow`` -> ``PixelAccuracy`` -> ``GcpAccuracy.total_ce90_m``.
    A flattering number here becomes a false survey claim downstream."""
    imagery_date_known: bool
    """★ Gates whether ``SatelliteChip.captured_at`` is meaningful."""
    rate_limit_rps: float | None
    requires_attribution: bool
    allows_caching: bool
    """★ FROM THE ToS. False makes ``DiskTileCache``/``RedisTileCache`` REFUSE the write
    and fall back to in-process LRU with a warning."""
    allows_derivative_export: bool
    """★ FROM THE ToS. False makes ``ExportContext.chip = None``, so the PDF omits the map
    figure and records it in ``ExportBundle.warnings``. Coordinates still export; the
    pixels do not travel."""
    max_static_px: tuple[int, int] | None
    kinds: tuple[BasemapKind, ...] = (BasemapKind.SATELLITE,)
    """What the UI's BasemapSwitcher may offer.

    ★ MATCHING ALWAYS USES ``SATELLITE``, normatively — so this cannot touch the
    algorithm. Labels and hillshade are for human eyes only; feeding a label-burned tile to
    a matcher would be a genuine accuracy regression."""
    supports_multispectral: bool = False
    bands: tuple[str, ...] = ("R", "G", "B")
    native_max_zoom: int | None = None
    """★ Where NATIVE detail typically ends, as distinct from ``max_zoom`` (what the
    provider SERVES). Above this the provider overzooms — upsampled pixels that look
    sharp but carry no new information. None means unknown, which is an honest answer:
    the UI warns rather than pretending detail exists."""
    native_resolution_status: str = "unknown"
    """``"known"`` | ``"estimated"`` | ``"unknown"`` — how ``native_max_zoom`` was
    obtained. Never present an estimate as a vendor fact."""
    gsd_status: str = "estimated"
    """``"vendor_certified"`` | ``"estimated"`` | ``"unknown"`` — the epistemic status of
    ``typical_gsd_m``. It flows into GCP accuracy, so its provenance must travel with it."""
    accuracy_status: str = "estimated"
    """``"vendor_certified"`` | ``"estimated"`` | ``"unknown"`` — the epistemic status of
    ``georef_ce90_m``. Most web providers publish NO georegistration figure; ours are
    conservative estimates and must be labelled as such."""


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """The outcome of a cheap liveness probe."""

    name: str
    status: str
    """``"up"`` | ``"degraded"`` | ``"down"``."""
    configured: bool
    latency_ms: float | None
    message: str | None
    checked_at: float
    """Unix epoch seconds. ★ The imagery service caches this for 30 s; endpoint 51 serves
    the cache rather than making a per-request round trip."""


class ImageryProvider(abc.ABC):
    """One satellite imagery source, normalised to pixels + a geotransform.

    Contract for implementors:

    * ``__init__`` MUST NOT perform network I/O and MUST NOT raise on missing credentials.
      Construction ALWAYS succeeds; ``is_configured()`` reports readiness. (L11)
    * ``get_tile`` / ``get_static_bbox`` raise ``ProviderError`` subclasses, **never** bare
      httpx/rasterio/GDAL exceptions. The caller must not learn our stack.
    * All returned pixels are **RGB uint8**. No BGR, no alpha, no float.
    * Thread-safe: Celery calls these from a worker pool.
    """

    # ---- identity & static metadata (properties, NO I/O) --------------------

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable registry key. MUST be a member of ``PROVIDER_NAMES``."""

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool:
        """True iff this provider cannot serve without a credential."""

    @property
    @abc.abstractmethod
    def min_zoom(self) -> int:
        """Lowest zoom this provider serves."""

    @property
    @abc.abstractmethod
    def max_zoom(self) -> int:
        """Max zoom the provider SERVES.

        ★ NOT the max zoom with real detail — several providers overzoom. See
        ``capabilities().typical_gsd_m``.
        """

    @property
    @abc.abstractmethod
    def attribution(self) -> str:
        """Plain-text credit. MUST be rendered wherever pixels are shown."""

    @property
    @abc.abstractmethod
    def terms_url(self) -> str:
        """Canonical ToS URL. Surfaced in the UI and in PDF exports."""

    # ---- capability & readiness --------------------------------------------

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True iff this provider can serve RIGHT NOW (creds present, paths exist).

        ★ PURE LOCAL CHECK. No network. NEVER raises.
        """

    @abc.abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return this provider's capabilities. ★ Total. Never raises, never fetches."""

    def configuration_reason(self) -> str | None:
        """Why ``is_configured()`` is False, as a human sentence naming the fix.

        ★ §11.4 requires ``GET /imagery/providers`` to list an unconfigured provider with
        ``configured: false`` **and a reason**, and §11.3 requires every unconfigured
        component to *report its reason* rather than crash. CONTRACT.md §4.16 declares the
        ``is_configured() -> bool`` signature (``docs/guides/adding-a-provider.md`` sketches
        a ``tuple[bool, str | None]``; the contract wins on precedence), so the reason gets
        its own total method rather than a signature change that would ripple into every
        caller.

        Returns:
            None when configured. Otherwise a sentence naming the missing key or path.
        """
        return None if self.is_configured() else "not configured"

    # ---- cache policy (per-provider, overridable) ---------------------------

    @property
    def cache_ttl_seconds(self) -> int | None:
        """This provider's ToS-compliant positive-cache TTL, seconds.

        ★ None means "no provider-specific cap — use the operator's global
        ``LE_IMAGERY_TILE_CACHE_TTL_SECONDS``". A provider whose terms cap caching
        duration (Mapbox) overrides this, and the tile cache write path consults it —
        the global default is never *assumed* compliant for a capped provider.
        """
        return None

    @property
    def negative_cache_ttl_seconds(self) -> int:
        """How long "the provider has no imagery here" may be remembered, seconds.

        ★ Deliberately much shorter than the tile TTL: coverage gaps DO get filled, and a
        permanent negative would hide new imagery forever.
        """
        return 86_400

    def cache_variant(self, kind: BasemapKind = BasemapKind.SATELLITE) -> str:
        """The ``TileCacheKey.variant`` for this provider's current configuration.

        ★ THE KEY-ISOLATION HOOK. The variant must change whenever the *pixels* a given
        ``(z, x, y)`` resolves to would change: basemap kind, style id, ``@2x`` scale,
        format/quality, an orthophoto file hash. The default is the kind alone — right for
        providers with no configurable rendering. A provider with configurable rendering
        MUST override and fingerprint it, or a config change silently serves stale,
        incompatible cached tiles.
        """
        return kind.value

    # ---- imagery access ----------------------------------------------------

    @abc.abstractmethod
    def get_tile(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> np.ndarray:
        """Fetch a single tile, XYZ scheme (origin NW, ``y`` increasing south).

        ★ Decoding is the PROVIDER's job, so callers never branch on
        JPEG-vs-PNG-vs-WebP. The return type is ``np.ndarray``, never
        ``bytes | np.ndarray``: a union forces every call site to type-test and decode,
        which is exactly the provider-specific branching this ABC exists to remove.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: Which basemap rendering. MUST be in ``capabilities().kinds``. Providers
                that declare only SATELLITE may ignore it; matching never passes anything
                else.

        Returns:
            ``(S, S, 3)`` uint8 RGB, C-contiguous.

        Raises:
            TileOutOfRangeError: ``z`` outside ``[min_zoom, max_zoom]``, ``x``/``y``
                outside ``2**z``, or an unsupported ``kind``. A caller bug — NEVER retry.
            TileNotAvailableError: The provider has no imagery here (ocean, gap, cloud).
                A permanent answer — cache the negative.
            ProviderNotConfiguredError: No credential or path.
            ProviderRateLimitError: Retryable; carries ``retry_after``.
            ProviderTransportError: Retryable.
        """

    @abc.abstractmethod
    def get_static_bbox(
        self, bbox: BBox, zoom: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> SatelliteChip:
        """Fetch contiguous imagery covering ``bbox`` at ``zoom``, as one chip.

        ``TileProviderMixin`` supplies the stitching implementation. Providers with a
        native bbox endpoint (Google Static, local orthophotos) override and skip it.

        ★ The returned chip's geotransform is EXACT for the returned pixels — crop offsets
        are FOLDED INTO THE ORIGIN, never approximated.

        ★ Returns ``SatelliteChip``, not ``(ndarray, geotransform)``. A bare tuple lets
        pixels travel without their attribution, which is a licence condition. Making
        ``attribution`` a required field makes the obligation unforgeable.

        Args:
            bbox: EPSG:4326 target extent.
            zoom: Zoom level to fetch at.
            kind: Which basemap rendering.

        Returns:
            A ``SatelliteChip``.

        Raises:
            AreaTooLargeError: The request exceeds the tile/pixel budget.
            TileOutOfRangeError | TileNotAvailableError | ProviderNotConfiguredError |
            ProviderRateLimitError | ProviderTransportError: As ``get_tile``.
        """

    # ---- non-abstract shared behaviour -------------------------------------

    def get_tile_bytes(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> tuple[bytes, str]:
        """Return a raw encoded tile + its MIME type, for pass-through proxying.

        ★ ``kind`` IS LOAD-BEARING AND MUST BE FORWARDED BY EVERY OVERRIDE. It used to be
        absent from this signature while the caller threaded it all the way down from the
        HTTP route and used it to build the CACHE KEY — so a hybrid request was stored
        under a hybrid key holding satellite pixels, and the poisoned entry then served
        every later hybrid request. Silent, persistent, and invisible in every test that
        only ever asked for satellite. An override that hardcodes SATELLITE here
        reintroduces exactly that bug.

        ★ Exactly ONE legitimate caller: the tile proxy (endpoint 52). Two needs, two
        methods, no union.

        The default re-encodes ``get_tile()`` as PNG; network providers override to avoid
        the decode/encode round trip.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.

        Returns:
            ``(encoded_bytes, mime_type)``.

        Raises:
            ProviderError: As ``get_tile``.
        """
        from PIL import Image  # noqa: PLC0415 - keeps the ABC import-cheap

        array = self.get_tile(z, x, y, kind=kind)
        buffer = io.BytesIO()
        Image.fromarray(array, mode="RGB").save(buffer, format="PNG", optimize=False)
        return (buffer.getvalue(), "image/png")

    def tile_url(
        self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE
    ) -> str:
        """Return the resolved UPSTREAM tile URL.

        Network providers override. Used for cache keys, debugging, and — for keyless
        providers with ``LE_IMAGERY_DIRECT_TILE_URLS=true`` only — the frontend's
        direct-to-provider tile layer.

        Args:
            z: Zoom level.
            x: Tile column.
            y: Tile row.
            kind: Which basemap rendering.

        Returns:
            An absolute URL.

        Raises:
            NotImplementedError: For providers that have no upstream URL (local
                orthophotos, the fixture provider). ★ Deliberate: there is no honest URL
                to return, and inventing one would put a broken tile layer in the browser.
        """
        raise NotImplementedError(
            f"{self.name} has no upstream tile URL; it serves pixels, not links"
        )

    def health(self) -> ProviderHealth:
        """Probe liveness cheaply. ★ NEVER raises — returns a status.

        The default reports readiness without touching the network, which is the right
        answer for every offline provider and a safe one for the rest. Network providers
        may override to make one real call.

        ★ The result is CACHED for 30 s by ``imagery_service``; endpoint 51 serves the
        cache. It is not a per-request round trip.

        Returns:
            A ``ProviderHealth``.
        """
        configured = False
        message: str | None = None
        try:
            configured = self.is_configured()
            if not configured:
                message = self.configuration_reason()
        except Exception as exc:  # noqa: BLE001 - a health check that raises is not one
            return ProviderHealth(
                name=self.name,
                status="down",
                configured=False,
                latency_ms=None,
                message=f"is_configured() raised: {exc}",
                checked_at=time.time(),
            )
        return ProviderHealth(
            name=self.name,
            status="up" if configured else "down",
            configured=configured,
            latency_ms=None,
            message=message,
            checked_at=time.time(),
        )

    # ---- shared validation helpers -----------------------------------------

    def _check_tile_range(self, z: int, x: int, y: int, kind: BasemapKind) -> None:
        """Validate a tile request against this provider's declared limits.

        Raises:
            TileOutOfRangeError: ``z`` outside ``[min_zoom, max_zoom]``, ``x``/``y``
                outside ``2**z``, or ``kind`` not in ``capabilities().kinds``. ★ A caller
                bug, and NEVER retryable — which is exactly why it is a distinct type from
                ``TileNotAvailableError``.
        """
        if not (self.min_zoom <= z <= self.max_zoom):
            raise TileOutOfRangeError(
                f"zoom {z} outside [{self.min_zoom}, {self.max_zoom}]",
                provider=self.name,
            )
        limit = 1 << z
        if not (0 <= x < limit and 0 <= y < limit):
            raise TileOutOfRangeError(
                f"tile ({x}, {y}) outside [0, {limit}) at z={z}", provider=self.name
            )
        kinds = self.capabilities().kinds
        if kind not in kinds:
            raise TileOutOfRangeError(
                f"{self.name} does not serve kind={kind.value!r}; it serves "
                f"{[k.value for k in kinds]}",
                provider=self.name,
            )


# --- Shared pixel helpers ----------------------------------------------------
#
# ★ These live here, in the providers' shared base, rather than in a decode module of
#   their own: §2.3's tree lists no such module, and every one of the three callers is a
#   provider. Flagged in the PR description per §2's rule for files not in the tree.


def decode_rgb(data: bytes, *, provider: str, expect_size: int | None = None) -> np.ndarray:
    """Decode encoded tile bytes to ``(H, W, 3)`` uint8 RGB, C-contiguous.

    ★ Decoding is the PROVIDER's job (§4.16), which is what lets every caller ignore
    JPEG-vs-PNG-vs-WebP. This is the one implementation they all share, so the RGB / uint8
    / no-alpha / C-contiguous guarantees are made once instead of seven times.

    ★ RGB, never BGR. PIL is RGB-native, so nothing is swapped here — but the contract test
    asserts channel order, because a provider that hands OpenCV-flavoured BGR to a matcher
    produces plausible, confidently-wrong results rather than an error.

    Args:
        data: Encoded image bytes.
        provider: Registry key, for error attribution.
        expect_size: When set, the decoded tile must be exactly this square.

    Returns:
        ``(H, W, 3)`` uint8 RGB, C-contiguous.

    Raises:
        TileNotAvailableError: The bytes are empty. ★ A zero-length 200 is how some tile
            servers say "nothing here"; it is an absence, not a transport failure.
        ProviderTransportError: The bytes are not a decodable image, or the tile is the
            wrong size. ★ Never a bare PIL exception.
    """
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415 - PIL is a base dep

    from gis.errors import ProviderTransportError  # noqa: PLC0415 - avoids a top-level cycle

    if not data:
        raise TileNotAvailableError(
            f"{provider} returned an empty tile body", provider=provider
        )
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderTransportError(
            f"{provider} returned {len(data)} bytes that are not a decodable image: {exc}",
            provider=provider,
        ) from exc

    if array.ndim != 3 or array.shape[2] != 3:  # pragma: no cover - convert("RGB") ensures it
        raise ProviderTransportError(
            f"{provider} tile decoded to shape {array.shape}, expected (H, W, 3)",
            provider=provider,
        )
    if expect_size is not None and array.shape[:2] != (expect_size, expect_size):
        raise ProviderTransportError(
            f"{provider} returned a {array.shape[1]}x{array.shape[0]} tile, expected "
            f"{expect_size}x{expect_size}; the provider's tile_size_px capability is wrong "
            "or the endpoint changed",
            provider=provider,
        )
    return np.ascontiguousarray(array)


def decode_rgba(data: bytes, *, provider: str) -> np.ndarray:
    """Decode encoded bytes to ``(H, W, 4)`` uint8 RGBA, C-contiguous.

    For overlay layers only — labels and boundaries, whose transparency is the whole point.
    ★ Imagery never travels as RGBA past a provider's boundary; ``SatelliteChip.image`` is
    RGB by contract.

    Args:
        data: Encoded image bytes.
        provider: Registry key, for error attribution.

    Returns:
        ``(H, W, 4)`` uint8 RGBA, C-contiguous.

    Raises:
        TileNotAvailableError: The bytes are empty.
        ProviderTransportError: The bytes are not a decodable image.
    """
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

    from gis.errors import ProviderTransportError  # noqa: PLC0415

    if not data:
        raise TileNotAvailableError(
            f"{provider} returned an empty overlay body", provider=provider
        )
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderTransportError(
            f"{provider} returned an undecodable overlay: {exc}", provider=provider
        ) from exc
    return np.ascontiguousarray(array)


def composite_over(base_rgb: np.ndarray, overlay_rgba: np.ndarray) -> np.ndarray:
    """Alpha-composite an RGBA overlay over an RGB base. ★ Server-side ``kind=hybrid``.

    Standard source-over: ``out = overlay*a + base*(1-a)``, computed in float32 and rounded
    once. Compositing in uint8 would quantise every blend to the nearest 1/255 and leave
    visible banding along every label's antialiased edge.

    ★ Hybrid is for HUMAN EYES ONLY. Matching always uses ``kind=SATELLITE``, normatively:
    label glyphs are high-contrast corners that a feature matcher would happily lock onto,
    and they are not on the ground.

    Args:
        base_rgb: ``(H, W, 3)`` uint8.
        overlay_rgba: ``(H, W, 4)`` uint8. Resized to the base if it differs.

    Returns:
        ``(H, W, 3)`` uint8 RGB, C-contiguous.

    Raises:
        ValueError: If the shapes are not ``(H, W, 3)`` and ``(H, W, 4)``.
    """
    if base_rgb.ndim != 3 or base_rgb.shape[2] != 3:
        raise ValueError(f"base must be (H, W, 3), got {base_rgb.shape}")
    if overlay_rgba.ndim != 3 or overlay_rgba.shape[2] != 4:
        raise ValueError(f"overlay must be (H, W, 4), got {overlay_rgba.shape}")

    if overlay_rgba.shape[:2] != base_rgb.shape[:2]:
        from PIL import Image  # noqa: PLC0415

        resized = Image.fromarray(overlay_rgba, mode="RGBA").resize(
            (base_rgb.shape[1], base_rgb.shape[0]), Image.Resampling.BILINEAR
        )
        overlay_rgba = np.asarray(resized, dtype=np.uint8)

    alpha = (overlay_rgba[:, :, 3:4].astype(np.float32)) / 255.0
    out = overlay_rgba[:, :, :3].astype(np.float32) * alpha + base_rgb.astype(
        np.float32
    ) * (1.0 - alpha)
    return np.ascontiguousarray(np.clip(np.rint(out), 0, 255).astype(np.uint8))


class TileProviderMixin:
    """``get_static_bbox()`` for providers that only speak tiles.

    Mix in **before** ``ImageryProvider``::

        class AcmeProvider(TileProviderMixin, ImageryProvider): ...

    so that this implementation satisfies the ABC's abstract method. It enumerates the
    covering tiles, fetches them concurrently, stitches, crops to the bbox, and folds the
    crop offset into the geotransform's origin.

    ★ Missing tiles are FILLED, not fatal, and the fraction is reported on
    ``SatelliteChip.placeholder_fraction``. A single 404 over a coastline should not lose a
    whole chip — but a chip that is 60% black must say so, because a matcher will happily
    find "features" in a fill region and a surveyor will never see it.
    """

    _max_concurrent_fetches: int = 4
    _max_tiles_per_chip: int = 256

    def _fetch_tiles(
        self: ImageryProvider,
        refs: Iterable[TileRef],
        kind: BasemapKind,
        max_workers: int,
    ) -> tuple[dict[TileRef, np.ndarray], int]:
        """Fetch tiles concurrently, tolerating legitimate absences.

        Returns:
            ``(tiles, missing_count)``. ``TileNotAvailableError`` counts as missing;
            every other ``ProviderError`` propagates — a rate limit or a transport failure
            is not a hole in the imagery, it is a failure to fetch, and silently filling it
            black would hand a matcher a fabricated scene.
        """
        refs = list(refs)
        if not refs:
            return ({}, 0)

        tiles: dict[TileRef, np.ndarray] = {}
        missing = 0
        workers = max(1, min(max_workers, len(refs)))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix=f"tiles-{self.name}"
        ) as pool:
            futures = {
                pool.submit(self.get_tile, ref.z, ref.x, ref.y, kind=kind): ref
                for ref in refs
            }
            for future in concurrent.futures.as_completed(futures):
                ref = futures[future]
                try:
                    tiles[ref] = future.result()
                except TileNotAvailableError:
                    missing += 1
                    _log.debug("%s: no imagery at %s", self.name, ref)
        return (tiles, missing)

    def _check_budget(self: ImageryProvider, rng: TileRange, tile_size: int) -> None:
        """Guard the tile and pixel budget for one chip.

        Raises:
            AreaTooLargeError: The covering rectangle exceeds the chip budget. ★ Endpoint
                53 is a request, not a job: a 64-megapixel stitch inside a GET is the
                workload L5 forbids.
        """
        count = len(rng)
        limit = getattr(self, "_max_tiles_per_chip", 256)
        if count > limit:
            raise AreaTooLargeError(
                f"bbox needs {count} tiles at z={rng.z} ({rng.cols}x{rng.rows}), over the "
                f"{limit}-tile chip budget; request a smaller bbox or a lower zoom",
                provider=self.name,
            )
        max_static = self.capabilities().max_static_px
        if max_static is not None:
            width = rng.cols * tile_size
            height = rng.rows * tile_size
            if width > max_static[0] or height > max_static[1]:
                raise AreaTooLargeError(
                    f"stitched chip would be {width}x{height} px, over this provider's "
                    f"{max_static[0]}x{max_static[1]} limit",
                    provider=self.name,
                )

    def get_static_bbox(
        self: ImageryProvider,
        bbox: BBox,
        zoom: int,
        *,
        kind: BasemapKind = BasemapKind.SATELLITE,
    ) -> SatelliteChip:
        """Stitch tiles into one chip covering ``bbox``. See ``ImageryProvider``.

        ★ The geotransform is EXACT for the returned pixels: ``stitch_tiles`` computes the
        mosaic's origin from the NW tile's true corner, and ``crop_to_bbox`` folds the crop
        offset into the origin through the same affine. Nothing is approximated and nothing
        is dropped.

        Args:
            bbox: EPSG:4326 target extent. MUST NOT cross the antimeridian.
            zoom: Zoom level.
            kind: Which basemap rendering.

        Returns:
            A ``SatelliteChip`` in ``capabilities().native_crs`` (EPSG:3857 for slippy
            providers).

        Raises:
            AreaTooLargeError | TileOutOfRangeError | ProviderError: As documented on the
                ABC.
            ValueError: If ``bbox`` crosses the antimeridian.
        """
        caps = self.capabilities()
        if kind not in caps.kinds:
            raise TileOutOfRangeError(
                f"{self.name} does not serve kind={kind.value!r}; it serves "
                f"{[k.value for k in caps.kinds]}",
                provider=self.name,
            )
        if not (self.min_zoom <= zoom <= self.max_zoom):
            raise TileOutOfRangeError(
                f"zoom {zoom} outside [{self.min_zoom}, {self.max_zoom}]",
                provider=self.name,
            )

        tile_size = caps.tile_size_px
        rng = bbox_to_tile_range(bbox, zoom)
        self._check_budget(rng, tile_size)

        refs = list(rng)
        tiles, missing = self._fetch_tiles(
            refs, kind, getattr(self, "_max_concurrent_fetches", 4)
        )
        if not tiles:
            raise TileNotAvailableError(
                f"{self.name} has no imagery for {bbox} at z={zoom} "
                f"({len(refs)} tiles requested, none returned)",
                provider=self.name,
            )

        mosaic, mosaic_gt = stitch_tiles(tiles, rng, tile_size)
        image, gt = crop_to_bbox(mosaic, mosaic_gt, bbox, crs=caps.native_crs)

        # ★ The placeholder fraction is measured over the CROPPED chip, not the mosaic:
        #   the caller's quality signal must describe the pixels it was handed. Tiles the
        #   crop discarded never mattered.
        placeholder_fraction = _cropped_placeholder_fraction(
            rng, tiles, tile_size, mosaic_gt, gt, image.shape[1], image.shape[0]
        )

        centre_lon, centre_lat = bbox.center()
        return SatelliteChip(
            image=image,
            geotransform=gt,
            crs=caps.native_crs,
            provider_name=self.name,
            attribution=self.attribution,
            terms_url=self.terms_url,
            zoom=zoom,
            captured_at=self._captured_at(bbox, zoom) if caps.imagery_date_known else None,
            # ★ TRUE ground metres per pixel at the chip's centre, cos(phi)-corrected.
            #   NOT gt[1] — that is a Web Mercator metre, which is inflated by 1/cos(phi)
            #   and is ~1.41x too large at 45 degrees. This is the whole reason gsd_m is a
            #   field rather than something callers derive from the geotransform.
            gsd_m=resolution_at(zoom, centre_lat, tile_size),
            georef_ce90_m=caps.georef_ce90_m,
            is_authoritative=False,
            kind=kind,
            placeholder_fraction=placeholder_fraction,
            bands=caps.bands,
            extra_bands=None,
        )

    def _captured_at(self: ImageryProvider, bbox: BBox, zoom: int) -> datetime | None:
        """Return the imagery capture date, when the provider knows one.

        The default is None. Providers whose ``imagery_date_known`` is True override this.

        Args:
            bbox: The chip's extent.
            zoom: The chip's zoom.

        Returns:
            The capture timestamp, or None.
        """
        return None


def _cropped_placeholder_fraction(
    rng: TileRange,
    tiles: dict[TileRef, np.ndarray],
    tile_size: int,
    mosaic_gt: GeoTransform,
    crop_gt: GeoTransform,
    crop_w: int,
    crop_h: int,
) -> float:
    """Return the fraction of the CROPPED chip that came from tiles we never got.

    Computed geometrically from which tiles are missing, rather than by counting black
    pixels — black is a legitimate pixel value (deep water, shadow, burnt field), and
    counting it would report a night scene as 100% placeholder.

    Args:
        rng: The tile rectangle that was stitched.
        tiles: The tiles actually fetched.
        tile_size: Tile edge in pixels.
        mosaic_gt: The full mosaic's geotransform.
        crop_gt: The cropped chip's geotransform.
        crop_w: Cropped width in pixels.
        crop_h: Cropped height in pixels.

    Returns:
        A fraction in ``[0, 1]``.
    """
    if crop_w <= 0 or crop_h <= 0:
        return 0.0
    missing_refs = [ref for ref in rng if ref not in tiles]
    if not missing_refs:
        return 0.0

    # The crop's offset within the mosaic, in mosaic pixels. Both transforms are north-up
    # and share a pixel size (crop_to_bbox only moves the origin), so this is exact.
    pixel_w = mosaic_gt[1]
    pixel_h = mosaic_gt[5]
    if pixel_w == 0.0 or pixel_h == 0.0:  # pragma: no cover - stitch_tiles never emits this
        return 0.0
    col_off = int(round((crop_gt[0] - mosaic_gt[0]) / pixel_w))
    row_off = int(round((crop_gt[3] - mosaic_gt[3]) / pixel_h))

    missing_px = 0
    for ref in missing_refs:
        tile_col0 = (ref.x - rng.min_x) * tile_size
        tile_row0 = (ref.y - rng.min_y) * tile_size
        overlap_w = min(tile_col0 + tile_size, col_off + crop_w) - max(tile_col0, col_off)
        overlap_h = min(tile_row0 + tile_size, row_off + crop_h) - max(tile_row0, row_off)
        if overlap_w > 0 and overlap_h > 0:
            missing_px += overlap_w * overlap_h
    return min(1.0, missing_px / float(crop_w * crop_h))
