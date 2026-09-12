# 40 — Imagery & GIS Layer

**Owner:** Remote Sensing Specialist / GIS Engineer
**Status:** Design (no implementation code in this document)
**Scope:** `backend/app/gis/**`, `backend/app/imagery/**`, the provider abstraction, tile math, projections, GeoTIFF handling, and all export writers.

---

## 0. Executive summary

The matching pipeline (see `50-matching.md`) consumes **one pixel-addressable image plus one affine geotransform**. That is the entire contract. Everything in this document exists to produce that pair from six wildly different sources — a keyless Esri tile endpoint, a keyed Mapbox endpoint, Bing's quadkey scheme, a 10 m Sentinel-2 scene, a restricted Google endpoint, or a GeoTIFF sitting on local disk — without the matcher ever learning which one it got.

Three commitments govern this layer:

1. **Zero-config default.** `IMAGERY_PROVIDER` defaults to `esri`, which needs no API key. `docker compose up` yields a working satellite search with no `.env` edits. Keyed providers are strictly opt-in.
2. **No Google Earth ingestion.** Google Earth imagery is not scraped, tiled, cached, or searched. §3 states the posture in full. The provider seam is what makes honoring this constraint an architectural property rather than a promise.
3. **Provider swap is algorithmically inert.** Changing `IMAGERY_PROVIDER` from `esri` to `local_ortho` changes resolution, licence, and accuracy — it changes **no line** of the matching code, because the matcher's input type is `SatelliteChip`, not a provider.

### 0.1 The dev-machine reality that shapes this design

Verified on the target machine (2026-07-17):

| Library | Status |
|---|---|
| opencv 4.13, numpy 2.4, torch 2.11+cu130, scipy 1.17, PIL | installed |
| **GDAL/osgeo 3.8.4** | **installed** |
| rasterio, geopandas, shapely, pyproj, fiona, reportlab | **NOT installed** |

This has a non-obvious consequence that the rest of this document is built around.

`LocalOrthophotoProvider` is specified as reading GeoTIFFs "via rasterio". But **rasterio is not installed and GDAL is**. If the local provider hard-imports rasterio, the single highest-accuracy, fully-offline provider — the one a real surveyor would actually use — is dead on the only machine we can currently test on. That contradicts the "works end-to-end out of the box" mandate as directly as a missing model weight would.

So the same graceful-degradation discipline the deep-model plugins get is applied to raster I/O:

- **`gis/rasterio_shim.py`** exposes a small raster-read surface (`open_raster`, `windowed_read`, `dataset_crs`, `dataset_transform`, `overview_levels`, `nodata_mask`). It binds to **rasterio when importable**, otherwise to **`osgeo.gdal`**, otherwise raises a typed `RasterBackendUnavailable` at *call* time, never at import time.
- **`gis/crs.py`** wraps pyproj identically, with a **GDAL `osr.CoordinateTransformation` fallback** and a pure-NumPy path for the 4326↔3857 special case (the only transform the hot path needs — closed-form, no library required).

The rule generalizes: **no module in `gis/` may raise ImportError at import time for an optional dependency.** Import failures become capability flags, surfaced at `/api/v1/system/capabilities` and degraded per-feature. A missing `fiona` disables Shapefile export and *only* Shapefile export — CSV, GeoJSON, and KML have zero third-party dependencies by deliberate design (§8).

### 0.2 The honesty ledger

Four things in this brief do not survive contact with reality unqualified. They are flagged here and argued in place, because a surveying product that overstates its accuracy or its legal footing is worse than one that ships late.

| Claim | Reality | Where |
|---|---|---|
| "Esri World Imagery is keyless, so it's the safe default" | Keyless ≠ unrestricted. Reachable without a key; the terms are *not* public domain. Correct default for **zero-config bootstrapping**; the operator must verify terms before production. | §3.2 |
| "Sentinel-2 is free imagery" | True, and mostly **unsuitable for GCP work**. 10 m/px floors GCP error at roughly ±10–20 m. A coarse locator, not a survey source. | §2.4 |
| "Search satellite imagery for the matching location" | Only *within a hinted region*. Hintless global search is ~10¹¹ tiles. **A location hint is a hard input requirement**, not a nice-to-have. | §5.4 |
| "Web Mercator is the tile CRS" | It is, and it is **not a survey CRS**. Metric work happens in UTM. Web Mercator scale error is ~1/cos(φ) — 41% at 55°N. | §6.3 |

---

## 1. The provider abstraction

### 1.1 Package layout

```
backend/app/imagery/
├── __init__.py
├── base.py                 # ImageryProvider ABC, ProviderCapabilities, SatelliteChip, TileRef
├── registry.py             # ProviderRegistry: config string -> provider instance
├── errors.py               # typed exception hierarchy
├── cache/
│   ├── __init__.py
│   ├── base.py             # TileCache ABC
│   ├── memory.py           # LRUTileCache — always available, default in tests
│   ├── disk.py             # DiskTileCache — content-addressed, default in dev
│   └── redis.py            # RedisTileCache — shared across Celery workers, default in prod
├── http.py                 # shared session, retry/backoff, rate limiter, User-Agent policy
├── ratelimit.py            # TokenBucket, per-provider budget enforcement
└── providers/
    ├── esri.py             # EsriWorldImageryProvider   (KEYLESS, DEFAULT)
    ├── mapbox.py           # MapboxSatelliteProvider    (key)
    ├── bing.py             # BingAerialProvider         (key, quadkey)
    ├── sentinel.py         # SentinelHubProvider        (account, 10m)
    ├── google.py           # GoogleStaticProvider       (key, RESTRICTED, never default)
    └── local_ortho.py      # LocalOrthophotoProvider    (offline, highest accuracy)
```

### 1.2 Value types (`imagery/base.py`)

```python
@dataclass(frozen=True, slots=True)
class TileRef:
    z: int
    x: int
    y: int

    def quadkey(self) -> str: ...
    def parent(self) -> "TileRef": ...
    def children(self) -> tuple["TileRef", "TileRef", "TileRef", "TileRef"]: ...


@dataclass(frozen=True, slots=True)
class BBox:
    """Always EPSG:4326, always (west, south, east, north), always degrees."""
    west: float
    south: float
    east: float
    north: float

    def center(self) -> tuple[float, float]: ...          # (lon, lat)
    def contains(self, lon: float, lat: float) -> bool: ...
    def buffered_m(self, meters: float) -> "BBox": ...
    def area_m2(self) -> float: ...                        # equal-area approx, for budget checks


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_tiles: bool               # get_tile() is meaningful
    supports_static_bbox: bool         # get_static_bbox() is native, not stitched
    supports_offline: bool             # works with the NIC unplugged
    native_crs: str                    # "EPSG:3857" for slippy; per-file for local ortho
    tile_size_px: int                  # 256 or 512
    typical_gsd_m: float | None        # best-case ground sample distance at max_zoom, metres
    imagery_date_known: bool           # can we report capture date per tile?
    rate_limit_rps: float | None
    requires_attribution: bool
    allows_caching: bool               # per provider terms — gates DiskTileCache/RedisTileCache
    allows_derivative_export: bool     # may a rendered chip go into a PDF deliverable?
    max_static_px: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class SatelliteChip:
    """The ONLY type the matcher sees. Provider identity is metadata, never control flow."""
    image: np.ndarray                  # HxWx3 uint8, RGB, C-contiguous
    geotransform: tuple[float, float, float, float, float, float]   # GDAL order
    crs: str                           # EPSG code of geotransform, e.g. "EPSG:3857"
    provider_name: str                 # provenance only
    attribution: str                   # MUST travel with the pixels — see §3.5
    zoom: int | None
    captured_at: datetime | None
    gsd_m: float                       # ground sample distance at chip centre
    is_authoritative: bool             # True => georeferencing is survey-grade (§7.4)
```

`geotransform` is the **GDAL 6-tuple** `(originX, pixelWidth, rowRotation, originY, colRotation, pixelHeight)` where `pixelHeight` is negative for north-up rasters. This is the interchange format for the whole system. Chosen over rasterio's `Affine` because GDAL is installed and rasterio is not (§0.1); `Affine` is derivable in one line where it's wanted.

`is_authoritative` is the hinge for §7.4. When a chip carries survey-grade georeferencing, downstream confidence scoring treats residuals as *measurement* error rather than *registration* error.

### 1.3 The ABC (`imagery/base.py`)

```python
class ImageryProvider(abc.ABC):
    """
    One satellite imagery source, normalized to pixels + geotransform.

    Contract for implementors:
      - __init__ MUST NOT perform network I/O or raise on missing credentials.
        Construction always succeeds; is_configured() reports readiness.
      - get_tile / get_static_bbox raise ProviderError subclasses, never bare
        requests/rasterio/GDAL exceptions. The matcher must not learn our stack.
      - All returned pixels are RGB uint8. No BGR, no alpha, no float.
      - Thread-safe: Celery calls these from a worker pool.
    """

    # ---- identity & static metadata (properties, no I/O) -------------------
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable registry key, lowercase snake_case. e.g. 'esri'."""

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool: ...

    @property
    @abc.abstractmethod
    def min_zoom(self) -> int: ...

    @property
    @abc.abstractmethod
    def max_zoom(self) -> int:
        """Max zoom the provider SERVES. Not the max zoom with real detail —
        several providers overzoom. See capabilities().typical_gsd_m."""

    @property
    @abc.abstractmethod
    def attribution(self) -> str:
        """Plain-text credit. MUST be rendered wherever pixels are shown (§3.5)."""

    @property
    @abc.abstractmethod
    def terms_url(self) -> str:
        """Canonical ToS URL. Surfaced in UI and PDF exports."""

    # ---- capability & readiness -------------------------------------------
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True if this provider can serve RIGHT NOW (creds present, paths exist).
        Pure local check. No network. Never raises."""

    @abc.abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    # ---- imagery access ----------------------------------------------------
    @abc.abstractmethod
    def get_tile(self, z: int, x: int, y: int) -> np.ndarray:
        """
        Single 256/512 px tile, XYZ scheme (origin NW, y increasing south).

        Returns HxWx3 uint8 RGB. Decoding is the provider's job so callers
        never branch on JPEG-vs-PNG-vs-WebP.

        Raises:
            TileOutOfRangeError    z outside [min_zoom, max_zoom], or x/y outside 2^z
            TileNotAvailableError  provider has no imagery here (ocean, gap, cloud)
            ProviderNotConfiguredError
            ProviderRateLimitError (retryable; carries retry_after)
            ProviderTransportError (retryable)
        """

    @abc.abstractmethod
    def get_static_bbox(
        self,
        bbox: BBox,
        zoom: int,
    ) -> SatelliteChip:
        """
        Contiguous imagery covering bbox at the given zoom, as one chip.

        Default implementation in TileProviderMixin: enumerate covering tiles,
        fetch concurrently, stitch, crop to bbox, compute geotransform (§4.6).
        Providers with a native bbox endpoint (Google Static, local ortho)
        override and skip stitching entirely.

        The returned chip's geotransform is EXACT for the returned pixels —
        crop offsets are folded into the origin, never approximated.

        Raises: as get_tile, plus
            AreaTooLargeError  requested px count exceeds provider/global budget
        """

    # ---- non-abstract shared behaviour ------------------------------------
    def tile_url(self, z: int, x: int, y: int) -> str:
        """Resolved URL for a tile. Network providers override; used for
        debugging, cache keys, and the frontend's direct-to-provider tile layer."""
        raise NotImplementedError

    def health(self) -> ProviderHealth:
        """Cheap liveness probe for /api/v1/system/providers. MAY do one
        network call. Never raises — returns a status object."""
```

**Signature note on `get_tile`.** The brief permits `bytes | np.ndarray`. The union is rejected: it forces every call site to type-test and decode, which is exactly the provider-specific branching the abstraction exists to eliminate, and it leaks image-format concerns into the matcher. The provider decodes; the return type is `np.ndarray`, always. Callers that genuinely need raw bytes — the frontend tile proxy, which should pass JPEG through without a decode/re-encode round trip — use a separate, explicit method:

```python
def get_tile_bytes(self, z: int, x: int, y: int) -> tuple[bytes, str]:
    """Raw encoded tile + MIME type, for pass-through proxying. Default impl
    re-encodes get_tile() as PNG; network providers override to avoid the
    decode/encode round trip."""
```

Two callers, two needs, two methods — instead of one method and a union that every caller must unpick.

**Signature note on `get_static_bbox`.** The brief says "stitched np.ndarray + geotransform". Returning `SatelliteChip` returns exactly that, plus the attribution and provenance that §3.5 makes mandatory. A bare tuple would let pixels escape without their required credit — the type system should make the legal obligation unforgeable, not leave it to reviewer diligence.

### 1.4 Errors (`imagery/errors.py`)

