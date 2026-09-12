# MonoCameraGeoLocator — Mapbox Satellite, Local Cache & Offline Surveying

## 1. What MonoCameraGeoLocator will have after the implementation

After completing the Mapbox, caching, and offline-workflow implementation, **MonoCameraGeoLocator** will have a complete reference-imagery subsystem designed for image geolocation, landmark selection, GCP workflows, and field surveying.

The main capability will be:

> **Use Mapbox Satellite imagery online, automatically cache imagery locally, prepare selected geographic areas for offline use, and continue using the cached imagery when the computer has no Internet connection.**

The system will not require a separate offline map engine. The same tile-proxy and cache architecture will be used both online and offline.

---

# 2. Overall workflow

The application will support two main workflows.

## Online workflow

```text
                    MonoCameraGeoLocator
                            |
                            v
                       Leaflet Map
                            |
                            v
                    FastAPI Tile Proxy
                            |
                            v
                     ImageryService
                            |
                  +---------+---------+
                  |                   |
              CACHE HIT           CACHE MISS
                  |                   |
                  v                   v
           Local Tile Cache     Mapbox Satellite
                                      |
                                      v
                                 Rate Limiter
                                      |
                                      v
                                  Mapbox API
                                      |
                                      v
                                 Store Tile
                                      |
                                      v
                                 Return Tile
```

When a tile has already been downloaded:

```text
Leaflet
   |
   v
MonoCameraGeoLocator
   |
   v
Local Cache
   |
   v
Tile returned immediately
```

No new upstream imagery request is necessary for that cached tile.

---

# 3. Offline surveying workflow

MonoCameraGeoLocator will allow the user to prepare an area before going to the field.

```text
Create/Open Project
        |
        v
Open Mapbox Satellite
        |
        v
Draw AOI
        |
        v
Select Zoom Range
        |
        v
Calculate Required Tiles
        |
        v
Calculate Cached Tiles
        |
        v
Calculate Missing Tiles
        |
        v
Estimate Storage
        |
        v
Estimate Upstream Requests
        |
        v
Download Missing Tiles
        |
        v
Validate Download
        |
        v
Create Offline Manifest
        |
        v
Go to Field
        |
        v
Disable Internet
        |
        v
Open MonoCameraGeoLocator
        |
        v
Use Local Mapbox Imagery
```

This means the user can prepare a geographic area while online and then continue working with that area without requiring Internet access.

---

# 4. Mapbox Satellite inside the application

Mapbox Satellite will be integrated as an imagery provider called:

```text
mapbox_satellite
```

The provider will fit into the application's existing provider architecture.

Conceptually:

```text
ProviderRegistry
       |
       +-- local_orthophoto
       |
       +-- mapbox_satellite
       |
       +-- google_map_tiles
       |
       +-- future providers
```

This means Mapbox is not hard-coded into the entire application.

It is one provider implementation that can be selected by the imagery system.

---

# 5. Mapbox tile proxy

The frontend will normally request imagery from MonoCameraGeoLocator rather than directly constructing Mapbox requests.

Example:

```text
/api/v1/imagery/tiles/mapbox_satellite/{z}/{x}/{y}
```

The request flow is:

```text
Leaflet
   |
   v
MonoCameraGeoLocator API
   |
   v
ImageryService
   |
   v
Mapbox provider
   |
   v
Mapbox
```

This provides a central location for:

- caching
- rate limiting
- error handling
- provider selection
- offline operation
- usage statistics
- imagery metadata

---

# 6. Persistent local tile cache

MonoCameraGeoLocator will have a persistent tile cache on disk.

Conceptually:

```text
data/
└── tile_cache/
    └── mapbox_satellite/
        └── satellite/
            └── z/
                └── x/
                    └── y.tile
```

The exact directory structure will follow the implementation already present in the project.

The important behavior is that cached imagery survives application restarts.

For example:

```text
Day 1:
Download tile
       |
       v
Save tile to disk

Close application

Day 2:
Open application
       |
       v
Tile is still available
```

---

# 7. Read-through caching

The cache will use a read-through model.

## First request

```text
Request tile
    |
    v
Cache lookup
    |
    v
MISS
    |
    v
Mapbox request
    |
    v
Receive tile
    |
    v
Save tile
    |
    v
Return tile
```

## Second request

