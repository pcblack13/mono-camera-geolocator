"""``gis.imagery`` — ★ THE LEGAL BOUNDARY OF THE PRODUCT.

Every satellite pixel in LandExplorer enters through this package, behind one
interchangeable interface (``ImageryProvider``). Swapping a provider must not change
anything else in the system — that is what ADR-002 buys, and it is why the legal
constraints below are expressible as *capability flags* rather than as rules people have to
remember.

# ★ THE CLIENT'S HARD CONSTRAINT. The desktop globe application from Google cannot legally
#   or technically be searched or processed via its app or API, and this project honours
#   that without qualification. Legally: its terms prohibit the automated access, bulk
#   download and derivative use this pipeline requires, and extracting features from that
#   imagery to export survey coordinates is derivative use outside the permitted context.
#   Technically: it is not a tile service with a stable public contract - it is a client
#   application against undocumented internal endpoints with no versioning guarantee and
#   active anti-automation, so an integration built on it would break silently, mid-job, in
#   production, producing WRONG COORDINATES rather than clean errors. Both reasons are
#   independently disqualifying. Neither is worked around: there is no provider, no
#   scraper, no "advanced" flag and no documented workaround, and the imagery_provider PG
#   enum has no member for it - it is UNREPRESENTABLE IN THE TYPE SYSTEM. Requests to add
#   one should be closed by pointing at docs/legal/imagery-terms.md.
#   `providers/google_static.py` is a DIFFERENT service (Google Maps Platform - a
#   documented commercial API with a key and a contract). It is still not a default, still
#   capability-blocked from caching and derivative export, and still requires an
#   affirmative acknowledgement. Its presence is not a partial concession.

★ This module stays import-cheap and total. Importing it must not touch the network, read a
key, or bind an optional dependency — the registry constructs every provider merely to ask
each one whether it is configured.
"""

from __future__ import annotations

from gis.imagery.attribution import ESRI_KEYLESS_CAVEAT, attribution_for, terms_url_for
from gis.imagery.base import (
    PROVIDER_NAMES,
    ImageryProvider,
    ProviderCapabilities,
    ProviderHealth,
    TileProviderMixin,
)
from gis.imagery.providers import OFFLINE_PROVIDERS, PROVIDERS
from gis.imagery.registry import (
    ProviderListing,
    ProviderRegistry,
    default_registry,
    get_provider,
    provider_allows_caching,
)

__all__ = [
    "ESRI_KEYLESS_CAVEAT",
    "OFFLINE_PROVIDERS",
    "PROVIDERS",
    "PROVIDER_NAMES",
    "ImageryProvider",
    "ProviderCapabilities",
    "ProviderHealth",
    "ProviderListing",
    "ProviderRegistry",
    "TileProviderMixin",
    "attribution_for",
    "default_registry",
    "get_provider",
    "provider_allows_caching",
    "terms_url_for",
]