```python
class ProviderError(Exception):
    provider: str
    retryable: bool = False

class ProviderNotConfiguredError(ProviderError): ...      # missing key/path
class ProviderDisabledError(ProviderError): ...           # not in ALLOWED_PROVIDERS (§3.4)
class TileOutOfRangeError(ProviderError): ...             # caller bug — never retry
class TileNotAvailableError(ProviderError): ...           # legitimate 404 — cache the negative
class AreaTooLargeError(ProviderError): ...               # budget guard (§5.3)
class ProviderRateLimitError(ProviderError):
    retryable = True
    retry_after: float | None
class ProviderTransportError(ProviderError):
    retryable = True
class RasterBackendUnavailable(ProviderError): ...        # no rasterio AND no GDAL (§0.1)
```

`TileNotAvailableError` vs `ProviderTransportError` is the distinction that matters operationally: a 404 over open ocean is a **permanent** answer worth caching as a negative; a 503 is transient and must be retried with backoff. Collapsing them means either hammering a provider for tiles that will never exist, or permanently caching a blank tile because of one bad minute.

### 1.5 Tile cache (`imagery/cache/base.py`)

```python
class TileCache(abc.ABC):
    @abc.abstractmethod
    def get(self, key: TileCacheKey) -> bytes | None: ...

    @abc.abstractmethod
    def put(self, key: TileCacheKey, data: bytes, *, ttl_s: int | None = None) -> None: ...

    @abc.abstractmethod
    def get_many(self, keys: Sequence[TileCacheKey]) -> dict[TileCacheKey, bytes]:
        """Batch read. Stitching asks for 30-200 tiles at once; N round trips
        to Redis for one chip is the difference between 40ms and 2s."""

    @abc.abstractmethod
    def put_negative(self, key: TileCacheKey, *, ttl_s: int = 86_400) -> None:
        """Record 'provider has no tile here'. Prevents re-fetch storms over
        ocean/void. Distinct from absent."""

    @abc.abstractmethod
    def invalidate(self, prefix: TileCacheKeyPrefix) -> int: ...

    @abc.abstractmethod
    def stats(self) -> CacheStats: ...


@dataclass(frozen=True, slots=True)
class TileCacheKey:
    provider: str
    z: int
    x: int
    y: int
    variant: str = "default"     # "@2x", "l2a-2024-06", style id, ortho file hash

    def to_str(self) -> str:
        return f"tile:{self.provider}:{self.variant}:{self.z}:{self.x}:{self.y}"
```

`variant` prevents the single nastiest cache bug in this domain: a Sentinel L2A June composite and an October composite are the same `(z,x,y)` and utterly different pixels. Without `variant` in the key, a re-run silently matches against the wrong season's imagery and produces confidently wrong coordinates. Same for `@2x` retina tiles and Mapbox style ids.

**Caching is licence-gated, not merely a performance choice.** `DiskTileCache` and `RedisTileCache` consult `capabilities().allows_caching` and refuse to persist tiles from providers whose terms prohibit it, falling back to `LRUTileCache` (in-process, request-lifetime) with a `WARNING`. Several commercial providers permit only transient caching; some cap it (e.g. ~30 days). Encoding this in the cache layer means a provider with restrictive terms cannot accidentally have a permanent on-disk copy of its tiles built up by a background job.

Implementations:

| Impl | Backing | TTL | Default in | Notes |
|---|---|---|---|---|
| `LRUTileCache` | in-process dict + `OrderedDict` | none | tests | zero deps; bounded by count and bytes |
| `DiskTileCache` | `CACHE_DIR/{provider}/{variant}/{z}/{x}/{y}.{ext}` | mtime sweep | dev | content-addressed; safe across restarts |
| `RedisTileCache` | Redis binary values | `TILE_CACHE_TTL_S` (default 30d) | prod | shared by all Celery workers — the point |

The prod choice is Redis specifically because tile fetching happens **inside Celery workers**, and a disk cache in a container is per-replica. Four workers searching the same AOI would otherwise fetch every tile four times — quadrupling both latency and our rate-limit consumption against the provider.

### 1.6 Registry & factory (`imagery/registry.py`)

```python
class ProviderRegistry:
    def register(self, name: str, factory: Callable[[Settings], ImageryProvider]) -> None: ...
    def resolve(self, name: str, settings: Settings) -> ImageryProvider:
        """
        Config string -> ready provider instance. Cached per (name, settings-hash).

        Resolution order:
          1. name not registered            -> UnknownProviderError (fail loud: typo'd config)
          2. name not in ALLOWED_PROVIDERS  -> ProviderDisabledError (§3.4)
          3. build instance (never raises)
          4. not is_configured() and IMAGERY_STRICT -> ProviderNotConfiguredError
          5. not is_configured() and not strict     -> WARN + fall back to default_chain
        """
    def available(self, settings: Settings) -> list[ProviderInfo]:
        """Every registered provider + configured/allowed flags. Drives the UI
        picker and /api/v1/system/providers. Never raises."""
    def default_chain(self, settings: Settings) -> list[str]:
        """Ordered fallback. Default: ['local_ortho', 'esri'].
        local_ortho first — if the operator mounted orthophotos, they are
        definitionally better than any web tile source (§2.6). It self-skips
        via is_configured() when ORTHO_DIR is empty, so the zero-config machine
        lands on esri with no branching."""
```

Registration is explicit in `imagery/providers/__init__.py`, not entry-point autodiscovery. For a product whose central legal constraint is *which imagery sources are permitted*, a plugin mechanism that lets an unreviewed provider appear by being pip-installed is a liability. The set of providers is a reviewed, auditable list in version control.

**The fallback rule.** A missing API key degrades exactly like a missing model weight: log, fall back, keep serving. `IMAGERY_STRICT=true` inverts this for production, where silently serving 10 m Sentinel imagery when the operator paid for and expected 0.3 m Mapbox is a *worse* failure than a 503. Dev is forgiving; prod is loud. Fallback is never silent — every fallback emits a `WARNING` and sets `chip.provider_name` to what was actually used, so a downstream report can never misattribute imagery.

---

## 2. Concrete providers

### 2.1 Esri World Imagery — **KEYLESS, DEFAULT**

| | |
|---|---|
| Registry key | `esri` |
| Endpoint | `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |
| **Axis order** | **`{z}/{y}/{x}` — row before column.** Not `{z}/{x}/{y}`. |
| Auth | none |
| Tile size | 256 px, JPEG |
| Zoom | 0–19 global; 20–23 in selected metros |
| Best GSD | ~0.3 m in covered areas; ~1 m typical rural |
| Attribution | `Esri, Maxar, Earthstar Geographics, and the GIS User Community` |
| Terms | https://www.esri.com/en-us/legal/terms/full-master-agreement |
| Metadata | `.../World_Imagery/MapServer?f=pjson`; per-pixel date/source via the companion *World Imagery Metadata* layer |

The `{z}/{y}/{x}` ordering is the single most common integration bug against this endpoint, because it is visually one character from the near-universal `{z}/{x}/{y}` and produces *plausible imagery of the wrong place* rather than a 404. `EsriWorldImageryProvider.tile_url()` is the only place the ordering is expressed, and it carries a unit test asserting a known `(z,x,y)` resolves to a known URL.

**Rate limits.** No published per-key limit (there is no key). This is not permission for unlimited traffic. Self-imposed: `rate_limit_rps = 8.0`, `max_concurrency = 4`, with a descriptive `User-Agent` (`LandExplorer/{version} (+{CONTACT_URL})`) so Esri can identify and contact us. Silent aggressive scraping from an anonymous UA is how a keyless endpoint stops being keyless for everyone.

**Why default (honestly).** Because it is the only high-resolution source that produces a working app with **zero configuration**, which the brief mandates. That is a *bootstrapping* argument, not a licensing one.

> **Keyless is not licence-free.** Esri World Imagery is not public domain. The tile endpoint is reachable without authentication, and the basemap is broadly used, but access is governed by Esri's terms and by the terms of upstream vendors (Maxar and others) whose imagery it aggregates. Reachable ≠ licensed for your use. Commercial redistribution, bulk caching, and use as a source for derived survey deliverables are exactly the uses most likely to exceed what's permitted — and "derived survey deliverable" is precisely what LandExplorer produces.
>
> **Default = zero-config bootstrap. It is not a determination that your production use is licensed.** An operator delivering paid survey products must read the terms, and will likely need either an ArcGIS subscription with appropriate rights, or a different provider. For real surveying, §2.6 (`local_ortho`) is the correct answer on both accuracy and licence grounds. This is stated in `README.md`, at first run in the log banner, in the UI provider picker, and on every PDF export.

### 2.2 Mapbox Satellite — key

| | |
|---|---|
| Registry key | `mapbox` |
| Raster tiles | `https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}{@2x}.{format}?access_token={token}` |
| Styles API | `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/{tilesize}/{z}/{x}/{y}{@2x}?access_token={token}` |
| Auth | `access_token` query param — `MAPBOX_ACCESS_TOKEN` |
| Tile size | 256 or 512 (`@2x` → 512/1024) |
| Zoom | 0–22 served; native detail typically to ~18–19, overzoom above |
| Best GSD | ~0.3–0.5 m urban; coarser rural |
| Attribution | `© Mapbox © Maxar` + link to https://www.mapbox.com/about/maps/ |
| Terms | https://www.mapbox.com/legal/tos |
| Pricing | free monthly tile-request allowance, then metered per 1k requests |
| Caching | permitted only within the limits in the ToS (temporary/duration-capped) |

`format` ∈ {`jpg70`, `jpg80`, `jpg90`, `png`, `webp`}. Default `jpg90` — JPEG artifacts at lower quality are a real matcher hazard: block-boundary ringing manufactures spurious SIFT keypoints along an 8×8 grid, and those false features are *spatially regular*, which is worse than noise because RANSAC can lock onto the grid itself.

`use_2x = True` by default. A 512 px `@2x` tile is one request covering the same ground as a 256 px tile at 4× the pixels — it bills as one request while roughly doubling linear resolution. Strictly better economics for feature matching, where keypoint density is the currency.

`capabilities().allows_caching = True` **but** `RedisTileCache` TTL is clamped to `MAPBOX_CACHE_TTL_S` (default 30 days) rather than the global 30-day default being assumed compliant. The clamp is explicit and configurable because the permitted duration is a term the operator must confirm.

### 2.3 Bing Maps Aerial — key, quadkey

| | |
|---|---|
| Registry key | `bing` |
| **Metadata (required first call)** | `https://dev.virtualearth.net/REST/v1/Imagery/Metadata/Aerial?output=json&include=ImageryProviders&key={key}` |
| Tile template | returned by metadata, e.g. `https://ecn.t{subdomain}.tiles.virtualearth.net/tiles/a{quadkey}.jpeg?g={g}&n=z` |
| Auth | `BING_MAPS_KEY` |
| Tile size | 256 px JPEG |
| Zoom | 1–19 global (21 in places). **Note z starts at 1**, not 0 |
| Best GSD | ~0.3 m urban |
| Attribution | `© {year} Microsoft Corporation` + the per-region `ImageryProviders` strings from metadata |
| Terms | https://www.microsoft.com/maps/product/terms.html |

**Bing must not be integrated by hardcoding the tile URL.** The ToS requires resolving the template via the Metadata API; the `{subdomain}` list and `g=` version change, and — importantly — the `ImageryProviders` block returns **per-bbox, per-zoom attribution strings** that are legally required to be displayed for the specific area being viewed. Hardcoding the URL both violates the terms and produces wrong attribution. `BingAerialProvider` fetches metadata once at first use, caches it (24 h TTL), and derives attribution per request from the `coverageAreas` bboxes and zoom ranges.

**Quadkey algorithm.** Bing interleaves the `(x, y)` bits of a slippy tile into a base-4 string of length `z`. Each character encodes one zoom level's quadrant: `0`=NW, `1`=NE, `2`=SW, `3`=SE.

```python
def tile_to_quadkey(z: int, x: int, y: int) -> str:
    """
    XYZ tile -> Bing quadkey.

    For i from z down to 1:
        digit = 0
        mask  = 1 << (i - 1)
        if x & mask: digit += 1     # east  -> +1
        if y & mask: digit += 2     # south -> +2
        append str(digit)

    Length of result == z. Purely bit manipulation; no floats, exactly invertible.

    tile_to_quadkey(1, 0, 0) == "0"
    tile_to_quadkey(1, 1, 1) == "3"
    tile_to_quadkey(3, 3, 5) == "213"
    """

def quadkey_to_tile(quadkey: str) -> TileRef:
    """
    Inverse. z = len(quadkey). For each char at level i = z - index:
        mask = 1 << (i - 1)
        '0': neither bit   '1': x |= mask
        '2': y |= mask     '3': x |= mask; y |= mask
        anything else -> ValueError
    """
```

Both live in `gis/tiles.py`, not in `providers/bing.py` — the quadkey scheme is tile math, not a Bing implementation detail, and it is round-trip property-tested (`quadkey_to_tile(tile_to_quadkey(t)) == t` for random `t` across z ∈ [1, 22]).

