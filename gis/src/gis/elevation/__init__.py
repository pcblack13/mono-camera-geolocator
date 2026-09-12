"""The elevation provider registry (§4.27) — the FOURTH provider interface.

★ EXPLICIT registration. No entry-point autodiscovery: a provider that appears because a
package happened to be installed is a provider nobody reviewed.

Registration is eager and safe. Every provider's ``__init__`` is guaranteed not to touch
the network, not to read a key and not to raise, so importing this module costs nothing
and cannot fail — which is what lets ``GET /capabilities`` report an unconfigured provider
instead of 500ing because it could not construct one.

The default is ``none`` (``NullElevationProvider``): keyless, offline, terminal, and
honest about having no data.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from gis.elevation.base import ElevationProvider, ElevationSample
from gis.elevation.copernicus_dem import CopernicusDemProvider
from gis.elevation.dem_run import DemRunProvider
from gis.elevation.local_dem import LocalDemProvider
from gis.elevation.null import NullElevationProvider
from gis.errors import UnknownProviderError

__all__ = [
    "ELEVATION_PROVIDERS",
    "ELEVATION_PROVIDER_NAMES",
    "CopernicusDemProvider",
    "DemRunProvider",
    "ElevationProvider",
    "ElevationSample",
    "LocalDemProvider",
    "NullElevationProvider",
    "get_elevation_provider",
]

_log = logging.getLogger("gis.elevation")

ELEVATION_PROVIDERS: Final[Mapping[str, type[ElevationProvider]]] = {
    NullElevationProvider.name: NullElevationProvider,
    # ★ The DEM prepared on the DEM page: the surface the surveyor cropped, reprojected
    #   and inspected IS the surface their control points are measured against.
    DemRunProvider.name: DemRunProvider,
    LocalDemProvider.name: LocalDemProvider,
    CopernicusDemProvider.name: CopernicusDemProvider,
}
"""Every registered elevation provider, by registry key."""

ELEVATION_PROVIDER_NAMES: Final[tuple[str, ...]] = tuple(ELEVATION_PROVIDERS)
"""★ THE CANONICAL ELEVATION PROVIDER NAME TUPLE, owned by the layer that owns providers.

``gis`` may not import ``sqlalchemy``, so ``gis`` tests against THIS and a backend test
pins it to the ``elevation_source`` enum. The dependency points the way it already points.
"""

DEFAULT_ELEVATION_PROVIDER: Final[str] = NullElevationProvider.name
"""``LE_ELEVATION_PROVIDER``'s default: keyless, offline, terminal, honest."""


def get_elevation_provider(name: str | None = None, **kwargs: object) -> ElevationProvider:
    """Construct an elevation provider by registry key.

    ★ Never falls back silently. An unknown name is a typo'd config and fails LOUD; an
    unconfigured-but-known provider is constructed and reports ``is_configured() ==
    False``, which is the caller's cue to warn and degrade to ``none``. The distinction
    matters: a typo should not quietly resolve to "no elevation", because that looks
    exactly like a correct configuration of the default.

    Args:
        name: A key from ``ELEVATION_PROVIDERS``. None or empty selects the default.
        **kwargs: Passed to the provider's constructor.

    Returns:
        The constructed provider. Construction never raises for missing config.

    Raises:
        UnknownProviderError: If ``name`` is not registered.
    """
    key = (name or DEFAULT_ELEVATION_PROVIDER).strip()
    provider_cls = ELEVATION_PROVIDERS.get(key)
    if provider_cls is None:
        raise UnknownProviderError(
            f"unknown elevation provider {key!r}; registered: "
            f"{', '.join(ELEVATION_PROVIDER_NAMES)}",
            provider=key,
        )
    return provider_cls(**kwargs)  # type: ignore[arg-type]