```text
Request same tile
    |
    v
Cache lookup
    |
    v
HIT
    |
    v
Return local tile
```

The second request does not need to fetch the same tile again.

This is one of the most important parts of the system because repeated map navigation over the same area becomes much faster and reduces unnecessary upstream requests.

---

# 8. Browser caching

The browser can also cache recently requested tiles using HTTP caching.

The architecture therefore has multiple levels:

```text
Leaflet / Browser Cache
        |
        v
MonoCameraGeoLocator Tile Cache
        |
        v
Mapbox
```

This provides fast access at both the browser and application levels.

---

# 9. Provider-specific cache policy

Mapbox will have its own configurable cache policy.

The application will support configuration such as:

```text
LE_MAPBOX_CACHE_TTL_SECONDS
```

The important improvement is that the configured Mapbox cache TTL will actually be used by the cache implementation.

The cache will be able to determine:

```text
Tile
 |
 +-- valid cache entry
 |
 +-- expired cache entry
 |
 +-- missing cache entry
```

Expired tiles can be removed and downloaded again when needed.

---

# 10. Strong cache keys

Cached tiles will be uniquely identified using relevant imagery parameters.

The cache identity can include:

```text
provider
style
variant
z
x
y
tile size
scale
format
quality
configuration version
```

This prevents an old tile configuration from accidentally being returned after the imagery configuration changes.

For example, changing from:

```text
512px @2x
```

to another tile representation will not accidentally reuse an incompatible cached file.

---

# 11. Mapbox @2x / 512px imagery

The existing integration uses Mapbox imagery at approximately:

```text
512px
@2x
```

The frontend will correctly account for the larger tile size.

The implementation will verify the relationship between:

- Leaflet tile size
- zoom offset
- XYZ coordinates
- Mapbox zoom
- geographic coverage

This is important because:

> A 512px tile contains more pixels, but it does not automatically mean that the underlying satellite imagery has twice the geographic resolution.

The application will keep this distinction clear.

---

# 12. Offline Area Manager

MonoCameraGeoLocator will have an interface for preparing offline imagery.

Conceptually:

```text
+------------------------------------------+
|             OFFLINE AREA                 |
+------------------------------------------+
| Provider: Mapbox Satellite               |
|                                          |
| Zoom: 15 → 19                            |
|                                          |
|              [ MAP / AOI ]               |
|                                          |
| Total tiles:        8,420                |
| Already cached:     3,120                |
| New tiles:          5,300                |
| Estimated storage:  1.7 GB               |
| Estimated requests: 5,300                |
|                                          |
|              [ START DOWNLOAD ]          |
+------------------------------------------+
```

The user will draw an area on the map and choose the required zoom range.

---

# 13. AOI-based tile calculation

The application will calculate the actual XYZ tiles intersecting the selected AOI.

For example:

```text
AOI
 |
 +-- Zoom 15
 |     +-- tile x/y
 |
 +-- Zoom 16
 |     +-- tile x/y
 |
 +-- Zoom 17
 |     +-- tile x/y
 |
 +-- Zoom 18
 |     +-- tile x/y
 |
 +-- Zoom 19
       +-- tile x/y
```

The system will determine:

```text
total_tiles
cached_tiles
missing_tiles
new_tiles
```

This is better than estimating the number of tiles only from geographic area.

---

# 14. Storage estimation

Before downloading an offline area, MonoCameraGeoLocator will estimate the required disk space.

Example:

```text
New tiles:
5,300

Average tile size:
~320 KB

Estimated storage:
~1.7 GB
```

The system can use previously downloaded tiles to improve the average tile-size estimate.

After downloading, the application can display the actual storage used.

---

# 15. Upstream request estimation

Before starting a large offline download, the user will see how many new tiles must be obtained.

Example:

```text
Total tiles:       8,420
Already cached:    3,120
New tiles:         5,300
```

Therefore the pre-cache operation expects approximately:

```text
5,300 new tile requests
```

This gives the user visibility before starting a large download.

---

# 16. Pre-cache engine

The offline downloader will be implemented as a reusable service.

Conceptually:

```text
OfflineCacheService
```

It will handle:

- AOI tile calculation
- cache lookup
- missing-tile detection
- downloading
- bounded concurrency
- retry handling
- progress
- pause/cancel
- resume
- validation
- manifest creation

The user will not need to manually download individual tiles.

The workflow will simply be:

```text
Draw area
    |
    v
Select zoom
    |
    v
Click Download
    |
    v
MonoCameraGeoLocator handles the tiles
```

---

# 17. Download progress

The user will see progress while preparing an offline area.

Example:

```text
Downloading Mapbox Satellite

5,100 / 5,300

96%

Completed: 5,100
Failed:       3
Remaining: 197

[ PAUSE ] [ CANCEL ]
```

The operation should support:

- progress
- pause
- cancellation
- resume
- retry of failed tiles

---

# 18. Offline manifest

After downloading an area, MonoCameraGeoLocator will create an offline manifest.

The manifest records information such as:

```text
Project
Provider
AOI
Zoom range
Tile count
Completed tiles
Missing tiles
Tile configuration
Creation time
Expiration information
Cache version
```

Conceptually:

```json
{
    "project_id": "...",
    "provider": "mapbox_satellite",
    "zoom_min": 15,
    "zoom_max": 19,
    "tile_count": 8420,
    "completed_tiles": 8420,
    "missing_tiles": 0
}
```

This gives the application a clear description of what offline imagery is available.

---

# 19. Offline mode

When the computer has no Internet connection:

```text
Leaflet
   |
   v
MonoCameraGeoLocator
   |
   v
Local Tile Cache
   |
   v
Return cached tile
```

If a tile exists locally, the application continues to display it.

If it does not exist:

```text
Tile not available in offline cache
```

The application should not repeatedly try to contact Mapbox for every missing tile while offline.

---

# 20. Offline coverage

MonoCameraGeoLocator will be able to determine how much of the requested AOI has actually been cached.

Example:

```text
Offline Coverage

AOI: 12.4 km²
Zoom: 15–19

Available: 92%
Missing:     8%
```

Where practical, the UI can also display cached and uncached regions visually.

This is especially useful before going into the field.

---

# 21. Cache maintenance

The application will maintain the cache automatically.

Maintenance can include:

```text
Expired tiles
    |
    v
Remove

Corrupted tiles
    |
    v
Remove

Temporary files
    |
    v
Remove

Cache exceeds maximum size
    |
    v
Evict old entries
```

The cleanup process will not run expensive full-cache operations on every map request.

---

# 22. Cache size management

MonoCameraGeoLocator will support a configurable maximum cache size.

For example:

```text
LE_IMAGERY_TILE_CACHE_MAX_BYTES
```

If the cache becomes too large, older entries can be removed according to the cache policy.

This prevents the imagery cache from consuming the entire disk indefinitely.

---

# 23. Negative caching

If a location genuinely has no available imagery, the application can temporarily remember that result.

Example:

```text
Request tile
    |
    v
No imagery available
    |
    v
Negative cache
```

A later request can avoid repeating the same unavailable lookup until the negative-cache entry expires.

Temporary failures such as rate limiting or server errors should not be treated as permanent "no imagery" results.

---

# 24. Rate limiting and retries

Mapbox requests will pass through a configurable rate limiter.

Example configuration:

```text
LE_MAPBOX_RATE_LIMIT_RPS
```

The system will support:

- bounded concurrency
- token-bucket style limiting
- retry with backoff
- jitter
- Retry-After handling
- controlled handling of HTTP 429

This is especially important during large offline pre-cache operations.

---

# 25. Request limits

MonoCameraGeoLocator will be able to impose application-level limits on large pre-cache operations.

Examples:

```text
LE_MAPBOX_MAX_TILE_REQUESTS_PER_OPERATION

LE_MAPBOX_MAX_PREFETCH_TILES

LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY
```

Before starting a download, the application can determine whether the requested operation exceeds the configured limit.

---

# 26. Imagery usage statistics

MonoCameraGeoLocator will maintain application-level imagery statistics.

Examples:

```text
Mapbox upstream requests
Cache hits
Cache misses
Negative-cache hits
HTTP 429 responses
Failed requests
```

The UI can show information such as:

```text
Mapbox Imagery Usage

Upstream requests: 12,430
Cache hits:        48,210
Cache misses:      12,430
Cache hit ratio:   79.5%
```

These are **MonoCameraGeoLocator application statistics**, not a replacement for the provider's official usage/billing information.

---

# 27. GCP and landmark integration

The cached Mapbox imagery will be usable as reference imagery for MonoCameraGeoLocator's geolocation and GCP workflows.