### 2.4 Sentinel-2 / Copernicus — free, 10 m

| | |
|---|---|
| Registry key | `sentinel` |
| STAC catalogue | `https://catalogue.dataspace.copernicus.eu/stac` |
| OData | `https://catalogue.dataspace.copernicus.eu/odata/v1/Products` |
| WMTS (Sentinel Hub on CDSE) | `https://sh.dataspace.copernicus.eu/ogc/wmts/{instance_id}` |
| Alt. STAC (AWS Open Data) | `https://earth-search.aws.element84.com/v1` |
| Auth | free CDSE account; OAuth2 client credentials for Sentinel Hub APIs |
| Native GSD | **10 m** (B02/B03/B04/B08); 20 m and 60 m for other bands |
| Native zoom | ~z13–14 (z14 ≈ 9.55 m/px at equator) |
| Revisit | ~5 days (2-satellite constellation) |
| Attribution | `Contains modified Copernicus Sentinel data [year]` |
| Terms | https://dataspace.copernicus.eu/terms-and-conditions |
| Licence | free, full, open — genuinely permissive, incl. commercial use |

**Honest suitability assessment: Sentinel-2 is nearly useless for the core GCP task, and it is in the product anyway for reasons that are not GCP accuracy.**

The argument is arithmetic, not taste. A GCP's positional error cannot beat the imagery's ground sample distance. At 10 m/px, a landmark localized to a *perfect* ±1 px is ±10 m on the ground. Realistic sub-pixel matching at ±0.5 px still yields ~±5 m *before* homography residual, provider georegistration error (Sentinel-2 L1C/L2A geolocation is specified at roughly 10–12 m at 95% confidence), and terrain effects. Compounded, expect **±10–20 m**.

For agricultural GCP work that is a category error:

- A field boundary corner, a gate post, an irrigation valve, a pivot centre — the actual GCP targets — are 0.3–3 m objects. At 10 m/px they occupy **less than one pixel**. There is nothing to match.
- Ground-photo↔satellite matching needs corresponding *texture*. At 10 m/px, a 100 m field is 10×10 px. SIFT will not find stable, distinctive keypoints in a 10×10 px near-uniform patch — and the ones it does find will be dominated by the field's spectral response, which changes with crop phenology week to week.
- Survey-grade GCPs are typically specified at centimetre-to-decimetre accuracy. We would be off by **2–3 orders of magnitude**.

It ships because it earns its place at three *other* jobs:

1. **Coarse-to-fine anchor (§5.2).** z13–14 is exactly the coarse stage. Sentinel narrows a 5 km radius to a ~500 m candidate before a keyed provider is asked for a single high-zoom tile — cutting paid tile requests by ~1–2 orders of magnitude.
2. **The only fully-open commercial-safe web source.** When licensing forbids Esri/Mapbox/Bing for a deliverable and no orthophotos exist, Sentinel is the legally unambiguous fallback. Coarse and legal beats sharp and prohibited.
3. **Temporal context.** ~5-day revisit and NIR gives NDVI-style crop-state layers over the AOI — genuinely valuable *agricultural* context, sitting beside the GCP result rather than producing it.

`SentinelHubProvider.capabilities()` reports `typical_gsd_m = 10.0`, and the API refuses `zoom > 15` with `TileOutOfRangeError` rather than serving upsampled mush that *looks* like detail. **The provider must not manufacture the appearance of resolution it does not have** — an interpolated z18 Sentinel tile is a lie that a matcher will confidently act on. The UI shows a persistent accuracy warning whenever `sentinel` is the active provider for a GCP job, and every export carries `gsd_m = 10.0` with an explicit accuracy caveat in the PDF (§8.6).

`variant` encodes the mosaic window (e.g. `l2a-2024-06-median`) so seasonal composites never collide in cache (§1.5).

### 2.5 Google Maps Static / tiles — **RESTRICTED, NEVER DEFAULT**

| | |
|---|---|
| Registry key | `google_static` |
| Static Maps | `https://maps.googleapis.com/maps/api/staticmap?center={lat},{lon}&zoom={z}&size={w}x{h}&scale={1,2}&maptype=satellite&format=png&key={key}` |
| Map Tiles API | session token via `https://tile.googleapis.com/v1/createSession`, then `https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}?session={token}&key={key}` |
| Auth | `GOOGLE_MAPS_API_KEY` (+ `GOOGLE_TOS_ACKNOWLEDGED=true`, see below) |
| Max static size | 640×640 (`scale=2` → 1280×1280 delivered pixels) |
| Zoom | 0–21 (imagery-dependent) |
| Attribution | Google logo + `Map data ©{year} Google` — **as delivered, not restyled** |
| Terms | https://cloud.google.com/maps-platform/terms |
| Default? | **NO. Never. Not in any chain.** |

> ### ⚠️ Read before enabling
>
> Google Maps Platform terms place restrictions that sit **directly athwart what LandExplorer does**. In particular, terms of this kind commonly restrict: caching or persistent storage of imagery beyond narrow limits; creating derivative products from the imagery; using the content outside a Google Map; bulk/automated retrieval; and removing or obscuring Google attribution.
>
> Extracting GCPs from Google satellite imagery and exporting them as a Shapefile deliverable is **plausibly all of: derivative creation, use outside a Google Map, and prohibited caching — simultaneously.**
>
> **This provider exists for the narrow case where the operator has their own agreement with Google that permits their specific use. It is not a general-purpose option, and enabling it because it "looks sharper" is very likely a terms violation.** Verify against your own contract, or don't enable it.
>
> **This is not legal advice.** Terms change; only the operator knows their agreement. The burden is the operator's, deliberately.

Enforcement is structural, not advisory:

- `google_static` is **absent from `default_chain()`** and cannot be reached by fallback. Only an explicit `IMAGERY_PROVIDER=google_static` selects it.
- `is_configured()` requires **both** `GOOGLE_MAPS_API_KEY` **and** `GOOGLE_TOS_ACKNOWLEDGED=true`. A key alone is insufficient. The second env var has no technical function — it exists to make enabling this an affirmative, auditable act by a human who read the paragraph above, rather than a side effect of having a key in the environment.
- `capabilities().allows_caching = False` → the cache layer (§1.5) **refuses to persist Google tiles to disk or Redis**, hard-falling to in-process LRU. Compliance is enforced by the cache, not by developer memory.
- `capabilities().allows_derivative_export = False` → the export layer (§8) **refuses to embed Google imagery in PDF map figures** and emits a provenance-only note. Coordinates still export; the *pixels* do not travel into a deliverable.
- First use logs a `WARNING` with the terms URL. The UI shows a non-dismissible banner.

This is what "the abstraction honors the legal constraint" means concretely: the restriction is expressed as capability flags that mechanically gate caching and export, so violating it requires editing capability code, not merely forgetting a rule.

### 2.6 LocalOrthophotoProvider — offline, highest accuracy

| | |
|---|---|
| Registry key | `local_ortho` |
| Source | `ORTHO_DIR` — directory of GeoTIFF / COG / `.vrt`, recursive |
| Auth | none — **fully offline** |
| GSD | whatever the file has: typically **0.02–0.25 m** (UAV/aerial) |
| Zoom | derived per-file from GSD (§4.4); `max_zoom` = f(finest file) |
| Attribution | `ORTHO_ATTRIBUTION` (operator-supplied), default `Local orthophoto` |
| Terms | operator's own imagery — operator's own rights |
| **`is_authoritative`** | **True** |

**This is the correct provider for real surveying, and the design should say so rather than treating it as an edge case.** It is the only provider that is simultaneously: high resolution (10–100× better GSD than any web source), legally unambiguous (the operator's own imagery), reproducible (bytes don't change under you when a vendor refreshes a basemap), offline (works in a field office with no connectivity — where surveyors actually are), and *known-accuracy* (the operator knows their own GCP-controlled orthomosaic's RMSE; nobody knows Esri's).

Every web provider is a compromise made because the operator doesn't have an orthophoto. `default_chain()` puts `local_ortho` first for exactly this reason (§1.6).

**Design:**

- **Startup index.** Walk `ORTHO_DIR`, read each file's CRS, bounds, GSD, and overview levels; reproject bounds to EPSG:4326; build an in-memory R-tree (`shapely.STRtree` when available, else a NumPy bbox scan — the fallback is fine, this indexes hundreds of files, not millions). Persist to `ortho_index` (§7.5) so workers don't re-walk. Watch with a periodic Celery beat re-index (`ORTHO_REINDEX_S`, default 300).
- **`is_configured()`** → `ORTHO_DIR` set, exists, and index is non-empty. This is what lets `local_ortho` sit first in the default chain harmlessly: on a machine with no orthophotos it self-skips, and the zero-config path lands on `esri` with no special-casing.
- **`get_static_bbox()`** — native, no stitching. Query index → candidate files → for each, `windowed_read` only the overlapping window at the overview level nearest the requested GSD (§7.1) → reproject into the requested chip grid → mosaic by priority (finest GSD wins; ties broken by newest `captured_at`). Returns `is_authoritative=True`.
- **`get_tile(z,x,y)`** — synthesized: compute the tile's 3857 bbox (§4.5), call `get_static_bbox`, resample to 256². Lets the frontend's Leaflet layer show local orthophotos through the *same* `/api/v1/tiles/{provider}/{z}/{x}/{y}` route as any web provider. The UX is identical; only the pixels are better.
- **Raster I/O goes through `gis/rasterio_shim.py`** (§0.1), so this provider works on the current dev machine — rasterio absent, GDAL 3.8 present.

### 2.7 Comparison table

| Provider | Best GSD | Native zoom | Cost | Licence posture | Offline | Key | Caching | **Suitability for agricultural GCP work** |
|---|---|---|---|---|---|---|---|---|
| **`local_ortho`** | **0.02–0.25 m** | per-file | operator's own | operator's own imagery — unambiguous | **✅ yes** | no | unrestricted | **★★★★★ The right answer.** Only survey-grade path. cm–dm accuracy, reproducible, legal, works in the field. Requires the operator to have orthophotos. |
| **`esri`** (default) | ~0.3 m urban, ~1 m rural | 0–19 (23 spots) | free to access | ⚠️ keyless ≠ unrestricted; Esri + upstream vendor terms; verify for commercial/derivative use | ❌ | **no** | verify | **★★★☆☆ Best zero-config option.** Good resolution, no setup. Licence must be verified before paid deliverables. Unknown per-tile georegistration error. |
| **`mapbox`** | ~0.3–0.5 m | 0–22 (native ~18–19) | free tier, then metered/1k | commercial use OK under ToS; caching duration-capped | ❌ | yes | limited TTL | **★★★★☆ Best keyed web option.** Sharp, reliable, clear terms, `@2x` economics. Costs money; rural detail varies; georegistration unstated. |
| **`bing`** | ~0.3 m urban | 1–19 (21 spots) | free tier w/ key | commercial needs appropriate licence; metadata-driven attribution mandatory | ❌ | yes | verify | **★★★☆☆ Solid alternative.** Comparable to Mapbox. Quadkey + mandatory metadata call add integration cost. Good when Bing coverage beats Mapbox locally. |
| **`sentinel`** | **10 m** | ~13–14 | **free** | **✅ fully open, incl. commercial** | ❌ (⚠️ cacheable offline) | account | unrestricted | **★☆☆☆☆ Not for GCP extraction.** 10 m/px ⇒ ±10–20 m. GCP targets are sub-pixel. **Valuable as coarse-search anchor, licence-safe fallback, and NDVI context — not as a GCP source.** |
| **`google_static`** | ~0.3 m | 0–21 | metered | **⚠️⚠️ Restrictive. Derivative export/caching likely prohibited. Verify your own agreement.** | ❌ | yes | **forbidden** | **☆☆☆☆☆ Do not enable without your own verified agreement.** Technically capable; the constraint is legal, not optical. Never default; pixels blocked from exports. |

**Reading the table:** the two columns that actually decide a real survey job are *GSD* and *Licence posture* — and they point the same direction. `local_ortho` wins both. Every other row is a compromise the operator makes because they don't have orthophotos yet. The default (`esri`) is chosen to satisfy *zero-config bootstrapping*, and the product should keep saying so rather than letting a convenient default masquerade as a recommendation.

---

## 3. Legal posture

> **This section is engineering documentation, not legal advice.** Terms change; jurisdictions differ; only the operator knows their own agreements. Where this document says "verify", it means *the operator must read the current terms and decide*, and the design deliberately refuses to make that decision for them.

### 3.1 Why Google Earth is not scraped

The client constraint: **Google Earth imagery cannot legally or technically be searched or processed via its application or API.** LandExplorer honors this without qualification.

**Legally.** Google Earth's terms prohibit the automated access, bulk download, and derivative use that this pipeline would require. Extracting features from Earth imagery to produce exported survey coordinates is a derivative use of licensed content, outside the permitted context. There is no configuration flag that enables it.

