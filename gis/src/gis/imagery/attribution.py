"""Per-provider attribution and terms text. ★ A ToS OBLIGATION, NOT A NICETY.

Attribution is a **licence condition**. ``SatelliteChip.attribution`` and
``SatelliteChip.terms_url`` are required, non-nullable fields precisely so that pixels
cannot travel through this system without their credit attached — the type system makes
the obligation unforgeable rather than reviewer-dependent.

This module is the single home of the static strings. Two providers' attribution is
**dynamic** and must not be read from here as if it were final:

* **Bing** derives per-region vendor strings from its Metadata API's ``coverageAreas``,
  filtered to the current bbox and zoom. A hardcoded Bing string is **non-compliant**.
  The constant here is only the invariant ``(c) {year} Microsoft Corporation`` prefix.
* **Local orthophotos** carry the operator's own text (``LE_LOCAL_ORTHO_ATTRIBUTION``).

Every string was transcribed from the provider's published terms; ``REVIEWED_ON`` records
when, because these expire. ``docs/legal/imagery-terms.md`` is the authoritative record
and this module is its executable half.
"""

from __future__ import annotations

import datetime as _dt
from typing import Final

__all__ = [
    "ATTRIBUTION",
    "ESRI_KEYLESS_CAVEAT",
    "REVIEWED_ON",
    "TERMS_URL",
    "attribution_for",
    "bing_attribution",
    "terms_url_for",
]

REVIEWED_ON: Final[str] = "2026-07-17"
"""When these strings were last checked against the providers' published terms.

★ Terms change. A stale attribution string is a compliance defect, not a cosmetic one.
"""

ATTRIBUTION: Final[dict[str, str]] = {
    "esri_world_imagery": (
        "Esri, Maxar, Earthstar Geographics, and the GIS User Community"
    ),
    "local_orthophoto": "Local orthophoto",
    "fixture": "LandExplorer synthetic fixture imagery (not real imagery)",
    "mapbox_satellite": "© Mapbox © Maxar",
    "bing_aerial": "© Microsoft Corporation",
    "sentinel_copernicus": "Contains modified Copernicus Sentinel data",
    "google_maps_static": "Map data © Google",
    "google_map_tiles": "Map data © Google",
}
"""Plain-text credit per provider registry key. ★ MUST be rendered wherever pixels are.

``bing_aerial`` and ``sentinel_copernicus`` are **prefixes**: see ``bing_attribution()``
and the year-stamping in ``attribution_for()``.
"""

TERMS_URL: Final[dict[str, str]] = {
    "esri_world_imagery": "https://www.esri.com/en-us/legal/terms/full-master-agreement",
    "local_orthophoto": "",
    "fixture": "",
    "mapbox_satellite": "https://www.mapbox.com/legal/tos",
    "bing_aerial": "https://www.microsoft.com/maps/product/terms.html",
    "sentinel_copernicus": "https://dataspace.copernicus.eu/terms-and-conditions",
    "google_maps_static": "https://cloud.google.com/maps-platform/terms",
    "google_map_tiles": "https://cloud.google.com/maps-platform/terms",
}
"""Canonical ToS URL per provider. Surfaced in the UI and in every PDF export.

``local_orthophoto`` and ``fixture`` are empty by design: the operator's own imagery is
governed by the operator's own rights, and the fixture provider's pixels are synthetic and
carry no third-party licence at all. Both are the only honest answers; inventing a URL
would be worse than an empty one.
"""

ESRI_KEYLESS_CAVEAT: Final[str] = (
    "Esri World Imagery is the zero-config default because it is keyless, not because it "
    "is licensed for your use. Reachable is not licensed. Commercial redistribution, bulk "
    "caching, and use as a source for derived survey deliverables are exactly the uses "
    "most likely to exceed the terms - and a derived survey deliverable is precisely what "
    "LandExplorer produces. Verify against Esri's terms before shipping paid work, or use "
    "a local orthophoto."
)
"""★ Repeated in the README, the first-run log banner, the UI provider picker and every
PDF export. The repetition is deliberate: the default satisfies the zero-config mandate,
and this product refuses to let that read as a recommendation.
"""


def _current_year() -> int:
    """Return the current year, for the providers whose credit is year-stamped."""
    return _dt.datetime.now(tz=_dt.UTC).year


def attribution_for(provider: str, *, year: int | None = None) -> str:
    """Return the static attribution text for a provider.

    ★ For ``bing_aerial`` this returns only the invariant prefix. Bing's compliant string
    is per-region and comes from its metadata handshake — use ``bing_attribution()``.

    Args:
        provider: A registry key from ``gis.imagery.base.PROVIDER_NAMES``.
        year: Year to stamp where the provider's credit requires one. Defaults to now.

    Returns:
        The attribution text, or an empty string for an unknown provider. ★ Never raises:
        this is called on the pixel path, and a KeyError there would take down a tile
        request over a string lookup.
    """
    text = ATTRIBUTION.get(provider, "")
    if not text:
        return ""
    stamp = _current_year() if year is None else year
    if provider == "bing_aerial":
        return f"© {stamp} Microsoft Corporation"
    if provider in {"google_maps_static", "google_map_tiles"}:
        return f"Map data © {stamp} Google"
    if provider == "sentinel_copernicus":
        return f"Contains modified Copernicus Sentinel data {stamp}"
    return text


def terms_url_for(provider: str) -> str:
    """Return a provider's canonical ToS URL.

    Args:
        provider: A registry key.

    Returns:
        The URL, or an empty string when the provider has none (local orthophotos, the
        fixture provider) or is unknown. Never raises.
    """
    return TERMS_URL.get(provider, "")


def bing_attribution(vendor_strings: "list[str] | tuple[str, ...]", *, year: int | None = None) -> str:
    """Compose Bing's per-region attribution.

    ★ Static Bing attribution is NON-COMPLIANT. The terms require displaying the vendor
    credits that the Metadata API returns for the **specific area and zoom being viewed**,
    which is why ``BingAerialProvider`` performs the metadata handshake and filters
    ``coverageAreas`` per request rather than hardcoding a URL and a string.

    Args:
        vendor_strings: The ``ImageryProviders`` attribution strings that apply to the
            current bbox and zoom, already filtered.
        year: Year for the Microsoft credit. Defaults to now.

    Returns:
        The Microsoft credit, followed by any vendor credits. Never raises.
    """
    stamp = _current_year() if year is None else year
    base = f"© {stamp} Microsoft Corporation"
    vendors = [str(v).strip() for v in vendor_strings if str(v).strip()]
    if not vendors:
        return base
    return f"{base} - {' - '.join(dict.fromkeys(vendors))}"