When a user selects a reference point, the application can associate imagery information with the GCP.

For example:

```text
GCP
 |
 +-- image pixel coordinates
 +-- longitude
 +-- latitude
 +-- elevation
 +-- imagery provider
 +-- imagery variant
 +-- zoom
 +-- tile coordinates
 +-- imagery date status
 +-- GSD status
 +-- accuracy status
 +-- cache timestamp
 +-- confidence
```

This provides traceability for the reference imagery used during the GCP workflow.

---

# 28. Imagery date information

MonoCameraGeoLocator will not invent satellite acquisition dates.

If a reliable imagery date is unavailable:

```text
Imagery acquisition date:
Unknown
```

The GCP/reference metadata can record:

```text
imagery_date_known = false
```

This is important for professional workflows where the date of the reference imagery may affect interpretation.

---

# 29. GSD and accuracy information

The application will distinguish between:

```text
Known
Estimated
Unknown
Vendor-certified
```

For example:

```text
GSD:
Estimated

Georeferencing accuracy:
Estimated
```

An estimated value should not be presented as a guaranteed survey accuracy.

This is especially important because MonoCameraGeoLocator is intended for professional geolocation/GCP workflows.

---

# 30. Native resolution awareness

The application will distinguish between:

```text
Maximum service zoom
```

and:

```text
Known native imagery resolution
```

For example, even if the service allows:

```text
Zoom 22
```

the source imagery may not contain native detail at that level.

Therefore the application can warn:

```text
Imagery may be upsampled beyond native source resolution.
```

This helps prevent users from assuming that extreme zoom automatically provides additional real-world detail.

---

# 31. Project data remains separate from imagery cache

Survey data and imagery cache will remain logically separate.

Example:

```text
Project
├── project.json
├── survey_images/
├── gcp/
├── results/
└── metadata/

Imagery cache
└── tile_cache/
    └── mapbox_satellite/
```

The offline manifest can connect the project to the relevant cached imagery.

This keeps the survey dataset organized while allowing the imagery cache to be managed independently.

---

# 32. Provider architecture

The final application will retain a provider abstraction.

Conceptually:

```text
                 ImageryService
                       |
                       v
                ProviderRegistry
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
 Local Orthophoto   Mapbox         Other Provider
                    Satellite
```

This means the application can later support additional imagery providers without redesigning the entire map system.

---

# 33. Security

The Mapbox access token will remain on the backend side of the application architecture.

The token should not be placed unnecessarily into:

- cache filenames
- cache keys
- offline manifests
- normal logs
- error messages

The frontend should normally request the MonoCameraGeoLocator tile proxy.

---

# 34. What the user will see in the final application

From the user's perspective, the final workflow will look approximately like this:

## Map screen

```text
+------------------------------------------------------+
| MonoCameraGeoLocator                                 |
+------------------------------------------------------+
| Imagery: [ Mapbox Satellite ▼ ]                     |
|                                                      |
|                    MAP                               |
|                                                      |
|             Satellite Imagery                        |
|                                                      |
|                                  [GCP Tool]          |
|                                  [Landmark Tool]     |
+------------------------------------------------------+
```

The user can navigate the satellite map normally.

---

# 35. Offline preparation screen

The application will provide an offline preparation workflow:

```text
+------------------------------------------------------+
|              OFFLINE AREA MANAGER                    |
+------------------------------------------------------+
| Provider: Mapbox Satellite                           |
|                                                      |
| Zoom: [15] → [19]                                    |
|                                                      |
| Draw an AOI on the map                               |
|                                                      |
| Total tiles:             8,420                       |
| Cached tiles:            3,120                       |
| New tiles:               5,300                       |
| Estimated storage:       1.7 GB                      |
| Estimated requests:      5,300                       |
|                                                      |
|                 [ DOWNLOAD ]                          |
+------------------------------------------------------+
```

---

# 36. Download screen

During downloading:

```text
+------------------------------------------------------+
|              DOWNLOADING IMAGERY                    |
+------------------------------------------------------+

Mapbox Satellite

5,100 / 5,300

96%

Downloaded:       5,100
Failed:               3
Remaining:          197

Storage:
1.64 GB

                    [ PAUSE ]
                    [ CANCEL ]
+------------------------------------------------------+
```

---

# 37. Offline status

Once the area is prepared:

```text
+------------------------------------------------------+
|                OFFLINE AREA                         |
+------------------------------------------------------+

Provider:
Mapbox Satellite

AOI:
Survey Area 01

Zoom:
15–19

Coverage:
100%

Tiles:
8,420 / 8,420

Storage:
2.1 GB

Status:
READY FOR OFFLINE USE

Created:
2026-08-07
```

---

# 38. Field workflow

In the field:

```text
Internet:
OFFLINE

Project:
Survey Area 01

Offline imagery:
AVAILABLE

Coverage:
100%

Provider:
Mapbox Satellite
```

The user can then:

```text
Open map
   |
   v
Navigate cached satellite imagery
   |
   v
Open uploaded image
   |
   v
Identify landmark
   |
   v
Select corresponding reference point
   |
   v
Create/use GCP
   |
   v
Continue geolocation workflow
```

No Internet connection is required for tiles that were successfully cached beforehand.

---

# 39. Performance behavior

The expected behavior will be:

### First visit to an area

```text
Map
 ↓
Cache miss
 ↓
Mapbox
 ↓
Cache tile
 ↓
Display
```

### Returning to the same area

```text
Map
 ↓
Cache hit
 ↓
Display immediately
```

### Offline

```text
Map
 ↓
Cache hit
 ↓
Display
```

### Offline + tile was never cached

```text
Map
 ↓
Cache miss
 ↓
"Tile unavailable in offline cache"
```

---

# 40. What MonoCameraGeoLocator will ultimately provide

After these implementations, MonoCameraGeoLocator will have a complete imagery workflow consisting of:

```text
                MONOCAMERAGEOLOCATOR
                         |
       +-----------------+------------------+
       |                 |                  |
       v                 v                  v
   Mapbox Satellite   Local Imagery      Other Providers
       |
       v
   Tile Proxy
       |
       v
   Local Cache
       |
       +----------------------------+
       |                            |
       v                            v
 Online Map                  Offline Map
       |                            |
       v                            v
 GCP / Landmark             GCP / Landmark
 Workflow                    Workflow
```

The major capabilities will be:

- **Mapbox Satellite reference imagery**
- **persistent local tile cache**
- **automatic read-through caching**
- **AOI-based offline downloading**
- **zoom-level selection**
- **tile-count calculation**
- **storage estimation**
- **request estimation**
- **download progress**
- **pause/cancel/resume**
- **offline manifests**
- **offline coverage verification**
- **cache expiration**
- **cache-size management**
- **negative caching**
- **rate limiting**
- **retry handling**
- **usage statistics**
- **offline map operation**
- **GCP/reference imagery metadata**
- **imagery-date awareness**
- **GSD/accuracy status**
- **native-resolution awareness**
- **provider abstraction**
- **desktop-friendly persistent storage**

---

# 41. The most important result

The most important result is that **online and offline maps use the same imagery pipeline**.

```text
                    LEAFLET
                       |
                       v
              TILE PROXY / API
                       |
                       v
                 LOCAL CACHE
                  /       \
                 /         \
             HIT            MISS
             |                |
             v                v
        RETURN TILE       MAPBOX
                              |
                              v
                         STORE TILE
                              |
                              v
                         RETURN TILE
```

Therefore, the application does not need two completely different map systems.

The same map can operate in both modes:

```text
ONLINE
------
Mapbox Satellite + Local Cache


OFFLINE
-------
Local Cache only
```

This is the core architecture that makes the system practical for field surveying.

---

# 42. Final expected state

After the implementation is complete, the intended user experience is:

```text
1. Open MonoCameraGeoLocator

2. Open a project

3. Select Mapbox Satellite

4. View satellite imagery

5. Navigate normally

6. Select an AOI

7. Choose required zoom levels

8. See:
      - number of tiles
      - cached tiles
      - missing tiles
      - estimated storage
      - estimated requests

9. Download the AOI

10. Verify:
      - all required tiles downloaded
      - coverage
      - storage
      - offline manifest

11. Go to the field

12. Disable Internet

13. Open MonoCameraGeoLocator

14. Open the project

15. Open the cached satellite map

16. Continue navigating the prepared area

17. Use landmarks/GCP tools

18. Continue the geolocation/survey workflow
```

That is the intended end state of the Mapbox Satellite + local caching + offline subsystem in **MonoCameraGeoLocator**.