**Technically.** Google Earth is not a tile service with a stable public contract. It is a client application against undocumented internal endpoints with no versioning guarantee, no ToS permitting programmatic use, and active anti-automation. Even setting the licence aside, an integration built on it would be unstable by construction — one that breaks silently, mid-job, in production, producing *wrong coordinates* rather than clean errors.

Both reasons are independently disqualifying. **Neither is worked around. There is no `google_earth` provider, no scraper, no "advanced" flag, no documented workaround.** Requests to add one should be closed by pointing here.

`google_static` (§2.5) is a *different service* — Google Maps Platform, a documented commercial API with a key and a contract — and is still not enabled by default, still capability-blocked from caching and derivative export, and still requires an affirmative acknowledgement. Its presence is not a partial concession on Earth; it is a narrow accommodation for operators with their own agreement.

### 3.2 Why the default is keyless Esri

The brief requires the default provider be **keyless**, so the app runs with zero configuration. Esri World Imagery is the only source that is simultaneously keyless, global, and high-resolution enough to be plausible for GCP work. Sentinel is keyless-ish but 10 m (§2.4). Everything else needs a key.

**So the default is a bootstrapping decision, made under a zero-config constraint. It is not a licensing determination, and the product must not let it read as one.** §2.1's honesty box is reproduced in `README.md`, in the first-run log banner, in the UI provider picker, and on every PDF export. An operator who ships paid deliverables on the default provider without reading Esri's terms has made a mistake the software should have made hard to make — hence the repetition.

### 3.3 Operator verification checklist

Before enabling any provider in production, verify **for your jurisdiction, your use, and your agreement**:

| Question | `local_ortho` | `esri` | `mapbox` | `bing` | `sentinel` | `google_static` |
|---|---|---|---|---|---|---|
| May I use this commercially? | your imagery | **verify** | ToS + plan | licence tier | ✅ yes | your agreement |
| May I create derivative products (extracted GCPs)? | ✅ | **verify** | **verify** | **verify** | ✅ | **⚠️ likely no** |
| May I cache tiles, and for how long? | n/a | **verify** | capped | **verify** | ✅ | **⚠️ likely no** |
| May imagery appear in a client PDF? | ✅ | **verify** | w/ attribution | w/ attribution | ✅ w/ attribution | **⚠️ likely no** |
| Attribution text + placement required? | your call | ✅ | ✅ + link | ✅ per-region | ✅ | ✅ logo as delivered |
| Automated/bulk retrieval permitted? | n/a | be conservative | per ToS | per ToS | ✅ | **⚠️ likely no** |
| Rate limits? | n/a | none published — self-limit | per plan | per plan | per plan | per plan |

Every **verify** is a cell where the honest engineering answer is "we don't know your situation, and guessing on your behalf would be worse than asking."

### 3.4 Enforcement (mechanical, not advisory)

Documentation that relies on people remembering it is not a control. Each obligation is bound to a mechanism:

| Obligation | Mechanism |
|---|---|
| Google Earth never accessed | No provider exists. No endpoint in the codebase. CI greps for Earth endpoint patterns and fails the build. |
| Restricted providers not default | `default_chain()` = `['local_ortho', 'esri']`. `google_static` unreachable via fallback. |
| Google requires affirmative opt-in | `is_configured()` demands `GOOGLE_TOS_ACKNOWLEDGED=true` in addition to the key. |
| Caching respects terms | `capabilities().allows_caching = False` ⇒ persistent caches **refuse the write**, LRU only. |
| Pixels don't leak into deliverables | `capabilities().allows_derivative_export = False` ⇒ PDF/report writers omit the map figure. |
| Attribution always shown | `SatelliteChip.attribution` is non-optional on the type; §3.5. |
| Operator can hard-restrict the fleet | `ALLOWED_PROVIDERS` env allow-list; `resolve()` raises `ProviderDisabledError` for anything outside it, regardless of keys present. |
| Rate limits respected | Per-provider `TokenBucket` in `imagery/ratelimit.py`, shared across workers via Redis. |

`ALLOWED_PROVIDERS` is the operator's blunt instrument: an org that has decided only `local_ortho` and `sentinel` are licensed for their work sets `ALLOWED_PROVIDERS=local_ortho,sentinel`, and no misconfiguration, no fallback, and no UI selection can reach anything else.

### 3.5 Attribution rendering requirements (UI + exports)

Attribution is a **licence condition**, not a courtesy. Requirements:

1. **`SatelliteChip.attribution` is a required, non-nullable field.** Pixels cannot exist in this system without their credit attached. This is the whole reason `get_static_bbox` returns `SatelliteChip` rather than a bare `(ndarray, geotransform)` tuple (§1.3) — a tuple lets pixels travel naked; the type forbids it.
2. **Map view (Leaflet).** Bottom-right control, always visible, never behind a toggle, never obscured by overlays. Contrast-compliant against imagery (dark text on translucent light scrim). Links open in a new tab: `<attribution text> · Terms`.
3. **Canvas view (Konva).** The GCP-marking canvas renders the satellite chip; the same attribution string renders as a fixed bottom-left overlay outside the pan/zoom transform — it must not scroll away or scale down when the user zooms.
4. **Bing.** Attribution derives from the Metadata API's `ImageryProviders` `coverageAreas`, filtered to the current bbox and zoom, appended to `© {year} Microsoft Corporation`. Static text is non-compliant (§2.3).
5. **Google.** The Google logo must render **as delivered**, not cropped, restyled, or recomposed. Since `allows_derivative_export = False` blocks the figure from exports anyway, this constrains only the live view.
6. **PDF export (§8.6).** Attribution renders in the map figure's caption **and** the metadata block: provider name, attribution string, terms URL, imagery capture date (where known), and retrieval timestamp. Full imagery provenance on the artifact the client actually keeps.
7. **CSV / GeoJSON / Shapefile / KML.** Machine formats carry provenance too — GeoJSON top-level `properties.attribution`; CSV `# ` header comment block; Shapefile a sidecar `README.txt` inside the zip (the `.dbf` cannot hold it); KML a `<description>` on the document node.
8. **Missing attribution is a test failure.** `test_every_provider_has_attribution` asserts every registered provider returns non-empty `attribution` and a well-formed `terms_url`. A new provider cannot merge without them.

---

## 4. Tile math (`gis/tiles.py`)

Pure functions. **No I/O, no provider knowledge, no optional dependencies** — NumPy and stdlib `math` only. This module must import and pass its tests on a machine with nothing installed but numpy, because every other part of the GIS layer depends on it and it is the one place where a subtle error produces *plausible wrong answers* rather than a crash.

### 4.1 Constants

```python
EARTH_RADIUS_M: float = 6_378_137.0                     # WGS84 semi-major (Web Mercator sphere)
ORIGIN_SHIFT_M: float = math.pi * EARTH_RADIUS_M        # 20_037_508.342789244
INITIAL_RESOLUTION: float = 2 * math.pi * EARTH_RADIUS_M / 256   # 156_543.033928041 m/px at z0
MAX_LAT: float = 85.0511287798066                       # atan(sinh(pi)) — Mercator clip
DEFAULT_TILE_SIZE: int = 256
```

`MAX_LAT` is where the Mercator projection of ±90° diverges; it is the latitude at which the world is exactly square. Latitudes beyond it have **no tile representation at all** — not a degraded one. Functions clamp and log rather than emitting `inf`/`NaN` that propagate silently into a geotransform.

### 4.2 lat/lon ↔ tile

```python
def lonlat_to_tile(lon: float, lat: float, z: int) -> TileRef:
    """
    WGS84 lon/lat -> XYZ tile indices (origin NW, y increases south).

        n = 2 ** z
        x = floor((lon + 180.0) / 360.0 * n)
        lat_rad = radians(clamp(lat, -MAX_LAT, MAX_LAT))
        y = floor((1.0 - asinh(tan(lat_rad)) / pi) / 2.0 * n)
        clamp x, y into [0, n-1]

    asinh(tan(φ)) is used rather than log(tan(φ) + sec(φ)): mathematically
    identical, numerically better near the equator, and one call.

    lat outside ±MAX_LAT is CLAMPED with a WARNING, never NaN'd.
    lon is WRAPPED to [-180, 180) — antimeridian AOIs are real (§4.8).
    """

def lonlat_to_tile_fractional(lon: float, lat: float, z: int) -> tuple[float, float]:
    """
    Same, unfloored. Fractional part IS the within-tile pixel offset:
    px = (fx - floor(fx)) * tile_size. Essential for stitch cropping (§4.6)
    and for pixel->lonlat at sub-pixel precision. Flooring early and
    reconstructing offsets later is how off-by-half-a-tile bugs are born.
    """

def tile_to_lonlat(z: int, x: int, y: int) -> tuple[float, float]:
    """
    Tile indices -> lon/lat of the tile's NW CORNER (not centre — corners
    compose; centres don't).

        n = 2 ** z
        lon = x / n * 360.0 - 180.0
        lat = degrees(atan(sinh(pi * (1 - 2 * y / n))))

    Exact inverse of lonlat_to_tile_fractional. Property-tested round-trip
    to 1e-9 deg across z in [0, 22].
    """

def tile_to_lonlat_center(z: int, x: int, y: int) -> tuple[float, float]: ...
```

### 4.3 Web Mercator ↔ lat/lon (closed form, no pyproj)

```python
def lonlat_to_meters(lon: float, lat: float) -> tuple[float, float]:
    """
    EPSG:4326 -> EPSG:3857.
        mx = lon * ORIGIN_SHIFT_M / 180.0
        my = log(tan((90 + clamp(lat,-MAX_LAT,MAX_LAT)) * pi / 360.0)) / (pi / 180.0)
        my = my * ORIGIN_SHIFT_M / 180.0
    """

def meters_to_lonlat(mx: float, my: float) -> tuple[float, float]:
    """
    EPSG:3857 -> EPSG:4326.
        lon = mx / ORIGIN_SHIFT_M * 180.0
        lat = my / ORIGIN_SHIFT_M * 180.0
        lat = 180.0 / pi * (2 * atan(exp(lat * pi / 180.0)) - pi / 2.0)
    """

def lonlat_to_meters_array(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized. Used per-GCP-batch and for grid warps. Same formula, np ufuncs."""
```

These exist **in closed form, in NumPy, with no pyproj**, for one deliberate reason: 4326↔3857 is the only transform on the hot path, pyproj is not installed on the dev machine (§0.1), and the transform is exactly this arithmetic. Making the core tile pipeline depend on an uninstalled library for a 4-line formula would fail the "works out of the box" mandate over nothing. pyproj is required only for *other* CRSs (§6), where reimplementing would be reckless.

### 4.4 Resolution & zoom selection

```python
def resolution_at(z: int, lat: float, tile_size: int = DEFAULT_TILE_SIZE) -> float:
    """
    Ground metres per pixel at zoom z, latitude φ.

        mpp = 156543.033928041 * cos(radians(lat)) / (2 ** z)      [tile_size=256]
        general: (2*pi*R / tile_size) * cos(radians(lat)) / (2**z)

    The cos(φ) is Web Mercator's scale distortion (§6.3) and is the ONLY
    reason this takes a latitude. Callers that drop it are wrong by 1/cos(φ):
    at 55°N a "0.6 m/px" z18 tile is really 0.34 m/px on the ground.

    resolution_at(0,  0.0) == 156543.03392804097
    resolution_at(18, 0.0) ==      0.5971642834779395
    resolution_at(18, 55.0)==      0.34251936163340246
    """

def zoom_for_resolution(
    target_mpp: float,
    lat: float,
    tile_size: int = DEFAULT_TILE_SIZE,
    *,
    round_mode: Literal["up", "down", "nearest"] = "up",
) -> int:
    """
    Smallest zoom whose resolution is at least as fine as target_mpp at lat.

        z = log2(156543.033928041 * cos(radians(lat)) / target_mpp)
        apply round_mode; clamp to [0, 24]

    round_mode="up" is the DEFAULT and the right default: rounding DOWN
    silently gives coarser imagery than requested, and "coarser than
    requested" in a surveying product means a GCP is less accurate than
    the operator was told. Over-fetching costs tiles; under-fetching costs
    correctness. Fail toward the expensive side.

    Callers MUST then clamp into [provider.min_zoom, provider.max_zoom] and
    surface the clamp — see choose_zoom().
    """

def choose_zoom(
    provider: ImageryProvider,
    target_mpp: float,
    lat: float,
) -> ZoomDecision:
    """
    Provider-aware zoom selection. Returns:
        ZoomDecision(zoom, achieved_mpp, clamped: bool, reason: str | None)

    'clamped' is load-bearing. If the operator wants 0.1 m/px and asks
    Sentinel, the honest answer is 'you asked for 0.1, you are getting 9.55,
    here is why' — surfaced in the UI and stamped on the export, never
    quietly downgraded. Silent degradation in a measurement product is a
    correctness bug wearing a UX costume.
    """
```

