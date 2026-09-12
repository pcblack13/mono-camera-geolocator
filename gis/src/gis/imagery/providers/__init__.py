"""★ EXPLICIT PROVIDER REGISTRATION. No entry-point autodiscovery.

For a product whose central legal constraint is **which imagery sources are permitted**, a
plugin mechanism that lets an unreviewed provider appear **by being pip-installed** is a
liability. The set of providers is a reviewed, auditable list in version control — this
file. Adding a row here is a code review; a plugin hook would not be.

★ **Importing this module is EAGER and must stay cheap and total.** Every provider class is
imported here, and the registry constructs every one of them just to ask each whether it is
configured. That is only safe because of two invariants the contract test enforces:

1. Every ``__init__`` is free — no network, no raster read, no key requirement, no raise.
2. Every optional dependency binds at CALL time (§11.3). ``httpx`` is in ``gis``'s base
   deps *and* is call-time bound in ``gis.imagery.http`` — so this import succeeds, and
   every provider's ``name`` / ``is_configured()`` / ``capabilities()`` works, on a machine
   with no httpx. Only an actual fetch raises.

Without those, ``cd gis && pytest`` would die at COLLECTION, before a single test ran.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from gis.imagery.base import PROVIDER_NAMES, ImageryProvider
from gis.imagery.providers.bing import BingAerialProvider
from gis.imagery.providers.esri import EsriWorldImageryProvider
from gis.imagery.providers.fixture import FixtureProvider
from gis.imagery.providers.google_map_tiles import GoogleMapTilesProvider
from gis.imagery.providers.google_static import GoogleStaticProvider
from gis.imagery.providers.local_ortho import LocalOrthophotoProvider
from gis.imagery.providers.mapbox import MapboxSatelliteProvider
from gis.imagery.providers.sentinel import SentinelCopernicusProvider

__all__ = [
    "OFFLINE_PROVIDERS",
    "PROVIDERS",
    "BingAerialProvider",
    "EsriWorldImageryProvider",
    "FixtureProvider",
    "GoogleMapTilesProvider",
    "GoogleStaticProvider",
    "ImageryProvider",
    "LocalOrthophotoProvider",
    "MapboxSatelliteProvider",
    "SentinelCopernicusProvider",
]

PROVIDERS: Final[Mapping[str, type[ImageryProvider]]] = {
    "esri_world_imagery": EsriWorldImageryProvider,
    "local_orthophoto": LocalOrthophotoProvider,
    "fixture": FixtureProvider,
    "mapbox_satellite": MapboxSatelliteProvider,
    "bing_aerial": BingAerialProvider,
    "sentinel_copernicus": SentinelCopernicusProvider,
    "google_maps_static": GoogleStaticProvider,
    "google_map_tiles": GoogleMapTilesProvider,
}
"""★ THE REVIEWED, AUDITABLE LIST. Registry key -> provider class.

The keys are the DB enum's values (which is what ``ImageryProvider.name`` must return and
what is persisted and put on the wire); the CLASS names keep the readable form. The class
name is not the registry key.

# Note what is not here, and never will be: the excluded desktop globe application. It has
# no entry, no class, no flag and no scaffolding. An absence, not a disabled feature.
"""

OFFLINE_PROVIDERS: Final[tuple[str, ...]] = ("local_orthophoto", "fixture")
"""The only providers resolvable under ``LE_IMAGERY_OFFLINE=true``.

★ Air-gapped mode is a **first-class supported mode**, not a test flag. ``fixture`` is
listed here because ``LE_IMAGERY_OFFLINE`` needs a provider that works on a fresh clone
with nothing mounted — ``local_orthophoto`` self-skips when ``./data/orthophotos`` is empty,
which it ships as.
"""


def _assert_names_agree() -> None:
    """Fail loudly at import if the registry and ``PROVIDER_NAMES`` disagree.

    ★ Import-time, not test-time, and deliberately so. ``PROVIDER_NAMES`` is what a BACKEND
    test pins to the ``imagery_provider`` PG enum, so a provider registered here but missing
    from that tuple would be a provider whose name **cannot be persisted** — an
    integration-time failure, in a Celery worker, after a job has already run. Two lines
    here turn it into an import error.

    Raises:
        RuntimeError: If the two sets differ.
    """
    registered = set(PROVIDERS)
    canonical = set(PROVIDER_NAMES)
    if registered != canonical:
        missing = canonical - registered
        extra = registered - canonical
        raise RuntimeError(
            "gis.imagery.providers.PROVIDERS and gis.imagery.base.PROVIDER_NAMES disagree. "
            f"Registered but not canonical: {sorted(extra)}. "
            f"Canonical but not registered: {sorted(missing)}. "
            "A provider's name must appear in PROVIDER_NAMES, backend enums.ImageryProvider, "
            "the wire enum and migration 0002 - see docs/guides/adding-a-provider.md."
        )


_assert_names_agree()