### 4.5 Tile bboxes

```python
def tile_bbox_lonlat(z: int, x: int, y: int) -> BBox:
    """Tile extent in EPSG:4326 from tile_to_lonlat of (x,y) and (x+1,y+1)."""

def tile_bbox_meters(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """
    Tile extent in EPSG:3857 (minx, miny, maxx, maxy). Exact, no trig:

        tile_span = 2 * ORIGIN_SHIFT_M / (2 ** z)
        minx = -ORIGIN_SHIFT_M + x * tile_span
        maxx = minx + tile_span
        maxy =  ORIGIN_SHIFT_M - y * tile_span      # y grows SOUTH
        miny = maxy - tile_span

    Preferred over the 4326 form for anything metric: 3857 tiles are exactly
    square and uniform, so this is pure arithmetic with no trig error.
    """

def bbox_to_tile_range(bbox: BBox, z: int) -> TileRange:
    """
    Minimal covering tile rectangle.
        TileRange(z, x_min, y_min, x_max, y_max)  # inclusive
    NOTE north/south inversion: bbox.north -> y_min, bbox.south -> y_max.
    Handles antimeridian by splitting (§4.8). Raises AreaTooLargeError above
    MAX_TILES_PER_REQUEST.
    """

def tile_range_count(rng: TileRange) -> int:
    """(x_max-x_min+1) * (y_max-y_min+1). Call BEFORE fetching, always (§5.3)."""
```

### 4.6 Stitching & geotransform

```python
def stitch_tiles(
    tiles: dict[TileRef, np.ndarray],
    rng: TileRange,
    tile_size: int = DEFAULT_TILE_SIZE,
    *,
    missing_fill: tuple[int, int, int] = (0, 0, 0),
) -> tuple[np.ndarray, tuple[float, ...]]:
    """
    Assemble a tile grid into one mosaic + its EPSG:3857 geotransform.

    Canvas: H = (y_max-y_min+1)*tile_size, W = (x_max-x_min+1)*tile_size
    Placement: tile (x,y) at row (y-y_min)*tile_size, col (x-x_min)*tile_size

    Geotransform (GDAL 6-tuple), derived from the NW tile corner:
        span   = 2 * ORIGIN_SHIFT_M / (2**z)
        res    = span / tile_size                       # m/px, exact
        originX = -ORIGIN_SHIFT_M + x_min * span
        originY =  ORIGIN_SHIFT_M - y_min * span
        gt = (originX, res, 0.0, originY, 0.0, -res)    # note: NEGATIVE y-res

    Missing tiles fill with missing_fill AND are recorded in the returned
    coverage mask — the matcher must never treat filled black as terrain.
    A synthetic uniform region is a feature-detector trap: it produces no
    keypoints, which is safe, but it also silently shrinks effective overlap
    without telling anyone. The mask makes the hole explicit.
    """

def crop_to_bbox(
    mosaic: np.ndarray,
    gt: tuple[float, ...],
    bbox: BBox,
) -> tuple[np.ndarray, tuple[float, ...]]:
    """
    Crop a tile-aligned mosaic to the exact requested bbox, folding the crop
    offset into the geotransform origin:

        px_min = (bbox_mx_min - gt[0]) / gt[1]
        py_min = (bbox_my_max - gt[3]) / gt[5]
        ...floor/ceil to whole pixels (never crop to sub-pixel — resampling
        for a crop invents data)...
        new_gt = (gt[0] + px_min * gt[1], gt[1], 0.0,
                  gt[3] + py_min * gt[5], 0.0, gt[5])

    THE geotransform bug in every tile pipeline is cropping the array and
    forgetting the origin. Result: every coordinate off by a constant offset
    up to one tile (~150 m at z18). It looks plausible. It is catastrophic in
    a surveying product, because nothing crashes and the numbers are wrong.
    Crop and geotransform update are ONE function for this reason — they
    cannot be done separately because there is no public API to do them
    separately.
    """

def pixel_to_lonlat(gt, crs, col: float, row: float) -> tuple[float, float]:
    """
    Pixel (col,row) -> lon/lat. Pixel CENTRES are at +0.5:
        mx = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
        my = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]
        -> meters_to_lonlat if crs is 3857, else crs.to_lonlat (§6)
    The +0.5 is not pedantry: omitting it biases every GCP by half a pixel
    consistently in one direction — ~0.3 m at z18. That is a systematic bias,
    not noise, and it will not average out across GCPs.
    """

def lonlat_to_pixel(gt, crs, lon: float, lat: float) -> tuple[float, float]:
    """Inverse via the affine inverse. Returns floats; caller rounds knowingly."""

def geotransform_to_affine(gt) -> tuple[float, ...]:
    """GDAL 6-tuple -> rasterio/Affine order (a,b,c,d,e,f). One-liner, but it
    exists so the reordering happens in exactly one audited place."""
```

### 4.7 Testability

`gis/tiles.py` has zero I/O and zero optional deps, so it is exhaustively testable offline:

- **Round-trip properties** (hypothesis): `tile_to_lonlat(lonlat_to_tile(...))` within one tile; `meters_to_lonlat(lonlat_to_meters(...))` to 1e-6 m; `quadkey_to_tile(tile_to_quadkey(t)) == t`.
- **Golden values** against published references: `resolution_at(0, 0) == 156543.03392804097`; `tile_to_quadkey(3, 3, 5) == "213"`; known lon/lat→tile fixtures at several latitudes.
- **Geotransform invariants**: for any stitched mosaic, `pixel_to_lonlat(gt, 0, 0)` equals the NW tile corner; crop-then-transform equals transform-then-offset (the §4.6 bug, as an executable assertion).
- **Adversarial**: poles, antimeridian, z0, z24, lat = ±MAX_LAT exactly, lon = ±180 exactly.

### 4.8 Antimeridian

`bbox_to_tile_range` detects `west > east` (a bbox crossing ±180°) and returns **two** `TileRange`s. `stitch_tiles` refuses a wrapped range and raises `AntimeridianSplitRequired`, forcing the caller to handle two chips explicitly rather than silently producing a mosaic that wraps the entire globe backwards. Rare in agricultural work — and a 40,000 km-wide chip request is a memory-exhaustion event, not a rounding error, so it fails loudly.

---

## 5. Candidate tile generation (`gis/search_grid.py`)

### 5.1 Hint sources

The pipeline needs a location hint. Sources, in confidence order:

| Hint | Source | Typical radius | Confidence |
|---|---|---|---|
| **User-drawn AOI** | Leaflet rectangle/polygon | as drawn | highest — a human asserted it |
| **EXIF GPS** | `GPSLatitude/GPSLongitude/GPSHDOP` from the upload | 10–500 m (phone) | high, but see below |
| **Manual centre + radius** | UI form | user-chosen | medium |
| **Georeferenced upload** | GeoTIFF CRS + transform | exact | **total — skips search entirely (§7.4)** |
| **Nearest prior job** | prior GCPs in this project (PostGIS `ST_DWithin`) | 1–5 km | weak — a suggestion |
| **None** | — | — | **infeasible (§5.4)** |

```python
@dataclass(frozen=True, slots=True)
class SearchHint:
    center_lon: float
    center_lat: float
    radius_m: float
    source: Literal["aoi", "exif", "manual", "georef", "prior_job"]
    confidence: float                 # 0..1, feeds radius inflation
    polygon: list[tuple[float, float]] | None = None   # exact AOI when source="aoi"
```

**EXIF GPS is a hint, not a truth.** Phone GPS is 3–10 m at best and tens of metres under canopy or beside a barn; the tag may be the *processing* location if the photo was exported through desktop software; and `GPSHDOP`/`GPSDifferential` are frequently absent. `EXIF_RADIUS_INFLATION` (default 3.0×, floored at `EXIF_MIN_RADIUS_M = 250`) inflates the hinted radius accordingly. An EXIF hint taken literally produces a search box that confidently excludes the correct answer — the worst failure mode available here, because it returns a *plausible wrong match* from a neighbouring field rather than no match.

### 5.2 Coarse-to-fine strategy

Brute-forcing the finest zoom over a 5 km radius is unaffordable in tiles and unnecessary in information. The search is a pyramid:

```python
@dataclass(frozen=True, slots=True)
class SearchPlan:
    stages: list[SearchStage]
    total_tile_budget: int
    hint: SearchHint

@dataclass(frozen=True, slots=True)
class SearchStage:
    zoom: int
    tiles: list[TileRef]
    overlap_px: int
    keep_top_k: int          # candidates promoted to the next stage
    chip_size_px: int

def plan_search(
    hint: SearchHint,
    provider: ImageryProvider,
    *,
    target_gsd_m: float = 0.5,
    max_tiles: int = 400,
    coarse_zoom_offset: int = 4,
    overlap_frac: float = 0.25,
) -> SearchPlan:
    """
    Build a coarse-to-fine plan.

      1. z_fine   = choose_zoom(provider, target_gsd_m, hint.center_lat).zoom
      2. z_coarse = max(provider.min_zoom, z_fine - coarse_zoom_offset)
      3. Stage 0 @ z_coarse: enumerate ALL tiles covering the hint disc.
         Cheap: each z_coarse tile covers 2^offset squared = 256x the ground
         of a z_fine tile at offset=4.
      4. Stages 1..n: only tiles under the top-k stage-(i-1) candidates,
         stepping ~2 zooms per stage.
      5. If projected tiles > max_tiles: raise z_coarse, cut keep_top_k, or
         raise AreaTooLargeError with a message telling the operator to
         shrink the AOI. NEVER silently truncate the search area — a
         truncated search that reports 'no match' is indistinguishable from
         an honest 'no match', and the operator will believe the wrong one.
    """

def enumerate_candidate_tiles(
    hint: SearchHint,
    zoom: int,
    *,
    overlap_frac: float = 0.25,
) -> list[TileRef]:
    """
    Tiles covering the hint disc/polygon at `zoom`.
      - disc: bbox = hint.buffered_m -> bbox_to_tile_range -> filter by true
        great-circle distance (a bbox over-covers the disc by 4/pi ~= 27%;
        at high zoom that is real money and real latency)
      - polygon: filter tiles whose 4326 bbox intersects the polygon
    """

def enumerate_search_chips(
    hint: SearchHint,
    provider: ImageryProvider,
    zoom: int,
    chip_size_px: int = 1024,
    overlap_frac: float = 0.25,
) -> Iterator[ChipRequest]:
    """
    Yield OVERLAPPING chip windows, not bare tiles. This is the unit the
    matcher actually wants.

    Overlap is not optional. A landmark straddling a tile seam is split
    across two chips and matches neither — SIFT needs the feature's full
    support region intact. stride = chip_size_px * (1 - overlap_frac);
    at 0.25, any feature with support <= 256 px is whole in at least one chip.

    Yields lazily so a Celery task can stream chips and short-circuit on a
    confident match instead of materializing the whole grid.
    """
```

### 5.3 Tile budget

Cost is quadratic in radius and in `2^z`. The count for a radius `r` at zoom `z`, latitude `φ`:

```
tiles ≈ (2r / (256 · resolution_at(z, φ)))²  ·  (1 / (1 - overlap_frac))²
```

Worked, at φ=45°, `resolution_at(18, 45) ≈ 0.4224 m/px` → one z18 tile ≈ 108 m:

| Radius | z18 tiles | z14 tiles (coarse) | Verdict |
|---|---|---|---|
| 100 m | ~4 | 1 | trivial |
| 500 m | ~86 | 1 | fine |
| 1 km | ~342 | ~2 | at budget |
| 5 km | ~8,558 | ~34 | **coarse-to-fine mandatory** |
| 50 km | ~855,800 | ~3,343 | **refuse** |

(Computed values; actual counts round up slightly because a bbox over-covers the disc — see `enumerate_candidate_tiles`.)

This table *is* the argument for §5.2. At 5 km, stage 0 costs ~34 tiles instead of ~8,558 — and only the top-k winners pay for z18. That is roughly a 100× reduction in tile spend, latency, and rate-limit consumption for the same answer.

Guards:

- `MAX_TILES_PER_REQUEST` (default 400) — hard ceiling per `get_static_bbox`.
- `MAX_TILES_PER_JOB` (default 2,000) — across all stages; exceeding raises `AreaTooLargeError` with the projected count and a suggested radius.
- `MAX_SEARCH_RADIUS_M` (default 10,000) — rejected at the API boundary, before a job is even created.
- Budget is checked **before** fetching, from `tile_range_count` (§4.5). Never discovered by running out.

### 5.4 No hint at all — the honest answer

**Hintless global search is infeasible. This is arithmetic, not an implementation gap, and no amount of engineering makes it go away.**

At z18 the world is 2¹⁸ × 2¹⁸ = **68,719,476,736 tiles**. Landmass only (~29%) still leaves ~2×10¹⁰. At ~15 KB/tile that is roughly **1 petabyte** to fetch — for one photograph. At Esri's self-imposed 8 rps it is ~270 years. Even a hypothetical DINOv2 global embedding index over land at z14 is ~10⁸ tiles: a pre-built index of a scale this product does not have and would not be licensed to build from any provider in §2.

Even granting infinite compute, the *matching* fails on information grounds: a single ground-level field photo of crops, a fence, and a treeline is not globally discriminative. Tens of thousands of locations on Earth match it as well as the true one. There is no signal to find. The bottleneck is not tiles — it is that the query is genuinely ambiguous.

**Therefore: a location hint is a hard input requirement of the product, not a convenience.**

Design consequences, made explicit rather than discovered by a user at 2am:

- **API.** `POST /api/v1/jobs/match` requires **exactly one** of `aoi_geojson`, `center+radius_m`, or `use_exif_gps: true`. Absent all three → **`422`** with `detail: "A location hint is required. LandExplorer searches within a hinted region; global search is not possible."` Not a 500, not an empty result — a validation error that names the missing input.
- **Upload.** EXIF GPS is parsed at upload and stored on `uploads.exif_gps` (§7.5). The UI shows a green "GPS found — search will centre here" chip, or an amber "No GPS in this photo — draw the search area on the map" prompt. The user learns this at *upload*, not after a failed job.
- **UX.** The map step is a **required, blocking step** in the wizard when no EXIF GPS exists. The Leaflet AOI draw control is the primary action, not a hidden option.
- **Honest copy.** The UI says *"Search this area"*, never *"Find this photo anywhere"*. Overpromising here creates a support burden and destroys trust in the coordinates the product *can* produce accurately.
- **Assist, don't fake.** `prior_job` hints (nearest AOI in the same project, via PostGIS `ST_DWithin`) and project-level default AOIs reduce hint friction for the realistic case — a surveyor working one farm all day. This is good UX; it is not global search, and the docs must not imply it is.

---

## 6. Projections (`gis/crs.py`)

### 6.1 Where each CRS is used

| CRS | Role | Used in |
|---|---|---|
| **EPSG:4326** WGS84 lon/lat | **The interchange CRS.** All API I/O, DB storage, exports, `BBox`. | API, PostGIS `geography`, GeoJSON/KML/CSV |
| **EPSG:3857** Web Mercator | **The tile/pixel CRS.** Slippy tiles, chip geotransforms, homography. | `gis/tiles.py`, providers, matcher |
| **UTM zone N/S** | **The metric CRS.** Distances, areas, RMSE, buffers. | accuracy metrics, Shapefile (optional), area calcs |
| Source CRS (per file) | Whatever an uploaded GeoTIFF declares. | `local_ortho`, georeferenced uploads |

**The rule: never measure in 4326, never measure in 3857.** Degrees are not a length unit (1° longitude is 111 km at the equator, 64 km at 55°N, 0 at the pole). And 3857 metres are not metres (§6.3). Any function returning a distance, area, or RMSE transforms to UTM first. Enforced by naming: functions returning metres end `_m` and require a projected CRS argument; passing 4326 raises `NonMetricCRSError`. A `_m` function that silently accepted degrees would return numbers that look like metres and aren't — the failure mode this whole section exists to prevent.

### 6.2 Reprojection boundaries

Reprojection happens at exactly three seams, and nowhere else:

1. **Provider → chip.** Tiles are native 3857 (free). `local_ortho` reprojects file CRS → 3857 during windowed read (§7.1). Chips leave with `crs="EPSG:3857"` — except the authoritative path (§7.4), which keeps native CRS and declares it.
2. **Chip pixel → output coordinate.** After homography: pixel → (via chip `gt`) 3857 → 4326. This is the closed-form path (§4.3) — no pyproj needed.
3. **4326 → UTM for metrics.** Only when computing distances/areas/RMSE. Transient; results are scalars, never stored geometry.

Everything between is **one CRS end to end**. The single most common defect class in GIS code is a mid-pipeline CRS change nobody noticed, producing coordinates that are wrong by a plausible-looking amount. Confining transforms to three named seams makes "which CRS is this?" answerable by location in the pipeline.

### 6.3 Web Mercator accuracy — a real problem for a surveying product

Web Mercator is conformal (locally angle-preserving) but **not equal-area and not equidistant**. Scale error grows as **1/cos(φ)**:

| Latitude | Scale factor | 100 m ground measures |
|---|---|---|
| 0° (equator) | 1.000 | 100.0 m |
| 30° | 1.155 | 115.5 m |
| 45° | 1.414 | 141.4 m |
| 55° (UK, N. Europe, S. Canada) | **1.743** | **174.3 m** |
| 60° (Scandinavia, Alaska) | 2.000 | 200.0 m |
| 70° | 2.924 | 292.4 m |

At 55°N — Yorkshire, Denmark, southern Sweden, much of Canada's prairie belt, all serious agricultural country — **a distance computed in 3857 metres is 74% too large.** A field measured as 174 m is 100 m.

Compounding it: EPSG:3857 uses a **sphere** for the projection while treating coordinates as WGS84 **ellipsoidal** lat/lon. This is geodetically incorrect by design (it is why it took years to get an EPSG code, and why 900913 was the joke that preceded it), introducing up to ~20 km of northing discrepancy versus a true ellipsoidal Mercator at high latitude.

**Consequences, enforced:**

- **3857 is a pixel-addressing scheme, not a measurement system.** It is used because tiles are defined in it. Its metres are for indexing, never for reporting.
- **Every reported distance, area, and RMSE is computed in UTM** (or a local ENU frame), never in 3857. `NonMetricCRSError` (§6.1) enforces it at the type boundary.
- **The homography is fitted in pixel space**, then applied through the chip geotransform. It never touches 3857 metres as if they were ground metres. Local scale distortion is *constant across a single chip* (a chip spans ≪ 1° of latitude), so it is absorbed into the homography rather than corrupting it — this is why the pixel-space fit is correct and a 3857-metre-space fit would not be.
- **Confidence radii** reported to the user are UTM metres. A "±2 m" that was silently 3857 metres at 55°N would really be ±1.15 m — over-conservative here, but the same bug reversed in an area calculation *under*-reports. Either way the number is not what it claims.

### 6.4 pyproj usage and the `always_xy` pitfall

```python
def utm_epsg_for(lon: float, lat: float) -> str:
    """
    Best UTM zone EPSG for a point.
        zone = floor((lon + 180) / 6) + 1
        north: 32600 + zone      south: 32700 + zone
    Norway zone-32 and Svalbard exceptions are NOT special-cased; they are
    documented and logged. LandExplorer's AOIs are <= 10 km, and using the
    'wrong' adjacent zone costs sub-mm at that extent. Special-casing them
    would add a rarely-exercised branch for no measurable accuracy.
    Raises OutsideUTMError for |lat| > 84 (use UPS).
    """

def get_transformer(src: str, dst: str) -> Transformer:
    """
    Cached pyproj Transformer.

        Transformer.from_crs(src, dst, always_xy=True)

    ############################################################
    #  always_xy=True IS MANDATORY. NON-NEGOTIABLE.            #
    ############################################################

    EPSG:4326's AUTHORITY-DEFINED axis order is (LATITUDE, LONGITUDE).
    pyproj >= 2.2 HONORS the authority order by default. So:

        Transformer.from_crs("EPSG:4326", "EPSG:32630")
            .transform(lon, lat)          # <-- SILENTLY WRONG
            # pyproj reads arg1 as LATITUDE, arg2 as LONGITUDE

    It does not raise. It returns plausible-looking numbers for the wrong
    place on Earth. In an agricultural GCP product, "plausible numbers for
    the wrong place" is the single most expensive bug available: the surveyor
    drives to the wrong field.

    always_xy=True forces (x=lon, y=lat) ordering on input AND output,
    matching GeoJSON, the whole rest of this codebase, and every developer's
    intuition.

    ENFORCEMENT: pyproj is NEVER imported outside gis/crs.py. CI greps for
    'from_crs' outside this module and fails the build. Transformer
    construction happens ONLY here, ONLY through this function, which ONLY
    ever passes always_xy=True. The pitfall is eliminated by making the
    mistake unreachable, not by asking reviewers to notice it.

    Cached via @lru_cache(maxsize=64): Transformer construction is expensive
    (~ms) and these are called per-GCP in tight loops.
    """

def transform_points(
    lons: np.ndarray, lats: np.ndarray, src: str, dst: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized batch transform. pyproj's transform() is vectorized over
    numpy arrays — per-point Python looping is ~100x slower for no reason."""

def is_metric_crs(crs: str) -> bool:
    """True iff linear units are metres. Gate for every *_m function (§6.1)."""
```

**Fallback (§0.1).** pyproj is not installed on the dev machine. `gis/crs.py` binds, in order: **pyproj** → **`osgeo.osr`** (installed, with `SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)` — the exact `always_xy` equivalent, and it is mandatory for the identical reason) → **closed-form NumPy** for the 4326↔3857 special case only. If an unsupported CRS pair is requested with no backend, `CRSBackendUnavailable` raises at *call* time with the missing dependency named. Core tile/match/export flows use only 4326↔3857 and therefore work on a bare machine; UTM metrics need osr or pyproj, both of which the container has.

---

## 7. GeoTIFF / orthophoto handling (`gis/raster.py`)

### 7.1 Windowed reads

Orthomosaics are routinely 5–100 GB. Never `read()` a whole dataset — a 60 GB file will OOM a Celery worker, and it will do it in production, on the biggest customer's data.

```python
def windowed_read(
    path: str | Path,
    bbox: BBox,
    *,
    target_gsd_m: float | None = None,
    out_crs: str = "EPSG:3857",
    band_indexes: tuple[int, ...] = (1, 2, 3),
) -> SatelliteChip:
    """
    Read only the pixels overlapping bbox, at the cheapest sufficient
    overview level, reprojected to out_crs.

      1. open via rasterio_shim (rasterio | GDAL)
      2. bbox 4326 -> dataset CRS -> pixel window (dataset transform inverse)
      3. clip window to dataset bounds; empty -> TileNotAvailableError
      4. pick overview: level whose GSD is the finest that is still coarser
         than or equal to target_gsd_m (§7.2)
      5. read window at that level with out_shape decimation
      6. reproject to out_crs (bilinear for imagery, NEVER nearest —
         nearest resampling on imagery destroys the sub-pixel gradient
         structure SIFT depends on; it is correct for categorical rasters
         and wrong for everything we do)
      7. apply nodata mask (§7.3)
      8. return SatelliteChip(is_authoritative=True, gsd_m=<actual>)
    """
```

### 7.2 Overviews

Overviews (internal pyramids) turn a 60 GB file into a browsable one. Absent them, a zoomed-out read decimates from full resolution — reading gigabytes to produce a 1024² chip.

```python
def overview_levels(path) -> list[OverviewLevel]:
    """Per band: decimation factors and their effective GSD."""

def best_overview_for_gsd(levels: list[OverviewLevel], target_gsd_m: float) -> int:
    """
    Finest level still >= target_gsd_m. Reading a coarser level and upsampling
    fabricates detail; reading a finer level and downsampling is correct but
    can be 100x the I/O. Pick the cheapest level that does not lie.
    """

def ensure_overviews(path, *, factors=(2,4,8,16,32), resampling="average") -> bool:
    """
    Build overviews if absent (gdaladdo-equivalent via the shim).
    Called by the ortho indexer at startup, gated on ORTHO_BUILD_OVERVIEWS
    (default True) — it WRITES to the operator's files, so it is announced in
    the log and skipped for read-only mounts rather than failing the index.
    Warns loudly if a large (>1 GB) file lacks overviews and building is off:
    that combination is a latent production timeout, not a preference.
    """
```

Uploaded GeoTIFFs are converted to **COG** (tiled, internal overviews, `DEFLATE`) on ingest. A striped, overview-less TIFF makes windowed reads pathological — every window touches every strip.

### 7.3 CRS & nodata

```python
def dataset_crs(path) -> str:
    """
    Declared CRS as 'EPSG:xxxx'. Handles: no CRS (-> MissingCRSError, do NOT
    assume 4326 — assuming is how imagery ends up silently off the coast of
    Africa at 0,0); non-EPSG WKT (-> best-effort EPSG match, else keep WKT);
    ESRI codes (-> mapped where possible).
    """

def nodata_mask(path, window) -> np.ndarray:
    """
    Bool mask, True = VALID.
      1. dataset alpha band, if present (authoritative)
      2. dataset nodata value per band
      3. ORTHO_ASSUME_BLACK_NODATA (default False): treat pure (0,0,0) as
         nodata. DEFAULT FALSE deliberately — real imagery contains genuine
         black (shadow, water, asphalt, tarps), and masking it silently
         deletes real features from the matcher.
      4. no info -> all valid

    Mosaic collars are the reason this matters. Orthomosaic edges are black
    triangles from the flight boundary. Unmasked, they present as huge
    high-contrast corners — the strongest 'features' in the whole chip, and
    entirely synthetic. SIFT will happily match a collar edge to another
    collar edge and RANSAC will find a beautifully consistent homography
    between two artifacts. A confident, completely wrong result. The mask
    propagates to SatelliteChip.valid_mask and the feature extractor drops
    keypoints outside it.
    """
```

### 7.4 The authoritative path — georeferenced uploads short-circuit everything

**If the upload is already georeferenced, there is nothing to search for. The answer is already in the file. Do not run the matcher.**

This is the most important design decision in §7, and it inverts the pipeline. A surveyor uploading their own orthophoto — the most sophisticated, highest-value user — does not need SIFT, RANSAC, tiles, providers, or a location hint. Their file already contains a survey-grade transform. Running a matcher over it would *replace exact coordinates with estimated ones* — actively destroying accuracy while burning compute and looking busy.

```python
def detect_georeferencing(path) -> GeorefInfo | None:
    """
    Inspect an upload for usable georeferencing.

    GeorefInfo(
        crs: str,
        transform: tuple[float, ...],      # GDAL 6-tuple
        gsd_m: float,
        source: Literal["geotiff", "worldfile", "gcps", "rpc"],
        quality: Literal["exact", "approximate"],
        gcp_rmse_m: float | None,          # if embedded GCPs carry residuals
    )

    Detection order:
      1. valid CRS + affine transform in the TIFF   -> source="geotiff", "exact"
      2. sidecar world file (.tfw/.jgw/.pgw) + .prj -> source="worldfile", "exact"
      3. embedded GCPs (no affine)  -> fit affine/TPS -> source="gcps",
                                       quality per fit RMSE
      4. RPC coefficients (raw satellite) -> source="rpc", "approximate"
         (needs a DEM for real rectification — out of scope; flag it)
      5. none -> None -> normal matching pipeline
    """
```

**Pipeline fork, at job creation:**

```
upload
  └─ detect_georeferencing()
       ├─ GeorefInfo(quality="exact")   -> DIRECT PATH
       │     • no provider call, no tiles, no hint, no Celery CV stage
       │     • each marked pixel -> pixel_to_lonlat(transform, crs, col, row)
       │     • confidence = 1.0; method = "direct_georeference"
       │     • accuracy = the file's own accuracy (gcp_rmse_m if known,
       │                  else gsd_m/2 as a floor, clearly labelled as a floor)
       │     • job completes in milliseconds
       │     • export identical in shape to the matched path
       │
       ├─ GeorefInfo(quality="approximate") -> ASSISTED PATH
       │     • georef seeds the hint (radius = 3 * gcp_rmse_m or 100 m)
       │     • matcher runs, but SEARCH IS TINY — one chip, not a grid
       │     • refined homography composed with the file's transform
       │
       └─ None -> FULL MATCHING PIPELINE (§5)
```

The API exposes this as `job.method ∈ {"direct_georeference", "assisted", "matched"}` so the UI can be honest: *"This image is already georeferenced — coordinates are exact, no search needed"* is a far better outcome than a progress bar and a 0.87 confidence score. A ground-level phone photo cannot take this path (no georeferencing) — which is the common case, and why the matcher exists. But the direct path is the one that makes the product *correct* for professional users, and it must exist from day one rather than being retrofitted.

**Guard against the seductive wrong move:** never *assume* georeferencing. A TIFF with a CRS but an identity transform, or a transform with a zero pixel size, is corrupt, not exact. `detect_georeferencing` validates that the transform is invertible, has non-zero pixel sizes, and produces bounds within the CRS's area of use — else returns `None` and falls through to matching. Trusting broken metadata is worse than having none.

### 7.5 Persistence

```sql
-- Indexed local orthophotos (populated by the startup/beat indexer, §2.6)
CREATE TABLE ortho_index (
    id            BIGSERIAL PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    file_hash     TEXT NOT NULL,                    -- content hash -> cache variant key
    crs           TEXT NOT NULL,
    gsd_m         DOUBLE PRECISION NOT NULL,
    width_px      INTEGER NOT NULL,
    height_px     INTEGER NOT NULL,
    band_count    SMALLINT NOT NULL,
    has_overviews BOOLEAN NOT NULL DEFAULT FALSE,
    nodata_value  DOUBLE PRECISION,
    captured_at   TIMESTAMPTZ,
    bounds_4326   geometry(Polygon, 4326) NOT NULL, -- footprint for R-tree / ST_Intersects
    indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ortho_index_gsd_positive CHECK (gsd_m > 0)
);
CREATE INDEX ortho_index_bounds_gix ON ortho_index USING GIST (bounds_4326);
CREATE INDEX ortho_index_gsd_idx    ON ortho_index (gsd_m);

-- Georeferencing detected on an upload (§7.4)
ALTER TABLE uploads
  ADD COLUMN georef_crs        TEXT,
  ADD COLUMN georef_transform  DOUBLE PRECISION[6],
  ADD COLUMN georef_source     TEXT,               -- geotiff|worldfile|gcps|rpc
  ADD COLUMN georef_quality    TEXT,               -- exact|approximate
  ADD COLUMN georef_rmse_m     DOUBLE PRECISION,
  ADD COLUMN exif_gps          geometry(Point, 4326),
  ADD COLUMN exif_gps_hdop     DOUBLE PRECISION;
CREATE INDEX uploads_exif_gps_gix ON uploads USING GIST (exif_gps);
```

`bounds_4326` as a PostGIS geometry with a GIST index lets `local_ortho` answer "which files cover this AOI?" with `ST_Intersects` in the DB, rather than scanning an in-memory index — which matters once an operator mounts a few thousand tiles' worth of county orthophotography.

---

## 8. Exports (`gis/exports/`)

### 8.1 Layout & common contract

```
backend/app/gis/exports/
├── __init__.py          # EXPORT_WRITERS registry, get_writer(fmt)
├── base.py             # ExportWriter ABC, ExportBundle, ExportContext
├── csv_writer.py       # CsvExportWriter        — stdlib only
├── geojson_writer.py   # GeoJsonExportWriter    — stdlib only
├── shapefile_writer.py # ShapefileExportWriter  — geopandas/fiona
├── kml_writer.py       # KmlExportWriter        — stdlib xml.etree
├── pdf_writer.py       # PdfReportWriter        — reportlab
└── fieldmap.py         # FieldNameMapper — the .dbf 10-char problem (§8.4)
```

```python
@dataclass(frozen=True, slots=True)
class ExportContext:
    """Everything a writer needs. Assembled once; writers never touch the DB
    or the network — makes every writer trivially unit-testable offline."""
    job_id: uuid.UUID
    project_name: str
    gcps: list[GcpRecord]              # lon, lat, confidence, pixel col/row, label, method
    chip: SatelliteChip | None         # None when allows_derivative_export=False
    provider_name: str
    attribution: str
    terms_url: str
    imagery_captured_at: datetime | None
    retrieved_at: datetime
    method: Literal["direct_georeference", "assisted", "matched"]
    homography: np.ndarray | None
    rmse_m: float | None
    crs: str = "EPSG:4326"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    software_version: str = __version__


class ExportWriter(abc.ABC):
    @property
    @abc.abstractmethod
    def format_id(self) -> str: ...            # "csv" | "geojson" | "shp" | "kml" | "pdf"
    @property
    @abc.abstractmethod
    def media_type(self) -> str: ...
    @property
    @abc.abstractmethod
    def file_extension(self) -> str: ...

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str | None]:
        """(available, reason_if_not). Optional deps are reported, not raised
        (§0.1). /api/v1/exports/formats returns this so the UI greys out
        Shapefile with 'requires fiona' instead of offering a 500."""

    @abc.abstractmethod
    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle: ...


@dataclass(frozen=True, slots=True)
class ExportBundle:
    path: Path
    media_type: str
    filename: str
    size_bytes: int
    warnings: list[str]     # e.g. truncated field names, omitted imagery
```

`warnings` is not decoration. When Shapefile truncates `confidence_score` → `confidenc`, the user must be told in the API response — not left to discover it when their GIS shows a column they didn't name.

### 8.2 CSV (`csv_writer.py`)

```python
class CsvExportWriter(ExportWriter):
    format_id = "csv"; media_type = "text/csv"; file_extension = ".csv"

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """
        Columns (exact, ordered):
            gcp_id, label, longitude, latitude, elevation_m,
            pixel_col, pixel_row, confidence, method, rmse_m,
            provider, imagery_captured_at, generated_at, crs

        - stdlib csv, UTF-8 **with BOM** (utf-8-sig): Excel mis-decodes plain
          UTF-8 CSV, and field labels contain non-ASCII more often than people
          expect. The BOM costs nothing and prevents a support ticket.
        - lon/lat at 8 dp (~1.1 mm) — beyond ANY provider's accuracy, so
          rounding never becomes the error term.
        - **longitude before latitude**, matching GeoJSON and the rest of the
          codebase (§6.4). Documented in the header comment because CSV has no
          schema to enforce it.
        - provenance as leading '# ' comment lines (§3.5): provider,
          attribution, terms_url, software version. Skipped by pandas via
          comment='#'.
        """
```

### 8.3 GeoJSON (`geojson_writer.py`)

```python
class GeoJsonExportWriter(ExportWriter):
    format_id = "geojson"; media_type = "application/geo+json"; file_extension = ".geojson"

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """
        RFC 7946 FeatureCollection. Point per GCP, [lon, lat] order.

        RFC 7946 MANDATES CRS84 (WGS84 lon/lat). No 'crs' member — it was
        removed in RFC 7946 and emitting one is both non-conformant and
        ignored. We therefore ALWAYS emit 4326 and never offer a CRS option
        here; operators wanting a projected CRS use Shapefile (§8.4).

        Per feature: properties = {gcp_id, label, confidence, method,
                                   pixel_col, pixel_row, rmse_m,
                                   elevation_m?}
        Top level: "properties" = {job_id, project_name, provider,
                                   attribution, terms_url,
                                   imagery_captured_at, generated_at,
                                   software_version}   <- §3.5 requirement

        Top-level "properties" is technically an extension member (RFC 7946
        does not define it on a FeatureCollection); it is permitted, widely
        tolerated, and the least-bad place for provenance that must not be
        lost. Ignoring parsers ignore it harmlessly.

        stdlib json. No dependencies. Always available.
        """
```

### 8.4 Shapefile (`shapefile_writer.py`) — the format that fights back

Shapefile is a 1990s format the industry cannot leave. Its limits are not edge cases; they are load-bearing:

| Limit | Value | Consequence here |
|---|---|---|
| **`.dbf` field names** | **≤ 10 chars, ASCII** | `confidence_score` → truncated/mangled |
| Field name collisions | after truncation | `imagery_captured_at` & `imagery_capture_date` both → `imagery_c` |
| Text fields | 254 chars | long labels truncated |
| No datetime | date only, no time | timestamps lose time-of-day |
| No `NULL` for numerics | 0 vs missing ambiguous | nodata indistinguishable from zero |
| File size | 2 GB per `.shp`/`.dbf` | irrelevant here (thousands of points) |
| Multi-file | `.shp .shx .dbf .prj .cpg` | **must ship as a zip** |
| Encoding | `.cpg` or ambiguous | mojibake without it |

```python
class ShapefileExportWriter(ExportWriter):
    format_id = "shp"
    media_type = "application/zip"
    file_extension = ".zip"

    def is_available(self) -> tuple[bool, str | None]:
        """False + 'requires geopandas/fiona' when unimportable. NOT installed
        on the dev machine (§0.1) — so this MUST degrade, not crash. The UI
        greys the option; CSV/GeoJSON/KML remain available."""

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """
        1. FieldNameMapper.map(...) -> 10-char unique names (below)
        2. gpd.GeoDataFrame(rows, geometry=points, crs=ctx.crs)
        3. optional reproject to target_crs (UTM) — Shapefile is the ONE
           format where a projected CRS is both legal and commonly wanted
        4. to_file(tmp/gcps.shp, driver="ESRI Shapefile", encoding="utf-8")
        5. write .cpg = "UTF-8" (fiona does not always) — without it, ArcGIS
           guesses the codepage and non-ASCII labels become mojibake
        6. verify .prj was emitted; write from CRS WKT1_ESRI if missing —
           a Shapefile without .prj is a Shapefile with NO CRS, and the
           receiving GIS will guess (wrongly)
        7. README.txt: attribution, terms_url, provider, capture date, the
           FULL field-name mapping table (§3.5 — the .dbf cannot hold this)
        8. zip all sidecars -> out_path
        9. warnings += every truncation/rename, surfaced to the API
        """
```

```python
class FieldNameMapper:
    """
    Long attribute names -> unique, valid, <=10-char .dbf names.

    Explicit table first — a hand-chosen abbreviation beats an algorithmic
    one, and these are the names a surveyor reads in ArcGIS at 6pm:

        gcp_id               -> GCP_ID
        label                -> LABEL
        longitude            -> LON
        latitude             -> LAT
        elevation_m          -> ELEV_M
        confidence           -> CONF
        method               -> METHOD
        rmse_m               -> RMSE_M
        pixel_col            -> PIX_COL
        pixel_row            -> PIX_ROW
        provider             -> PROVIDER
        imagery_captured_at  -> IMG_DATE
        generated_at         -> GEN_DATE

    Fallback for unknown fields: uppercase, strip non-alnum, truncate to 10,
    then de-duplicate with a numeric suffix that REPLACES trailing chars
    (never extends past 10): SOMEFIELD, SOMEFIEL1, SOMEFIEL2...

    map() returns (mapping, warnings). EVERY rename is a warning. The full
    mapping goes in the zip's README.txt because the .dbf has nowhere to
    record what it did to the operator's schema.
    """
    def map(self, field_names: Sequence[str]) -> tuple[dict[str, str], list[str]]: ...
```

### 8.5 KML (`kml_writer.py`)

```python
class KmlExportWriter(ExportWriter):
    format_id = "kml"
    media_type = "application/vnd.google-earth.kml+xml"
    file_extension = ".kml"

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """
        OGC KML 2.2 via stdlib xml.etree — no dependency. Always available.

        <Document><name>{project} - GCPs</name>
                  <description>{attribution} | {terms_url} | ...</description>
        Per GCP: <Placemark> with <name>{label}</name>,
                 <ExtendedData><Data name="confidence">... (typed schema),
                 <Point><coordinates>lon,lat,elev</coordinates>

        - coordinates are **lon,lat,alt** — KML's own order, matching ours.
        - KML is DEFINED as WGS84 (EPSG:4326) only. No CRS option. Reproject
          in if needed; never emit projected coordinates into KML.
        - <Style>/<StyleMap> colour-codes markers by confidence band
          (green >=0.8, amber 0.5-0.8, red <0.5) — the one export where a
          human eyeballs results in a viewer, so confidence should be visible
          without opening a table.
        - KMZ (zipped KML + marker icons) via `format_id="kmz"` variant.

        NOTE: emitting KML is unrelated to §3.1. KML is an open OGC standard;
        producing a file a user may open in Google Earth is not accessing
        Google Earth imagery. We never read their imagery; a user opening our
        coordinates in their viewer is their own use of their own software.
        """
```

### 8.6 PDF report (`pdf_writer.py`)

```python
class PdfReportWriter(ExportWriter):
    format_id = "pdf"; media_type = "application/pdf"; file_extension = ".pdf"

    def is_available(self) -> tuple[bool, str | None]:
        """False + 'requires reportlab' when unimportable (not installed on
        the dev machine, §0.1). Degrades; never crashes the export endpoint."""

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """
        A4 portrait, reportlab platypus. The client-facing artifact.

        Page 1 — Summary
          • Title: {project_name} — GCP Report;  job id; generated_at
          • Method badge: Direct georeference / Assisted / Matched (§7.4) —
            the FIRST thing a reader should see, because it determines how
            much to trust everything below
          • Map figure: ctx.chip with GCP markers + labels, north arrow,
            scale bar (UTM metres, §6.3 — NEVER 3857 metres)
            - OMITTED with an explanatory note when
              capabilities().allows_derivative_export is False (§2.5).
              Coordinates still export; pixels do not.
          • Caption: attribution + capture date + retrieval date (§3.5)

        Page 2 — GCP table
          • ID | Label | Longitude | Latitude | Confidence | Method
          • lon/lat 8 dp; confidence colour-banded to match KML
          • repeating header across page breaks (LongTable)

        Page 3 — Metadata & provenance
          • provider, attribution, terms_url (hyperlinked)
          • imagery capture date, retrieval timestamp
          • GSD, zoom, achieved vs requested resolution + clamp reason (§4.4)
          • homography, inlier count, RMSE (UTM metres)
          • **Accuracy statement** — mandatory, honest, and NOT boilerplate:
              - direct_georeference: "Coordinates derived directly from the
                source file's georeferencing. Accuracy = source accuracy
                ({rmse or 'gsd/2, a floor not a measurement'})."
              - matched + sentinel: "Imagery GSD 10 m. Positional accuracy is
                limited to approximately +/-10-20 m and is NOT suitable for
                survey-grade GCP work." (§2.4 — stated on the artifact the
                client keeps, not only in a UI they closed)
              - matched + other: RMSE + inliers + the caveat that provider
                georegistration error is unknown and NOT included in RMSE.
          • software version, LandExplorer attribution

        The accuracy statement is generated from ExportContext, never
        hand-written per template. A PDF that quietly omits 'this is +/-15 m'
        is the document that gets forwarded to a client and believed.
        """
```

### 8.7 Registry

```python
EXPORT_WRITERS: dict[str, type[ExportWriter]] = {
    "csv": CsvExportWriter,
    "geojson": GeoJsonExportWriter,
    "shp": ShapefileExportWriter,
    "kml": KmlExportWriter,
    "kmz": KmzExportWriter,
    "pdf": PdfReportWriter,
}

def get_writer(format_id: str) -> ExportWriter:
    """Raises UnknownExportFormatError. Availability is the CALLER's check
    via is_available() — so the API can 400 with 'Shapefile export requires
    fiona' instead of 500-ing inside a writer."""

def available_formats() -> list[ExportFormatInfo]:
    """Every format + availability + reason. Backs GET /api/v1/exports/formats;
    the UI greys unavailable options rather than failing on click."""
```

**Dependency posture, deliberately:** CSV, GeoJSON, and KML use **stdlib only** and are therefore *always* available — including on the current dev machine with no geo stack installed. Only Shapefile (fiona/geopandas) and PDF (reportlab) can be unavailable, and both degrade gracefully. This means the export path is never fully broken, whatever the environment: the user can always get their coordinates out. That is not an accident of implementation; it is why the three most important formats were built on stdlib.

---

## 9. `gis/` package tree

```
backend/app/gis/
├── __init__.py
├── tiles.py              # §4. Slippy tile math, quadkeys, stitching, geotransforms,
│                         #     pixel<->lonlat. PURE. numpy+stdlib only. No I/O.
│                         #     The foundation — everything depends on it, so it has
│                         #     zero optional deps and exhaustive offline tests.
├── crs.py                # §6. CRS registry, UTM zone selection, cached pyproj
│                         #     Transformers (ALWAYS always_xy=True), osr/NumPy
│                         #     fallbacks. THE ONLY MODULE THAT MAY IMPORT pyproj.
├── raster.py             # §7. Windowed reads, overviews, nodata, CRS detection,
│                         #     detect_georeferencing(), COG conversion.
├── rasterio_shim.py      # §0.1. rasterio | osgeo.gdal | typed-error backend shim.
│                         #     Exists because GDAL is installed and rasterio is not.
├── search_grid.py        # §5. SearchHint, plan_search(), coarse-to-fine staging,
│                         #     chip enumeration with overlap, tile budgeting.
├── geometry.py           # BBox ops, UTM-metre distances/areas/buffers, disc<->bbox,
│                         #     antimeridian handling. shapely-optional (NumPy fallback
│                         #     for the bbox/point ops the hot path needs).
├── accuracy.py           # RMSE/CEP90 in UTM metres, confidence -> radius, error
│                         #     propagation from homography covariance. The module
│                         #     that must never see a degree or a 3857 metre.
├── exif.py               # EXIF GPS extraction (PIL), DOP parsing, radius inflation
│                         #     (§5.1). Pure; PIL is installed.
└── exports/              # §8. One writer per format + FieldNameMapper.
    ├── __init__.py       #     registry, get_writer(), available_formats()
    ├── base.py           #     ExportWriter ABC, ExportContext, ExportBundle
    ├── csv_writer.py     #     stdlib only — always available
    ├── geojson_writer.py #     stdlib only — always available
    ├── shapefile_writer.py #   geopandas/fiona — degrades
    ├── kml_writer.py     #     stdlib xml.etree — always available
    ├── pdf_writer.py     #     reportlab — degrades
    └── fieldmap.py       #     the .dbf 10-char problem (§8.4)
```

**Dependency direction (strict, acyclic):**

```
tiles.py  <-  crs.py  <-  geometry.py  <-  accuracy.py
   ^             ^            ^
   |             |            |
   +--------- raster.py  <- rasterio_shim.py
   |             ^
   +--- search_grid.py    exports/*  ->  (base only; writers never import providers)
   |
imagery/providers/*  ->  gis/tiles.py, gis/raster.py
```

`gis/` **never imports `imagery/`.** The GIS layer is pure geospatial machinery with no knowledge of providers, HTTP, or licensing. Providers import GIS math; the reverse would create a cycle and, worse, would let a tile-math bug fix require reasoning about Bing's ToS. The one shared type (`SatelliteChip`) lives in `imagery/base.py` because it carries `attribution` and `provider_name` — provider concerns — and `gis/exports/base.py` imports it as a *type*, not a behaviour.

---

## 10. Configuration reference

```bash
# --- Provider selection ---------------------------------------------------
IMAGERY_PROVIDER=esri                     # default; keyless; zero-config (§3.2)
IMAGERY_FALLBACK_CHAIN=local_ortho,esri
IMAGERY_STRICT=false                      # true in prod: no silent fallback (§1.6)
ALLOWED_PROVIDERS=                        # empty = all registered; else hard allow-list (§3.4)

# --- Keys (all optional; absence degrades, never crashes) -----------------
MAPBOX_ACCESS_TOKEN=
MAPBOX_CACHE_TTL_S=2592000                # 30d — VERIFY against current ToS
BING_MAPS_KEY=
COPERNICUS_CLIENT_ID=
COPERNICUS_CLIENT_SECRET=
SENTINEL_HUB_INSTANCE_ID=

# --- Google: RESTRICTED. Read docs/architecture/40-imagery.md §2.5 --------
GOOGLE_MAPS_API_KEY=
GOOGLE_TOS_ACKNOWLEDGED=false             # BOTH required. Affirmative act (§2.5).

# --- Local orthophotos (the accuracy path, §2.6) --------------------------
ORTHO_DIR=/data/orthophotos
ORTHO_ATTRIBUTION=Local orthophoto
ORTHO_REINDEX_S=300
ORTHO_BUILD_OVERVIEWS=true
ORTHO_ASSUME_BLACK_NODATA=false           # false on purpose (§7.3)

# --- Cache ----------------------------------------------------------------
TILE_CACHE_BACKEND=redis                  # redis|disk|memory
TILE_CACHE_DIR=/data/tile_cache
TILE_CACHE_TTL_S=2592000
TILE_CACHE_MAX_BYTES=21474836480

# --- Budgets (§5.3) -------------------------------------------------------
MAX_TILES_PER_REQUEST=400
MAX_TILES_PER_JOB=2000
MAX_SEARCH_RADIUS_M=10000
TARGET_GSD_M=0.5
EXIF_RADIUS_INFLATION=3.0
EXIF_MIN_RADIUS_M=250

# --- Politeness -----------------------------------------------------------
IMAGERY_USER_AGENT=LandExplorer/{version} (+https://example.org/landexplorer)
IMAGERY_CONTACT_URL=https://example.org/landexplorer
ESRI_RATE_LIMIT_RPS=8.0
```

---

## 11. Open questions for the architect

1. **Esri terms for commercial deliverables (§2.1, §3.2).** Zero-config default is the right *engineering* call under the brief's constraint. Whether it is a defensible *product* default for paid survey deliverables is a question for the client and their counsel. If the answer is no, the honest move is a first-run interstitial forcing an explicit provider choice — which trades away the zero-config promise. Worth deciding deliberately rather than by default.
2. **Elevation.** GCPs currently export `elevation_m = NULL`. Real GCPs have three coordinates, and terrain relief also introduces horizontal error into the ground-photo↔nadir-satellite homography (the planar assumption breaks on slopes). A DEM provider (Copernicus DEM 30 m, or operator DTMs alongside orthophotos) is a natural fourth interface — out of scope here, but the `SatelliteChip`/`ExportContext` types are shaped to admit it without a rewrite.
3. **Provider georegistration error is unmodelled.** We report homography RMSE, which measures our fit to *the provider's pixels*. It does not include the provider's own georegistration error — unpublished for Esri/Mapbox/Bing, ~10–12 m for Sentinel-2. **Reported accuracy is therefore optimistic for every web provider**, and the PDF says so (§8.6). `local_ortho` is the only path where total error is actually knowable, which is one more reason it heads the default chain.
4. **Rate-limit coordination.** `TokenBucket` is per-worker unless backed by Redis. With N Celery replicas, per-worker limits multiply by N and can breach a provider's terms. The Redis-backed bucket should be the default before any horizontal scaling, not after.
```
